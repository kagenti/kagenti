#!/usr/bin/env python3
"""
Phoenix Interactive E2E Tests

Interactive tests for Phoenix observability that verify:
1. Agent conversations create traces in Phoenix
2. Phoenix UI is accessible and functional
3. Traces can be queried and viewed in Phoenix UI
4. Users can chat with agents and see traces in real-time

These tests are designed for manual verification and require Phoenix to be deployed.

Usage:
    # Run interactive Phoenix tests
    pytest kagenti/tests/e2e/common/test_phoenix_interactive.py -v -s

    # Run specific test
    pytest kagenti/tests/e2e/common/test_phoenix_interactive.py::TestPhoenixInteractive::test_chat_and_verify_phoenix_ui -v -s

Requirements:
    - Phoenix feature flag enabled in config
    - Weather agent deployed with Phoenix instrumentation
    - Phoenix UI accessible (port-forward or HTTPRoute)

Environment Variables:
    AGENT_URL: Weather agent endpoint (default: http://localhost:8000)
    PHOENIX_URL: Phoenix endpoint (default: http://localhost:6006)
"""

import os
import time
import logging
from typing import Dict, Any, Optional
from uuid import uuid4

import pytest
import httpx
from a2a.client import A2AClient
from a2a.types import MessageSendParams, SendStreamingMessageRequest

logger = logging.getLogger(__name__)


# ============================================================================
# Test Markers
# ============================================================================

pytestmark = pytest.mark.requires_features(["otel"])


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture(scope="module")
def phoenix_url():
    """Phoenix endpoint."""
    url = os.getenv("PHOENIX_URL", "http://localhost:6006")
    logger.info(f"Phoenix URL: {url}")
    return url


@pytest.fixture(scope="module")
def agent_url():
    """Weather agent endpoint."""
    url = os.getenv("AGENT_URL", "http://localhost:8000")
    logger.info(f"Agent URL: {url}")
    return url


# ============================================================================
# Helper Functions
# ============================================================================


async def send_chat_message(
    agent_url: str,
    message: str,
    user_id: str = "test-user",
    request_id: Optional[str] = None,
    timeout: int = 60,
) -> Dict[str, Any]:
    """
    Send chat message to agent via A2A protocol.

    Returns dict with request_id, user_id, and responses.
    """
    request_id = request_id or f"req-{uuid4()}"
    conversation_id = f"conv-{uuid4()}"

    async with httpx.AsyncClient(timeout=float(timeout)) as httpx_client:
        client = A2AClient(httpx_client=httpx_client, url=agent_url)

        # Create message payload matching A2A protocol format
        send_message_payload = {
            "message": {
                "role": "user",
                "parts": [{"kind": "text", "text": message}],
                "messageId": uuid4().hex,
            },
        }

        request_params = SendStreamingMessageRequest(
            id=str(uuid4()),
            params=MessageSendParams(**send_message_payload),
        )

        responses = []
        async for response in client.send_message_streaming(request_params):
            responses.append(response)

        return {
            "request_id": request_id,
            "conversation_id": conversation_id,
            "user_id": user_id,
            "message": message,
            "responses": responses,
        }


async def query_phoenix_for_traces(
    phoenix_url: str, request_id: str, max_retries: int = 5, retry_delay: int = 5
) -> Dict[str, Any]:
    """
    Query Phoenix GraphQL API for traces by request_id.

    Retries to account for OTEL batch export delay.
    """
    query = """
    query GetTracesByRequestId($requestId: String!) {
      spans(filter: {attribute: {key: "request.id", value: $requestId}}, first: 50) {
        edges {
          node {
            name
            context {
              traceId
              spanId
            }
            attributes
          }
        }
      }
    }
    """

    graphql_url = f"{phoenix_url}/graphql"

    for attempt in range(max_retries):
        async with httpx.AsyncClient() as client:
            response = await client.post(
                graphql_url,
                json={"query": query, "variables": {"requestId": request_id}},
                timeout=15,
            )
            response.raise_for_status()
            data = response.json()

            # Handle null responses safely
            response_data = data.get("data") or {}
            spans_data = response_data.get("spans") or {}
            spans = spans_data.get("edges", [])
            if len(spans) > 0:
                return data

            # No spans yet, wait and retry
            if attempt < max_retries - 1:
                logger.info(
                    f"No traces yet, retrying in {retry_delay}s ({attempt+1}/{max_retries})..."
                )
                time.sleep(retry_delay)

    return {"data": {"spans": {"edges": []}}}


