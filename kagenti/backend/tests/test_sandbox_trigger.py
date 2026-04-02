# Copyright 2025 IBM Corp.
# Licensed under the Apache License, Version 2.0

"""Tests for sandbox trigger API endpoint."""

from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

pytest.importorskip("app.routers.sandbox_trigger", reason="sandbox_trigger module not available")

from app.core.auth import ROLE_OPERATOR, ROLE_VIEWER, require_roles
from app.routers.sandbox_trigger import router


@pytest.fixture
def client():
    """FastAPI test client with sandbox trigger router (auth bypassed)."""
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    # Override auth dependency to allow all requests in tests
    app.dependency_overrides[require_roles(ROLE_OPERATOR)] = lambda: None
    return TestClient(app)


@pytest.fixture(autouse=True)
def mock_kubectl():
    """Mock kubectl so no real clusters are needed."""
    mock_result = MagicMock(returncode=0, stdout="", stderr="")
    with patch("triggers.subprocess.run", return_value=mock_result):
        yield mock_result


class TestCronTrigger:
    """POST /api/v1/sandbox/trigger with type=cron."""

    def test_cron_trigger_success(self, client):
        resp = client.post(
            "/api/v1/sandbox/trigger",
            json={"type": "cron", "skill": "rca:ci", "schedule": "0 2 * * *"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "sandbox_claim" in data
        assert data["sandbox_claim"].startswith("cron-rca-ci-")
        assert data["namespace"] == "team1"

    def test_cron_trigger_missing_skill(self, client):
        resp = client.post("/api/v1/sandbox/trigger", json={"type": "cron"})
        assert resp.status_code == 422


class TestWebhookTrigger:
    """POST /api/v1/sandbox/trigger with type=webhook."""

    def test_webhook_trigger_success(self, client):
        resp = client.post(
            "/api/v1/sandbox/trigger",
            json={
                "type": "webhook",
                "event": "pull_request",
                "repo": "kagenti/kagenti",
                "branch": "feat/x",
                "pr_number": 42,
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["sandbox_claim"].startswith("gh-kagenti-kagenti-")

    def test_webhook_trigger_missing_repo(self, client):
        resp = client.post(
            "/api/v1/sandbox/trigger",
            json={"type": "webhook", "event": "pull_request"},
        )
        assert resp.status_code == 422

    def test_webhook_trigger_custom_namespace(self, client):
        resp = client.post(
            "/api/v1/sandbox/trigger",
            json={
                "type": "webhook",
                "event": "issue_comment",
                "repo": "kagenti/kagenti",
                "namespace": "team2",
            },
        )
        assert resp.status_code == 200
        assert resp.json()["namespace"] == "team2"


class TestAlertTrigger:
    """POST /api/v1/sandbox/trigger with type=alert."""

    def test_alert_trigger_success(self, client):
        resp = client.post(
            "/api/v1/sandbox/trigger",
            json={
                "type": "alert",
                "alert": "PodCrashLoop",
                "cluster": "prod",
                "severity": "critical",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["sandbox_claim"].startswith("alert-podcrashloop-")

    def test_alert_trigger_missing_alert(self, client):
        resp = client.post(
            "/api/v1/sandbox/trigger",
            json={"type": "alert"},
        )
        assert resp.status_code == 422


class TestErrorHandling:
    """Test error cases."""

    def test_unknown_trigger_type(self, client):
        resp = client.post(
            "/api/v1/sandbox/trigger",
            json={"type": "unknown"},
        )
        assert resp.status_code == 400

    def test_kubectl_failure(self, client, mock_kubectl):
        mock_kubectl.returncode = 1
        mock_kubectl.stderr = "connection refused"
        resp = client.post(
            "/api/v1/sandbox/trigger",
            json={"type": "cron", "skill": "test"},
        )
        assert resp.status_code == 500
