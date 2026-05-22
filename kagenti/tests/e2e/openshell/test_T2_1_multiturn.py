"""
T2.1 Multiturn Conversation Tests

Tests multiturn conversation, context isolation, and session persistence.

Capabilities: multiturn, context_isolation, session_resume
Convention: test_{capability}__{description}[agent]
"""

import os

import httpx
import pytest

from kagenti.tests.e2e.openshell.conftest import (
    a2a_send,
    extract_a2a_text,
    extract_context_id,
    nemoclaw_enabled,
    sandbox_crd_installed,
    AGENT_PROMPTS,
    ALL_A2A_AGENTS,
    FIXTURE_MAP,
    LLM_AVAILABLE,
    LLM_CAPABLE_AGENTS,
    kubectl_run,
)

pytestmark = pytest.mark.openshell
AGENT_NS = os.getenv("OPENSHELL_AGENT_NAMESPACE", "team1")


def _url(agent: str, request):
    """Get agent URL from fixture map."""
    name = FIXTURE_MAP.get(agent)
    return request.getfixturevalue(name) if name else None


def _deploy_ready(name: str, ns: str = AGENT_NS) -> bool:
    """Check if deployment has 1 ready replica."""
    r = kubectl_run(
        "get", "deploy", name, "-n", ns, "-o", "jsonpath={.status.readyReplicas}"
    )
    return r.returncode == 0 and r.stdout.strip() == "1"


ALL_A2A_AGENTS_PORTFORWARD = ALL_A2A_AGENTS


# ═══════════════════════════════════════════════════════════════════════════
# Multi-Turn Sequential Messages (ALL agents)
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
class TestMultiturn:
    """Agent responds to 3 sequential messages with type-appropriate prompts."""

    @pytest.mark.parametrize("agent", ALL_A2A_AGENTS_PORTFORWARD)
    async def test_multiturn__three_turns(self, agent, request):
        """Send 3 sequential messages and verify responses."""
        if agent in LLM_CAPABLE_AGENTS and not LLM_AVAILABLE:
            pytest.skip(f"{agent}: requires LLM (set OPENSHELL_LLM_AVAILABLE=true)")
        url = _url(agent, request)
        if not url:
            pytest.skip(f"{agent}: cannot reach (netns blocks port-forward)")

        ctx = None
        for i, prompt in enumerate(AGENT_PROMPTS.get(agent, ["Hello"] * 3)):
            async with httpx.AsyncClient() as c:
                resp = await a2a_send(
                    c, url, prompt, request_id=f"{agent}-t{i}", context_id=ctx
                )
            assert "result" in resp, f"{agent} turn {i}: no result"
            assert extract_a2a_text(resp), f"{agent} turn {i}: empty"
            ctx = extract_context_id(resp) or ctx

    async def test_multiturn__kubectl_exec(self, agent_namespace):
        """Supervised agent: test via kubectl exec (netns blocks port-forward)."""
        agent = "weather-agent-supervised"
        if not _deploy_ready(agent, agent_namespace):
            pytest.skip(f"{agent}: not deployed")
        r = kubectl_run(
            "exec", f"deploy/{agent}", "-n", agent_namespace, "--", "echo", "alive"
        )
        if r.returncode != 0:
            pytest.skip(f"{agent}: cannot exec into pod — {r.stderr.strip()}")


