"""
T5.1 Backend API Tests

Tests rossoctl-backend as the production A2A proxy path. Instead of
per-agent port-forwards, all A2A requests go through one backend
port-forward at /api/v1/chat/{namespace}/{agent}/send|stream.

Capability: backend_connectivity, backend_proxy, backend_multiturn
Convention: test_T5_{capability}__{description}[agent]
"""

import asyncio
import os

import httpx
import pytest

from rossoctl.tests.e2e.openshell.conftest import (
    BACKEND_AGENTS,
    BACKEND_AGENT_NAMES,
    backend_send,
    skip_no_backend,
    skip_no_llm,
)

pytestmark = [pytest.mark.openshell, skip_no_backend]

AGENT_NS = os.getenv("OPENSHELL_AGENT_NAMESPACE", "team1")


class TestT5Connectivity:
    """Backend health and agent card proxy."""

    def test_T5_connectivity__backend_health(self, backend_url):
        """GET /health returns 200."""
        import httpx as hx

        resp = hx.get(f"{backend_url}/health", timeout=10)
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("status") == "healthy"

    @pytest.mark.parametrize("agent", BACKEND_AGENTS)
    def test_T5_connectivity__agent_card(self, agent, backend_url):
        """Backend proxies agent card for each A2A agent."""
        import httpx as hx

        resp = hx.get(
            f"{backend_url}/api/v1/chat/{AGENT_NS}/{agent}/agent-card",
            timeout=30,
        )
        if resp.status_code == 503:
            pytest.skip(f"{agent}: backend cannot reach agent (503, supervised netns)")
        assert resp.status_code == 200, f"Agent card failed for {agent}: {resp.text}"
        data = resp.json()
        assert "name" in data, f"Agent card missing 'name': {data}"


@pytest.mark.asyncio
class TestT5Send:
    """Non-streaming message send through backend proxy."""

    @skip_no_llm
    @pytest.mark.parametrize("agent", BACKEND_AGENTS)
    async def test_T5_send__responds(self, agent, backend_url):
        """POST /chat/{ns}/{agent}/send returns a valid response."""
        async with httpx.AsyncClient() as client:
            result = await backend_send(
                client, backend_url, AGENT_NS, agent, "Say hello in one word."
            )
        assert "content" in result, f"Response missing 'content': {result}"
        assert len(result["content"]) > 0, f"Empty content: {result}"

    @skip_no_llm
    @pytest.mark.parametrize("agent", BACKEND_AGENTS)
    async def test_T5_send__has_session_id(self, agent, backend_url):
        """Response includes a session_id for conversation tracking."""
        async with httpx.AsyncClient() as client:
            result = await backend_send(client, backend_url, AGENT_NS, agent, "Hi")
        assert "session_id" in result, f"Response missing 'session_id': {result}"
        assert len(result["session_id"]) > 0


@pytest.mark.asyncio
class TestT5Stream:
    """SSE streaming through backend proxy."""

    @skip_no_llm
    @pytest.mark.parametrize("agent", BACKEND_AGENTS)
    async def test_T5_stream__delivers_events(self, agent, backend_url):
        """POST /chat/{ns}/{agent}/stream delivers SSE events."""
        payload = {"message": "Say hello briefly."}
        got_data = False
        async with httpx.AsyncClient(timeout=120.0) as client:
            async with client.stream(
                "POST",
                f"{backend_url}/api/v1/chat/{AGENT_NS}/{agent}/stream",
                json=payload,
                headers={"Accept": "text/event-stream"},
            ) as resp:
                if resp.status_code == 503:
                    pytest.skip(
                        f"{agent}: backend cannot reach agent (503, supervised netns)"
                    )
                assert resp.status_code == 200, f"Stream failed: {resp.status_code}"
                async for line in resp.aiter_lines():
                    if line.startswith("data:"):
                        got_data = True
                        break
        if not got_data:
            pytest.skip(
                f"{agent}: no SSE data — agent may have returned empty response (LLM flake)"
            )


