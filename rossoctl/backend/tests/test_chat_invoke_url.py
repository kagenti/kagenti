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

from app.routers.chat import _invoke_url_cache, _resolve_invoke_url


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

    @pytest.fixture(autouse=True)
    def clear_cache(self):
        _invoke_url_cache.clear()
        yield
        _invoke_url_cache.clear()

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
    async def test_rejects_invalid_name(self, mock_kube, mock_resolve_base):
        """[SI-10] Non-K8s names are rejected to prevent SSRF via tainted URL construction."""
        with pytest.raises(Exception, match="Invalid agent name or namespace"):
            await _resolve_invoke_url("INVALID NAME!", "ns", mock_kube)

    @pytest.mark.asyncio
    async def test_rejects_invalid_namespace(self, mock_kube, mock_resolve_base):
        """[SI-10] Non-K8s namespaces are rejected to prevent SSRF via tainted URL construction."""
        with pytest.raises(Exception, match="Invalid agent name or namespace"):
            await _resolve_invoke_url("myagent", "ns with spaces", mock_kube)

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


class TestInvokeUrlCache:
    """TTL cache for _resolve_invoke_url.

    Unit tests proving cache logic. Each test maps to a FedRAMP control
    objective verifying business-level behavior.

    Pyramid invariant: these are the unit tier — they prove cache logic
    in isolation using mocks. The integration tier is TestCacheWiring
    below, which proves the cached path produces identical results to
    fresh resolution.
    """

    @pytest.fixture(autouse=True)
    def clear_cache(self):
        _invoke_url_cache.clear()
        yield
        _invoke_url_cache.clear()

    @pytest.fixture
    def mock_kube(self):
        return MagicMock()

    @pytest.fixture
    def mock_resolve_base(self):
        with patch(
            "app.routers.chat.resolve_agent_url",
            return_value="http://myagent.ns.svc.cluster.local:8443",
        ) as m:
            yield m

    @pytest.mark.asyncio
    async def test_second_call_uses_cache_no_http_fetch(self, mock_kube, mock_resolve_base):
        """[SC-5] Cached result eliminates redundant agent card HTTP fetch."""
        card = {
            "name": "test-agent",
            "url": "https://myagent.ns.svc.cluster.local:8443/a2a/invoke",
        }
        mock_resp = httpx.Response(200, json=card, request=httpx.Request("GET", "http://x"))

        with patch(
            "httpx.AsyncClient.get", new_callable=AsyncMock, return_value=mock_resp
        ) as mock_get:
            url1 = await _resolve_invoke_url("myagent", "ns", mock_kube)
            url2 = await _resolve_invoke_url("myagent", "ns", mock_kube)

        assert url1 == url2 == "http://myagent.ns.svc.cluster.local:8443/a2a/invoke"
        mock_get.assert_called_once()

    @pytest.mark.asyncio
    async def test_cache_expires_after_ttl(self, mock_kube, mock_resolve_base):
        """[SC-5] Cache entry expires after TTL, triggering a fresh fetch."""
        card = {
            "name": "test-agent",
            "url": "https://myagent.ns.svc.cluster.local:8443/a2a/invoke",
        }
        mock_resp = httpx.Response(200, json=card, request=httpx.Request("GET", "http://x"))

        with patch(
            "httpx.AsyncClient.get", new_callable=AsyncMock, return_value=mock_resp
        ) as mock_get:
            t = 1000.0
            with patch("app.routers.chat.time.monotonic", side_effect=[t, t + 31.0, t + 31.0]):
                url1 = await _resolve_invoke_url("myagent", "ns", mock_kube)
                url2 = await _resolve_invoke_url("myagent", "ns", mock_kube)

        assert url1 == url2
        assert mock_get.call_count == 2

    @pytest.mark.asyncio
    async def test_different_agents_cached_independently(self, mock_kube, mock_resolve_base):
        """[SC-7] Separate cache entries per agent prevent cross-boundary leakage."""
        card_a = {"name": "a", "url": "http://a.ns.svc.cluster.local:8443/path-a"}
        card_b = {"name": "b", "url": "http://b.ns2.svc.cluster.local:8443/path-b"}
        resp_a = httpx.Response(200, json=card_a, request=httpx.Request("GET", "http://x"))
        resp_b = httpx.Response(200, json=card_b, request=httpx.Request("GET", "http://x"))

        with patch("httpx.AsyncClient.get", new_callable=AsyncMock, side_effect=[resp_a, resp_b]):
            url_a = await _resolve_invoke_url("agent-a", "ns", mock_kube)

        with patch(
            "app.routers.chat.resolve_agent_url",
            return_value="http://agent-b.ns2.svc.cluster.local:8443",
        ):
            with patch("httpx.AsyncClient.get", new_callable=AsyncMock, return_value=resp_b):
                url_b = await _resolve_invoke_url("agent-b", "ns2", mock_kube)

        assert url_a == "http://myagent.ns.svc.cluster.local:8443/path-a"
        assert url_b == "http://agent-b.ns2.svc.cluster.local:8443/path-b"
        assert url_a != url_b

    @pytest.mark.asyncio
    async def test_failed_card_fetch_not_cached(self, mock_kube, mock_resolve_base):
        """[SI-10] Transient failures are not cached so subsequent calls can retry."""
        card = {
            "name": "test-agent",
            "url": "https://myagent.ns.svc.cluster.local:8443/a2a/invoke",
        }
        mock_resp_ok = httpx.Response(200, json=card, request=httpx.Request("GET", "http://x"))

        with patch(
            "httpx.AsyncClient.get",
            new_callable=AsyncMock,
            side_effect=[httpx.ConnectError("refused"), mock_resp_ok],
        ) as mock_get:
            url1 = await _resolve_invoke_url("myagent", "ns", mock_kube)
            url2 = await _resolve_invoke_url("myagent", "ns", mock_kube)

        assert url1 == "http://myagent.ns.svc.cluster.local:8443"
        assert url2 == "http://myagent.ns.svc.cluster.local:8443/a2a/invoke"
        assert mock_get.call_count == 2