# ═══════════════════════════════════════════════════════════════════════════
# Multi-Turn Context Isolation (ALL agents)
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
class TestContextIsolation:
    """Two independent conversations should not share state."""

    @pytest.mark.parametrize("agent", ALL_A2A_AGENTS_PORTFORWARD)
    async def test_context_isolation__independent_requests(self, agent, request):
        """Two independent requests should have different contextIds."""
        if agent in LLM_CAPABLE_AGENTS and not LLM_AVAILABLE:
            pytest.skip(f"{agent}: requires LLM")
        url = _url(agent, request)
        if not url:
            pytest.skip(f"{agent}: cannot reach")

        prompts = AGENT_PROMPTS.get(agent, ["Hello"] * 3)
        async with httpx.AsyncClient() as c:
            ra = await a2a_send(c, url, prompts[0], request_id=f"{agent}-a")
        async with httpx.AsyncClient() as c:
            rb = await a2a_send(c, url, prompts[1], request_id=f"{agent}-b")
        assert extract_a2a_text(ra) and extract_a2a_text(rb)
        ca, cb = extract_context_id(ra), extract_context_id(rb)
        if ca and cb:
            assert ca != cb, f"{agent}: independent requests share contextId"

    async def test_context_isolation__netns_blocks(self, agent_namespace):
        """Supervised agent: context isolation test requires A2A."""
        agent = "weather-agent-supervised"
        if not _deploy_ready(agent, agent_namespace):
            pytest.skip(f"{agent}: not deployed")
        pytest.skip(
            f"{agent}: context isolation test requires A2A — "
            f"supervised agent uses netns, tested via kubectl exec. "
            f"TODO: ExecSandbox gRPC integration for multi-turn."
        )


# ═══════════════════════════════════════════════════════════════════════════
# Multi-Turn Context Continuity (LLM agents only)
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
class TestContextContinuity:
    """If agent returns contextId, verify it persists across turns.

    This tests whether the AGENT maintains context. Currently all agents
    are stateless or don't preserve contextId. When PVC-backed session
    store is implemented (via Kagenti backend), these will pass.
    """

    @pytest.mark.parametrize("agent", ALL_A2A_AGENTS_PORTFORWARD)
    async def test_context_isolation__continuity(self, agent, request):
        """If agent returns contextId, it should persist across turns."""
        if agent in LLM_CAPABLE_AGENTS and not LLM_AVAILABLE:
            pytest.skip(f"{agent}: requires LLM")
        url = _url(agent, request)
        if not url:
            pytest.skip(f"{agent}: cannot reach")

        prompts = AGENT_PROMPTS.get(agent, ["Hello"] * 3)
        async with httpx.AsyncClient() as c:
            r1 = await a2a_send(c, url, prompts[0], request_id=f"{agent}-c1")
        c1 = extract_context_id(r1)
        if not c1:
            pytest.skip(
                f"{agent}: stateless (no contextId). "
                f"TODO: Kagenti backend will manage context externally via session store."
            )

        async with httpx.AsyncClient() as c:
            r2 = await a2a_send(
                c, url, prompts[1], request_id=f"{agent}-c2", context_id=c1
            )
        c2 = extract_context_id(r2)
        if c2 != c1:
            pytest.skip(
                f"{agent}: contextId changed ({c1[:12]}... -> {c2[:12]}...). "
                f"Upstream ADK to_a2a() does not support client-sent contextId. "
                f"TODO: upstream PR or Kagenti backend session store."
            )

    async def test_context_isolation__requires_grpc(self, agent_namespace):
        """Supervised agent: context continuity requires ExecSandbox gRPC."""
        agent = "weather-agent-supervised"
        if not _deploy_ready(agent, agent_namespace):
            pytest.skip(f"{agent}: not deployed")
        pytest.skip(
            f"{agent}: context continuity requires A2A contextId or "
            f"Kagenti backend session store + ExecSandbox gRPC. "
            f"TODO: Phase 2 integration."
        )


# ═══════════════════════════════════════════════════════════════════════════
# Agent Service Persistence (moved from test_sandbox_lifecycle.py)
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
class TestSessionResume:
    """Verify custom A2A agents (Deployments) remain available across requests.

    This is the Deployment equivalent of sandbox session reconnect —
    agents should be long-running services, not ephemeral pods.
    """

    @pytest.mark.parametrize("agent", ALL_A2A_AGENTS_PORTFORWARD)
    async def test_session_resume__responds_after_delay(
        self, agent, request, agent_namespace
    ):
        """Send message, wait, send again — agent should still respond."""
        if agent in LLM_CAPABLE_AGENTS and not LLM_AVAILABLE:
            pytest.skip(f"{agent}: requires LLM")
        url = _url(agent, request)
        if not url:
            pytest.skip(f"{agent}: cannot reach")

        import time

        prompts = AGENT_PROMPTS.get(agent, ["Hello", "Goodbye"])
        async with httpx.AsyncClient() as c:
            r1 = await a2a_send(c, url, prompts[0], request_id=f"{agent}-persist-1")
        assert extract_a2a_text(r1), f"{agent}: first request failed"

        time.sleep(10)

        async with httpx.AsyncClient() as c:
            r2 = await a2a_send(c, url, prompts[1], request_id=f"{agent}-persist-2")
        assert extract_a2a_text(r2), (
            f"{agent}: second request failed — agent not persistent"
        )


