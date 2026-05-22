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
    a2a_send,
    A2A_AGENT_NAMES,
    EXEC_AGENT_NAMES,
    FIXTURE_MAP,
    LLM_AVAILABLE,
    LLM_CAPABLE_AGENTS,
    NEMOCLAW_AGENT_CONFIG,
    skip_no_llm,
    kubectl_run,
    nemoclaw_enabled,
    run_claude_in_sandbox,
    run_opencode_in_sandbox,
    sandbox_crd_installed,
)

pytestmark = pytest.mark.openshell
AGENT_NS = os.getenv("OPENSHELL_AGENT_NAMESPACE", "team1")

A2A_AGENTS = A2A_AGENT_NAMES
EXEC_AGENTS = EXEC_AGENT_NAMES


def _url(agent: str, request):
    name = FIXTURE_MAP.get(agent)
    return request.getfixturevalue(name) if name else None


def _deploy_ready(name: str, namespace: str) -> bool:
    r = kubectl_run(
        "get", "deploy", name, "-n", namespace, "-o", "jsonpath={.status.readyReplicas}"
    )
    return r.returncode == 0 and r.stdout.strip() == "1"


# ── A2A agent connectivity ──


@pytest.mark.asyncio
@pytest.mark.parametrize("agent", A2A_AGENTS)
class TestA2AConnectivity:
    """A2A agents respond to JSON-RPC message/send."""

    async def test_connectivity__responds(self, agent, request):
        """Agent responds to basic A2A request."""
        url = _url(agent, request)
        if url is None:
            pytest.skip(f"{agent}: no URL fixture")
        async with httpx.AsyncClient() as client:
            resp = await a2a_send(client, url, "Hello, who are you?")
        assert "result" in resp, f"A2A response missing 'result': {resp}"

    async def test_connectivity__agent_card(self, agent, request):
        """Agent exposes .well-known/agent-card.json."""
        url = _url(agent, request)
        if url is None:
            pytest.skip(f"{agent}: no URL fixture")
        async with httpx.AsyncClient() as client:
            resp = await client.get(f"{url}/.well-known/agent-card.json", timeout=30.0)
            if resp.status_code == 404:
                resp = await client.get(f"{url}/.well-known/agent.json", timeout=30.0)
        assert resp.status_code == 200
        card = resp.json()
        assert "name" in card or "agent" in card


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
    async def test_connectivity__nemoclaw_hermes__chat_completion(
        self, nemoclaw_hermes_url
    ):
        """Hermes responds to OpenAI-compatible chat completion."""
        async with httpx.AsyncClient() as client:
            try:
                resp = await client.post(
                    f"{nemoclaw_hermes_url}/v1/chat/completions",
                    json={
                        "model": "gpt-4o-mini",
                        "messages": [{"role": "user", "content": "Say hi"}],
                        "max_tokens": 10,
                    },
                    timeout=30.0,
                )
                assert resp.status_code == 200
                data = resp.json()
                assert "choices" in data
            except (httpx.RemoteProtocolError, httpx.ReadError):
                pytest.skip(
                    "Hermes uses internal protocol — HTTP API requires NemoClaw plugin"
                )

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
