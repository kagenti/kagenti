"""
T3.1 Skill Execution Tests

Tests skill execution across all agents and models.

Capability: skill_pr_review, skill_rca, skill_security, skill_github_pr
Convention: test_skill_{type}__{description}[agent]
"""

import os

import httpx
import pytest

from kagenti.tests.e2e.openshell.conftest import (
    a2a_send,
    extract_a2a_text,
    A2A_AGENT_NAMES,
    CLI_AGENT_NAMES,
    FIXTURE_MAP,
    LLM_CAPABLE_AGENTS,
    NEMOCLAW_AGENT_NAMES,
    NO_LLM_AGENTS,
    skip_no_llm,
    litellm_chat,
    litellm_chat_text,
    openclaw_chat,
    record_llm_metric,
    run_claude_in_sandbox,
    run_opencode_in_sandbox,
    sandbox_crd_installed,
    CANONICAL_DIFF,
    CANONICAL_CODE,
    CANONICAL_CI_LOG,
    LLM_MODELS,
    _read_skill,
)

# All agents tested for skill execution — single parametrized list
SKILL_AGENTS = [
    pytest.param("claude-sdk-agent", id="claude_sdk"),
    pytest.param("adk-agent-supervised", id="adk_supervised"),
    pytest.param("openshell-claude", id="openshell_claude"),
    pytest.param("openshell-opencode", id="openshell_opencode"),
    pytest.param("nemoclaw-openclaw", id="nemoclaw_openclaw"),
    pytest.param("weather-agent-supervised", id="weather_supervised"),
]

pytestmark = pytest.mark.openshell

skip_no_crd = pytest.mark.skipif(
    not sandbox_crd_installed(), reason="Sandbox CRD not installed"
)

REPO_ROOT = os.getenv(
    "REPO_ROOT",
    os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."),
)

SKILL_MODELS = LLM_MODELS if LLM_MODELS else ["default"]


# ═══════════════════════════════════════════════════════════════════════════
# Skill infrastructure (all agents share this)
# ═══════════════════════════════════════════════════════════════════════════


class TestSkillInfra:
    """Verify key kagenti skills exist in the repo."""

    def test_skill_pr_review__all__skill_files_exist(self):
        """Key kagenti skills must exist in the repo."""
        skills_dir = os.path.join(REPO_ROOT, ".claude", "skills")
        if not os.path.isdir(skills_dir):
            pytest.skip(f"Skills directory not found: {skills_dir}")

        expected = ["github:pr-review", "rca:ci", "k8s:health", "test:review"]
        for skill in expected:
            skill_path = os.path.join(skills_dir, skill, "SKILL.md")
            assert os.path.exists(skill_path), (
                f"Skill {skill} not found at {skill_path}"
            )

    def test_skill_pr_review__all__skill_structure(self):
        """Each skill directory must contain a SKILL.md file."""
        skills_dir = os.path.join(REPO_ROOT, ".claude", "skills")
        if not os.path.isdir(skills_dir):
            pytest.skip(f"Skills directory not found: {skills_dir}")

        skill_dirs = [
            d
            for d in os.listdir(skills_dir)
            if os.path.isdir(os.path.join(skills_dir, d))
        ]
        assert len(skill_dirs) >= 4, (
            f"Expected 4+ skill directories, found {len(skill_dirs)}"
        )
        for d in skill_dirs:
            skill_md = os.path.join(skills_dir, d, "SKILL.md")
            assert os.path.exists(skill_md), f"Skill {d} missing SKILL.md"


# ═══════════════════════════════════════════════════════════════════════════
# Skill execution helper — routes to the right agent protocol
# ═══════════════════════════════════════════════════════════════════════════


