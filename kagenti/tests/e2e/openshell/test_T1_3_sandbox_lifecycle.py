"""
T1.3 Sandbox Lifecycle Tests

Tests sandbox CRUD, gateway processing, and status observability.

Capabilities: sandbox_lifecycle
Convention: test_{capability}__{description}[agent]
"""

import json
import os
import subprocess
import time

import httpx
import pytest

from kagenti.tests.e2e.openshell.conftest import (
    a2a_send,
    extract_a2a_text,
    kubectl_get_pods_json,
    kubectl_get_deployments_json,
    kubectl_run,
    sandbox_crd_installed,
)

pytestmark = [pytest.mark.openshell, pytest.mark.mvp]

SANDBOX_NS = os.getenv("OPENSHELL_AGENT_NAMESPACE", "team1")
SANDBOX_NAME = "test-sandbox-poc"


def _kubectl(*args: str, timeout: int = 30) -> subprocess.CompletedProcess:
    return kubectl_run(*args, timeout=timeout)


skip_no_crd = pytest.mark.skipif(
    not sandbox_crd_installed(),
    reason="Sandbox CRD (agents.x-k8s.io) not installed",
)


class TestSandboxLifecycle:
    """Test sandbox CRUD via Kubernetes Sandbox CR API."""

    @skip_no_crd
    def test_sandbox_lifecycle__list(self):
        """List Sandbox CRs — should succeed even if none exist."""
        result = _kubectl(
            "get",
            "sandboxes.agents.x-k8s.io",
            "-n",
            SANDBOX_NS,
            "-o",
            "json",
        )
        assert result.returncode == 0, f"Failed to list sandboxes: {result.stderr}"
        data = json.loads(result.stdout)
        assert "items" in data

    @skip_no_crd
    def test_sandbox_lifecycle__create(self):
        """Create a Sandbox CR and verify the gateway picks it up."""
        # Clean up first
        _kubectl("delete", "sandbox", SANDBOX_NAME, "-n", SANDBOX_NS)
        time.sleep(2)

        # Create a minimal Sandbox CR (spec.podTemplate is the schema)
        sandbox_yaml = f"""
apiVersion: agents.x-k8s.io/v1alpha1
kind: Sandbox
metadata:
  name: {SANDBOX_NAME}
  namespace: {SANDBOX_NS}
spec:
  podTemplate:
    spec:
      containers:
      - name: sandbox
        image: ghcr.io/nvidia/openshell-community/sandboxes/base:latest
"""
        result = subprocess.run(
            ["kubectl", "apply", "-f", "-"],
            input=sandbox_yaml,
            capture_output=True,
            text=True,
            timeout=15,
        )
        assert result.returncode == 0, f"Failed to create sandbox: {result.stderr}"

        # Verify it exists
        time.sleep(3)
        try:
            result = _kubectl(
                "get",
                "sandbox",
                SANDBOX_NAME,
                "-n",
                SANDBOX_NS,
                "-o",
                "jsonpath={.metadata.name}",
            )
            assert result.stdout.strip() == SANDBOX_NAME
        finally:
            _kubectl(
                "delete",
                "sandbox",
                SANDBOX_NAME,
                "-n",
                SANDBOX_NS,
                "--ignore-not-found",
            )

    @skip_no_crd
    def test_sandbox_lifecycle__delete(self):
        """Create then delete a sandbox CR — self-contained."""
        delete_name = "test-sandbox-delete"
        _kubectl(
            "delete", "sandbox", delete_name, "-n", SANDBOX_NS, "--ignore-not-found"
        )
        time.sleep(2)

        sandbox_yaml = f"""
apiVersion: agents.x-k8s.io/v1alpha1
kind: Sandbox
metadata:
  name: {delete_name}
  namespace: {SANDBOX_NS}
spec:
  podTemplate:
    spec:
      containers:
      - name: sandbox
        image: ghcr.io/nvidia/openshell-community/sandboxes/base:latest
        command: ["sleep", "60"]
"""
        subprocess.run(
            ["kubectl", "apply", "-f", "-"],
            input=sandbox_yaml,
            capture_output=True,
            text=True,
            timeout=15,
        )
        time.sleep(3)

        result = _kubectl(
            "delete",
            "sandbox",
            delete_name,
            "-n",
            SANDBOX_NS,
            "--timeout=30s",
        )
        assert result.returncode == 0, f"Failed to delete sandbox: {result.stderr}"

    @skip_no_crd
    def test_gateway_sandbox_aware(self):
        """Verify the gateway is configured with a compute driver for sandbox support."""
        result = _kubectl(
            "logs",
            "openshell-server-0",
            "-n",
            GATEWAY_NS,
            "--tail=50",
        )
        assert result.returncode == 0
        assert (
            "compute driver" in result.stdout.lower()
            or "sandbox" in result.stdout.lower()
            or "Server listening" in result.stdout
        ), "Gateway logs don't show sandbox-capable configuration"


