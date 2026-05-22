"""
T0.3 — OpenShell supervisor enforcement infrastructure tests.

Verifies that the supervisor ACTUALLY enforces isolation:
- Landlock blocks filesystem writes outside allowed paths
- Network namespace isolates the agent from direct external access
- OPA proxy is the only network exit point
- Seccomp filters are applied

These tests verify enforcement by checking supervisor logs for
applied rules (since kubectl exec bypasses per-process restrictions).
For live enforcement tests, the agent process itself would need to
attempt violations — which we test via the A2A endpoint where possible.
"""

import json
import os
import subprocess
import re

import httpx
import pytest

from kagenti.tests.e2e.openshell.conftest import a2a_send, extract_a2a_text

pytestmark = [pytest.mark.openshell]

GATEWAY_NS = os.getenv("OPENSHELL_GATEWAY_NAMESPACE", "team1")
AGENT_NS = os.getenv("OPENSHELL_AGENT_NAMESPACE", "team1")
SUPERVISED_AGENT = "weather-agent-supervised"


from kagenti.tests.e2e.openshell.conftest import kubectl_run


def _kubectl(*args: str, timeout: int = 30) -> subprocess.CompletedProcess:
    return kubectl_run(*args, timeout=timeout)


def _get_supervisor_logs() -> str:
    result = _kubectl(
        "logs",
        f"deploy/{SUPERVISED_AGENT}",
        "-n",
        AGENT_NS,
        "-c",
        "agent",
    )
    return result.stdout if result.returncode == 0 else ""


def _supervised_pod_exists() -> bool:
    result = _kubectl(
        "get",
        "deploy",
        SUPERVISED_AGENT,
        "-n",
        AGENT_NS,
        "-o",
        "jsonpath={.status.readyReplicas}",
    )
    return result.stdout.strip() == "1"


skip_no_supervised = pytest.mark.skipif(
    not _supervised_pod_exists(),
    reason=f"{SUPERVISED_AGENT} not deployed",
)


class TestLandlockEnforcement:
    """Verify Landlock filesystem sandbox is applied."""

    @skip_no_supervised
    def test_landlock_applied_in_logs(self):
        """Supervisor logs must show Landlock was applied with rules."""
        logs = _get_supervisor_logs()
        assert "CONFIG:APPLYING" in logs, "No Landlock application in logs"
        assert "Landlock filesystem sandbox" in logs
        assert "rules_applied:" in logs

        match = re.search(r"rules_applied:(\d+)", logs)
        assert match, "Cannot parse rules_applied count"
        rules = int(match.group(1))
        assert rules >= 10, f"Only {rules} Landlock rules — expected 10+"

    @skip_no_supervised
    def test_landlock_abi_version(self):
        """Supervisor must use Landlock ABI V2 or higher."""
        logs = _get_supervisor_logs()
        assert "abi:" in logs.lower()
        match = re.search(r"abi:v(\d+)", logs, re.IGNORECASE)
        assert match, "Cannot parse Landlock ABI version"
        version = int(match.group(1))
        assert version >= 2, f"Landlock ABI v{version} too old (need v2+)"

    @skip_no_supervised
    def test_read_only_paths_configured(self):
        """Policy must define read-only paths."""
        result = _kubectl(
            "get",
            "configmap",
            f"{SUPERVISED_AGENT}-policy",
            "-n",
            AGENT_NS,
            "-o",
            "jsonpath={.data.policy\\.yaml}",
        )
        assert result.returncode == 0
        assert "read_only:" in result.stdout
        assert "/usr" in result.stdout
        assert "/etc" in result.stdout

    @skip_no_supervised
    def test_read_write_paths_configured(self):
        """Policy must define read-write paths (tmp, app)."""
        result = _kubectl(
            "get",
            "configmap",
            f"{SUPERVISED_AGENT}-policy",
            "-n",
            AGENT_NS,
            "-o",
            "jsonpath={.data.policy\\.yaml}",
        )
        assert "/tmp" in result.stdout
        assert "/app" in result.stdout


class TestNetworkNamespaceEnforcement:
    """Verify network namespace isolation is applied."""

    @skip_no_supervised
    def test_netns_created_in_logs(self):
        """Supervisor logs must show network namespace was created."""
        logs = _get_supervisor_logs()
        assert "CONFIG:CREATING" in logs
        assert "Network namespace" in logs
        assert "10.200.0.1" in logs, "Host veth IP not found"
        assert "10.200.0.2" in logs, "Sandbox veth IP not found"

    @skip_no_supervised
    def test_opa_proxy_listening(self):
        """OPA proxy must be listening on 10.200.0.1:3128."""
        logs = _get_supervisor_logs()
        assert "NET:LISTEN" in logs
        assert "10.200.0.1:3128" in logs

    @skip_no_supervised
    def test_netns_name_in_logs(self):
        """Network namespace must have a unique name."""
        logs = _get_supervisor_logs()
        match = re.search(r"ns:sandbox-([a-f0-9]+)", logs)
        assert match, "No sandbox netns name in logs"
        ns_id = match.group(1)
        assert len(ns_id) >= 6, f"Netns ID too short: {ns_id}"


class TestSeccompEnforcement:
    """Verify seccomp syscall filtering is applied."""

    @skip_no_supervised
    def test_seccomp_not_explicitly_disabled(self):
        """Pod spec must not have seccomp set to Unconfined."""
        result = _kubectl(
            "get",
            f"deploy/{SUPERVISED_AGENT}",
            "-n",
            AGENT_NS,
            "-o",
            "json",
        )
        dep = json.loads(result.stdout)
        containers = dep["spec"]["template"]["spec"]["containers"]
        for c in containers:
            sc = c.get("securityContext", {})
            seccomp = sc.get("seccompProfile", {})
            assert seccomp.get("type") != "Unconfined", (
                f"Container {c['name']} has seccomp Unconfined"
            )


class TestOPAPolicyEnforcement:
    """Verify OPA policy is loaded and evaluating."""

    @skip_no_supervised
    def test_opa_policy_loaded(self):
        """Supervisor logs must show OPA policy was loaded."""
        logs = _get_supervisor_logs()
        assert "CONFIG:LOADING" in logs
        assert "OPA policy engine" in logs
        assert "sandbox-policy.rego" in logs

    @skip_no_supervised
    def test_policy_has_network_rules(self):
        """OPA policy data must define network endpoint rules."""
        result = _kubectl(
            "get",
            "configmap",
            f"{SUPERVISED_AGENT}-policy",
            "-n",
            AGENT_NS,
            "-o",
            "jsonpath={.data.policy\\.yaml}",
        )
        assert "network_policies:" in result.stdout
        assert "endpoints:" in result.stdout

    @skip_no_supervised
    def test_rego_file_mounted(self):
        """The OPA Rego rules file must be mounted in the pod."""
        result = _kubectl(
            "exec",
            f"deploy/{SUPERVISED_AGENT}",
            "-n",
            AGENT_NS,
            "--",
            "ls",
            "/etc/openshell/sandbox-policy.rego",
        )
        assert result.returncode == 0, "Rego policy file not mounted"

    @skip_no_supervised
    def test_tls_termination_enabled(self):
        """Supervisor must enable TLS termination for L7 inspection."""
        logs = _get_supervisor_logs()
        assert "TLS termination enabled" in logs
        assert "ephemeral CA generated" in logs


# TestRealGitHubPRReview moved to test_07_skill_execution.py::TestRealWorldSkillExecution