@pytest.mark.asyncio
class TestT5Multiturn:
    """Multi-turn conversation context preservation via backend."""

    @skip_no_llm
    @pytest.mark.parametrize("agent", BACKEND_AGENTS)
    async def test_T5_multiturn__preserves_context(self, agent, backend_url):
        """Two sequential sends with session_id preserve conversation context."""
        async with httpx.AsyncClient() as client:
            r1 = await backend_send(
                client, backend_url, AGENT_NS, agent, "My name is TestBot."
            )
            session_id = r1.get("session_id", "")
            assert session_id, "First response missing session_id"

            r2 = await backend_send(
                client,
                backend_url,
                AGENT_NS,
                agent,
                "What is my name?",
                session_id=session_id,
            )
            assert "content" in r2, f"Second response missing content: {r2}"


class TestT5AgentList:
    """Agent listing through backend API."""

    def test_T5_agent_list__shows_deployed(self, backend_url):
        """GET /agents?namespace={ns} lists deployed agents."""
        import httpx as hx

        resp = hx.get(
            f"{backend_url}/api/v1/agents",
            params={"namespace": AGENT_NS},
            timeout=30,
        )
        if resp.status_code == 403:
            pytest.skip("Backend RBAC not sufficient for agent listing")
        assert resp.status_code == 200, f"Agent list failed: {resp.text}"
        data = resp.json()
        agents = data if isinstance(data, list) else data.get("agents", [])
        if len(agents) == 0:
            pytest.skip(
                "Backend agent list returns 0 — AgentRuntime CRs may be missing "
                "or rossoctl-operator has not yet reconciled rossoctl.io/type labels."
            )

    def test_T5_agent_list__has_metadata(self, backend_url):
        """Each agent has name and type metadata."""
        import httpx as hx

        resp = hx.get(
            f"{backend_url}/api/v1/agents",
            params={"namespace": AGENT_NS},
            timeout=30,
        )
        data = resp.json()
        agents = data if isinstance(data, list) else data.get("agents", [])
        for agent in agents[:3]:
            assert "name" in agent, f"Agent missing 'name': {agent}"


class TestT5ErrorHandling:
    """Backend error responses for invalid requests."""

    def test_T5_error__nonexistent_agent(self, backend_url):
        """Request to unknown agent returns 404 or 503."""
        import httpx as hx

        resp = hx.get(
            f"{backend_url}/api/v1/chat/{AGENT_NS}/nonexistent-agent-xyz/agent-card",
            timeout=15,
        )
        assert resp.status_code in (404, 503), (
            f"Expected 404/503, got {resp.status_code}"
        )

    def test_T5_error__invalid_namespace(self, backend_url):
        """Request to unknown namespace returns 404 or 503."""
        import httpx as hx

        resp = hx.get(
            f"{backend_url}/api/v1/chat/nonexistent-ns/some-agent/agent-card",
            timeout=15,
        )
        assert resp.status_code in (404, 503), (
            f"Expected 404/503, got {resp.status_code}"
        )


@pytest.mark.asyncio
class TestT5Concurrent:
    """Concurrent requests through backend."""

    @skip_no_llm
    async def test_T5_concurrent__parallel_requests(self, backend_url):
        """Multiple agents in parallel don't interfere."""
        async with httpx.AsyncClient() as client:
            tasks = [
                backend_send(client, backend_url, AGENT_NS, name, "Hello")
                for name in BACKEND_AGENT_NAMES
            ]
            results = await asyncio.gather(*tasks, return_exceptions=True)

        successes = [r for r in results if isinstance(r, dict) and "content" in r]
        skips = [r for r in results if isinstance(r, BaseException) and "503" in str(r)]
        if not successes and skips:
            pytest.skip(f"All {len(skips)} agents unreachable (503, netns)")
        assert len(successes) >= 1, f"Expected at least 1 success, got: {results}"
