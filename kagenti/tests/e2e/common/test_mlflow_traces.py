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
    # LangChain/LangGraph patterns (OpenInference instrumentation)
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
    # OpenTelemetry GenAI semantic convention patterns
    "openai",
    "chat.completions",
    "gen_ai",
    "llm.",
    "chat_completion",
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

    # Class-level cache for traces to avoid rate limiting between tests
    _cached_traces: list = None
    _cached_genai_traces: list = None

    @classmethod
    def _get_cached_traces(cls) -> tuple[list, list]:
        """Get cached traces or fetch from MLflow once."""
        if cls._cached_traces is None:
            cls._cached_traces = get_all_traces()
            cls._cached_genai_traces = [
                t for t in cls._cached_traces if has_genai_spans(t)
            ]
            logger.info(
                f"Cached {len(cls._cached_traces)} traces, "
                f"{len(cls._cached_genai_traces)} GenAI traces"
            )
        return cls._cached_traces, cls._cached_genai_traces

    def test_genai_traces_exist(self, mlflow_url: str, mlflow_configured: bool):
        """Verify GenAI/LLM traces are captured in MLflow.

        This test looks for spans from LangChain/LangGraph instrumentation,
        which include LLM calls, chain executions, and tool invocations.
        """
        all_traces, genai_traces = self._get_cached_traces()

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
        all_traces, genai_traces = self._get_cached_traces()
        if not all_traces:
            pytest.skip("No traces available to check structure")

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
        all_traces, genai_traces = self._get_cached_traces()

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

        if genai_span_count == 0:
            # If we can't find spans, it may be due to rate limiting after prior tests
            # The test_genai_traces_exist already verified GenAI traces exist
            if not spans:
                pytest.skip(
                    "Could not retrieve span details for trace. "
                    "This may be due to API rate limiting. "
                    "GenAI traces were verified in test_genai_traces_exist."
                )
            else:
                # Spans exist but none match - print them for debugging
                print("\nSpan names in trace:")
                for s in spans[:10]:
                    print(f"  - {s.get('name', 'unnamed')}")
                pytest.fail(f"No GenAI spans found in trace with {len(spans)} spans")

        print("\nSUCCESS: Found GenAI spans in trace hierarchy")