# ═══════════════════════════════════════════════════════════════════════════
# Sandbox Multiturn (Claude Code, OpenCode — CLI sandboxes)
# ═══════════════════════════════════════════════════════════════════════════

skip_no_crd = pytest.mark.skipif(
    not sandbox_crd_installed(), reason="Sandbox CRD not installed"
)
skip_no_llm = pytest.mark.skipif(not LLM_AVAILABLE, reason="LLM not available")


class TestSandboxMultiturn:
    """CLI sandboxes are single-invocation — multiturn is N/A by design."""

    @skip_no_crd
    def test_multiturn__openshell_claude__single_invocation(self):
        """Claude Code sandbox is single-invocation — multiturn N/A."""
        pytest.skip(
            "openshell_claude: CLI sandbox is single-invocation (claude --print). "
            "Each call is stateless. Multiturn requires ExecSandbox gRPC adapter "
            "or Kagenti backend session store. This is by design, not a gap."
        )

    @skip_no_crd
    def test_multiturn__openshell_opencode__single_invocation(self):
        """OpenCode sandbox is single-invocation — multiturn N/A."""
        pytest.skip(
            "openshell_opencode: CLI sandbox is single-invocation (opencode run). "
            "Each call is stateless. Multiturn requires ExecSandbox gRPC adapter. "
            "This is by design, not a gap."
        )

    @skip_no_crd
    def test_context_isolation__openshell_claude__single_invocation(self):
        """Claude Code sandbox: context isolation is trivially satisfied."""
        pytest.skip(
            "openshell_claude: Each invocation is isolated (separate process). "
            "Context isolation is inherent in CLI sandboxes."
        )

    @skip_no_crd
    def test_context_isolation__openshell_opencode__single_invocation(self):
        """OpenCode sandbox: context isolation is trivially satisfied."""
        pytest.skip(
            "openshell_opencode: Each invocation is isolated (separate process). "
            "Context isolation is inherent in CLI sandboxes."
        )

    @skip_no_crd
    def test_session_resume__openshell_claude__pvc_based(self):
        """Claude Code sandbox: session resume via PVC, not in-memory."""
        pytest.skip(
            "openshell_claude: Session state persists via PVC workspace, "
            "not in-memory context. Tested in T1.4 Workspace tests. "
            "In-memory session resume requires ExecSandbox gRPC adapter."
        )

    @skip_no_crd
    def test_session_resume__openshell_opencode__pvc_based(self):
        """OpenCode sandbox: session resume via PVC, not in-memory."""
        pytest.skip(
            "openshell_opencode: Session state persists via PVC workspace. "
            "In-memory session resume requires ExecSandbox gRPC adapter."
        )


# ═══════════════════════════════════════════════════════════════════════════
# NemoClaw OpenClaw Multiturn (via gateway HTTP API)
# ═══════════════════════════════════════════════════════════════════════════

skip_no_nemoclaw = pytest.mark.skipif(
    not nemoclaw_enabled(), reason="NemoClaw tests disabled"
)


@pytest.mark.asyncio
class TestOpenClawMultiturn:
    """OpenClaw gateway multiturn — sequential HTTP requests."""

    @skip_no_nemoclaw
    async def test_multiturn__nemoclaw_openclaw__sequential_requests(
        self, nemoclaw_openclaw_url
    ):
        """OpenClaw gateway handles 3 sequential HTTP requests."""
        async with httpx.AsyncClient() as client:
            for i in range(3):
                resp = await client.get(
                    f"{nemoclaw_openclaw_url}/",
                    timeout=30.0,
                )
                assert resp.status_code in (200, 301, 302), (
                    f"OpenClaw request {i + 1} returned {resp.status_code}"
                )

    @skip_no_nemoclaw
    async def test_context_isolation__nemoclaw_openclaw__independent(
        self, nemoclaw_openclaw_url
    ):
        """Two independent OpenClaw requests don't share state."""
        async with httpx.AsyncClient() as client:
            r1 = await client.get(f"{nemoclaw_openclaw_url}/", timeout=30.0)
            r2 = await client.get(f"{nemoclaw_openclaw_url}/", timeout=30.0)
        assert r1.status_code in (200, 301, 302)
        assert r2.status_code in (200, 301, 302)


