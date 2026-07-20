# Copyright 2025 IBM Corp.
# Licensed under the Apache License, Version 2.0

"""Tests for GET /api/v1/shipwright/builds."""

from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.constants import RESOURCE_TYPE_AGENT
from app.routers import agents, shipwright, tools
from app.services.kubernetes import get_kubernetes_service


@pytest.fixture
def shipwright_app():
    app = FastAPI()
    app.include_router(shipwright.router, prefix="/api/v1")
    return app


@pytest.fixture
def tools_shipwright_app():
    app = FastAPI()
    app.include_router(tools.router, prefix="/api/v1")
    return app


@pytest.fixture
def agents_shipwright_app():
    app = FastAPI()
    app.include_router(agents.router, prefix="/api/v1")
    return app


def _sample_build(name: str, ns: str, rtype: str):
    return {
        "metadata": {
            "name": name,
            "namespace": ns,
            "labels": {"rossoctl.io/type": rtype},
            "creationTimestamp": "2025-01-01T00:00:00Z",
        },
        "spec": {
            "source": {
                "git": {"url": "https://example.git", "revision": "main"},
                "contextDir": ".",
            },
            "strategy": {"name": "buildah"},
            "output": {"image": "registry/ns/img:latest"},
        },
        "status": {"registered": True},
    }


class TestListShipwrightBuilds:
    def test_requires_namespace_when_not_all_namespaces(self, shipwright_app):
        kube = MagicMock()

        def override_kube():
            return kube

        shipwright_app.dependency_overrides[get_kubernetes_service] = override_kube
        with patch("app.core.auth.settings") as mock_auth:
            mock_auth.enable_auth = False
            tc = TestClient(shipwright_app)
            r = tc.get("/api/v1/shipwright/builds")
            assert r.status_code == 400
        shipwright_app.dependency_overrides.clear()

    def test_lists_builds_single_namespace_all_resource_types(self, shipwright_app):
        kube = MagicMock()
        kube.custom_api.list_namespaced_custom_object.return_value = {
            "items": [
                _sample_build("b1", "team1", "agent"),
                _sample_build("t1", "team1", "tool"),
            ]
        }

        def override_kube():
            return kube

        shipwright_app.dependency_overrides[get_kubernetes_service] = override_kube
        with patch("app.core.auth.settings") as mock_auth:
            mock_auth.enable_auth = False
            tc = TestClient(shipwright_app)
            r = tc.get(
                "/api/v1/shipwright/builds",
                params={"namespace": "team1", "for": "all"},
            )
            assert r.status_code == 200
            data = r.json()
            assert len(data["items"]) == 2
            names = {i["name"] for i in data["items"]}
            assert names == {"b1", "t1"}
            types = {i["resourceType"] for i in data["items"]}
            assert types == {"agent", "tool"}
        kube.custom_api.list_namespaced_custom_object.assert_called_once()
        call_kw = kube.custom_api.list_namespaced_custom_object.call_args.kwargs
        assert "rossoctl.io/type in (agent,tool)" in call_kw.get("label_selector", "")
        shipwright_app.dependency_overrides.clear()

    def test_resource_type_agent_filter(self, shipwright_app):
        kube = MagicMock()
        kube.custom_api.list_namespaced_custom_object.return_value = {
            "items": [_sample_build("b1", "n1", "agent")]
        }

        def override_kube():
            return kube

        shipwright_app.dependency_overrides[get_kubernetes_service] = override_kube
        with patch("app.core.auth.settings") as mock_auth:
            mock_auth.enable_auth = False
            tc = TestClient(shipwright_app)
            r = tc.get(
                "/api/v1/shipwright/builds",
                params={"namespace": "n1", "for": "agents"},
            )
            assert r.status_code == 200
        call_kw = kube.custom_api.list_namespaced_custom_object.call_args.kwargs
        assert call_kw.get("label_selector") == "rossoctl.io/type=agent"
        shipwright_app.dependency_overrides.clear()

    def test_resource_type_tool_filter(self, shipwright_app):
        kube = MagicMock()
        kube.custom_api.list_namespaced_custom_object.return_value = {
            "items": [_sample_build("t1", "n1", "tool")]
        }

        def override_kube():
            return kube

        shipwright_app.dependency_overrides[get_kubernetes_service] = override_kube
        with patch("app.core.auth.settings") as mock_auth:
            mock_auth.enable_auth = False
            tc = TestClient(shipwright_app)
            r = tc.get(
                "/api/v1/shipwright/builds",
                params={"namespace": "n1", "for": "tools"},
            )
            assert r.status_code == 200
        call_kw = kube.custom_api.list_namespaced_custom_object.call_args.kwargs
        assert call_kw.get("label_selector") == "rossoctl.io/type=tool"
        shipwright_app.dependency_overrides.clear()

    def test_all_namespaces_scans_enabled(self, shipwright_app):
        kube = MagicMock()
        kube.list_enabled_namespaces.return_value = ["a", "b"]
        kube.custom_api.list_namespaced_custom_object.side_effect = [
            {"items": [_sample_build("x", "a", "tool")]},
            {"items": []},
        ]

        def override_kube():
            return kube

        shipwright_app.dependency_overrides[get_kubernetes_service] = override_kube
        with patch("app.core.auth.settings") as mock_auth:
            mock_auth.enable_auth = False
            tc = TestClient(shipwright_app)
            r = tc.get("/api/v1/shipwright/builds", params={"allNamespaces": "true"})
            assert r.status_code == 200
            assert len(r.json()["items"]) == 1
        assert kube.custom_api.list_namespaced_custom_object.call_count == 2
        shipwright_app.dependency_overrides.clear()


