# Copyright 2025 IBM Corp.
# Licensed under the Apache License, Version 2.0

"""Tests for effective_keycloak_url priority chain.

Priority: AUTH_ENDPOINT > KEYCLOAK_PUBLIC_URL > KEYCLOAK_URL > constructed default.
Fixes: https://github.com/kagenti/kagenti/issues/1154
"""

import pytest
from app.core.config import Settings


@pytest.fixture
def make_settings(monkeypatch):
    """Create Settings with specific env vars, clearing defaults."""

    def _make(**env_vars):
        monkeypatch.delenv("AUTH_ENDPOINT", raising=False)
        monkeypatch.delenv("KEYCLOAK_PUBLIC_URL", raising=False)
        monkeypatch.delenv("KEYCLOAK_URL", raising=False)
        monkeypatch.delenv("DOMAIN_NAME", raising=False)
        for k, v in env_vars.items():
            monkeypatch.setenv(k, v)
        return Settings()

    return _make


class TestEffectiveKeycloakUrl:
    """effective_keycloak_url must prefer browser-reachable URLs."""

    def test_auth_endpoint_wins(self, make_settings):
        s = make_settings(
            AUTH_ENDPOINT="https://kc.example.com/realms/kagenti/protocol/openid-connect/auth",
            KEYCLOAK_PUBLIC_URL="https://public.example.com",
            KEYCLOAK_URL="http://keycloak-service.keycloak:8080",
        )
        assert s.effective_keycloak_url == "https://kc.example.com"

    def test_public_url_when_no_auth_endpoint(self, make_settings):
        s = make_settings(
            KEYCLOAK_PUBLIC_URL="https://public.example.com",
            KEYCLOAK_URL="http://keycloak-service.keycloak:8080",
        )
        assert s.effective_keycloak_url == "https://public.example.com"

    def test_keycloak_url_as_last_resort(self, make_settings):
        s = make_settings(
            KEYCLOAK_URL="http://keycloak-service.keycloak:8080",
        )
        assert s.effective_keycloak_url == "http://keycloak-service.keycloak:8080"

    def test_constructed_default(self, make_settings):
        s = make_settings(DOMAIN_NAME="apps.cluster.example.com")
        assert s.effective_keycloak_url == "http://keycloak.apps.cluster.example.com:8080"

    def test_public_url_not_used_when_auth_endpoint_set(self, make_settings):
        s = make_settings(
            AUTH_ENDPOINT="https://route.example.com/realms/test/protocol/openid-connect/auth",
            KEYCLOAK_PUBLIC_URL="https://different.example.com",
        )
        assert s.effective_keycloak_url == "https://route.example.com"

    def test_malformed_auth_endpoint_falls_through(self, make_settings):
        s = make_settings(
            AUTH_ENDPOINT="not-a-url",
            KEYCLOAK_PUBLIC_URL="https://public.example.com",
        )
        assert s.effective_keycloak_url == "https://public.example.com"


class TestKeycloakInternalUrl:
    """keycloak_internal_url should use internal URL in-cluster."""

    def test_in_cluster_uses_keycloak_url(self, make_settings, monkeypatch):
        s = make_settings(
            KEYCLOAK_URL="http://keycloak-service.keycloak:8080",
            KEYCLOAK_PUBLIC_URL="https://public.example.com",
        )
        monkeypatch.setattr(type(s), "is_running_in_cluster", property(lambda self: True))
        assert s.keycloak_internal_url == "http://keycloak-service.keycloak:8080"

    def test_off_cluster_uses_effective(self, make_settings, monkeypatch):
        s = make_settings(
            KEYCLOAK_URL="http://keycloak-service.keycloak:8080",
            KEYCLOAK_PUBLIC_URL="https://public.example.com",
        )
        monkeypatch.setattr(type(s), "is_running_in_cluster", property(lambda self: False))
        assert s.keycloak_internal_url == "https://public.example.com"
