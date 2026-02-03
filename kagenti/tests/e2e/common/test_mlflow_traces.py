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
        return True
    except ImportError:
        logger.error("MLflow package not installed. Install with: pip install mlflow")
        return False
    except Exception as e:
        logger.error(f"Failed to configure MLflow client: {e}")
        return False


def get_all_traces() -> list[dict[str, Any]]:
    """Get all traces from MLflow using Python client."""
    try:
        import mlflow

        client = mlflow.MlflowClient()

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
    except Exception as e:
        logger.error(f"Failed to get traces: {e}")
        return []


def is_weather_agent_trace(trace: Any) -> bool:
    """Check if a trace is from the weather agent.

    Examines span resource attributes and span names to identify
    traces from the weather agent.
    """
    try:
        import mlflow

        client = mlflow.MlflowClient()

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


def find_weather_agent_traces() -> list[Any]:
    """Find all traces from the weather agent."""
    all_traces = get_all_traces()
    weather_traces = []

    for trace in all_traces:
        if is_weather_agent_trace(trace):
            weather_traces.append(trace)

    return weather_traces


def get_trace_span_details(trace: Any) -> list[dict[str, Any]]:
    """Get span details for a trace."""
    try:
        import mlflow

        client = mlflow.MlflowClient()

        trace_info = trace.info if hasattr(trace, "info") else trace
        request_id = (
            trace_info.request_id
            if hasattr(trace_info, "request_id")
            else trace_info.get("request_id")
        )

        if not request_id:
            return []

        trace_data = client.get_trace(request_id)
        if not trace_data or not hasattr(trace_data, "data"):
            return []

        spans = trace_data.data.spans if hasattr(trace_data.data, "spans") else []

        span_details = []
        for span in spans:
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

        return span_details

    except Exception as e:
        logger.warning(f"Error getting span details: {e}")
        return []


@pytest.fixture(scope="module")
def mlflow_url():
    """Get MLflow URL for tests."""
    url = get_mlflow_url()
    if not url:
        pytest.skip("MLflow URL not available")
    return url


@pytest.fixture(scope="module")
def mlflow_client_token(k8s_client):
    """Get OAuth2 token for MLflow using client credentials flow.

    Reads MLflow OAuth secret from K8s and uses client credentials grant
    to get an access token. This is required because mlflow-oidc-auth needs
    a token issued for the 'mlflow' client, not 'admin-cli'.

    Returns:
        str: Access token, or None if auth is not configured
    """
    import base64

    import requests
    from kubernetes.client.rest import ApiException

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
def mlflow_configured(mlflow_url, mlflow_client_token):
    """Configure MLflow client for tests with Keycloak authentication.

    Sets MLFLOW_TRACKING_TOKEN for bearer token auth when MLflow has OIDC enabled.
    Token must be set BEFORE importing/configuring MLflow client.
    """
    # Disable SSL verification for self-signed certs on OpenShift
    verify_ssl = os.getenv("MLFLOW_VERIFY_SSL", "true").lower() != "false"
    if not verify_ssl:
        import urllib3

        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        os.environ["MLFLOW_TRACKING_INSECURE_TLS"] = "true"

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