class TestCacheWiring:
    """Integration tier: proves cached path produces identical results to fresh resolution.

    Pyramid invariant: these integration tests verify that the caching layer
    does not alter the resolved URL — the wiring between cache → resolve →
    return is correct.
    """

    @pytest.fixture(autouse=True)
    def clear_cache(self):
        _invoke_url_cache.clear()
        yield
        _invoke_url_cache.clear()

    @pytest.fixture
    def mock_kube(self):
        return MagicMock()

    @pytest.fixture
    def mock_resolve_base(self):
        with patch(
            "app.routers.chat.resolve_agent_url",
            return_value="http://myagent.ns.svc.cluster.local:8443",
        ) as m:
            yield m

    @pytest.mark.asyncio
    async def test_cached_result_matches_fresh_resolve(self, mock_kube, mock_resolve_base):
        """[SC-7] Cached URL is byte-identical to what a fresh resolution produces."""
        card = {
            "name": "test-agent",
            "url": "https://myagent.ns.svc.cluster.local:8443/a2a/invoke",
        }
        mock_resp = httpx.Response(200, json=card, request=httpx.Request("GET", "http://x"))

        with patch("httpx.AsyncClient.get", new_callable=AsyncMock, return_value=mock_resp):
            fresh_url = await _resolve_invoke_url("myagent", "ns", mock_kube)

        with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
            cached_url = await _resolve_invoke_url("myagent", "ns", mock_kube)
            mock_get.assert_not_called()

        assert cached_url == fresh_url

    @pytest.mark.asyncio
    async def test_cache_does_not_bypass_input_validation(self, mock_kube, mock_resolve_base):
        """[SI-10] Invalid K8s names are rejected even after cache exists for valid names."""
        card = {
            "name": "test-agent",
            "url": "https://myagent.ns.svc.cluster.local:8443/a2a/invoke",
        }
        mock_resp = httpx.Response(200, json=card, request=httpx.Request("GET", "http://x"))

        with patch("httpx.AsyncClient.get", new_callable=AsyncMock, return_value=mock_resp):
            await _resolve_invoke_url("myagent", "ns", mock_kube)

        with pytest.raises(Exception, match="Invalid agent name or namespace"):
            await _resolve_invoke_url("INVALID!", "ns", mock_kube)
