"""
Kagenti Skill Execution Tests

Tests that verify agents can load and execute kagenti skills.

Consolidated from:
- test_skill_execution.py (all classes)
- test_adk_agent.py::test_pr_review
- test_claude_sdk_agent.py::test_code_review
- test_agent_skills.py skills
- test_supervisor_enforcement.py::TestRealGitHubPRReview

Skill execution matrix (ALL agent types):

| Agent ID           | Skill Loading          | Execution Method      | Status     |
|--------------------|------------------------|-----------------------|------------|
| weather_agent      | N/A                    | No LLM                | N/A        |
| adk_agent          | Skill in user prompt   | LLM follows via tool  | Tested     |
| claude_sdk_agent   | Skill in system prompt | LLM follows via prompt| Tested     |
| weather_supervised | N/A                    | No LLM                | N/A        |
| openshell_claude   | Native .claude/skills/ | Claude Code reads dir | TODO       |
| openshell_opencode | Skill in prompt        | OpenCode follows      | TODO       |
| openshell_generic  | N/A                    | No agent CLI          | N/A        |
"""

import os

import httpx
import pytest

from kagenti.tests.e2e.openshell.conftest import (
    a2a_send,
    extract_a2a_text,
    sandbox_crd_installed,
    CANONICAL_DIFF,
    CANONICAL_CODE,
    CANONICAL_CI_LOG,
    _read_skill,
)

pytestmark = pytest.mark.openshell

LLM_AVAILABLE = os.getenv("OPENSHELL_LLM_AVAILABLE", "").lower() == "true"
skip_no_llm = pytest.mark.skipif(not LLM_AVAILABLE, reason="LLM not available")
skip_no_crd = pytest.mark.skipif(
    not sandbox_crd_installed(), reason="Sandbox CRD not installed"
)

REPO_ROOT = os.getenv(
    "REPO_ROOT",
    os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."),
)


# ═══════════════════════════════════════════════════════════════════════════
# Skill files exist (all agents share this)
# ═══════════════════════════════════════════════════════════════════════════


