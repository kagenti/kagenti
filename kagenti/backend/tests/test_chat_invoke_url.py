# Copyright 2025 IBM Corp.
# Licensed under the Apache License, Version 2.0

"""
Tests for _resolve_invoke_url — agent card URL resolution.

Verifies that the backend uses the agent card's ``url`` field to determine
the correct A2A JSON-RPC invoke path, falling back to the bare service URL
when the card is unavailable or has no path.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.routers.chat import _resolve_invoke_url


@pytest.fixture
def mock_kube():
    return MagicMock()


@pytest.fixture
def mock_resolve_base():
    with patch(
        "app.routers.chat.resolve_agent_url",
        return_value="http://myagent.ns.svc.cluster.local:8443",
    ) as m:
        yield m


class TestResolveInvokeUrl:
    """Tests for _resolve_invoke_url helper."""

    @pytest.mark.asyncio
    async def test_uses_card_url_path(self, mock_kube, mock_resolve_base):
        """When agent card advertises a sub-path, use it."""
        card = {
            "name": "test-agent",
            "url": "https://myagent.ns.svc.cluster.local:8443/a2a/invoke",
        }
        mock_resp = httpx.Response(200, json=card, request=httpx.Request("GET", "http://x"))

        with patch("httpx.AsyncClient.get", new_callable=AsyncMock, return_value=mock_resp):
            url = await _resolve_invoke_url("myagent", "ns", mock_kube)

        assert url == "http://myagent.ns.svc.cluster.local:8443/a2a/invoke"

    @pytest.mark.asyncio
    async def test_falls_back_when_card_has_root_url(self, mock_kube, mock_resolve_base):
        """When agent card url has no path (root /), return base URL."""
        card = {
            "name": "test-agent",
            "url": "http://myagent.ns.svc.cluster.local:8443",
        }
        mock_resp = httpx.Response(200, json=card, request=httpx.Request("GET", "http://x"))

        with patch("httpx.AsyncClient.get", new_callable=AsyncMock, return_value=mock_resp):
            url = await _resolve_invoke_url("myagent", "ns", mock_kube)

        assert url == "http://myagent.ns.svc.cluster.local:8443"

    @pytest.mark.asyncio
    async def test_falls_back_when_card_url_is_slash(self, mock_kube, mock_resolve_base):
        """When agent card url path is just /, return base URL."""
        card = {
            "name": "test-agent",
            "url": "http://myagent.ns.svc.cluster.local:8443/",
        }
        mock_resp = httpx.Response(200, json=card, request=httpx.Request("GET", "http://x"))

        with patch("httpx.AsyncClient.get", new_callable=AsyncMock, return_value=mock_resp):
            url = await _resolve_invoke_url("myagent", "ns", mock_kube)

        assert url == "http://myagent.ns.svc.cluster.local:8443"

    @pytest.mark.asyncio
    async def test_falls_back_when_card_has_no_url(self, mock_kube, mock_resolve_base):
        """When agent card has no url field, return base URL."""
        card = {"name": "test-agent"}
        mock_resp = httpx.Response(200, json=card, request=httpx.Request("GET", "http://x"))

        with patch("httpx.AsyncClient.get", new_callable=AsyncMock, return_value=mock_resp):
            url = await _resolve_invoke_url("myagent", "ns", mock_kube)

        assert url == "http://myagent.ns.svc.cluster.local:8443"

    @pytest.mark.asyncio
    async def test_falls_back_on_card_fetch_failure(self, mock_kube, mock_resolve_base):
        """When agent card fetch fails, return base URL."""
        with patch(
            "httpx.AsyncClient.get",
            new_callable=AsyncMock,
            side_effect=httpx.ConnectError("Connection refused"),
        ):
            url = await _resolve_invoke_url("myagent", "ns", mock_kube)

        assert url == "http://myagent.ns.svc.cluster.local:8443"

    @pytest.mark.asyncio
    async def test_falls_back_on_404(self, mock_kube, mock_resolve_base):
        """When agent card endpoint returns 404, return base URL."""
        mock_resp = httpx.Response(
            404, text="not found", request=httpx.Request("GET", "http://x")
        )

        with patch("httpx.AsyncClient.get", new_callable=AsyncMock, return_value=mock_resp):
            url = await _resolve_invoke_url("myagent", "ns", mock_kube)

        assert url == "http://myagent.ns.svc.cluster.local:8443"

    @pytest.mark.asyncio
    async def test_rejects_path_traversal(self, mock_kube, mock_resolve_base):
        """Paths containing '..' segments are rejected to prevent traversal."""
        card = {
            "name": "evil-agent",
            "url": "http://myagent.ns.svc.cluster.local:8443/../../admin",
        }
        mock_resp = httpx.Response(200, json=card, request=httpx.Request("GET", "http://x"))

        with patch("httpx.AsyncClient.get", new_callable=AsyncMock, return_value=mock_resp):
            url = await _resolve_invoke_url("myagent", "ns", mock_kube)

        assert url == "http://myagent.ns.svc.cluster.local:8443"

    @pytest.mark.asyncio
    async def test_preserves_deep_path(self, mock_kube, mock_resolve_base):
        """When agent card url has a multi-segment path, preserve it."""
        card = {
            "name": "langchain-agent",
            "url": "http://myagent.ns.svc.cluster.local:8443/a2a/assistant-123",
        }
        mock_resp = httpx.Response(200, json=card, request=httpx.Request("GET", "http://x"))

        with patch("httpx.AsyncClient.get", new_callable=AsyncMock, return_value=mock_resp):
            url = await _resolve_invoke_url("myagent", "ns", mock_kube)

        assert url == "http://myagent.ns.svc.cluster.local:8443/a2a/assistant-123"
