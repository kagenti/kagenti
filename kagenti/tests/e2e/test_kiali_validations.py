"""
Kiali Istio configuration and traffic validation tests.

These tests query the Kiali API to check for:
1. Istio configuration errors and warnings across namespaces
2. Service mesh traffic health (HTTP errors, mTLS status)

These tests are marked with @pytest.mark.observability and should run AFTER
other E2E tests to validate both static configuration and traffic patterns.

Usage:
    # Run all tests except observability (generates traffic)
    uv run pytest kagenti/tests/e2e/ -v -m "not observability"

    # Run observability tests (validates traffic from previous tests)
    uv run pytest kagenti/tests/e2e/ -v -m "observability"

    # Run with explicit Kiali URL
    KIALI_URL=https://kiali-istio-system.apps.example.com \
        uv run pytest kagenti/tests/e2e/test_kiali_validations.py -v

    # Run as standalone script for debugging
    python kagenti/tests/e2e/test_kiali_validations.py

Environment Variables:
    KIALI_URL: Override Kiali URL (default: auto-detect from cluster route)
    KIALI_NAMESPACES: Comma-separated list of namespaces to check
                      (default: kagenti-managed namespaces)
    KIALI_IGNORE_NAMESPACES: Comma-separated list of namespaces to ignore
    KIALI_SKIP_VALIDATION_CODES: Comma-separated validation codes to ignore
    KIALI_FAIL_ON_WARNINGS: Set to "false" to only fail on errors (default: true)
    KIALI_TRAFFIC_DURATION: Duration for traffic analysis (default: 2h)
    KIALI_ERROR_RATE_THRESHOLD: Max allowed error rate 0.0-1.0 (default: 0.01)
"""

import json
import os
import subprocess
import ssl
import urllib.request
from dataclasses import dataclass, field
from typing import Optional

import pytest


# Default namespaces to check (Kagenti-managed)
DEFAULT_NAMESPACES = [
    "kagenti-system",
    "gateway-system",
    "mcp-system",
    "team1",
    "team2",
    "keycloak",
    "spire-server",
    "spire-system",
    "spire-mgmt",
    "toolhive-system",
    "istio-system",
    "istio-ztunnel",
]

# Namespaces to ignore by default (external/managed by other operators)
DEFAULT_IGNORE_NAMESPACES = [
    "redhat-ods-applications",  # OpenShift AI - has known PeerAuthentication issues
    "redhat-ods-operator",
    "redhat-ods-monitoring",
    "nvidia-gpu-operator",
    "openshift-nfd",
]

# Validation codes to ignore (known issues that can't be fixed)
DEFAULT_IGNORE_CODES = [
    # Add codes here like "KIA0101" if needed
]


@dataclass
class ValidationIssue:
    """Represents a single Kiali validation issue."""

    namespace: str
    object_type: str
    object_name: str
    severity: str  # "error" or "warning"
    code: str
    message: str
    path: Optional[str] = None

    def __str__(self):
        return (
            f"[{self.severity.upper()}] {self.namespace}/{self.object_type}/"
            f"{self.object_name}: {self.code} - {self.message}"
        )


@dataclass
class TrafficEdge:
    """Represents a service-to-service traffic edge from Kiali graph."""

    source_namespace: str
    source_workload: str
    dest_namespace: str
    dest_workload: str
    protocol: str
    requests: int = 0
    error_rate: float = 0.0
    is_mtls: bool = False
    response_time_p99: float = 0.0

    def __str__(self):
        mtls_status = "mTLS" if self.is_mtls else "NO-mTLS"
        return (
            f"{self.source_namespace}/{self.source_workload} -> "
            f"{self.dest_namespace}/{self.dest_workload} "
            f"[{self.protocol}] {self.requests} reqs, "
            f"{self.error_rate:.1%} errors, {mtls_status}"
        )


@dataclass
class TrafficSummary:
    """Summary of traffic analysis."""

    total_edges: int = 0
    total_requests: int = 0
    edges_with_errors: list = field(default_factory=list)
    edges_without_mtls: list = field(default_factory=list)
    max_error_rate: float = 0.0
    namespaces_analyzed: list = field(default_factory=list)


