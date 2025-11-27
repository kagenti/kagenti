#!/usr/bin/env python3
"""
Phoenix Integration E2E Tests

Comprehensive tests for Phoenix observability integration with OpenInference
auto-instrumentation and OTEL baggage propagation.

Tests verify:
1. Agent auto-instrumentation with OpenInference
2. Trace routing to Phoenix backend
3. OTEL baggage propagation across services
4. GenAI semantic conventions compliance
5. Multi-namespace project routing
6. Phoenix backend configuration

Usage:
    # Run all Phoenix tests
    pytest kagenti/tests/e2e/common/test_phoenix_integration.py -v

    # Run specific test
    pytest kagenti/tests/e2e/common/test_phoenix_integration.py::TestPhoenixAgentInstrumentation::test_agent_conversation_creates_traces -v

Environment Variables:
    AGENT_URL: Weather agent endpoint (default: http://localhost:8000)
    PHOENIX_URL: Phoenix endpoint (default: http://localhost:6006)
    KAGENTI_CONFIG_FILE: Path to Kagenti config YAML
"""

import os
import time
import uuid
import logging
from typing import Dict, Any, List, Optional

import pytest
import httpx
from kubernetes import client, config
from a2a.client import A2AClient
from a2a.types import MessageSendParams, SendStreamingMessageRequest

logger = logging.getLogger(__name__)


# ============================================================================
# Test Configuration & Fixtures
# ============================================================================


@pytest.fixture(scope="module")
def k8s_api():
    """Load Kubernetes client for cluster introspection."""
    try:
        config.load_kube_config()
        return client.CoreV1Api()
    except Exception as e:
        logger.warning(f"Failed to load kubeconfig: {e}")
        return None


@pytest.fixture(scope="module")
def phoenix_url():
    """Phoenix GraphQL API endpoint."""
    return os.getenv(
        "PHOENIX_URL", "http://phoenix.observability.svc.cluster.local:6006"
    )


@pytest.fixture(scope="module")
def agent_url():
    """Weather agent endpoint."""
    return os.getenv("AGENT_URL", "http://weather-service.team1.svc.cluster.local:8000")


@pytest.fixture(scope="module")
def test_namespace():
    """Namespace where test agents are deployed."""
    return "team1"


# ============================================================================
# Helper Functions
# ============================================================================


async def query_phoenix_graphql(
    phoenix_url: str,
    query: str,
    variables: Optional[Dict[str, Any]] = None,
    timeout: int = 10,
) -> Dict[str, Any]:
    """
    Query Phoenix GraphQL API.

    Args:
        phoenix_url: Phoenix base URL
        query: GraphQL query string
        variables: Query variables
        timeout: Request timeout in seconds

    Returns:
        GraphQL response data

    Raises:
        httpx.HTTPError: On request failure
    """
    graphql_url = f"{phoenix_url}/graphql"

    async with httpx.AsyncClient() as client:
        response = await client.post(
            graphql_url,
            json={"query": query, "variables": variables or {}},
            timeout=timeout,
        )
        response.raise_for_status()
        return response.json()


async def send_agent_request(
    agent_url: str,
    message: str,
    user_id: str = "test-user",
    request_id: Optional[str] = None,
    conversation_id: Optional[str] = None,
    timeout: int = 30,
) -> Dict[str, Any]:
    """
    Send request to weather agent via A2A protocol.

    Args:
        agent_url: Agent base URL
        message: User message
        user_id: User identifier (for baggage)
        request_id: Request identifier (for baggage)
        conversation_id: Conversation identifier (for baggage)
        timeout: Request timeout in seconds

    Returns:
        Agent response data
    """
    request_id = request_id or f"req-{uuid.uuid4()}"
    conversation_id = conversation_id or f"conv-{uuid.uuid4()}"

    # Create A2A client
    client = A2AClient(base_url=agent_url)

    # Prepare message with baggage headers
    # Note: A2A SDK may not directly support custom headers
    # We'll rely on the agent extracting from A2A message context
    request_params = SendStreamingMessageRequest(
        params=MessageSendParams(
            message=message,
            context_id=conversation_id,
        )
    )

    # Send streaming message
    responses = []
    async for response in client.send_streaming_message(request_params):
        responses.append(response)

    return {
        "request_id": request_id,
        "conversation_id": conversation_id,
        "user_id": user_id,
        "responses": responses,
    }