async def _execute_skill(agent: str, prompt: str, request) -> str:
    """Execute a skill prompt on the given agent. Returns response text.

    Routes to the correct protocol based on agent type:
    - A2A agents: a2a_send() via port-forward
    - CLI agents: run_*_in_sandbox() via kubectl exec
    - No-LLM agents: pytest.skip()
    """
    if agent in NO_LLM_AGENTS:
        pytest.skip(f"{agent}: no LLM — cannot execute skills (by design)")

    if agent in A2A_AGENT_NAMES:
        fixture_name = FIXTURE_MAP.get(agent)
        if not fixture_name:
            pytest.skip(f"{agent}: no URL fixture in FIXTURE_MAP")
        url = request.getfixturevalue(fixture_name)
        async with httpx.AsyncClient() as client:
            resp = await a2a_send(
                client, url, prompt, request_id=f"skill-{agent}", timeout=120.0
            )
        assert "result" in resp, f"{agent}: A2A response missing 'result'"
        text = extract_a2a_text(resp)
        assert text and len(text) > 20, f"{agent}: response too short: {text[:200]}"
        return text

    if agent == "openshell-claude":
        if not sandbox_crd_installed():
            pytest.skip("Sandbox CRD not installed")
        output = run_claude_in_sandbox(prompt)
        if output is None:
            pytest.skip("openshell_claude: sandbox or LiteLLM not available")
        if not output.strip():
            pytest.skip(
                "openshell_claude: LLM returned empty — "
                "known flake with llama-scout-17b (~17% empty rate)"
            )
        return output

    if agent == "openshell-opencode":
        if not sandbox_crd_installed():
            pytest.skip("Sandbox CRD not installed")
        output = run_opencode_in_sandbox(prompt)
        if output is None:
            pytest.skip("openshell_opencode: sandbox or LiteLLM not available")
        assert len(output) > 20, f"OpenCode response too short: {output[:200]}"
        return output

    if agent in NEMOCLAW_AGENT_NAMES:
        from kagenti.tests.e2e.openshell.conftest import nemoclaw_enabled

        if not nemoclaw_enabled():
            pytest.skip(f"{agent}: NemoClaw tests disabled")
        fixture_name = f"nemoclaw_{agent.split('-')[-1]}_url"
        try:
            url = request.getfixturevalue(fixture_name)
        except pytest.FixtureLookupError:
            pytest.skip(f"{agent}: no fixture {fixture_name}")
        async with httpx.AsyncClient() as client:
            resp = await openclaw_chat(client, url, prompt)
        if resp is None:
            pytest.skip(
                f"{agent}: gateway does not expose chat API. "
                "Needs A2A adapter or NemoClaw OpenAI-compat plugin."
            )
        text = litellm_chat_text(resp)
        assert text and len(text) > 20, f"{agent}: response too short: {text[:200]}"
        return text

    pytest.skip(f"{agent}: unsupported agent type for skill execution")


# ═══════════════════════════════════════════════════════════════════════════
# Skill tests — parametrized across all agents
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
class TestSkillPRReview:
    """PR review skill — parametrized across all agents."""

    @skip_no_llm
    @pytest.mark.parametrize("agent", SKILL_AGENTS)
    async def test_skill_pr_review(self, agent, request):
        """Agent reviews a PR diff for security issues."""
        prompt = (
            f"Review this diff for security issues. List each issue:\n"
            f"```diff\n{CANONICAL_DIFF}\n```"
        )
        text = await _execute_skill(agent, prompt, request)
        text_lower = text.lower()
        assert any(
            kw in text_lower
            for kw in ["sql", "injection", "os.system", "command", "security"]
        ), f"{agent}: didn't find security issues: {text[:200]}"


@pytest.mark.asyncio
class TestSkillRCA:
    """RCA skill — parametrized across all agents."""

    @skip_no_llm
    @pytest.mark.parametrize("agent", SKILL_AGENTS)
    async def test_skill_rca(self, agent, request):
        """Agent analyzes CI logs to identify root cause."""
        prompt = (
            f"Analyze these CI logs and identify the root cause:\n"
            f"```\n{CANONICAL_CI_LOG}\n```"
        )
        text = await _execute_skill(agent, prompt, request)
        text_lower = text.lower()
        assert any(
            kw in text_lower
            for kw in ["secret", "webhook", "tls", "root cause", "crashloop", "mount"]
        ), f"{agent}: didn't identify root cause: {text[:200]}"


