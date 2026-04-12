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
            "labels": {"kagenti.io/type": rtype},
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
        assert "kagenti.io/type in (agent,tool)" in call_kw.get("label_selector", "")
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
        assert call_kw.get("label_selector") == "kagenti.io/type=agent"
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
        assert call_kw.get("label_selector") == "kagenti.io/type=tool"
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
            == "kagenti.io/type=tool"
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
            == "kagenti.io/type=agent"
        )
        agents_shipwright_app.dependency_overrides.clear()


class TestCollectShipwrightBuildsLogging:
    def test_403_warning_is_constant_only(self):
        from kubernetes.client import ApiException

        from app.services.shipwright_builds import collect_kagenti_shipwright_builds

        kube = MagicMock()
        log_mock = MagicMock()
        kube.custom_api.list_namespaced_custom_object.side_effect = ApiException(
            status=403, reason="forbidden\nfake-log-line"
        )
        collect_kagenti_shipwright_builds(kube, ["team\n1"], RESOURCE_TYPE_AGENT, log_mock)
        log_mock.warning.assert_called_once()
        (msg,) = log_mock.warning.call_args[0]
        assert "\n" not in msg
        assert "403" in msg
        assert "team" not in msg
        assert "forbidden" not in msg
