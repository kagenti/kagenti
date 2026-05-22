# Copyright 2025 IBM Corp.
# Licensed under the Apache License, Version 2.0

"""
Tests for dashboard configuration endpoint.

Validates Phoenix optional component behavior: when TRACES_DASHBOARD_URL
is unset or empty, the /config/dashboards endpoint returns an empty traces URL
instead of a fallback Phoenix URL.
"""

from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routers.config import router


@pytest.fixture
def client():
    """Create a test client with the config router."""
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    return TestClient(app)


class TestDashboardConfigPhoenixToggle:
    """Test /config/dashboards response when Phoenix is disabled or enabled."""

    def test_traces_dashboard_url_empty(self, client):
        """When TRACES_DASHBOARD_URL is not set, traces should be empty string."""
        with patch("app.core.auth.settings") as mock_auth_settings:
            mock_auth_settings.enable_auth = False
            with patch("app.routers.config.settings") as mock_settings:
                mock_settings.traces_dashboard_url = ""
                mock_settings.network_dashboard_url = ""
                mock_settings.mlflow_dashboard_url = ""
                mock_settings.mcp_inspector_url = ""
                mock_settings.mcp_proxy_full_address = ""
                mock_settings.keycloak_console_url = ""
                mock_settings.domain_name = "localtest.me"
                mock_settings.effective_keycloak_url = "http://keycloak.localtest.me:8080"
                mock_settings.effective_keycloak_realm = "kagenti"

                response = client.get("/api/v1/config/dashboards")
                assert response.status_code == 200
                data = response.json()
                assert data["traces"] == ""
                assert "phoenix" not in data["traces"]

    def test_traces_dashboard_url_non_empty(self, client):
        """When TRACES_DASHBOARD_URL is set, it should be returned."""
        phoenix_url = "http://phoenix.localtest.me:8080"
        with patch("app.core.auth.settings") as mock_auth_settings:
            mock_auth_settings.enable_auth = False
            with patch("app.routers.config.settings") as mock_settings:
                mock_settings.traces_dashboard_url = phoenix_url
                mock_settings.network_dashboard_url = ""
                mock_settings.mlflow_dashboard_url = ""
                mock_settings.mcp_inspector_url = ""
                mock_settings.mcp_proxy_full_address = ""
                mock_settings.keycloak_console_url = ""
                mock_settings.domain_name = "localtest.me"
                mock_settings.effective_keycloak_url = "http://keycloak.localtest.me:8080"
                mock_settings.effective_keycloak_realm = "kagenti"

                response = client.get("/api/v1/config/dashboards")
                assert response.status_code == 200
                data = response.json()
                assert data["traces"] == phoenix_url

    def test_mlflow_dashboard_url_non_empty(self, client):
        """When MLFLOW_DASHBOARD_URL is set, it should be returned."""
        mlflow_url = "http://mlflow.localtest.me:8080"
        with patch("app.core.auth.settings") as mock_auth_settings:
            mock_auth_settings.enable_auth = False
            with patch("app.routers.config.settings") as mock_settings:
                mock_settings.traces_dashboard_url = ""
                mock_settings.network_dashboard_url = ""
                mock_settings.mlflow_dashboard_url = mlflow_url
                mock_settings.mcp_inspector_url = ""
                mock_settings.mcp_proxy_full_address = ""
                mock_settings.keycloak_console_url = ""
                mock_settings.domain_name = "localtest.me"
                mock_settings.effective_keycloak_url = "http://keycloak.localtest.me:8080"
                mock_settings.effective_keycloak_realm = "kagenti"

                response = client.get("/api/v1/config/dashboards")
                assert response.status_code == 200
                data = response.json()
                assert data["mlflow"] == mlflow_url
