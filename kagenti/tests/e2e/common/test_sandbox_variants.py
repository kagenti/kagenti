#!/usr/bin/env python3
"""
Sandbox Agent Variants E2E Tests

Parameterized tests that verify multi-turn conversation, tool calls, and
session isolation across ALL deployed sandbox agent variants:

- sandbox-legion     (persistent, OpenAI, shared pod)
- sandbox-hardened   (persistent, OpenAI, hardened security)
- sandbox-basic      (stateless, OpenAI, shared pod)
- sandbox-restricted (persistent, OpenAI, restricted proxy, hardened)

Each variant must:
1. Respond to agent card requests
2. Execute shell commands (tool call)
3. Write and read files (tool call persistence within session)
4. Maintain multi-turn context (memory across turns)
5. Isolate sessions (different context_ids don't share workspace)

Usage:
    pytest tests/e2e/common/test_sandbox_variants.py -v
    pytest tests/e2e/common/test_sandbox_variants.py -v -k "legion"
    pytest tests/e2e/common/test_sandbox_variants.py -v -k "hardened"
"""

import json
import os
import pathlib

import pytest
import httpx
from uuid import uuid4

from kagenti.tests.e2e.conftest import _fetch_openshift_ingress_ca

# Skip entire module if sandbox feature is not enabled
# Uses requires_features marker (reads featureFlags from config YAML or ENABLE_SANDBOX_TESTS env)
pytestmark = pytest.mark.requires_features(["sandbox"])


# ---------------------------------------------------------------------------
# Agent variant configurations
# ---------------------------------------------------------------------------

AGENT_VARIANTS = [
    pytest.param("sandbox-legion", id="legion"),
    pytest.param("sandbox-hardened", id="hardened"),
    pytest.param("sandbox-basic", id="basic"),
    pytest.param("sandbox-restricted", id="restricted"),
]

NAMESPACE = os.getenv("SANDBOX_NAMESPACE", "team1")


def _get_agent_url(agent_name: str) -> str | None:
    """Get the agent URL — from env var, or fall back to in-cluster DNS.

    Environment variables checked (example for sandbox-legion):
        SANDBOX_LEGION_URL — explicit URL (e.g. OpenShift route)

    Falls back to in-cluster DNS:
        http://sandbox-legion.<NAMESPACE>.svc.cluster.local:8000

    Returns None when the env var is not set AND in-cluster DNS is
    unlikely to work (i.e. no ENABLE_SANDBOX_TESTS flag).
    """
    env_key = f"SANDBOX_{agent_name.split('-', 1)[-1].upper()}_URL"
    url = os.getenv(env_key)
    if url:
        return url
    # Fall back to in-cluster DNS (works when tests run inside the cluster)
    return f"http://{agent_name}.{NAMESPACE}.svc.cluster.local:8000"


def _is_openshift_from_config() -> bool:
    config_file = os.getenv("KAGENTI_CONFIG_FILE")
    if not config_file:
        return False
    import yaml

    config_path = pathlib.Path(config_file)
    if not config_path.is_absolute():
        repo_root = pathlib.Path(__file__).parent.parent.parent.parent.parent
        config_path = repo_root / config_path
    if not config_path.exists():
        return False
    with open(config_path) as f:
        cfg = yaml.safe_load(f)
    return cfg.get("cluster", {}).get("type") == "openshift"


def _make_client(agent_name: str) -> httpx.Client:
    """Create an HTTP client with optional OpenShift CA.

    Uses 300s timeout because message/stream blocks until the full multi-node
    graph completes (router+planner+executor+reporter).  With MaaS models
    each LLM call can take 30-60s, and the graph has 4 nodes.
    """
    kwargs: dict = {
        "timeout": httpx.Timeout(connect=30, read=300, write=30, pool=30),
        "follow_redirects": True,
    }
    # Check if any agent URL is HTTPS (implies OpenShift routes with self-signed certs)
    agent_url = _get_agent_url(agent_name)
    needs_ca = _is_openshift_from_config() or agent_url.startswith("https://")
    if needs_ca:
        ca_path = _fetch_openshift_ingress_ca()
        if ca_path:
            # _fetch_openshift_ingress_ca() returns a file path, not cert content
            kwargs["verify"] = ca_path
        else:
            # No CA available — disable verification for self-signed certs
            kwargs["verify"] = False
    return httpx.Client(**kwargs)


