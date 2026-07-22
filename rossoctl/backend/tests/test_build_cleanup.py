# Copyright 2025 IBM Corp.
# Licensed under the Apache License, Version 2.0

"""
Tests for build cleanup on re-import (issue #1676).

When re-importing an agent or tool that already has a Build/BuildRun,
the backend must clean up existing resources before creating new ones
to prevent 409 conflicts.
"""

from unittest.mock import MagicMock, patch, call

import pytest
from kubernetes.client.exceptions import ApiException

from app.core.constants import (
    SHIPWRIGHT_CRD_GROUP,
    SHIPWRIGHT_CRD_VERSION,
    SHIPWRIGHT_BUILDS_PLURAL,
    SHIPWRIGHT_BUILDRUNS_PLURAL,
)
from app.services.shipwright_builds import cleanup_existing_build


class TestCleanupExistingBuild:
    """Tests for the cleanup_existing_build helper."""

    def test_deletes_buildruns_and_build_when_they_exist(self):
        """When a Build and its BuildRuns exist, all are deleted."""
        kube = MagicMock()
        kube.list_custom_resources.return_value = [
            {"metadata": {"name": "my-agent-run-abc"}},
            {"metadata": {"name": "my-agent-run-def"}},
        ]

        cleanup_existing_build(kube, namespace="team1", build_name="my-agent")

        # Should list BuildRuns by label
        kube.list_custom_resources.assert_called_once_with(
            group=SHIPWRIGHT_CRD_GROUP,
            version=SHIPWRIGHT_CRD_VERSION,
            namespace="team1",
            plural=SHIPWRIGHT_BUILDRUNS_PLURAL,
            label_selector="rossoctl.io/build-name=my-agent",
        )

        # Should delete each BuildRun
        buildrun_delete_calls = [
            call(
                group=SHIPWRIGHT_CRD_GROUP,
                version=SHIPWRIGHT_CRD_VERSION,
                namespace="team1",
                plural=SHIPWRIGHT_BUILDRUNS_PLURAL,
                name="my-agent-run-abc",
            ),
            call(
                group=SHIPWRIGHT_CRD_GROUP,
                version=SHIPWRIGHT_CRD_VERSION,
                namespace="team1",
                plural=SHIPWRIGHT_BUILDRUNS_PLURAL,
                name="my-agent-run-def",
            ),
        ]
        # Should also delete the Build CR itself
        build_delete_call = call(
            group=SHIPWRIGHT_CRD_GROUP,
            version=SHIPWRIGHT_CRD_VERSION,
            namespace="team1",
            plural=SHIPWRIGHT_BUILDS_PLURAL,
            name="my-agent",
        )
        kube.delete_custom_resource.assert_has_calls(
            buildrun_delete_calls + [build_delete_call], any_order=False
        )

    def test_still_deletes_build_when_list_buildruns_returns_404(self):
        """When listing BuildRuns returns 404, Build delete is still attempted."""
        kube = MagicMock()
        kube.list_custom_resources.side_effect = ApiException(status=404)
        kube.delete_custom_resource.side_effect = ApiException(status=404)

        # Should not raise
        cleanup_existing_build(kube, namespace="team1", build_name="new-agent")

        # Build delete still attempted even though list returned 404
        kube.delete_custom_resource.assert_called_once_with(
            group=SHIPWRIGHT_CRD_GROUP,
            version=SHIPWRIGHT_CRD_VERSION,
            namespace="team1",
            plural=SHIPWRIGHT_BUILDS_PLURAL,
            name="new-agent",
        )

    def test_skips_buildrun_without_name(self):
        """BuildRuns missing metadata.name are skipped."""
        kube = MagicMock()
        kube.list_custom_resources.return_value = [
            {"metadata": {}},  # no name
            {"metadata": {"name": "my-agent-run-abc"}},
        ]

        cleanup_existing_build(kube, namespace="team1", build_name="my-agent")

        # Should only delete the one with a name, plus the Build
        assert kube.delete_custom_resource.call_count == 2

    def test_continues_on_individual_buildrun_delete_failure(self):
        """If one BuildRun delete fails, others are still attempted."""
        kube = MagicMock()
        kube.list_custom_resources.return_value = [
            {"metadata": {"name": "my-agent-run-abc"}},
            {"metadata": {"name": "my-agent-run-def"}},
        ]
        # First delete fails, second succeeds, Build delete succeeds
        kube.delete_custom_resource.side_effect = [
            ApiException(status=500),
            None,
            None,
        ]

        # Should not raise
        cleanup_existing_build(kube, namespace="team1", build_name="my-agent")

        # All three deletes were attempted
        assert kube.delete_custom_resource.call_count == 3

    def test_handles_build_404_gracefully(self):
        """If the Build itself is already gone (404), no error."""
        kube = MagicMock()
        kube.list_custom_resources.return_value = []
        kube.delete_custom_resource.side_effect = ApiException(status=404)

        cleanup_existing_build(kube, namespace="team1", build_name="my-agent")

    def test_swallows_non_404_build_delete_error(self):
        """Non-404 errors deleting the Build are logged but not raised."""
        kube = MagicMock()
        kube.list_custom_resources.return_value = []
        kube.delete_custom_resource.side_effect = ApiException(status=500)

        # Should not raise - cleanup is best-effort
        cleanup_existing_build(kube, namespace="team1", build_name="my-agent")


