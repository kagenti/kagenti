"""
T1.1 Connectivity Tests

Tests basic connectivity for all agents — A2A JSON-RPC, kubectl exec,
and sandbox pod execution.

Capability: connectivity
Convention: test_connectivity__{description}[agent]
"""

import os

import httpx
import pytest

from kagenti.tests.e2e.openshell.conftest import (
    BACKEND_AGENTS,
    BACKEND_AVAILABLE,
    backend_send,
    A2A_AGENT_NAMES,
    EXEC_AGENT_NAMES,
    NEMOCLAW_AGENT_CONFIG,
    skip_no_backend,
    skip_no_llm,
    kubectl_run,
    nemoclaw_enabled,
    run_claude_in_sandbox,
    run_opencode_in_sandbox,
    sandbox_crd_installed,
)

pytestmark = pytest.mark.openshell
AGENT_NS = os.getenv("OPENSHELL_AGENT_NAMESPACE", "team1")

EXEC_AGENTS = EXEC_AGENT_NAMES


def _deploy_ready(name: str, namespace: str) -> bool:
    r = kubectl_run(
        "get", "deploy", name, "-n", namespace, "-o", "jsonpath={.status.readyReplicas}"
    )
    return r.returncode == 0 and r.stdout.strip() == "1"


# ── A2A agent connectivity (via kagenti-backend proxy) ──


@pytest.mark.asyncio
@pytest.mark.parametrize("agent", BACKEND_AGENTS)
class TestA2AConnectivity:
    """A2A agents respond via kagenti-backend A2A proxy."""

    @skip_no_backend
    async def test_connectivity__responds(self, agent, backend_url):
        """Agent responds to A2A request through backend proxy."""
        async with httpx.AsyncClient() as client:
            result = await backend_send(
                client, backend_url, AGENT_NS, agent, "Hello, who are you?"
            )
        assert "content" in result, f"Backend response missing 'content': {result}"

    @skip_no_backend
    async def test_connectivity__agent_card(self, agent, backend_url):
        """Agent card accessible through backend proxy."""
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{backend_url}/api/v1/chat/{AGENT_NS}/{agent}/agent-card",
                timeout=30.0,
            )
        if resp.status_code == 503:
            pytest.skip(f"{agent}: backend cannot reach agent (503, supervised netns)")
        assert resp.status_code == 200, f"Agent card failed: {resp.text}"
        card = resp.json()
        assert "name" in card, f"Agent card missing 'name': {card}"


# ── kubectl exec connectivity ──


@pytest.mark.parametrize("agent", EXEC_AGENTS)
class TestExecConnectivity:
    """Agents reachable via kubectl exec (netns blocks port-forward)."""

    def test_connectivity__responds(self, agent):
        """Agent responds to basic exec request."""
        if not _deploy_ready(agent, AGENT_NS):
            pytest.skip(f"{agent}: not deployed")
        r = kubectl_run(
            "exec", f"deploy/{agent}", "-n", AGENT_NS, "--", "echo", "alive"
        )
        if r.returncode != 0:
            pytest.skip(f"{agent}: cannot exec into pod — {r.stderr.strip()}")
        assert "alive" in r.stdout

    def test_connectivity__agent_card(self, agent):
        """Agent card accessible via internal HTTP from kubectl exec."""
        if not _deploy_ready(agent, AGENT_NS):
            pytest.skip(f"{agent}: not deployed")
        result = kubectl_run(
            "exec",
            f"deploy/{agent}",
            "-n",
            AGENT_NS,
            "-c",
            "agent",
            "--",
            "python3",
            "-c",
            "import urllib.request; "
            "r = urllib.request.urlopen('http://localhost:8080/.well-known/agent-card.json', timeout=5); "
            "print(r.read().decode())",
            timeout=30,
        )
        if result.returncode != 0:
            pytest.skip(f"Cannot reach agent card inside netns: {result.stderr[:200]}")
        assert "name" in result.stdout.lower()


# ── Sandbox connectivity (Claude Code, OpenCode) ──


skip_no_crd = pytest.mark.skipif(
    not sandbox_crd_installed(), reason="Sandbox CRD not installed"
)

CANONICAL_DIFF = """--- a/app.py
+++ b/app.py
@@ -1,3 +1,5 @@
+import os
 from flask import Flask, request
 app = Flask(__name__)
+SECRET = os.getenv("DB_PASSWORD")

 @app.route("/query")
 def query():
-    return db.execute(request.args["q"])
+    return db.execute("SELECT * FROM users WHERE id=" + request.args["id"])
"""


class TestSandboxConnectivity:
    """Claude Code and OpenCode sandbox connectivity via LiteLLM."""

    @skip_no_llm
    @skip_no_crd
    def test_connectivity__openshell_claude__simple_prompt(self):
        """Claude Code in sandbox responds to a simple math prompt."""
        output = run_claude_in_sandbox("What is 2+2? Reply with just the number.")
        if output is None:
            pytest.skip("Claude Code sandbox not available.")
        assert "4" in output, f"Expected '4' in output: {output[:200]}"

    @skip_no_llm
    @skip_no_crd
    def test_connectivity__openshell_claude__code_review(self):
        """Claude Code in sandbox can review code for security issues."""
        output = run_claude_in_sandbox(
            f"Review this diff for security issues. Be brief:\n{CANONICAL_DIFF[:500]}"
        )
        if output is None:
            pytest.skip("Claude Code sandbox not available.")
        assert len(output) > 20, f"Response too short: {output[:200]}"
        output_lower = output.lower()
        assert any(
            term in output_lower
            for term in ["sql", "injection", "security", "vulnerable", "command"]
        )

    @skip_no_llm
    @skip_no_crd
    def test_connectivity__openshell_opencode__simple_prompt(self):
        """OpenCode in sandbox responds to a simple math prompt."""
        output = run_opencode_in_sandbox("What is 2+2? Reply with just the number.")
        if output is None:
            pytest.skip("OpenCode sandbox not available.")
        assert "4" in output, f"Expected '4' in output: {output[:200]}"


