# Copyright 2025 IBM Corp.
# Licensed under the Apache License, Version 2.0

"""
Tests for MCP Gateway status endpoint.

Validates that GET /config/mcp-gateway-status correctly reports the
MCP Gateway deployment state as Ready, Degraded, or Missing.
"""

from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from kubernetes.client import ApiException

from app.routers.config import router
from app.services.kubernetes import KubernetesService, get_kubernetes_service


@pytest.fixture
def mock_kube():
    """Create a mock KubernetesService."""
    return MagicMock(spec=KubernetesService)


@pytest.fixture
def client(mock_kube):
    """Create a test client with DI override for KubernetesService."""
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[get_kubernetes_service] = lambda: mock_kube
    yield TestClient(app)
    app.dependency_overrides.clear()


class TestMCPGatewayStatus:
    """Test /config/mcp-gateway-status endpoint."""

    def test_gateway_ready(self, client, mock_kube):
        """When mcp-gateway-istio deployment is ready, returns Ready."""
        mock_deployment = MagicMock()
        mock_deployment.spec.replicas = 1
        mock_deployment.status.ready_replicas = 1
        mock_kube.apps_api.read_namespaced_deployment.return_value = mock_deployment

        with patch("app.core.auth.settings") as mock_auth_settings:
            mock_auth_settings.enable_auth = False
            response = client.get("/api/v1/config/mcp-gateway-status")

        assert response.status_code == 200
        assert response.json() == {"status": "Ready"}
        mock_kube.apps_api.read_namespaced_deployment.assert_called_once_with(
            name="mcp-gateway-istio", namespace="gateway-system"
        )

    def test_gateway_missing(self, client, mock_kube):
        """When gateway-system namespace or deployment doesn't exist, returns Missing."""
        mock_kube.apps_api.read_namespaced_deployment.side_effect = ApiException(status=404)

        with patch("app.core.auth.settings") as mock_auth_settings:
            mock_auth_settings.enable_auth = False
            response = client.get("/api/v1/config/mcp-gateway-status")

        assert response.status_code == 200
        assert response.json() == {"status": "Missing"}

    def test_gateway_degraded(self, client, mock_kube):
        """When deployment exists but replicas aren't ready, returns Degraded."""
        mock_deployment = MagicMock()
        mock_deployment.spec.replicas = 2
        mock_deployment.status.ready_replicas = 1
        mock_kube.apps_api.read_namespaced_deployment.return_value = mock_deployment

        with patch("app.core.auth.settings") as mock_auth_settings:
            mock_auth_settings.enable_auth = False
            response = client.get("/api/v1/config/mcp-gateway-status")

        assert response.status_code == 200
        assert response.json() == {"status": "Degraded"}

    def test_gateway_degraded_on_api_error(self, client, mock_kube):
        """When K8s API returns non-404 error, returns Degraded."""
        mock_kube.apps_api.read_namespaced_deployment.side_effect = ApiException(status=503)

        with patch("app.core.auth.settings") as mock_auth_settings:
            mock_auth_settings.enable_auth = False
            response = client.get("/api/v1/config/mcp-gateway-status")

        assert response.status_code == 200
        assert response.json() == {"status": "Degraded"}