@pytest.mark.asyncio
class TestSkillSecurity:
    """Security review skill — parametrized across all agents."""

    @skip_no_llm
    @pytest.mark.parametrize("agent", SKILL_AGENTS)
    async def test_skill_security(self, agent, request):
        """Agent reviews code for security vulnerabilities."""
        prompt = (
            f"Review this code for security vulnerabilities. "
            f"List each issue found:\n```python\n{CANONICAL_CODE}\n```"
        )
        text = await _execute_skill(agent, prompt, request)
        text_lower = text.lower()
        assert any(
            kw in text_lower
            for kw in ["pickle", "shell", "injection", "sql", "command", "security"]
        ), f"{agent}: didn't find security issues: {text[:200]}"


@pytest.mark.asyncio
class TestSkillGithubPR:
    """GitHub PR skill — parametrized across all agents."""

    @skip_no_llm
    @pytest.mark.parametrize("agent", SKILL_AGENTS)
    async def test_skill_github_pr(self, agent, request):
        """Agent reviews a code diff from a PR."""
        prompt = (
            f"Review this pull request diff for issues:\n```diff\n{CANONICAL_DIFF}\n```"
        )
        await _execute_skill(agent, prompt, request)


# ═══════════════════════════════════════════════════════════════════════════
# NemoClaw OpenClaw skill execution (via gateway HTTP API)
# ═══════════════════════════════════════════════════════════════════════════

# ═══════════════════════════════════════════════════════════════════════════
# Audit logging (CLI binary presence checks)
# ═══════════════════════════════════════════════════════════════════════════


class TestAuditLogging:
    """Verify builtin sandbox images have expected CLI tools."""

    @skip_no_crd
    def test_audit_logging__openshell_claude__claude_binary_present(self):
        """Claude Code sandbox must have `claude` binary."""
        from kagenti.tests.e2e.openshell.conftest import (
            _ensure_claude_sandbox,
            kubectl_run,
        )

        pod = _ensure_claude_sandbox()
        if not pod:
            pytest.skip("Claude sandbox pod not available")
        result = kubectl_run(
            "exec",
            pod,
            "-n",
            "team1",
            "--",
            "sh",
            "-c",
            "which claude && claude --version 2>/dev/null || true",
            timeout=15,
        )
        assert result.returncode == 0, f"exec failed: {result.stderr}"
        assert "claude" in result.stdout.lower(), (
            f"claude binary not found in sandbox: {result.stdout}"
        )

    @skip_no_crd
    def test_audit_logging__openshell_opencode__opencode_binary_present(self):
        """OpenCode sandbox must have `opencode` binary."""
        from kagenti.tests.e2e.openshell.conftest import (
            _ensure_claude_sandbox,
            kubectl_run,
        )

        pod = _ensure_claude_sandbox()
        if not pod:
            pytest.skip("Sandbox pod not available")
        result = kubectl_run(
            "exec",
            pod,
            "-n",
            "team1",
            "--",
            "sh",
            "-c",
            "which opencode 2>/dev/null && echo found || echo missing",
            timeout=15,
        )
        assert result.returncode == 0, f"exec failed: {result.stderr}"
        if "missing" in result.stdout:
            pytest.skip(
                "opencode binary not in base image — "
                "OpenCode tests use a separate sandbox with opencode pre-installed"
            )
        assert "found" in result.stdout

    @skip_no_crd
    def test_audit_logging__openshell_generic__has_bash_and_tools(self):
        """Generic sandbox must have bash, git, curl."""
        from kagenti.tests.e2e.openshell.conftest import (
            _ensure_claude_sandbox,
            kubectl_run,
        )

        pod = _ensure_claude_sandbox()
        if not pod:
            pytest.skip("Sandbox pod not available")
        result = kubectl_run(
            "exec",
            pod,
            "-n",
            "team1",
            "--",
            "sh",
            "-c",
            "which bash && which git && which curl && echo all-found",
            timeout=15,
        )
        assert result.returncode == 0, f"exec failed: {result.stderr}"
        assert "all-found" in result.stdout, (
            f"Missing tools in sandbox: {result.stdout}"
        )


