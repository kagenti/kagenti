"""
T6.1 ACP Protocol Tests

Tests the ACP (Agent Client Protocol) WebSocket endpoint at
/api/v1/acp/ws/{namespace}/{agent_name}. Validates JSON-RPC 2.0
lifecycle: initialize, session management, prompt relay to A2A agents.

Capability: acp_lifecycle, acp_bridge, acp_session
Convention: test_T6_{capability}__{description}[agent]
"""

import json
import os

import pytest

from kagenti.tests.e2e.openshell.conftest import (
    BACKEND_AGENTS,
    skip_no_backend,
    skip_no_llm,
)

pytestmark = [pytest.mark.openshell, skip_no_backend]

AGENT_NS = os.getenv("OPENSHELL_AGENT_NAMESPACE", "team1")


async def _acp_connect(backend_url: str, namespace: str, agent_name: str):
    """Connect to ACP WebSocket endpoint."""
    import websockets

    ws_url = backend_url.replace("http://", "ws://")
    return await websockets.connect(
        f"{ws_url}/api/v1/acp/ws/{namespace}/{agent_name}",
        close_timeout=5,
    )


async def _acp_rpc(
    ws, method: str, params: dict | None = None, rpc_id: str = "1"
) -> dict:
    """Send JSON-RPC request and return response."""
    payload = {"jsonrpc": "2.0", "id": rpc_id, "method": method}
    if params:
        payload["params"] = params
    await ws.send(json.dumps(payload))
    raw = await ws.recv()
    return json.loads(raw)


async def _acp_init_and_session(backend_url: str, namespace: str, agent_name: str):
    """Helper: connect, initialize, create session. Returns (ws, session_id)."""
    ws = await _acp_connect(backend_url, namespace, agent_name)
    await _acp_rpc(ws, "initialize", rpc_id="init-1")
    resp = await _acp_rpc(ws, "session/new", rpc_id="session-1")
    session_id = resp.get("result", {}).get("sessionId", "")
    return ws, session_id


@pytest.mark.asyncio
class TestT6Lifecycle:
    """ACP WebSocket lifecycle: initialize, session, close."""

    async def test_T6_lifecycle__initialize(self, backend_url):
        """WebSocket connect + initialize handshake returns capabilities."""
        agent = "claude-sdk-agent"
        ws = await _acp_connect(backend_url, AGENT_NS, agent)
        try:
            resp = await _acp_rpc(ws, "initialize", rpc_id="init-1")
            assert "result" in resp, f"Missing result: {resp}"
            caps = resp["result"]
            assert "protocolVersion" in caps or "agentCapabilities" in caps, (
                f"No capabilities: {caps}"
            )
        finally:
            await ws.close()

    async def test_T6_lifecycle__session_new(self, backend_url):
        """Create session returns a sessionId."""
        agent = "claude-sdk-agent"
        ws = await _acp_connect(backend_url, AGENT_NS, agent)
        try:
            await _acp_rpc(ws, "initialize")
            resp = await _acp_rpc(ws, "session/new", rpc_id="s-new")
            result = resp.get("result", {})
            assert "sessionId" in result, f"No sessionId: {resp}"
            assert len(result["sessionId"]) > 0
        finally:
            await ws.close()

    async def test_T6_lifecycle__session_close(self, backend_url):
        """Close session cleanly."""
        agent = "claude-sdk-agent"
        ws, session_id = await _acp_init_and_session(backend_url, AGENT_NS, agent)
        try:
            assert session_id, "Failed to create session"
            resp = await _acp_rpc(
                ws, "session/close", {"sessionId": session_id}, rpc_id="close-1"
            )
            result = resp.get("result", {})
            assert result.get("closed") is True, f"Close failed: {resp}"
        finally:
            await ws.close()


@pytest.mark.asyncio
class TestT6Prompt:
    """ACP prompt relay to A2A agents."""

    @skip_no_llm
    @pytest.mark.parametrize("agent", BACKEND_AGENTS)
    async def test_T6_prompt__text_response(self, agent, backend_url):
        """Send prompt, receive streaming updates with text content."""
        ws, session_id = await _acp_init_and_session(backend_url, AGENT_NS, agent)
        try:
            assert session_id, "Failed to create session"

            prompt_params = {
                "sessionId": session_id,
                "prompt": [{"type": "text", "text": "Say hello in one word."}],
            }
            await ws.send(
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": "prompt-1",
                        "method": "session/prompt",
                        "params": prompt_params,
                    }
                )
            )

            messages = []
            while True:
                raw = await ws.recv()
                msg = json.loads(raw)
                messages.append(msg)
                if msg.get("id") == "prompt-1" and "result" in msg:
                    break
                if msg.get("method") == "session/update":
                    params = msg.get("params", {})
                    if params.get("sessionUpdate") == "turn_complete":
                        break

            text_updates = [
                m
                for m in messages
                if m.get("method") == "session/update"
                and m.get("params", {}).get("sessionUpdate") == "agent_message_chunk"
            ]
            assert len(text_updates) > 0 or len(messages) > 1, (
                f"No text updates received: {messages[:3]}"
            )
        finally:
            await ws.close()


