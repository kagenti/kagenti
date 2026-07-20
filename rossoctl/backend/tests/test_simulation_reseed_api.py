# Copyright 2025 IBM Corp.
# Licensed under the Apache License, Version 2.0

"""Tests for simulated-tool database re-seed endpoint (issue #2164)."""

import json
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


def _kube(sts=None, sts_exc=None):
    k = MagicMock()
    if sts_exc is not None:
        k.apps_api.read_namespaced_stateful_set.side_effect = sts_exc
    else:
        k.apps_api.read_namespaced_stateful_set.return_value = sts if sts is not None else _sts()
    return k


def _client(kube):
    app = FastAPI()
    app.include_router(sim_router.router)
    app.dependency_overrides[get_kubernetes_service] = lambda: kube
    return app


def _put(app, body, ns="team1", name="petstore"):
    with patch("app.core.auth.settings") as auth:
        auth.enable_auth = False
        return TestClient(app).put(f"/simulation/tools/{ns}/{name}/database", json=body)


def _valid_body(db=None):
    return {"database": json.dumps(db if db is not None else {"pets": []})}


def test_reseed_happy_path_forwards_parsed_dict():
    kube = _kube()
    put = AsyncMock(return_value=(200, {"message": "Database replaced; simulation reset"}))
    with patch("app.routers.simulation.put_database", new=put):
        r = _put(_client(kube), _valid_body({"pets": [{"id": 1}]}))
    assert r.status_code == 200
    assert r.json()["success"] is True
    # forwarded the PARSED object, not the raw string
    args = put.call_args.args
    assert args[1] == {"pets": [{"id": 1}]}


def test_reseed_malformed_json_returns_422_without_harness_call():
    kube = _kube()
    put = AsyncMock()
    with patch("app.routers.simulation.put_database", new=put):
        r = _put(_client(kube), {"database": "{not json"})
    assert r.status_code == 422
    put.assert_not_called()


def test_reseed_non_object_json_returns_422_without_harness_call():
    kube = _kube()
    put = AsyncMock()
    with patch("app.routers.simulation.put_database", new=put):
        r = _put(_client(kube), {"database": "[1, 2, 3]"})
    assert r.status_code == 422
    put.assert_not_called()


def test_reseed_harness_422_returns_422_with_json_path():
    kube = _kube()
    put = AsyncMock(return_value=(422, {"detail": "bad type", "json_path": "$.pets[0].id"}))
    with patch("app.routers.simulation.put_database", new=put):
        r = _put(_client(kube), _valid_body())
    assert r.status_code == 422
    detail = r.json()["detail"]
    assert detail["json_path"] == "$.pets[0].id"
    assert detail["message"] == "bad type"


def test_reseed_harness_409_returns_409():
    kube = _kube()
    put = AsyncMock(return_value=(409, {}))
    with patch("app.routers.simulation.put_database", new=put):
        r = _put(_client(kube), _valid_body())
    assert r.status_code == 409


def test_reseed_harness_404_returns_409():
    kube = _kube()
    put = AsyncMock(return_value=(404, {}))
    with patch("app.routers.simulation.put_database", new=put):
        r = _put(_client(kube), _valid_body())
    assert r.status_code == 409


def test_reseed_harness_503_returns_409():
    kube = _kube()
    put = AsyncMock(return_value=(503, {}))
    with patch("app.routers.simulation.put_database", new=put):
        r = _put(_client(kube), _valid_body())
    assert r.status_code == 409


def test_reseed_unreachable_returns_502():
    kube = _kube()
    put = AsyncMock(side_effect=sim_router.HarnessUnreachable("down"))
    with patch("app.routers.simulation.put_database", new=put):
        r = _put(_client(kube), _valid_body())
    assert r.status_code == 502


def test_reseed_unexpected_status_returns_502():
    kube = _kube()
    put = AsyncMock(return_value=(500, {}))
    with patch("app.routers.simulation.put_database", new=put):
        r = _put(_client(kube), _valid_body())
    assert r.status_code == 502


def test_reseed_missing_statefulset_returns_404():
    kube = _kube(sts_exc=ApiException(status=404))
    put = AsyncMock()
    with patch("app.routers.simulation.put_database", new=put):
        r = _put(_client(kube), _valid_body())
    assert r.status_code == 404
    put.assert_not_called()


def test_reseed_non_simulated_returns_404():
    kube = _kube(sts=_sts(simulated=False))
    put = AsyncMock()
    with patch("app.routers.simulation.put_database", new=put):
        r = _put(_client(kube), _valid_body())
    assert r.status_code == 404
    put.assert_not_called()


def test_reseed_invalid_name_returns_404_without_backend_calls():
    kube = _kube()
    put = AsyncMock()
    with patch("app.routers.simulation.put_database", new=put):
        r = _put(_client(kube), _valid_body(), name="Bad_Name")
    assert r.status_code == 404
    kube.apps_api.read_namespaced_stateful_set.assert_not_called()
    put.assert_not_called()
