# Copyright 2025 IBM Corp.
# Licensed under the Apache License, Version 2.0

"""Regression: generic delete_tool cleans up StatefulSet PVCs (issue #2163)."""

from unittest.mock import MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from kubernetes.client import ApiException

from app.routers import tools as tools_router
from app.services.kubernetes import get_kubernetes_service


def _kube(pvcs):
    k = MagicMock()
    # No Shipwright builds / buildruns.
    k.list_custom_resources.return_value = []
    k.delete_custom_resource.side_effect = ApiException(status=404)
    # Deployment absent; StatefulSet present.
    k.delete_deployment.side_effect = ApiException(status=404)
    k.list_statefulset_pvcs.return_value = pvcs
    return k


def _client(kube):
    app = FastAPI()
    app.include_router(tools_router.router)
    app.dependency_overrides[get_kubernetes_service] = lambda: kube
    return app


def _delete(app, ns="team1", name="petstore"):
    with patch("app.core.auth.settings") as auth:
        auth.enable_auth = False
        return TestClient(app).delete(f"/tools/{ns}/{name}")


def test_delete_tool_removes_statefulset_pvcs():
    kube = _kube(pvcs=["data-petstore-0"])
    r = _delete(_client(kube))
    assert r.status_code == 200
    # tools.DeleteResponse has only {success, message}; the resource list is
    # embedded in the message string.
    assert "PersistentVolumeClaim/data-petstore-0" in r.json()["message"]
    kube.delete_persistent_volume_claim.assert_called_once_with("team1", "data-petstore-0")


def test_delete_tool_deployment_deletes_no_pvcs():
    kube = _kube(pvcs=[])  # a Deployment tool has no StatefulSet PVCs
    r = _delete(_client(kube))
    assert r.status_code == 200
    kube.delete_persistent_volume_claim.assert_not_called()