def print_trace_summary(spans: list, request_id: str, user_id: str):
    """Pretty print trace summary."""
    print("\n" + "=" * 80)
    print("🔥 PHOENIX TRACE SUMMARY")
    print("=" * 80)
    print(f"Request ID:  {request_id}")
    print(f"User ID:     {user_id}")
    print(f"Total Spans: {len(spans)}")
    print("-" * 80)

    for i, span_edge in enumerate(spans, 1):
        span = span_edge["node"]
        span_name = span["name"]
        attrs = span["attributes"]
        span_kind = attrs.get("openinference.span.kind", "UNKNOWN")

        print(f"\nSpan {i}: {span_name}")
        print(f"  Kind:     {span_kind}")
        print(f"  Trace ID: {span['context']['traceId']}")

        # Show key attributes
        if "llm.model_name" in attrs:
            print(f"  Model:    {attrs['llm.model_name']}")
        if "llm.token_count.prompt" in attrs:
            print(
                f"  Tokens:   {attrs['llm.token_count.prompt']} prompt, "
                f"{attrs.get('llm.token_count.completion', 0)} completion"
            )

    print("\n" + "=" * 80)


# ============================================================================
# Test Class: Phoenix Interactive Tests
# ============================================================================


@pytest.mark.skip(
    reason="Interactive tests - require manual verification, not suited for CI"
)
class TestPhoenixInteractive:
    """Interactive tests for Phoenix observability."""

    @pytest.mark.asyncio
    async def test_chat_and_verify_phoenix_ui(self, agent_url, phoenix_url):
        """
        🔥 INTERACTIVE TEST: Chat with agent and verify traces in Phoenix UI.

        This test:
        1. Sends chat message to weather agent
        2. Waits for OTEL export
        3. Queries Phoenix for traces
        4. Prints trace summary
        5. Provides Phoenix UI URL for manual verification

        Manual Steps:
        1. Run this test
        2. Open Phoenix UI in browser
        3. Navigate to Traces tab
        4. Search for the request_id shown in output
        5. Verify trace visualization

        This test requires Phoenix feature flag to be enabled.
        """
        print("\n" + "=" * 80)
        print("🧪 INTERACTIVE PHOENIX TEST")
        print("=" * 80)
        print("\nThis test will:")
        print("  1. Send a chat message to the weather agent")
        print("  2. Query Phoenix for the resulting trace")
        print("  3. Display trace summary")
        print("  4. Guide you to verify in Phoenix UI")
        print("\n" + "-" * 80)

        # Step 1: Send chat message
        user_id = "interactive-test-user"
        request_id = f"interactive-{uuid4()}"

        print(f"\n📤 Sending chat message to agent...")
        print(f"   Request ID: {request_id}")
        print(f"   User ID:    {user_id}")

        chat_response = await send_chat_message(
            agent_url=agent_url,
            message="What is the weather in San Francisco?",
            user_id=user_id,
            request_id=request_id,
            timeout=60,
        )

        print(f"\n✅ Agent responded with {len(chat_response['responses'])} events")

        # Print agent response
        for i, resp in enumerate(chat_response["responses"], 1):
            print(f"\n   Event {i}:")
            print(f"   {resp}")

        # Step 2: Wait for OTEL export
        print(f"\n⏳ Waiting 10 seconds for OTEL batch export...")
        time.sleep(10)

        # Step 3: Query Phoenix
        print(f"\n🔍 Querying Phoenix for traces...")

        phoenix_response = await query_phoenix_for_traces(
            phoenix_url=phoenix_url, request_id=request_id, max_retries=5, retry_delay=5
        )

        spans = phoenix_response.get("data", {}).get("spans", {}).get("edges", [])

        # Step 4: Verify traces exist
        assert len(spans) > 0, (
            f"\n❌ No traces found in Phoenix for request_id={request_id}\n"
            f"\n"
            f"Troubleshooting:\n"
            f"  1. Check agent logs:\n"
            f"     kubectl logs -n team1 -l app=weather-service --tail=50\n"
            f"\n"
            f"  2. Check OTEL Collector logs:\n"
            f"     kubectl logs -n observability -l app=otel-collector --tail=50\n"
            f"\n"
            f"  3. Check Phoenix logs:\n"
            f"     kubectl logs -n observability -l app=phoenix --tail=50\n"
            f"\n"
            f"  4. Verify Phoenix is accessible:\n"
            f"     curl {phoenix_url}/graphql\n"
        )

        # Step 5: Print trace summary
        print_trace_summary(spans, request_id, user_id)

        # Step 6: Guide user to Phoenix UI
        print("\n" + "=" * 80)
        print("🎉 SUCCESS! Traces found in Phoenix")
        print("=" * 80)
        print("\n📊 To view traces in Phoenix UI:")
        print(f"\n  1. Open Phoenix UI: {phoenix_url}")
        print(f"\n  2. Navigate to 'Traces' tab")
        print(f"\n  3. Search for request ID: {request_id}")
        print(f"\n  4. Click on the trace to see full visualization")
        print(f"\n  5. Verify you can see:")
        print(f"     - Agent execution spans")
        print(f"     - LLM call spans with prompts/responses")
        print(f"     - Tool call spans (if any)")
        print(f"     - Baggage attributes (user_id, request_id)")
        print("\n" + "=" * 80)

        # Get trace ID for easier lookup
        if spans:
            trace_id = spans[0]["node"]["context"]["traceId"]
            print(f"\n💡 Direct link to trace (if supported):")
            print(f"   {phoenix_url}/traces/{trace_id}")

        print("\n" + "=" * 80)

    @pytest.mark.asyncio
    async def test_multiple_conversations_create_separate_traces(
        self, agent_url, phoenix_url
    ):
        """
        Test that multiple conversations create separate traces.

        This verifies that each request gets its own trace ID.
        """
        print("\n" + "=" * 80)
        print("🧪 Testing Multiple Conversations")
        print("=" * 80)

        conversations = [
            "What is the weather in New York?",
            "What is the weather in London?",
            "What is the weather in Tokyo?",
        ]

        request_ids = []
        trace_ids = []

        for i, message in enumerate(conversations, 1):
            request_id = f"multi-conv-{i}-{uuid4()}"
            request_ids.append(request_id)

            print(f"\n📤 Conversation {i}/3: '{message}'")
            print(f"   Request ID: {request_id}")

            # Send message
            chat_response = await send_chat_message(
                agent_url=agent_url,
                message=message,
                user_id="multi-test-user",
                request_id=request_id,
                timeout=60,
            )

            print(f"   ✅ Response received")

        # Wait for all traces
        print(f"\n⏳ Waiting for OTEL export...")
        time.sleep(15)

        # Query Phoenix for each conversation
        print(f"\n🔍 Querying Phoenix for all traces...")
        for i, request_id in enumerate(request_ids, 1):
            response = await query_phoenix_for_traces(
                phoenix_url=phoenix_url,
                request_id=request_id,
                max_retries=3,
                retry_delay=5,
            )

            spans = response.get("data", {}).get("spans", {}).get("edges", [])

            assert (
                len(spans) > 0
            ), f"No traces for conversation {i} (request_id={request_id})"

            # Get trace ID
            trace_id = spans[0]["node"]["context"]["traceId"]
            trace_ids.append(trace_id)

            print(f"   ✅ Conversation {i}: {len(spans)} spans, trace_id={trace_id}")

        # Verify all traces are unique
        unique_trace_ids = set(trace_ids)
        assert len(unique_trace_ids) == len(
            conversations
        ), f"Expected {len(conversations)} unique traces, got {len(unique_trace_ids)}"

        print("\n" + "=" * 80)
        print("✅ SUCCESS! Each conversation has its own trace")
        print("=" * 80)
        print(f"\nUnique traces: {len(unique_trace_ids)}")
        for i, trace_id in enumerate(trace_ids, 1):
            print(f"  {i}. {trace_id}")
        print("\n" + "=" * 80)

    @pytest.mark.asyncio
    async def test_phoenix_ui_accessibility(self, phoenix_url):
        """
        Test that Phoenix UI is accessible and functional.

        Verifies:
        - Phoenix UI returns 200 OK
        - Phoenix GraphQL API is accessible
        """
        print("\n" + "=" * 80)
        print("🧪 Testing Phoenix UI Accessibility")
        print("=" * 80)

        async with httpx.AsyncClient() as client:
            # Test UI endpoint
            print(f"\n📡 Testing Phoenix UI: {phoenix_url}")
            ui_response = await client.get(
                phoenix_url, timeout=10, follow_redirects=True
            )
            assert (
                ui_response.status_code == 200
            ), f"Phoenix UI returned {ui_response.status_code}"
            print(f"   ✅ Phoenix UI accessible (status {ui_response.status_code})")

            # Test GraphQL API
            print(f"\n📡 Testing Phoenix GraphQL API: {phoenix_url}/graphql")
            query = """
            query {
              __schema {
                queryType {
                  name
                }
              }
            }
            """

            graphql_response = await client.post(
                f"{phoenix_url}/graphql", json={"query": query}, timeout=10
            )
            assert graphql_response.status_code == 200
            data = graphql_response.json()
            assert "data" in data
            assert "__schema" in data["data"]
            print(f"   ✅ Phoenix GraphQL API accessible")

        print("\n" + "=" * 80)
        print("✅ Phoenix UI is fully accessible")
        print("=" * 80)
        print(f"\n🌐 Open Phoenix UI in your browser:")
        print(f"   {phoenix_url}")
        print("\n" + "=" * 80)
