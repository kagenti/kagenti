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
    store_ui_url=None,
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
    if store_ui_url:
        cm.data["store-ui-url"] = store_ui_url
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
    # Patch DNS so that test URLs (e.g. http://reg:8000) pass the SSRF hostname check
    # without requiring real network access. Tests here exercise handler logic, not
    # the URL validator (which has its own dedicated test).
    public_addr = [(None, None, None, None, ("93.184.216.34", 0))]
    with (
        patch("app.routers.skills.settings") as mock_settings,
        patch("app.routers.skills.socket.getaddrinfo", return_value=public_addr),
    ):
        mock_settings.kagenti_feature_flag_external_skills = True
        mock_settings.kagenti_feature_flag_skills = True
        mock_settings.skill_registry_allowed_hosts = ""
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
            last_synced_at="2026-06-17T10:00:00Z",
            skill_count=5,
            store_ui_url="http://skillberry-store.localtest.me:8080",
        )
        resp = client.get("/api/v1/skills/autosync")
        assert resp.status_code == 200
        body = resp.json()
        assert body["enabled"] is True
        assert body["registryUrl"] == "http://reg:8000"
        assert body["storeUiUrl"] == "http://skillberry-store.localtest.me:8080"
        assert body["syncInterval"] == 30
        assert body["skillCount"] == 5

    def test_store_ui_url_absent_when_not_configured(self, client, kube):
        kube.core_api.read_namespaced_config_map.return_value = _make_autosync_cm()
        resp = client.get("/api/v1/skills/autosync")
        assert resp.status_code == 200
        assert resp.json()["storeUiUrl"] is None


class TestEnableAutoSync:
    def test_returns_409_when_skills_exist(self, client, kube):
        kube.core_api.read_namespaced_config_map.side_effect = ApiException(status=404)
        skill_cm = MagicMock()
        skill_cm.items = [MagicMock()]
        kube.core_api.list_namespaced_config_map.return_value = skill_cm
        resp = client.post(
            "/api/v1/skills/autosync",
            json={
                "registryUrl": "http://reg:8000",
                "registryType": "skillberry",
                "syncInterval": 30,
            },
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
            json={
                "registryUrl": "http://reg:8000",
                "registryType": "skillberry",
                "syncInterval": 30,
            },
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


def _addrinfo(ip):
    """Build a getaddrinfo-style result resolving to a single IP."""
    return [(None, None, None, None, (ip, 0))]


class TestValidateRegistryUrl:
    """Unit tests for the registry-URL SSRF validator and its allow-list."""

    def _validate(self, url, allowed, ip):
        from app.routers import skills

        mock_settings = MagicMock()
        mock_settings.skill_registry_allowed_hosts = allowed
        with (
            patch.object(skills, "settings", mock_settings),
            patch("app.routers.skills.socket.getaddrinfo", return_value=_addrinfo(ip)),
        ):
            return skills._validate_registry_url(url)

    def test_public_address_passes(self):
        assert (
            self._validate("https://skillberry.example.com", "", "93.184.216.34")
            == "https://skillberry.example.com"
        )

    def test_private_address_blocked_by_default(self):
        with pytest.raises(ValueError, match="private/internal"):
            self._validate("http://192.168.50.16:8000", "", "192.168.50.16")

    def test_private_address_allowed_by_ip(self):
        url = "http://192.168.50.16:8000"
        assert self._validate(url, "192.168.50.16", "192.168.50.16") == url

    def test_private_address_allowed_by_cidr(self):
        url = "http://192.168.50.16:8000"
        assert self._validate(url, "10.0.0.0/8,192.168.0.0/16", "192.168.50.16") == url

    def test_private_address_allowed_by_hostname(self):
        url = "http://reg.svc.cluster.local:8000"
        assert self._validate(url, "reg.svc.cluster.local", "10.96.0.5") == url

    def test_non_matching_allowlist_still_blocks(self):
        with pytest.raises(ValueError, match="private/internal"):
            self._validate("http://192.168.50.16:8000", "10.0.0.0/8", "192.168.50.16")

    def test_non_http_scheme_rejected(self):
        with pytest.raises(ValueError, match="http"):
            self._validate("ftp://192.168.50.16", "192.168.50.16", "192.168.50.16")
