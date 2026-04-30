#!/usr/bin/env python3
"""
Sandbox Legion E2E Tests for Kagenti Platform

Tests sandbox legion functionality via A2A protocol:
- Agent deployment and agent card
- Shell command execution (ls, grep)
- File write and read operations
- Multi-turn context persistence (same contextId sees prior files)

Usage:
    SANDBOX_LEGION_URL=http://... pytest tests/e2e/common/test_sandbox_agent.py -v
"""

import asyncio
import os
import pathlib

import pytest

pytest.importorskip("a2a.client", reason="a2a package not available")

import httpx
import yaml
from uuid import uuid4
from a2a.client import ClientConfig, ClientFactory
from a2a.types import (
    Message as A2AMessage,
    TextPart,
    TaskArtifactUpdateEvent,
)

from kagenti.tests.e2e.conftest import (
    _fetch_openshift_ingress_ca,
)

# Skip entire module if sandbox feature is not enabled
# Uses requires_features marker (reads featureFlags from config YAML or ENABLE_SANDBOX_TESTS env)
pytestmark = pytest.mark.requires_features(["sandbox"])


def _get_sandbox_legion_url() -> str:
    """Get the sandbox legion URL from env or default to in-cluster DNS."""
    return os.getenv(
        "SANDBOX_LEGION_URL",
        "http://sandbox-legion.team1.svc.cluster.local:8000",
    )


def _is_openshift_from_config():
    """Detect if running on OpenShift from KAGENTI_CONFIG_FILE."""
    config_file = os.getenv("KAGENTI_CONFIG_FILE")
    if not config_file:
        return False

    config_path = pathlib.Path(config_file)
    if not config_path.is_absolute():
        repo_root = pathlib.Path(__file__).parent.parent.parent.parent.parent
        config_path = repo_root / config_file

    if not config_path.exists():
        return False

    try:
        with open(config_path) as f:
            config = yaml.safe_load(f)
    except Exception:
        return False

    if config.get("openshift", False):
        return True

    charts = config.get("charts", {})
    if charts.get("kagenti-deps", {}).get("values", {}).get("openshift", False):
        return True
    if charts.get("kagenti", {}).get("values", {}).get("openshift", False):
        return True

    return False


def _fetch_ingress_ca():
    """Fetch OpenShift ingress CA from default-ingress-cert configmap."""
    import subprocess
    import tempfile

    # Try the ingress-specific CA first (signs route certificates)
    for ns, cm, key in [
        ("kagenti-system", "kube-root-ca.crt", "ca.crt"),
        ("openshift-config", "kube-root-ca.crt", "ca.crt"),
        ("openshift-config-managed", "default-ingress-cert", "ca-bundle.crt"),
    ]:
        jsonpath = "{.data." + key.replace(".", "\\.") + "}"
        try:
            result = subprocess.run(
                [
                    "kubectl",
                    "get",
                    "configmap",
                    cm,
                    "-n",
                    ns,
                    "-o",
                    f"jsonpath={jsonpath}",
                ],
                capture_output=True,
                text=True,
                timeout=15,
            )
            if result.returncode == 0 and result.stdout.startswith("-----BEGIN"):
                f = tempfile.NamedTemporaryFile(
                    mode="w", suffix=".crt", delete=False, prefix="ingress-ca-"
                )
                f.write(result.stdout)
                f.close()
                return f.name
        except Exception:
            continue
    return None


def _get_ssl_context():
    """Get SSL context for httpx client."""
    import ssl

    if not _is_openshift_from_config():
        return True

    ca_path = os.getenv("OPENSHIFT_INGRESS_CA")
    if not ca_path or not pathlib.Path(ca_path).exists():
        ca_path = _fetch_ingress_ca()
    if not ca_path:
        ca_path = _fetch_openshift_ingress_ca()

    if not ca_path:
        raise RuntimeError(
            "Could not fetch OpenShift ingress CA certificate. "
            "Set OPENSHIFT_INGRESS_CA env var to the CA bundle path."
        )

    return ssl.create_default_context(cafile=ca_path)


