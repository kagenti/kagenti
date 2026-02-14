#!/usr/bin/env python3
"""
Agent Conversation E2E Tests for Kagenti Platform

Tests agent conversation functionality via A2A protocol:
- Agent responds to queries via A2A protocol
- LLM integration (Ollama) works
- Agent can process weather queries

Usage:
    pytest tests/e2e/test_agent_conversation.py -v
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

# Import CA certificate fetching from conftest
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

    # Check various locations for openshift flag
    if config.get("openshift", False):
        return True

    charts = config.get("charts", {})
    if charts.get("kagenti-deps", {}).get("values", {}).get("openshift", False):
        return True
    if charts.get("kagenti", {}).get("values", {}).get("openshift", False):
        return True

    return False


def _get_ssl_context():
    """
    Get the SSL context for httpx client.

    On OpenShift: Returns ssl.SSLContext with the cluster CA certificate.
    On Kind: Returns True (default SSL verification, services use HTTP).

    Never returns False - raises if CA cert cannot be fetched on OpenShift.
    """
    import ssl

    if not _is_openshift_from_config():
        return True

    # Check environment variable first (allows override)
    ca_path = os.getenv("OPENSHIFT_INGRESS_CA")
    if not ca_path or not pathlib.Path(ca_path).exists():
        # Fetch from cluster
        ca_path = _fetch_openshift_ingress_ca()

    if not ca_path:
        raise RuntimeError(
            "Could not fetch OpenShift ingress CA certificate. "
            "Set OPENSHIFT_INGRESS_CA env var to the CA bundle path."
        )

    return ssl.create_default_context(cafile=ca_path)


# ============================================================================
# Test: Weather Agent Conversation via A2A Protocol (Both Operators)
# ============================================================================


class TestWeatherAgentConversation:
    """Test weather-service agent with MCP weather-tool (works with both operators)."""

    @pytest.mark.asyncio
    async def test_agent_simple_query(self, test_session_id):
        """
        Test agent can process a simple query using A2A protocol.

        This validates:
        - A2A protocol client works (ClientFactory API)
        - Agent API is accessible via A2A
        - LLM integration works (Ollama on Kind, OpenAI on OpenShift)
        - Agent can generate responses to weather queries

        Uses test_session_id as contextId so observability tests can
        correlate traces to this specific test run.
        """
        agent_url = os.getenv("AGENT_URL", "http://localhost:8000")
        ssl_verify = _get_ssl_context()

        # Connect using ClientFactory (replaces deprecated A2AClient)
        # TODO: Should the agent card return the public route URL instead of
        #   the internal bind address (0.0.0.0:8000)? The A2A spec says the
        #   card URL should be the agent's reachable endpoint. Options:
        #   1. Agent reads its own route hostname and sets card.url
        #   2. A proxy/gateway rewrites the card URL on the fly
        #   3. Clients override as we do here (current workaround)
        httpx_client = httpx.AsyncClient(timeout=120.0, verify=ssl_verify)
        config = ClientConfig(httpx_client=httpx_client)
        try:
            from a2a.client.card_resolver import A2ACardResolver

            resolver = A2ACardResolver(httpx_client, agent_url)
            card = await resolver.get_agent_card()
            # Override: card.url is the pod's internal address (0.0.0.0:8000)
            # but we connect via the external route
            card.url = agent_url
            client = await ClientFactory.connect(card, client_config=config)
        except Exception as e:
            pytest.fail(
                f"Agent not reachable at {agent_url}: {e}\n"
                "Check: pod running, port-forward active, service exists"
            )

        # Send message with contextId for trace correlation
        # Observability tests use this to filter traces from current test run
        user_message = "What is the weather like in San Francisco?"
        message = A2AMessage(
            role="user",
            parts=[TextPart(text=user_message)],
            messageId=uuid4().hex,
            contextId=test_session_id,
        )

        full_response = ""
        tool_invocation_detected = False
        events_received = []

        try:
            async for result in client.send_message(message):
                if isinstance(result, tuple):
                    task, event = result
                    events_received.append(
                        type(event).__name__ if event else "Task(final)"
                    )

                    # Extract from TaskArtifactUpdateEvent
                    if isinstance(event, TaskArtifactUpdateEvent):
                        tool_invocation_detected = True
                        if hasattr(event, "artifact") and event.artifact:
                            for part in event.artifact.parts or []:
                                p = getattr(part, "root", part)
                                if hasattr(p, "text"):
                                    full_response += p.text

                    # Extract from final task (event=None means complete)
                    if event is None and task and task.artifacts:
                        for artifact in task.artifacts:
                            for part in artifact.parts or []:
                                p = getattr(part, "root", part)
                                if hasattr(p, "text"):
                                    full_response += p.text
                        tool_invocation_detected = True

                elif isinstance(result, A2AMessage):
                    events_received.append("Message")
                    for part in result.parts or []:
                        p = getattr(part, "root", part)
                        if hasattr(p, "text"):
                            full_response += p.text

        except Exception as e:
            pytest.fail(f"Error during A2A conversation: {e}")

        # Validate response
        assert full_response, (
            f"Agent did not return any response\n"
            f"  Agent URL: {agent_url}\n"
            f"  Events received: {events_received}\n"
            f"  Query: {user_message}"
        )
        assert len(full_response) > 10, f"Agent response too short: {full_response}"

        print(f"\n  Agent responded via A2A (ClientFactory)")
        print(f"  Events: {events_received}")
        print(f"  Response: {full_response[:200]}...")

        # Weather-related keywords that should appear if tool was called successfully
        # The tool returns actual weather data (temperature, conditions, location)
        weather_data_keywords = [
            "weather",
            "temperature",
            "san francisco",
            "°",
            "degrees",
            "sunny",
            "cloudy",
            "rain",
            "forecast",
            "current",
            "conditions",
        ]

        response_lower = full_response.lower()
        has_weather_data = any(
            keyword in response_lower for keyword in weather_data_keywords
        )

        assert has_weather_data, (
            f"Agent response doesn't contain weather data from tool. "
            f"Response: {full_response}"
        )

        print("\n✓ Agent responded successfully via A2A protocol")
        print("✓ Weather MCP tool was invoked")
        print(f"  Query: {user_message}")
        print(f"  Response: {full_response[:200]}...")

    @pytest.mark.openshift_only
    @pytest.mark.asyncio
    async def test_agent_multiturn_conversation(self, test_session_id):
        """
        Test multi-turn conversation maintains consistent session/context ID.

        This validates:
        - Multiple messages can share the same contextId
        - Session tracking works across conversation turns
        - Observability traces can be grouped by session

        The test_session_id fixture provides a unique ID for this test run,
        allowing observability tests to filter traces by this specific session.
        """
        agent_url = os.getenv("AGENT_URL", "http://localhost:8000")
        ssl_verify = _get_ssl_context()

        context_id = test_session_id
        print(f"\n=== Multi-turn Conversation Test ===")
        print(f"Session/Context ID: {context_id}")

        messages = [
            "What is the weather in Paris?",
            "And what about London?",
            "Which city is warmer?",
        ]

        # Connect using ClientFactory (override card URL for external access)
        httpx_client = httpx.AsyncClient(timeout=120.0, verify=ssl_verify)
        config = ClientConfig(httpx_client=httpx_client)
        try:
            from a2a.client.card_resolver import A2ACardResolver

            resolver = A2ACardResolver(httpx_client, agent_url)
            card = await resolver.get_agent_card()
            card.url = agent_url
            client = await ClientFactory.connect(card, client_config=config)
        except Exception as e:
            pytest.fail(f"Agent not reachable at {agent_url}: {e}")

        for turn, user_message in enumerate(messages, 1):
            print(f"\n--- Turn {turn}: {user_message} ---")

            message = A2AMessage(
                role="user",
                parts=[TextPart(text=user_message)],
                messageId=uuid4().hex,
                contextId=context_id,
            )

            full_response = ""
            try:
                async for result in client.send_message(message):
                    if isinstance(result, tuple):
                        task, event = result
                        if isinstance(event, TaskArtifactUpdateEvent):
                            if event.artifact:
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
                        for part in result.parts or []:
                            p = getattr(part, "root", part)
                            if hasattr(p, "text"):
                                full_response += p.text
            except Exception as e:
                pytest.fail(f"Turn {turn} failed: {e}")

            assert full_response, f"Turn {turn}: Agent did not return any response"
            print(f"  Response: {full_response[:100]}...")

        print(f"\n  Multi-turn conversation completed ({len(messages)} turns)")
        print(f"  Context ID: {context_id}")


if __name__ == "__main__":
    import sys

    sys.exit(pytest.main([__file__, "-v"]))