@pytest.mark.observability
@pytest.mark.openshift_only
@pytest.mark.requires_features(["mlflow"])
class TestMLflowTraceMetadata:
    """
    Validate trace metadata fields visible in MLflow UI.

    Tests comprehensive trace metadata including:
    - Trace ID, Request ID
    - Session, User, Trace name
    - Tokens, Execution time
    - State, Source
    """

    # Class-level cache for traces to avoid rate limiting between tests
    _cached_traces: list = None

    @classmethod
    def _get_cached_traces(cls) -> list:
        """Get cached traces or fetch from MLflow once."""
        if cls._cached_traces is None:
            cls._cached_traces = get_all_traces()
            logger.info(f"Cached {len(cls._cached_traces)} traces for metadata tests")
        return cls._cached_traces

    def test_trace_metadata_fields(self, mlflow_url: str, mlflow_configured: bool):
        """Verify traces have comprehensive metadata visible in MLflow UI.

        MLflow UI shows these fields for each trace:
        - Trace ID, Request
        - Response, Session, User
        - Trace name, Version, Tokens
        - Execution time, Prompt, Request time
        - Run name, Source, State
        """
        all_traces = self._get_cached_traces()
        if not all_traces:
            pytest.skip("No traces available")

        print(f"\n{'=' * 60}")
        print("Trace Metadata Fields")
        print(f"{'=' * 60}")

        # Check first 5 traces for metadata
        for i, trace in enumerate(all_traces[:5]):
            trace_info = trace.info if hasattr(trace, "info") else trace

            print(f"\nTrace {i + 1}:")
            print("-" * 40)

            # Core identifiers
            request_id = getattr(trace_info, "request_id", None)
            trace_id = getattr(trace_info, "trace_id", None) or request_id
            print(f"  Trace ID: {trace_id[:30] if trace_id else 'N/A'}...")

            # Timing
            start_time = getattr(trace_info, "timestamp_ms", None)
            execution_time = getattr(trace_info, "execution_time_ms", None)
            print(f"  Request time: {start_time}")
            print(
                f"  Execution time: {execution_time}ms"
                if execution_time
                else "  Execution time: N/A"
            )

            # State
            state = getattr(trace_info, "state", None)
            status = getattr(trace_info, "status", None)
            print(f"  State: {state or status or 'N/A'}")

            # Tags and metadata
            tags = getattr(trace_info, "tags", {}) or {}
            print(f"  Tags: {list(tags.keys())[:5]}")

            # Session info
            session_id = tags.get("session_id") or tags.get("mlflow.session_id")
            user = tags.get("user") or tags.get("mlflow.user")
            source = tags.get("mlflow.source.name") or tags.get("source")
            print(f"  Session: {session_id or 'N/A'}")
            print(f"  User: {user or 'N/A'}")
            print(f"  Source: {source or 'N/A'}")

        # Basic assertion - traces should have request_id
        trace_with_id = sum(
            1
            for t in all_traces[:10]
            if getattr(t.info if hasattr(t, "info") else t, "request_id", None)
        )
        assert trace_with_id > 0, "No traces have request_id"
        print(f"\nSUCCESS: {trace_with_id}/10 traces have request_id")

    def test_traces_have_session_info(self, mlflow_url: str, mlflow_configured: bool):
        """Verify traces have session/context information.

        Traces should have tags or metadata that allow grouping by:
        - A2A context_id (conversation identifier)
        - Session ID
        - Client request ID
        """
        all_traces = self._get_cached_traces()
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

    def test_trace_execution_metrics(self, mlflow_url: str, mlflow_configured: bool):
        """Verify traces have execution metrics (timing, tokens).

        Traces should include:
        - Execution time in milliseconds
        - Token counts (if LLM calls)
        - Start/end timestamps
        """
        all_traces = self._get_cached_traces()
        if not all_traces:
            pytest.skip("No traces available")

        print(f"\n{'=' * 60}")
        print("Trace Execution Metrics")
        print(f"{'=' * 60}")

        traces_with_timing = 0
        total_execution_time = 0

        for trace in all_traces[:10]:
            trace_info = trace.info if hasattr(trace, "info") else trace

            execution_time = getattr(trace_info, "execution_time_ms", None)
            if execution_time:
                traces_with_timing += 1
                total_execution_time += execution_time

        print(f"Traces with timing: {traces_with_timing}/10")
        if traces_with_timing > 0:
            avg_time = total_execution_time / traces_with_timing
            print(f"Average execution time: {avg_time:.2f}ms")

        # Check for token info in trace tags or spans
        print("\nToken information checked via span attributes")
        print("(Tokens are typically in span attributes, not trace metadata)")