def wait_for_traces(seconds: int = 5):
    """
    Wait for OTEL batch export to complete.

    OTEL uses batch span processors which export spans periodically.
    This ensures traces have time to reach Phoenix.
    """
    logger.info(f"Waiting {seconds}s for OTEL batch export...")
    time.sleep(seconds)


# ============================================================================
# Test Class: Phoenix Agent Instrumentation
# ============================================================================


class TestPhoenixAgentInstrumentation:
    """Test agent instrumentation and trace collection in Phoenix."""

    @pytest.mark.asyncio
    async def test_pods_are_running(self, k8s_api, test_namespace):
        """
        Test that weather agent and tool pods are running.

        This is a prerequisite for all other tests.
        """
        if not k8s_api:
            pytest.skip("Kubernetes client not available")

        pods = k8s_api.list_namespaced_pod(namespace=test_namespace)

        agent_pod = None
        tool_pod = None

        for pod in pods.items:
            if "weather-service" in pod.metadata.name:
                agent_pod = pod
            if "weather-tool" in pod.metadata.name:
                tool_pod = pod

        assert agent_pod is not None, "Weather agent pod not found in team1 namespace"
        assert (
            agent_pod.status.phase == "Running"
        ), f"Weather agent pod not running: {agent_pod.status.phase}"

        # Tool pod is optional (may be in same pod or separate)
        if tool_pod:
            assert (
                tool_pod.status.phase == "Running"
            ), f"Weather tool pod not running: {tool_pod.status.phase}"

        logger.info(f"✅ Agent pod running: {agent_pod.metadata.name}")
        if tool_pod:
            logger.info(f"✅ Tool pod running: {tool_pod.metadata.name}")

    @pytest.mark.asyncio
    async def test_agent_conversation_creates_traces(self, agent_url, phoenix_url):
        """
        🔥 PRIMARY E2E TEST: Agent conversation creates traces in Phoenix.

        This test verifies the complete trace flow:
        1. Send request to agent with unique request_id
        2. Agent processes request (LLM call, potential tool call)
        3. OpenInference instrumentation creates spans
        4. Spans flow to OTEL Collector
        5. OTEL Collector routes to Phoenix (has openinference.span.kind)
        6. Phoenix stores traces
        7. We query Phoenix and find our trace

        Expected spans:
        - Agent execution span (openinference.span.kind=AGENT or CHAIN)
        - LLM call span (openinference.span.kind=LLM)
        - Tool call span (openinference.span.kind=TOOL) - if agent uses tool

        Expected baggage attributes in ALL spans:
        - request_id (set by us)
        - user_id (set by us)
        - task_id (from A2A SDK)
        - context_id (from A2A SDK)
        """
        # Step 1: Send request to agent
        user_id = "alice"
        request_id = f"test-phoenix-{uuid.uuid4()}"
        conversation_id = f"conv-{uuid.uuid4()}"

        logger.info("=" * 70)
        logger.info("🧪 Testing: Agent Conversation Creates Traces in Phoenix")
        logger.info("-" * 70)
        logger.info(f"Request ID:      {request_id}")
        logger.info(f"User ID:         {user_id}")
        logger.info(f"Conversation ID: {conversation_id}")
        logger.info(f"Agent URL:       {agent_url}")
        logger.info(f"Phoenix URL:     {phoenix_url}")
        logger.info("=" * 70)

        response = await send_agent_request(
            agent_url=agent_url,
            message="What is the weather in San Francisco?",
            user_id=user_id,
            request_id=request_id,
            conversation_id=conversation_id,
            timeout=60,  # LLM calls can be slow
        )

        logger.info(f"✅ Agent responded with {len(response['responses'])} events")

        # Step 2: Wait for OTEL batch export
        wait_for_traces(seconds=10)  # Give extra time for Phoenix ingestion

        # Step 3: Query Phoenix for traces by request_id (baggage attribute)
        # NOTE: This assumes baggage processor converts baggage to span attributes
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
                startTime
                endTime
              }
            }
          }
        }
        """

        logger.info(f"🔍 Querying Phoenix for traces with request.id={request_id}")

        phoenix_response = await query_phoenix_graphql(
            phoenix_url=phoenix_url,
            query=query,
            variables={"requestId": request_id},
            timeout=15,
        )

        # Step 4: Assertions
        assert "data" in phoenix_response, f"Phoenix query failed: {phoenix_response}"
        assert "spans" in phoenix_response["data"], "No spans field in Phoenix response"

        spans = phoenix_response["data"]["spans"]["edges"]

        # PRIMARY ASSERTION: Traces exist in Phoenix
        assert len(spans) > 0, (
            f"❌ No traces found in Phoenix for request_id={request_id}. "
            f"This indicates:\n"
            f"  1. Agent is not instrumented, OR\n"
            f"  2. OTEL Collector is not receiving traces, OR\n"
            f"  3. Traces are not being routed to Phoenix, OR\n"
            f"  4. Baggage processor is not converting baggage to attributes\n"
            f"Phoenix response: {phoenix_response}"
        )

        logger.info(f"✅ Found {len(spans)} spans in Phoenix")

        # Extract span data
        span_nodes = [edge["node"] for edge in spans]
        span_names = [span["name"] for span in span_nodes]
        span_kinds = [
            span["attributes"].get("openinference.span.kind", "UNKNOWN")
            for span in span_nodes
        ]

        logger.info(f"📊 Span names: {span_names}")
        logger.info(f"📊 Span kinds: {span_kinds}")

        # Verify expected spans exist
        # We expect at least one LLM span
        llm_spans = [kind for kind in span_kinds if kind == "LLM"]
        assert len(llm_spans) > 0, (
            f"❌ No LLM spans found. Expected at least 1 LLM span.\n"
            f"Found span kinds: {span_kinds}\n"
            f"This indicates OpenInference LangChain instrumentation may not be working."
        )

        logger.info(f"✅ Found {len(llm_spans)} LLM spans")

        # Verify baggage attributes are present
        for i, span in enumerate(span_nodes):
            attrs = span["attributes"]
            span_name = span["name"]

            logger.info(f"\n📋 Span {i+1}/{len(span_nodes)}: {span_name}")
            logger.info(f"   Attributes: {list(attrs.keys())}")

            # Check for openinference.span.kind (required for Phoenix routing)
            assert "openinference.span.kind" in attrs, (
                f"❌ Span '{span_name}' missing openinference.span.kind attribute.\n"
                f"This attribute is REQUIRED for Phoenix routing."
            )

            # Check for baggage attributes (may be converted by baggage processor)
            # These might be under different keys depending on processor config
            baggage_keys = ["request.id", "request_id", "user.id", "user_id"]
            has_baggage = any(key in attrs for key in baggage_keys)

            if not has_baggage:
                logger.warning(
                    f"⚠️  Span '{span_name}' missing baggage attributes. "
                    f"Expected one of: {baggage_keys}. "
                    f"Found: {list(attrs.keys())}"
                )

        # Get unique trace IDs
        trace_ids = set(span["context"]["traceId"] for span in span_nodes)
        logger.info(f"✅ Traces span {len(trace_ids)} trace ID(s): {trace_ids}")

        # Ideally all spans belong to same trace
        if len(trace_ids) > 1:
            logger.warning(
                f"⚠️  Spans belong to {len(trace_ids)} different traces. "
                f"Expected all spans in same trace."
            )

        logger.info("=" * 70)
        logger.info("✅ TEST PASSED: Agent conversation creates traces in Phoenix!")
        logger.info("=" * 70)

    @pytest.mark.asyncio
    async def test_llm_span_has_genai_attributes(self, phoenix_url):
        """
        Test LLM spans have GenAI semantic convention attributes.

        Verifies compliance with OpenTelemetry GenAI semantic conventions:
        - gen_ai.request.model (or llm.model_name)
        - gen_ai.usage.input_tokens (or llm.token_count.prompt)
        - gen_ai.usage.output_tokens (or llm.token_count.completion)
        - openinference.span.kind = "LLM"

        Note: Token usage may not always be available for all LLM providers.
        """
        logger.info("🧪 Testing: LLM spans have GenAI semantic conventions")

        # Query for all LLM spans
        query = """
        query GetLLMSpans {
          spans(filter: {attribute: {key: "openinference.span.kind", value: "LLM"}}, first: 10) {
            edges {
              node {
                name
                attributes
                context {
                  traceId
                }
              }
            }
          }
        }
        """

        response = await query_phoenix_graphql(
            phoenix_url=phoenix_url, query=query, timeout=10
        )

        assert "data" in response, f"Phoenix query failed: {response}"
        spans = response["data"]["spans"]["edges"]

        if len(spans) == 0:
            pytest.skip(
                "No LLM spans found in Phoenix (run test_agent_conversation_creates_traces first)"
            )

        logger.info(f"✅ Found {len(spans)} LLM spans")

        # Check each LLM span for GenAI attributes
        for span_edge in spans:
            span = span_edge["node"]
            attrs = span["attributes"]
            span_name = span["name"]

            logger.info(f"\n📋 Checking LLM span: {span_name}")

            # OpenInference span kind (required)
            assert (
                attrs.get("openinference.span.kind") == "LLM"
            ), f"Span '{span_name}' has wrong span kind: {attrs.get('openinference.span.kind')}"

            # Model name (REQUIRED)
            model_name_keys = ["gen_ai.request.model", "llm.model_name", "llm.model"]
            model_name = None
            for key in model_name_keys:
                if key in attrs:
                    model_name = attrs[key]
                    logger.info(f"   ✅ Model name: {model_name} (from {key})")
                    break

            assert model_name is not None, (
                f"❌ LLM span '{span_name}' missing model name attribute.\n"
                f"Expected one of: {model_name_keys}\n"
                f"Found attributes: {list(attrs.keys())}"
            )

            # Token usage (RECOMMENDED, may not always be present)
            input_token_keys = ["gen_ai.usage.input_tokens", "llm.token_count.prompt"]
            output_token_keys = [
                "gen_ai.usage.output_tokens",
                "llm.token_count.completion",
            ]

            input_tokens = None
            output_tokens = None

            for key in input_token_keys:
                if key in attrs:
                    input_tokens = attrs[key]
                    logger.info(f"   ✅ Input tokens: {input_tokens} (from {key})")
                    break

            for key in output_token_keys:
                if key in attrs:
                    output_tokens = attrs[key]
                    logger.info(f"   ✅ Output tokens: {output_tokens} (from {key})")
                    break

            if input_tokens is None or output_tokens is None:
                logger.warning(
                    f"   ⚠️  Token usage not available for '{span_name}'. "
                    f"This is acceptable for some LLM providers."
                )

        logger.info("✅ TEST PASSED: LLM spans have GenAI attributes")

    @pytest.mark.asyncio
    async def test_baggage_propagates_across_services(self, agent_url, phoenix_url):
        """
        Test OTEL baggage propagates from agent to LLM to tool.

        Verifies that baggage context (user_id, request_id) is present in
        ALL spans of the trace, including nested tool calls and LLM calls.

        This is critical for:
        - Tracking requests across microservices
        - Correlating logs with traces
        - User attribution
        - Request debugging
        """
        logger.info("🧪 Testing: Baggage propagates across all services")

        # Send request with unique baggage
        user_id = "bob"
        request_id = f"test-baggage-{uuid.uuid4()}"

        response = await send_agent_request(
            agent_url=agent_url,
            message="What is the temperature in New York?",
            user_id=user_id,
            request_id=request_id,
            timeout=60,
        )

        logger.info(f"✅ Agent responded")

        # Wait for export
        wait_for_traces(seconds=10)

        # Query all spans for this trace by request_id
        query = """
        query GetTraceSpans($requestId: String!) {
          spans(filter: {attribute: {key: "request.id", value: $requestId}}, first: 50) {
            edges {
              node {
                name
                attributes
                context {
                  traceId
                  spanId
                }
              }
            }
          }
        }
        """

        phoenix_response = await query_phoenix_graphql(
            phoenix_url=phoenix_url,
            query=query,
            variables={"requestId": request_id},
            timeout=15,
        )

        assert "data" in phoenix_response
        spans = phoenix_response["data"]["spans"]["edges"]

        if len(spans) == 0:
            pytest.fail(
                f"No traces found for request_id={request_id}. "
                f"Baggage may not be set correctly."
            )

        logger.info(f"✅ Found {len(spans)} spans")

        # Get unique trace IDs (should be only 1 trace)
        trace_ids = set(span["node"]["context"]["traceId"] for span in spans)
        assert len(trace_ids) == 1, (
            f"Expected all spans in same trace, found {len(trace_ids)} traces. "
            f"Trace IDs: {trace_ids}"
        )

        logger.info(f"✅ All spans belong to same trace: {list(trace_ids)[0]}")

        # Verify ALL spans have baggage attributes
        baggage_check_passed = True
        for span_edge in spans:
            span = span_edge["node"]
            attrs = span["attributes"]
            span_name = span["name"]

            # Check for request.id (or request_id)
            request_id_keys = ["request.id", "request_id"]
            has_request_id = any(
                attrs.get(key) == request_id for key in request_id_keys
            )

            # Check for user.id (or user_id)
            user_id_keys = ["user.id", "user_id"]
            has_user_id = any(attrs.get(key) == user_id for key in user_id_keys)

            if not has_request_id:
                logger.warning(
                    f"⚠️  Span '{span_name}' missing request_id baggage. "
                    f"Checked keys: {request_id_keys}"
                )
                baggage_check_passed = False

            if not has_user_id:
                logger.warning(
                    f"⚠️  Span '{span_name}' missing user_id baggage. "
                    f"Checked keys: {user_id_keys}"
                )
                baggage_check_passed = False

            if has_request_id and has_user_id:
                logger.info(f"   ✅ Span '{span_name}' has complete baggage")

        assert baggage_check_passed, (
            "❌ Not all spans have complete baggage attributes. "
            "Check OTEL baggage processor configuration."
        )

        logger.info("✅ TEST PASSED: Baggage propagates across all services")

    @pytest.mark.asyncio
    async def test_traces_routed_to_correct_namespace(
        self, phoenix_url, test_namespace
    ):
        """
        Test traces are routed to correct namespace project.

        Verifies that traces have k8s.namespace.name resource attribute
        and optionally phoenix.project.name attribute.
        """
        logger.info("🧪 Testing: Traces routed to correct namespace")

        # Query spans by namespace
        query = """
        query GetSpansByNamespace($namespace: String!) {
          spans(filter: {attribute: {key: "k8s.namespace.name", value: $namespace}}, first: 10) {
            edges {
              node {
                name
                attributes
              }
            }
          }
        }
        """

        response = await query_phoenix_graphql(
            phoenix_url=phoenix_url,
            query=query,
            variables={"namespace": test_namespace},
            timeout=10,
        )

        assert "data" in response
        spans = response["data"]["spans"]["edges"]

        if len(spans) == 0:
            pytest.skip(f"No spans found for namespace {test_namespace}")

        logger.info(f"✅ Found {len(spans)} spans for namespace {test_namespace}")

        # Verify all spans have correct namespace
        for span_edge in spans:
            attrs = span_edge["node"]["attributes"]
            span_name = span_edge["node"]["name"]

            assert (
                attrs.get("k8s.namespace.name") == test_namespace
            ), f"Span '{span_name}' has wrong namespace: {attrs.get('k8s.namespace.name')}"

            # Check for Phoenix project name (optional)
            if "phoenix.project.name" in attrs:
                expected_project = f"{test_namespace}-agents"
                actual_project = attrs["phoenix.project.name"]
                logger.info(
                    f"   ✅ Span '{span_name}' routed to project: {actual_project}"
                )
                assert (
                    actual_project == expected_project
                ), f"Wrong project name. Expected: {expected_project}, Got: {actual_project}"

        logger.info("✅ TEST PASSED: Traces routed to correct namespace")


# ============================================================================
# Test Class: Phoenix Backend
# ============================================================================


class TestPhoenixBackend:
    """Test Phoenix backend deployment and configuration."""

    @pytest.mark.asyncio
    async def test_phoenix_pod_running(self, k8s_api):
        """Test Phoenix pod is running in observability namespace."""
        if not k8s_api:
            pytest.skip("Kubernetes client not available")

        pods = k8s_api.list_namespaced_pod(namespace="observability")

        phoenix_pod = None
        for pod in pods.items:
            if "phoenix" in pod.metadata.name.lower():
                phoenix_pod = pod
                break

        assert (
            phoenix_pod is not None
        ), "Phoenix pod not found in observability namespace"
        assert (
            phoenix_pod.status.phase == "Running"
        ), f"Phoenix pod not running: {phoenix_pod.status.phase}"

        logger.info(f"✅ Phoenix pod running: {phoenix_pod.metadata.name}")

    @pytest.mark.asyncio
    async def test_phoenix_graphql_api_accessible(self, phoenix_url):
        """Test Phoenix GraphQL API is accessible."""
        # Simple introspection query
        query = """
        query {
          __schema {
            queryType {
              name
            }
          }
        }
        """

        response = await query_phoenix_graphql(
            phoenix_url=phoenix_url, query=query, timeout=10
        )

        assert "data" in response, f"GraphQL API failed: {response}"
        assert "__schema" in response["data"]
        assert "queryType" in response["data"]["__schema"]

        logger.info("✅ Phoenix GraphQL API accessible")


# ============================================================================
# Test Class: OTEL Collector Routing
# ============================================================================


class TestOTELCollectorRouting:
    """Test OTEL Collector routing configuration."""

    @pytest.mark.asyncio
    async def test_otel_collector_pod_running(self, k8s_api):
        """Test OTEL Collector pod is running."""
        if not k8s_api:
            pytest.skip("Kubernetes client not available")

        pods = k8s_api.list_namespaced_pod(namespace="observability")

        otel_pod = None
        for pod in pods.items:
            if "otel-collector" in pod.metadata.name.lower():
                otel_pod = pod
                break

        if not otel_pod:
            # Try kagenti-system namespace (depends on deployment)
            pods = k8s_api.list_namespaced_pod(namespace="kagenti-system")
            for pod in pods.items:
                if "otel-collector" in pod.metadata.name.lower():
                    otel_pod = pod
                    break

        assert otel_pod is not None, "OTEL Collector pod not found"
        assert (
            otel_pod.status.phase == "Running"
        ), f"OTEL Collector not running: {otel_pod.status.phase}"

        logger.info(f"✅ OTEL Collector running: {otel_pod.metadata.name}")

    @pytest.mark.asyncio
    async def test_otel_collector_routes_to_phoenix(self, k8s_api):
        """
        Test OTEL Collector configuration includes Phoenix exporter.

        This is a configuration test, not a runtime test.
        """
        if not k8s_api:
            pytest.skip("Kubernetes client not available")

        # Try observability namespace first
        namespaces = ["observability", "kagenti-system"]

        configmap = None
        for namespace in namespaces:
            try:
                configmap = k8s_api.read_namespaced_config_map(
                    name="otel-collector-config", namespace=namespace
                )
                break
            except Exception:
                continue

        if not configmap:
            pytest.skip("OTEL Collector ConfigMap not found")

        config_yaml = configmap.data.get("config.yaml", "")

        # Verify Phoenix exporter exists
        assert (
            "phoenix" in config_yaml.lower()
        ), "Phoenix exporter not found in OTEL Collector config"

        # Verify routing processor exists
        assert (
            "routing" in config_yaml or "openinference" in config_yaml
        ), "Routing processor not configured for OpenInference"

        logger.info("✅ OTEL Collector configured to route to Phoenix")
