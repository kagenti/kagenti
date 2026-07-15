# Copyright 2025 IBM Corp.
# Licensed under the Apache License, Version 2.0

"""Tests for the simulated-tools feature flag and flagged simulation router (issue #2160)."""

from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routers import config as config_router
from app.routers import simulation as simulation_router
from app.services.kubernetes import get_kubernetes_service


def _make_config_app(simulated_tools: bool) -> FastAPI:
    """Build an app with only the config router, feature flags mocked."""
    app = FastAPI()
    app.include_router(config_router.router)

    # Feature flags are read straight off `settings` in get_feature_flags.
    mock_settings = MagicMock()
    mock_settings.kagenti_feature_flag_sandbox = False
    mock_settings.kagenti_feature_flag_integrations = False
    mock_settings.kagenti_feature_flag_triggers = False
    mock_settings.kagenti_feature_flag_agent_sandbox = False
    mock_settings.kagenti_feature_flag_skills = False
    mock_settings.kagenti_feature_flag_external_skills = False
    mock_settings.kagenti_feature_flag_authbridge_api = False
    mock_settings.kagenti_feature_flag_admin = False
    mock_settings.kagenti_feature_flag_agent_import_defaults = False
    mock_settings.kagenti_feature_flag_simulated_tools = simulated_tools

    # get_feature_flags depends on the k8s service only to probe the `builds` flag.
    mock_kube = MagicMock()
    mock_kube.api_group_exists.return_value = False
    app.dependency_overrides[get_kubernetes_service] = lambda: mock_kube

    app.state._mock_settings = mock_settings  # keep a reference alive for the patch
    return app


class TestSimulatedToolsFeatureFlag:
    def test_features_reports_false_when_flag_off(self):
        app = _make_config_app(simulated_tools=False)
        with patch("app.routers.config.settings", app.state._mock_settings):
            r = TestClient(app).get("/config/features")
        assert r.status_code == 200
        assert r.json()["simulatedTools"] is False

    def test_features_reports_true_when_flag_on(self):
        app = _make_config_app(simulated_tools=True)
        with patch("app.routers.config.settings", app.state._mock_settings):
            r = TestClient(app).get("/config/features")
        assert r.status_code == 200
        assert r.json()["simulatedTools"] is True


class TestSimulationRouterScaffold:
    def test_health_endpoint_returns_ok_when_mounted(self):
        app = FastAPI()
        app.include_router(simulation_router.router)
        r = TestClient(app).get("/simulation/health")
        assert r.status_code == 200
        assert r.json() == {"status": "ok"}

    def test_no_simulation_routes_when_router_not_mounted(self):
        # Mirrors flag-off: the router is simply never included.
        app = FastAPI()
        r = TestClient(app).get("/simulation/health")
        assert r.status_code == 404


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
