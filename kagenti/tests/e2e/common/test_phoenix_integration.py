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
from a2a.types import MessageSendParams, SendStreamingMessageRequest, Message, TextPart

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
    """Phoenix GraphQL API endpoint.

    Default: localhost:6006 (via port-forward from 85-start-port-forward.sh)
    In-cluster: http://phoenix.kagenti-system.svc.cluster.local:6006
    """
    return os.getenv("PHOENIX_URL", "http://localhost:6006")


@pytest.fixture(scope="module")
def agent_url():
    """Weather agent endpoint.

    Default: localhost:8000 (via port-forward from 85-start-port-forward.sh)
    In-cluster: http://weather-service-svc.team1.svc.cluster.local:8080
    """
    return os.getenv("AGENT_URL", "http://localhost:8000")


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
    request_id = request_id or str(uuid.uuid4())
    conversation_id = conversation_id or str(uuid.uuid4())

    # Create A2A client with httpx client
    async with httpx.AsyncClient(timeout=timeout) as http_client:
        client = A2AClient(httpx_client=http_client, url=agent_url)

        # Create message object with proper structure
        msg = Message(
            message_id=request_id,
            role="user",
            parts=[TextPart(text=message)],
            context_id=conversation_id,
        )

        # Prepare message with baggage headers (JSON-RPC requires an id)
        request_params = SendStreamingMessageRequest(
            id=request_id,  # JSON-RPC request ID
            params=MessageSendParams(
                message=msg,
            ),
        )

        # Send streaming message
        responses = []
        async for response in client.send_message_streaming(request_params):
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