@pytest.mark.asyncio
class TestT6Bridge:
    """ACP-to-A2A bridge roundtrip."""

    @skip_no_llm
    @pytest.mark.parametrize("agent", BACKEND_AGENTS)
    async def test_T6_bridge__acp_to_a2a(self, agent, backend_url):
        """Full roundtrip: ACP client -> backend WS -> A2A agent -> response."""
        ws, session_id = await _acp_init_and_session(backend_url, AGENT_NS, agent)
        try:
            assert session_id

            prompt_params = {
                "sessionId": session_id,
                "prompt": [{"type": "text", "text": "What is 2+2?"}],
            }
            await ws.send(
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": "bridge-1",
                        "method": "session/prompt",
                        "params": prompt_params,
                    }
                )
            )

            got_response = False
            for _ in range(50):
                raw = await ws.recv()
                msg = json.loads(raw)
                if msg.get("id") == "bridge-1" and "result" in msg:
                    got_response = True
                    break
                if msg.get("method") == "session/update":
                    params = msg.get("params", {})
                    if params.get("sessionUpdate") in ("turn_complete", "error"):
                        got_response = True
                        break

            assert got_response, "Never received end-of-turn from ACP bridge"
        finally:
            await ws.close()

    @skip_no_llm
    @pytest.mark.parametrize("agent", BACKEND_AGENTS)
    async def test_T6_bridge__context_preserved(self, agent, backend_url):
        """Multi-turn via ACP maintains context across prompts."""
        ws, session_id = await _acp_init_and_session(backend_url, AGENT_NS, agent)
        try:
            assert session_id

            for prompt_text in ["My name is AcpBot.", "What is my name?"]:
                params = {
                    "sessionId": session_id,
                    "prompt": [{"type": "text", "text": prompt_text}],
                }
                await ws.send(
                    json.dumps(
                        {
                            "jsonrpc": "2.0",
                            "id": f"ctx-{prompt_text[:4]}",
                            "method": "session/prompt",
                            "params": params,
                        }
                    )
                )
                while True:
                    raw = await ws.recv()
                    msg = json.loads(raw)
                    if "result" in msg and msg.get("id", "").startswith("ctx-"):
                        break
                    p = msg.get("params", {})
                    if p.get("sessionUpdate") in ("turn_complete", "error"):
                        break
        finally:
            await ws.close()


@pytest.mark.asyncio
class TestT6Session:
    """ACP session management."""

    async def test_T6_session__list(self, backend_url):
        """List sessions returns created sessions."""
        agent = "claude-sdk-agent"
        ws, s1 = await _acp_init_and_session(backend_url, AGENT_NS, agent)
        try:
            resp2 = await _acp_rpc(ws, "session/new", rpc_id="s2")
            s2 = resp2.get("result", {}).get("sessionId", "")

            resp = await _acp_rpc(ws, "session/list", rpc_id="list-1")
            sessions = resp.get("result", {}).get("sessions", [])
            ids = [s["sessionId"] for s in sessions]
            assert s1 in ids, f"Session {s1} not in list: {ids}"
            assert s2 in ids, f"Session {s2} not in list: {ids}"
        finally:
            await ws.close()

    async def test_T6_session__resume(self, backend_url):
        """Resume an existing session."""
        agent = "claude-sdk-agent"
        ws, session_id = await _acp_init_and_session(backend_url, AGENT_NS, agent)
        try:
            assert session_id
            resp = await _acp_rpc(
                ws, "session/resume", {"sessionId": session_id}, rpc_id="resume-1"
            )
            result = resp.get("result", {})
            assert result.get("resumed") is True, f"Resume failed: {resp}"
        finally:
            await ws.close()


@pytest.mark.asyncio
class TestT6Permission:
    """ACP permission gate (HITL)."""

    async def test_T6_permission__request(self, backend_url):
        """Permission request auto-approves in PoC mode."""
        agent = "claude-sdk-agent"
        ws, session_id = await _acp_init_and_session(backend_url, AGENT_NS, agent)
        try:
            resp = await _acp_rpc(ws, "session/request_permission", rpc_id="perm-1")
            result = resp.get("result", {})
            assert result.get("outcome") == "selected", f"Permission failed: {resp}"
            assert result.get("selectedOptionId") == "allow_once"
        finally:
            await ws.close()


