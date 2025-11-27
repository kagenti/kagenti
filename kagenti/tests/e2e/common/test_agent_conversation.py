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
import pytest
import httpx
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

        async with httpx.AsyncClient(timeout=60.0) as httpx_client:
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

            try:
                stream_response_iterator = client.send_message_streaming(
                    streaming_request
                )

                async for chunk in stream_response_iterator:
                    if isinstance(chunk.root, SendStreamingMessageSuccessResponse):
                        event = chunk.root.result

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
        assert full_response, "Agent did not return any response"
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


if __name__ == "__main__":
    import sys

    sys.exit(pytest.main([__file__, "-v"]))