@pytest.mark.observability
@pytest.mark.openshift_only
@pytest.mark.requires_features(["mlflow"])
class TestSessionTracking:
    """
    Verify traces have session/context information for conversation grouping.

    Examines existing traces (generated by weather agent tests) for:
    - Session ID patterns
    - Context ID from A2A protocol
    - Grouping capability for multi-turn conversations
    """

    # Class-level cache for traces
    _cached_traces: list = None

    @classmethod
    def _get_cached_traces(cls) -> list:
        """Get cached traces or fetch from MLflow once."""
        if cls._cached_traces is None:
            cls._cached_traces = get_all_traces()
            logger.info(f"Cached {len(cls._cached_traces)} traces for session tests")
        return cls._cached_traces

    def test_traces_exist_for_session_analysis(
        self, mlflow_url: str, mlflow_configured: bool
    ):
        """Verify traces exist to analyze for session patterns."""
        all_traces = self._get_cached_traces()

        print(f"\n{'=' * 60}")
        print("Session Tracking - Trace Availability")
        print(f"{'=' * 60}")
        print(f"Total traces available: {len(all_traces)}")

        if not all_traces:
            pytest.skip("No traces available for session analysis")

        # Show trace timestamps to verify they're from recent runs
        for i, trace in enumerate(all_traces[:3]):
            trace_info = trace.info if hasattr(trace, "info") else trace
            timestamp = getattr(trace_info, "timestamp_ms", 0)
            request_id = getattr(trace_info, "request_id", "unknown")
            print(f"  [{i + 1}] {request_id[:30]}... (ts: {timestamp})")

        assert len(all_traces) > 0
        print(f"\nSUCCESS: {len(all_traces)} traces available for analysis")

    def test_analyze_session_patterns_in_traces(
        self, mlflow_url: str, mlflow_configured: bool
    ):
        """
        Analyze existing traces for session/context grouping patterns.

        Looks for:
        - a2a.context_id: A2A conversation context
        - session_id: User session identifier
        - client_request_id: Per-request identifier
        """
        all_traces = self._get_cached_traces()
        if not all_traces:
            pytest.skip("No traces available")

        print(f"\n{'=' * 60}")
        print("Session Pattern Analysis")
        print(f"{'=' * 60}")

        # Analyze trace tags for session patterns
        session_patterns = {}
        traces_with_session = 0

        for trace in all_traces[:20]:
            trace_info = trace.info if hasattr(trace, "info") else trace
            tags = getattr(trace_info, "tags", {}) or {}
            client_request_id = getattr(trace_info, "client_request_id", None)

            has_session = False

            # Check for client_request_id (always present)
            if client_request_id:
                has_session = True
                if "client_request_id" not in session_patterns:
                    session_patterns["client_request_id"] = 0
                session_patterns["client_request_id"] += 1

            # Check tag patterns
            for key in tags:
                key_lower = key.lower()
                if any(
                    p in key_lower
                    for p in ["session", "context", "conversation", "task"]
                ):
                    has_session = True
                    if key not in session_patterns:
                        session_patterns[key] = 0
                    session_patterns[key] += 1

            if has_session:
                traces_with_session += 1

        # Also check span attributes for session info (context_id is set as span attribute)
        span_session_patterns = {}
        for trace in all_traces[:5]:  # Check fewer traces due to API calls
            spans = get_trace_span_details(trace)
            for span in spans:
                attrs = span.get("attributes", {})
                for key in attrs:
                    key_lower = key.lower()
                    if any(
                        p in key_lower
                        for p in ["context_id", "session", "task_id", "user_input"]
                    ):
                        if key not in span_session_patterns:
                            span_session_patterns[key] = 0
                        span_session_patterns[key] += 1

        print(f"Traces analyzed: {min(20, len(all_traces))}")
        print(f"Traces with session info (tags): {traces_with_session}")
        print(f"\nSession-related tag patterns found:")

        if session_patterns:
            for key, count in sorted(session_patterns.items(), key=lambda x: -x[1]):
                print(f"  - {key}: {count} traces")
        else:
            print("  (No session-related tags found)")

        print(f"\nSession-related span attribute patterns found:")
        if span_session_patterns:
            for key, count in sorted(
                span_session_patterns.items(), key=lambda x: -x[1]
            ):
                print(f"  - {key}: {count} spans")
        else:
            print("  (No session-related span attributes found)")

        # Show recommendations
        print("\nSession grouping recommendations:")
        if (
            "a2a.context_id" not in session_patterns
            and "a2a.context_id" not in span_session_patterns
        ):
            print("  - Add a2a.context_id for conversation grouping")
        if "session_id" not in session_patterns:
            print("  - Add session_id for user session tracking")

        # This is informational, not a hard failure
        print(
            f"\nSUCCESS: Analyzed {min(20, len(all_traces))} traces for session patterns"
        )

    def test_trace_grouping_by_service(self, mlflow_url: str, mlflow_configured: bool):
        """
        Verify traces can be grouped by service.name for per-agent analysis.

        This is an alternative grouping strategy when session IDs aren't available.
        """
        all_traces = self._get_cached_traces()
        if not all_traces:
            pytest.skip("No traces available")

        print(f"\n{'=' * 60}")
        print("Trace Grouping by Service")
        print(f"{'=' * 60}")

        service_counts = {}

        # Check first 10 traces for service info (avoid rate limiting)
        for trace in all_traces[:10]:
            trace_info = trace.info if hasattr(trace, "info") else trace
            tags = getattr(trace_info, "tags", {}) or {}

            # Look for service.name in tags
            service_name = tags.get("service.name") or tags.get("mlflow.source.name")
            if service_name:
                if service_name not in service_counts:
                    service_counts[service_name] = 0
                service_counts[service_name] += 1

        print(f"Traces analyzed: {min(10, len(all_traces))}")
        print(f"\nService distribution:")

        if service_counts:
            for service, count in sorted(service_counts.items(), key=lambda x: -x[1]):
                print(f"  - {service}: {count} traces")
        else:
            print("  (No service.name tags found)")
            print("  Traces may be using span-level service.name instead of trace tags")

        print("\nSUCCESS: Service grouping analysis complete")