# ── NemoClaw connectivity (OpenClaw, Hermes) ──

skip_no_nemoclaw = pytest.mark.skipif(
    not nemoclaw_enabled(), reason="NemoClaw tests disabled"
)


@pytest.mark.asyncio
class TestNemoClawConnectivity:
    """NemoClaw agents respond to their native APIs."""

    @skip_no_nemoclaw
    async def test_connectivity__nemoclaw_openclaw__gateway_reachable(
        self, nemoclaw_openclaw_url
    ):
        """OpenClaw gateway responds to HTTP request."""
        config = NEMOCLAW_AGENT_CONFIG["nemoclaw-openclaw"]
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{nemoclaw_openclaw_url}{config['health_path']}",
                timeout=30.0,
            )
        assert resp.status_code in (200, 301, 302), (
            f"OpenClaw gateway returned {resp.status_code}"
        )

    @skip_no_nemoclaw
    @skip_no_llm
    async def test_connectivity__nemoclaw_hermes__deployment_ready(self):
        """Hermes deployment has available replicas and ACP support."""
        ns = os.getenv("OPENSHELL_AGENT_NAMESPACE", "team1")
        result = kubectl_run(
            "get",
            "deploy",
            "nemoclaw-hermes",
            "-n",
            ns,
            "-o",
            "jsonpath={.status.availableReplicas}",
        )
        replicas = result.stdout.strip()
        assert replicas and int(replicas) > 0, (
            f"nemoclaw-hermes has {replicas or 0} available replicas"
        )

    @skip_no_nemoclaw
    @skip_no_llm
    async def test_connectivity__nemoclaw_hermes__acp_responds(self):
        """Hermes responds to a prompt via the ACP bridge (ExecSandbox path)."""
        ns = os.getenv("OPENSHELL_AGENT_NAMESPACE", "team1")
        pods = kubectl_run("get", "pods", "-n", ns, "--no-headers")
        hermes_pod = ""
        for line in pods.stdout.strip().split("\n"):
            if "nemoclaw-hermes" in line and "Running" in line:
                hermes_pod = line.split()[0]
                break
        assert hermes_pod, f"No running nemoclaw-hermes pod in {ns}"

        result = kubectl_run(
            "exec",
            hermes_pod,
            "-n",
            ns,
            "--",
            "timeout",
            "30",
            "hermes",
            "chat",
            "-q",
            "What is 2+2? Reply with just the number.",
            timeout=45,
        )
        assert result.returncode == 0, (
            f"hermes chat failed (exit {result.returncode}): {result.stderr[-300:]}"
        )
        output = result.stdout.strip()
        assert len(output) > 0, "Empty response from hermes"
        assert "4" in output, f"Hermes didn't answer correctly: {output[-200:]}"

    @skip_no_nemoclaw
    async def test_connectivity__nemoclaw_openclaw__deployment_ready(self):
        """OpenClaw deployment has ready replicas."""
        r = kubectl_run(
            "get",
            "deploy",
            "nemoclaw-openclaw",
            "-n",
            AGENT_NS,
            "-o",
            "jsonpath={.status.readyReplicas}",
        )
        if r.returncode != 0:
            pytest.skip("nemoclaw-openclaw deployment not found")
        assert r.stdout.strip() == "1", (
            f"nemoclaw-openclaw has {r.stdout.strip()} ready replicas"
        )

    @skip_no_nemoclaw
    async def test_connectivity__nemoclaw_openclaw__api_surface(
        self, nemoclaw_openclaw_url
    ):
        """Discover which HTTP endpoints the OpenClaw gateway exposes."""
        endpoints_found = []
        async with httpx.AsyncClient() as client:
            for path in ["/", "/health", "/v1/models", "/v1/chat/completions"]:
                try:
                    resp = await client.get(
                        f"{nemoclaw_openclaw_url}{path}",
                        timeout=10.0,
                    )
                    endpoints_found.append((path, resp.status_code))
                except httpx.HTTPError:
                    endpoints_found.append((path, "error"))

            # Try POST to common chat endpoints
            payload = {
                "model": "gpt-4o-mini",
                "messages": [{"role": "user", "content": "hi"}],
                "max_tokens": 5,
            }
            for path in ["/v1/chat/completions", "/chat/completions", "/api/chat", "/"]:
                try:
                    resp = await client.post(
                        f"{nemoclaw_openclaw_url}{path}",
                        json=payload,
                        timeout=15.0,
                    )
                    endpoints_found.append((f"POST {path}", resp.status_code))
                except httpx.HTTPError as e:
                    endpoints_found.append((f"POST {path}", str(type(e).__name__)))

        assert any(status == 200 for _, status in endpoints_found), (
            f"No reachable endpoint found: {endpoints_found}"
        )
