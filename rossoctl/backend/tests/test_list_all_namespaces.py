# Copyright 2025 IBM Corp.
# Licensed under the Apache License, Version 2.0

"""Tests for allNamespaces=true on GET /agents, /tools and /skills (#1272)."""

from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from kubernetes.client import V1ConfigMap, V1ObjectMeta
from kubernetes.client.rest import ApiException

from app.routers import agents, skills, tools
from app.services.kubernetes import filter_to_namespaces, get_kubernetes_service


def _workload(name: str, ns: str, rtype: str) -> dict:
    return {
        "metadata": {
            "name": name,
            "namespace": ns,
            "labels": {"rossoctl.io/type": rtype},
            "annotations": {},
            "creationTimestamp": "2025-01-01T00:00:00Z",
        },
        "spec": {"replicas": 1},
        "status": {"readyReplicas": 1, "replicas": 1},
    }


def _sample_build(name: str, ns: str, rtype: str) -> dict:
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


def _sandbox(name: str, ns: str) -> dict:
    return {
        "metadata": {
            "name": name,
            "namespace": ns,
            "labels": {"rossoctl.io/type": "agent"},
            "annotations": {},
        },
        "status": {"conditions": [{"type": "Ready", "status": "True"}]},
    }


def _legacy_agent_crd(name: str, ns: str) -> dict:
    return {
        "metadata": {
            "name": name,
            "namespace": ns,
            "labels": {"rossoctl.io/type": "agent"},
            "annotations": {},
        },
        "spec": {"description": "legacy agent"},
        "status": {"conditions": [{"type": "Ready", "status": "True"}]},
    }


def _skill_cm(name: str, ns: str) -> V1ConfigMap:
    return V1ConfigMap(
        metadata=V1ObjectMeta(
            name=name,
            namespace=ns,
            labels={"rossoctl.io/type": "skill"},
            annotations={},
        ),
        data={"SKILL.md": f"# {name}"},
    )


def _kube(enabled=("team1", "team2")) -> MagicMock:
    kube = MagicMock()
    kube.list_enabled_namespaces.return_value = list(enabled)
    kube.list_deployments.return_value = []
    kube.list_statefulsets.return_value = []
    kube.list_jobs.return_value = []
    kube.list_sandboxes.return_value = []
    kube.list_custom_resources.return_value = []
    kube.custom_api.list_namespaced_custom_object.return_value = {"items": []}
    kube.custom_api.list_cluster_custom_object.return_value = {"items": []}
    return kube


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(agents.router, prefix="/api/v1")
    app.include_router(tools.router, prefix="/api/v1")
    app.include_router(skills.router, prefix="/api/v1")

    def _client(kube: MagicMock) -> TestClient:
        app.dependency_overrides[get_kubernetes_service] = lambda: kube
        return TestClient(app)

    with patch("app.core.auth.settings") as mock_auth:
        mock_auth.enable_auth = False
        yield _client
    app.dependency_overrides.clear()


class TestFilterToNamespaces:
    def test_none_scope_keeps_everything(self):
        items = [{"metadata": {"namespace": "a"}}, {"metadata": {"namespace": "b"}}]
        assert filter_to_namespaces(items, None) == items

    def test_drops_items_outside_scope(self):
        items = [
            {"metadata": {"namespace": "team1"}},
            {"metadata": {"namespace": "kube-system"}},
            {"metadata": None},
        ]
        assert filter_to_namespaces(items, {"team1"}) == [{"metadata": {"namespace": "team1"}}]


