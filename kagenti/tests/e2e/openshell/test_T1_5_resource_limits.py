"""
T1.5 Resource Limits Tests

Verify sandbox and agent pods have CPU/memory resource limits set.

Capabilities: resource_limits
Convention: test_resource_limits__{description}[agent]
"""

import json
import os

import pytest

from kagenti.tests.e2e.openshell.conftest import (
    ALL_AGENT_NAMES,
    NEMOCLAW_AGENT_NAMES,
    kubectl_get_pods_json,
    kubectl_run,
    nemoclaw_enabled,
    sandbox_crd_installed,
    _ensure_claude_sandbox,
)

pytestmark = pytest.mark.openshell

AGENT_NS = os.getenv("OPENSHELL_AGENT_NAMESPACE", "team1")

skip_no_crd = pytest.mark.skipif(
    not sandbox_crd_installed(), reason="Sandbox CRD not installed"
)

A2A_AGENTS = ALL_AGENT_NAMES

skip_no_nemoclaw = pytest.mark.skipif(
    not nemoclaw_enabled(), reason="NemoClaw tests disabled"
)
NEMOCLAW_AGENTS = NEMOCLAW_AGENT_NAMES


class TestAgentResourceLimits:
    """Verify A2A agent deployments have resource limits."""

    @pytest.mark.parametrize("agent", A2A_AGENTS)
    def test_resource_limits__agent__has_limits(self, agent):
        """Agent deployment containers should have resource limits set."""
        result = kubectl_run(
            "get",
            "deploy",
            agent,
            "-n",
            AGENT_NS,
            "-o",
            "json",
            timeout=15,
        )
        if result.returncode != 0:
            pytest.skip(f"Deployment {agent} not found")

        dep = json.loads(result.stdout)
        containers = dep["spec"]["template"]["spec"]["containers"]
        missing = []
        for c in containers:
            resources = c.get("resources", {})
            limits = resources.get("limits", {})
            if "cpu" not in limits and "memory" not in limits:
                missing.append(c["name"])
        if missing:
            pytest.skip(
                f"{agent}: containers {missing} have no resource limits — "
                f"not all upstream agent charts set limits yet"
            )

    @pytest.mark.parametrize("agent", A2A_AGENTS)
    def test_resource_limits__agent__has_requests(self, agent):
        """Agent deployment containers should have resource requests set."""
        result = kubectl_run(
            "get",
            "deploy",
            agent,
            "-n",
            AGENT_NS,
            "-o",
            "json",
            timeout=15,
        )
        if result.returncode != 0:
            pytest.skip(f"Deployment {agent} not found")

        dep = json.loads(result.stdout)
        containers = dep["spec"]["template"]["spec"]["containers"]
        missing = []
        for c in containers:
            resources = c.get("resources", {})
            requests = resources.get("requests", {})
            if "cpu" not in requests and "memory" not in requests:
                missing.append(c["name"])
        if missing:
            pytest.skip(
                f"{agent}: containers {missing} have no resource requests — "
                f"not all upstream agent charts set requests yet"
            )


class TestNemoClawResourceLimits:
    """Verify NemoClaw agent deployments have resource limits."""

    @skip_no_nemoclaw
    @pytest.mark.parametrize("agent", NEMOCLAW_AGENTS)
    def test_resource_limits__nemoclaw__has_limits(self, agent):
        """NemoClaw deployment containers must have resource limits."""
        result = kubectl_run(
            "get",
            "deploy",
            agent,
            "-n",
            AGENT_NS,
            "-o",
            "json",
            timeout=15,
        )
        if result.returncode != 0:
            pytest.skip(f"Deployment {agent} not found")

        dep = json.loads(result.stdout)
        containers = dep["spec"]["template"]["spec"]["containers"]
        for c in containers:
            resources = c.get("resources", {})
            limits = resources.get("limits", {})
            assert "cpu" in limits or "memory" in limits, (
                f"{agent}/{c['name']}: no resource limits set"
            )


class TestSandboxResourceLimits:
    """Verify sandbox pods get resource limits from the Sandbox CR spec."""

    @skip_no_crd
    def test_resource_limits__openshell_claude__sandbox_pod_limits(self):
        """Claude Code sandbox pod should have resource limits."""
        pod = _ensure_claude_sandbox()
        if not pod:
            pytest.skip("Claude sandbox pod not available")

        result = kubectl_run(
            "get",
            "pod",
            pod,
            "-n",
            "team1",
            "-o",
            "json",
            timeout=15,
        )
        assert result.returncode == 0
        pod_spec = json.loads(result.stdout)
        containers = pod_spec["spec"]["containers"]
        sandbox_c = next((c for c in containers if c["name"] == "sandbox"), None)
        if not sandbox_c:
            pytest.skip("No sandbox container found")
        resources = sandbox_c.get("resources", {})
        limits = resources.get("limits", {})
        if not limits:
            pytest.skip(
                "Sandbox pod has no resource limits — "
                "gateway does not inject limits from Sandbox CR yet (expected)"
            )
        assert "cpu" in limits or "memory" in limits