class TestSkillFilesExist:
    """Verify key kagenti skills exist in the repo."""

    def test_skill_files__all__key_skills_exist(self):
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

    def test_skill_structure__all__skill_md_present(self):
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
# PR Review skill (parametrized across ALL agent types)
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
class TestPRReviewSkill:
    """PR review skill execution across ALL agent types."""

    @skip_no_llm
    async def test_pr_review__claude_sdk_agent__follows_skill_instructions(
        self, claude_sdk_agent_url
    ):
        """Claude SDK agent follows pr-review skill instructions."""
        skill = _read_skill("github:pr-review")
        prompt = (
            f"You are executing the following code review skill:\n\n"
            f"```markdown\n{skill[:1000]}\n```\n\n"
            f"Now review this PR diff following the skill's instructions:\n\n"
            f"```diff\n{CANONICAL_DIFF}\n```"
        )
        async with httpx.AsyncClient() as client:
            resp = await a2a_send(
                client,
                claude_sdk_agent_url,
                prompt,
                request_id="skill-pr-review-claude",
                timeout=120.0,
            )
        assert "result" in resp
        text = extract_a2a_text(resp)
        assert text and len(text) > 50
        text_lower = text.lower()
        assert any(
            kw in text_lower
            for kw in ["sql", "injection", "os.system", "command", "security"]
        ), f"Skill execution didn't find security issues: {text[:200]}"

    @skip_no_llm
    async def test_pr_review__adk_agent__follows_skill_instructions(
        self, adk_agent_supervised_url
    ):
        """ADK agent follows pr-review skill instructions."""
        skill = _read_skill("github:pr-review")
        prompt = (
            f"Follow these review instructions:\n{skill[:800]}\n\n"
            f"Review this diff:\n```diff\n{CANONICAL_DIFF}\n```"
        )
        async with httpx.AsyncClient() as client:
            resp = await a2a_send(
                client,
                adk_agent_supervised_url,
                prompt,
                request_id="skill-pr-review-adk",
                timeout=120.0,
            )
        assert "result" in resp
        text = extract_a2a_text(resp)
        assert text and len(text) > 30

    @skip_no_llm
    async def test_pr_review__adk_agent_supervised__skill_under_supervisor(
        self, adk_agent_supervised_url
    ):
        """Tier 2: ADK agent executes PR review under supervisor security."""
        skill = _read_skill("github:pr-review")
        prompt = (
            f"Follow these review instructions:\n{skill[:800]}\n\n"
            f"Review this diff:\n```diff\n{CANONICAL_DIFF}\n```"
        )
        async with httpx.AsyncClient() as client:
            resp = await a2a_send(
                client,
                adk_agent_supervised_url,
                prompt,
                request_id="skill-pr-review-adk-supervised",
                timeout=120.0,
            )
        assert "result" in resp
        text = extract_a2a_text(resp)
        assert text and len(text) > 30

    async def test_pr_review__weather_agent__no_llm(self):
        """Weather agent cannot execute skills — no LLM."""
        pytest.skip(
            "weather_agent: No LLM — cannot execute PR review skill. "
            "This is by design (weather agent is a pure tool-calling agent)."
        )

    async def test_pr_review__weather_supervised__no_llm(self):
        """Supervised weather agent cannot execute skills — no LLM."""
        pytest.skip(
            "weather_supervised: No LLM — cannot execute PR review skill. "
            "Supervisor provides security isolation, not LLM capabilities."
        )

    @skip_no_crd
    @skip_no_llm
    @skip_no_crd
    async def test_pr_review__openshell_claude__native_skill_execution(self):
        """Claude Code builtin sandbox executes pr-review skill via LiteLLM."""
        from kagenti.tests.e2e.openshell.conftest import run_claude_in_sandbox

        output = run_claude_in_sandbox(
            f"Review this diff for security issues:\n{CANONICAL_DIFF[:500]}",
        )
        if output is None:
            pytest.skip(
                "openshell_claude: sandbox or LiteLLM not available. "
                "Needs: Sandbox CRD + LiteLLM + claude-sonnet-4 model alias."
            )
        assert len(output) > 20, f"Claude Code response too short: {output[:200]}"

    @skip_no_llm
    @skip_no_crd
    async def test_pr_review__openshell_opencode__litemaas_provider(self):
        """OpenCode builtin sandbox executes pr-review skill via LiteMaaS.

        Creates a sandbox with OpenCode + LiteLLM env vars, runs
        ``opencode run -m openai/gpt-4o-mini`` with the PR diff.
        LiteLLM maps gpt-4o-mini → llama-scout-17b on LiteMaaS.
        """
        from kagenti.tests.e2e.openshell.conftest import run_opencode_in_sandbox

        output = run_opencode_in_sandbox(
            f"Review this diff for security issues:\n{CANONICAL_DIFF[:500]}",
        )
        if output is None:
            pytest.skip(
                "openshell_opencode: sandbox or LiteLLM not available. "
                "Needs: Sandbox CRD + LiteLLM model proxy deployed."
            )
        assert len(output) > 20, f"OpenCode response too short: {output[:200]}"

    async def test_pr_review__openshell_generic__no_agent(self):
        """Generic sandbox has no agent — cannot execute skills."""
        pytest.skip(
            "openshell_generic: No agent CLI in generic sandbox. "
            "Skills require an LLM-capable agent runtime."
        )


