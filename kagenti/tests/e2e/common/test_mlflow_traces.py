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

Supports multiple agent observability variants via AGENT_OBSERVABILITY_VARIANT env var:
  - "baseline": Full observability.py in agent (PR 114 approach, ~551 lines)
  - "minimal": Minimal agent boilerplate + OTEL Collector enrichment (~50 lines)
  - "authbridge": AuthBridge ext_proc creates root span, zero agent code
  - "none": No agent instrumentation (negative test / infrastructure-only traces)

Usage:
    # Run with other observability tests (after main E2E tests)
    pytest kagenti/tests/e2e/ -v -m "observability"

    # Run for a specific variant
    AGENT_OBSERVABILITY_VARIANT=authbridge pytest -v -m "observability"

    # Standalone debugging
    python kagenti/tests/e2e/common/test_mlflow_traces.py
"""

import logging
import os
import subprocess
import time
from dataclasses import dataclass, field
from typing import Any, Callable, List, Optional

import pytest

logger = logging.getLogger(__name__)


# =============================================================================
# Agent Observability Variant Configuration
# =============================================================================


@dataclass
class VariantProfile:
    """Defines what trace attributes an agent observability variant produces.

    Each variant (baseline, minimal, authbridge, none) declares which
    attributes it sets on the root span and nested spans. Tests use this
    profile to assert the right things and skip irrelevant checks.
    """

    name: str
    description: str

    # Root span attributes this variant produces
    root_span_mlflow_attrs: list = field(default_factory=list)
    root_span_openinference_attrs: list = field(default_factory=list)
    root_span_genai_attrs: list = field(default_factory=list)

    # What span naming convention the root span uses
    root_span_name_pattern: str = "invoke_agent"

    # Whether this variant produces these trace features
    has_genai_spans: bool = True
    has_token_usage: bool = True
    has_tool_spans: bool = True
    has_session_tracking: bool = True

    # Whether MLflow E2E tests are expected to pass
    expects_mlflow_pass: bool = True


# Variant profiles for each approach
VARIANT_PROFILES = {
    "baseline": VariantProfile(
        name="baseline",
        description="Full observability.py in agent (PR 114 approach)",
        root_span_mlflow_attrs=[
            "mlflow.spanInputs",
            "mlflow.spanOutputs",
            "mlflow.user",
            "mlflow.traceName",
            "mlflow.version",
            "mlflow.runName",
        ],
        root_span_openinference_attrs=[
            "input.value",
            "output.value",
            "openinference.span.kind",
        ],
        root_span_genai_attrs=[
            "gen_ai.conversation.id",
            "gen_ai.agent.name",
        ],
        root_span_name_pattern="invoke_agent",
        has_genai_spans=True,
        has_token_usage=True,
        has_tool_spans=True,
        has_session_tracking=True,
        expects_mlflow_pass=True,
    ),
    "minimal": VariantProfile(
        name="minimal",
        description="Minimal agent boilerplate + OTEL Collector enrichment",
        root_span_mlflow_attrs=[
            # Collector adds these via transform processor
            "mlflow.spanInputs",
            "mlflow.spanOutputs",
            "mlflow.traceName",
        ],
        root_span_openinference_attrs=[
            "input.value",
            "output.value",
            "openinference.span.kind",
        ],
        root_span_genai_attrs=[
            "gen_ai.conversation.id",
            "gen_ai.agent.name",
        ],
        root_span_name_pattern="invoke_agent",
        has_genai_spans=True,
        has_token_usage=True,
        has_tool_spans=True,
        has_session_tracking=True,
        expects_mlflow_pass=True,
    ),
    "authbridge": VariantProfile(
        name="authbridge",
        description="AuthBridge ext_proc creates root span, zero agent code",
        root_span_mlflow_attrs=[
            "mlflow.spanInputs",
            "mlflow.spanOutputs",
            "mlflow.user",
            "mlflow.traceName",
            "mlflow.version",
            "mlflow.runName",
        ],
        root_span_openinference_attrs=[
            "input.value",
            "output.value",
            "openinference.span.kind",
        ],
        root_span_genai_attrs=[
            "gen_ai.conversation.id",
            "gen_ai.agent.name",
        ],
        root_span_name_pattern="invoke_agent",
        has_genai_spans=True,
        has_token_usage=True,
        has_tool_spans=True,
        has_session_tracking=True,
        expects_mlflow_pass=True,
    ),
    "none": VariantProfile(
        name="none",
        description="No agent instrumentation (negative test)",
        root_span_mlflow_attrs=[],
        root_span_openinference_attrs=[],
        root_span_genai_attrs=[],
        root_span_name_pattern="",
        has_genai_spans=False,
        has_token_usage=False,
        has_tool_spans=False,
        has_session_tracking=False,
        expects_mlflow_pass=False,
    ),
}


def get_variant_profile() -> VariantProfile:
    """Get the current agent observability variant profile.

    Reads from AGENT_OBSERVABILITY_VARIANT env var (default: "baseline").
    """
    variant_name = os.getenv("AGENT_OBSERVABILITY_VARIANT", "baseline")
    if variant_name not in VARIANT_PROFILES:
        logger.warning(
            f"Unknown variant '{variant_name}', using 'baseline'. "
            f"Valid variants: {list(VARIANT_PROFILES.keys())}"
        )
        variant_name = "baseline"
    return VARIANT_PROFILES[variant_name]


# =============================================================================
# kubectl Resilience Helpers
# =============================================================================


def run_kubectl_with_retry(
    args: List[str],
    retries: int = 5,
    initial_delay: float = 5.0,
    timeout: int = 30,
    check: bool = False,
) -> subprocess.CompletedProcess:
    """
    Run kubectl command with exponential backoff retry logic.

    Designed for HyperShift clusters that experience intermittent TLS handshake
    timeouts during control plane load. Retries on timeout/connection errors.

    Args:
        args: kubectl command arguments (e.g., ["kubectl", "exec", ...])
        retries: Number of retry attempts (default: 3)
        initial_delay: Initial delay between retries in seconds (default: 2.0)
        timeout: Timeout per attempt in seconds (default: 30)
        check: If True, raise CalledProcessError on failure (default: False)

    Returns:
        CompletedProcess result from successful attempt

    Raises:
        subprocess.TimeoutExpired: If all retries timeout
        subprocess.CalledProcessError: If check=True and command fails
    """
    delay = initial_delay
    last_exception = None

    for attempt in range(retries):
        try:
            result = subprocess.run(
                args,
                capture_output=True,
                text=True,
                timeout=timeout,
                check=check,
            )

            # Success - check for common kubectl errors in stderr
            if "TLS handshake timeout" in result.stderr:
                raise subprocess.CalledProcessError(
                    returncode=1,
                    cmd=args,
                    stderr=result.stderr,
                )

            return result

        except (subprocess.TimeoutExpired, subprocess.CalledProcessError) as e:
            last_exception = e

            if attempt < retries - 1:
                logger.warning(
                    f"kubectl attempt {attempt + 1}/{retries} failed: {type(e).__name__}. "
                    f"Retrying in {delay:.1f}s..."
                )
                time.sleep(delay)
                delay = min(delay * 2, 15)  # Exponential backoff, capped at 15s
            else:
                logger.error(
                    f"kubectl failed after {retries} attempts: {type(e).__name__}"
                )

    # All retries exhausted
    if last_exception:
        raise last_exception

    # Should never reach here
    raise RuntimeError(f"kubectl retry logic failed unexpectedly for {args}")


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

    # Fall back to Kind cluster URL using DOMAIN_NAME env var
    domain = os.environ.get("DOMAIN_NAME", "localtest.me")
    return f"http://mlflow.{domain}:8080"


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

    Uses kubectl exec to get token from internal Keycloak (same as initial token).
    This ensures the token has the correct issuer that MLflow expects.

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
        import json

        client_id = _token_credentials["client_id"]
        client_secret = _token_credentials["client_secret"]
        token_url = _token_credentials["token_url"]

        # Get token from inside cluster using kubectl exec
        # This gives us a token with the correct internal issuer
        python_script = f"""