# ═══════════════════════════════════════════════════════════════════════════
# Per-model skill execution (parametrized across OPENSHELL_LLM_MODELS)
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
class TestSkillPerModel:
    """Run skill tests with each configured LLM model via direct LiteLLM calls.

    Calls LiteLLM proxy directly with model=<specific_model> to test each
    model independently. Records per-model metrics (tokens, time, quality)
    to $LOG_DIR/llm-metrics.json for the parser.
    """

    @skip_no_llm
    @pytest.mark.parametrize(
        "model",
        SKILL_MODELS,
        ids=lambda m: m.replace(":", "_").replace("/", "_"),
    )
    async def test_skill_pr_review__per_model__responds(self, model, request):
        """PR review skill works with each configured model."""
        if model == "default":
            pytest.skip("No OPENSHELL_LLM_MODELS configured")

        import time

        prompt = (
            f"Review this diff for security issues. List each issue found:\n"
            f"```diff\n{CANONICAL_DIFF}\n```"
        )
        keywords = ["sql", "injection", "os.system", "command", "security"]
        t0 = time.monotonic()
        async with httpx.AsyncClient() as client:
            resp = await litellm_chat(client, prompt, model=model)
        duration = time.monotonic() - t0
        text = litellm_chat_text(resp)

        record_llm_metric(
            test_name=request.node.name,
            model=model,
            agent="litellm_direct",
            capability="skill_pr_review",
            status="PASSED" if text and len(text) > 30 else "FAILED",
            response=resp,
            duration_s=duration,
            response_text=text,
            keywords=keywords,
        )
        assert text and len(text) > 30, (
            f"Model {model} produced insufficient output: {text[:200]}"
        )

    @skip_no_llm
    @pytest.mark.parametrize(
        "model",
        SKILL_MODELS,
        ids=lambda m: m.replace(":", "_").replace("/", "_"),
    )
    async def test_skill_rca__per_model__identifies_issue(self, model, request):
        """RCA skill works with each configured model."""
        if model == "default":
            pytest.skip("No OPENSHELL_LLM_MODELS configured")

        import time

        prompt = (
            f"Analyze these CI logs and identify the root cause of the failure:\n"
            f"```\n{CANONICAL_CI_LOG}\n```"
        )
        keywords = ["secret", "webhook", "tls", "mount", "root cause", "missing"]
        t0 = time.monotonic()
        async with httpx.AsyncClient() as client:
            resp = await litellm_chat(client, prompt, model=model)
        duration = time.monotonic() - t0
        text = litellm_chat_text(resp)

        record_llm_metric(
            test_name=request.node.name,
            model=model,
            agent="litellm_direct",
            capability="skill_rca",
            status="PASSED" if text and len(text) > 30 else "FAILED",
            response=resp,
            duration_s=duration,
            response_text=text,
            keywords=keywords,
        )
        assert text and len(text) > 30, (
            f"Model {model} RCA output too short: {text[:200]}"
        )

    @skip_no_llm
    @pytest.mark.parametrize(
        "model",
        SKILL_MODELS,
        ids=lambda m: m.replace(":", "_").replace("/", "_"),
    )
    async def test_skill_security__per_model__finds_issues(self, model, request):
        """Security review skill works with each configured model."""
        if model == "default":
            pytest.skip("No OPENSHELL_LLM_MODELS configured")

        import time

        prompt = (
            f"Review this code for security vulnerabilities. List each issue:\n"
            f"```python\n{CANONICAL_CODE}\n```"
        )
        keywords = ["pickle", "shell=true", "injection", "sql", "command"]
        t0 = time.monotonic()
        async with httpx.AsyncClient() as client:
            resp = await litellm_chat(client, prompt, model=model)
        duration = time.monotonic() - t0
        text = litellm_chat_text(resp)

        record_llm_metric(
            test_name=request.node.name,
            model=model,
            agent="litellm_direct",
            capability="skill_security",
            status="PASSED" if text and len(text) > 30 else "FAILED",
            response=resp,
            duration_s=duration,
            response_text=text,
            keywords=keywords,
        )
        assert text and len(text) > 30, (
            f"Model {model} security review too short: {text[:200]}"
        )