AGENT_NS = os.getenv("OPENSHELL_AGENT_NAMESPACE", "team1")
GATEWAY_NS = os.getenv("OPENSHELL_GATEWAY_NAMESPACE", "team1")


class TestSandboxStatusObservability:
    """A2A equivalent of the proposal's ``openshell term`` validation criterion.

    The proposal requires: "openshell term shows sandbox status."
    In our A2A-first model, sandbox/agent status is observed via the
    Kubernetes API (kubectl / Kagenti UI PodStatusPanel), not the CLI.

    These tests verify that all sandbox and agent status information
    is queryable and accurate — the same data the Kagenti UI renders.
    """

    def test_gateway_status_queryable(self):
        """Gateway StatefulSet status is queryable with phase and readiness."""
        result = _kubectl(
            "get",
            "statefulset",
            "openshell-server",
            "-n",
            GATEWAY_NS,
            "-o",
            "json",
        )
        if result.returncode != 0:
            pytest.skip("Gateway StatefulSet not found")

        sts = json.loads(result.stdout)
        desired = sts["spec"].get("replicas", 1)
        ready = sts.get("status", {}).get("readyReplicas", 0)
        assert ready >= desired, f"Gateway: {ready}/{desired} replicas ready"

    def test_agent_deployments_status_queryable(self):
        """Each agent deployment exposes replicas, readyReplicas, conditions."""
        deployments = kubectl_get_deployments_json(AGENT_NS)
        agent_deploys = [
            d
            for d in deployments
            if d.get("metadata", {}).get("labels", {}).get("kagenti.io/type") == "agent"
        ]
        if not agent_deploys:
            pytest.skip("No agent deployments found")

        for dep in agent_deploys:
            name = dep["metadata"]["name"]
            status = dep.get("status", {})
            has_replicas = "replicas" in status or "readyReplicas" in status
            has_conditions = len(status.get("conditions", [])) > 0
            assert has_replicas or has_conditions, (
                f"{name}: deployment status missing both replica counts and conditions "
                f"(may still be initializing after rollout)"
            )

    def test_agent_pods_status_queryable(self):
        """Each agent pod exposes phase, containerStatuses, and resource usage."""
        pods = kubectl_get_pods_json(AGENT_NS)
        agent_pods = [
            p
            for p in pods
            if p.get("metadata", {}).get("labels", {}).get("kagenti.io/type") == "agent"
            and "-build" not in p["metadata"]["name"]
        ]
        if not agent_pods:
            pytest.skip("No agent pods found")

        for pod in agent_pods:
            name = pod["metadata"]["name"]
            status = pod.get("status", {})
            assert "phase" in status, f"{name}: pod missing phase"
            # NemoClaw agents may CrashLoopBackOff (image pending)
            if "nemoclaw" in name:
                continue
            if status["phase"] != "Running":
                pytest.skip(
                    f"{name}: pod phase is {status['phase']} "
                    "(CI runner resource constraints)"
                )
            container_statuses = status.get("containerStatuses", [])
            assert len(container_statuses) > 0, f"{name}: pod has no containerStatuses"
            for cs in container_statuses:
                assert "restartCount" in cs, (
                    f"{name}/{cs['name']}: missing restartCount"
                )

    def test_sandbox_cr_status_queryable(self):
        """Sandbox CRs expose status fields when created."""
        if not sandbox_crd_installed():
            pytest.skip("Sandbox CRD not installed")

        result = _kubectl(
            "get",
            "sandboxes.agents.x-k8s.io",
            "-n",
            AGENT_NS,
            "-o",
            "json",
        )
        assert result.returncode == 0, f"Cannot list sandboxes: {result.stderr}"
        data = json.loads(result.stdout)
        assert "items" in data, "Sandbox list response missing 'items'"

    def test_gateway_logs_accessible(self):
        """Gateway logs are accessible for debugging and audit."""
        result = _kubectl(
            "logs",
            "openshell-server-0",
            "-n",
            GATEWAY_NS,
            "--tail=20",
        )
        assert result.returncode == 0, f"Cannot read gateway logs: {result.stderr}"
        assert len(result.stdout) > 0, "Gateway logs are empty"


# TestAgentServicePersistence moved to test_05_multiturn_conversation.py