def _skip_if_unreachable(agent_name: str, agent_url: str) -> None:
    """Verify agent is reachable — retry on transient errors (502/503)."""
    import time

    client = _make_client(agent_name)
    last_exc = None
    try:
        for attempt in range(6):
            try:
                resp = client.get(
                    f"{agent_url}/.well-known/agent-card.json",
                    timeout=15.0,
                )
                if resp.status_code in (502, 503, 504):
                    last_exc = Exception(f"HTTP {resp.status_code}")
                    time.sleep(10)
                    continue
                resp.raise_for_status()
                return
            except Exception as exc:
                last_exc = exc
                time.sleep(10)
        env_key = f"SANDBOX_{agent_name.split('-', 1)[-1].upper()}_URL"
        pytest.fail(
            f"Agent {agent_name} not reachable at {agent_url} after 6 attempts "
            f"(set {env_key} to the route URL): {last_exc}"
        )
    finally:
        client.close()


def _send_message(
    client: httpx.Client,
    agent_url: str,
    message: str,
    context_id: str,
) -> dict:
    """Send an A2A message via SSE streaming and collect the final result.

    Uses message/stream instead of message/send to keep data flowing on
    the connection, preventing Istio/Envoy idle timeout drops.
    """
    payload = {
        "jsonrpc": "2.0",
        "id": uuid4().hex,
        "method": "message/stream",
        "params": {
            "message": {
                "role": "user",
                "parts": [{"kind": "text", "text": message}],
                "messageId": uuid4().hex,
                "contextId": context_id,
            }
        },
    }

    result: dict = {}
    try:
        with client.stream(
            "POST",
            f"{agent_url}/",
            json=payload,
            headers={"Accept": "text/event-stream"},
        ) as response:
            response.raise_for_status()
            for line in response.iter_lines():
                if not line or line.startswith(":"):
                    continue
                if line.startswith("data: "):
                    try:
                        event = json.loads(line[6:])
                    except json.JSONDecodeError:
                        continue
                    event_result = event.get("result", {})
                    kind = event_result.get("kind", "")
                    if kind == "artifact-update" and "artifact" in event_result:
                        result.setdefault("artifacts", []).append(
                            event_result["artifact"]
                        )
                    if "status" in event_result:
                        result["status"] = event_result["status"]
                    if "contextId" in event_result:
                        result["contextId"] = event_result["contextId"]
                    status_state = (
                        event_result.get("status", {}).get("state", "")
                        if isinstance(event_result.get("status"), dict)
                        else ""
                    )
                    if kind in ("task", "status-update") and status_state in (
                        "completed",
                        "failed",
                        "canceled",
                    ):
                        if "artifacts" in event_result:
                            result["artifacts"] = event_result["artifacts"]
                        break
    except httpx.RemoteProtocolError:
        pass

    if not result:
        raise RuntimeError("No events received from SSE stream")

    return result


def _extract_text(result: dict) -> str:
    """Extract text from A2A result artifacts or status message.

    Checks artifacts first (preferred), then status message as fallback.
    Filters out generic "no response" placeholders that the reporter
    emits when accumulation fails.
    """
    texts = []
    for artifact in result.get("artifacts", []):
        for part in artifact.get("parts", []):
            if "text" in part:
                texts.append(part["text"])
    if not texts:
        status = result.get("status", {})
        msg = status.get("message", {})
        for part in msg.get("parts", []):
            if "text" in part:
                texts.append(part["text"])
    combined = "\n".join(texts)
    if combined.strip().lower() in ("no response generated.", "no response generated"):
        return ""
    return combined


