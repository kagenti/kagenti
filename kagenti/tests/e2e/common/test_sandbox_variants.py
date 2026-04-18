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

    Uses 300s timeout because message/send blocks until the full multi-node
    graph completes (router+planner+executor+reporter).  With MaaS models
    each LLM call can take 30-60s, and the graph has 4 nodes.
    """
    kwargs: dict = {"timeout": 300.0, "follow_redirects": True}
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
    """Verify agent is reachable — fail (not skip) if deployed but broken."""
    client = _make_client(agent_name)
    try:
        resp = client.get(
            f"{agent_url}/.well-known/agent-card.json",
            timeout=10.0,
        )
        resp.raise_for_status()
    except Exception as exc:
        env_key = f"SANDBOX_{agent_name.split('-', 1)[-1].upper()}_URL"
        pytest.fail(
            f"Agent {agent_name} not reachable at {agent_url} "
            f"(set {env_key} to the route URL): {exc}"
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
                    result.setdefault("artifacts", []).append(event_result["artifact"])
                if "status" in event_result:
                    result["status"] = event_result["status"]
                if "contextId" in event_result:
                    result["contextId"] = event_result["contextId"]
                if kind == "task" and event_result.get("status", {}).get("state") in (
                    "completed",
                    "failed",
                    "canceled",
                ):
                    if "artifacts" in event_result:
                        result["artifacts"] = event_result["artifacts"]
                    break

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
    # Filter out generic reporter placeholder — treat as empty so callers
    # can distinguish a real response from a reporter accumulation failure.
    if combined.strip().lower() in ("no response generated.", "no response generated"):
        return ""
    return combined


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


@pytest.mark.parametrize("agent_name", AGENT_VARIANTS)
class TestMultiTurnConversation:
    """Verify multi-turn conversation with tool calls for each variant."""

    def test_shell_command(self, agent_name: str):
        """Agent can execute a shell command and return output.

        Retries once with a fresh context_id if the reporter returns an
        empty/placeholder response (transient accumulator issue).
        """
        agent_url = _get_agent_url(agent_name)
        _skip_if_unreachable(agent_name, agent_url)
        client = _make_client(agent_name)

        text = ""
        for attempt in range(3):
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
            if attempt < 2:
                import time

                time.sleep(2)

        assert text, f"Agent {agent_name} returned empty response after 3 attempts"
        # The response must contain the actual echo output
        assert "hello-from-test" in text.lower(), (
            f"Agent {agent_name} response doesn't contain expected echo output: {text[:200]}"
        )
        client.close()

    def test_file_write_and_read(self, agent_name: str):
        """Agent can write a file and read it back in the same session."""
        agent_url = _get_agent_url(agent_name)
        _skip_if_unreachable(agent_name, agent_url)
        client = _make_client(agent_name)
        context_id = uuid4().hex[:36]
        marker = f"variant-test-{agent_name}-{uuid4().hex[:8]}"

        # Turn 1: Write file
        result1 = _send_message(
            client,
            agent_url,
            f'Write the text "{marker}" to a file called variant-marker.txt',
            context_id,
        )
        text1 = _extract_text(result1)
        assert text1, f"Write response empty for {agent_name}"

        # Turn 2: Read file back
        result2 = _send_message(
            client,
            agent_url,
            "Read the file variant-marker.txt and tell me its exact contents.",
            context_id,
        )
        text2 = _extract_text(result2)
        assert marker in text2, (
            f"Agent {agent_name} did not return marker '{marker}' from file read. "
            f"Got: {text2[:300]}"
        )
        client.close()

    def test_multi_turn_context_memory(self, agent_name: str):
        """Agent remembers information across turns within the same session."""
        agent_url = _get_agent_url(agent_name)
        _skip_if_unreachable(agent_name, agent_url)
        client = _make_client(agent_name)
        context_id = uuid4().hex[:36]
        secret_word = f"zebra-{uuid4().hex[:6]}"

        # Turn 1: Tell agent a secret word
        _send_message(
            client,
            agent_url,
            f"Remember this secret word: {secret_word}. Just acknowledge.",
            context_id,
        )

        # Turn 2: Ask for the secret word
        result2 = _send_message(
            client,
            agent_url,
            "What was the secret word I told you earlier?",
            context_id,
        )
        text2 = _extract_text(result2)
        assert secret_word in text2, (
            f"Agent {agent_name} forgot the secret word '{secret_word}'. "
            f"Got: {text2[:300]}"
        )
        client.close()


@pytest.mark.parametrize("agent_name", AGENT_VARIANTS)
class TestSessionIsolation:
    """Verify that different sessions are isolated from each other."""

    def test_workspace_isolation(self, agent_name: str):
        """Files in session A are NOT visible in session B."""
        agent_url = _get_agent_url(agent_name)
        _skip_if_unreachable(agent_name, agent_url)
        client = _make_client(agent_name)

        session_a = uuid4().hex[:36]
        session_b = uuid4().hex[:36]
        marker = f"isolation-{agent_name}-{uuid4().hex[:8]}"

        # Session A: Write a file
        _send_message(
            client,
            agent_url,
            f'Write "{marker}" to isolation-test.txt',
            session_a,
        )

        # Session B: Try to read the file (should not exist)
        result_b = _send_message(
            client,
            agent_url,
            "Read the file isolation-test.txt. If it does not exist, say FILE_NOT_FOUND.",
            session_b,
        )
        text_b = _extract_text(result_b)
        # Session B should NOT contain the marker from Session A
        assert marker not in text_b, (
            f"Session isolation FAILED for {agent_name}: "
            f"Session B contains Session A's marker '{marker}'. Got: {text_b[:300]}"
        )
        client.close()