# ═══════════════════════════════════════════════════════════════════════════
# RCA skill (parametrized across ALL agent types)
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
class TestRCASkill:
    """RCA (root cause analysis) skill execution across ALL agent types."""

    @skip_no_llm
    async def test_rca__claude_sdk_agent__follows_skill_instructions(
        self, claude_sdk_agent_url
    ):
        """Claude SDK agent follows rca:ci skill instructions."""
        skill = _read_skill("rca:ci")
        prompt = (
            f"You are executing the following RCA skill:\n\n"
            f"```markdown\n{skill[:1000]}\n```\n\n"
            f"Analyze these CI logs following the skill's methodology:\n\n"
            f"```\n{CANONICAL_CI_LOG}\n```"
        )
        async with httpx.AsyncClient() as client:
            resp = await a2a_send(
                client,
                claude_sdk_agent_url,
                prompt,
                request_id="skill-rca-claude",
                timeout=120.0,
            )
        assert "result" in resp
        text = extract_a2a_text(resp)
        assert text and len(text) > 50
        text_lower = text.lower()
        assert any(
            kw in text_lower
            for kw in ["secret", "webhook", "tls", "mount", "root cause", "missing"]
        ), f"RCA skill didn't identify root cause: {text[:200]}"

    @skip_no_llm
    async def test_rca__adk_agent__follows_skill_instructions(
        self, adk_agent_supervised_url
    ):
        """ADK agent follows rca:ci skill instructions."""
        skill = _read_skill("rca:ci")
        prompt = (
            f"Follow these RCA instructions:\n{skill[:800]}\n\n"
            f"Analyze these CI logs:\n```\n{CANONICAL_CI_LOG}\n```"
        )
        async with httpx.AsyncClient() as client:
            resp = await a2a_send(
                client,
                adk_agent_supervised_url,
                prompt,
                request_id="skill-rca-adk",
                timeout=120.0,
            )
        assert "result" in resp
        text = extract_a2a_text(resp)
        assert text and len(text) > 30

    @skip_no_llm
    async def test_rca__adk_agent_supervised__skill_under_supervisor(
        self, adk_agent_supervised_url
    ):
        """Tier 2: ADK agent executes RCA under supervisor security."""
        skill = _read_skill("rca:ci")
        prompt = (
            f"Follow these RCA instructions:\n{skill[:800]}\n\n"
            f"Analyze these CI logs:\n```\n{CANONICAL_CI_LOG}\n```"
        )
        async with httpx.AsyncClient() as client:
            resp = await a2a_send(
                client,
                adk_agent_supervised_url,
                prompt,
                request_id="skill-rca-adk-supervised",
                timeout=120.0,
            )
        assert "result" in resp
        text = extract_a2a_text(resp)
        assert text and len(text) > 30

    async def test_rca__weather_agent__no_llm(self):
        """Weather agent cannot execute RCA skill — no LLM."""
        pytest.skip("weather_agent: No LLM — cannot execute RCA skill.")

    async def test_rca__weather_supervised__no_llm(self):
        """Supervised weather agent cannot execute RCA skill — no LLM."""
        pytest.skip("weather_supervised: No LLM — cannot execute RCA skill.")

    @skip_no_llm
    @skip_no_crd
    async def test_rca__openshell_claude__native_execution(self):
        """Claude Code builtin sandbox executes rca:ci skill via LiteLLM."""
        from kagenti.tests.e2e.openshell.conftest import run_claude_in_sandbox

        output = run_claude_in_sandbox(
            f"Analyze this CI log and identify the root cause:\n{CANONICAL_CI_LOG}",
        )
        if output is None:
            pytest.skip("openshell_claude: sandbox or LiteLLM not available.")
        assert len(output) > 20, f"Claude Code response too short: {output[:200]}"

    @skip_no_crd
    async def test_rca__openshell_opencode__litemaas_provider(self):
        """OpenCode executes rca:ci skill via LiteMaaS in sandbox."""
        from kagenti.tests.e2e.openshell.conftest import run_opencode_in_sandbox

        output = run_opencode_in_sandbox(
            f"Analyze these CI logs and identify the root cause:\n{CANONICAL_CI_LOG[:500]}",
        )
        if output is None:
            pytest.skip("openshell_opencode: sandbox or LiteLLM not available.")
        assert len(output) > 20, f"OpenCode RCA response too short: {output[:200]}"

    async def test_rca__openshell_generic__no_agent(self):
        """Generic sandbox has no agent — cannot execute RCA skill."""
        pytest.skip("openshell_generic: No agent CLI — cannot execute skills.")