class TestListAgentsAllNamespaces:
    def test_single_cluster_wide_call_filtered_to_enabled(self, client):
        kube = _kube()
        kube.list_deployments.return_value = [
            _workload("weather", "team1", "agent"),
            _workload("weather", "team2", "agent"),  # same name, other namespace
            _workload("stray", "not-enabled", "agent"),
        ]

        r = client(kube).get("/api/v1/agents", params={"allNamespaces": "true"})

        assert r.status_code == 200
        got = sorted((a["namespace"], a["name"]) for a in r.json()["items"])
        assert got == [("team1", "weather"), ("team2", "weather")]
        kube.list_deployments.assert_called_once()
        assert kube.list_deployments.call_args.kwargs["namespace"] is None
        assert kube.list_statefulsets.call_args.kwargs["namespace"] is None
        assert kube.list_jobs.call_args.kwargs["namespace"] is None

    def test_no_enabled_namespaces_skips_cluster_queries(self, client):
        kube = _kube(enabled=())

        r = client(kube).get("/api/v1/agents", params={"allNamespaces": "true"})

        assert r.status_code == 200
        assert r.json()["items"] == []
        kube.list_deployments.assert_not_called()

    def test_single_namespace_behaviour_unchanged(self, client):
        kube = _kube()
        kube.list_deployments.return_value = [_workload("weather", "team1", "agent")]

        r = client(kube).get("/api/v1/agents", params={"namespace": "team1"})

        assert r.status_code == 200
        assert [a["name"] for a in r.json()["items"]] == ["weather"]
        assert kube.list_deployments.call_args.kwargs["namespace"] == "team1"
        kube.list_enabled_namespaces.assert_not_called()

    def test_shipwright_build_dedup_all_namespaces(self, client):
        kube = _kube()
        kube.list_deployments.return_value = [_workload("weather", "team1", "agent")]
        kube.custom_api.list_cluster_custom_object.return_value = {
            "items": [
                _sample_build("weather", "team1", "agent"),  # workload exists -> skip
                _sample_build("weather", "team2", "agent"),  # no workload -> Building
                _sample_build("x", "not-enabled", "agent"),  # out of scope -> dropped
            ]
        }

        r = client(kube).get("/api/v1/agents", params={"allNamespaces": "true"})

        assert r.status_code == 200
        items = r.json()["items"]
        got = sorted((a["namespace"], a["name"]) for a in items)
        assert got == [("team1", "weather"), ("team2", "weather")]
        team2_item = next(a for a in items if a["namespace"] == "team2")
        assert team2_item["status"] == "Building"
        kube.custom_api.list_namespaced_custom_object.assert_not_called()
        kube.custom_api.list_cluster_custom_object.assert_called_once()

    def test_same_namespace_duplicate_workloads_dedup(self, client):
        kube = _kube()
        kube.list_deployments.return_value = [_workload("weather", "team1", "agent")]
        kube.list_statefulsets.return_value = [
            _workload("weather", "team1", "agent"),  # dup of Deployment -> skipped
            _workload("weather", "team2", "agent"),  # different namespace -> listed
        ]

        r = client(kube).get("/api/v1/agents", params={"allNamespaces": "true"})

        assert r.status_code == 200
        items = r.json()["items"]
        got = {(a["namespace"], a["name"]) for a in items}
        assert got == {("team1", "weather"), ("team2", "weather")}
        team1_item = next(a for a in items if a["namespace"] == "team1")
        assert team1_item["workloadType"] == "deployment"


class TestLegacyAgentCrdsAndSandboxesAllNamespaces:
    def test_legacy_crds_and_sandboxes_filtered_to_enabled(self, client, monkeypatch):
        monkeypatch.setattr(agents.settings, "enable_legacy_agent_crd", True)
        monkeypatch.setattr(agents.settings, "rossoctl_feature_flag_agent_sandbox", True)

        kube = _kube()
        kube.list_custom_resources.return_value = [
            _legacy_agent_crd("legacy1", "team1"),
            _legacy_agent_crd("legacy2", "not-enabled"),
        ]
        kube.list_sandboxes.return_value = [
            _sandbox("sandbox1", "team2"),
            _sandbox("sandbox2", "not-enabled"),
        ]

        r = client(kube).get("/api/v1/agents", params={"allNamespaces": "true"})

        assert r.status_code == 200
        got = {(a["namespace"], a["name"]) for a in r.json()["items"]}
        assert got == {("team1", "legacy1"), ("team2", "sandbox1")}
        assert kube.list_custom_resources.call_args.kwargs["namespace"] is None
        assert kube.list_sandboxes.call_args.kwargs["namespace"] is None