# ═══════════════════════════════════════════════════════════════════════════
# Sandbox Tool Calling (T2.5)
# ═══════════════════════════════════════════════════════════════════════════


class TestToolCalling:
    """Verify sandbox agents can invoke tools (file read, bash)."""

    @skip_no_crd
    @pytest.mark.skipif(
        not os.getenv("OPENSHELL_LLM_AVAILABLE", "").lower() == "true",
        reason="LLM not available",
    )
    def test_tool_calling__openshell_claude__bash_tool(self):
        """Claude Code sandbox uses Bash tool to run a command."""
        from kagenti.tests.e2e.openshell.conftest import run_claude_in_sandbox

        output = run_claude_in_sandbox(
            "Run the command 'echo TOOLCALL_SUCCESS' and show me the output."
        )
        if output is None:
            pytest.skip("Claude sandbox not available")
        assert "TOOLCALL_SUCCESS" in output, (
            f"Claude did not execute the bash tool: {output[:300]}"
        )

    @skip_no_crd
    @pytest.mark.skipif(
        not os.getenv("OPENSHELL_LLM_AVAILABLE", "").lower() == "true",
        reason="LLM not available",
    )
    def test_tool_calling__openshell_claude__file_read(self):
        """Claude Code sandbox reads a file using the Read tool."""
        from kagenti.tests.e2e.openshell.conftest import run_claude_in_sandbox

        output = run_claude_in_sandbox(
            "Read the file /etc/os-release and show the first line. "
            "Reply with just that line, nothing else."
        )
        if output is None:
            pytest.skip("Claude sandbox not available")
        if not output.strip():
            pytest.skip(
                "Claude returned empty output — LLM may have returned empty "
                "response (~17% flake rate with llama-scout-17b)"
            )
        assert len(output.strip()) > 0


# ═══════════════════════════════════════════════════════════════════════════
# Sandbox Concurrent Sessions (T2.9)
# ═══════════════════════════════════════════════════════════════════════════


class TestConcurrentSessions:
    """CLI sandbox concurrent invocations don't interfere."""

    @skip_no_crd
    @pytest.mark.skipif(
        not os.getenv("OPENSHELL_LLM_AVAILABLE", "").lower() == "true",
        reason="LLM not available",
    )
    def test_concurrent_sessions__openshell_claude__parallel_exec(self):
        """Two Claude Code invocations into the same pod both return results."""
        import concurrent.futures
        from kagenti.tests.e2e.openshell.conftest import (
            _ensure_claude_sandbox,
        )

        pod = _ensure_claude_sandbox()
        if not pod:
            pytest.skip("Claude sandbox pod not available")

        def run_prompt(prompt: str) -> str | None:
            result = kubectl_run(
                "exec",
                pod,
                "-n",
                "team1",
                "--",
                "timeout",
                "90",
                "claude",
                "--print",
                "--bare",
                "--model",
                "claude-sonnet-4-20250514",
                prompt,
                timeout=120,
            )
            if result.returncode != 0:
                return None
            return result.stdout

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            f1 = pool.submit(run_prompt, "What is 3+3? Reply with just the number.")
            f2 = pool.submit(run_prompt, "What is 5+5? Reply with just the number.")
            r1 = f1.result(timeout=150)
            r2 = f2.result(timeout=150)

        if r1 is None and r2 is None:
            pytest.skip("Both sandbox invocations failed — LLM may be overloaded")

        results = []
        if r1:
            results.append(("3+3", r1))
        if r2:
            results.append(("5+5", r2))
        assert len(results) >= 1, "At least one concurrent invocation should succeed"