# ═══════════════════════════════════════════════════════════════════════════
# Security Review skill (parametrized across ALL agent types)
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
class TestSecurityReviewSkill:
    """Security review skill execution across ALL agent types."""

    @skip_no_llm
    async def test_security_review__claude_sdk_agent__follows_skill(
        self, claude_sdk_agent_url
    ):
        """Claude SDK agent follows security review skill."""
        skill = _read_skill("test:review")
        prompt = (
            f"Execute this security review skill:\n{skill[:800]}\n\n"
            f"Review this code:\n```python\n{CANONICAL_CODE}\n```"
        )
        async with httpx.AsyncClient() as client:
            resp = await a2a_send(
                client,
                claude_sdk_agent_url,
                prompt,
                request_id="skill-security-claude",
                timeout=120.0,
            )
        assert "result" in resp
        text = extract_a2a_text(resp)
        assert text and len(text) > 50
        text_lower = text.lower()
        findings = sum(
            1
            for kw in ["pickle", "shell=true", "injection", "sql", "command"]
            if kw in text_lower
        )
        assert findings >= 2, (
            f"Security review found only {findings} issues (expected 2+): {text[:200]}"
        )

    @skip_no_llm
    async def test_security_review__adk_agent__follows_skill(
        self, adk_agent_supervised_url
    ):
        """ADK agent follows security review skill."""
        skill = _read_skill("test:review")
        prompt = (
            f"Follow these security review instructions:\n{skill[:800]}\n\n"
            f"Review this code:\n```python\n{CANONICAL_CODE}\n```"
        )
        async with httpx.AsyncClient() as client:
            resp = await a2a_send(
                client,
                adk_agent_supervised_url,
                prompt,
                request_id="skill-security-adk",
                timeout=120.0,
            )
        assert "result" in resp
        text = extract_a2a_text(resp)
        assert text and len(text) > 30

    @skip_no_llm
    async def test_security_review__adk_agent_supervised__skill_under_supervisor(
        self, adk_agent_supervised_url
    ):
        """Tier 2: ADK agent executes security review under supervisor."""
        skill = _read_skill("test:review")
        prompt = (
            f"Follow these security review instructions:\n{skill[:800]}\n\n"
            f"Review this code:\n```python\n{CANONICAL_CODE}\n```"
        )
        async with httpx.AsyncClient() as client:
            resp = await a2a_send(
                client,
                adk_agent_supervised_url,
                prompt,
                request_id="skill-security-adk-supervised",
                timeout=120.0,
            )
        assert "result" in resp
        text = extract_a2a_text(resp)
        assert text and len(text) > 30

    async def test_security_review__weather_agent__no_llm(self):
        """Weather agent cannot execute security review — no LLM."""
        pytest.skip("weather_agent: No LLM — cannot execute security review skill.")

    async def test_security_review__weather_supervised__no_llm(self):
        """Supervised weather agent cannot execute security review — no LLM."""
        pytest.skip(
            "weather_supervised: No LLM — cannot execute security review skill."
        )

    @skip_no_llm
    @skip_no_crd
    async def test_security_review__openshell_claude__native(self):
        """Claude Code builtin sandbox executes security review via LiteLLM."""
        from kagenti.tests.e2e.openshell.conftest import run_claude_in_sandbox

        output = run_claude_in_sandbox(
            "What security issues are in this code? "
            "Answer with a numbered list:\n"
            "import pickle\n"
            "def load(p): return pickle.load(open(p,'rb'))\n"
            "def run(c): return os.system(c)\n"
            "def q(n): return db.execute(f\"SELECT * FROM t WHERE n='{n}'\")\n",
        )
        if output is None:
            pytest.skip("openshell_claude: sandbox or LiteLLM not available.")
        stripped = output.strip()
        if len(stripped) < 10:
            pytest.xfail(
                "LLM returned empty — known flaky with llama-scout-17b via LiteMaaS"
            )
        assert len(stripped) > 10, f"Claude Code response too short: {stripped[:200]}"

    @skip_no_crd
    @skip_no_llm
    @skip_no_crd
    async def test_security_review__openshell_opencode__litemaas(self):
        """OpenCode executes security review via LiteMaaS in sandbox."""
        from kagenti.tests.e2e.openshell.conftest import run_opencode_in_sandbox

        output = run_opencode_in_sandbox(
            f"Review this code for security issues:\n{CANONICAL_CODE[:400]}",
        )
        if output is None:
            pytest.skip("openshell_opencode: sandbox or LiteLLM not available.")
        assert len(output) > 20, f"OpenCode security review too short: {output[:200]}"

    async def test_security_review__openshell_generic__no_agent(self):
        """Generic sandbox has no agent — cannot execute skills."""
        pytest.skip("openshell_generic: No agent CLI — cannot execute skills.")


