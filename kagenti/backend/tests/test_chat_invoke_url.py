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
        mock_resp = httpx.Response(404, text="not found", request=httpx.Request("GET", "http://x"))

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

    # --- Security hardening tests ---

    @pytest.mark.asyncio
    async def test_rejects_url_encoded_traversal(self, mock_kube, mock_resolve_base):
        """URL-encoded '..' (%2e%2e) must be caught after decoding (CWE-22)."""
        card = {
            "name": "evil-agent",
            "url": "http://myagent.ns.svc.cluster.local:8443/%2e%2e/%2e%2e/admin",
        }
        mock_resp = httpx.Response(200, json=card, request=httpx.Request("GET", "http://x"))

        with patch("httpx.AsyncClient.get", new_callable=AsyncMock, return_value=mock_resp):
            url = await _resolve_invoke_url("myagent", "ns", mock_kube)

        assert url == "http://myagent.ns.svc.cluster.local:8443"

    @pytest.mark.asyncio
    async def test_skips_card_fetch_for_invalid_name(self, mock_kube, mock_resolve_base):
        """Non-K8s names skip the card fetch entirely (SSRF prevention)."""
        with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
            url = await _resolve_invoke_url("INVALID NAME!", "ns", mock_kube)

        assert url == "http://myagent.ns.svc.cluster.local:8443"
        mock_get.assert_not_called()

    @pytest.mark.asyncio
    async def test_skips_card_fetch_for_invalid_namespace(self, mock_kube, mock_resolve_base):
        """Non-K8s namespaces skip the card fetch entirely (SSRF prevention)."""
        with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
            url = await _resolve_invoke_url("myagent", "ns with spaces", mock_kube)

        assert url == "http://myagent.ns.svc.cluster.local:8443"
        mock_get.assert_not_called()

    @pytest.mark.asyncio
    async def test_drops_unsafe_query_string(self, mock_kube, mock_resolve_base):
        """Unsafe query chars (e.g. URL injection via '://') are stripped; path is kept."""
        card = {
            "name": "test-agent",
            "url": "http://myagent.ns.svc.cluster.local:8443/a2a?redirect=http://evil.com",
        }
        mock_resp = httpx.Response(200, json=card, request=httpx.Request("GET", "http://x"))

        with patch("httpx.AsyncClient.get", new_callable=AsyncMock, return_value=mock_resp):
            url = await _resolve_invoke_url("myagent", "ns", mock_kube)

        assert url == "http://myagent.ns.svc.cluster.local:8443/a2a"

    @pytest.mark.asyncio
    async def test_preserves_safe_query_string(self, mock_kube, mock_resolve_base):
        """Per A2A spec §4.4.6, safe query params are part of the endpoint URL."""
        card = {
            "name": "langchain-agent",
            "url": "http://myagent.ns.svc.cluster.local:8443/a2a?assistant_id=123",
        }
        mock_resp = httpx.Response(200, json=card, request=httpx.Request("GET", "http://x"))

        with patch("httpx.AsyncClient.get", new_callable=AsyncMock, return_value=mock_resp):
            url = await _resolve_invoke_url("myagent", "ns", mock_kube)

        assert url == "http://myagent.ns.svc.cluster.local:8443/a2a?assistant_id=123"

    @pytest.mark.asyncio
    async def test_ignores_card_url_host(self, mock_kube, mock_resolve_base):
        """Only the path from the card URL is used; the host is always base_url's."""
        card = {
            "name": "test-agent",
            "url": "http://evil.com:9999/a2a/invoke",
        }
        mock_resp = httpx.Response(200, json=card, request=httpx.Request("GET", "http://x"))

        with patch("httpx.AsyncClient.get", new_callable=AsyncMock, return_value=mock_resp):
            url = await _resolve_invoke_url("myagent", "ns", mock_kube)

        assert url == "http://myagent.ns.svc.cluster.local:8443/a2a/invoke"
