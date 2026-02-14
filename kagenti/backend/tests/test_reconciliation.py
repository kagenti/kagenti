# Copyright 2025 IBM Corp.
# Licensed under the Apache License, Version 2.0

"""
Unit tests for the build reconciliation loop.

Tests cover:
- _workload_exists() checks for Deployment, StatefulSet, and Job
- reconcile_builds() namespace scanning and build filtering
- _reconcile_single_build() skipping non-succeeded / already-deployed builds
- _reconcile_single_build() calling the correct finalize function
- Error handling: HTTPException(409/400) suppressed, others re-raised
- reconcile_builds() continues after per-build failures
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from kubernetes.client import ApiException

from app.core.constants import (
    KAGENTI_TYPE_LABEL,
    RESOURCE_TYPE_AGENT,
    RESOURCE_TYPE_TOOL,
)

# ---------------------------------------------------------------------------
# Helpers to build fake K8s resources
# ---------------------------------------------------------------------------


def _make_build(name: str, resource_type: str) -> dict:
    """Create a minimal Shipwright Build resource."""
    return {
        "metadata": {
            "name": name,
            "labels": {KAGENTI_TYPE_LABEL: resource_type},
        },
    }


def _make_succeeded_buildrun(build_name: str) -> dict:
    """Create a BuildRun that has succeeded."""
    return {
        "metadata": {
            "name": f"{build_name}-run-1",
            "creationTimestamp": "2026-01-01T00:00:00Z",
        },
        "status": {
            "conditions": [{"type": "Succeeded", "status": "True"}],
            "output": {"image": "registry.local/img:latest", "digest": "sha256:abc"},
        },
    }


def _make_running_buildrun(build_name: str) -> dict:
    """Create a BuildRun that is still running."""
    return {
        "metadata": {
            "name": f"{build_name}-run-1",
            "creationTimestamp": "2026-01-01T00:00:00Z",
        },
        "status": {
            "conditions": [{"type": "Succeeded", "status": "Unknown"}],
        },
    }


def _api_404() -> ApiException:
    """Create a 404 ApiException."""
    exc = ApiException(status=404, reason="Not Found")
    exc.status = 404
    return exc


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_kube():
    """Create a mock KubernetesService."""
    kube = MagicMock()
    kube.list_enabled_namespaces.return_value = ["team1"]
    kube.get_deployment.side_effect = _api_404()
    kube.get_statefulset.side_effect = _api_404()
    kube.get_job.side_effect = _api_404()
    return kube


# ---------------------------------------------------------------------------
# _workload_exists
# ---------------------------------------------------------------------------


class TestWorkloadExists:
    """Tests for _workload_exists helper."""

    def test_deployment_exists(self, mock_kube):
        from app.services.reconciliation import _workload_exists

        mock_kube.get_deployment.side_effect = None
        mock_kube.get_deployment.return_value = {"metadata": {"name": "agent1"}}

        assert _workload_exists(mock_kube, "team1", "agent1") is True

    def test_statefulset_exists(self, mock_kube):
        from app.services.reconciliation import _workload_exists

        # Deployment 404, StatefulSet found
        mock_kube.get_statefulset.side_effect = None
        mock_kube.get_statefulset.return_value = {"metadata": {"name": "agent1"}}

        assert _workload_exists(mock_kube, "team1", "agent1") is True

    def test_job_exists(self, mock_kube):
        from app.services.reconciliation import _workload_exists

        # Deployment 404, StatefulSet 404, Job found
        mock_kube.get_job.side_effect = None
        mock_kube.get_job.return_value = {"metadata": {"name": "agent1"}}

        assert _workload_exists(mock_kube, "team1", "agent1") is True

    def test_no_workload_exists(self, mock_kube):
        from app.services.reconciliation import _workload_exists

        assert _workload_exists(mock_kube, "team1", "agent1") is False

    def test_non_404_error_propagates(self, mock_kube):
        from app.services.reconciliation import _workload_exists

        exc = ApiException(status=500, reason="Internal Server Error")
        exc.status = 500
        mock_kube.get_deployment.side_effect = exc

        with pytest.raises(ApiException):
            _workload_exists(mock_kube, "team1", "agent1")


# ---------------------------------------------------------------------------
# _reconcile_single_build
# ---------------------------------------------------------------------------


class TestReconcileSingleBuild:
    """Tests for _reconcile_single_build."""

    @pytest.mark.asyncio
    async def test_skips_when_build_not_succeeded(self, mock_kube):
        from app.services.reconciliation import _reconcile_single_build

        mock_kube.list_custom_resources.return_value = [_make_running_buildrun("my-agent")]

        with patch("app.services.reconciliation.get_kubernetes_service", return_value=mock_kube):
            await _reconcile_single_build(mock_kube, "team1", "my-agent", RESOURCE_TYPE_AGENT)

        # Should not check workload existence or call finalize
        mock_kube.get_deployment.assert_not_called()

    @pytest.mark.asyncio
    async def test_skips_when_no_buildruns(self, mock_kube):
        from app.services.reconciliation import _reconcile_single_build

        mock_kube.list_custom_resources.return_value = []

        await _reconcile_single_build(mock_kube, "team1", "my-agent", RESOURCE_TYPE_AGENT)

        mock_kube.get_deployment.assert_not_called()

    @pytest.mark.asyncio
    async def test_skips_when_workload_already_exists(self, mock_kube):
        from app.services.reconciliation import _reconcile_single_build

        mock_kube.list_custom_resources.return_value = [_make_succeeded_buildrun("my-agent")]
        # Deployment exists
        mock_kube.get_deployment.side_effect = None
        mock_kube.get_deployment.return_value = {"metadata": {"name": "my-agent"}}

        with patch(
            "app.routers.agents.finalize_shipwright_build",
            new_callable=AsyncMock,
        ) as mock_finalize:
            await _reconcile_single_build(mock_kube, "team1", "my-agent", RESOURCE_TYPE_AGENT)
            mock_finalize.assert_not_called()

    @pytest.mark.asyncio
    async def test_calls_agent_finalize(self, mock_kube):
        from app.services.reconciliation import _reconcile_single_build

        mock_kube.list_custom_resources.return_value = [_make_succeeded_buildrun("my-agent")]

        with patch(
            "app.routers.agents.finalize_shipwright_build",
            new_callable=AsyncMock,
        ) as mock_finalize:
            await _reconcile_single_build(mock_kube, "team1", "my-agent", RESOURCE_TYPE_AGENT)

            mock_finalize.assert_awaited_once()
            call_kwargs = mock_finalize.call_args.kwargs
            assert call_kwargs["namespace"] == "team1"
            assert call_kwargs["name"] == "my-agent"
            assert call_kwargs["kube"] is mock_kube

    @pytest.mark.asyncio
    async def test_calls_tool_finalize(self, mock_kube):
        from app.services.reconciliation import _reconcile_single_build

        mock_kube.list_custom_resources.return_value = [_make_succeeded_buildrun("my-tool")]

        with patch(
            "app.routers.tools.finalize_tool_shipwright_build",
            new_callable=AsyncMock,
        ) as mock_finalize:
            await _reconcile_single_build(mock_kube, "team1", "my-tool", RESOURCE_TYPE_TOOL)

            mock_finalize.assert_awaited_once()
            call_kwargs = mock_finalize.call_args.kwargs
            assert call_kwargs["namespace"] == "team1"
            assert call_kwargs["name"] == "my-tool"
            assert call_kwargs["kube"] is mock_kube

    @pytest.mark.asyncio
    async def test_suppresses_409_conflict(self, mock_kube):
        from fastapi import HTTPException

        from app.services.reconciliation import _reconcile_single_build

        mock_kube.list_custom_resources.return_value = [_make_succeeded_buildrun("my-agent")]

        with patch(
            "app.routers.agents.finalize_shipwright_build",
            new_callable=AsyncMock,
            side_effect=HTTPException(status_code=409, detail="Already exists"),
        ):
            # Should not raise
            await _reconcile_single_build(mock_kube, "team1", "my-agent", RESOURCE_TYPE_AGENT)

    @pytest.mark.asyncio
    async def test_suppresses_400_not_ready(self, mock_kube):
        from fastapi import HTTPException

        from app.services.reconciliation import _reconcile_single_build

        mock_kube.list_custom_resources.return_value = [_make_succeeded_buildrun("my-agent")]

        with patch(
            "app.routers.agents.finalize_shipwright_build",
            new_callable=AsyncMock,
            side_effect=HTTPException(status_code=400, detail="Not ready"),
        ):
            # Should not raise
            await _reconcile_single_build(mock_kube, "team1", "my-agent", RESOURCE_TYPE_AGENT)

    @pytest.mark.asyncio
    async def test_reraises_other_http_errors(self, mock_kube):
        from fastapi import HTTPException

        from app.services.reconciliation import _reconcile_single_build

        mock_kube.list_custom_resources.return_value = [_make_succeeded_buildrun("my-agent")]

        with patch(
            "app.routers.agents.finalize_shipwright_build",
            new_callable=AsyncMock,
            side_effect=HTTPException(status_code=500, detail="Server error"),
        ):
            with pytest.raises(HTTPException) as exc_info:
                await _reconcile_single_build(mock_kube, "team1", "my-agent", RESOURCE_TYPE_AGENT)
            assert exc_info.value.status_code == 500


# ---------------------------------------------------------------------------
# reconcile_builds
# ---------------------------------------------------------------------------


class TestReconcileBuilds:
    """Tests for the top-level reconcile_builds function."""

    @pytest.mark.asyncio
    async def test_scans_all_enabled_namespaces(self, mock_kube):
        from app.services.reconciliation import reconcile_builds

        mock_kube.list_enabled_namespaces.return_value = ["team1", "team2"]
        mock_kube.list_custom_resources.return_value = []

        with patch(
            "app.services.reconciliation.get_kubernetes_service",
            return_value=mock_kube,
        ):
            await reconcile_builds()

        # Should list builds in both namespaces
        assert mock_kube.list_custom_resources.call_count == 2

    @pytest.mark.asyncio
    async def test_filters_by_resource_type(self, mock_kube):
        from app.services.reconciliation import reconcile_builds

        # Build with unknown type label
        mock_kube.list_custom_resources.return_value = [
            {
                "metadata": {
                    "name": "unknown-build",
                    "labels": {KAGENTI_TYPE_LABEL: "unknown"},
                },
            }
        ]

        with (
            patch(
                "app.services.reconciliation.get_kubernetes_service",
                return_value=mock_kube,
            ),
            patch(
                "app.services.reconciliation._reconcile_single_build",
                new_callable=AsyncMock,
            ) as mock_reconcile,
        ):
            await reconcile_builds()

        mock_reconcile.assert_not_called()

    @pytest.mark.asyncio
    async def test_continues_after_build_failure(self, mock_kube):
        from app.services.reconciliation import reconcile_builds

        mock_kube.list_custom_resources.return_value = [
            _make_build("agent1", RESOURCE_TYPE_AGENT),
            _make_build("agent2", RESOURCE_TYPE_AGENT),
        ]

        call_count = 0

        async def side_effect(kube, namespace, name, resource_type):
            nonlocal call_count
            call_count += 1
            if name == "agent1":
                raise RuntimeError("Unexpected error")

        with (
            patch(
                "app.services.reconciliation.get_kubernetes_service",
                return_value=mock_kube,
            ),
            patch(
                "app.services.reconciliation._reconcile_single_build",
                side_effect=side_effect,
            ),
        ):
            await reconcile_builds()

        # Both builds should be attempted despite first one failing
        assert call_count == 2

    @pytest.mark.asyncio
    async def test_continues_after_namespace_list_failure(self, mock_kube):
        from app.services.reconciliation import reconcile_builds

        mock_kube.list_enabled_namespaces.return_value = ["team1", "team2"]

        exc = ApiException(status=403, reason="Forbidden")
        exc.status = 403

        # First namespace fails, second succeeds
        mock_kube.list_custom_resources.side_effect = [
            exc,
            [_make_build("agent1", RESOURCE_TYPE_AGENT)],
        ]

        with (
            patch(
                "app.services.reconciliation.get_kubernetes_service",
                return_value=mock_kube,
            ),
            patch(
                "app.services.reconciliation._reconcile_single_build",
                new_callable=AsyncMock,
            ) as mock_reconcile,
        ):
            await reconcile_builds()

        # Should still reconcile the build from team2
        mock_reconcile.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_skips_build_with_missing_type_label(self, mock_kube):
        from app.services.reconciliation import reconcile_builds

        # Build with no labels at all
        mock_kube.list_custom_resources.return_value = [
            {"metadata": {"name": "no-label-build", "labels": {}}},
        ]

        with (
            patch(
                "app.services.reconciliation.get_kubernetes_service",
                return_value=mock_kube,
            ),
            patch(
                "app.services.reconciliation._reconcile_single_build",
                new_callable=AsyncMock,
            ) as mock_reconcile,
        ):
            await reconcile_builds()

        mock_reconcile.assert_not_called()
