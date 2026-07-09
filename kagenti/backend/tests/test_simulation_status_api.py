# Copyright 2025 IBM Corp.
# Licensed under the Apache License, Version 2.0

"""Tests for GET /simulation/tools/{ns}/{name}/generation-status (issue #2162)."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from kubernetes.client import ApiException

from app.routers import simulation as sim_router
from app.services.kubernetes import get_kubernetes_service


def _sts(created=None, ready_replicas=1):
    created = created or datetime.now(timezone.utc)
    return SimpleNamespace(
        metadata=SimpleNamespace(creation_timestamp=created),
        spec=SimpleNamespace(replicas=1),
        status=SimpleNamespace(ready_replicas=ready_replicas),
    )


def _kube(sts=None, sts_exc=None, pod_status=None):
    k = MagicMock()
    if sts_exc is not None:
        k.apps_api.read_namespaced_stateful_set.side_effect = sts_exc
    else:
        k.apps_api.read_namespaced_stateful_set.return_value = sts or _sts()
    k.get_workload_pod_status.return_value = pod_status or {
        "ready": True,
        "waiting_reason": None,
        "waiting_message": None,
    }
    return k


def _client(kube):
    app = FastAPI()
    app.include_router(sim_router.router)
    app.dependency_overrides[get_kubernetes_service] = lambda: kube
    return app


def _get(app, ns="team1", name="petstore"):
    with patch("app.core.auth.settings") as auth:
        auth.enable_auth = False
        return TestClient(app).get(f"/simulation/tools/{ns}/{name}/generation-status")


def test_ready_returns_ready_with_mcp_url():
    kube = _kube()
    with (
        patch(
            "app.routers.simulation.get_simulation",
            new=AsyncMock(return_value={"status": "ready", "mcp_url": "http://x/mcp/petstore"}),
        ),
        patch("app.routers.simulation.settings") as s,
    ):
        s.simulation_generation_timeout = 600
        r = _get(_client(kube))
    assert r.status_code == 200
    assert r.json() == {"status": "Ready", "reason": None, "mcpUrl": "http://x/mcp/petstore"}


def test_harness_404_healthy_pod_within_timeout_is_generating():
    kube = _kube()
    with (
        patch(
            "app.routers.simulation.get_simulation",
            new=AsyncMock(side_effect=sim_router.HarnessNotFound()),
        ),
        patch("app.routers.simulation.settings") as s,
    ):
        s.simulation_generation_timeout = 600
        r = _get(_client(kube))
    assert r.json()["status"] == "Generating"


def test_crashloop_pod_returns_error():
    kube = _kube(
        pod_status={
            "ready": False,
            "waiting_reason": "CrashLoopBackOff",
            "waiting_message": "no LLM_API_KEY",
        }
    )
    with (
        patch(
            "app.routers.simulation.get_simulation",
            new=AsyncMock(side_effect=sim_router.HarnessUnreachable("down")),
        ),
        patch("app.routers.simulation.settings") as s,
    ):
        s.simulation_generation_timeout = 600
        r = _get(_client(kube))
    body = r.json()
    assert body["status"] == "Error"
    assert "CrashLoopBackOff" in body["reason"]


def test_stalled_past_timeout_returns_failed():
    old = datetime.now(timezone.utc) - timedelta(seconds=900)
    kube = _kube(sts=_sts(created=old))
    with (
        patch(
            "app.routers.simulation.get_simulation",
            new=AsyncMock(side_effect=sim_router.HarnessNotFound()),
        ),
        patch("app.routers.simulation.settings") as s,
    ):
        s.simulation_generation_timeout = 600
        r = _get(_client(kube))
    assert r.json() == {"status": "Failed", "reason": "generation_stalled", "mcpUrl": None}


def test_unknown_workload_returns_404():
    kube = _kube(sts_exc=ApiException(status=404))
    r = _get(_client(kube))
    assert r.status_code == 404


def test_harness_http_error_degrades_to_pod_state():
    import httpx as _httpx

    kube = _kube()
    err = _httpx.HTTPStatusError("500", request=None, response=None)
    with (
        patch("app.routers.simulation.get_simulation", new=AsyncMock(side_effect=err)),
        patch("app.routers.simulation.settings") as s,
    ):
        s.simulation_generation_timeout = 600
        r = _get(_client(kube))
    assert r.status_code == 200
    assert r.json()["status"] == "Generating"