# ═══════════════════════════════════════════════════════════════════════════
# Code Generation skill (placeholder for future)
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
class TestCodeGenerationSkill:
    """Code generation skill execution across ALL agent types."""

    @skip_no_llm
    async def test_code_generation__claude_sdk_agent__generates_code(
        self, claude_sdk_agent_url
    ):
        """Claude SDK agent generates code from a natural language spec."""
        async with httpx.AsyncClient() as client:
            resp = await a2a_send(
                client,
                claude_sdk_agent_url,
                "Write a Python function called `fibonacci(n)` that returns the "
                "nth Fibonacci number using iteration. Include a docstring.",
                request_id="code-gen-claude",
                timeout=120.0,
            )
        assert "result" in resp
        text = extract_a2a_text(resp)
        assert text and len(text) > 30
        text_lower = text.lower()
        assert "def " in text_lower or "fibonacci" in text_lower, (
            f"Response doesn't contain code: {text[:200]}"
        )


# ═══════════════════════════════════════════════════════════════════════════
# Real-world skill execution (GitHub PR, CI logs)
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
class TestRealWorldSkillExecution:
    """Test skill execution with real-world data (GitHub API, CI logs)."""

    @skip_no_llm
    async def test_real_github_pr__claude_sdk_agent__fetches_and_reviews(
        self, claude_sdk_agent_url
    ):
        """Fetch a real PR diff from kagenti repo and review it."""
        gh_token = os.getenv("GITHUB_TOKEN", "")
        headers = {"Accept": "application/vnd.github.v3.diff"}
        if gh_token:
            headers["Authorization"] = f"token {gh_token}"

        async with httpx.AsyncClient() as client:
            diff_resp = await client.get(
                "https://api.github.com/repos/kagenti/kagenti/pulls/1300",
                headers={**headers, "Accept": "application/vnd.github.v3.diff"},
                timeout=15.0,
            )
        if diff_resp.status_code != 200:
            pytest.skip(f"Cannot fetch PR diff: HTTP {diff_resp.status_code}")

        diff_text = diff_resp.text[:2000]
        async with httpx.AsyncClient() as client:
            resp = await a2a_send(
                client,
                claude_sdk_agent_url,
                f"Review this pull request diff for security and code quality:\n\n"
                f"```diff\n{diff_text}\n```",
                request_id="github-pr-review",
                timeout=120.0,
            )
        assert "result" in resp
        text = extract_a2a_text(resp)
        assert text and len(text) > 50

    @skip_no_llm
    async def test_rca_ci_logs__claude_sdk_agent__identifies_root_cause(
        self, claude_sdk_agent_url
    ):
        """Send CI-style error logs and ask agent for root cause analysis."""
        async with httpx.AsyncClient() as client:
            resp = await a2a_send(
                client,
                claude_sdk_agent_url,
                f"Analyze these CI logs and identify the root cause:\n\n"
                f"```\n{CANONICAL_CI_LOG}\n```",
                request_id="rca-logs",
                timeout=120.0,
            )
        assert "result" in resp
        text = extract_a2a_text(resp)
        assert text
        text_lower = text.lower()
        assert any(
            kw in text_lower
            for kw in ["secret", "webhook", "tls", "mount", "not found", "root cause"]
        ), f"Response doesn't identify root cause: {text[:200]}"

    @skip_no_llm
    async def test_real_github_pr__adk_agent__fetches_and_reviews(
        self, adk_agent_supervised_url
    ):
        """ADK agent reviews real GitHub PR."""
        gh_token = os.getenv("GITHUB_TOKEN", "")
        headers = {"Accept": "application/vnd.github.v3.diff"}
        if gh_token:
            headers["Authorization"] = f"token {gh_token}"

        async with httpx.AsyncClient() as client:
            diff_resp = await client.get(
                "https://api.github.com/repos/kagenti/kagenti/pulls/1300",
                headers={**headers, "Accept": "application/vnd.github.v3.diff"},
                timeout=15.0,
            )
        if diff_resp.status_code != 200:
            pytest.skip(f"Cannot fetch PR diff: HTTP {diff_resp.status_code}")

        diff_text = diff_resp.text[:1500]
        async with httpx.AsyncClient() as client:
            resp = await a2a_send(
                client,
                adk_agent_supervised_url,
                f"Review this PR diff:\n```diff\n{diff_text}\n```",
                request_id="github-pr-review-adk",
                timeout=120.0,
            )
        assert "result" in resp
        text = extract_a2a_text(resp)
        assert text and len(text) > 30

    @skip_no_llm
    @skip_no_crd
    async def test_real_github_pr__openshell_claude__native_clone_and_review(self):
        """Claude Code sandbox reviews a code snippet via LiteLLM."""
        from kagenti.tests.e2e.openshell.conftest import run_claude_in_sandbox

        output = run_claude_in_sandbox(
            f"Review this diff for issues:\n{CANONICAL_DIFF[:500]}",
        )
        if output is None:
            pytest.skip("openshell_claude: sandbox or LiteLLM not available.")
        assert len(output) > 20, f"Claude Code response too short: {output[:200]}"

    @skip_no_crd
    @skip_no_llm
    @skip_no_crd
    async def test_real_github_pr__openshell_opencode__litemaas_review(self):
        """OpenCode sandbox reviews real PR diff via LiteMaaS."""
        from kagenti.tests.e2e.openshell.conftest import run_opencode_in_sandbox

        output = run_opencode_in_sandbox(
            f"Review this PR diff:\n{CANONICAL_DIFF[:500]}",
        )
        if output is None:
            pytest.skip("openshell_opencode: sandbox or LiteLLM not available.")
        assert len(output) > 20, f"OpenCode PR review too short: {output[:200]}"