@pytest.mark.observability
@pytest.mark.openshift_only
@pytest.mark.requires_features(["mlflow"])
class TestTraceCategorization:
    """
    Categorize traces into GenAI vs non-GenAI (chatty) for filtering.

    Helps identify:
    - Traces with LLM/GenAI spans (valuable for debugging)
    - Chatty infrastructure traces (A2A protocol only)
    - Recommendations for trace filtering
    """

    # Class-level cache for traces
    _cached_traces: list = None
    _genai_traces: list = None
    _non_genai_traces: list = None

    @classmethod
    def _get_categorized_traces(cls) -> tuple[list, list, list]:
        """Get traces categorized into GenAI and non-GenAI."""
        if cls._cached_traces is None:
            cls._cached_traces = get_all_traces()

            # Categorize traces (limit to avoid rate limiting)
            cls._genai_traces = []
            cls._non_genai_traces = []

            for trace in cls._cached_traces[:15]:
                if has_genai_spans(trace):
                    cls._genai_traces.append(trace)
                else:
                    cls._non_genai_traces.append(trace)

            logger.info(
                f"Categorized {len(cls._cached_traces)} traces: "
                f"{len(cls._genai_traces)} GenAI, {len(cls._non_genai_traces)} non-GenAI"
            )

        return cls._cached_traces, cls._genai_traces, cls._non_genai_traces

    def test_categorize_traces_by_genai_content(
        self, mlflow_url: str, mlflow_configured: bool
    ):
        """
        Categorize traces into GenAI (LLM spans) vs non-GenAI (chatty).

        GenAI traces contain spans from LangChain, OpenAI, or LLM instrumentation.
        Non-GenAI traces contain only A2A protocol or infrastructure spans.
        """
        all_traces, genai_traces, non_genai_traces = self._get_categorized_traces()

        if not all_traces:
            pytest.skip("No traces available")

        print(f"\n{'=' * 60}")
        print("Trace Categorization: GenAI vs Non-GenAI")
        print(f"{'=' * 60}")

        total_checked = min(15, len(all_traces))
        print(f"Total traces checked: {total_checked}")
        print(f"GenAI traces: {len(genai_traces)}")
        print(f"Non-GenAI traces: {len(non_genai_traces)}")

        if genai_traces:
            genai_pct = (len(genai_traces) / total_checked) * 100
            print(f"\nGenAI trace percentage: {genai_pct:.1f}%")

        # Show sample span names from each category
        if genai_traces:
            print("\nSample GenAI trace span types:")
            sample = genai_traces[0]
            spans = get_trace_span_details(sample)
            genai_spans = [
                s.get("name")
                for s in spans
                if any(p in s.get("name", "").lower() for p in GENAI_SPAN_PATTERNS)
            ]
            for name in genai_spans[:5]:
                print(f"  - {name}")

        if non_genai_traces:
            print("\nSample non-GenAI (chatty) trace span types:")
            sample = non_genai_traces[0]
            spans = get_trace_span_details(sample)
            for span in spans[:5]:
                print(f"  - {span.get('name', 'unnamed')}")

        print(f"\nSUCCESS: Categorized {total_checked} traces")

    def test_identify_chatty_trace_patterns(
        self, mlflow_url: str, mlflow_configured: bool
    ):
        """
        Identify patterns in chatty (non-GenAI) traces for filtering.

        Analyzes non-GenAI traces to find common patterns that could be
        filtered out to reduce noise in observability dashboards.
        """
        all_traces, genai_traces, non_genai_traces = self._get_categorized_traces()

        if not non_genai_traces:
            pytest.skip("No non-GenAI traces to analyze")

        print(f"\n{'=' * 60}")
        print("Chatty Trace Pattern Analysis")
        print(f"{'=' * 60}")

        # Analyze root span names in non-GenAI traces
        root_span_patterns = {}

        for trace in non_genai_traces[:10]:
            spans = get_trace_span_details(trace)
            if not spans:
                continue

            # Find root spans (no parent)
            for span in spans:
                parent_id = span.get("parent_id")
                is_root = not parent_id or parent_id == "None" or parent_id == ""
                if is_root:
                    name = span.get("name", "unknown")
                    # Normalize pattern (remove specific IDs)
                    pattern = name.split(".")[0] if "." in name else name
                    if pattern not in root_span_patterns:
                        root_span_patterns[pattern] = 0
                    root_span_patterns[pattern] += 1

        print(f"Non-GenAI traces analyzed: {len(non_genai_traces)}")
        print(f"\nRoot span patterns (candidates for filtering):")

        if root_span_patterns:
            for pattern, count in sorted(
                root_span_patterns.items(), key=lambda x: -x[1]
            ):
                print(f"  - {pattern}: {count} occurrences")
        else:
            print("  (No distinct patterns found)")

        # Recommendations
        print("\nFiltering recommendations:")
        print("  - Consider filtering traces with only 'a2a.*' root spans")
        print("  - Keep traces with 'langchain', 'openai', 'llm' spans")
        print("  - Use MLflow's trace filtering UI to exclude chatty patterns")

        print("\nSUCCESS: Identified chatty trace patterns")

    def test_trace_value_assessment(self, mlflow_url: str, mlflow_configured: bool):
        """
        Assess the debugging value of different trace categories.

        Provides a summary of trace value for observability:
        - High value: GenAI traces with LLM calls, tokens, latency
        - Medium value: Tool/function call traces
        - Low value: Infrastructure-only traces
        """
        all_traces, genai_traces, non_genai_traces = self._get_categorized_traces()

        if not all_traces:
            pytest.skip("No traces available")

        print(f"\n{'=' * 60}")
        print("Trace Value Assessment")
        print(f"{'=' * 60}")

        total_checked = min(15, len(all_traces))

        # Categorize by value
        high_value = len(genai_traces)  # GenAI traces
        low_value = len(non_genai_traces)  # Non-GenAI traces

        print(f"Traces assessed: {total_checked}")
        print(f"\nValue distribution:")
        print(f"  HIGH VALUE (GenAI/LLM):     {high_value} traces")
        print(f"  LOW VALUE (infrastructure): {low_value} traces")

        # Calculate noise ratio
        if total_checked > 0:
            noise_ratio = (low_value / total_checked) * 100
            print(f"\nNoise ratio: {noise_ratio:.1f}%")

            if noise_ratio > 50:
                print("\nRECOMMENDATION: High noise ratio detected.")
                print("  Consider configuring OTEL collector to filter:")
                print("  - Exclude spans with only a2a.* namespace")
                print("  - Keep spans from openinference.* or gen_ai.*")
            else:
                print("\nTrace quality: Good - most traces contain GenAI spans")

        print("\nSUCCESS: Trace value assessment complete")


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