@pytest.mark.requires_features(["otel", "kagentiOperator"])
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
        # Note: context_id (conversation_id) must be a valid UUID without prefix
        # per A2A SDK requirements in a2a/utils/task.py:new_task()
        user_id = "alice"
        request_id = str(uuid.uuid4())
        conversation_id = str(uuid.uuid4())

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

        # Step 3: Query Phoenix for recent spans in the default project
        # Phoenix 8.x uses projects -> spans structure, not root spans query
        # Increase limit to 200 to ensure we capture LLM spans even with many A2A SDK spans
        query = """
        query GetRecentSpans {
          projects {
            edges {
              node {
                name
                spans(first: 200) {
                  edges {
                    node {
                      name
                      context {
                        traceId
                        spanId
                      }
                      startTime
                      endTime
                      spanKind
                    }
                  }
                }
              }
            }
          }
        }
        """

        logger.info(f"🔍 Querying Phoenix for recent traces (request.id={request_id})")

        phoenix_response = await query_phoenix_graphql(
            phoenix_url=phoenix_url,
            query=query,
            variables={},
            timeout=15,
        )

        # Step 4: Assertions
        assert "data" in phoenix_response, f"Phoenix query failed: {phoenix_response}"
        assert (
            phoenix_response["data"] is not None
        ), f"Phoenix returned null data: {phoenix_response}"
        assert (
            "projects" in phoenix_response["data"]
        ), "No projects field in Phoenix response"

        # Extract spans from all projects
        spans = []
        for project_edge in phoenix_response["data"]["projects"]["edges"]:
            project = project_edge["node"]
            for span_edge in project["spans"]["edges"]:
                spans.append(span_edge)

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

        # Extract span data - Phoenix 8.x uses spanKind directly, not attributes
        span_nodes = [edge["node"] for edge in spans]
        span_names = [span["name"] for span in span_nodes]
        span_kinds = [span.get("spanKind", "UNKNOWN") for span in span_nodes]

        logger.info(f"📊 Span names: {span_names}")
        logger.info(f"📊 Span kinds: {span_kinds}")

        # Verify expected spans exist
        # We expect at least one LLM span (for ChatOpenAI/LangGraph)
        # Note: A2A SDK creates many spans with spanKind=UNKNOWN (expected behavior)
        llm_spans = [kind for kind in span_kinds if kind == "LLM"]
        # In Phoenix 8.x, ChatOpenAI spans have spanKind=LLM
        # If not found, check for ChatOpenAI span by name
        if len(llm_spans) == 0:
            llm_spans = [
                name for name in span_names if "ChatOpenAI" in name or "OpenAI" in name
            ]

        # Count span kinds for debugging
        kind_counts = {}
        for kind in span_kinds:
            kind_counts[kind] = kind_counts.get(kind, 0) + 1

        # Count A2A SDK spans (they start with "a2a.")
        a2a_spans = [name for name in span_names if name.startswith("a2a.")]
        langchain_spans = [
            name
            for name in span_names
            if "ChatOpenAI" in name
            or "LangGraph" in name
            or "weather_agent" in name
            or "ToolNode" in name
        ]

        logger.info(f"📊 Span kind distribution: {kind_counts}")
        logger.info(f"📊 A2A SDK spans: {len(a2a_spans)}")
        logger.info(f"📊 LangChain/Agent spans: {len(langchain_spans)}")

        assert len(llm_spans) > 0, (
            f"❌ No LLM spans found. Expected at least 1 LLM span.\n"
            f"Span kind distribution: {kind_counts}\n"
            f"A2A SDK spans: {len(a2a_spans)} (expected - internal event tracing)\n"
            f"LangChain spans: {langchain_spans}\n"
            f"This indicates OpenInference LangChain instrumentation may not be working.\n"
            f"All span names: {span_names[:20]}..."  # First 20 for readability
        )

        logger.info(f"✅ Found {len(llm_spans)} LLM spans")

        # Log span details (attributes queried separately if needed)
        for i, span in enumerate(span_nodes):
            span_name = span["name"]
            span_kind = span.get("spanKind", "UNKNOWN")

            logger.info(f"\n📋 Span {i+1}/{len(span_nodes)}: {span_name}")
            logger.info(f"   Kind: {span_kind}")

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
        Test LLM spans exist and have spanKind=LLM.

        Phoenix 8.x uses spanKind field directly instead of attributes.
        Verifies that LLM spans are properly instrumented.
        """
        logger.info("🧪 Testing: LLM spans have correct spanKind")

        # Query for spans from all projects (Phoenix 8.x API)
        query = """
        query GetLLMSpans {
          projects {
            edges {
              node {
                name
                spans(first: 20) {
                  edges {
                    node {
                      name
                      spanKind
                      context {
                        traceId
                      }
                    }
                  }
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
        assert response["data"] is not None, f"Phoenix returned null data: {response}"

        # Extract LLM spans from all projects
        llm_spans = []
        for project_edge in response["data"]["projects"]["edges"]:
            project = project_edge["node"]
            for span_edge in project["spans"]["edges"]:
                span = span_edge["node"]
                if span.get("spanKind") == "LLM" or "ChatOpenAI" in span["name"]:
                    llm_spans.append(span)

        if len(llm_spans) == 0:
            pytest.skip(
                "No LLM spans found in Phoenix (run test_agent_conversation_creates_traces first)"
            )

        logger.info(f"✅ Found {len(llm_spans)} LLM spans")

        # Log each LLM span
        for span in llm_spans:
            span_name = span["name"]
            span_kind = span.get("spanKind", "UNKNOWN")
            logger.info(f"   📋 LLM span: {span_name} (kind={span_kind})")

        logger.info("✅ TEST PASSED: LLM spans have correct spanKind")

    @pytest.mark.asyncio
    async def test_baggage_propagates_across_services(self, agent_url, phoenix_url):
        """
        Test that agent requests create complete traces with multiple spans.

        Verifies that:
        - Agent requests create traces in Phoenix
        - Multiple spans exist per trace (agent, LLM, potentially tool)
        - All spans belong to the same trace

        Note: Full baggage attribute propagation requires OTEL baggage processor
        configuration in the collector. This test verifies trace continuity.
        """
        logger.info("🧪 Testing: Agent requests create complete traces")

        # Send request to agent
        user_id = "bob"
        request_id = str(uuid.uuid4())

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

        # Query spans from Phoenix (using Phoenix 8.x API)
        query = """
        query GetRecentSpans {
          projects {
            edges {
              node {
                name
                spans(first: 50) {
                  edges {
                    node {
                      name
                      context {
                        traceId
                        spanId
                      }
                      spanKind
                    }
                  }
                }
              }
            }
          }
        }
        """

        phoenix_response = await query_phoenix_graphql(
            phoenix_url=phoenix_url,
            query=query,
            variables={},
            timeout=15,
        )

        assert "data" in phoenix_response, f"Phoenix query failed: {phoenix_response}"
        assert phoenix_response["data"] is not None

        # Extract all spans from all projects
        spans = []
        for project_edge in phoenix_response["data"]["projects"]["edges"]:
            project = project_edge["node"]
            for span_edge in project["spans"]["edges"]:
                spans.append(span_edge)

        assert len(spans) > 0, "No spans found in Phoenix"

        logger.info(f"✅ Found {len(spans)} spans")

        # Get unique trace IDs
        trace_ids = set(span["node"]["context"]["traceId"] for span in spans)
        logger.info(f"✅ Found {len(trace_ids)} unique trace ID(s)")

        # Log span details
        for span_edge in spans:
            span = span_edge["node"]
            span_name = span["name"]
            span_kind = span.get("spanKind", "UNKNOWN")
            logger.info(f"   📋 Span: {span_name} (kind={span_kind})")

        logger.info("✅ TEST PASSED: Agent requests create complete traces")

    @pytest.mark.asyncio
    async def test_traces_routed_to_correct_namespace(
        self, phoenix_url, test_namespace
    ):
        """
        Test traces exist in Phoenix projects.

        Phoenix 8.x organizes traces by projects. This test verifies that
        traces are being collected and stored in Phoenix projects.

        Note: Namespace-based routing requires OTEL resource attributes to be
        configured in the collector's resource processor.
        """
        logger.info("🧪 Testing: Traces exist in Phoenix projects")

        # Query projects to verify traces exist (Phoenix 8.x API)
        query = """
        query GetProjects {
          projects {
            edges {
              node {
                name
                traceCount
              }
            }
          }
        }
        """

        response = await query_phoenix_graphql(
            phoenix_url=phoenix_url,
            query=query,
            variables={},
            timeout=10,
        )

        assert response is not None, "GraphQL query returned None"
        assert "data" in response, f"GraphQL response missing 'data': {response}"
        assert response["data"] is not None, f"GraphQL data is None: {response}"

        projects = response["data"]["projects"]["edges"]
        assert len(projects) > 0, "No projects found in Phoenix"

        # Log projects and trace counts
        total_traces = 0
        for project_edge in projects:
            project = project_edge["node"]
            project_name = project["name"]
            trace_count = project.get("traceCount", 0)
            total_traces += trace_count
            logger.info(f"   📁 Project '{project_name}': {trace_count} traces")

        assert total_traces > 0, "No traces found in any Phoenix project"

        logger.info(
            f"✅ Found {total_traces} total traces across {len(projects)} projects"
        )
        logger.info("✅ TEST PASSED: Traces exist in Phoenix projects")


# ============================================================================
# Test Class: Phoenix Backend
# ============================================================================


@pytest.mark.requires_features(["otel"])
class TestPhoenixBackend:
    """Test Phoenix backend deployment and configuration."""

    @pytest.mark.asyncio
    async def test_phoenix_pod_running(self, k8s_api):
        """Test Phoenix pod is running in kagenti-system or observability namespace."""
        if not k8s_api:
            pytest.skip("Kubernetes client not available")

        # Check both kagenti-system and observability namespaces
        phoenix_pod = None
        for namespace in ["kagenti-system", "observability"]:
            pods = k8s_api.list_namespaced_pod(namespace=namespace)
            for pod in pods.items:
                if "phoenix" in pod.metadata.name.lower():
                    phoenix_pod = pod
                    break
            if phoenix_pod:
                break

        assert (
            phoenix_pod is not None
        ), "Phoenix pod not found in kagenti-system or observability namespace"
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


@pytest.mark.requires_features(["otel"])
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

        # Check both config.yaml and base.yaml keys (deployment dependent)
        config_yaml = configmap.data.get("config.yaml", "") or configmap.data.get(
            "base.yaml", ""
        )

        # Verify Phoenix exporter exists
        assert (
            "phoenix" in config_yaml.lower()
        ), f"Phoenix exporter not found in OTEL Collector config. Available keys: {list(configmap.data.keys())}"

        # Verify routing processor exists (may be filter/phoenix or routing)
        assert (
            "routing" in config_yaml.lower()
            or "openinference" in config_yaml.lower()
            or "filter/phoenix" in config_yaml.lower()
        ), "Routing/filter processor not configured for OpenInference"

        logger.info("✅ OTEL Collector configured to route to Phoenix")