class TestPermissionErrorsAllNamespaces:
    def test_list_enabled_namespaces_403_agents(self, client):
        kube = _kube()
        kube.list_enabled_namespaces.side_effect = ApiException(status=403)

        r = client(kube).get("/api/v1/agents", params={"allNamespaces": "true"})

        assert r.status_code == 403

    def test_list_enabled_namespaces_403_tools(self, client):
        kube = _kube()
        kube.list_enabled_namespaces.side_effect = ApiException(status=403)

        r = client(kube).get("/api/v1/tools", params={"allNamespaces": "true"})

        assert r.status_code == 403

    def test_list_deployments_403_agents(self, client):
        # In agents.py, the Deployments query is not individually try/except'd,
        # so a 403 propagates to the outer handler -> HTTPException(403). (In
        # tools.py, the Deployments query is wrapped and swallows non-404
        # errors with a warning log, so it doesn't apply there.)
        kube = _kube()
        kube.list_deployments.side_effect = ApiException(status=403)

        r = client(kube).get("/api/v1/agents", params={"allNamespaces": "true"})

        assert r.status_code == 403


class TestListToolsAllNamespaces:
    def test_single_cluster_wide_call_filtered_to_enabled(self, client):
        kube = _kube()
        kube.list_deployments.return_value = [
            _workload("fetch", "team1", "tool"),
            _workload("fetch", "team2", "tool"),
            _workload("stray", "not-enabled", "tool"),
        ]

        r = client(kube).get("/api/v1/tools", params={"allNamespaces": "true"})

        assert r.status_code == 200
        got = sorted((t["namespace"], t["name"]) for t in r.json()["items"])
        assert got == [("team1", "fetch"), ("team2", "fetch")]
        assert kube.list_deployments.call_args.args[0] is None
        assert kube.list_statefulsets.call_args.args[0] is None

    def test_shipwright_build_dedup_all_namespaces(self, client):
        kube = _kube()
        kube.list_deployments.return_value = [_workload("fetch", "team1", "tool")]
        kube.custom_api.list_cluster_custom_object.return_value = {
            "items": [
                _sample_build("fetch", "team1", "tool"),  # workload exists -> skip
                _sample_build("fetch", "team2", "tool"),  # no workload -> Building
                _sample_build("x", "not-enabled", "tool"),  # out of scope -> dropped
            ]
        }

        r = client(kube).get("/api/v1/tools", params={"allNamespaces": "true"})

        assert r.status_code == 200
        items = r.json()["items"]
        got = sorted((t["namespace"], t["name"]) for t in items)
        assert got == [("team1", "fetch"), ("team2", "fetch")]
        team2_item = next(t for t in items if t["namespace"] == "team2")
        assert team2_item["status"] == "Building"
        kube.custom_api.list_namespaced_custom_object.assert_not_called()
        kube.custom_api.list_cluster_custom_object.assert_called_once()


class TestListSkillsAllNamespaces:
    def test_single_cluster_wide_call_filtered_to_enabled(self, client):
        kube = _kube()
        kube.core_api.list_config_map_for_all_namespaces.return_value = MagicMock(
            items=[_skill_cm("summarize", "team1"), _skill_cm("stray", "not-enabled")]
        )

        r = client(kube).get("/api/v1/skills", params={"allNamespaces": "true"})

        assert r.status_code == 200
        assert [s["name"] for s in r.json()["items"]] == ["summarize"]
        kube.core_api.list_namespaced_config_map.assert_not_called()

    def test_namespace_required_without_all_namespaces(self, client):
        r = client(_kube()).get("/api/v1/skills")

        assert r.status_code == 400
