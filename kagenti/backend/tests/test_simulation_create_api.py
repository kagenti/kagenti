# Copyright 2025 IBM Corp.
# Licensed under the Apache License, Version 2.0

"""Tests for POST /simulation/tools (issue #2161)."""

from unittest.mock import MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from kubernetes.client import ApiException

from app.routers import simulation as sim_router
from app.services.kubernetes import get_kubernetes_service

VALID_SPEC = '{"openapi": "3.0.0", "info": {"title": "Pet Store"}, "paths": {}}'


def _client(kube):
    app = FastAPI()
    app.include_router(sim_router.router)
    app.dependency_overrides[get_kubernetes_service] = lambda: kube
    return TestClient(app)


def _kube():
    k = MagicMock()
    k.ensure_service_account.return_value = None
    k.create_statefulset.return_value = {}
    k.create_service.return_value = {}
    return k


def test_create_returns_202_and_provisions_workload():
    kube = _kube()
    with patch("app.core.auth.settings") as auth, patch("app.routers.simulation.settings") as s:
        auth.enable_auth = False
        s.simulation_harness_image = "ghcr.io/kagenti/simulation-harness:latest"
        r = _client(kube).post(
            "/simulation/tools",
            json={"namespace": "team1", "openapiSpec": VALID_SPEC},
        )
    assert r.status_code == 202
    body = r.json()
    assert body["status"] == "Generating"
    assert body["name"] == "pet-store"
    kube.create_statefulset.assert_called_once()
    kube.create_service.assert_called_once()


def test_create_rejects_invalid_spec_with_422_and_no_workload():
    kube = _kube()
    with patch("app.core.auth.settings") as auth:
        auth.enable_auth = False
        r = _client(kube).post(
            "/simulation/tools",
            json={"namespace": "team1", "openapiSpec": "not json"},
        )
    assert r.status_code == 422
    kube.create_statefulset.assert_not_called()


def test_create_wires_image_pull_secret_into_statefulset():
    kube = _kube()
    with patch("app.core.auth.settings") as auth, patch("app.routers.simulation.settings") as s:
        auth.enable_auth = False
        s.simulation_harness_image = "ghcr.io/kagenti/simulation-harness:latest"
        s.simulation_image_pull_secret = "ghcr-secret"
        r = _client(kube).post(
            "/simulation/tools",
            json={"namespace": "team1", "openapiSpec": VALID_SPEC},
        )
    assert r.status_code == 202
    sts = kube.create_statefulset.call_args.args[1]
    assert sts["spec"]["template"]["spec"]["imagePullSecrets"] == [{"name": "ghcr-secret"}]


def test_create_omits_image_pull_secret_when_setting_empty():
    kube = _kube()
    with patch("app.core.auth.settings") as auth, patch("app.routers.simulation.settings") as s:
        auth.enable_auth = False
        s.simulation_harness_image = "ghcr.io/kagenti/simulation-harness:latest"
        s.simulation_image_pull_secret = ""
        r = _client(kube).post(
            "/simulation/tools",
            json={"namespace": "team1", "openapiSpec": VALID_SPEC},
        )
    assert r.status_code == 202
    sts = kube.create_statefulset.call_args.args[1]
    assert "imagePullSecrets" not in sts["spec"]["template"]["spec"]


def test_create_conflict_returns_409():
    kube = _kube()
    kube.create_statefulset.side_effect = ApiException(status=409)
    with patch("app.core.auth.settings") as auth, patch("app.routers.simulation.settings") as s:
        auth.enable_auth = False
        s.simulation_harness_image = "img"
        r = _client(kube).post(
            "/simulation/tools",
            json={"namespace": "team1", "openapiSpec": VALID_SPEC, "name": "dup"},
        )
    assert r.status_code == 409


def test_route_absent_when_flag_off():
    """With the flag off, main.py never mounts the router (see #2160)."""
    import app.main

    r = TestClient(app.main.app).post("/api/v1/simulation/tools", json={})
    assert r.status_code == 404


def test_create_rejects_invalid_namespace_with_422():
    kube = _kube()
    with patch("app.core.auth.settings") as auth:
        auth.enable_auth = False
        r = _client(kube).post(
            "/simulation/tools",
            json={"namespace": "Bad_NS", "openapiSpec": VALID_SPEC},
        )
    assert r.status_code == 422
    kube.create_statefulset.assert_not_called()


def test_create_rejects_invalid_storage_size_with_422():
    kube = _kube()
    with patch("app.core.auth.settings") as auth:
        auth.enable_auth = False
        r = _client(kube).post(
            "/simulation/tools",
            json={"namespace": "team1", "openapiSpec": VALID_SPEC, "storageSize": "big"},
        )
    assert r.status_code == 422
    kube.create_statefulset.assert_not_called()


def test_create_rejects_invalid_custom_name_with_422():
    kube = _kube()
    with patch("app.core.auth.settings") as auth:
        auth.enable_auth = False
        r = _client(kube).post(
            "/simulation/tools",
            json={"namespace": "team1", "openapiSpec": VALID_SPEC, "name": "Bad Name!"},
        )
    assert r.status_code == 422
    kube.create_statefulset.assert_not_called()


def test_create_spawns_generation_trigger():
    kube = _kube()
    saved = set(sim_router._generation_tasks)
    try:
        with (
            patch("app.core.auth.settings") as auth,
            patch("app.routers.simulation.settings") as s,
            patch("app.routers.simulation._run_generation_trigger", new=MagicMock()) as trig,
        ):
            auth.enable_auth = False
            s.simulation_harness_image = "img"
            # _run_generation_trigger is wrapped in asyncio.create_task; the MagicMock
            # returns a coroutine-like sentinel, so patch create_task to capture the call.
            with patch("app.routers.simulation.asyncio.create_task") as create_task:
                r = _client(kube).post(
                    "/simulation/tools",
                    json={"namespace": "team1", "openapiSpec": VALID_SPEC},
                )
        assert r.status_code == 202
        create_task.assert_called_once()
        trig.assert_called_once()
        ns, name, spec, port = trig.call_args.args
        assert ns == "team1"
        assert name == "pet-store"
    finally:
        sim_router._generation_tasks.clear()
        sim_router._generation_tasks.update(saved)