def _is_tool_refusal(text: str) -> bool:
    """Detect when the LLM responded conversationally instead of calling a tool.

    With tool_choice="auto", simpler agent variants (basic, restricted)
    sometimes emit a "ready to help" reply rather than invoking write_file
    or read_file.  This helper catches those patterns so the caller can
    retry with a more forceful prompt.
    """
    lower = text.lower()
    refusal_phrases = (
        "i am ready",
        "i'm ready",
        "ready to help",
        "ready to assist",
        "how can i help",
        "how can i assist",
        "what would you like",
        "let me know",
        "respond_to_user",
    )
    return any(phrase in lower for phrase in refusal_phrases)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("agent_name", AGENT_VARIANTS)
class TestAgentCard:
    """Verify each agent variant serves a valid agent card."""

    def test_agent_card_accessible(self, agent_name: str):
        agent_url = _get_agent_url(agent_name)
        _skip_if_unreachable(agent_name, agent_url)
        client = _make_client(agent_name)

        resp = client.get(f"{agent_url}/.well-known/agent-card.json")
        assert resp.status_code == 200, f"Agent card not accessible: {resp.status_code}"

        card = resp.json()
        assert "capabilities" in card, "Agent card missing capabilities"
        assert "defaultInputModes" in card, "Agent card missing defaultInputModes"
        client.close()

    def test_agent_card_has_streaming(self, agent_name: str):
        agent_url = _get_agent_url(agent_name)
        _skip_if_unreachable(agent_name, agent_url)
        client = _make_client(agent_name)

        resp = client.get(f"{agent_url}/.well-known/agent-card.json")
        card = resp.json()
        assert card.get("capabilities", {}).get("streaming") is True, (
            f"Agent {agent_name} should support streaming"
        )
        client.close()