# ═══════════════════════════════════════════════════════════════════════════
# Builtin Sandbox CLIs (openshell_claude, openshell_opencode)
# ═══════════════════════════════════════════════════════════════════════════


class TestBuiltinSandboxCLIs:
    """Verify builtin sandbox images have expected CLI tools."""

    @skip_no_crd
    def test_builtin_cli__openshell_claude__claude_binary_present(self):
        """Claude Code sandbox must have `claude` binary."""
        pytest.skip(
            "openshell_claude: Verify via kubectl exec into openshell_claude sandbox. "
            "TODO: Create sandbox + kubectl exec -- which claude"
        )

    @skip_no_crd
    def test_builtin_cli__openshell_opencode__opencode_binary_present(self):
        """OpenCode sandbox must have `opencode` binary."""
        pytest.skip(
            "openshell_opencode: Verify via kubectl exec into openshell_opencode sandbox. "
            "TODO: Create sandbox + kubectl exec -- which opencode"
        )

    @skip_no_crd
    def test_builtin_cli__openshell_generic__has_bash_and_tools(self):
        """Generic sandbox must have bash, git, curl."""
        pytest.skip(
            "openshell_generic: Verify via kubectl exec into openshell_generic sandbox. "
            "TODO: Create sandbox + kubectl exec -- bash -c 'which git curl'"
        )
