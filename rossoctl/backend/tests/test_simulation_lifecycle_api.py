# Copyright 2025 IBM Corp.
# Licensed under the Apache License, Version 2.0

"""Tests for simulated-tool lifecycle endpoints — stop/start/reset/delete (issue #2163)."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from kubernetes.client import ApiException

from app.routers import simulation as sim_router
from app.services.kubernetes import get_kubernetes_service


def _sts(name="petstore", namespace="team1", simulated=True):
    labels = {"rossoctl.io/simulated": "true"} if simulated else {"app.kubernetes.io/name": name}
    return SimpleNamespace(
        metadata=SimpleNamespace(name=name, namespace=namespace, labels=labels),
        spec=SimpleNamespace(replicas=1),
    )


def _kube(sts=None, sts_exc=None, pvcs=None):
    k = MagicMock()
    if sts_exc is not None:
        k.apps_api.read_namespaced_stateful_set.side_effect = sts_exc
    else:
        k.apps_api.read_namespaced_stateful_set.return_value = sts if sts is not None else _sts()
    k.list_statefulset_pvcs.return_value = pvcs if pvcs is not None else ["data-petstore-0"]
    return k


def _client(kube):
    app = FastAPI()
    app.include_router(sim_router.router)
    app.dependency_overrides[get_kubernetes_service] = lambda: kube
    return app


def _post(app, action, ns="team1", name="petstore"):
    with patch("app.core.auth.settings") as auth:
        auth.enable_auth = False
        return TestClient(app).post(f"/simulation/tools/{ns}/{name}/{action}")


# ---- stop / start ----


def test_stop_scales_to_zero():
    kube = _kube()
    r = _post(_client(kube), "stop")
    assert r.status_code == 200
    assert r.json()["status"] == "Stopped"
    kube.patch_statefulset.assert_called_once_with("team1", "petstore", {"spec": {"replicas": 0}})


def test_start_scales_to_one():
    kube = _kube()
    r = _post(_client(kube), "start")
    assert r.status_code == 200
    assert r.json()["status"] == "Starting"
    kube.patch_statefulset.assert_called_once_with("team1", "petstore", {"spec": {"replicas": 1}})


def test_stop_missing_statefulset_returns_404():
    kube = _kube(sts_exc=ApiException(status=404))
    r = _post(_client(kube), "stop")
    assert r.status_code == 404
    kube.patch_statefulset.assert_not_called()


def test_stop_non_simulated_statefulset_returns_404():
    kube = _kube(sts=_sts(simulated=False))
    r = _post(_client(kube), "stop")
    assert r.status_code == 404
    kube.patch_statefulset.assert_not_called()


def test_stop_read_error_returns_502():
    kube = _kube(sts_exc=ApiException(status=403))
    r = _post(_client(kube), "stop")
    assert r.status_code == 502


def test_stop_patch_error_returns_502():
    kube = _kube()
    kube.patch_statefulset.side_effect = ApiException(status=500)
    r = _post(_client(kube), "stop")
    assert r.status_code == 502


def test_stop_invalid_name_returns_404_without_backend_calls():
    kube = _kube()
    r = _post(_client(kube), "stop", name="Bad_Name")
    assert r.status_code == 404
    kube.apps_api.read_namespaced_stateful_set.assert_not_called()


# ---- reset ----


def test_reset_success_returns_200():
    kube = _kube()
    with patch("app.routers.simulation.reset_simulation", new=AsyncMock(return_value=200)):
        r = _post(_client(kube), "reset")
    assert r.status_code == 200
    assert r.json()["success"] is True


def test_reset_harness_404_returns_409():
    kube = _kube()
    with patch("app.routers.simulation.reset_simulation", new=AsyncMock(return_value=404)):
        r = _post(_client(kube), "reset")
    assert r.status_code == 409


def test_reset_harness_503_returns_409():
    kube = _kube()
    with patch("app.routers.simulation.reset_simulation", new=AsyncMock(return_value=503)):
        r = _post(_client(kube), "reset")
    assert r.status_code == 409


def test_reset_unreachable_returns_502():
    kube = _kube()
    with patch(
        "app.routers.simulation.reset_simulation",
        new=AsyncMock(side_effect=sim_router.HarnessUnreachable("down")),
    ):
        r = _post(_client(kube), "reset")
    assert r.status_code == 502


def test_reset_non_simulated_returns_404():
    kube = _kube(sts=_sts(simulated=False))
    reset = AsyncMock()
    with patch("app.routers.simulation.reset_simulation", new=reset):
        r = _post(_client(kube), "reset")
    assert r.status_code == 404
    reset.assert_not_called()


# ---- delete ----


def _delete(app, ns="team1", name="petstore"):
    with patch("app.core.auth.settings") as auth:
        auth.enable_auth = False
        return TestClient(app).delete(f"/simulation/tools/{ns}/{name}")


def test_delete_removes_statefulset_service_and_pvcs():
    kube = _kube(pvcs=["data-petstore-0"])
    r = _delete(_client(kube))
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is True
    assert "StatefulSet/petstore" in body["deletedResources"]
    assert "AgentRuntime/petstore" in body["deletedResources"]
    assert "Service/petstore-mcp" in body["deletedResources"]
    assert "PersistentVolumeClaim/data-petstore-0" in body["deletedResources"]
    kube.delete_statefulset.assert_called_once_with("team1", "petstore")
    kube.delete_service.assert_called_once_with("team1", "petstore-mcp")
    kube.delete_persistent_volume_claim.assert_called_once_with("team1", "data-petstore-0")
    # AgentRuntime CR removed (adopted-workload teardown).
    args = kube.delete_custom_resource.call_args.args
    assert args[2] == "team1" and args[4] == "petstore"


def test_delete_is_idempotent_on_missing_service_and_pvc():
    kube = _kube(pvcs=["data-petstore-0"])
    kube.delete_service.side_effect = ApiException(status=404)
    kube.delete_persistent_volume_claim.side_effect = ApiException(status=404)
    r = _delete(_client(kube))
    assert r.status_code == 200
    assert "StatefulSet/petstore" in r.json()["deletedResources"]


def test_delete_missing_statefulset_returns_404():
    kube = _kube(sts_exc=ApiException(status=404))
    r = _delete(_client(kube))
    assert r.status_code == 404
    kube.delete_statefulset.assert_not_called()


def test_delete_non_simulated_returns_404():
    kube = _kube(sts=_sts(simulated=False))
    r = _delete(_client(kube))
    assert r.status_code == 404
    kube.delete_statefulset.assert_not_called()


def test_delete_removes_multiple_pvcs_in_order():
    # Two PVCs prove per-iteration closure binding (a late-binding bug would
    # target the last name twice).
    from unittest.mock import call

    kube = _kube(pvcs=["data-petstore-0", "data-petstore-1"])
    r = _delete(_client(kube))
    assert r.status_code == 200
    body = r.json()
    assert "PersistentVolumeClaim/data-petstore-0" in body["deletedResources"]
    assert "PersistentVolumeClaim/data-petstore-1" in body["deletedResources"]
    assert kube.delete_persistent_volume_claim.call_args_list == [
        call("team1", "data-petstore-0"),
        call("team1", "data-petstore-1"),
    ]


def test_delete_all_404_still_returns_200():
    kube = _kube(pvcs=["data-petstore-0"])
    kube.delete_statefulset.side_effect = ApiException(status=404)
    kube.delete_custom_resource.side_effect = ApiException(status=404)
    kube.delete_service.side_effect = ApiException(status=404)
    kube.delete_persistent_volume_claim.side_effect = ApiException(status=404)
    r = _delete(_client(kube))
    assert r.status_code == 200
    assert r.json()["deletedResources"] == []


def test_delete_pvc_list_error_returns_502():
    kube = _kube(pvcs=["data-petstore-0"])
    kube.list_statefulset_pvcs.side_effect = ApiException(status=403)
    r = _delete(_client(kube))
    assert r.status_code == 502
    kube.delete_statefulset.assert_not_called()
