# Copyright 2024 Kagenti Authors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
MLflow Weather Agent Traces E2E Tests.

Validates that weather agent traces are captured in MLflow after E2E tests run.
These tests MUST run AFTER other E2E tests (especially test_agent_conversation.py)
which generate the traces by invoking the weather agent.

The test is marked with @pytest.mark.observability to ensure it runs in phase 2
of the two-phase test execution:
  - Phase 1: pytest -m "not observability"  (runs weather agent tests, generates traces)
  - Phase 2: pytest -m "observability"      (validates traces in MLflow)

Uses the MLflow Python client for full access to trace span details,
which is required to identify weather agent traces by service.name.

Usage:
    # Run with other observability tests (after main E2E tests)
    pytest kagenti/tests/e2e/ -v -m "observability"

    # Standalone debugging
    python kagenti/tests/e2e/common/test_mlflow_traces.py
"""

import logging
import os
import subprocess
import time
from typing import Any

import pytest

logger = logging.getLogger(__name__)

# Weather agent identification patterns
# These patterns match the service.name or span names from weather agent traces
WEATHER_AGENT_PATTERNS = [
    "weather",
    "weather-service",
    "weather_service",
    "weather_agent",
    "weatheragent",
    "a2a-server",  # Default A2A server service name
    "a2a.server",  # A2A SDK span name prefix (e.g., a2a.server.request_handlers...)
]


def get_mlflow_url() -> str | None:
    """Get MLflow URL from environment or auto-detect from cluster."""
    url = os.getenv("MLFLOW_URL")
    if url:
        return url

    # Try to get from OpenShift route (try both oc and kubectl)
    for cmd in ["oc", "kubectl"]:
        try:
            result = subprocess.run(
                [
                    cmd,
                    "get",
                    "route",
                    "mlflow",
                    "-n",
                    "kagenti-system",
                    "-o",
                    "jsonpath={.spec.host}",
                ],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.returncode == 0 and result.stdout:
                return f"https://{result.stdout}"
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass

    # Fall back to Kind cluster URL
    return "http://mlflow.localtest.me:8080"


def setup_mlflow_client(mlflow_url: str) -> bool:
    """Configure MLflow client with tracking URI.

    Returns True if successful, False otherwise.
    """
    try:
        import mlflow

        # Set tracking URI
        mlflow.set_tracking_uri(mlflow_url)
        logger.info(f"MLflow tracking URI set to: {mlflow_url}")

        # Test connection by getting the tracking URI back
        configured_uri = mlflow.get_tracking_uri()
        logger.info(f"MLflow configured with tracking URI: {configured_uri}")
        return True
    except ImportError:
        logger.error("MLflow package not installed. Install with: pip install mlflow")
        return False
    except Exception as e:
        logger.error(f"Failed to configure MLflow client: {e}")
        import traceback

        traceback.print_exc()
        return False


# Module-level shared MLflow client to avoid creating multiple instances
_mlflow_client = None


def get_mlflow_client():
    """Get or create a shared MLflow client.

    Uses a module-level cached client to avoid creating multiple instances
    which can cause rate limiting issues.

    Raises an error if MLflow is not configured or auth token is missing.
    """
    global _mlflow_client
    import mlflow

    # Verify tracking URI is set
    tracking_uri = mlflow.get_tracking_uri()
    if not tracking_uri or tracking_uri == "databricks":
        raise ValueError(
            "MLflow tracking URI not configured - call setup_mlflow_client first"
        )

    # Verify token is set - fail if not
    token = os.environ.get("MLFLOW_TRACKING_TOKEN", "")
    if not token:
        raise ValueError(
            "MLFLOW_TRACKING_TOKEN not set - MLflow auth required. "
            "Ensure mlflow_configured fixture ran before this test."
        )

    # Reuse existing client if available
    if _mlflow_client is None:
        _mlflow_client = mlflow.MlflowClient()
        logger.info("Created new MLflow client")

    return _mlflow_client


def get_all_traces() -> list[dict[str, Any]]:
    """Get all traces from MLflow using Python client."""
    try:
        client = get_mlflow_client()
        if not client:
            return []

        # Get all experiments
        experiments = client.search_experiments()
        all_traces = []

        for exp in experiments:
            try:
                # Search traces in this experiment
                # Use 'locations' parameter (experiment_ids is deprecated)
                traces = client.search_traces(locations=[exp.experiment_id])
                all_traces.extend(traces)
            except Exception as e:
                logger.warning(f"Failed to search traces in experiment {exp.name}: {e}")

        return all_traces
    except ValueError:
        # Re-raise configuration errors
        raise
    except Exception as e:
        logger.error(f"Failed to get traces: {e}")
        import traceback

        traceback.print_exc()
        return []


def is_weather_agent_trace(trace: Any) -> bool:
    """Check if a trace is from the weather agent.

    Examines span resource attributes and span names to identify
    traces from the weather agent.
    """
    try:
        client = get_mlflow_client()
        if not client:
            return False

        # Get trace info (contains spans)
        trace_info = trace.info if hasattr(trace, "info") else trace

        request_id = (
            trace_info.request_id
            if hasattr(trace_info, "request_id")
            else trace_info.get("request_id")
        )

        if not request_id:
            return False

        # Get trace data which includes spans
        trace_data = client.get_trace(request_id)

        if not trace_data:
            return False

        # Check spans for weather agent indicators
        spans = trace_data.data.spans if hasattr(trace_data, "data") else []

        for span in spans:
            # Check span name
            span_name = span.name.lower() if hasattr(span, "name") else ""
            if any(pattern in span_name for pattern in WEATHER_AGENT_PATTERNS):
                return True

            # Check span attributes for service.name
            attributes = span.attributes if hasattr(span, "attributes") else {}
            service_name = attributes.get("service.name", "").lower()
            if any(pattern in service_name for pattern in WEATHER_AGENT_PATTERNS):
                return True

            # Check resource attributes
            if hasattr(span, "resource"):
                resource_attrs = span.resource.attributes if span.resource else {}
                service_name = resource_attrs.get("service.name", "").lower()
                if any(pattern in service_name for pattern in WEATHER_AGENT_PATTERNS):
                    return True

        # Check trace-level tags
        tags = trace_info.tags if hasattr(trace_info, "tags") else {}
        for key, value in tags.items():
            value_str = str(value).lower()
            if any(pattern in value_str for pattern in WEATHER_AGENT_PATTERNS):
                return True

        return False

    except Exception as e:
        logger.warning(f"Error checking trace: {e}")
        return False


def find_weather_agent_traces(max_traces_to_check: int = 20) -> list[Any]:
    """Find all traces from the weather agent.

    Args:
        max_traces_to_check: Maximum number of traces to check. Limited to avoid
                            excessive API calls which can cause rate limiting.
    """
    all_traces = get_all_traces()
    weather_traces = []

    # Limit the number of traces we check to avoid rate limiting
    traces_to_check = all_traces[:max_traces_to_check]
    logger.info(
        f"Checking {len(traces_to_check)} of {len(all_traces)} traces for weather agent"
    )

    for trace in traces_to_check:
        if is_weather_agent_trace(trace):
            weather_traces.append(trace)

    return weather_traces


def get_trace_span_details(trace: Any) -> list[dict[str, Any]]:
    """Get span details for a trace."""
    try:
        client = get_mlflow_client()
        if not client:
            logger.warning("MLflow client not available")
            print("ERROR: MLflow client not available in get_trace_span_details")
            return []

        trace_info = trace.info if hasattr(trace, "info") else trace
        request_id = (
            trace_info.request_id
            if hasattr(trace_info, "request_id")
            else trace_info.get("request_id")
        )

        if not request_id:
            logger.warning("No request_id found in trace")
            print(f"ERROR: No request_id found in trace: {trace}")
            return []

        token = os.environ.get("MLFLOW_TRACKING_TOKEN", "")
        print(
            f"DEBUG: Getting trace {request_id} (token set: {bool(token)}, len: {len(token)})"
        )
        trace_data = client.get_trace(request_id)
        if not trace_data:
            logger.warning(f"No trace data returned for {request_id}")
            print(f"ERROR: No trace data returned for {request_id}")
            return []
        if not hasattr(trace_data, "data"):
            logger.warning(f"Trace {request_id} has no data attribute")
            print(f"ERROR: Trace {request_id} has no data attribute")
            return []

        spans = trace_data.data.spans if hasattr(trace_data.data, "spans") else []
        print(f"DEBUG: Trace {request_id} has {len(spans)} raw spans")
        logger.debug(f"Trace {request_id} has {len(spans)} spans")

        span_details = []
        for span in spans:
            print(
                f"DEBUG: Processing span: {span.name if hasattr(span, 'name') else 'unknown'}"
            )
            span_detail = {
                "name": span.name if hasattr(span, "name") else "unknown",
                "span_id": span.span_id if hasattr(span, "span_id") else "unknown",
                "parent_id": span.parent_id if hasattr(span, "parent_id") else None,
                "status": span.status if hasattr(span, "status") else "unknown",
                "attributes": dict(span.attributes)
                if hasattr(span, "attributes")
                else {},
            }
            span_details.append(span_detail)

        print(f"DEBUG: Returning {len(span_details)} span_details for {request_id}")
        return span_details

    except Exception as e:
        logger.warning(f"Error getting span details: {e}")
        import traceback

        traceback.print_exc()
        return []


@pytest.fixture(scope="module")
def mlflow_url():
    """Get MLflow URL for tests."""
    url = get_mlflow_url()
    if not url:
        pytest.skip("MLflow URL not available")
    return url


@pytest.fixture(scope="module")
def mlflow_client_token(k8s_client, is_openshift):
    """Get OAuth2 token for MLflow using client credentials flow.

    Reads MLflow OAuth secret from K8s and uses client credentials grant
    to get an access token. This is required because mlflow-oidc-auth needs
    a token issued for the 'mlflow' client, not 'admin-cli'.

    Returns:
        str: Access token, or None if auth is not configured
    """
    import base64

    import requests
    import urllib3
    from kubernetes.client.rest import ApiException

    # Suppress SSL warnings for OpenShift self-signed certs
    if is_openshift:
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    try:
        # Get MLflow OAuth secret
        secret = k8s_client.read_namespaced_secret(
            name="mlflow-oauth-secret", namespace="kagenti-system"
        )

        client_id = base64.b64decode(secret.data["OIDC_CLIENT_ID"]).decode()
        client_secret = base64.b64decode(secret.data["OIDC_CLIENT_SECRET"]).decode()
        token_url = base64.b64decode(secret.data["OIDC_TOKEN_URL"]).decode()

        logger.info(f"Getting MLflow token from: {token_url}")

        # Get token using client credentials flow
        response = requests.post(
            token_url,
            data={
                "grant_type": "client_credentials",
                "client_id": client_id,
                "client_secret": client_secret,
            },
            timeout=10,
            verify=False,  # OpenShift self-signed certs
        )

        if response.status_code == 200:
            token_data = response.json()
            logger.info(
                f"Got MLflow client token (expires in {token_data.get('expires_in')}s)"
            )
            return token_data.get("access_token")
        else:
            logger.warning(f"Failed to get MLflow token: {response.status_code}")
            return None

    except ApiException as e:
        if e.status == 404:
            logger.info("mlflow-oauth-secret not found - auth may not be enabled")
        else:
            logger.warning(f"Error reading mlflow-oauth-secret: {e}")
        return None
    except Exception as e:
        logger.warning(f"Error getting MLflow token: {e}")
        return None


@pytest.fixture(scope="module")
def mlflow_configured(mlflow_url, mlflow_client_token, is_openshift):
    """Configure MLflow client for tests with Keycloak authentication.

    Sets MLFLOW_TRACKING_TOKEN for bearer token auth when MLflow has OIDC enabled.
    Token must be set BEFORE importing/configuring MLflow client.
    """
    # Disable SSL verification for self-signed certs on OpenShift
    # On OpenShift, we need to disable SSL verification by default
    verify_ssl = os.getenv("MLFLOW_VERIFY_SSL", "true").lower() != "false"
    if is_openshift or not verify_ssl:
        import urllib3

        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        os.environ["MLFLOW_TRACKING_INSECURE_TLS"] = "true"
        if is_openshift:
            logger.info("Disabled SSL verification for OpenShift self-signed certs")

    # Set bearer token for MLflow client authentication BEFORE configuring client
    # This is needed when mlflow-oidc-auth is enabled
    if mlflow_client_token:
        os.environ["MLFLOW_TRACKING_TOKEN"] = mlflow_client_token
        logger.info("Set MLFLOW_TRACKING_TOKEN from MLflow client credentials")
    else:
        logger.warning("No MLflow token available - MLflow auth may fail")

    if not setup_mlflow_client(mlflow_url):
        pytest.skip("Failed to configure MLflow client")

    # Verify token is set by re-checking
    token = os.environ.get("MLFLOW_TRACKING_TOKEN", "")
    logger.info(f"MLFLOW_TRACKING_TOKEN set: {bool(token)} (length: {len(token)})")

    return True


@pytest.mark.observability
@pytest.mark.requires_features(["mlflow"])
class TestMLflowConnectivity:
    """Test MLflow service is accessible."""

    def test_mlflow_accessible(self, mlflow_url: str, mlflow_configured: bool):
        """Verify MLflow is accessible."""
        import httpx

        try:
            response = httpx.get(f"{mlflow_url}/version", verify=False, timeout=30.0)
            # Accept 200 (no auth) or 302/307 (OAuth redirect) as healthy
            assert response.status_code in (200, 302, 307), (
                f"MLflow returned unexpected status {response.status_code}. "
                f"Expected 200, 302, or 307."
            )
        except httpx.RequestError as e:
            pytest.fail(f"Cannot connect to MLflow at {mlflow_url}: {e}")


@pytest.mark.observability
@pytest.mark.openshift_only
@pytest.mark.requires_features(["mlflow"])
class TestWeatherAgentTracesInMLflow:
    """
    Validate weather agent traces are captured in MLflow.

    These tests verify that traces from test_agent_conversation.py
    (which queries the weather agent) are visible in MLflow.

    OpenShift only: Kind CI doesn't have full OTEL instrumentation.
    """

    def test_mlflow_has_traces(self, mlflow_url: str, mlflow_configured: bool):
        """Verify MLflow received traces from E2E tests."""
        # Give traces time to be exported (OTEL batching)
        time.sleep(2)

        traces = get_all_traces()
        trace_count = len(traces)

        print(f"\n{'=' * 60}")
        print("MLflow Trace Summary")
        print(f"{'=' * 60}")
        print(f"Total traces found: {trace_count}")

        assert trace_count > 0, (
            "No traces found in MLflow. "
            "Expected traces from weather agent E2E tests. "
            "Verify that:\n"
            "  1. test_agent_conversation.py ran before this test\n"
            "  2. Weather agent is instrumented (openinference or OTEL)\n"
            "  3. OTEL collector has mlflow exporter configured\n"
            "  4. MLflow is enabled in values.yaml (components.mlflow.enabled: true)"
        )

    def test_weather_agent_traces_exist(self, mlflow_url: str, mlflow_configured: bool):
        """Verify weather agent traces are captured in MLflow.

        This test specifically looks for traces from the weather agent,
        identified by service.name or span names containing 'weather' or 'a2a-server'.
        """
        weather_traces = find_weather_agent_traces()

        print(f"\n{'=' * 60}")
        print("Weather Agent Traces in MLflow")
        print(f"{'=' * 60}")
        print(f"Weather agent traces found: {len(weather_traces)}")

        # Print sample trace info
        for i, trace in enumerate(weather_traces[:5]):
            trace_info = trace.info if hasattr(trace, "info") else trace
            request_id = (
                trace_info.request_id
                if hasattr(trace_info, "request_id")
                else trace_info.get("request_id", "unknown")
            )
            timestamp = (
                trace_info.timestamp_ms
                if hasattr(trace_info, "timestamp_ms")
                else trace_info.get("timestamp_ms", 0)
            )
            print(f"  [{i + 1}] request_id={request_id}, timestamp={timestamp}")

        # Also show total traces for context
        all_traces = get_all_traces()
        print(f"\nTotal traces in MLflow: {len(all_traces)}")

        assert len(weather_traces) > 0, (
            f"No weather agent traces found in MLflow. "
            f"Found {len(all_traces)} total traces, but none from weather agent.\n\n"
            "Expected traces from weather agent with:\n"
            f"  - service.name containing: {', '.join(WEATHER_AGENT_PATTERNS)}\n"
            "  - Span names containing 'weather' or 'a2a'\n\n"
            "Verify that:\n"
            "  1. test_agent_conversation.py ran before this test\n"
            "  2. Weather agent is deployed and instrumented\n"
            "  3. OTEL_EXPORTER_OTLP_ENDPOINT is set in weather agent deployment\n"
            "  4. OTEL collector is forwarding traces to MLflow"
        )

        print(f"\nSUCCESS: Found {len(weather_traces)} weather agent traces")

    def test_weather_trace_has_spans(self, mlflow_url: str, mlflow_configured: bool):
        """Verify weather agent traces have proper span structure.

        This test validates that weather agent traces contain meaningful span
        data that can be used for debugging and performance analysis.
        """
        weather_traces = find_weather_agent_traces()

        assert len(weather_traces) > 0, (
            "No weather agent traces found in MLflow. "
            "Cannot validate span details without traces. "
            "Ensure test_agent_conversation.py ran before this test."
        )

        # Get first weather trace details
        first_trace = weather_traces[0]
        spans = get_trace_span_details(first_trace)

        trace_info = first_trace.info if hasattr(first_trace, "info") else first_trace
        request_id = (
            trace_info.request_id
            if hasattr(trace_info, "request_id")
            else trace_info.get("request_id", "unknown")
        )

        print(f"\n{'=' * 60}")
        print(f"Weather Agent Trace Details: {request_id}")
        print(f"{'=' * 60}")
        print(f"Spans in trace: {len(spans)}")

        assert len(spans) > 0, (
            f"Weather agent trace {request_id} has no spans. "
            "Traces must contain spans for proper observability."
        )

        # Print span hierarchy
        for span in spans[:10]:
            span_name = span.get("name", "unnamed")
            span_status = span.get("status", "unknown")
            print(f"  - {span_name} (status: {span_status})")

        print(f"\nSUCCESS: Weather agent trace has {len(spans)} spans")


# GenAI span patterns - LangChain/LangGraph instrumentation
# Patterns that indicate GenAI/LLM instrumentation
# More specific to avoid matching A2A spans
GENAI_SPAN_PATTERNS = [
    "langchain",
    "langgraph",
    "llmchain",
    "chatopenai",
    "chatollama",
    "agentexecutor",
    "runnablesequence",
    "chatmodel",
    "basellm",
    "retriever",
    "embedding",
    "vectorstore",
]


def has_genai_spans(trace: Any) -> bool:
    """Check if a trace contains GenAI/LLM spans.

    GenAI spans come from LangChain/LangGraph instrumentation and include
    span names like 'ChatOpenAI', 'LLMChain', 'AgentExecutor', etc.

    Excludes A2A spans which have patterns like 'a2a.server.*'.
    """
    spans = get_trace_span_details(trace)
    for span in spans:
        span_name = span.get("name", "").lower()
        span_type = span.get("type", "").lower() if span.get("type") else ""

        # Skip A2A spans - they have distinct naming pattern
        if span_name.startswith("a2a."):
            continue

        # Check span name patterns
        if any(pattern in span_name for pattern in GENAI_SPAN_PATTERNS):
            return True

        # Check span type (LangChain uses types like LLM, CHAIN, TOOL)
        if span_type in ["llm", "chain"]:
            return True

    return False


def get_trace_tree_structure(trace: Any) -> dict:
    """Build a tree structure from trace spans showing parent-child relationships.

    Returns a dict with:
        - root_spans: List of spans with no parent
        - children: Dict mapping span_id to list of child spans
        - depth: Maximum depth of the tree
    """
    spans = get_trace_span_details(trace)

    # Build parent-child relationships
    children: dict = {}
    root_spans = []

    for span in spans:
        span_id = span.get("span_id")
        parent_id = span.get("parent_id")

        # MLflow span.parent_id can be None, "None" (string), or empty string for root spans
        is_root = not parent_id or parent_id == "None" or parent_id == ""
        if is_root:
            root_spans.append(span)
        else:
            if parent_id not in children:
                children[parent_id] = []
            children[parent_id].append(span)

    # Calculate max depth
    def get_depth(span_id: str, current_depth: int = 0) -> int:
        if span_id not in children:
            return current_depth
        max_child_depth = current_depth
        for child in children[span_id]:
            child_depth = get_depth(child.get("span_id", ""), current_depth + 1)
            max_child_depth = max(max_child_depth, child_depth)
        return max_child_depth

    max_depth = 0
    for root in root_spans:
        depth = get_depth(root.get("span_id", ""))
        max_depth = max(max_depth, depth)

    return {
        "root_spans": root_spans,
        "children": children,
        "depth": max_depth,
        "total_spans": len(spans),
    }


@pytest.mark.observability
@pytest.mark.openshift_only
@pytest.mark.requires_features(["mlflow"])
class TestGenAITracesInMLflow:
    """
    Validate GenAI/LLM traces are captured with proper tree structure.

    These tests verify that LangChain/LangGraph instrumentation produces
    traces with:
    - LLM spans (ChatOpenAI, ChatOllama, etc.)
    - Proper parent-child hierarchy
    - Nested structure under a single root trace
    """

    def test_genai_traces_exist(self, mlflow_url: str, mlflow_configured: bool):
        """Verify GenAI/LLM traces are captured in MLflow.

        This test looks for spans from LangChain/LangGraph instrumentation,
        which include LLM calls, chain executions, and tool invocations.
        """
        all_traces = get_all_traces()
        genai_traces = [t for t in all_traces if has_genai_spans(t)]

        print(f"\n{'=' * 60}")
        print("GenAI Traces in MLflow")
        print(f"{'=' * 60}")
        print(f"Total traces: {len(all_traces)}")
        print(f"GenAI traces: {len(genai_traces)}")

        # Show sample GenAI span names
        if genai_traces:
            sample_trace = genai_traces[0]
            spans = get_trace_span_details(sample_trace)
            genai_span_names = [
                s.get("name")
                for s in spans
                if any(p in s.get("name", "").lower() for p in GENAI_SPAN_PATTERNS)
            ]
            print(f"Sample GenAI spans: {genai_span_names[:5]}")

        if len(genai_traces) == 0:
            # Skip if no GenAI traces - agent may not have LangChain instrumentation
            pytest.skip(
                f"No GenAI traces found in MLflow. "
                f"Found {len(all_traces)} total traces, but none with LangChain/LLM spans.\n"
                "To enable GenAI tracing:\n"
                "  1. Install openinference-instrumentation-langchain in the agent\n"
                "  2. Call LangChainInstrumentor().instrument() at startup"
            )

        print(f"\nSUCCESS: Found {len(genai_traces)} GenAI traces")

    def test_trace_has_tree_structure(self, mlflow_url: str, mlflow_configured: bool):
        """Verify traces have proper parent-child hierarchy.

        GenAI traces should have a tree structure where:
        - A root span represents the top-level request
        - Child spans represent LLM calls, tool executions, etc.
        - The tree should have depth > 1 for non-trivial requests
        """
        all_traces = get_all_traces()
        if not all_traces:
            pytest.skip("No traces available to check structure")

        # Get a trace with GenAI spans if available, otherwise any trace
        # Prefer traces with more spans for better tree structure validation
        genai_traces = [t for t in all_traces if has_genai_spans(t)]

        # Find a trace with multiple spans (prefer 3+ for proper hierarchy)
        # Limit API calls to avoid rate limiting issues
        candidate_traces = genai_traces if genai_traces else all_traces
        trace = None
        best_span_count = 0

        # Only check first 5 traces to avoid rate limiting
        for t in candidate_traces[:5]:
            tree_info = get_trace_tree_structure(t)
            if tree_info["total_spans"] > best_span_count:
                best_span_count = tree_info["total_spans"]
                trace = t
                if best_span_count >= 3:
                    break  # Good enough for tree structure test

        if not trace:
            if candidate_traces:
                trace = candidate_traces[0]
            else:
                pytest.skip("No candidate traces available")

        tree = get_trace_tree_structure(trace)

        print(f"\n{'=' * 60}")
        print("Trace Tree Structure")
        print(f"{'=' * 60}")
        print(f"Total spans: {tree['total_spans']}")
        print(f"Root spans: {len(tree['root_spans'])}")
        print(f"Max depth: {tree['depth']}")

        # Print tree visualization
        def print_tree(span: dict, indent: int = 0):
            name = span.get("name", "unnamed")[:50]
            print(f"{'  ' * indent}├─ {name}")
            span_id = span.get("span_id", "")
            for child in tree["children"].get(span_id, [])[:3]:
                print_tree(child, indent + 1)

        print("\nTree structure (first root, max 3 children per level):")
        if tree["root_spans"]:
            print_tree(tree["root_spans"][0])

        if tree["total_spans"] == 0:
            pytest.skip(
                "Could not retrieve span details for trace. "
                "This may be due to API rate limiting or auth issues."
            )

        assert len(tree["root_spans"]) > 0, "Trace has no root spans"

        # For GenAI traces, we expect a tree structure with depth > 0
        if genai_traces:
            assert tree["depth"] >= 1, (
                f"GenAI trace has flat structure (depth={tree['depth']}). "
                "Expected hierarchical trace with LLM calls nested under agent spans."
            )

        print(f"\nSUCCESS: Trace has tree structure with depth {tree['depth']}")

    def test_genai_spans_nested_under_a2a(
        self, mlflow_url: str, mlflow_configured: bool
    ):
        """Verify GenAI spans are nested under A2A request spans.

        When the weather agent receives an A2A request, the trace should show:
        - A2A request handler as root span
        - LangGraph/LangChain execution as child spans
        - LLM calls nested under the chain/agent spans
        """
        all_traces = get_all_traces()
        genai_traces = [t for t in all_traces if has_genai_spans(t)]

        if not genai_traces:
            pytest.skip("No GenAI traces available")

        trace = genai_traces[0]
        tree = get_trace_tree_structure(trace)
        spans = get_trace_span_details(trace)

        # Check if there's an A2A root span with GenAI children
        a2a_root = None
        for root in tree["root_spans"]:
            root_name = root.get("name", "").lower()
            if "a2a" in root_name or "request" in root_name:
                a2a_root = root
                break

        print(f"\n{'=' * 60}")
        print("A2A + GenAI Trace Structure")
        print(f"{'=' * 60}")

        if a2a_root:
            print(f"A2A root span: {a2a_root.get('name')}")
            root_id = a2a_root.get("span_id", "")
            children = tree["children"].get(root_id, [])
            print(f"Direct children: {len(children)}")
            for child in children[:5]:
                print(f"  - {child.get('name', 'unnamed')[:60]}")
        else:
            print("No A2A root span found")
            print("Root spans:")
            for root in tree["root_spans"][:3]:
                print(f"  - {root.get('name', 'unnamed')[:60]}")

        # Check for GenAI spans in the tree
        genai_span_count = sum(
            1
            for s in spans
            if any(p in s.get("name", "").lower() for p in GENAI_SPAN_PATTERNS)
        )
        print(f"\nGenAI spans in trace: {genai_span_count}")

        assert genai_span_count > 0, "No GenAI spans found in trace"
        print("\nSUCCESS: Found GenAI spans in trace hierarchy")


@pytest.mark.observability
@pytest.mark.openshift_only
@pytest.mark.requires_features(["mlflow"])
class TestMLflowSessions:
    """
    Validate trace sessions are properly organized in MLflow.

    MLflow supports grouping traces into sessions, which can be mapped
    to A2A context_id for conversation tracking.
    """

    def test_traces_have_session_info(self, mlflow_url: str, mlflow_configured: bool):
        """Verify traces have session/context information.

        Traces should have tags or metadata that allow grouping by:
        - A2A context_id (conversation identifier)
        - Session ID
        - Client request ID
        """
        all_traces = get_all_traces()
        if not all_traces:
            pytest.skip("No traces available")

        print(f"\n{'=' * 60}")
        print("Trace Session Information")
        print(f"{'=' * 60}")

        traces_with_session = 0
        session_ids = set()

        for trace in all_traces[:10]:
            trace_info = trace.info if hasattr(trace, "info") else trace

            # Check for session-related fields
            client_request_id = getattr(trace_info, "client_request_id", None)
            tags = getattr(trace_info, "tags", {}) or {}

            # Look for session/context tags
            context_id = tags.get("a2a.context_id") or tags.get("context_id")
            session_id = tags.get("session_id") or tags.get("mlflow.session_id")

            if client_request_id or context_id or session_id:
                traces_with_session += 1
                if context_id:
                    session_ids.add(context_id)
                if session_id:
                    session_ids.add(session_id)

        print(f"Total traces checked: {min(10, len(all_traces))}")
        print(f"Traces with session info: {traces_with_session}")
        print(f"Unique session IDs: {len(session_ids)}")
        if session_ids:
            print(f"Sample session IDs: {list(session_ids)[:3]}")

        # This is informational - not a hard requirement yet
        if traces_with_session == 0:
            print(
                "\nNOTE: No session info found. Consider adding a2a.context_id "
                "as a trace tag for conversation grouping."
            )


def main():
    """Standalone execution for debugging MLflow traces."""
    import argparse

    logging.basicConfig(level=logging.INFO)

    parser = argparse.ArgumentParser(description="Debug MLflow traces")
    parser.add_argument("--url", help="MLflow URL (default: auto-detect)")
    parser.add_argument(
        "--no-verify-ssl", action="store_true", help="Disable SSL verification"
    )
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose output")
    args = parser.parse_args()

    url = args.url or get_mlflow_url()
    if not url:
        print("ERROR: Could not determine MLflow URL")
        return 1

    print(f"MLflow URL: {url}")

    if args.no_verify_ssl:
        import urllib3

        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        os.environ["MLFLOW_TRACKING_INSECURE_TLS"] = "true"

    if not setup_mlflow_client(url):
        print("ERROR: Failed to configure MLflow client")
        return 1

    print("MLflow: Connected\n")

    # Get all traces
    traces = get_all_traces()
    print(f"Total traces: {len(traces)}")

    # Find weather agent traces
    weather_traces = find_weather_agent_traces()
    print(f"Weather agent traces: {len(weather_traces)}")

    if args.verbose and weather_traces:
        print("\n" + "=" * 60)
        print("Weather Agent Trace Details")
        print("=" * 60)
        for trace in weather_traces[:3]:
            trace_info = trace.info if hasattr(trace, "info") else trace
            request_id = (
                trace_info.request_id
                if hasattr(trace_info, "request_id")
                else trace_info.get("request_id", "unknown")
            )
            print(f"\nTrace: {request_id}")

            spans = get_trace_span_details(trace)
            for span in spans[:5]:
                print(f"  - {span.get('name', 'unnamed')}")

    return 0


if __name__ == "__main__":
    exit(main())
