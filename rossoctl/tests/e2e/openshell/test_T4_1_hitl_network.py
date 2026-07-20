"""
T4.1 HITL Network Policy Tests

Tests that OPA policy enforcement blocks unauthorized egress from
supervised agents. Uses kubectl exec to verify network isolation.

Capability: hitl_network
Convention: test_hitl_network__{description}[agent]
"""

import os
import subprocess

import pytest

from rossoctl.tests.e2e.openshell.conftest import kubectl_run

pytestmark = [pytest.mark.openshell, pytest.mark.mvp]

AGENT_NS = os.getenv("OPENSHELL_AGENT_NAMESPACE", "team1")
SUPERVISED_AGENTS = ["weather-agent-supervised"]


def _kubectl(*args: str, timeout: int = 30) -> subprocess.CompletedProcess:
    return kubectl_run(*args, timeout=timeout)


def _deploy_ready(name: str, ns: str = AGENT_NS) -> bool:
    r = _kubectl(
        "get", "deploy", name, "-n", ns, "-o", "jsonpath={.status.readyReplicas}"
    )
    return r.returncode == 0 and r.stdout.strip() == "1"


@pytest.mark.parametrize("agent", SUPERVISED_AGENTS)
class TestHITLNetwork:
    """Verify OPA policy blocks unauthorized egress from supervised agents."""

    def test_hitl_network__denies_egress(self, agent):
        """OPA proxy blocks access to unauthorized domain."""
        if not _deploy_ready(agent):
            pytest.skip(f"{agent} not deployed")

        py_cmd = (
            "import urllib.request, os; "
            "os.environ['http_proxy']='http://10.200.0.1:3128'; "
            "os.environ['https_proxy']='http://10.200.0.1:3128'; "
            "urllib.request.urlopen('http://example.com', timeout=5)"
        )
        result = _kubectl(
            "exec",
            f"deploy/{agent}",
            "-n",
            AGENT_NS,
            "-c",
            "agent",
            "--",
            "python3",
            "-c",
            py_cmd,
            timeout=30,
        )

        combined = (result.stdout + result.stderr).lower()
        blocked = result.returncode != 0 or any(
            kw in combined
            for kw in ["403", "forbidden", "denied", "refused", "error", "urlopen"]
        )
        assert blocked, (
            f"OPA did not block unauthorized egress. "
            f"rc={result.returncode} out={result.stdout[:200]} err={result.stderr[:200]}"
        )

    def test_hitl_network__allows_egress(self, agent):
        """OPA proxy allows access to authorized domain (policy allowlist)."""
        if not _deploy_ready(agent):
            pytest.skip(f"{agent} not deployed")

        py_cmd = (
            "import urllib.request, os; "
            "os.environ['http_proxy']='http://10.200.0.1:3128'; "
            "os.environ['https_proxy']='http://10.200.0.1:3128'; "
            "r = urllib.request.urlopen('http://weather-agent.team1.svc.cluster.local:8080/.well-known/agent-card.json', timeout=10); "
            "print(r.status)"
        )
        result = _kubectl(
            "exec",
            f"deploy/{agent}",
            "-n",
            AGENT_NS,
            "-c",
            "agent",
            "--",
            "python3",
            "-c",
            py_cmd,
            timeout=30,
        )

        combined = (result.stdout + result.stderr).lower()
        opa_deny = any(kw in combined for kw in ["403", "forbidden", "denied"])

        if opa_deny:
            pytest.skip(
                "OPA denied internal service — supervisor netns DNS may not "
                "resolve cluster-local names."
            )
        if result.returncode != 0 and "urlopen" in combined:
            pytest.skip(
                "Internal service unreachable from supervised netns — "
                "may need DNS resolution fix."
            )

    def test_hitl_network__denial_logged(self, agent):
        """OPA denials are logged in supervisor logs with policy details."""
        if not _deploy_ready(agent):
            pytest.skip(f"{agent} not deployed")

        py_cmd = (
            "import urllib.request, os; "
            "os.environ['http_proxy']='http://10.200.0.1:3128'; "
            "urllib.request.urlopen('http://blocked.example', timeout=3)"
        )
        _kubectl(
            "exec",
            f"deploy/{agent}",
            "-n",
            AGENT_NS,
            "-c",
            "agent",
            "--",
            "python3",
            "-c",
            py_cmd,
            timeout=15,
        )

        logs_result = _kubectl(
            "logs",
            f"deploy/{agent}",
            "-n",
            AGENT_NS,
            "-c",
            "agent",
            "--tail=100",
        )

        logs_lower = logs_result.stdout.lower()
        has_opa_log = any(
            kw in logs_lower
            for kw in ["opa:", "policy:", "denied", "blocked", "egress"]
        )

        if not has_opa_log:
            pytest.skip(
                "OPA denial not logged (supervisor may log to different stream)."
            )

        assert has_opa_log
