# Copyright 2025 IBM Corp.
# Licensed under the Apache License, Version 2.0

"""
Tests for chat streaming 401 propagation.

Verifies that when an agent rejects a request with 401 (audience mismatch),
the backend returns HTTP 401 to the frontend so the UI can trigger token refresh.
"""

from unittest.mock import MagicMock, patch

import httpx
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def app():
    """Create FastAPI app with mocked Kubernetes dependencies."""
    with (
        patch.dict("os.environ", {"KUBERNETES_SERVICE_HOST": "fake"}, clear=False),
        patch("app.services.kubernetes.kubernetes.config.load_incluster_config"),
        patch("app.services.kubernetes.kubernetes.config.load_kube_config"),
        patch("app.services.kubernetes.kubernetes.client.ApiClient"),
    ):
        from app.main import app as fastapi_app

        yield fastapi_app
        fastapi_app.dependency_overrides.clear()


@pytest.fixture
def client(app):
    from app.services.kubernetes import get_kubernetes_service

    app.dependency_overrides[get_kubernetes_service] = lambda: MagicMock()
    return TestClient(app)


@pytest.fixture
def mock_auth(app):
    """Override auth dependencies to skip token validation."""
    from app.core.auth import TokenData, get_required_user, require_roles

    user = TokenData(
        sub="test-user",
        username="alice",
        email="alice@example.com",
        roles=["kagenti-operator"],
        raw_token={},
    )

    app.dependency_overrides[get_required_user] = lambda: user
    app.dependency_overrides[require_roles("kagenti-operator")] = lambda: None
    yield user


@pytest.fixture
def mock_resolve_agent_url():
    with patch(
        "app.routers.chat.resolve_agent_url",
        return_value="http://weather-agent.team1.svc:8080",
    ):
        yield


class TestStreamMessage401:
    """Test that agent 401 responses are propagated as HTTP 401."""

    def test_agent_401_returns_http_401(self, client, mock_auth, mock_resolve_agent_url):
        """When agent returns 401, backend should return HTTP 401 (not 200 with SSE error)."""
        mock_response = httpx.Response(
            status_code=401,
            request=httpx.Request("POST", "http://weather-agent.team1.svc:8080"),
        )

        async def mock_send(self, request, *, stream=False, **kwargs):
            return mock_response

        with patch.object(httpx.AsyncClient, "send", mock_send):
            response = client.post(
                "/api/v1/chat/team1/weather-agent/stream",
                json={"message": "hello", "session_id": "test123"},
                headers={"Authorization": "Bearer fake-token"},
            )

        assert response.status_code == 401
        assert "audience" in response.json().get("detail", "").lower()

    def test_agent_503_on_connection_error(self, client, mock_auth, mock_resolve_agent_url):
        """When agent is unreachable, backend should return HTTP 503."""

        async def mock_send(self, request, *, stream=False, **kwargs):
            raise httpx.ConnectError("Connection refused")

        with patch.object(httpx.AsyncClient, "send", mock_send):
            response = client.post(
                "/api/v1/chat/team1/weather-agent/stream",
                json={"message": "hello", "session_id": "test123"},
                headers={"Authorization": "Bearer fake-token"},
            )

        assert response.status_code == 503
