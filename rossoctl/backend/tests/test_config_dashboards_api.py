# Copyright 2025 IBM Corp.
# Licensed under the Apache License, Version 2.0

"""Tests for GET /api/config/dashboards."""

from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routers import config as config_router


@pytest.fixture
def config_app():
    app = FastAPI()
    app.include_router(config_router.router)
    return app


class TestGetDashboardConfig:
    def test_mcp_inspector_null_when_not_configured(self, config_app):
        with (
            patch("app.core.auth.settings") as mock_auth,
            patch("app.routers.config.settings") as mock_settings,
        ):
            mock_auth.enable_auth = False
            mock_settings.domain_name = "localtest.me"
            mock_settings.mcp_inspector_url = ""
            mock_settings.mcp_proxy_full_address = ""
            mock_settings.traces_dashboard_url = ""
            mock_settings.network_dashboard_url = ""
            mock_settings.mlflow_dashboard_url = ""
            mock_settings.trace_analysis_dashboard_url = ""
            mock_settings.keycloak_console_url = ""
            mock_settings.effective_keycloak_url = "http://keycloak.localtest.me:8080"
            mock_settings.effective_keycloak_realm = "rossoctl"

            tc = TestClient(config_app)
            r = tc.get("/config/dashboards")

        assert r.status_code == 200
        data = r.json()
        assert data["mcpInspector"] is None
        assert data["mcpProxy"] is None

    def test_mcp_inspector_url_when_configured(self, config_app):
        inspector_url = "http://mcp-inspector.example.com:8080"
        proxy_url = "http://mcp-proxy.example.com:8080"

        with (
            patch("app.core.auth.settings") as mock_auth,
            patch("app.routers.config.settings") as mock_settings,
        ):
            mock_auth.enable_auth = False
            mock_settings.domain_name = "localtest.me"
            mock_settings.mcp_inspector_url = inspector_url
            mock_settings.mcp_proxy_full_address = proxy_url
            mock_settings.traces_dashboard_url = ""
            mock_settings.network_dashboard_url = ""
            mock_settings.mlflow_dashboard_url = ""
            mock_settings.trace_analysis_dashboard_url = ""
            mock_settings.keycloak_console_url = ""
            mock_settings.effective_keycloak_url = "http://keycloak.localtest.me:8080"
            mock_settings.effective_keycloak_realm = "rossoctl"

            tc = TestClient(config_app)
            r = tc.get("/config/dashboards")

        assert r.status_code == 200
        data = r.json()
        assert data["mcpInspector"] == inspector_url
        assert data["mcpProxy"] == proxy_url