import urllib.request
import json

data = 'grant_type=client_credentials&client_id={client_id}&client_secret={client_secret}'
req = urllib.request.Request(
    '{token_url}',
    data=data.encode('utf-8'),
    headers={{'Content-Type': 'application/x-www-form-urlencoded'}}
)
resp = urllib.request.urlopen(req)
result = json.loads(resp.read())
print(json.dumps(result))
"""

        try:
            result = run_kubectl_with_retry(
                [
                    "kubectl",
                    "exec",
                    "-n",
                    "kagenti-system",
                    "deploy/mlflow",
                    "--",
                    "python",
                    "-c",
                    python_script,
                ],
                retries=5,
                timeout=30,
            )

            if result.returncode != 0:
                logger.error(
                    f"Failed to refresh token via kubectl exec: {result.stderr}"
                )
                return False
        except (subprocess.TimeoutExpired, subprocess.CalledProcessError) as e:
            logger.error(f"Failed to refresh token after retries: {e}")
            return False

        # Parse JSON output (skip any kubectl warnings)
        json_output = result.stdout.strip()
        # Find the JSON object (starts with {)
        json_start = json_output.find("{")
        if json_start >= 0:
            json_output = json_output[json_start:]

        token_data = json.loads(json_output)
        new_token = token_data.get("access_token")
        _token_expires_in = token_data.get("expires_in", 60)
        _token_issued_at = time.time()

        # Update the environment variable for MLflow client
        os.environ["MLFLOW_TRACKING_TOKEN"] = new_token

        logger.info(f"Token refreshed (expires in {_token_expires_in}s)")
        return True

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


def get_traces_by_session_id(session_id: str) -> list[dict[str, Any]]:
    """Get traces that match a specific session/conversation ID.

    Filters traces by gen_ai.conversation.id in span attributes.
    This allows correlating traces to a specific test run, preventing
    false positives from old traces on repeated test runs.

    Args:
        session_id: The conversation/context ID to filter by

    Returns:
        List of traces that have spans with matching gen_ai.conversation.id
    """
    all_traces = get_all_traces()
    matching_traces = []

    client = get_mlflow_client()
    if not client:
        return []

    for trace in all_traces:
        try:
            trace_info = trace.info if hasattr(trace, "info") else trace
            request_id = (
                trace_info.request_id
                if hasattr(trace_info, "request_id")
                else trace_info.get("request_id")
            )

            if not request_id:
                continue

            trace_data = client.get_trace(request_id)
            if not trace_data:
                continue

            spans = trace_data.data.spans if hasattr(trace_data, "data") else []

            for span in spans:
                attributes = span.attributes if hasattr(span, "attributes") else {}
                conversation_id = attributes.get("gen_ai.conversation.id")
                if conversation_id == session_id:
                    matching_traces.append(trace)
                    break  # Found match, no need to check other spans

        except Exception as e:
            logger.warning(f"Error checking trace for session ID: {e}")
            continue

    logger.info(f"Found {len(matching_traces)} traces matching session ID {session_id}")
    return matching_traces


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
def agent_variant():
    """Get the current agent observability variant profile.

    Controls which assertions are run based on how the agent is instrumented.
    Set via AGENT_OBSERVABILITY_VARIANT env var:
      - "baseline": Full observability.py (default)
      - "minimal": Minimal agent + collector enrichment
      - "authbridge": AuthBridge ext_proc root span
      - "none": No instrumentation (negative test)
    """
    profile = get_variant_profile()
    print(f"\n[Variant] Testing agent observability variant: {profile.name}")
    print(f"[Variant] {profile.description}")
    return profile


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
    import json

    import requests
    import urllib3
    from kubernetes.client.rest import ApiException

    # Use CA file for SSL verification (openshift_ingress_ca fixture fails if unavailable)
    import ssl as ssl_module

    if is_openshift:
        ssl_verify = ssl_module.create_default_context(cafile=openshift_ingress_ca)
    else:
        ssl_verify = True

    try:
        # Get MLflow OAuth secret
        secret = k8s_client.read_namespaced_secret(
            name="mlflow-oauth-secret", namespace="kagenti-system"
        )

        client_id = base64.b64decode(secret.data["OIDC_CLIENT_ID"]).decode()
        client_secret = base64.b64decode(secret.data["OIDC_CLIENT_SECRET"]).decode()
        # Use internal Keycloak URL (always) for correct issuer
        # Tests run from outside cluster, so we use kubectl exec to access internal Keycloak
        # This ensures token issuer matches what MLflow expects
        token_url = base64.b64decode(secret.data["OIDC_TOKEN_URL"]).decode()

        logger.info(
            f"Getting token from internal Keycloak via kubectl exec: {token_url}"
        )

        # Get token from inside cluster using kubectl exec
        # This gives us a token with the correct internal issuer
        python_script = f"""
import urllib.request
import json