def _send_message_raw(agent_url: str, text: str) -> dict:
    """Send A2A message via raw httpx SSE streaming (sync).

    More reliable than the A2A SDK's send_message which sometimes
    returns empty due to response timing issues.
    """
    import json as _json

    ssl_verify = _get_ssl_context()
    verify = ssl_verify if isinstance(ssl_verify, bool) else ssl_verify
    client = httpx.Client(timeout=300.0, verify=verify, follow_redirects=True)
    payload = {
        "jsonrpc": "2.0",
        "id": uuid4().hex,
        "method": "message/stream",
        "params": {
            "message": {
                "role": "user",
                "parts": [{"kind": "text", "text": text}],
                "messageId": uuid4().hex,
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
                        event = _json.loads(line[6:])
                    except _json.JSONDecodeError:
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
    finally:
        client.close()
    return result


async def _extract_response(client, message):
    """Send an A2A message (non-streaming) and extract the text response.

    Uses the non-streaming send_message API which returns a direct JSON
    response. This avoids SSE connection drops from OpenShift routes.
    """
    from a2a.types import SendMessageRequest, MessageSendParams

    params = MessageSendParams(message=message)
    request = SendMessageRequest(id=uuid4().hex, params=params)
    response = await client.send_message(request)

    # Extract from response
    root = getattr(response, "root", response)
    if hasattr(root, "error") and root.error:
        raise RuntimeError(f"A2A error: {root.error}")

    result = getattr(root, "result", None)
    if result is None:
        return "", ["NoResult"]

    full_response = ""
    events_received = ["NonStreaming"]

    # Result can be a Task or a Message
    if hasattr(result, "artifacts") and result.artifacts:
        for artifact in result.artifacts:
            for part in artifact.parts or []:
                p = getattr(part, "root", part)
                if hasattr(p, "text"):
                    full_response += p.text
    elif hasattr(result, "parts"):
        for part in result.parts or []:
            p = getattr(part, "root", part)
            if hasattr(p, "text"):
                full_response += p.text

    return full_response, events_received


async def _connect_to_agent(agent_url):
    """Connect to the sandbox legion via A2A protocol."""
    ssl_verify = _get_ssl_context()
    httpx_client = httpx.AsyncClient(timeout=180.0, verify=ssl_verify)

    from a2a.client import A2AClient
    from a2a.client.card_resolver import A2ACardResolver

    resolver = A2ACardResolver(httpx_client, agent_url)
    card = await resolver.get_agent_card()
    card.url = agent_url
    client = A2AClient(httpx_client=httpx_client, url=agent_url)
    return client, card


async def _connect_to_agent_streaming(agent_url):
    """Connect to the sandbox legion via A2A streaming protocol.

    Uses ClientFactory which returns a streaming-capable client.
    SSE streaming keeps the connection alive with heartbeat events,
    avoiding gateway timeouts on multi-turn requests.
    """
    ssl_verify = _get_ssl_context()
    httpx_client = httpx.AsyncClient(timeout=180.0, verify=ssl_verify)
    config = ClientConfig(httpx_client=httpx_client)

    from a2a.client.card_resolver import A2ACardResolver

    resolver = A2ACardResolver(httpx_client, agent_url)
    card = await resolver.get_agent_card()
    card.url = agent_url
    client = await ClientFactory.connect(card, client_config=config)
    return client, card


async def _extract_response_streaming(client, message):
    """Send an A2A message via streaming and extract the text response.

    Uses SSE streaming which keeps the connection alive with heartbeat
    events, preventing gateway timeouts on long-running multi-turn
    requests (LLM call + checkpointer lookup).
    """
    full_response = ""
    events_received = []

    async for result in client.send_message(message):
        if isinstance(result, tuple):
            task, event = result
            events_received.append(type(event).__name__ if event else "Task(final)")

            if isinstance(event, TaskArtifactUpdateEvent):
                if hasattr(event, "artifact") and event.artifact:
                    for part in event.artifact.parts or []:
                        p = getattr(part, "root", part)
                        if hasattr(p, "text"):
                            full_response += p.text

            if event is None and task and task.artifacts:
                for artifact in task.artifacts:
                    for part in artifact.parts or []:
                        p = getattr(part, "root", part)
                        if hasattr(p, "text"):
                            full_response += p.text

        elif isinstance(result, A2AMessage):
            events_received.append("Message")
            for part in result.parts or []:
                p = getattr(part, "root", part)
                if hasattr(p, "text"):
                    full_response += p.text

    return full_response, events_received


class TestSandboxLegionDeployment:
    """Verify sandbox-legion deployment and agent card."""

    def test_deployment_ready(self, k8s_apps_client):
        """Verify sandbox-legion deployment exists and is ready."""
        deployment = k8s_apps_client.read_namespaced_deployment(
            name="sandbox-legion", namespace="team1"
        )
        assert deployment is not None
        desired = deployment.spec.replicas or 1
        ready = deployment.status.ready_replicas or 0
        assert ready >= desired, f"sandbox-legion not ready: {ready}/{desired} replicas"

    def test_service_exists(self, k8s_client):
        """Verify sandbox-legion service exists."""
        service = k8s_client.read_namespaced_service(
            name="sandbox-legion", namespace="team1"
        )
        assert service is not None

    @pytest.mark.asyncio
    async def test_agent_card(self):
        """Verify agent card returns correct metadata."""
        agent_url = _get_sandbox_legion_url()
        try:
            _, card = await _connect_to_agent(agent_url)
        except Exception as e:
            pytest.fail(f"Sandbox agent not reachable at {agent_url}: {e}")

        assert card.name in ("Sandbox Assistant", "Sandbox Legion"), (
            f"Unexpected agent name: {card.name}"
        )
        assert card.capabilities.streaming is True
        assert len(card.skills) > 0

        skill_tags = []
        for skill in card.skills:
            skill_tags.extend(skill.tags or [])
        assert "shell" in skill_tags, f"Missing 'shell' tag in skills: {skill_tags}"

        print(f"\n  Agent card: {card.name}")
        print(f"  Skills: {[s.name for s in card.skills]}")
        print(f"  Tags: {skill_tags}")


class TestSandboxLegionShellExecution:
    """Test shell command execution via A2A protocol."""

    @pytest.mark.asyncio
    async def test_shell_ls(self):
        """
        Test agent can list workspace directory contents.

        Uses raw httpx SSE streaming instead of A2A SDK send_message
        because the SDK's non-streaming API sometimes returns empty.
        """
        agent_url = _get_sandbox_legion_url()

        response = ""
        for attempt in range(5):
            result = await asyncio.to_thread(
                _send_message_raw, agent_url, "Run the command: ls"
            )
            for artifact in result.get("artifacts", []):
                for part in artifact.get("parts", []):
                    if "text" in part:
                        response += part["text"]
            if not response:
                status = result.get("status", {})
                msg = status.get("message", {}) if isinstance(status, dict) else {}
                for part in msg.get("parts", []) if isinstance(msg, dict) else []:
                    if "text" in part:
                        response += part["text"]
            if response and response.strip().lower() not in (
                "no response generated.",
                "no response generated",
            ):
                break
            response = ""
            if attempt < 4:
                await asyncio.sleep(2)

        assert response, f"Agent returned empty after 5 attempts"

        response_lower = response.lower()
        workspace_indicators = ["data", "scripts", "repos", "output"]
        has_workspace_content = any(
            indicator in response_lower for indicator in workspace_indicators
        )

        print(f"\n  Response: {response[:300]}")

        assert has_workspace_content, (
            f"Response doesn't mention workspace directories.\n"
            f"Expected one of: {workspace_indicators}\n"
            f"Response: {response}"
        )

    @pytest.mark.asyncio
    async def test_file_write_and_read(self):
        """
        Test agent can write a file and read it back.

        Sends a request to write content to a file, then read it.
        Expects the response to contain the written content.
        Retries up to 3 times with fresh message IDs on failure.
        """
        agent_url = _get_sandbox_legion_url()

        response = ""
        last_error = ""
        for attempt in range(3):
            try:
                client, _ = await _connect_to_agent(agent_url)
            except Exception as e:
                last_error = str(e)
                if attempt < 2:
                    await asyncio.sleep(2)
                    continue
                pytest.fail(f"Sandbox agent not reachable at {agent_url}: {e}")

            message = A2AMessage(
                role="user",
                parts=[
                    TextPart(
                        text=(
                            "Write the text 'sandbox-e2e-test-payload' to a file "
                            "called data/e2e_test.txt, then read it back and tell "
                            "me exactly what the file contains."
                        )
                    )
                ],
                messageId=uuid4().hex,
            )

            try:
                response, events = await _extract_response(client, message)
            except Exception as e:
                last_error = str(e)
                if attempt < 2:
                    await asyncio.sleep(2)
                    continue
                pytest.fail(f"Error during A2A conversation: {e}")

            if response and "sandbox-e2e-test-payload" in response:
                break
            last_error = f"Response missing payload: {response[:200]}"
            if attempt < 2:
                await asyncio.sleep(2)

        assert response, (
            f"Agent did not return any response after 3 attempts. "
            f"Last error: {last_error}"
        )

        print(f"\n  Response: {response[:300]}")

        assert "sandbox-e2e-test-payload" in response, (
            f"Response doesn't contain the written content after 3 attempts.\n"
            f"Expected: 'sandbox-e2e-test-payload'\n"
            f"Response: {response}"
        )


class TestSandboxLegionContextPersistence:
    """Test multi-turn context persistence via shared contextId.

    Each turn uses a fresh non-streaming HTTP request to avoid
    connection drops from the OpenShift route / Istio ztunnel.
    """

    @pytest.mark.asyncio
    async def test_multi_turn_file_persistence(self, test_session_id):
        """
        Test that files written in turn 1 are readable in turn 2
        when using the same contextId.

        Turn 1: Write a file with unique content
        Turn 2: Read the file back and verify content matches
        """
        agent_url = _get_sandbox_legion_url()

        # contextId must be <= 36 chars (VARCHAR(36) in A2A SDK tasks table)
        context_id = uuid4().hex[:36]
        unique_marker = f"persistence-check-{uuid4().hex[:8]}"

        print(f"\n=== Multi-turn Context Persistence Test ===")
        print(f"  Context ID: {context_id}")
        print(f"  Unique marker: {unique_marker}")

        # Turn 1: Write a file (fresh connection)
        client1, _ = await _connect_to_agent(agent_url)
        msg1 = A2AMessage(
            role="user",
            parts=[
                TextPart(
                    text=f"Write the text '{unique_marker}' to a file called data/persist_test.txt"
                )
            ],
            messageId=uuid4().hex,
            contextId=context_id,
        )

        response1, events1 = await _extract_response(client1, msg1)
        assert response1, f"Turn 1: No response\n  Events: {events1}"
        print(f"  Turn 1 response: {response1[:200]}")

        # Turn 2: Read the file back (fresh connection)
        client2, _ = await _connect_to_agent(agent_url)
        msg2 = A2AMessage(
            role="user",
            parts=[
                TextPart(
                    text="Read the file data/persist_test.txt and tell me exactly what it contains."
                )
            ],
            messageId=uuid4().hex,
            contextId=context_id,
        )

        response2, events2 = await _extract_response(client2, msg2)
        assert response2, f"Turn 2: No response\n  Events: {events2}"
        print(f"  Turn 2 response: {response2[:200]}")

        assert unique_marker in response2, (
            f"Turn 2 response doesn't contain the marker from turn 1.\n"
            f"Expected: '{unique_marker}'\n"
            f"Turn 2 response: {response2}"
        )

        print(f"\n  Multi-turn persistence verified")
        print(f"  Marker '{unique_marker}' survived across turns")


class TestSandboxLegionMemory:
    """Test multi-turn conversational memory via shared contextId.

    Each turn uses a fresh non-streaming HTTP request to avoid
    connection drops from the OpenShift route / Istio ztunnel.
    """

    @pytest.mark.asyncio
    async def test_multi_turn_memory(self, test_session_id):
        """
        Verify agent remembers context across turns.

        Turn 1: Tell the agent a name ("My name is Bob Beep")
        Turn 2: Ask for the name back ("What is my name?")
        Expects the agent to recall "Bob Beep" from turn 1.
        """
        agent_url = _get_sandbox_legion_url()

        # contextId must be <= 36 chars (VARCHAR(36) in A2A SDK tasks table)
        context_id = uuid4().hex[:36]

        print(f"\n=== Multi-turn Memory Test ===")
        print(f"  Context ID: {context_id}")

        # Turn 1: Tell the agent a name (fresh connection)
        client1, _ = await _connect_to_agent(agent_url)
        msg1 = A2AMessage(
            role="user",
            parts=[TextPart(text="My name is Bob Beep")],
            messageId=uuid4().hex,
            contextId=context_id,
        )

        response1, events1 = await _extract_response(client1, msg1)
        assert response1, f"Turn 1: No response\n  Events: {events1}"
        print(f"  Turn 1 response: {response1[:200]}")

        # Turn 2: Ask for the name back (fresh connection)
        client2, _ = await _connect_to_agent(agent_url)
        msg2 = A2AMessage(
            role="user",
            parts=[TextPart(text="What is my name?")],
            messageId=uuid4().hex,
            contextId=context_id,
        )

        response2, events2 = await _extract_response(client2, msg2)
        assert response2, f"Turn 2: No response\n  Events: {events2}"
        print(f"  Turn 2 response: {response2[:200]}")

        response2_lower = response2.lower()
        assert "bob" in response2_lower and (
            "beep" in response2_lower or "bob beep" in response2_lower
        ), (
            f"Agent didn't remember the name.\n"
            f"Expected 'Bob' and 'Beep' in response.\n"
            f"Response: {response2}"
        )

        print(f"\n  Multi-turn memory verified: agent remembered the name")


if __name__ == "__main__":
    import sys

    sys.exit(pytest.main([__file__, "-v"]))