class TestListToolShipwrightBuilds:
    def test_always_uses_tool_label_selector(self, tools_shipwright_app):
        kube = MagicMock()
        kube.custom_api.list_namespaced_custom_object.return_value = {
            "items": [_sample_build("tb", "ns1", "tool")]
        }

        def override_kube():
            return kube

        tools_shipwright_app.dependency_overrides[get_kubernetes_service] = override_kube
        with patch("app.core.auth.settings") as mock_auth:
            mock_auth.enable_auth = False
            tc = TestClient(tools_shipwright_app)
            r = tc.get("/api/v1/tools/shipwright-builds", params={"namespace": "ns1"})
            assert r.status_code == 200
            assert r.json()["items"][0]["resourceType"] == "tool"
        assert (
            kube.custom_api.list_namespaced_custom_object.call_args.kwargs.get("label_selector")
            == "rossoctl.io/type=tool"
        )
        tools_shipwright_app.dependency_overrides.clear()


class TestListAgentShipwrightBuilds:
    def test_always_uses_agent_label_selector(self, agents_shipwright_app):
        kube = MagicMock()
        kube.custom_api.list_namespaced_custom_object.return_value = {
            "items": [_sample_build("ab", "ns1", "agent")]
        }

        def override_kube():
            return kube

        agents_shipwright_app.dependency_overrides[get_kubernetes_service] = override_kube
        with patch("app.core.auth.settings") as mock_auth:
            mock_auth.enable_auth = False
            tc = TestClient(agents_shipwright_app)
            r = tc.get("/api/v1/agents/shipwright-builds", params={"namespace": "ns1"})
            assert r.status_code == 200
            item = r.json()["items"][0]
            assert item["resourceType"] == "agent"
        assert (
            kube.custom_api.list_namespaced_custom_object.call_args.kwargs.get("label_selector")
            == "rossoctl.io/type=agent"
        )
        agents_shipwright_app.dependency_overrides.clear()


def _buildrun(name: str, succeeded_status: str | None):
    """Mock a BuildRun dict. succeeded_status is the 'Succeeded' condition status
    ("True"/"False"/"Unknown"), or None for a BuildRun with no conditions."""
    conditions = []
    if succeeded_status is not None:
        conditions = [{"type": "Succeeded", "status": succeeded_status, "message": "boom"}]
    return {
        # No tests care about timestamps -- mock a dummy timestamp
        "metadata": {"name": name, "creationTimestamp": "2025-01-02T00:00:00Z"},
        "status": {"conditions": conditions},
    }