class KialiClient:
    """Client for querying Kiali API."""

    def __init__(self, base_url: Optional[str] = None, token: Optional[str] = None):
        """
        Initialize Kiali client.

        Args:
            base_url: Kiali URL. If not provided, auto-detects from cluster.
            token: Bearer token for authentication. If not provided, uses `oc whoami -t`.
        """
        self.base_url = base_url or self._detect_kiali_url()
        self.token = token or self._get_token()

        # Create SSL context that ignores certificate verification
        # (common for self-signed certs in dev/test clusters)
        self.ssl_context = ssl.create_default_context()
        self.ssl_context.check_hostname = False
        self.ssl_context.verify_mode = ssl.CERT_NONE

    def _detect_kiali_url(self) -> str:
        """Auto-detect Kiali URL from cluster route."""
        try:
            # Try OpenShift route first
            result = subprocess.run(
                [
                    "oc",
                    "get",
                    "route",
                    "kiali",
                    "-n",
                    "istio-system",
                    "-o",
                    "jsonpath={.spec.host}",
                ],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0 and result.stdout.strip():
                return f"https://{result.stdout.strip()}"
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass

        try:
            # Try kubectl with ingress
            result = subprocess.run(
                [
                    "kubectl",
                    "get",
                    "ingress",
                    "kiali",
                    "-n",
                    "istio-system",
                    "-o",
                    "jsonpath={.spec.rules[0].host}",
                ],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0 and result.stdout.strip():
                return f"https://{result.stdout.strip()}"
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass

        # Default for Kind clusters
        return "http://kiali.localtest.me:8080"

    def _get_token(self) -> str:
        """Get authentication token."""
        try:
            result = subprocess.run(
                ["oc", "whoami", "-t"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0:
                return result.stdout.strip()
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass

        # Return empty token for Kind clusters (may use anonymous access)
        return ""

    def _request(self, path: str) -> dict:
        """Make authenticated request to Kiali API."""
        url = f"{self.base_url}/api{path}"
        headers = {}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"

        request = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(
                request, timeout=30, context=self.ssl_context
            ) as response:
                return json.loads(response.read().decode())
        except urllib.error.HTTPError as e:
            raise RuntimeError(f"Kiali API error: {e.code} {e.reason}") from e
        except urllib.error.URLError as e:
            raise RuntimeError(f"Cannot connect to Kiali at {url}: {e}") from e

    def get_status(self) -> dict:
        """Get Kiali status to verify connectivity."""
        return self._request("/status")

    def get_validation_summary(self) -> list[dict]:
        """Get validation summary for all namespaces."""
        return self._request("/istio/validations")

    def get_namespace_config(self, namespace: str) -> dict:
        """Get detailed Istio config for a namespace."""
        return self._request(f"/istio/config?namespaces={namespace}")

    def get_workloads(self, namespaces: list[str]) -> dict:
        """Get workloads with validations."""
        ns_param = ",".join(namespaces)
        return self._request(f"/workloads?namespaces={ns_param}")

    def get_graph(self, namespaces: list[str], duration: str = "10m") -> dict:
        """
        Get the traffic graph for specified namespaces.

        Args:
            namespaces: List of namespaces to include in graph
            duration: Time duration for metrics (e.g., "10m", "1h")

        Returns:
            Kiali graph response with nodes and edges
        """
        ns_param = ",".join(namespaces)
        # Include traffic rates and response times in the graph
        params = (
            f"namespaces={ns_param}"
            f"&duration={duration}"
            "&graphType=workload"
            "&includeIdleEdges=false"
            "&injectServiceNodes=true"
            "&responseTime=avg"
            "&throughput=request"
        )
        return self._request(f"/namespaces/graph?{params}")

    def get_all_validations(
        self,
        namespaces: Optional[list[str]] = None,
        ignore_namespaces: Optional[list[str]] = None,
        ignore_codes: Optional[list[str]] = None,
    ) -> tuple[list[ValidationIssue], dict]:
        """
        Get all validation issues across namespaces.

        Returns:
            Tuple of (list of ValidationIssue, summary dict)
        """
        ignore_namespaces = ignore_namespaces or []
        ignore_codes = ignore_codes or []

        # Get summary first
        summary = self.get_validation_summary()

        issues = []
        total_errors = 0
        total_warnings = 0
        namespaces_with_errors = []
        namespaces_with_warnings = []

        for ns_summary in summary:
            ns_name = ns_summary.get("namespace", "")

            # Skip if namespace not in our list (if specified)
            if namespaces and ns_name not in namespaces:
                continue

            # Skip ignored namespaces
            if ns_name in ignore_namespaces:
                continue

            errors = ns_summary.get("errors", 0)
            warnings = ns_summary.get("warnings", 0)

            if errors > 0:
                total_errors += errors
                namespaces_with_errors.append(ns_name)

            if warnings > 0:
                total_warnings += warnings
                namespaces_with_warnings.append(ns_name)

            # Get detailed config if there are issues
            if errors > 0 or warnings > 0:
                try:
                    config = self.get_namespace_config(ns_name)

                    # Parse detailed validations from config
                    for obj in config.get("objects", []):
                        obj_validations = obj.get("validations", [])
                        for validation in obj_validations:
                            code = validation.get("code", "")
                            if code in ignore_codes:
                                continue

                            severity = validation.get("severity", "warning")
                            issue = ValidationIssue(
                                namespace=ns_name,
                                object_type=obj.get("type", "unknown"),
                                object_name=obj.get("name", "unknown"),
                                severity=severity,
                                code=code,
                                message=validation.get("message", ""),
                                path=validation.get("path"),
                            )
                            issues.append(issue)
                except Exception as e:
                    # If we can't get details, create a generic issue
                    issues.append(
                        ValidationIssue(
                            namespace=ns_name,
                            object_type="unknown",
                            object_name="unknown",
                            severity="error" if errors > 0 else "warning",
                            code="KIALI_API_ERROR",
                            message=f"Could not fetch details: {e}",
                        )
                    )

        summary_dict = {
            "total_errors": total_errors,
            "total_warnings": total_warnings,
            "namespaces_with_errors": namespaces_with_errors,
            "namespaces_with_warnings": namespaces_with_warnings,
            "issues": issues,
        }

        return issues, summary_dict

    def get_traffic_health(
        self,
        namespaces: list[str],
        duration: str = "10m",
        ignore_namespaces: Optional[list[str]] = None,
    ) -> tuple[list[TrafficEdge], TrafficSummary]:
        """
        Analyze traffic graph for errors and mTLS compliance.

        Args:
            namespaces: Namespaces to analyze
            duration: Time window for traffic analysis
            ignore_namespaces: Namespaces to exclude from analysis

        Returns:
            Tuple of (list of TrafficEdge, TrafficSummary)
        """
        ignore_namespaces = ignore_namespaces or []

        # Filter namespaces
        target_namespaces = [ns for ns in namespaces if ns not in ignore_namespaces]

        if not target_namespaces:
            return [], TrafficSummary()

        graph = self.get_graph(target_namespaces, duration)

        edges = []
        summary = TrafficSummary(namespaces_analyzed=target_namespaces)

        # Build node ID to info mapping
        nodes = {}
        for element in graph.get("elements", {}).get("nodes", []):
            node_data = element.get("data", {})
            node_id = node_data.get("id", "")
            nodes[node_id] = {
                "namespace": node_data.get("namespace", "unknown"),
                "workload": node_data.get("workload", node_data.get("app", "unknown")),
                "is_service": node_data.get("isServiceEntry", False),
            }

        # Process edges
        for element in graph.get("elements", {}).get("edges", []):
            edge_data = element.get("data", {})

            source_id = edge_data.get("source", "")
            target_id = edge_data.get("target", "")

            source = nodes.get(
                source_id, {"namespace": "unknown", "workload": "unknown"}
            )
            dest = nodes.get(target_id, {"namespace": "unknown", "workload": "unknown"})

            # Get traffic metrics
            traffic = edge_data.get("traffic", {})
            protocol = traffic.get("protocol", "unknown")

            # Get rates from traffic object
            rates = traffic.get("rates", {})
            requests = int(float(rates.get("http", rates.get("grpc", 0))))

            # Calculate error rate
            error_rate = 0.0
            if requests > 0:
                errors_5xx = float(rates.get("http5xx", rates.get("grpc5xx", 0)))
                error_rate = errors_5xx / requests if requests > 0 else 0.0

            # Check mTLS status
            is_mtls = edge_data.get("isMTLS", False)

            # Get response time if available
            response_time = float(edge_data.get("responseTime", 0))

            edge = TrafficEdge(
                source_namespace=source["namespace"],
                source_workload=source["workload"],
                dest_namespace=dest["namespace"],
                dest_workload=dest["workload"],
                protocol=protocol,
                requests=requests,
                error_rate=error_rate,
                is_mtls=is_mtls,
                response_time_p99=response_time,
            )
            edges.append(edge)

            # Update summary
            summary.total_edges += 1
            summary.total_requests += requests

            if error_rate > 0:
                summary.edges_with_errors.append(edge)
                if error_rate > summary.max_error_rate:
                    summary.max_error_rate = error_rate

            if not is_mtls and requests > 0:
                summary.edges_without_mtls.append(edge)

        return edges, summary


def format_validation_report(
    issues: list[ValidationIssue],
    summary: dict,
    title: str = "Kiali Validation Report",
) -> str:
    """Format a nice validation report for CI output."""
    lines = []
    lines.append("")
    lines.append("=" * 70)
    lines.append(f" {title}")
    lines.append("=" * 70)

    errors = [i for i in issues if i.severity == "error"]
    warnings = [i for i in issues if i.severity == "warning"]

    if errors:
        lines.append("")
        lines.append(f"ERRORS ({len(errors)})")
        lines.append("-" * 70)
        for e in errors:
            lines.append(f"  {e}")

    if warnings:
        lines.append("")
        lines.append(f"WARNINGS ({len(warnings)})")
        lines.append("-" * 70)
        for w in warnings:
            lines.append(f"  {w}")

    lines.append("")
    lines.append("SUMMARY")
    lines.append("-" * 70)
    lines.append(f"  Total errors:   {summary['total_errors']}")
    lines.append(f"  Total warnings: {summary['total_warnings']}")

    if summary["namespaces_with_errors"]:
        lines.append(f"  Namespaces with errors: {summary['namespaces_with_errors']}")
    if summary["namespaces_with_warnings"]:
        lines.append(
            f"  Namespaces with warnings: {summary['namespaces_with_warnings']}"
        )

    lines.append("=" * 70)
    lines.append("")

    return "\n".join(lines)


def format_traffic_report(
    edges: list[TrafficEdge],
    summary: TrafficSummary,
    title: str = "Traffic Health Report",
    error_threshold: float = 0.01,
) -> str:
    """Format a comprehensive traffic health report for CI output."""
    lines = []
    lines.append("")
    lines.append("=" * 90)
    lines.append(f" {title}")
    lines.append("=" * 90)

    if not edges:
        lines.append("")
        lines.append("  No traffic edges observed.")
        lines.append("=" * 90)
        return "\n".join(lines)

    # Group edges by source namespace
    by_namespace = {}
    for edge in edges:
        ns = edge.source_namespace
        if ns not in by_namespace:
            by_namespace[ns] = []
        by_namespace[ns].append(edge)

    # Table header
    lines.append("")
    lines.append(
        f"  {'STATUS':<8} {'SOURCE':<40} {'DEST':<40} {'PROTO':<6} {'REQS':<8} {'ERR%':<8} {'mTLS':<6}"
    )
    lines.append("  " + "-" * 116)

    for ns in sorted(by_namespace.keys()):
        for edge in sorted(by_namespace[ns], key=lambda e: e.dest_workload):
            # Determine status
            has_error = edge.error_rate > error_threshold
            has_mtls = edge.is_mtls
            if has_error or (not has_mtls and edge.requests > 0):
                status = "FAIL"
            else:
                status = "PASS"

            source = f"{edge.source_namespace}/{edge.source_workload}"
            dest = f"{edge.dest_namespace}/{edge.dest_workload}"
            err_pct = f"{edge.error_rate:.1%}"
            mtls = "yes" if edge.is_mtls else "NO"

            lines.append(
                f"  {status:<8} {source:<40} {dest:<40} "
                f"{edge.protocol:<6} {edge.requests:<8} {err_pct:<8} {mtls:<6}"
            )

    # Summary section
    lines.append("")
    lines.append("  SUMMARY")
    lines.append("  " + "-" * 116)
    lines.append(f"  Namespaces analyzed: {summary.namespaces_analyzed}")
    lines.append(f"  Total edges:         {summary.total_edges}")
    lines.append(f"  Total requests:      {summary.total_requests}")
    lines.append(f"  Edges with errors:   {len(summary.edges_with_errors)}")
    lines.append(f"  Edges without mTLS:  {len(summary.edges_without_mtls)}")
    lines.append(f"  Max error rate:      {summary.max_error_rate:.2%}")

    failed_count = len(summary.edges_with_errors) + len(summary.edges_without_mtls)
    if failed_count == 0:
        lines.append("")
        lines.append("  All traffic is healthy with mTLS enabled!")
    else:
        lines.append("")
        lines.append(f"  {failed_count} edge(s) have issues - see FAIL entries above")

    lines.append("=" * 90)
    lines.append("")

    return "\n".join(lines)


# ============================================================================
# Pytest Fixtures
# ============================================================================


@pytest.fixture(scope="module")
def kiali_client():
    """Create Kiali client for tests."""
    url = os.getenv("KIALI_URL")
    try:
        client = KialiClient(base_url=url)
        # Verify connectivity
        status = client.get_status()
        if status.get("status", {}).get("Kiali state") != "running":
            pytest.skip("Kiali is not running")
        return client
    except Exception as e:
        pytest.skip(f"Cannot connect to Kiali: {e}")


@pytest.fixture(scope="module")
def target_namespaces():
    """Get list of namespaces to check."""
    ns_env = os.getenv("KIALI_NAMESPACES")
    if ns_env:
        return [ns.strip() for ns in ns_env.split(",")]
    return DEFAULT_NAMESPACES


@pytest.fixture(scope="module")
def ignore_namespaces():
    """Get list of namespaces to ignore."""
    ns_env = os.getenv("KIALI_IGNORE_NAMESPACES")
    if ns_env:
        return [ns.strip() for ns in ns_env.split(",")]
    return DEFAULT_IGNORE_NAMESPACES


@pytest.fixture(scope="module")
def ignore_codes():
    """Get list of validation codes to ignore."""
    codes_env = os.getenv("KIALI_SKIP_VALIDATION_CODES")
    if codes_env:
        return [code.strip() for code in codes_env.split(",")]
    return DEFAULT_IGNORE_CODES


@pytest.fixture(scope="module")
def fail_on_warnings():
    """Check if test should fail on warnings."""
    env_val = os.getenv("KIALI_FAIL_ON_WARNINGS", "true").lower()
    return env_val not in ("false", "0", "no")


@pytest.fixture(scope="module")
def traffic_duration():
    """Get duration for traffic analysis."""
    return os.getenv("KIALI_TRAFFIC_DURATION", "2h")


@pytest.fixture(scope="module")
def error_rate_threshold():
    """Get max allowed error rate."""
    return float(os.getenv("KIALI_ERROR_RATE_THRESHOLD", "0.01"))


# ============================================================================
# Tests
# ============================================================================


@pytest.mark.observability
@pytest.mark.requires_features(["kiali"])
class TestKialiValidations:
    """
    Tests for Kiali Istio configuration and traffic validations.

    These tests are marked with @pytest.mark.observability and should run
    AFTER other E2E tests have generated traffic. Run pytest twice:

        # First: all tests except observability
        pytest -m "not observability"

        # Then: observability tests
        pytest -m "observability"
    """

    def test_kiali_connectivity(self, kiali_client):
        """Verify Kiali is accessible and running."""
        status = kiali_client.get_status()
        assert status.get("status", {}).get("Kiali state") == "running"
        print(f"\nKiali version: {status.get('status', {}).get('Kiali version')}")
        print(f"Kiali URL: {kiali_client.base_url}")

    def test_no_istio_configuration_issues(
        self,
        kiali_client,
        target_namespaces,
        ignore_namespaces,
        ignore_codes,
        fail_on_warnings,
    ):
        """
        Ensure no Istio configuration errors or warnings in Kagenti namespaces.

        This test queries Kiali for all validation issues and fails if any
        errors are found. By default, it also fails on warnings (configurable
        via KIALI_FAIL_ON_WARNINGS=false).

        The test produces a formatted report showing all issues for easy
        debugging in CI logs.
        """
        issues, summary = kiali_client.get_all_validations(
            namespaces=target_namespaces,
            ignore_namespaces=ignore_namespaces,
            ignore_codes=ignore_codes,
        )

        errors = [i for i in issues if i.severity == "error"]
        warnings = [i for i in issues if i.severity == "warning"]

        # Always print the report for visibility
        report = format_validation_report(issues, summary)
        print(report)

        # Fail on errors
        if errors:
            pytest.fail(
                f"Found {len(errors)} Istio configuration error(s). "
                f"See report above for details.\n"
                f"Namespaces with errors: {summary['namespaces_with_errors']}"
            )

        # Optionally fail on warnings
        if fail_on_warnings and warnings:
            pytest.fail(
                f"Found {len(warnings)} Istio configuration warning(s). "
                f"See report above for details.\n"
                f"Namespaces with warnings: {summary['namespaces_with_warnings']}\n\n"
                f"To ignore warnings, set KIALI_FAIL_ON_WARNINGS=false"
            )

        # Success message
        if not errors and not warnings:
            print(
                f"\nNo validation issues found in {len(target_namespaces)} namespaces"
            )

    def test_no_traffic_errors(
        self,
        kiali_client,
        target_namespaces,
        ignore_namespaces,
        traffic_duration,
        error_rate_threshold,
    ):
        """
        Ensure no HTTP errors in service mesh traffic.

        This test analyzes the traffic graph from the last N minutes
        (default 10m) and fails if any edges have error rates above
        the threshold (default 1%).

        Run this test AFTER other E2E tests to validate that the traffic
        they generated was successful.
        """
        edges, summary = kiali_client.get_traffic_health(
            namespaces=target_namespaces,
            duration=traffic_duration,
            ignore_namespaces=ignore_namespaces,
        )

        # Always print the report for visibility
        report = format_traffic_report(
            edges, summary, error_threshold=error_rate_threshold
        )
        print(report)

        # Check for edges with errors above threshold
        high_error_edges = [
            e for e in summary.edges_with_errors if e.error_rate > error_rate_threshold
        ]

        if high_error_edges:
            error_details = "\n".join(f"  - {e}" for e in high_error_edges)
            pytest.fail(
                f"Found {len(high_error_edges)} edge(s) with error rate > "
                f"{error_rate_threshold:.1%}:\n{error_details}\n\n"
                f"Max error rate observed: {summary.max_error_rate:.2%}\n"
                f"To adjust threshold, set KIALI_ERROR_RATE_THRESHOLD"
            )

        if summary.total_requests == 0:
            print(
                f"\nNo traffic observed in the last {traffic_duration}. "
                "This may be expected if no tests ran before this."
            )
        else:
            print(
                f"\nTraffic health check passed: {summary.total_requests} requests "
                f"across {summary.total_edges} edges with max error rate "
                f"{summary.max_error_rate:.2%}"
            )

    def test_mtls_compliance(
        self,
        kiali_client,
        target_namespaces,
        ignore_namespaces,
        traffic_duration,
    ):
        """
        Ensure all service mesh traffic uses mTLS.

        This test analyzes the traffic graph and fails if any edges
        are NOT using mutual TLS. mTLS is critical for zero-trust
        security in the service mesh.
        """
        edges, summary = kiali_client.get_traffic_health(
            namespaces=target_namespaces,
            duration=traffic_duration,
            ignore_namespaces=ignore_namespaces,
        )

        # Print comprehensive traffic table
        report = format_traffic_report(edges, summary, title="mTLS Compliance Report")
        print(report)

        if summary.edges_without_mtls:
            non_mtls_details = "\n".join(f"  - {e}" for e in summary.edges_without_mtls)
            pytest.fail(
                f"Found {len(summary.edges_without_mtls)} edge(s) without mTLS:\n"
                f"{non_mtls_details}\n\n"
                "All service mesh traffic should use mutual TLS for zero-trust security."
            )

        if summary.total_requests == 0:
            print(
                f"\nNo traffic observed in the last {traffic_duration}. "
                "mTLS compliance cannot be verified without traffic."
            )
        else:
            print(
                f"\nmTLS compliance check passed: all {summary.total_edges} edges use mTLS"
            )


# ============================================================================
# Standalone Script Mode
# ============================================================================


def main():
    """Run validation scan as standalone script."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Scan Kiali for Istio configuration and traffic issues"
    )
    parser.add_argument("--url", help="Kiali URL (auto-detect if not specified)")
    parser.add_argument(
        "--namespaces",
        help="Comma-separated namespaces to check",
        default=",".join(DEFAULT_NAMESPACES),
    )
    parser.add_argument(
        "--ignore-namespaces",
        help="Comma-separated namespaces to ignore",
        default=",".join(DEFAULT_IGNORE_NAMESPACES),
    )
    parser.add_argument(
        "--ignore-codes",
        help="Comma-separated validation codes to ignore",
        default="",
    )
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    parser.add_argument(
        "--fail-on-warnings",
        action="store_true",
        default=True,
        help="Exit with error code on warnings (default: true)",
    )
    parser.add_argument(
        "--no-fail-on-warnings",
        action="store_true",
        help="Only exit with error code on errors, not warnings",
    )
    parser.add_argument(
        "--check-traffic",
        action="store_true",
        help="Also check traffic graph for errors and mTLS",
    )
    parser.add_argument(
        "--duration",
        default="10m",
        help="Duration for traffic analysis (default: 10m)",
    )
    parser.add_argument(
        "--error-threshold",
        type=float,
        default=0.01,
        help="Max allowed error rate 0.0-1.0 (default: 0.01)",
    )
    args = parser.parse_args()

    # Handle --no-fail-on-warnings
    fail_on_warnings = args.fail_on_warnings and not args.no_fail_on_warnings

    # Parse arguments
    namespaces = [ns.strip() for ns in args.namespaces.split(",") if ns.strip()]
    ignore_namespaces = [
        ns.strip() for ns in args.ignore_namespaces.split(",") if ns.strip()
    ]
    ignore_codes = [
        code.strip() for code in args.ignore_codes.split(",") if code.strip()
    ]

    try:
        client = KialiClient(base_url=args.url)
        status = client.get_status()
        kiali_version = status.get("status", {}).get("Kiali version", "unknown")
    except Exception as e:
        print(f"ERROR: Cannot connect to Kiali: {e}")
        return 1

    print(f"Connected to Kiali {kiali_version}")
    print(f"Scanning namespaces: {namespaces}")
    print(f"Ignoring namespaces: {ignore_namespaces}")
    print(f"Fail on warnings: {fail_on_warnings}")

    # Get validation issues
    issues, validation_summary = client.get_all_validations(
        namespaces=namespaces,
        ignore_namespaces=ignore_namespaces,
        ignore_codes=ignore_codes,
    )

    # Get traffic health if requested
    traffic_edges = []
    traffic_summary = None
    if args.check_traffic:
        traffic_edges, traffic_summary = client.get_traffic_health(
            namespaces=namespaces,
            duration=args.duration,
            ignore_namespaces=ignore_namespaces,
        )

    if args.json:
        output = {
            "kiali_version": kiali_version,
            "kiali_url": client.base_url,
            "validation_summary": {
                "total_errors": validation_summary["total_errors"],
                "total_warnings": validation_summary["total_warnings"],
                "namespaces_with_errors": validation_summary["namespaces_with_errors"],
                "namespaces_with_warnings": validation_summary[
                    "namespaces_with_warnings"
                ],
            },
            "validation_issues": [
                {
                    "namespace": i.namespace,
                    "object_type": i.object_type,
                    "object_name": i.object_name,
                    "severity": i.severity,
                    "code": i.code,
                    "message": i.message,
                    "path": i.path,
                }
                for i in issues
            ],
        }
        if traffic_summary:
            output["traffic_summary"] = {
                "total_edges": traffic_summary.total_edges,
                "total_requests": traffic_summary.total_requests,
                "edges_with_errors": len(traffic_summary.edges_with_errors),
                "edges_without_mtls": len(traffic_summary.edges_without_mtls),
                "max_error_rate": traffic_summary.max_error_rate,
            }
        print(json.dumps(output, indent=2))
    else:
        print(format_validation_report(issues, validation_summary))
        if traffic_summary:
            print(
                format_traffic_report(
                    traffic_edges, traffic_summary, error_threshold=args.error_threshold
                )
            )

    # Determine exit code
    exit_code = 0

    if validation_summary["total_errors"] > 0:
        exit_code = 1
    if fail_on_warnings and validation_summary["total_warnings"] > 0:
        exit_code = 1

    if traffic_summary:
        high_error_edges = [
            e
            for e in traffic_summary.edges_with_errors
            if e.error_rate > args.error_threshold
        ]
        if high_error_edges:
            exit_code = 1
        if traffic_summary.edges_without_mtls:
            exit_code = 1

    return exit_code


if __name__ == "__main__":
    exit(main())