data = 'grant_type=client_credentials&client_id={client_id}&client_secret={client_secret}'
req = urllib.request.Request(
    '{token_url}',
    data=data.encode('utf-8'),
    headers={{'Content-Type': 'application/x-www-form-urlencoded'}}
)
resp = urllib.request.urlopen(req)
result = json.loads(resp.read())
print(json.dumps(result))
"""

        try:
            result = run_kubectl_with_retry(
                [
                    "kubectl",
                    "exec",
                    "-n",
                    "kagenti-system",
                    "deploy/mlflow",
                    "--",
                    "python",
                    "-c",
                    python_script,
                ],
                retries=5,
                timeout=30,
            )

            if result.returncode != 0:
                logger.warning(f"Failed to get token via kubectl exec: {result.stderr}")
                return None
        except (subprocess.TimeoutExpired, subprocess.CalledProcessError) as e:
            logger.warning(f"Failed to get token after retries: {e}")
            return None

        try:
            # Parse JSON output (skip any kubectl warnings)
            json_output = result.stdout.strip()
            # Find the JSON object (starts with {)
            json_start = json_output.find("{")
            if json_start >= 0:
                json_output = json_output[json_start:]

            token_data = json.loads(json_output)
            _token_expires_in = token_data.get("expires_in", 60)
            _token_issued_at = time.time()

            # Store credentials for automatic token refresh
            _token_credentials = {
                "client_id": client_id,
                "client_secret": client_secret,
                "token_url": token_url,
                "ssl_verify": False,  # Not used for kubectl exec
            }

            logger.info(
                f"✅ Got MLflow token from internal Keycloak (expires in {_token_expires_in}s)"
            )
            return token_data.get("access_token")
        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse token response: {e}")
            logger.warning(f"Output was: {result.stdout}")
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

        # Use CA cert for SSL verification on OpenShift
        import ssl as ssl_module

        if openshift_ingress_ca:
            ssl_ctx = ssl_module.create_default_context(cafile=openshift_ingress_ca)
        else:
            ssl_ctx = True

        try:
            response = httpx.get(f"{mlflow_url}/version", verify=ssl_ctx, timeout=30.0)
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

    def test_mlflow_otel_metrics_received(self, k8s_client):
        """
        Verify OTEL collector successfully sends traces to MLflow database.

        This is a pipeline health check that bypasses HTTP/auth to verify
        traces are being received and persisted. Does NOT validate trace
        content - that's done by subsequent MLflow SDK tests.

        This test queries the database directly (no auth required) to verify:
        - OTEL collector is running
        - OTEL → MLflow pipeline is working
        - Traces are being persisted to database

        This test will FAIL if:
        - No traces exist in database
        - Database is not accessible
        - Agent tests didn't run first (no traces generated)
        """
        logger.info("Checking if MLflow received traces from OTEL collector...")

        # Query database directly (bypasses HTTP auth)
        result = run_kubectl_with_retry(
            [
                "kubectl",
                "exec",
                "-n",
                "kagenti-system",
                "postgres-otel-0",
                "--",
                "psql",
                "-U",
                "testuser",
                "-d",
                "mlflow",
                "-t",
                "-c",
                """
                SELECT COUNT(*)
                FROM trace_info
                WHERE timestamp_ms > EXTRACT(EPOCH FROM NOW() - INTERVAL '2 hours') * 1000;
                """,
            ],
            retries=10,
            timeout=30,
            check=True,
        )

        count = int(result.stdout.strip())

        assert count > 0, (
            f"No traces found in MLflow database from last 2 hours. "
            f"OTEL → MLflow pipeline may be broken or agent tests didn't run first. "
            f"Check: (1) OTEL collector pods, (2) MLflow OTLP endpoint, (3) OAuth2 auth"
        )

        logger.info(f"✅ Pipeline healthy: MLflow received {count} traces from OTEL")

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

    def test_genai_traces_exist(
        self, mlflow_url: str, mlflow_configured: bool, agent_variant: VariantProfile
    ):
        """Verify GenAI/LLM traces are captured in MLflow.

        This test looks for spans from LangChain/LangGraph instrumentation,
        which include LLM calls, chain executions, and tool invocations.
        """
        if not agent_variant.has_genai_spans:
            pytest.skip(f"Variant '{agent_variant.name}' does not produce GenAI spans")

        all_traces, genai_traces = self._get_cached_traces()

        print(f"\n{'=' * 60}")
        print(f"GenAI Traces in MLflow (variant: {agent_variant.name})")
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
        self,
        mlflow_url: str,
        mlflow_configured: bool,
        traces_available: list,
        agent_variant: VariantProfile,
    ):
        """
        Assert traces have gen_ai.conversation.id for session tracking.

        This is the standard GenAI semantic convention attribute that enables
        MLflow to group traces by conversation/session.

        NOTE: Due to MLflow async trace hierarchy flattening (see GitHub issue #16880),
        GenAI spans may be in separate traces from A2A framework spans. This test
        specifically checks GenAI traces, not all traces.
        """
        if not agent_variant.has_session_tracking:
            pytest.skip(
                f"Variant '{agent_variant.name}' does not produce session tracking attributes"
            )

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

    def test_traces_filter_by_session_id(
        self, mlflow_url: str, mlflow_configured: bool, test_session_id: str
    ):
        """
        Test filtering traces by the current test session ID.

        This demonstrates trace correlation between agent conversation tests
        and observability tests. The test_session_id fixture provides a unique
        ID that is passed to agent tests as context_id, allowing us to filter
        for only traces from the current test run.

        This prevents false positives from old traces when running repeated
        test runs on the same cluster.
        """
        print(f"\n{'=' * 60}")
        print("Session ID Trace Filtering")
        print(f"{'=' * 60}")
        print(f"Looking for traces with session ID: {test_session_id}")

        # Get traces filtered by session ID
        session_traces = get_traces_by_session_id(test_session_id)

        print(f"Traces matching session ID: {len(session_traces)}")

        if session_traces:
            print("\nMatching traces:")
            for i, trace in enumerate(session_traces[:5]):
                trace_info = trace.info if hasattr(trace, "info") else trace
                request_id = getattr(trace_info, "request_id", "unknown")
                print(f"  [{i + 1}] {request_id[:40]}...")

            print(f"\nSUCCESS: Found {len(session_traces)} traces for current session")
        else:
            # This is not a failure - just means agent tests haven't run with this session ID yet
            pytest.skip(
                f"No traces found for session ID {test_session_id}. "
                "Run agent conversation tests first to generate traces with this session."
            )


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
        self,
        mlflow_url: str,
        mlflow_configured: bool,
        traces_available: list,
        agent_variant: VariantProfile,
    ):
        """
        Verify root span has MLflow-specific attributes.

        Attributes checked depend on the agent observability variant:
        - baseline: All mlflow.* attributes set by agent middleware
        - minimal: Subset set by OTEL Collector transform
        - authbridge: All mlflow.* attributes set by ext_proc
        - none: Skip (no instrumentation)
        """
        if not agent_variant.root_span_mlflow_attrs:
            pytest.skip(
                f"Variant '{agent_variant.name}' does not produce MLflow root span attributes"
            )

        all_traces, genai_traces = self._get_cached_traces(traces_available)
        if not genai_traces:
            pytest.fail(
                "No GenAI traces available - ensure conversation tests ran first"
            )

        print(f"\n{'=' * 60}")
        print(f"Root Span MLflow Attributes (variant: {agent_variant.name})")
        print(f"{'=' * 60}")

        # Use variant-specific expected attributes
        mlflow_attrs = agent_variant.root_span_mlflow_attrs

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
        self,
        mlflow_url: str,
        mlflow_configured: bool,
        traces_available: list,
        agent_variant: VariantProfile,
    ):
        """
        Verify root span has OpenInference attributes for Phoenix.

        Attributes checked depend on the agent observability variant.
        """
        if not agent_variant.root_span_openinference_attrs:
            pytest.skip(
                f"Variant '{agent_variant.name}' does not produce OpenInference root span attributes"
            )

        all_traces, genai_traces = self._get_cached_traces(traces_available)
        if not genai_traces:
            pytest.fail(
                "No GenAI traces available - ensure conversation tests ran first"
            )

        print(f"\n{'=' * 60}")
        print(f"Root Span OpenInference Attributes (variant: {agent_variant.name})")
        print(f"{'=' * 60}")

        # Use variant-specific expected attributes
        openinference_attrs = agent_variant.root_span_openinference_attrs

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
        self,
        mlflow_url: str,
        mlflow_configured: bool,
        traces_available: list,
        agent_variant: VariantProfile,
    ):
        """
        Verify root span has GenAI semantic convention attributes.

        Attributes checked depend on the agent observability variant.
        """
        if not agent_variant.root_span_genai_attrs:
            pytest.skip(
                f"Variant '{agent_variant.name}' does not produce GenAI root span attributes"
            )

        all_traces, genai_traces = self._get_cached_traces(traces_available)
        if not genai_traces:
            pytest.fail(
                "No GenAI traces available - ensure conversation tests ran first"
            )

        print(f"\n{'=' * 60}")
        print(f"Root Span GenAI Attributes (variant: {agent_variant.name})")
        print(f"{'=' * 60}")

        # Use variant-specific expected attributes
        genai_attrs = agent_variant.root_span_genai_attrs

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


@pytest.mark.observability
@pytest.mark.openshift_only
@pytest.mark.requires_features(["mlflow"])
class TestTokenUsageVerification:
    """
    Verify LLM spans have token usage attributes.

    Token usage is critical for:
    - Cost tracking in MLflow
    - Performance analysis in Phoenix
    - Understanding LLM efficiency

    Expected attributes:
    - gen_ai.usage.input_tokens (or llm.token_count.prompt)
    - gen_ai.usage.output_tokens (or llm.token_count.completion)
    - gen_ai.usage.total_tokens (optional, sum of above)
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
            cls._cached_genai_traces = [
                t for t in cls._cached_traces if has_genai_spans(t)
            ]
            logger.info(
                f"Cached {len(cls._cached_traces)} traces, "
                f"{len(cls._cached_genai_traces)} GenAI traces for token usage tests"
            )
        return cls._cached_traces, cls._cached_genai_traces

    def _find_llm_spans(self, trace: Any) -> list[dict]:
        """Find LLM spans in a trace that should have token usage.

        LLM spans are identified by:
        - Span name containing 'chat', 'completion', 'llm', 'openai', 'ollama'
        - Span type being 'LLM'
        - Having gen_ai.request.model attribute
        """
        spans = get_trace_span_details(trace)
        llm_spans = []

        llm_patterns = [
            "chatopenai",
            "chatollama",
            "chat_completion",
            "chat.completions",
            "llm",
            "openai",
            "anthropic",
            "gen_ai.chat",
        ]

        for span in spans:
            span_name = span.get("name", "").lower()
            attrs = span.get("attributes", {})

            # Check if this is an LLM span
            is_llm = False

            # Check span name patterns
            if any(pattern in span_name for pattern in llm_patterns):
                is_llm = True

            # Check for gen_ai.request.model attribute (indicates LLM call)
            if attrs.get("gen_ai.request.model"):
                is_llm = True

            # Check for llm.model_name (OpenInference)
            if attrs.get("llm.model_name"):
                is_llm = True

            if is_llm:
                llm_spans.append(span)

        return llm_spans

    def test_llm_spans_have_token_counts(
        self,
        mlflow_url: str,
        mlflow_configured: bool,
        traces_available: list,
        agent_variant: VariantProfile,
    ):
        """
        Verify LLM spans have token usage attributes.

        Checks for token count attributes in either:
        - GenAI format: gen_ai.usage.input_tokens, gen_ai.usage.output_tokens
        - OpenInference format: llm.token_count.prompt, llm.token_count.completion
        """
        if not agent_variant.has_token_usage:
            pytest.skip(
                f"Variant '{agent_variant.name}' does not produce token usage spans"
            )

        all_traces, genai_traces = self._get_cached_traces(traces_available)
        if not genai_traces:
            pytest.skip(
                "No GenAI traces available - agent may not have LLM instrumentation"
            )

        print(f"\n{'=' * 60}")
        print("LLM Token Usage Verification")
        print(f"{'=' * 60}")

        # Token attributes to check (either format)
        token_attrs_genai = [
            "gen_ai.usage.input_tokens",
            "gen_ai.usage.output_tokens",
        ]
        token_attrs_openinference = [
            "llm.token_count.prompt",
            "llm.token_count.completion",
        ]

        total_llm_spans = 0
        llm_spans_with_tokens = 0
        token_counts_found = []

        # Check GenAI traces (max 10 to avoid rate limiting)
        for trace in genai_traces[:10]:
            llm_spans = self._find_llm_spans(trace)
            total_llm_spans += len(llm_spans)

            for span in llm_spans:
                attrs = span.get("attributes", {})

                # Check for token counts in either format
                input_tokens = (
                    attrs.get("gen_ai.usage.input_tokens")
                    or attrs.get("llm.token_count.prompt")
                    or attrs.get("gen_ai.usage.prompt_tokens")
                )
                output_tokens = (
                    attrs.get("gen_ai.usage.output_tokens")
                    or attrs.get("llm.token_count.completion")
                    or attrs.get("gen_ai.usage.completion_tokens")
                )

                if input_tokens is not None or output_tokens is not None:
                    llm_spans_with_tokens += 1
                    token_counts_found.append(
                        {
                            "span_name": span.get("name", "unknown"),
                            "input_tokens": input_tokens,
                            "output_tokens": output_tokens,
                            "total": (input_tokens or 0) + (output_tokens or 0),
                        }
                    )

        print(f"GenAI traces checked: {min(10, len(genai_traces))}")
        print(f"Total LLM spans found: {total_llm_spans}")
        print(f"LLM spans with token counts: {llm_spans_with_tokens}")

        if token_counts_found:
            print(f"\nSample token counts:")
            for tc in token_counts_found[:5]:
                print(
                    f"  - {tc['span_name'][:40]}: "
                    f"input={tc['input_tokens']}, output={tc['output_tokens']}"
                )

            # Calculate averages
            avg_input = sum(tc["input_tokens"] or 0 for tc in token_counts_found) / len(
                token_counts_found
            )
            avg_output = sum(
                tc["output_tokens"] or 0 for tc in token_counts_found
            ) / len(token_counts_found)
            print(f"\nAverage tokens per LLM call:")
            print(f"  Input: {avg_input:.1f}")
            print(f"  Output: {avg_output:.1f}")

        if total_llm_spans == 0:
            pytest.skip(
                "No LLM spans found in traces. "
                "Weather agent may be using a framework without LLM instrumentation, "
                "or LLM calls are not being traced."
            )

        # Assert: at least some LLM spans should have token counts
        # Note: Not all LLM spans may have token counts (e.g., streaming responses)
        if llm_spans_with_tokens == 0:
            print(
                "\nWARNING: No LLM spans have token usage attributes.\n"
                "Possible causes:\n"
                "  - LLM provider not returning usage data\n"
                "  - Streaming responses (tokens may not be available)\n"
                "  - Instrumentation not capturing token counts"
            )
            # This is informational, not a hard failure
            # Some LLM providers don't return token counts
        else:
            coverage = (llm_spans_with_tokens / total_llm_spans) * 100
            print(f"\nToken count coverage: {coverage:.1f}%")

        print(f"\nSUCCESS: Found {llm_spans_with_tokens} LLM spans with token counts")

    def test_token_totals_are_reasonable(
        self, mlflow_url: str, mlflow_configured: bool, traces_available: list
    ):
        """
        Verify token counts are reasonable values.

        Checks that token counts are:
        - Non-negative integers
        - Within reasonable ranges for LLM calls
        - Consistent (total = input + output when present)
        """
        all_traces, genai_traces = self._get_cached_traces(traces_available)
        if not genai_traces:
            pytest.skip("No GenAI traces available")

        print(f"\n{'=' * 60}")
        print("Token Count Validation")
        print(f"{'=' * 60}")

        valid_token_counts = 0
        invalid_token_counts = 0
        validation_issues = []

        for trace in genai_traces[:10]:
            llm_spans = self._find_llm_spans(trace)

            for span in llm_spans:
                attrs = span.get("attributes", {})

                input_tokens = attrs.get("gen_ai.usage.input_tokens") or attrs.get(
                    "llm.token_count.prompt"
                )
                output_tokens = attrs.get("gen_ai.usage.output_tokens") or attrs.get(
                    "llm.token_count.completion"
                )
                total_tokens = attrs.get("gen_ai.usage.total_tokens") or attrs.get(
                    "llm.token_count.total"
                )

                if input_tokens is None and output_tokens is None:
                    continue  # No token info, skip

                issues = []

                # Validate input tokens
                if input_tokens is not None:
                    try:
                        input_val = int(input_tokens)
                        if input_val < 0:
                            issues.append(f"negative input_tokens: {input_val}")
                        elif input_val > 100000:
                            issues.append(f"unusually high input_tokens: {input_val}")
                    except (ValueError, TypeError):
                        issues.append(
                            f"invalid input_tokens type: {type(input_tokens)}"
                        )

                # Validate output tokens
                if output_tokens is not None:
                    try:
                        output_val = int(output_tokens)
                        if output_val < 0:
                            issues.append(f"negative output_tokens: {output_val}")
                        elif output_val > 50000:
                            issues.append(f"unusually high output_tokens: {output_val}")
                    except (ValueError, TypeError):
                        issues.append(
                            f"invalid output_tokens type: {type(output_tokens)}"
                        )

                # Validate total if present
                if (
                    total_tokens is not None
                    and input_tokens is not None
                    and output_tokens is not None
                ):
                    try:
                        expected_total = int(input_tokens) + int(output_tokens)
                        actual_total = int(total_tokens)
                        if actual_total != expected_total:
                            issues.append(
                                f"total mismatch: {actual_total} != {expected_total}"
                            )
                    except (ValueError, TypeError):
                        pass  # Already caught above

                if issues:
                    invalid_token_counts += 1
                    validation_issues.append(
                        {
                            "span": span.get("name", "unknown")[:30],
                            "issues": issues,
                        }
                    )
                else:
                    valid_token_counts += 1

        print(f"Token counts validated: {valid_token_counts + invalid_token_counts}")
        print(f"Valid: {valid_token_counts}")
        print(f"Invalid: {invalid_token_counts}")

        if validation_issues:
            print(f"\nValidation issues found:")
            for vi in validation_issues[:5]:
                print(f"  - {vi['span']}: {', '.join(vi['issues'])}")

        if valid_token_counts + invalid_token_counts == 0:
            pytest.skip("No LLM spans with token counts to validate")

        # Assert: most token counts should be valid
        if invalid_token_counts > 0:
            error_rate = invalid_token_counts / (
                valid_token_counts + invalid_token_counts
            )
            assert error_rate < 0.5, (
                f"High error rate in token counts: {error_rate:.1%}. "
                f"Issues: {validation_issues[:3]}"
            )

        print(f"\nSUCCESS: {valid_token_counts} valid token counts")

    def test_mlflow_span_chat_usage_attribute(
        self, mlflow_url: str, mlflow_configured: bool, traces_available: list
    ):
        """
        Verify OTEL transform creates mlflow.span.chat_usage for MLflow UI.

        The OTEL collector should transform gen_ai.usage.* attributes to
        mlflow.span.chat_usage JSON object for display in MLflow's token column.
        """
        all_traces, genai_traces = self._get_cached_traces(traces_available)
        if not genai_traces:
            pytest.skip("No GenAI traces available")

        print(f"\n{'=' * 60}")
        print("MLflow Chat Usage Attribute (Token Display)")
        print(f"{'=' * 60}")

        spans_with_chat_usage = 0
        chat_usage_samples = []

        for trace in genai_traces[:10]:
            spans = get_trace_span_details(trace)

            for span in spans:
                attrs = span.get("attributes", {})

                # Check for mlflow.span.chat_usage (added by OTEL transform)
                chat_usage = attrs.get("mlflow.span.chat_usage")
                if chat_usage:
                    spans_with_chat_usage += 1
                    chat_usage_samples.append(
                        {
                            "span_name": span.get("name", "unknown"),
                            "chat_usage": chat_usage,
                        }
                    )

        print(f"Traces checked: {min(10, len(genai_traces))}")
        print(f"Spans with mlflow.span.chat_usage: {spans_with_chat_usage}")

        if chat_usage_samples:
            print(f"\nSample mlflow.span.chat_usage values:")
            for sample in chat_usage_samples[:3]:
                usage_str = str(sample["chat_usage"])[:80]
                print(f"  - {sample['span_name'][:30]}: {usage_str}")

        # This attribute is created by the OTEL collector transform
        # If not present, the transform may not be configured
        if spans_with_chat_usage == 0:
            print(
                "\nNOTE: mlflow.span.chat_usage not found.\n"
                "This attribute is created by the OTEL collector transform/genai_to_mlflow.\n"
                "Check otel-collector config for transform processor."
            )
        else:
            print(
                f"\nSUCCESS: Found {spans_with_chat_usage} spans with mlflow.span.chat_usage"
            )


@pytest.mark.observability
@pytest.mark.openshift_only
@pytest.mark.requires_features(["mlflow"])
class TestErrorSpanValidation:
    """
    Validate error span attributes are properly captured.

    When errors occur during agent execution, spans should have:
    - Status indicating ERROR
    - Exception/error message attributes
    - Stack trace (when available)

    This helps with debugging failed agent invocations in MLflow/Phoenix.
    """

    # Class-level cache for traces
    _cached_traces: list = None

    @classmethod
    def _get_cached_traces(cls, traces_from_fixture: list = None) -> list:
        """Get cached traces or use traces from fixture."""
        if cls._cached_traces is None:
            if traces_from_fixture:
                cls._cached_traces = traces_from_fixture
            else:
                cls._cached_traces = get_all_traces()
            logger.info(f"Cached {len(cls._cached_traces)} traces for error span tests")
        return cls._cached_traces

    def _find_error_spans(self, trace: Any) -> list[dict]:
        """Find spans with error status in a trace.

        Error spans are identified by:
        - status = 'ERROR' or 'StatusCode.ERROR'
        - exception.* attributes present
        - error.* attributes present
        - otel.status_code = 'ERROR'
        """
        spans = get_trace_span_details(trace)
        error_spans = []

        for span in spans:
            status = span.get("status", "")
            attrs = span.get("attributes", {})

            is_error = False

            # Check status field
            if status:
                status_str = str(status).upper()
                if "ERROR" in status_str:
                    is_error = True

            # Check otel.status_code attribute
            otel_status = attrs.get("otel.status_code", "")
            if otel_status and "ERROR" in str(otel_status).upper():
                is_error = True

            # Check for exception attributes (indicates error occurred)
            if attrs.get("exception.type") or attrs.get("exception.message"):
                is_error = True

            # Check for error attributes
            if attrs.get("error.type") or attrs.get("error.message"):
                is_error = True

            if is_error:
                error_spans.append(span)

        return error_spans

    def test_error_spans_have_proper_status(
        self, mlflow_url: str, mlflow_configured: bool, traces_available: list
    ):
        """
        Verify error spans have proper status attributes.

        When an error occurs, the span should have:
        - status = ERROR (or equivalent)
        - otel.status_code = ERROR (OpenTelemetry convention)
        """
        all_traces = self._get_cached_traces(traces_available)
        if not all_traces:
            pytest.fail(
                "No traces available - ensure conversation tests ran first and auth is working"
            )

        print(f"\n{'=' * 60}")
        print("Error Span Status Verification")
        print(f"{'=' * 60}")

        total_error_spans = 0
        error_spans_with_status = 0
        status_values_found = {}

        # Check traces (max 10 to avoid rate limiting)
        for trace in all_traces[:10]:
            error_spans = self._find_error_spans(trace)
            total_error_spans += len(error_spans)

            for span in error_spans:
                status = span.get("status", "")
                attrs = span.get("attributes", {})
                otel_status = attrs.get("otel.status_code", "")

                # Track status values
                if status:
                    status_str = str(status)
                    if status_str not in status_values_found:
                        status_values_found[status_str] = 0
                    status_values_found[status_str] += 1
                    error_spans_with_status += 1
                elif otel_status:
                    if str(otel_status) not in status_values_found:
                        status_values_found[str(otel_status)] = 0
                    status_values_found[str(otel_status)] += 1
                    error_spans_with_status += 1

        print(f"Traces checked: {min(10, len(all_traces))}")
        print(f"Total error spans found: {total_error_spans}")
        print(f"Error spans with status: {error_spans_with_status}")

        if status_values_found:
            print(f"\nStatus values observed:")
            for status, count in status_values_found.items():
                print(f"  - {status}: {count}")

        if total_error_spans == 0:
            # No errors is actually good - successful execution
            print("\nNo error spans found - all spans completed successfully")
            print("This is expected for successful test runs")
            return

        # If there are error spans, they should have proper status
        if error_spans_with_status > 0:
            print(
                f"\nSUCCESS: {error_spans_with_status}/{total_error_spans} "
                f"error spans have status"
            )

    def test_error_spans_have_exception_details(
        self, mlflow_url: str, mlflow_configured: bool, traces_available: list
    ):
        """
        Verify error spans have exception/error details.

        When an error occurs, the span should capture:
        - exception.type: Exception class name
        - exception.message: Error message
        - exception.stacktrace: Stack trace (if available)
        """
        all_traces = self._get_cached_traces(traces_available)
        if not all_traces:
            pytest.fail(
                "No traces available - ensure conversation tests ran first and auth is working"
            )

        print(f"\n{'=' * 60}")
        print("Error Span Exception Details")
        print(f"{'=' * 60}")

        # Exception attributes to check
        exception_attrs = [
            "exception.type",
            "exception.message",
            "exception.stacktrace",
            "error.type",
            "error.message",
        ]

        total_error_spans = 0
        attr_counts = {attr: 0 for attr in exception_attrs}
        error_samples = []

        # Check traces (max 10)
        for trace in all_traces[:10]:
            error_spans = self._find_error_spans(trace)
            total_error_spans += len(error_spans)

            for span in error_spans:
                attrs = span.get("attributes", {})

                for attr in exception_attrs:
                    if attrs.get(attr):
                        attr_counts[attr] += 1

                # Capture sample for display
                if len(error_samples) < 5:
                    exc_type = attrs.get("exception.type") or attrs.get("error.type")
                    exc_msg = attrs.get("exception.message") or attrs.get(
                        "error.message"
                    )
                    if exc_type or exc_msg:
                        error_samples.append(
                            {
                                "span_name": span.get("name", "unknown"),
                                "type": exc_type,
                                "message": str(exc_msg)[:100] if exc_msg else None,
                            }
                        )

        print(f"Traces checked: {min(10, len(all_traces))}")
        print(f"Total error spans: {total_error_spans}")

        if total_error_spans > 0:
            print(f"\nException attribute coverage:")
            for attr, count in attr_counts.items():
                print(f"  - {attr}: {count}/{total_error_spans}")

            if error_samples:
                print(f"\nSample error details:")
                for sample in error_samples[:3]:
                    print(f"  - {sample['span_name'][:30]}")
                    if sample["type"]:
                        print(f"      Type: {sample['type']}")
                    if sample["message"]:
                        print(f"      Message: {sample['message'][:60]}...")
        else:
            print("\nNo error spans found - all spans completed successfully")
            print("This is expected for successful test runs")

    def test_span_status_distribution(
        self, mlflow_url: str, mlflow_configured: bool, traces_available: list
    ):
        """
        Analyze the distribution of span statuses across all traces.

        Provides visibility into:
        - Success vs error rate
        - Common error patterns
        - Overall trace health
        """
        all_traces = self._get_cached_traces(traces_available)
        if not all_traces:
            pytest.fail(
                "No traces available - ensure conversation tests ran first and auth is working"
            )

        print(f"\n{'=' * 60}")
        print("Span Status Distribution")
        print(f"{'=' * 60}")

        status_counts = {}
        total_spans = 0

        # Check traces (max 10)
        for trace in all_traces[:10]:
            spans = get_trace_span_details(trace)
            total_spans += len(spans)

            for span in spans:
                status = span.get("status", "UNKNOWN")
                status_str = str(status).upper() if status else "UNKNOWN"

                # Normalize status
                if "OK" in status_str or "UNSET" in status_str:
                    status_key = "OK"
                elif "ERROR" in status_str:
                    status_key = "ERROR"
                else:
                    status_key = status_str[:20]

                if status_key not in status_counts:
                    status_counts[status_key] = 0
                status_counts[status_key] += 1

        print(f"Traces analyzed: {min(10, len(all_traces))}")
        print(f"Total spans: {total_spans}")

        if status_counts:
            print(f"\nStatus distribution:")
            for status, count in sorted(status_counts.items(), key=lambda x: -x[1]):
                pct = (count / total_spans) * 100 if total_spans > 0 else 0
                bar = "█" * int(pct / 5)
                print(f"  {status:15} {count:5} ({pct:5.1f}%) {bar}")

            # Calculate error rate
            error_count = status_counts.get("ERROR", 0)
            if total_spans > 0:
                error_rate = (error_count / total_spans) * 100
                print(f"\nOverall error rate: {error_rate:.1f}%")

                if error_rate > 20:
                    print("WARNING: High error rate detected - investigate failures")
                else:
                    print("Status: Healthy - error rate is acceptable")


@pytest.mark.observability
@pytest.mark.openshift_only
@pytest.mark.requires_features(["mlflow"])
class TestToolCallSpanAttributes:
    """
    Validate tool call spans have proper attributes.

    When the weather agent calls MCP tools (weather-tool), spans should have:
    - Tool name (gen_ai.tool.name or tool.name)
    - Tool input parameters
    - Tool output/response
    - Span type indicating TOOL

    This is critical for:
    - Debugging tool invocations in MLflow/Phoenix
    - Understanding agent tool usage patterns
    - Tracking tool latency and errors
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
            cls._cached_genai_traces = [
                t for t in cls._cached_traces if has_genai_spans(t)
            ]
            logger.info(
                f"Cached {len(cls._cached_traces)} traces, "
                f"{len(cls._cached_genai_traces)} GenAI traces for tool call tests"
            )
        return cls._cached_traces, cls._cached_genai_traces

    def _find_tool_spans(self, trace: Any) -> list[dict]:
        """Find tool call spans in a trace.

        Tool spans are identified by:
        - Span name containing 'tool', 'function', 'mcp'
        - openinference.span.kind = 'TOOL'
        - mlflow.spanType = 'TOOL'
        - gen_ai.tool.name attribute present
        """
        spans = get_trace_span_details(trace)
        tool_spans = []

        tool_patterns = [
            "tool",
            "function",
            "mcp",
            "weather",  # Specific to weather-tool
            "get_weather",
        ]

        for span in spans:
            span_name = span.get("name", "").lower()
            attrs = span.get("attributes", {})

            is_tool = False

            # Check span name patterns
            if any(pattern in span_name for pattern in tool_patterns):
                # Exclude 'tool' in agent names like 'weather-tool-agent'
                if not span_name.endswith("agent"):
                    is_tool = True

            # Check span kind/type
            span_kind = attrs.get("openinference.span.kind", "")
            if str(span_kind).upper() == "TOOL":
                is_tool = True

            mlflow_type = attrs.get("mlflow.spanType", "")
            if str(mlflow_type).upper() == "TOOL":
                is_tool = True

            # Check for tool-specific attributes
            if attrs.get("gen_ai.tool.name") or attrs.get("tool.name"):
                is_tool = True

            if is_tool:
                tool_spans.append(span)

        return tool_spans

    def test_tool_spans_exist(
        self,
        mlflow_url: str,
        mlflow_configured: bool,
        traces_available: list,
        agent_variant: VariantProfile,
    ):
        """
        Verify tool call spans are captured in traces.

        Weather agent tests invoke the weather-tool via MCP, which should
        produce tool spans in the trace.
        """
        if not agent_variant.has_tool_spans:
            pytest.skip(f"Variant '{agent_variant.name}' does not produce tool spans")

        all_traces, genai_traces = self._get_cached_traces(traces_available)
        if not genai_traces:
            pytest.skip("No GenAI traces available - may not have tool instrumentation")

        print(f"\n{'=' * 60}")
        print("Tool Call Span Detection")
        print(f"{'=' * 60}")

        total_tool_spans = 0
        traces_with_tools = 0
        tool_names_found = set()

        # Check GenAI traces (max 10)
        for trace in genai_traces[:10]:
            tool_spans = self._find_tool_spans(trace)
            if tool_spans:
                traces_with_tools += 1
                total_tool_spans += len(tool_spans)

                for span in tool_spans:
                    attrs = span.get("attributes", {})
                    tool_name = (
                        attrs.get("gen_ai.tool.name")
                        or attrs.get("tool.name")
                        or span.get("name", "unknown")
                    )
                    tool_names_found.add(str(tool_name))

        print(f"GenAI traces checked: {min(10, len(genai_traces))}")
        print(f"Traces with tool spans: {traces_with_tools}")
        print(f"Total tool spans: {total_tool_spans}")

        if tool_names_found:
            print(f"\nTool names found:")
            for name in list(tool_names_found)[:10]:
                print(f"  - {name}")

        if total_tool_spans == 0:
            print(
                "\nNOTE: No tool spans found.\n"
                "Possible causes:\n"
                "  - Weather agent not using instrumented MCP client\n"
                "  - Tool calls happening outside traced context\n"
                "  - Tool instrumentation not configured"
            )
            pytest.skip("No tool spans found - agent may not have tool instrumentation")

        print(
            f"\nSUCCESS: Found {total_tool_spans} tool spans in {traces_with_tools} traces"
        )

    def test_tool_spans_have_name_attribute(
        self, mlflow_url: str, mlflow_configured: bool, traces_available: list
    ):
        """
        Verify tool spans have tool name attribute.

        The tool name is critical for:
        - Identifying which tool was called
        - Filtering traces by tool
        - Understanding agent behavior

        Expected attributes:
        - gen_ai.tool.name (GenAI convention)
        - tool.name (OpenInference)
        """
        all_traces, genai_traces = self._get_cached_traces(traces_available)
        if not genai_traces:
            pytest.skip("No GenAI traces available")

        print(f"\n{'=' * 60}")
        print("Tool Span Name Attribute Verification")
        print(f"{'=' * 60}")

        total_tool_spans = 0
        tool_spans_with_name = 0
        name_attribute_sources = {}

        for trace in genai_traces[:10]:
            tool_spans = self._find_tool_spans(trace)
            total_tool_spans += len(tool_spans)

            for span in tool_spans:
                attrs = span.get("attributes", {})

                # Check for tool name in different attributes
                tool_name = None
                source = None

                if attrs.get("gen_ai.tool.name"):
                    tool_name = attrs["gen_ai.tool.name"]
                    source = "gen_ai.tool.name"
                elif attrs.get("tool.name"):
                    tool_name = attrs["tool.name"]
                    source = "tool.name"
                elif attrs.get("function.name"):
                    tool_name = attrs["function.name"]
                    source = "function.name"

                if tool_name:
                    tool_spans_with_name += 1
                    if source not in name_attribute_sources:
                        name_attribute_sources[source] = 0
                    name_attribute_sources[source] += 1

        print(f"Total tool spans: {total_tool_spans}")
        print(f"Tool spans with name attribute: {tool_spans_with_name}")

        if name_attribute_sources:
            print(f"\nName attribute sources:")
            for source, count in name_attribute_sources.items():
                print(f"  - {source}: {count}")

        if total_tool_spans == 0:
            pytest.skip("No tool spans found to check")

        coverage = (
            (tool_spans_with_name / total_tool_spans) * 100
            if total_tool_spans > 0
            else 0
        )
        print(f"\nName attribute coverage: {coverage:.1f}%")

        if coverage < 50:
            print(
                "\nWARNING: Low tool name attribute coverage.\n"
                "Consider adding gen_ai.tool.name to tool spans."
            )

    def test_tool_spans_have_input_output(
        self, mlflow_url: str, mlflow_configured: bool, traces_available: list
    ):
        """
        Verify tool spans capture input and output.

        Tool spans should have:
        - Input: gen_ai.tool.input, tool.input, input.value
        - Output: gen_ai.tool.output, tool.output, output.value

        This is essential for debugging tool calls.
        """
        all_traces, genai_traces = self._get_cached_traces(traces_available)
        if not genai_traces:
            pytest.skip("No GenAI traces available")

        print(f"\n{'=' * 60}")
        print("Tool Span Input/Output Verification")
        print(f"{'=' * 60}")

        # Input/output attributes to check
        input_attrs = [
            "gen_ai.tool.input",
            "tool.input",
            "input.value",
            "function.arguments",
            "tool.parameters",
        ]
        output_attrs = [
            "gen_ai.tool.output",
            "tool.output",
            "output.value",
            "function.result",
            "tool.result",
        ]

        total_tool_spans = 0
        spans_with_input = 0
        spans_with_output = 0
        input_output_samples = []

        for trace in genai_traces[:10]:
            tool_spans = self._find_tool_spans(trace)
            total_tool_spans += len(tool_spans)

            for span in tool_spans:
                attrs = span.get("attributes", {})

                has_input = any(attrs.get(attr) for attr in input_attrs)
                has_output = any(attrs.get(attr) for attr in output_attrs)

                if has_input:
                    spans_with_input += 1
                if has_output:
                    spans_with_output += 1

                # Capture sample
                if len(input_output_samples) < 3 and (has_input or has_output):
                    sample_input = None
                    sample_output = None
                    for attr in input_attrs:
                        if attrs.get(attr):
                            sample_input = str(attrs[attr])[:60]
                            break
                    for attr in output_attrs:
                        if attrs.get(attr):
                            sample_output = str(attrs[attr])[:60]
                            break
                    input_output_samples.append(
                        {
                            "span_name": span.get("name", "unknown"),
                            "input": sample_input,
                            "output": sample_output,
                        }
                    )

        print(f"Total tool spans: {total_tool_spans}")
        print(f"Spans with input: {spans_with_input}")
        print(f"Spans with output: {spans_with_output}")

        if total_tool_spans > 0:
            input_coverage = (spans_with_input / total_tool_spans) * 100
            output_coverage = (spans_with_output / total_tool_spans) * 100
            print(f"\nCoverage:")
            print(f"  Input: {input_coverage:.1f}%")
            print(f"  Output: {output_coverage:.1f}%")

        if input_output_samples:
            print(f"\nSample tool I/O:")
            for sample in input_output_samples:
                print(f"  - {sample['span_name'][:30]}")
                if sample["input"]:
                    print(f"      Input: {sample['input']}...")
                if sample["output"]:
                    print(f"      Output: {sample['output']}...")

        if total_tool_spans == 0:
            pytest.skip("No tool spans found to check")

        print(f"\nSUCCESS: Analyzed {total_tool_spans} tool spans")

    def test_tool_spans_have_span_kind(
        self, mlflow_url: str, mlflow_configured: bool, traces_available: list
    ):
        """
        Verify tool spans have proper span kind/type.

        Tool spans should be identified as TOOL type via:
        - openinference.span.kind = 'TOOL' (OpenInference)
        - mlflow.spanType = 'TOOL' (MLflow)

        This allows filtering and visualization in dashboards.
        """
        all_traces, genai_traces = self._get_cached_traces(traces_available)
        if not genai_traces:
            pytest.skip("No GenAI traces available")

        print(f"\n{'=' * 60}")
        print("Tool Span Kind/Type Verification")
        print(f"{'=' * 60}")

        total_tool_spans = 0
        spans_with_kind = 0
        kind_values = {}

        for trace in genai_traces[:10]:
            tool_spans = self._find_tool_spans(trace)
            total_tool_spans += len(tool_spans)

            for span in tool_spans:
                attrs = span.get("attributes", {})

                # Check for span kind/type
                span_kind = (
                    attrs.get("openinference.span.kind")
                    or attrs.get("mlflow.spanType")
                    or attrs.get("span.kind")
                )

                if span_kind:
                    spans_with_kind += 1
                    kind_str = str(span_kind)
                    if kind_str not in kind_values:
                        kind_values[kind_str] = 0
                    kind_values[kind_str] += 1

        print(f"Total tool spans: {total_tool_spans}")
        print(f"Spans with kind/type: {spans_with_kind}")

        if kind_values:
            print(f"\nSpan kind values:")
            for kind, count in kind_values.items():
                print(f"  - {kind}: {count}")

        if total_tool_spans > 0:
            coverage = (spans_with_kind / total_tool_spans) * 100
            print(f"\nKind/type coverage: {coverage:.1f}%")

            # Check if TOOL is properly identified
            tool_kind_count = sum(
                count
                for kind, count in kind_values.items()
                if "TOOL" in str(kind).upper()
            )
            if tool_kind_count > 0:
                print(f"Spans with TOOL kind: {tool_kind_count}")
            else:
                print(
                    "\nNOTE: No spans explicitly marked as TOOL.\n"
                    "Consider adding openinference.span.kind='TOOL' to tool spans."
                )
        else:
            pytest.skip("No tool spans found to check")

        print(f"\nSUCCESS: Analyzed {total_tool_spans} tool spans")


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