class TestListAgentsIncludesBuilds:
    """GET /api/v1/agents surfaces in-progress / failed Shipwright builds that
    have no workload yet, with a status of "Building" or "Build Failed"."""

    def _run(self, kube, buildrun, *, builds=None, params=None):
        """Drive GET /agents with empty workloads and one agent build (unless
        overridden), returning the parsed items list."""
        app = FastAPI()
        app.include_router(agents.router, prefix="/api/v1")

        # Default workloads to empty unless the caller pre-seeded a return_value.
        for meth in ("list_deployments", "list_statefulsets", "list_jobs"):
            m = getattr(kube, meth)
            if not isinstance(m.return_value, list):
                m.return_value = []
        # Builds listed by collect_rossoctl_shipwright_builds (via custom_api).
        if builds is None:
            builds = [_sample_build("buildme", "team1", "agent")]
        kube.custom_api.list_namespaced_custom_object.return_value = {"items": builds}
        # BuildRuns listed by the new block via kube.list_custom_resources.
        kube.list_custom_resources.return_value = [] if buildrun is None else [buildrun]

        app.dependency_overrides[get_kubernetes_service] = lambda: kube
        with (
            patch("app.core.auth.settings") as mock_auth,
            patch("app.routers.agents.settings") as mock_settings,
        ):
            mock_auth.enable_auth = False
            mock_settings.rossoctl_feature_flag_agent_sandbox = False
            mock_settings.enable_legacy_agent_crd = False
            tc = TestClient(app)
            r = tc.get("/api/v1/agents", params=params or {"namespace": "team1"})
            assert r.status_code == 200
            items = r.json()["items"]
        app.dependency_overrides.clear()
        return items

    def test_failed_build_marked_build_failed(self):
        items = self._run(MagicMock(), _buildrun("br1", "False"))
        assert len(items) == 1
        assert items[0]["name"] == "buildme"
        assert items[0]["status"] == "Build Failed"

    def test_running_build_marked_building(self):
        items = self._run(MagicMock(), _buildrun("br1", "Unknown"))
        assert len(items) == 1
        assert items[0]["status"] == "Building"

    def test_no_buildrun_marked_building(self):
        items = self._run(MagicMock(), None)
        assert len(items) == 1
        assert items[0]["status"] == "Building"

    def test_succeeded_build_not_listed(self):
        items = self._run(MagicMock(), _buildrun("br1", "True"))
        assert items == []

    def test_build_deduped_against_existing_workload(self):
        kube = MagicMock()
        kube.list_deployments.return_value = [
            {
                "metadata": {
                    "name": "buildme",
                    "namespace": "team1",
                    "labels": {"rossoctl.io/type": "agent"},
                    "creationTimestamp": "2025-01-01T00:00:00Z",
                },
                "status": {"conditions": [{"type": "Available", "status": "True"}]},
            }
        ]
        # Build with the same name as the deployment -> must not be added twice.
        items = self._run(kube, _buildrun("br1", "False"))
        assert len(items) == 1
        # The single entry is the real workload, not the synthetic build entry.
        assert items[0]["status"] != "Build Failed"

    def test_build_listing_failure_does_not_break_list(self):
        from kubernetes.client import ApiException

        kube = MagicMock()
        kube.custom_api.list_namespaced_custom_object.side_effect = ApiException(
            status=500, reason="boom"
        )
        # collect_rossoctl_shipwright_builds re-raises non-403/404; the new block's
        # outer guard must swallow it so the core (empty) list still returns 200.
        items = self._run(kube, None, builds=[])
        assert items == []


class TestListToolsIncludesBuilds:
    """GET /api/v1/tools surfaces in-progress / failed Shipwright builds that
    have no workload yet, with a status of "Building" or "Build Failed"."""

    def _run(self, kube, buildrun, *, builds=None):
        """Drive GET /tools with empty workloads and one tool build (unless
        overridden), returning the parsed items list."""
        app = FastAPI()
        app.include_router(tools.router, prefix="/api/v1")

        # Default workloads to empty unless the caller pre-seeded a return_value.
        for meth in ("list_deployments", "list_statefulsets"):
            m = getattr(kube, meth)
            if not isinstance(m.return_value, list):
                m.return_value = []
        # Builds listed by collect_rossoctl_shipwright_builds (via custom_api).
        if builds is None:
            builds = [_sample_build("buildme", "team1", "tool")]
        kube.custom_api.list_namespaced_custom_object.return_value = {"items": builds}
        # BuildRuns listed by the new block via kube.list_custom_resources.
        kube.list_custom_resources.return_value = [] if buildrun is None else [buildrun]

        app.dependency_overrides[get_kubernetes_service] = lambda: kube
        with patch("app.core.auth.settings") as mock_auth:
            mock_auth.enable_auth = False
            tc = TestClient(app)
            r = tc.get("/api/v1/tools", params={"namespace": "team1"})
            assert r.status_code == 200
            items = r.json()["items"]
        app.dependency_overrides.clear()
        return items

    def test_failed_build_marked_build_failed(self):
        items = self._run(MagicMock(), _buildrun("br1", "False"))
        assert len(items) == 1
        assert items[0]["name"] == "buildme"
        assert items[0]["status"] == "Build Failed"

    def test_running_build_marked_building(self):
        items = self._run(MagicMock(), _buildrun("br1", "Unknown"))
        assert len(items) == 1
        assert items[0]["status"] == "Building"

    def test_no_buildrun_marked_building(self):
        items = self._run(MagicMock(), None)
        assert len(items) == 1
        assert items[0]["status"] == "Building"

    def test_succeeded_build_not_listed(self):
        items = self._run(MagicMock(), _buildrun("br1", "True"))
        assert items == []

    def test_build_deduped_against_existing_workload(self):
        kube = MagicMock()
        kube.list_deployments.return_value = [
            {
                "metadata": {
                    "name": "buildme",
                    "namespace": "team1",
                    "labels": {"rossoctl.io/type": "tool"},
                    "creationTimestamp": "2025-01-01T00:00:00Z",
                },
                "status": {"conditions": [{"type": "Available", "status": "True"}]},
                "spec": {"replicas": 1},
            }
        ]
        # Build with the same name as the deployment -> must not be added twice.
        items = self._run(kube, _buildrun("br1", "False"))
        assert len(items) == 1
        # The single entry is the real workload, not the synthetic build entry.
        assert items[0]["status"] != "Build Failed"

    def test_build_listing_failure_does_not_break_list(self):
        from kubernetes.client import ApiException

        kube = MagicMock()
        kube.custom_api.list_namespaced_custom_object.side_effect = ApiException(
            status=500, reason="boom"
        )
        # collect_rossoctl_shipwright_builds re-raises non-403/404; the new block's
        # outer guard must swallow it so the core (empty) list still returns 200.
        items = self._run(kube, None, builds=[])
        assert items == []


