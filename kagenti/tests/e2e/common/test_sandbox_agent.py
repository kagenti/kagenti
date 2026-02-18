#!/usr/bin/env python3
"""
Sandbox Agent E2E Tests for Kagenti Platform

Tests sandbox agent functionality via A2A protocol:
- Agent deployment and agent card
- Shell command execution (ls, grep)
- File write and read operations
- Multi-turn context persistence (same contextId sees prior files)

Usage:
    SANDBOX_AGENT_URL=http://... pytest tests/e2e/common/test_sandbox_agent.py -v
"""

import os
import pathlib

import pytest
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


def _get_ssl_context():
    """Get SSL context for httpx client."""
    import ssl

    if not _is_openshift_from_config():
        return True

    ca_path = os.getenv("OPENSHIFT_INGRESS_CA")
    if not ca_path or not pathlib.Path(ca_path).exists():
        ca_path = _fetch_openshift_ingress_ca()

    if not ca_path:
        raise RuntimeError(
            "Could not fetch OpenShift ingress CA certificate. "
            "Set OPENSHIFT_INGRESS_CA env var to the CA bundle path."
        )

    return ssl.create_default_context(cafile=ca_path)


async def _extract_response(client, message):
    """Send an A2A message and extract the full text response."""
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


async def _connect_to_agent(agent_url):
    """Connect to the sandbox agent via A2A protocol."""
    ssl_verify = _get_ssl_context()
    httpx_client = httpx.AsyncClient(timeout=120.0, verify=ssl_verify)
    config = ClientConfig(httpx_client=httpx_client)

    from a2a.client.card_resolver import A2ACardResolver

    resolver = A2ACardResolver(httpx_client, agent_url)
    card = await resolver.get_agent_card()
    card.url = agent_url
    client = await ClientFactory.connect(card, client_config=config)
    return client, card


class TestSandboxAgentDeployment:
    """Verify sandbox-agent deployment and agent card."""

    def test_deployment_ready(self, k8s_apps_client):
        """Verify sandbox-agent deployment exists and is ready."""
        deployment = k8s_apps_client.read_namespaced_deployment(
            name="sandbox-agent", namespace="team1"
        )
        assert deployment is not None
        desired = deployment.spec.replicas or 1
        ready = deployment.status.ready_replicas or 0
        assert ready >= desired, f"sandbox-agent not ready: {ready}/{desired} replicas"

    def test_service_exists(self, k8s_client):
        """Verify sandbox-agent service exists."""
        service = k8s_client.read_namespaced_service(
            name="sandbox-agent", namespace="team1"
        )
        assert service is not None

    @pytest.mark.asyncio
    async def test_agent_card(self):
        """Verify agent card returns correct metadata."""
        agent_url = os.getenv(
            "SANDBOX_AGENT_URL", "http://sandbox-agent.team1.svc.cluster.local:8000"
        )
        try:
            _, card = await _connect_to_agent(agent_url)
        except Exception as e:
            pytest.fail(f"Sandbox agent not reachable at {agent_url}: {e}")

        assert card.name == "Sandbox Assistant", f"Unexpected agent name: {card.name}"
        assert card.capabilities.streaming is True
        assert len(card.skills) > 0

        skill_tags = []
        for skill in card.skills:
            skill_tags.extend(skill.tags or [])
        assert "shell" in skill_tags, f"Missing 'shell' tag in skills: {skill_tags}"

        print(f"\n  Agent card: {card.name}")
        print(f"  Skills: {[s.name for s in card.skills]}")
        print(f"  Tags: {skill_tags}")


class TestSandboxAgentShellExecution:
    """Test shell command execution via A2A protocol."""

    @pytest.mark.asyncio
    async def test_shell_ls(self):
        """
        Test agent can list workspace directory contents.

        Sends a natural language request to list files.
        Expects the response to mention workspace subdirectories.
        """
        agent_url = os.getenv(
            "SANDBOX_AGENT_URL", "http://sandbox-agent.team1.svc.cluster.local:8000"
        )
        try:
            client, _ = await _connect_to_agent(agent_url)
        except Exception as e:
            pytest.fail(f"Sandbox agent not reachable at {agent_url}: {e}")

        message = A2AMessage(
            role="user",
            parts=[
                TextPart(text="List the contents of the current directory using ls")
            ],
            messageId=uuid4().hex,
        )

        try:
            response, events = await _extract_response(client, message)
        except Exception as e:
            pytest.fail(f"Error during A2A conversation: {e}")

        assert response, f"Agent did not return any response\n  Events: {events}"

        # The workspace should have subdirectories from ensure_workspace
        response_lower = response.lower()
        workspace_indicators = ["data", "scripts", "repos", "output"]
        has_workspace_content = any(
            indicator in response_lower for indicator in workspace_indicators
        )

        print(f"\n  Response: {response[:300]}")
        print(f"  Events: {events}")

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
        """
        agent_url = os.getenv(
            "SANDBOX_AGENT_URL", "http://sandbox-agent.team1.svc.cluster.local:8000"
        )
        try:
            client, _ = await _connect_to_agent(agent_url)
        except Exception as e:
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
            pytest.fail(f"Error during A2A conversation: {e}")

        assert response, f"Agent did not return any response\n  Events: {events}"

        print(f"\n  Response: {response[:300]}")
        print(f"  Events: {events}")

        assert "sandbox-e2e-test-payload" in response, (
            f"Response doesn't contain the written content.\n"
            f"Expected: 'sandbox-e2e-test-payload'\n"
            f"Response: {response}"
        )


class TestSandboxAgentContextPersistence:
    """Test multi-turn context persistence via shared contextId."""

    @pytest.mark.asyncio
    async def test_multi_turn_file_persistence(self, test_session_id):
        """
        Test that files written in turn 1 are readable in turn 2
        when using the same contextId.

        Turn 1: Write a file with unique content
        Turn 2: Read the file back and verify content matches
        """
        agent_url = os.getenv(
            "SANDBOX_AGENT_URL", "http://sandbox-agent.team1.svc.cluster.local:8000"
        )
        try:
            client, _ = await _connect_to_agent(agent_url)
        except Exception as e:
            pytest.fail(f"Sandbox agent not reachable at {agent_url}: {e}")

        context_id = f"e2e-{test_session_id}"
        unique_marker = f"persistence-check-{uuid4().hex[:8]}"

        print(f"\n=== Multi-turn Context Persistence Test ===")
        print(f"  Context ID: {context_id}")
        print(f"  Unique marker: {unique_marker}")

        # Turn 1: Write a file
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

        try:
            response1, events1 = await _extract_response(client, msg1)
        except Exception as e:
            pytest.fail(f"Turn 1 failed: {e}")

        assert response1, f"Turn 1: No response\n  Events: {events1}"
        print(f"  Turn 1 response: {response1[:200]}")

        # Turn 2: Read the file back
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

        try:
            response2, events2 = await _extract_response(client, msg2)
        except Exception as e:
            pytest.fail(f"Turn 2 failed: {e}")

        assert response2, f"Turn 2: No response\n  Events: {events2}"
        print(f"  Turn 2 response: {response2[:200]}")

        assert unique_marker in response2, (
            f"Turn 2 response doesn't contain the marker from turn 1.\n"
            f"Expected: '{unique_marker}'\n"
            f"Turn 2 response: {response2}"
        )

        print(f"\n  Multi-turn persistence verified")
        print(f"  Marker '{unique_marker}' survived across turns")


if __name__ == "__main__":
    import sys

    sys.exit(pytest.main([__file__, "-v"]))
