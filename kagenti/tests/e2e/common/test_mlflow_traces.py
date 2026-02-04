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
from typing import Any, Callable

import pytest

logger = logging.getLogger(__name__)


# =============================================================================
# Trace Waiting with Exponential Backoff
# =============================================================================


def wait_for_traces(
    check_fn: Callable[[], list],
    min_count: int = 1,
    timeout_seconds: int = 60,
    poll_interval: float = 2.0,
    backoff_factor: float = 1.5,
    max_interval: float = 10.0,
    description: str = "traces",
) -> list:
    """Wait for traces to appear in MLflow with exponential backoff.

    Args:
        check_fn: Function that returns list of traces to check
        min_count: Minimum number of traces required
        timeout_seconds: Maximum time to wait
        poll_interval: Initial polling interval
        backoff_factor: Multiplier for interval after each attempt
        max_interval: Maximum polling interval
        description: Description for logging

    Returns:
        List of traces found

    Raises:
        TimeoutError: If traces don't appear within timeout
    """
    start_time = time.time()
    current_interval = poll_interval
    attempt = 0

    while time.time() - start_time < timeout_seconds:
        attempt += 1
        try:
            traces = check_fn()
            if len(traces) >= min_count:
                logger.info(
                    f"Found {len(traces)} {description} after {attempt} attempts "
                    f"({time.time() - start_time:.1f}s)"
                )
                return traces

            logger.info(
                f"Attempt {attempt}: Found {len(traces)} {description}, "
                f"waiting for {min_count}... (next check in {current_interval:.1f}s)"
            )
        except Exception as e:
            logger.warning(f"Attempt {attempt}: Error checking {description}: {e}")

        time.sleep(current_interval)
        current_interval = min(current_interval * backoff_factor, max_interval)

    elapsed = time.time() - start_time
    raise TimeoutError(
        f"Timed out waiting for {min_count} {description} after {elapsed:.1f}s "
        f"({attempt} attempts). OTEL collector may not be forwarding traces to MLflow."
    )


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

# Token refresh state
_token_credentials: dict = {}  # Stores client_id, client_secret, token_url, ssl_verify
_token_issued_at: float = 0  # Time when token was issued
_token_expires_in: int = 60  # Token lifetime in seconds
TOKEN_REFRESH_MARGIN = 10  # Refresh token 10 seconds before expiry


def _refresh_mlflow_token() -> bool:
    """Refresh the MLflow tracking token if it's about to expire.

    Returns True if token was refreshed or still valid, False on error.
    """
    global _token_issued_at, _token_expires_in

    # Check if we have credentials to refresh
    if not _token_credentials:
        logger.warning("No token credentials available for refresh")
        return False

    # Check if token needs refresh
    elapsed = time.time() - _token_issued_at
    if elapsed < (_token_expires_in - TOKEN_REFRESH_MARGIN):
        # Token is still valid
        return True

    logger.info(f"Token expired or expiring (elapsed: {elapsed:.0f}s), refreshing...")

    try:
        import requests

        response = requests.post(
            _token_credentials["token_url"],
            data={
                "grant_type": "client_credentials",
                "client_id": _token_credentials["client_id"],
                "client_secret": _token_credentials["client_secret"],
            },
            timeout=10,
            verify=_token_credentials.get("ssl_verify", False),
        )

        if response.status_code == 200:
            token_data = response.json()
            new_token = token_data.get("access_token")
            _token_expires_in = token_data.get("expires_in", 60)
            _token_issued_at = time.time()

            # Update the environment variable for MLflow client
            os.environ["MLFLOW_TRACKING_TOKEN"] = new_token

            logger.info(f"Token refreshed (expires in {_token_expires_in}s)")
            return True
        else:
            logger.error(f"Failed to refresh token: {response.status_code}")
            return False

    except Exception as e:
        logger.error(f"Error refreshing token: {e}")
        return False


