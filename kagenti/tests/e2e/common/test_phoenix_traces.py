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
Phoenix LLM Traces E2E Tests.

Validates that weather agent traces are captured in Phoenix after E2E tests run.
These tests MUST run AFTER other E2E tests (especially test_agent_conversation.py)
which generate the traces by invoking the weather agent.

The test is marked with @pytest.mark.observability to ensure it runs in phase 2
of the two-phase test execution:
  - Phase 1: pytest -m "not observability"  (runs weather agent tests, generates traces)
  - Phase 2: pytest -m "observability"      (validates traces in Phoenix)

Usage:
    # Run with other observability tests (after main E2E tests)
    pytest kagenti/tests/e2e/ -v -m "observability"

    # Standalone debugging
    python kagenti/tests/e2e/test_phoenix_traces.py
"""

import os
import subprocess
import time

import httpx
import pytest


def get_phoenix_url() -> str | None:
    """Get Phoenix URL from environment or auto-detect from cluster."""
    url = os.getenv("PHOENIX_URL")
    if url:
        return url

    # Try to get from OpenShift route
    try:
        result = subprocess.run(
            [
                "oc",
                "get",
                "route",
                "phoenix",
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
    return "http://phoenix.localtest.me:8080"


class PhoenixClient:
    """Client for Phoenix REST API to query traces."""

    def __init__(self, base_url: str, verify_ssl: bool = True):
        self.base_url = base_url.rstrip("/")
        self.verify_ssl = verify_ssl
        self.client = httpx.Client(verify=verify_ssl, timeout=30.0)

    def health_check(self) -> bool:
        """Check if Phoenix is accessible."""
        try:
            # Phoenix serves UI at root
            response = self.client.get(self.base_url)
            return response.status_code == 200
        except httpx.RequestError:
            return False

    def get_projects(self) -> list[dict]:
        """Get all projects from Phoenix."""
        try:
            response = self.client.get(f"{self.base_url}/v1/projects")
            if response.status_code == 200:
                return response.json().get("data", [])
            return []
        except httpx.RequestError:
            return []

    def get_traces(self, project_name: str = "default", limit: int = 100) -> list[dict]:
        """Get traces for a project."""
        try:
            response = self.client.get(
                f"{self.base_url}/v1/projects/{project_name}/traces",
                params={"limit": limit},
            )
            if response.status_code == 200:
                return response.json().get("data", [])
            return []
        except httpx.RequestError:
            return []

    def get_all_traces(self) -> list[dict]:
        """Get all traces across all projects."""
        all_traces = []
        projects = self.get_projects()

        # If no projects, try default
        if not projects:
            return self.get_traces("default")

        for project in projects:
            project_name = project.get("name", "default")
            traces = self.get_traces(project_name)
            all_traces.extend(traces)

        return all_traces

    def get_trace_spans(self, trace_id: str) -> list[dict]:
        """Get spans for a specific trace."""
        try:
            response = self.client.get(f"{self.base_url}/v1/traces/{trace_id}/spans")
            if response.status_code == 200:
                return response.json().get("data", [])
            return []
        except httpx.RequestError:
            return []

    def find_llm_traces(self) -> list[dict]:
        """Find traces that contain LLM-related spans."""
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
            trace_id = trace.get("id") or trace.get("trace_id")
            if not trace_id:
                continue

            # Check trace name/metadata
            trace_name = (trace.get("name") or "").lower()
            if any(pattern in trace_name for pattern in llm_patterns):
                llm_traces.append(trace)
                continue

            # Check spans
            spans = self.get_trace_spans(trace_id)
            for span in spans:
                span_name = (span.get("name") or "").lower()
                if any(pattern in span_name for pattern in llm_patterns):
                    llm_traces.append(trace)
                    break

        return llm_traces


@pytest.fixture(scope="module")
def phoenix_client():
    """Create Phoenix client for tests."""
    url = get_phoenix_url()
    if not url:
        pytest.skip("Phoenix URL not available")

    # Disable SSL verification for self-signed certs on OpenShift
    verify_ssl = os.getenv("PHOENIX_VERIFY_SSL", "true").lower() != "false"
    return PhoenixClient(url, verify_ssl=verify_ssl)


@pytest.mark.observability
@pytest.mark.requires_features(["otel"])
class TestPhoenixConnectivity:
    """Test Phoenix service is accessible."""

    def test_phoenix_health(self, phoenix_client: PhoenixClient):
        """Verify Phoenix is accessible and healthy."""
        assert phoenix_client.health_check(), (
            f"Cannot connect to Phoenix at {phoenix_client.base_url}. "
            "Check that Phoenix is deployed and accessible."
        )


@pytest.mark.observability
@pytest.mark.requires_features(["otel"])
class TestWeatherAgentTracesInPhoenix:
    """
    Validate weather agent traces are captured in Phoenix.

    These tests verify that traces from test_agent_conversation.py
    (which queries the weather agent) are visible in Phoenix.
    """

    def test_phoenix_has_traces(self, phoenix_client: PhoenixClient):
        """Verify Phoenix received traces from E2E tests."""
        if not phoenix_client.health_check():
            pytest.skip("Phoenix not accessible")

        # Give traces time to be exported (OTEL batching)
        time.sleep(2)

        traces = phoenix_client.get_all_traces()
        trace_count = len(traces)

        print(f"\n{'=' * 60}")
        print("Phoenix Trace Summary")
        print(f"{'=' * 60}")
        print(f"Total traces found: {trace_count}")

        # List projects
        projects = phoenix_client.get_projects()
        print(f"Projects: {len(projects)}")
        for proj in projects:
            print(f"  - {proj.get('name', 'default')}")

        assert trace_count > 0, (
            "No traces found in Phoenix. "
            "Expected traces from weather agent E2E tests. "
            "Verify that:\n"
            "  1. test_agent_conversation.py ran before this test\n"
            "  2. Weather agent is instrumented (openinference-instrumentation-langchain)\n"
            "  3. OTEL_EXPORTER_OTLP_ENDPOINT is set in weather agent deployment\n"
            "  4. OTEL collector filter passes openinference spans to Phoenix"
        )

    def test_weather_agent_llm_traces(self, phoenix_client: PhoenixClient):
        """Verify LLM/LangChain traces from weather agent are in Phoenix."""
        if not phoenix_client.health_check():
            pytest.skip("Phoenix not accessible")

        llm_traces = phoenix_client.find_llm_traces()

        print(f"\n{'=' * 60}")
        print("Weather Agent LLM Traces in Phoenix")
        print(f"{'=' * 60}")
        print(f"LLM-related traces found: {len(llm_traces)}")

        # Print sample trace info
        for i, trace in enumerate(llm_traces[:5]):
            trace_id = trace.get("id") or trace.get("trace_id") or "unknown"
            trace_name = trace.get("name", "unnamed")
            print(f"  [{i + 1}] id={trace_id[:16]}... name={trace_name}")

        assert len(llm_traces) > 0, (
            "No LLM traces found in Phoenix. "
            "Expected LangChain/LangGraph traces from weather agent. "
            "The weather agent uses LangGraph and should produce traces with:\n"
            "  - Span names containing 'langchain', 'langgraph', 'agent', 'chain'\n"
            "  - Instrumentation scope 'openinference.instrumentation.langchain'\n\n"
            "Verify that:\n"
            "  1. Weather agent has openinference-instrumentation-langchain installed\n"
            "  2. OTEL_EXPORTER_OTLP_ENDPOINT points to otel-collector\n"
            "  3. OTEL collector filter passes openinference spans"
        )

        print(f"\nSUCCESS: Found {len(llm_traces)} LLM traces from weather agent")

    def test_trace_has_spans(self, phoenix_client: PhoenixClient):
        """Verify traces have proper span structure."""
        if not phoenix_client.health_check():
            pytest.skip("Phoenix not accessible")

        traces = phoenix_client.get_all_traces()
        if not traces:
            pytest.skip("No traces available to inspect")

        # Get first trace with spans
        for trace in traces[:5]:
            trace_id = trace.get("id") or trace.get("trace_id")
            if not trace_id:
                continue

            spans = phoenix_client.get_trace_spans(trace_id)
            if spans:
                print(f"\n{'=' * 60}")
                print(f"Trace Spans: {trace_id[:16]}...")
                print(f"{'=' * 60}")
                print(f"Span count: {len(spans)}")

                for span in spans[:10]:
                    span_name = span.get("name", "unnamed")
                    span_kind = span.get("span_kind", "unknown")
                    print(f"  - {span_name} ({span_kind})")

                assert len(spans) > 0, "Trace has no spans"
                print(f"\nSUCCESS: Trace has {len(spans)} spans")
                return

        pytest.skip("No traces with spans found")


def main():
    """Standalone execution for debugging Phoenix traces."""
    import argparse

    parser = argparse.ArgumentParser(description="Debug Phoenix traces")
    parser.add_argument("--url", help="Phoenix URL (default: auto-detect)")
    parser.add_argument(
        "--no-verify-ssl", action="store_true", help="Disable SSL verification"
    )
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose output")
    args = parser.parse_args()

    url = args.url or get_phoenix_url()
    if not url:
        print("ERROR: Could not determine Phoenix URL")
        return 1

    print(f"Phoenix URL: {url}")

    client = PhoenixClient(url, verify_ssl=not args.no_verify_ssl)

    # Health check
    if not client.health_check():
        print(f"ERROR: Cannot connect to Phoenix at {url}")
        return 1
    print("Phoenix: Connected\n")

    # Get projects
    projects = client.get_projects()
    print(f"Projects: {len(projects)}")
    for proj in projects:
        print(f"  - {proj.get('name', 'default')}")

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
            trace_id = trace.get("id") or trace.get("trace_id")
            print(f"\nTrace: {trace_id}")
            spans = client.get_trace_spans(trace_id)
            for span in spans[:5]:
                print(f"  - {span.get('name', 'unnamed')}")

    return 0


if __name__ == "__main__":
    exit(main())
