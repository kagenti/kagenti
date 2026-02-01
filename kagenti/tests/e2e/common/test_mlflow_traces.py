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
MLflow LLM Traces E2E Tests.

Validates that weather agent traces are captured in MLflow after E2E tests run.
These tests MUST run AFTER other E2E tests (especially test_agent_conversation.py)
which generate the traces by invoking the weather agent.

The test is marked with @pytest.mark.observability to ensure it runs in phase 2
of the two-phase test execution:
  - Phase 1: pytest -m "not observability"  (runs weather agent tests, generates traces)
  - Phase 2: pytest -m "observability"      (validates traces in MLflow)

Usage:
    # Run with other observability tests (after main E2E tests)
    pytest kagenti/tests/e2e/ -v -m "observability"

    # Standalone debugging
    python kagenti/tests/e2e/test_mlflow_traces.py
"""

import logging
import os
import subprocess
import time

import httpx
import pytest

logger = logging.getLogger(__name__)


def get_keycloak_url() -> str | None:
    """Get Keycloak URL from environment or auto-detect from cluster."""
    url = os.getenv("KEYCLOAK_URL")
    if url:
        return url

    # Try to get from OpenShift route
    try:
        result = subprocess.run(
            [
                "oc",
                "get",
                "route",
                "keycloak",
                "-n",
                "keycloak",
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
    return "http://keycloak.localtest.me:8080"


def get_mlflow_url() -> str | None:
    """Get MLflow URL from environment or auto-detect from cluster."""
    url = os.getenv("MLFLOW_URL")
    if url:
        return url

    # Try to get from OpenShift route
    try:
        result = subprocess.run(
            [
                "oc",
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


def get_keycloak_token(
    keycloak_url: str,
    realm: str = "demo",
    client_id: str = "mlflow",
    client_secret: str | None = None,
    verify_ssl: bool = True,
) -> str | None:
    """Get access token from Keycloak using client credentials flow."""
    if not client_secret:
        client_secret = os.getenv("MLFLOW_CLIENT_SECRET")
        if not client_secret:
            logger.warning("No MLFLOW_CLIENT_SECRET set, skipping authentication")
            return None

    token_url = f"{keycloak_url}/realms/{realm}/protocol/openid-connect/token"

    try:
        response = httpx.post(
            token_url,
            data={
                "grant_type": "client_credentials",
                "client_id": client_id,
                "client_secret": client_secret,
            },
            verify=verify_ssl,
            timeout=30.0,
        )
        response.raise_for_status()
        return response.json().get("access_token")
    except httpx.HTTPError as e:
        logger.warning(f"Failed to get Keycloak token: {e}")
        return None


class MLflowClient:
    """Client for MLflow REST API to query traces."""

    def __init__(
        self,
        base_url: str,
        verify_ssl: bool = True,
        access_token: str | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.verify_ssl = verify_ssl
        self.access_token = access_token

        headers = {}
        if access_token:
            headers["Authorization"] = f"Bearer {access_token}"

        self.client = httpx.Client(
            verify=verify_ssl,
            timeout=30.0,
            headers=headers,
        )

    def health_check(self) -> bool:
        """Check if MLflow is accessible."""
        try:
            # Use /version endpoint which is typically unauthenticated
            response = self.client.get(f"{self.base_url}/version")
            return response.status_code == 200
        except httpx.RequestError:
            return False

    def get_experiments(self) -> list[dict]:
        """Get all experiments from MLflow."""
        try:
            response = self.client.get(
                f"{self.base_url}/api/2.0/mlflow/experiments/search"
            )
            if response.status_code == 200:
                return response.json().get("experiments", [])
            if response.status_code == 401:
                logger.warning(
                    "MLflow returned 401 Unauthorized - token may be invalid"
                )
            return []
        except httpx.RequestError:
            return []

    def search_traces(
        self,
        experiment_ids: list[str] | None = None,
        max_results: int = 100,
    ) -> list[dict]:
        """Search for traces in MLflow."""
        try:
            params = {"max_results": max_results}
            if experiment_ids:
                params["experiment_ids"] = ",".join(experiment_ids)

            response = self.client.get(
                f"{self.base_url}/api/2.0/mlflow/traces",
                params=params,
            )
            if response.status_code == 200:
                return response.json().get("traces", [])
            return []
        except httpx.RequestError:
            return []

    def get_all_traces(self) -> list[dict]:
        """Get all traces across all experiments."""
        all_traces = []
        experiments = self.get_experiments()

        # If no experiments, try default
        if not experiments:
            return self.search_traces()

        for exp in experiments:
            exp_id = exp.get("experiment_id")
            if exp_id:
                traces = self.search_traces([exp_id])
                all_traces.extend(traces)
        return all_traces

    def get_trace_details(self, request_id: str) -> dict | None:
        """Get detailed trace info including spans."""
        try:
            response = self.client.get(
                f"{self.base_url}/api/2.0/mlflow/traces/{request_id}"
            )
            if response.status_code == 200:
                return response.json()
            return None
        except httpx.RequestError:
            return None

    def find_traces_with_span_name(self, name_pattern: str) -> list[dict]:
        """Find traces that contain spans matching a name pattern."""
        matching_traces = []
        traces = self.get_all_traces()

        for trace in traces:
            request_id = trace.get("request_id")
            if not request_id:
                continue

            # Get trace details to inspect spans
            details = self.get_trace_details(request_id)
            if not details:
                continue

            # Check span names
            spans = details.get("spans", [])
            for span in spans:
                span_name = span.get("name", "").lower()
                if name_pattern.lower() in span_name:
                    matching_traces.append(trace)
                    break

        return matching_traces

    def find_llm_traces(self) -> list[dict]:
        """Find traces that contain LLM-related spans (LangChain, OpenAI, etc.)."""
        llm_patterns = [
            "langchain",
            "langgraph",
            "openai",
            "anthropic",
            "llm",
            "chat",
            "completion",
            "agent",
            "chain",
        ]

        all_traces = self.get_all_traces()
        llm_traces = []

        for trace in all_traces:
            request_id = trace.get("request_id")
            if not request_id:
                continue

            details = self.get_trace_details(request_id)
            if not details:
                continue

            # Check if any span matches LLM patterns
            spans = details.get("spans", [])
            is_llm_trace = False

            for span in spans:
                span_name = span.get("name", "").lower()
                span_attributes = span.get("attributes", {})

                # Check span name
                if any(pattern in span_name for pattern in llm_patterns):
                    is_llm_trace = True
                    break

                # Check instrumentation scope
                scope = span.get("instrumentation_scope", {})
                scope_name = scope.get("name", "").lower()
                if "openinference" in scope_name or "langchain" in scope_name:
                    is_llm_trace = True
                    break

            if is_llm_trace:
                llm_traces.append(trace)

        return llm_traces


@pytest.fixture(scope="module")
def mlflow_client():
    """Create MLflow client for tests."""
    url = get_mlflow_url()
    if not url:
        pytest.skip("MLflow URL not available")

    # Disable SSL verification for self-signed certs on OpenShift
    verify_ssl = os.getenv("MLFLOW_VERIFY_SSL", "true").lower() != "false"

    # Get Keycloak token for authenticated access
    access_token = None
    keycloak_url = get_keycloak_url()
    if keycloak_url and os.getenv("MLFLOW_CLIENT_SECRET"):
        access_token = get_keycloak_token(
            keycloak_url,
            realm=os.getenv("KEYCLOAK_REALM", "demo"),
            client_id=os.getenv("MLFLOW_CLIENT_ID", "mlflow"),
            verify_ssl=verify_ssl,
        )
        if access_token:
            logger.info("Successfully obtained Keycloak token for MLflow")
        else:
            logger.warning("Could not get Keycloak token, proceeding without auth")

    return MLflowClient(url, verify_ssl=verify_ssl, access_token=access_token)


@pytest.mark.observability
@pytest.mark.requires_features(["mlflow"])
class TestMLflowConnectivity:
    """Test MLflow service is accessible."""

    def test_mlflow_health(self, mlflow_client: MLflowClient):
        """Verify MLflow is accessible and healthy."""
        assert mlflow_client.health_check(), (
            f"Cannot connect to MLflow at {mlflow_client.base_url}. "
            "Check that MLflow is deployed and accessible."
        )


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

    def test_mlflow_has_traces(self, mlflow_client: MLflowClient):
        """Verify MLflow received traces from E2E tests."""
        if not mlflow_client.health_check():
            pytest.skip("MLflow not accessible")

        # Give traces time to be exported (OTEL batching)
        time.sleep(2)

        traces = mlflow_client.get_all_traces()
        trace_count = len(traces)

        print(f"\n{'=' * 60}")
        print("MLflow Trace Summary")
        print(f"{'=' * 60}")
        print(f"Total traces found: {trace_count}")

        # List experiments
        experiments = mlflow_client.get_experiments()
        print(f"Experiments: {len(experiments)}")
        for exp in experiments:
            print(f"  - {exp.get('name', 'Default')} (id: {exp.get('experiment_id')})")

        assert trace_count > 0, (
            "No traces found in MLflow. "
            "Expected traces from weather agent E2E tests. "
            "Verify that:\n"
            "  1. test_agent_conversation.py ran before this test\n"
            "  2. Weather agent is instrumented (openinference-instrumentation-langchain)\n"
            "  3. OTEL collector has mlflow exporter configured\n"
            "  4. MLflow is enabled in values.yaml (components.mlflow.enabled: true)"
        )

    def test_weather_agent_llm_traces(self, mlflow_client: MLflowClient):
        """Verify LLM/LangChain traces from weather agent are in MLflow."""
        if not mlflow_client.health_check():
            pytest.skip("MLflow not accessible")

        llm_traces = mlflow_client.find_llm_traces()

        print(f"\n{'=' * 60}")
        print("Weather Agent LLM Traces in MLflow")
        print(f"{'=' * 60}")
        print(f"LLM-related traces found: {len(llm_traces)}")

        # Print sample trace info
        for i, trace in enumerate(llm_traces[:5]):
            request_id = trace.get("request_id", "unknown")
            timestamp = trace.get("timestamp_ms", 0)
            print(f"  [{i + 1}] request_id={request_id}, timestamp={timestamp}")

        assert len(llm_traces) > 0, (
            "No LLM traces found in MLflow. "
            "Expected LangChain/LangGraph traces from weather agent. "
            "The weather agent uses LangGraph and should produce traces with:\n"
            "  - Span names containing 'langchain', 'langgraph', 'agent', 'chain'\n"
            "  - Instrumentation scope 'openinference.instrumentation.langchain'\n\n"
            "Verify that:\n"
            "  1. Weather agent has openinference-instrumentation-langchain installed\n"
            "  2. OTEL_EXPORTER_OTLP_ENDPOINT is set in weather agent deployment\n"
            "  3. OTEL collector filter passes openinference spans to MLflow"
        )

        print(f"\nSUCCESS: Found {len(llm_traces)} LLM traces from weather agent")

    def test_trace_has_span_details(self, mlflow_client: MLflowClient):
        """Verify traces have proper span structure with attributes."""
        if not mlflow_client.health_check():
            pytest.skip("MLflow not accessible")

        traces = mlflow_client.get_all_traces()
        if not traces:
            pytest.skip("No traces available to inspect")

        # Get first trace details
        first_trace = traces[0]
        request_id = first_trace.get("request_id")
        if not request_id:
            pytest.skip("Trace missing request_id")

        details = mlflow_client.get_trace_details(request_id)

        print(f"\n{'=' * 60}")
        print(f"Trace Details: {request_id}")
        print(f"{'=' * 60}")

        assert details is not None, f"Could not get details for trace {request_id}"

        spans = details.get("spans", [])
        print(f"Spans in trace: {len(spans)}")

        assert len(spans) > 0, "Trace has no spans"

        # Print span hierarchy
        for span in spans[:10]:
            span_name = span.get("name", "unnamed")
            span_kind = span.get("kind", "unknown")
            duration_ns = span.get("end_time_unix_nano", 0) - span.get(
                "start_time_unix_nano", 0
            )
            duration_ms = duration_ns / 1_000_000

            print(f"  - {span_name} ({span_kind}) [{duration_ms:.1f}ms]")

        print(f"\nSUCCESS: Trace has {len(spans)} spans with proper structure")


def main():
    """Standalone execution for debugging MLflow traces."""
    import argparse

    parser = argparse.ArgumentParser(description="Debug MLflow traces")
    parser.add_argument("--url", help="MLflow URL (default: auto-detect)")
    parser.add_argument("--keycloak-url", help="Keycloak URL (default: auto-detect)")
    parser.add_argument("--client-secret", help="MLflow OAuth client secret")
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

    verify_ssl = not args.no_verify_ssl

    # Get Keycloak token if credentials provided
    access_token = None
    keycloak_url = args.keycloak_url or get_keycloak_url()
    client_secret = args.client_secret or os.getenv("MLFLOW_CLIENT_SECRET")
    if keycloak_url and client_secret:
        print(f"Keycloak URL: {keycloak_url}")
        access_token = get_keycloak_token(
            keycloak_url,
            client_secret=client_secret,
            verify_ssl=verify_ssl,
        )
        if access_token:
            print("Authentication: Token obtained")
        else:
            print("Authentication: Failed to get token")
    else:
        print("Authentication: Disabled (no client secret)")

    client = MLflowClient(url, verify_ssl=verify_ssl, access_token=access_token)

    # Health check
    if not client.health_check():
        print(f"ERROR: Cannot connect to MLflow at {url}")
        return 1
    print("MLflow: Connected\n")

    # Get experiments
    experiments = client.get_experiments()
    print(f"Experiments: {len(experiments)}")
    for exp in experiments:
        print(f"  - {exp.get('name', 'Default')} (id: {exp.get('experiment_id')})")

    # Get all traces
    traces = client.get_all_traces()
    print(f"\nTotal traces: {len(traces)}")

    # Find LLM traces
    llm_traces = client.find_llm_traces()
    print(f"LLM traces: {len(llm_traces)}")

    if args.verbose and traces:
        print("\n" + "=" * 60)
        print("Trace Details")
        print("=" * 60)
        for trace in traces[:3]:
            request_id = trace.get("request_id")
            print(f"\nTrace: {request_id}")
            details = client.get_trace_details(request_id)
            if details:
                spans = details.get("spans", [])
                for span in spans[:5]:
                    print(f"  - {span.get('name', 'unnamed')}")

    return 0


if __name__ == "__main__":
    exit(main())