def get_mlflow_client():
    """Get or create a shared MLflow client.

    Uses a module-level cached client to avoid creating multiple instances
    which can cause rate limiting issues.

    Automatically refreshes the auth token if it's about to expire.

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

    # Refresh token if needed (before checking if it's set)
    if _token_credentials:
        _refresh_mlflow_token()

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
        pytest.fail(
            "MLflow URL not available. "
            "Set MLFLOW_URL env var or ensure mlflow route exists in kagenti-system."
        )
    return url


@pytest.fixture(scope="module")
def mlflow_client_token(k8s_client, is_openshift, openshift_ingress_ca):
    """Get OAuth2 token for MLflow using client credentials flow.

    Reads MLflow OAuth secret from K8s and uses client credentials grant
    to get an access token. This is required because mlflow-oidc-auth needs
    a token issued for the 'mlflow' client, not 'admin-cli'.

    Also stores credentials for automatic token refresh during long test runs.

    Returns:
        str: Access token, or None if auth is not configured
    """
    global _token_credentials, _token_issued_at, _token_expires_in

    import base64

    import requests
    import urllib3
    from kubernetes.client.rest import ApiException

    # Use CA file if available, otherwise disable warnings for self-signed certs
    ssl_verify = openshift_ingress_ca if openshift_ingress_ca else False
    if is_openshift and not openshift_ingress_ca:
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    try:
        # Get MLflow OAuth secret
        secret = k8s_client.read_namespaced_secret(
            name="mlflow-oauth-secret", namespace="kagenti-system"
        )

        client_id = base64.b64decode(secret.data["OIDC_CLIENT_ID"]).decode()
        client_secret = base64.b64decode(secret.data["OIDC_CLIENT_SECRET"]).decode()
        token_url = base64.b64decode(secret.data["OIDC_TOKEN_URL"]).decode()

        # If token_url is an internal cluster URL, use external Keycloak route instead
        # This happens when tests run from outside the cluster (e.g., developer laptop)
        if "keycloak-service.keycloak" in token_url or ".svc" in token_url:
            logger.info(f"Internal token URL detected: {token_url}")
            try:
                # Get external Keycloak route from OpenShift
                from kubernetes.client import CustomObjectsApi

                custom_api = CustomObjectsApi()
                route = custom_api.get_namespaced_custom_object(
                    group="route.openshift.io",
                    version="v1",
                    namespace="keycloak",
                    plural="routes",
                    name="keycloak",
                )
                keycloak_host = route["spec"]["host"]
                # Extract the path from internal URL (e.g., /realms/master/protocol/...)
                from urllib.parse import urlparse

                parsed = urlparse(token_url)
                token_url = f"https://{keycloak_host}{parsed.path}"
                logger.info(f"Using external Keycloak route: {token_url}")
            except Exception as e:
                logger.warning(f"Could not get Keycloak route, using internal URL: {e}")

        logger.info(f"Getting MLflow token from: {token_url}")

        # Store credentials for automatic token refresh
        _token_credentials = {
            "client_id": client_id,
            "client_secret": client_secret,
            "token_url": token_url,
            "ssl_verify": ssl_verify,
        }

        # Get token using client credentials flow
        response = requests.post(
            token_url,
            data={
                "grant_type": "client_credentials",
                "client_id": client_id,
                "client_secret": client_secret,
            },
            timeout=10,
            verify=ssl_verify,
        )

        if response.status_code == 200:
            token_data = response.json()
            _token_expires_in = token_data.get("expires_in", 60)
            _token_issued_at = time.time()
            logger.info(f"Got MLflow client token (expires in {_token_expires_in}s)")
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
        pytest.fail(
            "Failed to get MLflow OAuth token from Keycloak. "
            "Check that mlflow-oauth-secret exists in kagenti-system and "
            "Keycloak is accessible. Auth must work for tests to run."
        )

    if not setup_mlflow_client(mlflow_url):
        pytest.fail(
            "Failed to configure MLflow client. "
            "Check MLflow URL and network connectivity."
        )

    # Verify token is set by re-checking
    token = os.environ.get("MLFLOW_TRACKING_TOKEN", "")
    logger.info(f"MLFLOW_TRACKING_TOKEN set: {bool(token)} (length: {len(token)})")

    return True


@pytest.fixture(scope="module")
def traces_available(mlflow_configured):
    """Wait for traces to be available in MLflow before running trace tests.

    This fixture ensures that:
    1. OTEL collector has time to batch and forward traces
    2. MLflow has ingested the traces
    3. Tests don't fail due to timing issues

    Uses exponential backoff to avoid overwhelming MLflow API.
    Module-scoped so it only runs once for all test classes.
    """
    logger.info("Waiting for traces to appear in MLflow...")

    try:
        traces = wait_for_traces(
            check_fn=get_all_traces,
            min_count=1,
            timeout_seconds=30,
            poll_interval=2.0,
            backoff_factor=1.5,
            description="traces in MLflow",
        )
        logger.info(f"Found {len(traces)} traces, proceeding with tests")
        return traces
    except TimeoutError as e:
        pytest.fail(
            f"No traces appeared in MLflow after waiting: {e}\n\n"
            "Possible causes:\n"
            "  1. Weather agent conversation tests didn't run first\n"
            "  2. OTEL collector not forwarding to MLflow\n"
            "  3. MLflow OTLP endpoint not configured correctly"
        )


@pytest.mark.observability
@pytest.mark.requires_features(["mlflow"])
class TestMLflowConnectivity:
    """Test MLflow service is accessible."""

    def test_mlflow_accessible(
        self, mlflow_url: str, mlflow_configured: bool, openshift_ingress_ca
    ):
        """Verify MLflow is accessible."""
        import httpx

        # Use CA file if available, otherwise disable verification
        ssl_verify = openshift_ingress_ca if openshift_ingress_ca else False

        try:
            response = httpx.get(
                f"{mlflow_url}/version", verify=ssl_verify, timeout=30.0
            )
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

    def test_mlflow_has_traces(
        self, mlflow_url: str, mlflow_configured: bool, traces_available: list
    ):
        """Verify MLflow received traces from E2E tests."""
        # traces_available fixture already waited for traces with backoff
        traces = traces_available
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

    # First pass: collect all span_ids
    all_span_ids = {span.get("span_id") for span in spans if span.get("span_id")}

    for span in spans:
        span_id = span.get("span_id")
        parent_id = span.get("parent_id")

        # MLflow span.parent_id can be None, "None" (string), empty string, or
        # the OpenTelemetry INVALID_SPAN_ID (16 zeros) for root spans.
        # Also treat spans as root if parent_id points to a span NOT in this trace
        # (e.g., parent is in A2A framework trace that was broken).
        is_explicitly_root = (
            not parent_id
            or parent_id == "None"
            or parent_id == ""
            or parent_id == "0000000000000000"
            or (parent_id and parent_id not in all_span_ids)
        )
        if is_explicitly_root:
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
    def _get_cached_traces(cls, traces_from_fixture: list = None) -> tuple[list, list]:
        """Get cached traces or use traces from fixture."""
        if cls._cached_traces is None:
            if traces_from_fixture:
                cls._cached_traces = traces_from_fixture
            else:
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
            pytest.fail(
                "No traces available to check structure. "
                "Ensure conversation tests ran first and MLflow auth is working."
            )

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
                pytest.fail("No candidate traces available - auth or API issue")

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
            pytest.fail(
                "Could not retrieve span details for trace. "
                "This may be due to API rate limiting or auth issues. "
                "Fix the auth/API issue - do not skip this test."
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
                pytest.fail(
                    "Could not retrieve span details for trace. "
                    "This may be due to API rate limiting or auth issues. "
                    "Fix the auth/API issue - do not skip this test."
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
    def _get_cached_traces(cls, traces_from_fixture: list = None) -> list:
        """Get cached traces or use traces from fixture."""
        if cls._cached_traces is None:
            if traces_from_fixture:
                cls._cached_traces = traces_from_fixture
            else:
                cls._cached_traces = get_all_traces()
            logger.info(f"Cached {len(cls._cached_traces)} traces for metadata tests")
        return cls._cached_traces

    def test_trace_metadata_fields(
        self, mlflow_url: str, mlflow_configured: bool, traces_available: list
    ):
        """Verify traces have comprehensive metadata visible in MLflow UI.

        MLflow UI shows these fields for each trace:
        - Trace ID, Request
        - Response, Session, User
        - Trace name, Version, Tokens
        - Execution time, Prompt, Request time
        - Run name, Source, State
        """
        all_traces = self._get_cached_traces(traces_available)
        if not all_traces:
            pytest.fail(
                "No traces available - ensure conversation tests ran first and auth is working"
            )

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

    def test_traces_have_session_info(
        self, mlflow_url: str, mlflow_configured: bool, traces_available: list
    ):
        """Verify traces have session/context information.

        Traces should have tags or metadata that allow grouping by:
        - A2A context_id (conversation identifier)
        - Session ID
        - Client request ID
        """
        all_traces = self._get_cached_traces(traces_available)
        if not all_traces:
            pytest.fail(
                "No traces available - ensure conversation tests ran first and auth is working"
            )

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

    def test_trace_execution_metrics(
        self, mlflow_url: str, mlflow_configured: bool, traces_available: list
    ):
        """Verify traces have execution metrics (timing, tokens).

        Traces should include:
        - Execution time in milliseconds
        - Token counts (if LLM calls)
        - Start/end timestamps
        """
        all_traces = self._get_cached_traces(traces_available)
        if not all_traces:
            pytest.fail(
                "No traces available - ensure conversation tests ran first and auth is working"
            )

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
    _cached_genai_traces: list = None

    @classmethod
    def _get_cached_traces(cls, traces_from_fixture: list = None) -> tuple[list, list]:
        """Get cached traces or use traces from fixture.

        Returns:
            Tuple of (all_traces, genai_traces) where genai_traces are filtered
            to only include traces with GenAI spans.
        """
        if cls._cached_traces is None:
            if traces_from_fixture:
                cls._cached_traces = traces_from_fixture
            else:
                cls._cached_traces = get_all_traces()
            # Filter for GenAI traces - these are the ones with gen_ai.* attributes
            cls._cached_genai_traces = [
                t for t in cls._cached_traces if has_genai_spans(t)
            ]
            logger.info(
                f"Cached {len(cls._cached_traces)} traces, "
                f"{len(cls._cached_genai_traces)} GenAI traces for session tests"
            )
        return cls._cached_traces, cls._cached_genai_traces

    def test_traces_exist_for_session_analysis(
        self, mlflow_url: str, mlflow_configured: bool, traces_available: list
    ):
        """Verify traces exist to analyze for session patterns."""
        all_traces, genai_traces = self._get_cached_traces(traces_available)

        print(f"\n{'=' * 60}")
        print("Session Tracking - Trace Availability")
        print(f"{'=' * 60}")
        print(f"Total traces available: {len(all_traces)}")
        print(f"GenAI traces available: {len(genai_traces)}")

        if not all_traces:
            pytest.fail(
                "No traces available for session analysis - ensure tests ran first"
            )

        # Show trace timestamps to verify they're from recent runs
        for i, trace in enumerate(all_traces[:3]):
            trace_info = trace.info if hasattr(trace, "info") else trace
            timestamp = getattr(trace_info, "timestamp_ms", 0)
            request_id = getattr(trace_info, "request_id", "unknown")
            print(f"  [{i + 1}] {request_id[:30]}... (ts: {timestamp})")

        assert len(all_traces) > 0
        print(f"\nSUCCESS: {len(all_traces)} traces available for analysis")

    def test_traces_have_genai_conversation_id(
        self, mlflow_url: str, mlflow_configured: bool, traces_available: list
    ):
        """
        Assert traces have gen_ai.conversation.id for session tracking.

        This is the standard GenAI semantic convention attribute that enables
        MLflow to group traces by conversation/session.

        NOTE: Due to MLflow async trace hierarchy flattening (see GitHub issue #16880),
        GenAI spans may be in separate traces from A2A framework spans. This test
        specifically checks GenAI traces, not all traces.
        """
        all_traces, genai_traces = self._get_cached_traces(traces_available)
        if not all_traces:
            pytest.fail(
                "No traces available - ensure conversation tests ran first and auth is working"
            )

        print(f"\n{'=' * 60}")
        print("GenAI Conversation ID Check")
        print(f"{'=' * 60}")
        print(f"Total traces: {len(all_traces)}")
        print(f"GenAI traces: {len(genai_traces)}")

        # Check GenAI traces specifically - these are the ones that should have
        # gen_ai.conversation.id set. Due to MLflow's async trace flattening,
        # A2A framework traces won't have these attributes.
        traces_to_check = genai_traces if genai_traces else all_traces[:10]

        # Check span attributes for gen_ai.conversation.id
        traces_with_conversation_id = 0
        conversation_ids_found = set()

        for trace in traces_to_check[:10]:  # Check first 10 GenAI traces
            spans = get_trace_span_details(trace)
            for span in spans:
                attrs = span.get("attributes", {})
                conversation_id = attrs.get("gen_ai.conversation.id")
                if conversation_id:
                    traces_with_conversation_id += 1
                    conversation_ids_found.add(conversation_id)
                    break  # Found in this trace, move to next

        print(f"GenAI traces checked: {min(10, len(traces_to_check))}")
        print(f"Traces with gen_ai.conversation.id: {traces_with_conversation_id}")
        print(f"Unique conversation IDs: {len(conversation_ids_found)}")

        if conversation_ids_found:
            print(f"Sample IDs: {list(conversation_ids_found)[:3]}")

        # ASSERT: At least one GenAI trace must have gen_ai.conversation.id
        assert traces_with_conversation_id > 0, (
            "No GenAI traces found with gen_ai.conversation.id attribute. "
            f"Checked {len(traces_to_check)} GenAI traces out of {len(all_traces)} total. "
            "Weather agent should set this attribute for MLflow session tracking. "
            "Ensure the weather agent is using GenAI semantic conventions."
        )

        print(
            f"\nSUCCESS: Found {traces_with_conversation_id} traces with conversation ID"
        )

    def test_trace_grouping_by_service(
        self, mlflow_url: str, mlflow_configured: bool, traces_available: list
    ):
        """
        Verify traces can be grouped by service.name for per-agent analysis.

        This is an alternative grouping strategy when session IDs aren't available.
        """
        all_traces, genai_traces = self._get_cached_traces(traces_available)
        if not all_traces:
            pytest.fail(
                "No traces available - ensure conversation tests ran first and auth is working"
            )

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
    def _get_categorized_traces(
        cls, traces_from_fixture: list = None
    ) -> tuple[list, list, list]:
        """Get traces categorized into GenAI and non-GenAI."""
        if cls._cached_traces is None:
            if traces_from_fixture:
                cls._cached_traces = traces_from_fixture
            else:
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
        self, mlflow_url: str, mlflow_configured: bool, traces_available: list
    ):
        """
        Categorize traces into GenAI (LLM spans) vs non-GenAI (chatty).

        GenAI traces contain spans from LangChain, OpenAI, or LLM instrumentation.
        Non-GenAI traces contain only A2A protocol or infrastructure spans.
        """
        all_traces, genai_traces, non_genai_traces = self._get_categorized_traces(
            traces_available
        )

        if not all_traces:
            pytest.fail(
                "No traces available - ensure conversation tests ran first and auth is working"
            )

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

    def test_trace_value_assessment(
        self, mlflow_url: str, mlflow_configured: bool, traces_available: list
    ):
        """
        Assess the debugging value of different trace categories.

        Provides a summary of trace value for observability:
        - High value: GenAI traces with LLM calls, tokens, latency
        - Medium value: Tool/function call traces
        - Low value: Infrastructure-only traces
        """
        all_traces, genai_traces, non_genai_traces = self._get_categorized_traces(
            traces_available
        )

        if not all_traces:
            pytest.fail(
                "No traces available - ensure conversation tests ran first and auth is working"
            )

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


@pytest.mark.observability
@pytest.mark.openshift_only
@pytest.mark.requires_features(["mlflow"])
class TestRootSpanAttributes:
    """
    Verify root spans have required attributes for MLflow and Phoenix.

    Root spans should have:
    - MLflow metadata: mlflow.spanInputs, mlflow.spanOutputs, mlflow.user, etc.
    - OpenInference: input.value, output.value, openinference.span.kind
    - GenAI conventions: gen_ai.conversation.id, gen_ai.agent.name
    """

    # Class-level cache for traces
    _cached_traces: list = None
    _cached_genai_traces: list = None

    @classmethod
    def _get_cached_traces(cls, traces_from_fixture: list = None) -> tuple[list, list]:
        """Get cached traces or use traces from fixture."""
        if cls._cached_traces is None:
            if traces_from_fixture:
                cls._cached_traces = traces_from_fixture
            else:
                cls._cached_traces = get_all_traces()
            # Filter for GenAI traces
            cls._cached_genai_traces = [
                t for t in cls._cached_traces if has_genai_spans(t)
            ]
            logger.info(
                f"Cached {len(cls._cached_traces)} traces, "
                f"{len(cls._cached_genai_traces)} GenAI traces for root span tests"
            )
        return cls._cached_traces, cls._cached_genai_traces

    def _get_root_span(self, trace: Any) -> dict | None:
        """Get the root span from a trace.

        The root span is either:
        - A span with no parent_id
        - A span named 'gen_ai.agent.invoke' (our middleware root)
        """
        spans = get_trace_span_details(trace)
        if not spans:
            return None

        # First, look for our middleware root span by name
        for span in spans:
            if span.get("name") == "gen_ai.agent.invoke":
                return span

        # Build tree structure to find root
        tree = get_trace_tree_structure(trace)
        root_spans = tree.get("root_spans", [])

        # Return first root span
        return root_spans[0] if root_spans else None

    def test_root_span_has_mlflow_attributes(
        self, mlflow_url: str, mlflow_configured: bool, traces_available: list
    ):
        """
        Verify root span has MLflow-specific attributes.

        Required MLflow attributes:
        - mlflow.spanInputs: Captured input to the agent
        - mlflow.spanOutputs: Captured output from the agent
        - mlflow.user: User identifier (default: 'kagenti')
        - mlflow.traceName: Name of the trace/agent
        - mlflow.version: Agent version
        - mlflow.runName: Run identifier
        """
        all_traces, genai_traces = self._get_cached_traces(traces_available)
        if not genai_traces:
            pytest.fail(
                "No GenAI traces available - ensure conversation tests ran first"
            )

        print(f"\n{'=' * 60}")
        print("Root Span MLflow Attributes")
        print(f"{'=' * 60}")

        # Required attributes for MLflow display
        mlflow_attrs = [
            "mlflow.spanInputs",
            "mlflow.spanOutputs",
            "mlflow.user",
            "mlflow.traceName",
            "mlflow.version",
            "mlflow.runName",
        ]

        traces_checked = 0
        traces_with_all_attrs = 0
        attr_counts = {attr: 0 for attr in mlflow_attrs}
        missing_by_trace = []

        # Check GenAI traces (max 10)
        for trace in genai_traces[:10]:
            root_span = self._get_root_span(trace)
            if not root_span:
                continue

            traces_checked += 1
            attrs = root_span.get("attributes", {})
            trace_missing = []

            for attr in mlflow_attrs:
                if attr in attrs and attrs[attr]:
                    attr_counts[attr] += 1
                else:
                    trace_missing.append(attr)

            if not trace_missing:
                traces_with_all_attrs += 1
            else:
                trace_info = trace.info if hasattr(trace, "info") else trace
                request_id = getattr(trace_info, "request_id", "unknown")[:16]
                missing_by_trace.append((request_id, trace_missing))

        print(f"Traces checked: {traces_checked}")
        print(f"Traces with all MLflow attrs: {traces_with_all_attrs}")
        print(f"\nAttribute coverage:")
        for attr, count in attr_counts.items():
            status = "✓" if count == traces_checked else "✗"
            print(f"  {status} {attr}: {count}/{traces_checked}")

        if missing_by_trace:
            print(f"\nMissing attributes (first 3 traces):")
            for req_id, missing in missing_by_trace[:3]:
                print(f"  {req_id}...: {', '.join(missing)}")

        # Assert: at least one trace should have all MLflow attributes
        assert traces_with_all_attrs > 0, (
            f"No traces have all required MLflow attributes.\n"
            f"Checked {traces_checked} GenAI traces.\n"
            f"Missing attributes: {[a for a, c in attr_counts.items() if c == 0]}\n\n"
            "Ensure the weather agent observability middleware sets these attributes "
            "on the root span."
        )

        print(
            f"\nSUCCESS: {traces_with_all_attrs}/{traces_checked} traces have all MLflow attrs"
        )

    def test_root_span_has_openinference_attributes(
        self, mlflow_url: str, mlflow_configured: bool, traces_available: list
    ):
        """
        Verify root span has OpenInference attributes for Phoenix.

        Required OpenInference attributes:
        - input.value: User input text
        - output.value: Agent response text
        - openinference.span.kind: Span type (should be 'AGENT')
        """
        all_traces, genai_traces = self._get_cached_traces(traces_available)
        if not genai_traces:
            pytest.fail(
                "No GenAI traces available - ensure conversation tests ran first"
            )

        print(f"\n{'=' * 60}")
        print("Root Span OpenInference Attributes (Phoenix)")
        print(f"{'=' * 60}")

        # Required attributes for Phoenix display
        openinference_attrs = [
            "input.value",
            "output.value",
            "openinference.span.kind",
        ]

        traces_checked = 0
        traces_with_all_attrs = 0
        attr_counts = {attr: 0 for attr in openinference_attrs}
        sample_values = {}

        # Check GenAI traces (max 10)
        for trace in genai_traces[:10]:
            root_span = self._get_root_span(trace)
            if not root_span:
                continue

            traces_checked += 1
            attrs = root_span.get("attributes", {})

            has_all = True
            for attr in openinference_attrs:
                if attr in attrs and attrs[attr]:
                    attr_counts[attr] += 1
                    # Capture first sample value
                    if attr not in sample_values:
                        val = str(attrs[attr])[:50]
                        sample_values[attr] = val
                else:
                    has_all = False

            if has_all:
                traces_with_all_attrs += 1

        print(f"Traces checked: {traces_checked}")
        print(f"Traces with all OpenInference attrs: {traces_with_all_attrs}")
        print(f"\nAttribute coverage:")
        for attr, count in attr_counts.items():
            status = "✓" if count == traces_checked else "✗"
            print(f"  {status} {attr}: {count}/{traces_checked}")
            if attr in sample_values:
                print(f"      Sample: {sample_values[attr]}...")

        # Note: output.value may be missing due to streaming responses (Task #8)
        # Make this a soft assertion with informative message
        if attr_counts["output.value"] == 0:
            print(
                "\nWARNING: output.value missing on all traces. "
                "This is expected for streaming responses - "
                "see Task #8 for streaming output capture fix."
            )

        # Assert: at least input.value and openinference.span.kind should be present
        assert attr_counts["input.value"] > 0, (
            "No traces have input.value attribute. "
            "Ensure the weather agent sets input.value on root span."
        )
        assert attr_counts["openinference.span.kind"] > 0, (
            "No traces have openinference.span.kind attribute. "
            "Ensure the weather agent sets openinference.span.kind='AGENT' on root span."
        )

        print(
            f"\nSUCCESS: {traces_with_all_attrs}/{traces_checked} traces have OpenInference attrs"
        )

    def test_root_span_has_genai_attributes(
        self, mlflow_url: str, mlflow_configured: bool, traces_available: list
    ):
        """
        Verify root span has GenAI semantic convention attributes.

        Required GenAI attributes:
        - gen_ai.conversation.id: Session/conversation identifier
        - gen_ai.agent.name: Agent name
        """
        all_traces, genai_traces = self._get_cached_traces(traces_available)
        if not genai_traces:
            pytest.fail(
                "No GenAI traces available - ensure conversation tests ran first"
            )

        print(f"\n{'=' * 60}")
        print("Root Span GenAI Attributes")
        print(f"{'=' * 60}")

        # Required GenAI semantic convention attributes
        genai_attrs = [
            "gen_ai.conversation.id",
            "gen_ai.agent.name",
        ]

        traces_checked = 0
        traces_with_all_attrs = 0
        attr_counts = {attr: 0 for attr in genai_attrs}
        conversation_ids = set()

        # Check GenAI traces (max 10)
        for trace in genai_traces[:10]:
            root_span = self._get_root_span(trace)
            if not root_span:
                continue

            traces_checked += 1
            attrs = root_span.get("attributes", {})

            has_all = True
            for attr in genai_attrs:
                if attr in attrs and attrs[attr]:
                    attr_counts[attr] += 1
                    if attr == "gen_ai.conversation.id":
                        conversation_ids.add(attrs[attr])
                else:
                    has_all = False

            if has_all:
                traces_with_all_attrs += 1

        print(f"Traces checked: {traces_checked}")
        print(f"Traces with all GenAI attrs: {traces_with_all_attrs}")
        print(f"\nAttribute coverage:")
        for attr, count in attr_counts.items():
            status = "✓" if count == traces_checked else "✗"
            print(f"  {status} {attr}: {count}/{traces_checked}")

        print(f"\nUnique conversation IDs: {len(conversation_ids)}")
        if conversation_ids:
            print(f"Sample IDs: {list(conversation_ids)[:3]}")

        # Assert: conversation.id is required for MLflow session tracking
        assert attr_counts["gen_ai.conversation.id"] > 0, (
            "No traces have gen_ai.conversation.id attribute. "
            "This is required for MLflow session grouping."
        )

        print(
            f"\nSUCCESS: {traces_with_all_attrs}/{traces_checked} traces have GenAI attrs"
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
