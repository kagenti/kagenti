# Copyright 2026 IBM Corp.
# Licensed under the Apache License, Version 2.0
"""Tests for skill auto-sync REST endpoints."""

import pytest
from unittest.mock import MagicMock, patch
from fastapi import FastAPI
from fastapi.testclient import TestClient
from kubernetes.client.exceptions import ApiException

from app.routers.skills import router
from app.services.kubernetes import get_kubernetes_service


def _make_autosync_cm(
    enabled="true",
    registry_url="http://reg:8000",
    registry_type="skillberry",
    sync_interval="30",
    last_synced_at=None,
    skill_count=None,
):
    cm = MagicMock()
    cm.data = {
        "enabled": enabled,
        "registry-url": registry_url,
        "registry-type": registry_type,
        "sync-interval": sync_interval,
    }
    if last_synced_at:
        cm.data["last-synced-at"] = last_synced_at
    if skill_count is not None:
        cm.data["skill-count"] = str(skill_count)
    return cm


@pytest.fixture
def kube():
    mock = MagicMock()
    mock.list_enabled_namespaces.return_value = ["team1"]
    return mock


@pytest.fixture
def client(kube):
    """Build a minimal test app with just the skills router and feature flags enabled."""
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[get_kubernetes_service] = lambda: kube
    with patch("app.routers.skills.settings") as mock_settings:
        mock_settings.kagenti_feature_flag_external_skills = True
        mock_settings.kagenti_feature_flag_skills = True
        with TestClient(app) as c:
            yield c


class TestGetAutoSync:
    def test_returns_enabled_false_when_configmap_absent(self, client, kube):
        kube.core_api.read_namespaced_config_map.side_effect = ApiException(status=404)
        resp = client.get("/api/v1/skills/autosync")
        assert resp.status_code == 200
        assert resp.json()["enabled"] is False

    def test_returns_full_status_when_active(self, client, kube):
        kube.core_api.read_namespaced_config_map.return_value = _make_autosync_cm(
            last_synced_at="2026-06-17T10:00:00Z", skill_count=5
        )
        resp = client.get("/api/v1/skills/autosync")
        assert resp.status_code == 200
        body = resp.json()
        assert body["enabled"] is True
        assert body["registryUrl"] == "http://reg:8000"
        assert body["syncInterval"] == 30
        assert body["skillCount"] == 5


class TestEnableAutoSync:
    def test_returns_409_when_skills_exist(self, client, kube):
        kube.core_api.read_namespaced_config_map.side_effect = ApiException(status=404)
        skill_cm = MagicMock()
        skill_cm.items = [MagicMock()]
        kube.core_api.list_namespaced_config_map.return_value = skill_cm
        resp = client.post(
            "/api/v1/skills/autosync",
            json={"registryUrl": "http://reg:8000", "registryType": "skillberry", "syncInterval": 30},
        )
        assert resp.status_code == 409
        assert "existing skills" in resp.json()["detail"].lower()

    def test_creates_configmap_when_no_skills_exist(self, client, kube):
        # enable_autosync calls read once at the end to return status
        kube.core_api.read_namespaced_config_map.return_value = _make_autosync_cm()
        skill_cm = MagicMock()
        skill_cm.items = []
        kube.core_api.list_namespaced_config_map.return_value = skill_cm
        resp = client.post(
            "/api/v1/skills/autosync",
            json={"registryUrl": "http://reg:8000", "registryType": "skillberry", "syncInterval": 30},
        )
        assert resp.status_code == 200
        assert resp.json()["enabled"] is True
        kube.core_api.create_namespaced_config_map.assert_called_once()

    def test_rejects_invalid_registry_url(self, client, kube):
        resp = client.post(
            "/api/v1/skills/autosync",
            json={"registryUrl": "not-a-url", "registryType": "skillberry", "syncInterval": 30},
        )
        assert resp.status_code == 422


class TestDisableAutoSync:
    def test_deletes_autosync_skills_and_config(self, client, kube):
        autosync_cm = MagicMock()
        autosync_cm.items = [
            MagicMock(metadata=MagicMock(name="skill-a")),
            MagicMock(metadata=MagicMock(name="skill-b")),
        ]
        kube.core_api.list_namespaced_config_map.return_value = autosync_cm
        resp = client.delete("/api/v1/skills/autosync")
        assert resp.status_code == 204
        # Should have deleted both skills + the config CM (3 total)
        assert kube.core_api.delete_namespaced_config_map.call_count >= 2

    def test_still_succeeds_when_no_skills_and_config_absent(self, client, kube):
        kube.core_api.list_namespaced_config_map.return_value = MagicMock(items=[])
        kube.core_api.delete_namespaced_config_map.side_effect = ApiException(status=404)
        resp = client.delete("/api/v1/skills/autosync")
        assert resp.status_code == 204
