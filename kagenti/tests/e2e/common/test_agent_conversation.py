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
from a2a.client import A2AClient
from a2a.types import (
    Task,
    Message as A2AMessage,
    TaskStatusUpdateEvent,
    TaskArtifactUpdateEvent,
    MessageSendParams,
    SendStreamingMessageRequest,
    SendStreamingMessageSuccessResponse,
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


def _get_ssl_verify():
    """
    Get the SSL verification setting for httpx client.

    On OpenShift: Uses the ingress CA certificate if available, otherwise False
    On Kind: True (standard SSL verification)
    """
    if not _is_openshift_from_config():
        return True

    # Check environment variable first (allows override)
    ca_path = os.getenv("OPENSHIFT_INGRESS_CA")
    if ca_path and pathlib.Path(ca_path).exists():
        return ca_path

    # Try to fetch from cluster
    ca_file = _fetch_openshift_ingress_ca()
    if ca_file:
        return ca_file

    # Fallback: disable SSL verification
    return False


# ============================================================================
# Test: Weather Agent Conversation via A2A Protocol (Both Operators)
# ============================================================================


class TestWeatherAgentConversation:
    """Test weather-service agent with MCP weather-tool (works with both operators)."""

    @pytest.mark.asyncio
    async def test_agent_simple_query(self):
        """
        Test agent can process a simple query using A2A protocol and Ollama.

        This validates:
        - A2A protocol client works
        - Agent API is accessible via A2A
        - Ollama LLM integration works
        - Agent can generate responses to weather queries
        """
        # Use environment variable or default to localhost (for CI with port-forward)
        # Set AGENT_URL=http://weather-service.team1.svc.cluster.local:8000 for in-cluster tests
        agent_url = os.getenv("AGENT_URL", "http://localhost:8000")

        # Get SSL verification setting (uses OpenShift CA cert if available)
        ssl_verify = _get_ssl_verify()
        # Ollama on Kind CI with small models (qwen2.5:0.5b) can be slow
        async with httpx.AsyncClient(timeout=120.0, verify=ssl_verify) as httpx_client:
            # Pre-flight: verify agent is reachable
            try:
                card_resp = await httpx_client.get(
                    f"{agent_url}/.well-known/agent-card.json", timeout=10.0
                )
                print(f"\n  Agent card: HTTP {card_resp.status_code}")
                if card_resp.status_code == 200:
                    card = card_resp.json()
                    print(f"  Agent name: {card.get('name', '?')}")
                else:
                    print(f"  Agent card response: {card_resp.text[:200]}")
            except Exception as e:
                pytest.fail(
                    f"Agent not reachable at {agent_url}: {e}\n"
                    "Check: pod running, port-forward active, service exists"
                )

            # Initialize A2A client
            client = A2AClient(httpx_client=httpx_client, url=agent_url)

            # Create message payload
            user_message = "What is the weather like in San Francisco?"
            send_message_payload = {
                "message": {
                    "role": "user",
                    "parts": [{"kind": "text", "text": user_message}],
                    "messageId": uuid4().hex,
                },
            }

            # Create streaming request
            streaming_request = SendStreamingMessageRequest(
                id=str(uuid4()), params=MessageSendParams(**send_message_payload)
            )

            # Send message and collect response
            full_response = ""
            final_event_received = False
            tool_invocation_detected = False
            events_received = []

            try:
                stream_response_iterator = client.send_message_streaming(
                    streaming_request
                )

                async for chunk in stream_response_iterator:
                    if isinstance(chunk.root, SendStreamingMessageSuccessResponse):
                        event = chunk.root.result
                        events_received.append(type(event).__name__)

                        # Handle Task events
                        if isinstance(event, Task):
                            if event.status and event.status.state in [
                                "COMPLETED",
                                "FAILED",
                            ]:
                                final_event_received = True
                                if event.status.message and hasattr(
                                    event.status.message, "parts"
                                ):
                                    for part in event.status.message.parts:
                                        p = getattr(part, "root", part)
                                        if hasattr(p, "text"):
                                            full_response += p.text

                        # Handle TaskStatusUpdateEvent
                        elif isinstance(event, TaskStatusUpdateEvent):
                            state = getattr(event.status, "state", "?")
                            events_received[-1] += f"({state})"
                            if event.final:
                                final_event_received = True
                                if event.status.message and event.status.message.parts:
                                    for part in event.status.message.parts:
                                        p = getattr(part, "root", part)
                                        if hasattr(p, "text"):
                                            full_response += p.text

                        # Handle TaskArtifactUpdateEvent (indicates tool was called)
                        elif isinstance(event, TaskArtifactUpdateEvent):
                            tool_invocation_detected = True
                            print(
                                f"\n✓ Tool invocation detected (Artifact ID: {getattr(getattr(event, 'artifact', None), 'artifactId', '?')})"
                            )
                            # Extract tool response data
                            if hasattr(event, "artifact") and hasattr(
                                event.artifact, "parts"
                            ):
                                for part in event.artifact.parts or []:
                                    p = getattr(part, "root", part)
                                    if hasattr(p, "text"):
                                        full_response += p.text
                                    elif hasattr(p, "data"):
                                        # Tool might return data in data field
                                        full_response += str(p.data)

                        # Handle Message events
                        elif isinstance(event, A2AMessage):
                            if hasattr(event, "parts"):
                                for part in event.parts:
                                    p = getattr(part, "root", part)
                                    if hasattr(p, "text"):
                                        full_response += p.text

                    # Break if we got a final event
                    if final_event_received:
                        break

            except httpx.HTTPStatusError as e:
                pytest.fail(
                    f"A2A HTTP error: {e.response.status_code} - {e.response.text}"
                )
            except httpx.RequestError as e:
                pytest.fail(f"A2A network error: {e}")
            except Exception as e:
                pytest.fail(f"Unexpected error during A2A conversation: {e}")

        # Validate we got a response
        assert full_response, (
            f"Agent did not return any response\n"
            f"  Agent URL: {agent_url}\n"
            f"  Events received: {events_received}\n"
            f"  Final event: {final_event_received}\n"
            f"  Tool invoked: {tool_invocation_detected}\n"
            f"  Query: {user_message}"
        )
        assert len(full_response) > 10, f"Agent response too short: {full_response}"

        # Validate tool was invoked (critical for MCP integration test)
        assert tool_invocation_detected, (
            "Weather MCP tool was not invoked by the agent. "
            "Agent should call the weather-tool to get weather data."
        )

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
        ssl_verify = _get_ssl_verify()

        # Use the shared test session ID for trace correlation
        context_id = test_session_id
        print(f"\n=== Multi-turn Conversation Test ===")
        print(f"Session/Context ID: {context_id} (shared with observability tests)")

        messages = [
            "What is the weather in Paris?",
            "And what about London?",
            "Which city is warmer?",
        ]

        # Ollama on Kind CI with small models (qwen2.5:0.5b) can be slow
        async with httpx.AsyncClient(timeout=120.0, verify=ssl_verify) as httpx_client:
            client = A2AClient(httpx_client=httpx_client, url=agent_url)

            for turn, user_message in enumerate(messages, 1):
                print(f"\n--- Turn {turn}: {user_message} ---")

                send_message_payload = {
                    "message": {
                        "role": "user",
                        "parts": [{"kind": "text", "text": user_message}],
                        "messageId": uuid4().hex,
                        "contextId": context_id,
                    },
                    "contextId": context_id,
                }

                streaming_request = SendStreamingMessageRequest(
                    id=str(uuid4()), params=MessageSendParams(**send_message_payload)
                )

                full_response = ""
                final_event_received = False

                try:
                    stream_response_iterator = client.send_message_streaming(
                        streaming_request
                    )

                    async for chunk in stream_response_iterator:
                        if isinstance(chunk.root, SendStreamingMessageSuccessResponse):
                            event = chunk.root.result

                            if isinstance(event, Task):
                                if event.status and event.status.state in [
                                    "COMPLETED",
                                    "FAILED",
                                ]:
                                    final_event_received = True

                            elif isinstance(event, TaskStatusUpdateEvent):
                                if event.final:
                                    final_event_received = True

                            elif isinstance(event, TaskArtifactUpdateEvent):
                                if hasattr(event, "artifact") and hasattr(
                                    event.artifact, "parts"
                                ):
                                    for part in event.artifact.parts or []:
                                        p = getattr(part, "root", part)
                                        if hasattr(p, "text"):
                                            full_response += p.text

                        if final_event_received:
                            break

                except Exception as e:
                    pytest.fail(f"Turn {turn} failed: {e}")

                assert full_response, f"Turn {turn}: Agent did not return any response"
                print(f"  Response: {full_response[:100]}...")

        print(f"\n✓ Multi-turn conversation completed successfully")
        print(f"✓ All {len(messages)} turns used context ID: {context_id}")
        print("✓ Check observability (MLflow/Phoenix) for session grouping")


if __name__ == "__main__":
    import sys

    sys.exit(pytest.main([__file__, "-v"]))
