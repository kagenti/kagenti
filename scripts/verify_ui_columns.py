#!/usr/bin/env python3
"""
Verify UI Table Columns for MLflow and Phoenix.

This script checks what data is available for the trace table columns in both UIs.
It uses the APIs directly since the UIs are SPAs that load data via JavaScript.

Usage:
    # Set environment variables
    export MLFLOW_URL=https://mlflow-kagenti-system.apps.kagenti-hypershift-custom-mlflow.octo-emerging.redhataicoe.com
    export PHOENIX_URL=https://phoenix-kagenti-system.apps.kagenti-hypershift-custom-mlflow.octo-emerging.redhataicoe.com
    export KEYCLOAK_URL=https://keycloak-keycloak.apps.kagenti-hypershift-custom-mlflow.octo-emerging.redhataicoe.com

    # Run the script
    python scripts/verify_ui_columns.py
"""

import json
import os
import sys
import time
from dataclasses import dataclass
from typing import Any

import httpx


@dataclass
class ColumnStatus:
    """Status of a UI column."""

    name: str
    populated: bool
    sample_value: Any = None
    source_attribute: str = ""


class MLflowColumnChecker:
    """Check MLflow UI trace table columns."""

    # Expected columns in MLflow Traces table (from MLflow UI)
    EXPECTED_COLUMNS = [
        ("Trace ID", "trace_id"),
        ("Trace Name", "mlflow.traceName"),
        ("Request", "mlflow.spanInputs"),
        ("Response", "mlflow.spanOutputs"),
        ("Timestamp", "timestamp_ms"),
        ("Latency", "execution_time_ms"),
        ("Tokens", "mlflow.span.chat_usage"),
        ("Status", "status"),
        ("Session", "mlflow.trace.session"),
        ("User", "mlflow.user"),
        ("Source", "mlflow.source"),
    ]

    def __init__(self, base_url: str, keycloak_url: str | None = None):
        self.base_url = base_url.rstrip("/")
        self.keycloak_url = keycloak_url
        self.token = None
        self.token_expires = 0
        self.client = httpx.Client(verify=False, timeout=30.0)

    def _get_token(self) -> str | None:
        """Get OAuth token using client credentials from mlflow-oauth-secret."""
        if self.token and time.time() < self.token_expires - 5:
            return self.token

        # Try to get credentials from Kubernetes secret
        client_id = os.getenv("MLFLOW_CLIENT_ID")
        client_secret = os.getenv("MLFLOW_CLIENT_SECRET")
        token_url = os.getenv("MLFLOW_TOKEN_URL")

        if not all([client_id, client_secret, token_url]):
            # Try to read from Kubernetes
            try:
                import subprocess
                import base64

                result = subprocess.run(
                    [
                        "kubectl",
                        "get",
                        "secret",
                        "mlflow-oauth-secret",
                        "-n",
                        "kagenti-system",
                        "-o",
                        "json",
                    ],
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                if result.returncode == 0:
                    import json as json_module

                    secret = json_module.loads(result.stdout)
                    client_id = base64.b64decode(
                        secret["data"]["OIDC_CLIENT_ID"]
                    ).decode()
                    client_secret = base64.b64decode(
                        secret["data"]["OIDC_CLIENT_SECRET"]
                    ).decode()
                    token_url = base64.b64decode(
                        secret["data"]["OIDC_TOKEN_URL"]
                    ).decode()
                    print(f"  Got credentials from mlflow-oauth-secret")
            except Exception as e:
                print(f"  Warning: Could not read mlflow-oauth-secret: {e}")

        if not all([client_id, client_secret, token_url]):
            print("  Warning: No MLflow credentials available")
            return None

        try:
            response = self.client.post(
                token_url,
                data={
                    "grant_type": "client_credentials",
                    "client_id": client_id,
                    "client_secret": client_secret,
                },
            )
            if response.status_code == 200:
                data = response.json()
                self.token = data.get("access_token")
                expires_in = data.get("expires_in", 60)
                self.token_expires = time.time() + expires_in
                print(f"  Got MLflow token (expires in {expires_in}s)")
                return self.token
            else:
                print(f"  Warning: Token fetch failed: {response.status_code}")
        except Exception as e:
            print(f"  Warning: Token fetch failed: {e}")
        return None

    def get_traces(self, limit: int = 10) -> list[dict]:
        """Fetch traces using MLflow Python client."""
        token = self._get_token()
        if token:
            os.environ["MLFLOW_TRACKING_TOKEN"] = token
        os.environ["MLFLOW_TRACKING_URI"] = self.base_url
        os.environ["MLFLOW_TRACKING_INSECURE_TLS"] = "true"

        try:
            from mlflow import MlflowClient

            client = MlflowClient()

            # Get more traces to find ones with GenAI content
            traces = client.search_traces(experiment_ids=["0"], max_results=50)
            print(f"  Found {len(traces)} traces via MLflow client")

            # Filter for traces with GenAI or agent spans
            good_traces = []
            for trace in traces:
                spans = trace.data.spans or []
                for span in spans:
                    span_name = span.name or ""
                    attrs = span.attributes or {}
                    # Look for GenAI spans or spans with mlflow.spanInputs
                    if (
                        "gen_ai" in span_name.lower()
                        or "mlflow.spanInputs" in attrs
                        or "gen_ai.prompt" in attrs
                        or len(attrs) > 3
                    ):  # Spans with more attributes
                        good_traces.append(trace)
                        break
                if len(good_traces) >= limit:
                    break

            if good_traces:
                print(f"  Found {len(good_traces)} traces with GenAI/agent content")
                traces = good_traces[:limit]
            else:
                print(f"  No GenAI traces found, using first {limit} traces")
                traces = traces[:limit]

            # Convert to dicts for analysis
            result = []
            for trace in traces:
                trace_dict = {
                    "info": {
                        "request_id": trace.info.request_id,
                        "experiment_id": trace.info.experiment_id,
                        "timestamp_ms": trace.info.timestamp_ms,
                        "execution_time_ms": trace.info.execution_time_ms,
                        "status": str(trace.info.status),
                        "tags": [
                            {"key": k, "value": v}
                            for k, v in (trace.info.tags or {}).items()
                        ],
                        "request_metadata": [
                            {"key": k, "value": v}
                            for k, v in (trace.info.request_metadata or {}).items()
                        ],
                    },
                    "data": {
                        "spans": [
                            self._span_to_dict(s) for s in (trace.data.spans or [])
                        ]
                    },
                }
                result.append(trace_dict)
            return result
        except Exception as e:
            print(f"  Error fetching MLflow traces: {e}")
            import traceback

            traceback.print_exc()
            return []

    def _span_to_dict(self, span) -> dict:
        """Convert MLflow Span to dict."""
        return {
            "name": span.name,
            "span_id": span.span_id,
            "parent_id": span.parent_id,
            "status": str(span.status) if span.status else None,
            "attributes": span.attributes or {},
            "events": span.events or [],
        }

    def get_trace_info(self, trace_id: str) -> dict | None:
        """Get detailed trace info including tags and metadata."""
        headers = {}
        token = self._get_token()
        if token:
            headers["Authorization"] = f"Bearer {token}"

        try:
            response = self.client.get(
                f"{self.base_url}/api/2.0/mlflow/traces/{trace_id}/info",
                headers=headers,
            )
            if response.status_code == 200:
                return response.json()
            return None
        except Exception:
            return None

    def check_columns(self) -> list[ColumnStatus]:
        """Check which columns are populated."""
        results = []
        traces = self.get_traces(limit=5)

        if not traces:
            print("  No traces found in MLflow!")
            return [
                ColumnStatus(name=col[0], populated=False, source_attribute=col[1])
                for col in self.EXPECTED_COLUMNS
            ]

        # Analyze first trace
        trace = traces[0]
        trace_id = trace.get("info", {}).get("request_id") or trace.get(
            "request_id", ""
        )

        # Get detailed info
        trace_info = self.get_trace_info(trace_id) if trace_id else None

        # Check each expected column
        info = trace.get("info", {})
        tags = {t["key"]: t["value"] for t in info.get("tags", [])}
        metadata = {m["key"]: m["value"] for m in info.get("request_metadata", [])}

        print(f"\n  Sample trace: {trace_id[:20]}...")
        print(f"  Tags: {list(tags.keys())}")
        print(f"  Metadata: {list(metadata.keys())}")

        # Also show span attributes - focus on spans with GenAI or mlflow attributes
        spans = trace.get("data", {}).get("spans", [])
        if spans:
            print(f"  Spans: {len(spans)}")

            # Find spans with interesting attributes
            interesting_spans = []
            for span in spans:
                span_name = span.get("name", "unnamed")
                span_attrs = span.get("attributes", {})
                # Look for GenAI spans or spans with important attributes
                if "gen_ai" in span_name.lower() or any(
                    k.startswith("gen_ai.")
                    or k.startswith("mlflow.span")
                    or k == "input.value"
                    for k in span_attrs.keys()
                ):
                    interesting_spans.append(span)

            # Find root span (no parent_id)
            root_span = None
            for span in spans:
                if not span.get("parent_id"):
                    root_span = span
                    break

            if root_span:
                print(f"\n  ROOT SPAN: {root_span.get('name')}")
                root_attrs = root_span.get("attributes", {})
                print(f"    Attributes: {list(root_attrs.keys())[:10]}")

                # Check if root has the required span attributes
                print(f"\n  ROOT SPAN - MLflow/GenAI Attributes Check:")
                for key in [
                    "mlflow.spanInputs",
                    "mlflow.spanOutputs",
                    "mlflow.spanType",
                    "gen_ai.prompt",
                    "gen_ai.completion",
                    "input.value",
                    "output.value",
                ]:
                    if key in root_attrs:
                        val = str(root_attrs[key])[:50]
                        print(f"    ✅ {key}: {val}...")
                    else:
                        print(f"    ❌ {key}: MISSING on root span")

                # Check resource-level attributes that should become trace metadata
                print(f"\n  TRACE-LEVEL - Tags and Metadata Check:")
                for key in [
                    "mlflow.trace.session",
                    "mlflow.traceName",
                    "mlflow.user",
                    "mlflow.source",
                ]:
                    found_in = None
                    if key in tags:
                        found_in = f"tags: {tags[key][:30]}..."
                    elif key in metadata:
                        found_in = f"metadata: {metadata[key][:30]}..."
                    elif key in root_attrs:
                        found_in = f"root span attrs: {str(root_attrs[key])[:30]}..."
                    if found_in:
                        print(f"    ✅ {key}: {found_in}")
                    else:
                        print(
                            f"    ❌ {key}: NOT FOUND in tags, metadata, or root span"
                        )

            if interesting_spans:
                print(
                    f"\n  Interesting spans with GenAI/MLflow attributes: {len(interesting_spans)}"
                )
                for i, span in enumerate(interesting_spans[:5]):
                    span_name = span.get("name", "unnamed")
                    span_attrs = span.get("attributes", {})
                    is_root = " (ROOT)" if not span.get("parent_id") else ""
                    print(f"    [{i}] {span_name}{is_root}")
                    # Show specific attributes we care about
                    for key in [
                        "mlflow.spanInputs",
                        "mlflow.spanOutputs",
                        "mlflow.spanType",
                        "gen_ai.prompt",
                        "gen_ai.completion",
                        "gen_ai.agent.name",
                        "input.value",
                        "output.value",
                    ]:
                        if key in span_attrs:
                            val = str(span_attrs[key])[:50]
                            print(f"        {key}: {val}...")
            else:
                print("  No spans with GenAI/mlflow.span* attributes found!")
                # Show first 3 spans for debugging
                for i, span in enumerate(spans[:3]):
                    span_name = span.get("name", "unnamed")
                    span_attrs = list(span.get("attributes", {}).keys())
                    print(f"    [{i}] {span_name}: {span_attrs[:8]}...")

        # Map columns to their values
        for col_name, attr_name in self.EXPECTED_COLUMNS:
            value = None

            # Check different sources
            if attr_name == "trace_id":
                value = trace_id
            elif attr_name == "timestamp_ms":
                value = info.get("timestamp_ms")
            elif attr_name == "execution_time_ms":
                value = info.get("execution_time_ms")
            elif attr_name == "status":
                value = info.get("status")
            elif attr_name in tags:
                value = tags.get(attr_name)
            elif attr_name in metadata:
                value = metadata.get(attr_name)
            else:
                # Check root span attributes
                spans = trace.get("data", {}).get("spans", [])
                if spans:
                    root_span = spans[0]  # Usually first span is root
                    span_attrs = root_span.get("attributes", {})
                    if attr_name in span_attrs:
                        value = span_attrs.get(attr_name)

            populated = value is not None and str(value).strip() != ""
            sample = (
                str(value)[:50] + "..." if value and len(str(value)) > 50 else value
            )
            results.append(
                ColumnStatus(
                    name=col_name,
                    populated=populated,
                    sample_value=sample,
                    source_attribute=attr_name,
                )
            )

        return results


class PhoenixColumnChecker:
    """Check Phoenix UI trace table columns."""

    # Expected columns in Phoenix Traces table
    EXPECTED_COLUMNS = [
        ("Trace ID", "traceId"),
        ("Span Name", "name"),
        ("Kind", "spanKind"),
        ("Input", "input.value"),
        ("Output", "output.value"),
        ("Model", "llm.model_name"),
        ("Total Tokens", "llm.token_count.total"),
        ("Prompt Tokens", "llm.token_count.prompt"),
        ("Completion Tokens", "llm.token_count.completion"),
        ("Latency", "latencyMs"),
        ("Status", "statusCode"),
    ]

    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")
        self.client = httpx.Client(verify=False, timeout=30.0)

    def _graphql_query(self, query: str) -> dict | None:
        """Execute GraphQL query."""
        try:
            response = self.client.post(
                f"{self.base_url}/graphql",
                json={"query": query},
                headers={"Content-Type": "application/json"},
            )
            if response.status_code == 200:
                result = response.json()
                if "errors" not in result or not result["errors"]:
                    return result.get("data")
            return None
        except Exception as e:
            print(f"  GraphQL error: {e}")
            return None

    def get_spans_with_attributes(self, limit: int = 20) -> list[dict]:
        """Get spans with their attributes."""
        query = f"""
        query {{
            projects(first: 1) {{
                edges {{
                    node {{
                        spans(first: {limit}) {{
                            edges {{
                                node {{
                                    name
                                    spanKind
                                    latencyMs
                                    statusCode
                                    context {{
                                        spanId
                                        traceId
                                    }}
                                    attributes
                                }}
                            }}
                        }}
                    }}
                }}
            }}
        }}
        """
        data = self._graphql_query(query)
        if not data:
            return []

        spans = []
        projects = data.get("projects", {}).get("edges", [])
        for proj in projects:
            span_edges = proj.get("node", {}).get("spans", {}).get("edges", [])
            for edge in span_edges:
                node = edge.get("node", {})
                # Parse attributes JSON if it's a string
                attrs = node.get("attributes", {})
                if isinstance(attrs, str):
                    try:
                        attrs = json.loads(attrs)
                    except:
                        attrs = {}
                spans.append(
                    {
                        "name": node.get("name"),
                        "spanKind": node.get("spanKind"),
                        "latencyMs": node.get("latencyMs"),
                        "statusCode": node.get("statusCode"),
                        "traceId": node.get("context", {}).get("traceId"),
                        "spanId": node.get("context", {}).get("spanId"),
                        "attributes": attrs,
                    }
                )
        return spans

    def check_columns(self) -> list[ColumnStatus]:
        """Check which columns are populated."""
        results = []
        spans = self.get_spans_with_attributes(limit=20)

        if not spans:
            print("  No spans found in Phoenix!")
            return [
                ColumnStatus(name=col[0], populated=False, source_attribute=col[1])
                for col in self.EXPECTED_COLUMNS
            ]

        # Find a span with the most attributes (likely a gen_ai or LLM span)
        best_span = None
        best_attr_count = 0
        for span in spans:
            attr_count = len(span.get("attributes", {}))
            if attr_count > best_attr_count:
                best_attr_count = attr_count
                best_span = span

        if not best_span:
            best_span = spans[0]

        attrs = best_span.get("attributes", {})
        print(f"\n  Sample span: {best_span.get('name')}")
        print(f"  Attributes: {list(attrs.keys())[:10]}...")

        for col_name, attr_name in self.EXPECTED_COLUMNS:
            value = None

            # Check span properties first
            if attr_name in best_span:
                value = best_span.get(attr_name)
            # Then check attributes
            elif attr_name in attrs:
                value = attrs.get(attr_name)
            # Handle nested attribute paths like "llm.token_count.total"
            elif "." in attr_name:
                parts = attr_name.split(".")
                obj = attrs
                for part in parts:
                    if isinstance(obj, dict):
                        obj = obj.get(part, {})
                    else:
                        obj = None
                        break
                if obj and obj != {}:
                    value = obj

            populated = value is not None and str(value).strip() != ""
            sample = (
                str(value)[:50] + "..." if value and len(str(value)) > 50 else value
            )
            results.append(
                ColumnStatus(
                    name=col_name,
                    populated=populated,
                    sample_value=sample,
                    source_attribute=attr_name,
                )
            )

        return results


def print_results(name: str, results: list[ColumnStatus]):
    """Print column status table."""
    print(f"\n{'=' * 70}")
    print(f"{name} UI Table Columns")
    print(f"{'=' * 70}")
    print(f"{'Column':<20} {'Status':<10} {'Attribute':<25} {'Sample Value':<30}")
    print(f"{'-' * 70}")

    populated = 0
    empty = 0
    for r in results:
        status = "✅ OK" if r.populated else "❌ EMPTY"
        if r.populated:
            populated += 1
        else:
            empty += 1
        sample = str(r.sample_value)[:28] if r.sample_value else ""
        print(f"{r.name:<20} {status:<10} {r.source_attribute:<25} {sample:<30}")

    print(f"{'-' * 70}")
    print(f"Summary: {populated} populated, {empty} empty")


def main():
    print("=" * 70)
    print("UI Table Column Verification")
    print("=" * 70)

    # Get URLs from environment
    mlflow_url = os.getenv(
        "MLFLOW_URL",
        "https://mlflow-kagenti-system.apps.kagenti-hypershift-custom-mlflow.octo-emerging.redhataicoe.com",
    )
    phoenix_url = os.getenv(
        "PHOENIX_URL",
        "https://phoenix-kagenti-system.apps.kagenti-hypershift-custom-mlflow.octo-emerging.redhataicoe.com",
    )
    keycloak_url = os.getenv(
        "KEYCLOAK_URL",
        "https://keycloak-keycloak.apps.kagenti-hypershift-custom-mlflow.octo-emerging.redhataicoe.com",
    )

    print(f"\nMLflow URL: {mlflow_url}")
    print(f"Phoenix URL: {phoenix_url}")
    print(f"Keycloak URL: {keycloak_url}")

    # Check MLflow
    print("\n" + "-" * 70)
    print("Checking MLflow...")
    mlflow_checker = MLflowColumnChecker(mlflow_url, keycloak_url)
    mlflow_results = mlflow_checker.check_columns()
    print_results("MLflow", mlflow_results)

    # Check Phoenix
    print("\n" + "-" * 70)
    print("Checking Phoenix...")
    phoenix_checker = PhoenixColumnChecker(phoenix_url)
    phoenix_results = phoenix_checker.check_columns()
    print_results("Phoenix", phoenix_results)

    # Summary
    print("\n" + "=" * 70)
    print("SUMMARY: Columns Needing Attention")
    print("=" * 70)

    print("\nMLflow empty columns:")
    for r in mlflow_results:
        if not r.populated:
            print(f"  - {r.name}: needs '{r.source_attribute}'")

    print("\nPhoenix empty columns:")
    for r in phoenix_results:
        if not r.populated:
            print(f"  - {r.name}: needs '{r.source_attribute}'")

    return 0


if __name__ == "__main__":
    sys.exit(main())