@pytest.mark.timeout(900)
@pytest.mark.parametrize("agent_name", AGENT_VARIANTS)
class TestMultiTurnConversation:
    """Verify multi-turn conversation with tool calls for each variant."""

    def test_shell_command(self, agent_name: str):
        """Agent can execute a shell command and return output.

        Retries with a fresh context_id if the reporter returns an
        empty/placeholder response (transient accumulator issue).
        """
        agent_url = _get_agent_url(agent_name)
        _skip_if_unreachable(agent_name, agent_url)
        client = _make_client(agent_name)

        text = ""
        for attempt in range(5):
            context_id = uuid4().hex[:36]
            result = _send_message(
                client,
                agent_url,
                "Run the command: echo hello-from-test",
                context_id,
            )
            text = _extract_text(result)
            if text:
                break
            if attempt < 4:
                import time

                time.sleep(2)

        assert text, f"Agent {agent_name} returned empty response after 5 attempts"
        assert "hello-from-test" in text.lower(), (
            f"Agent {agent_name} response doesn't contain expected echo output: {text[:200]}"
        )
        client.close()

    def test_file_write_and_read(self, agent_name: str):
        """Agent can write a file and read it back in the same session.

        Retries with a fresh context_id on empty write response (transient
        reporter accumulation issue).  Also retries within the same session
        when the LLM returns a conversational reply (e.g. "I am ready...")
        instead of calling the file tool -- a known non-determinism with
        tool_choice="auto" on simpler agent variants.
        """
        agent_url = _get_agent_url(agent_name)
        _skip_if_unreachable(agent_name, agent_url)
        client = _make_client(agent_name)

        text2 = ""
        last_marker = ""
        for attempt in range(5):
            context_id = uuid4().hex[:36]
            last_marker = f"variant-test-{agent_name}-{uuid4().hex[:8]}"

            # Explicit prompt that steers the LLM toward tool invocation
            write_prompt = (
                f"Use the write_file tool to create a file named variant-marker.txt "
                f'with the exact content "{last_marker}". '
                f"Do NOT just respond with text -- you MUST call the write_file tool."
            )

            result1 = _send_message(
                client,
                agent_url,
                write_prompt,
                context_id,
            )
            text1 = _extract_text(result1)

            # Detect LLM non-determinism: agent replied conversationally
            # instead of calling the tool.  Retry within the same session
            # (the LLM usually complies on a follow-up nudge).
            if not text1 or _is_tool_refusal(text1):
                if not text1:
                    # Empty response -- retry with fresh context
                    if attempt < 4:
                        import time

                        time.sleep(2)
                    continue
                # Non-empty but refused to call tool -- nudge once more
                result1 = _send_message(
                    client,
                    agent_url,
                    (
                        "You did not write the file. Please call the write_file "
                        "tool NOW to create variant-marker.txt with content "
                        f'"{last_marker}". Do not reply with text, use the tool.'
                    ),
                    context_id,
                )
                text1 = _extract_text(result1)
                if not text1 or _is_tool_refusal(text1):
                    if attempt < 4:
                        import time

                        time.sleep(2)
                    continue

            result2 = _send_message(
                client,
                agent_url,
                (
                    "Use the read_file tool to read the file variant-marker.txt "
                    "and show me its exact contents."
                ),
                context_id,
            )
            text2 = _extract_text(result2)
            if last_marker in text2:
                break
            if attempt < 4:
                import time

                time.sleep(2)

        assert last_marker in text2, (
            f"Agent {agent_name} did not return marker '{last_marker}' from file read "
            f"after 5 attempts. Got: {text2[:300]}"
        )
        client.close()

    def test_multi_turn_context_memory(self, agent_name: str):
        """Agent remembers information across turns within the same session.

        Retries with a fresh context_id and new secret word if the agent
        returns an empty or irrelevant response on either turn.
        """
        agent_url = _get_agent_url(agent_name)
        _skip_if_unreachable(agent_name, agent_url)
        client = _make_client(agent_name)

        text2 = ""
        last_secret = ""
        for attempt in range(5):
            context_id = uuid4().hex[:36]
            last_secret = f"zebra-{uuid4().hex[:6]}"

            _send_message(
                client,
                agent_url,
                f"Remember this secret word: {last_secret}. Just acknowledge.",
                context_id,
            )

            result2 = _send_message(
                client,
                agent_url,
                "What was the secret word I told you earlier?",
                context_id,
            )
            text2 = _extract_text(result2)
            if last_secret in text2:
                break
            if attempt < 4:
                import time

                time.sleep(2)

        assert last_secret in text2, (
            f"Agent {agent_name} forgot the secret word '{last_secret}' "
            f"after 5 attempts. Got: {text2[:300]}"
        )
        client.close()


@pytest.mark.timeout(900)
@pytest.mark.parametrize("agent_name", AGENT_VARIANTS)
class TestSessionIsolation:
    """Verify that different sessions are isolated from each other."""

    def test_workspace_isolation(self, agent_name: str):
        """Files in session A are NOT visible in session B.

        Retries on transient connection drops (RemoteProtocolError,
        timeout) with fresh sessions.
        """
        agent_url = _get_agent_url(agent_name)
        _skip_if_unreachable(agent_name, agent_url)

        text_b = ""
        last_marker = ""
        for attempt in range(5):
            client = _make_client(agent_name)
            session_a = uuid4().hex[:36]
            session_b = uuid4().hex[:36]
            last_marker = f"isolation-{agent_name}-{uuid4().hex[:8]}"

            try:
                _send_message(
                    client,
                    agent_url,
                    (
                        f"Use the write_file tool to create a file named "
                        f'isolation-test.txt with content "{last_marker}". '
                        f"You MUST call the write_file tool."
                    ),
                    session_a,
                )

                result_b = _send_message(
                    client,
                    agent_url,
                    "Read the file isolation-test.txt. If it does not exist, say FILE_NOT_FOUND.",
                    session_b,
                )
                text_b = _extract_text(result_b)
                break
            except (RuntimeError, Exception):
                if attempt < 4:
                    import time

                    time.sleep(2)
                    continue
                raise
            finally:
                client.close()

        assert last_marker not in text_b, (
            f"Session isolation FAILED for {agent_name}: "
            f"Session B contains Session A's marker '{last_marker}'. Got: {text_b[:300]}"
        )