class TestAgentCreateCleanupIntegration:
    """Integration tests: agent create endpoint cleans up existing builds."""

    @pytest.fixture
    def app_with_mocks(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from app.routers import agents
        from app.services.kubernetes import get_kubernetes_service

        app = FastAPI()
        app.include_router(agents.router, prefix="/api/v1")

        kube = MagicMock()
        kube.list_custom_resources.return_value = [
            {"metadata": {"name": "test-agent-run-old"}},
        ]
        kube.create_custom_resource.return_value = {"metadata": {"name": "test-agent-run-new"}}
        # resolve_clone_secret needs core_api
        kube.core_api = MagicMock()
        kube.core_api.list_namespaced_secret.return_value = MagicMock(items=[])

        def override_kube():
            return kube

        app.dependency_overrides[get_kubernetes_service] = override_kube

        with patch("app.core.auth.settings") as mock_auth:
            mock_auth.enable_auth = False
            yield TestClient(app), kube

        app.dependency_overrides.clear()

    def test_create_agent_source_cleans_up_existing_build(self, app_with_mocks):
        """POST /agents (source deploy) cleans up existing Build before creating new one."""
        client, kube = app_with_mocks

        response = client.post(
            "/api/v1/agents",
            json={
                "name": "test-agent",
                "namespace": "team1",
                "protocol": "a2a",
                "framework": "LangGraph",
                "deploymentMethod": "source",
                "gitUrl": "https://github.com/example/repo",
                "gitBranch": "main",
                "gitPath": ".",
                "imageTag": "v1",
            },
        )

        assert response.status_code == 200

        # Verify cleanup was called (list + delete of old buildrun + delete of old build)
        kube.list_custom_resources.assert_called_once_with(
            group=SHIPWRIGHT_CRD_GROUP,
            version=SHIPWRIGHT_CRD_VERSION,
            namespace="team1",
            plural=SHIPWRIGHT_BUILDRUNS_PLURAL,
            label_selector="rossoctl.io/build-name=test-agent",
        )

        # Exact sequence: delete old BuildRun, then delete old Build
        delete_calls = list(kube.delete_custom_resource.call_args_list)
        assert delete_calls == [
            call(
                group=SHIPWRIGHT_CRD_GROUP,
                version=SHIPWRIGHT_CRD_VERSION,
                namespace="team1",
                plural=SHIPWRIGHT_BUILDRUNS_PLURAL,
                name="test-agent-run-old",
            ),
            call(
                group=SHIPWRIGHT_CRD_GROUP,
                version=SHIPWRIGHT_CRD_VERSION,
                namespace="team1",
                plural=SHIPWRIGHT_BUILDS_PLURAL,
                name="test-agent",
            ),
        ]


class TestToolCreateCleanupIntegration:
    """Integration tests: tool create endpoint cleans up existing builds."""

    @pytest.fixture
    def app_with_mocks(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from app.routers import tools
        from app.services.kubernetes import get_kubernetes_service

        app = FastAPI()
        app.include_router(tools.router, prefix="/api/v1")

        kube = MagicMock()
        kube.list_custom_resources.return_value = [
            {"metadata": {"name": "test-tool-run-old"}},
        ]
        kube.create_custom_resource.return_value = {"metadata": {"name": "test-tool-run-new"}}
        kube.core_api = MagicMock()
        kube.core_api.list_namespaced_secret.return_value = MagicMock(items=[])

        def override_kube():
            return kube

        app.dependency_overrides[get_kubernetes_service] = override_kube

        with patch("app.core.auth.settings") as mock_auth:
            mock_auth.enable_auth = False
            yield TestClient(app), kube

        app.dependency_overrides.clear()

    def test_create_tool_source_cleans_up_existing_build(self, app_with_mocks):
        """POST /tools (source deploy) cleans up existing Build before creating new one."""
        client, kube = app_with_mocks

        response = client.post(
            "/api/v1/tools",
            json={
                "name": "test-tool",
                "namespace": "team1",
                "protocol": "mcp",
                "deploymentMethod": "source",
                "gitUrl": "https://github.com/example/repo",
                "gitBranch": "main",
                "gitPath": ".",
                "imageTag": "v1",
            },
        )

        assert response.status_code == 200

        # Verify cleanup was called
        kube.list_custom_resources.assert_called_once_with(
            group=SHIPWRIGHT_CRD_GROUP,
            version=SHIPWRIGHT_CRD_VERSION,
            namespace="team1",
            plural=SHIPWRIGHT_BUILDRUNS_PLURAL,
            label_selector="rossoctl.io/build-name=test-tool",
        )

        # Exact sequence: delete old BuildRun, then delete old Build
        delete_calls = list(kube.delete_custom_resource.call_args_list)
        assert delete_calls == [
            call(
                group=SHIPWRIGHT_CRD_GROUP,
                version=SHIPWRIGHT_CRD_VERSION,
                namespace="team1",
                plural=SHIPWRIGHT_BUILDRUNS_PLURAL,
                name="test-tool-run-old",
            ),
            call(
                group=SHIPWRIGHT_CRD_GROUP,
                version=SHIPWRIGHT_CRD_VERSION,
                namespace="team1",
                plural=SHIPWRIGHT_BUILDS_PLURAL,
                name="test-tool",
            ),
        ]