class TestGetToolBuildFallback:
    """GET /api/v1/tools/{ns}/{name} falls back to a source build when no
    workload exists, returning readyStatus "Building" / "Build Failed" instead
    of a 404 (and a real 404 only when there is no build either)."""

    def _run(self, buildrun, *, build="present"):
        """Drive GET /tools/team1/buildme with no Deployment/StatefulSet.

        build="present" -> get_custom_resource returns a Build CR
        build="missing" -> get_custom_resource raises 404
        buildrun         -> BuildRun dict (or None for no BuildRun)
        Returns (status_code, json_body).
        """
        from kubernetes.client import ApiException

        kube = MagicMock()
        kube.get_deployment.side_effect = ApiException(status=404, reason="nf")
        kube.get_statefulset.side_effect = ApiException(status=404, reason="nf")
        if build == "missing":
            kube.get_custom_resource.side_effect = ApiException(status=404, reason="nf")
        else:
            kube.get_custom_resource.return_value = _sample_build("buildme", "team1", "tool")
        kube.list_custom_resources.return_value = [] if buildrun is None else [buildrun]

        app = FastAPI()
        app.include_router(tools.router, prefix="/api/v1")
        app.dependency_overrides[get_kubernetes_service] = lambda: kube
        with patch("app.core.auth.settings") as mock_auth:
            mock_auth.enable_auth = False
            tc = TestClient(app)
            r = tc.get("/api/v1/tools/team1/buildme")
        app.dependency_overrides.clear()
        return r.status_code, (r.json() if r.status_code == 200 else None)

    def test_failed_build_marked_build_failed(self):
        code, body = self._run(_buildrun("br1", "False"))
        assert code == 200
        assert body["readyStatus"] == "Build Failed"
        assert body["isBuild"] is True
        assert body["metadata"]["name"] == "buildme"

    def test_running_build_marked_building(self):
        code, body = self._run(_buildrun("br1", "Unknown"))
        assert code == 200
        assert body["readyStatus"] == "Building"

    def test_no_buildrun_marked_building(self):
        code, body = self._run(None)
        assert code == 200
        assert body["readyStatus"] == "Building"

    def test_succeeded_build_returns_404(self):
        # Build succeeded but no workload exists -> not a build placeholder;
        # fall through to the normal 404.
        code, _ = self._run(_buildrun("br1", "True"))
        assert code == 404

    def test_no_build_returns_404(self):
        code, _ = self._run(_buildrun("br1", "False"), build="missing")
        assert code == 404


class TestCollectShipwrightBuildsLogging:
    def test_403_warning_is_constant_only(self):
        from kubernetes.client import ApiException

        from app.services.shipwright_builds import collect_rossoctl_shipwright_builds

        kube = MagicMock()
        log_mock = MagicMock()
        kube.custom_api.list_namespaced_custom_object.side_effect = ApiException(
            status=403, reason="forbidden\nfake-log-line"
        )
        collect_rossoctl_shipwright_builds(kube, ["team\n1"], RESOURCE_TYPE_AGENT, log_mock)
        log_mock.warning.assert_called_once()
        (msg,) = log_mock.warning.call_args[0]
        assert "\n" not in msg
        assert "403" in msg
        assert "team" not in msg
        assert "forbidden" not in msg