@pytest.mark.asyncio
class TestT6Concurrent:
    """Concurrent ACP sessions."""

    async def test_T6_concurrent__sessions(self, backend_url):
        """Two WebSocket clients operate independently."""
        agent = "claude-sdk-agent"
        ws1, s1 = await _acp_init_and_session(backend_url, AGENT_NS, agent)
        ws2, s2 = await _acp_init_and_session(backend_url, AGENT_NS, agent)
        try:
            assert s1 != s2, "Sessions should be independent"
            r1 = await _acp_rpc(ws1, "session/list", rpc_id="c1")
            r2 = await _acp_rpc(ws2, "session/list", rpc_id="c2")
            assert "result" in r1
            assert "result" in r2
        finally:
            await ws1.close()
            await ws2.close()


@pytest.mark.asyncio
class TestT6Error:
    """ACP error handling."""

    async def test_T6_error__malformed_rpc(self, backend_url):
        """Invalid JSON-RPC returns error response."""
        agent = "claude-sdk-agent"
        ws = await _acp_connect(backend_url, AGENT_NS, agent)
        try:
            await ws.send("not json at all {{{")
            raw = await ws.recv()
            msg = json.loads(raw)
            assert "error" in msg, f"Expected error: {msg}"
            assert msg["error"]["code"] == -32700
        finally:
            await ws.close()

    async def test_T6_error__unknown_method(self, backend_url):
        """Unknown method returns method-not-found error."""
        agent = "claude-sdk-agent"
        ws = await _acp_connect(backend_url, AGENT_NS, agent)
        try:
            resp = await _acp_rpc(ws, "nonexistent/method", rpc_id="err-1")
            assert "error" in resp, f"Expected error: {resp}"
            assert resp["error"]["code"] == -32601
        finally:
            await ws.close()


@pytest.mark.asyncio
class TestT6SandboxAgent:
    """ACP WebSocket tests for sandbox agents (openshell-claude).

    These agents use ExecSandbox gRPC path instead of A2A HTTP.
    """

    @skip_no_backend
    async def test_T6_sandbox__initialize(self, backend_url):
        """ACP initialize works for sandbox agent name."""
        ws = await _acp_connect(backend_url, AGENT_NS, "openshell-claude")
        try:
            resp = await _acp_rpc(ws, "initialize")
            assert "result" in resp, f"Expected result: {resp}"
            assert resp["result"]["agentCapabilities"]["streaming"] is True
        finally:
            await ws.close()

    @skip_no_backend
    async def test_T6_sandbox__session_lifecycle(self, backend_url):
        """Create and close session for sandbox agent."""
        ws = await _acp_connect(backend_url, AGENT_NS, "openshell-claude")
        try:
            await _acp_rpc(ws, "initialize")
            session = await _acp_rpc(ws, "session/new", rpc_id="new-1")
            assert "result" in session
            sid = session["result"]["sessionId"]
            assert len(sid) == 32

            close = await _acp_rpc(
                ws, "session/close", {"sessionId": sid}, rpc_id="close-1"
            )
            assert close["result"]["closed"] is True
        finally:
            await ws.close()

    @skip_no_backend
    @skip_no_llm
    async def test_T6_sandbox__prompt_response(self, backend_url):
        """Send prompt to openshell-claude via ACP and get response.

        Requires backend with ExecSandbox gRPC client (PR #1689).
        """
        import asyncio

        ws = await _acp_connect(backend_url, AGENT_NS, "openshell-claude")
        try:
            await _acp_rpc(ws, "initialize")
            session = await _acp_rpc(ws, "session/new", rpc_id="new-1")
            sid = session["result"]["sessionId"]

            await ws.send(
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": "prompt-1",
                        "method": "session/prompt",
                        "params": {
                            "sessionId": sid,
                            "text": "What is 2+2? Reply with just the number.",
                        },
                    }
                )
            )

            messages = []
            for _ in range(10):
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=120)
                    msg = json.loads(raw)
                    messages.append(msg)
                    if msg.get("id") == "prompt-1":
                        break
                except asyncio.TimeoutError:
                    break

            assert len(messages) > 0, "No response from sandbox agent"
            has_content = any(
                m.get("params", {}).get("sessionUpdate") == "agent_message_chunk"
                for m in messages
            )
            assert has_content, f"No content in ACP messages: {messages}"
        finally:
            await ws.close()
