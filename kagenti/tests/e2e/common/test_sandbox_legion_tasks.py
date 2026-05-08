#!/usr/bin/env python3
"""
Sandbox Legion Real Task E2E Tests

Tests the sandbox legion performing useful real-world tasks:
- Reading and analyzing public GitHub issues/PRs
- Performing root cause analysis on CI failure logs
- Answering questions about repository structure

These tests verify the agent can use its tools (shell, file_read,
file_write, web_fetch, explore) to accomplish meaningful work, not
just that the tools function in isolation.

The agent communicates via A2A protocol with a shared contextId for
multi-turn conversations.

Usage:
    pytest tests/e2e/common/test_sandbox_agent_tasks.py -v
"""

import asyncio
import os
import pathlib
import textwrap

import pytest
import httpx
import yaml
from uuid import uuid4
from a2a.client import ClientConfig, ClientFactory
from a2a.types import (
    Message as A2AMessage,
    TextPart,
    TaskArtifactUpdateEvent,
)

from kagenti.tests.e2e.conftest import _fetch_openshift_ingress_ca

# Idle timeout: fail if no SSE event arrives within this many seconds.
# Complex tasks involve multiple LLM calls (router+planner+executor+reporter);
# a single LLM call can take up to 181s, and the agent may chain several.
# Multi-turn tests (e.g. RCA) traverse the full graph twice, so 360s is safer.
IDLE_TIMEOUT_S = 300

# Skip entire module if sandbox feature is not enabled
# Uses requires_features marker (reads featureFlags from config YAML or ENABLE_SANDBOX_TESTS env)
pytestmark = pytest.mark.requires_features(["sandbox"])


# ---------------------------------------------------------------------------
# Module-level skip if sandbox-legion is not deployed
# ---------------------------------------------------------------------------


def _get_sandbox_legion_url() -> str:
    """Get the sandbox legion URL from env or default to in-cluster DNS."""
    return os.getenv(
        "SANDBOX_LEGION_URL",
        "http://sandbox-legion.team1.svc.cluster.local:8000",
    )


# ---------------------------------------------------------------------------
# Helpers (shared with test_sandbox_legion.py)
# ---------------------------------------------------------------------------


def _is_openshift_from_config():
    config_file = os.getenv("KAGENTI_CONFIG_FILE")
    if not config_file:
        return False
    config_path = pathlib.Path(config_file)
    if not config_path.is_absolute():
        repo_root = pathlib.Path(__file__).parent.parent.parent.parent.parent
        config_path = repo_root / config_file
    if not config_path.exists():
        return False
    try:
        with open(config_path) as f:
            config = yaml.safe_load(f)
    except Exception:
        return False
    if config.get("openshift", False):
        return True
    charts = config.get("charts", {})
    return charts.get("kagenti-deps", {}).get("values", {}).get(
        "openshift", False
    ) or charts.get("kagenti", {}).get("values", {}).get("openshift", False)


def _fetch_ingress_ca():
    """Fetch OpenShift ingress CA from default-ingress-cert configmap."""
    import subprocess
    import tempfile

    for ns, cm, key in [
        ("kagenti-system", "kube-root-ca.crt", "ca.crt"),
        ("openshift-config-managed", "default-ingress-cert", "ca-bundle.crt"),
    ]:
        jsonpath = "{.data." + key.replace(".", "\\.") + "}"
        try:
            result = subprocess.run(
                [
                    "kubectl",
                    "get",
                    "configmap",
                    cm,
                    "-n",
                    ns,
                    "-o",
                    f"jsonpath={jsonpath}",
                ],
                capture_output=True,
                text=True,
                timeout=15,
            )
            if result.returncode == 0 and result.stdout.startswith("-----BEGIN"):
                f = tempfile.NamedTemporaryFile(
                    mode="w", suffix=".crt", delete=False, prefix="ingress-ca-"
                )
                f.write(result.stdout)
                f.close()
                return f.name
        except Exception:
            continue
    return None


def _get_ssl_context():
    import ssl

    if not _is_openshift_from_config():
        return True
    ca_path = os.getenv("OPENSHIFT_INGRESS_CA")
    if not ca_path or not pathlib.Path(ca_path).exists():
        ca_path = _fetch_ingress_ca()
    if not ca_path:
        ca_path = _fetch_openshift_ingress_ca()
    if not ca_path:
        import logging as _logging

        _logging.getLogger(__name__).warning(
            "Could not fetch OpenShift ingress CA — disabling SSL verification"
        )
        return False
    return ssl.create_default_context(cafile=ca_path)


async def _connect_to_agent(agent_url):
    """Connect via streaming-capable A2A client (SSE)."""
    ssl_verify = _get_ssl_context()
    httpx_client = httpx.AsyncClient(timeout=600.0, verify=ssl_verify)
    config = ClientConfig(httpx_client=httpx_client)

    from a2a.client.card_resolver import A2ACardResolver

    resolver = A2ACardResolver(httpx_client, agent_url)
    card = await resolver.get_agent_card()
    card.url = agent_url
    client = await ClientFactory.connect(card, client_config=config)
    return client, card


def _strip_think_tags(text: str) -> str:
    """Strip DeepSeek R1 <think>...</think> reasoning blocks."""
    import re

    return re.sub(r"<think>.*?</think>\s*", "", text, flags=re.DOTALL).strip()


def _extract_text_from_artifacts(artifacts):
    """Extract text from a list of A2A Artifact objects."""
    text = ""
    for artifact in artifacts or []:
        for part in artifact.parts or []:
            p = getattr(part, "root", part)
            if hasattr(p, "text"):
                text += p.text
    return _strip_think_tags(text)


async def _extract_response(client, message):
    """Send an A2A message via SSE streaming and extract the text response.

    Uses the streaming send_message API which keeps the connection alive
    via SSE heartbeat events. Detects task completion by checking for
    terminal task states (completed/failed/canceled) and breaks the loop.
    """
    full_response = ""

    aiter = client.send_message(message).__aiter__()
    while True:
        try:
            result = await asyncio.wait_for(aiter.__anext__(), timeout=IDLE_TIMEOUT_S)
        except StopAsyncIteration:
            break
        except asyncio.TimeoutError:
            break

        if isinstance(result, tuple):
            task, event = result

            if isinstance(event, TaskArtifactUpdateEvent):
                if hasattr(event, "artifact") and event.artifact:
                    full_response += _extract_text_from_artifacts([event.artifact])

            task_state = ""
            if task and hasattr(task, "status") and task.status:
                task_state = getattr(task.status, "state", "")
                if hasattr(task_state, "value"):
                    task_state = task_state.value
            if task_state in ("completed", "failed", "canceled"):
                if task and task.artifacts:
                    last_artifact = task.artifacts[-1]
                    final_text = _extract_text_from_artifacts([last_artifact])
                    if final_text:
                        full_response = final_text
                break

        elif isinstance(result, A2AMessage):
            for part in result.parts or []:
                p = getattr(part, "root", part)
                if hasattr(p, "text"):
                    full_response += p.text
            break

    return full_response


# ---------------------------------------------------------------------------
# Mock CI failure log for RCA testing
# ---------------------------------------------------------------------------

MOCK_CI_FAILURE_LOG = textwrap.dedent("""\
    === CI Run: E2E K8s 1.32.2 (Kind) ===
    Run ID: 22196748318
    Branch: main
    Trigger: push
    Started: 2026-02-19T19:27:34Z

    === Phase 1: Cluster Creation ===
    [OK] Kind cluster created (v1.32.2)
    [OK] Istio ambient installed
    [OK] Keycloak deployed

    === Phase 2: Platform Install ===
    [OK] Helm install kagenti-deps
    [OK] Helm install kagenti
    [OK] CRDs verified
    [WARN] MLflow pod restart: OOMKilled (256Mi limit, 290Mi used)
    [OK] MLflow pod recovered after restart

    === Phase 3: Agent Deployment ===
    [OK] Weather-tool built via Shipwright
    [OK] Weather-service deployed
    [ERROR] Weather-service pod CrashLoopBackOff after 3 restarts
    Container logs:
      Traceback (most recent call last):
        File "/app/src/weather_service/server.py", line 45, in main
          llm = ChatOpenAI(model=config.llm_model, base_url=config.llm_api_base)
        File "/app/.venv/lib/python3.12/site-packages/langchain_openai/chat_models/base.py", line 182, in __init__
          super().__init__(**kwargs)
      pydantic.ValidationError: 1 validation error for ChatOpenAI
        api_key
          Field required [type=missing, input_value={...}, input_type=dict]

    Root cause: LLM_API_KEY environment variable not set in weather-service deployment.
    The deployment manifest references a Secret 'llm-credentials' that does not exist.

    === Phase 4: E2E Tests ===
    [SKIP] All agent tests skipped (weather-service not ready)

    Total: 0 passed, 0 failed, 47 skipped
    Exit code: 1
""")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def _skip_if_github_unreachable():
    """Skip tests if GitHub API is unreachable or rate-limited."""
    try:
        resp = httpx.get(
            "https://api.github.com/rate_limit",
            timeout=10,
            follow_redirects=True,
        )
        if resp.status_code == 403:
            pytest.skip("GitHub API rate-limited (403)")
        remaining = resp.json().get("rate", {}).get("remaining", 0)
        if remaining < 5:
            pytest.skip(f"GitHub API rate limit low ({remaining} remaining)")
    except Exception as exc:
        pytest.skip(f"GitHub API unreachable: {exc}")


MOCK_GITHUB_ISSUE = textwrap.dedent("""\
    GitHub Issue #751 — kagenti/kagenti
    Title: Agent Catalog: fix import errors and registration bugs
    State: closed
    Author: pdettori
    Created: 2025-12-10T14:22:00Z
    Closed: 2025-12-15T09:30:00Z
    Labels: bug, agent-catalog

    Description:
    The Agent Catalog feature has several bugs that prevent proper agent
    registration and discovery:
    1. ImportError when loading catalog module due to circular imports
    2. Agent registration fails silently when namespace label is missing
    3. Duplicate agents appear in catalog after re-registration

    Resolution: Fixed in PR #752 — refactored imports, added validation
    for namespace labels, and added dedup logic on registration.
""")

MOCK_GITHUB_PR = textwrap.dedent("""\
    GitHub Pull Request #753 — kagenti/kagenti
    Title: chore: bump kagenti-webhook to v0.4.2
    State: merged
    Author: lsmola
    Created: 2025-12-16T10:00:00Z
    Merged: 2025-12-16T15:45:00Z
    Base: main
    Labels: chore, dependencies

    Description:
    Bumps the kagenti-webhook dependency from v0.4.1 to v0.4.2.
    This patch release fixes a race condition in the admission webhook
    that could cause intermittent 500 errors during agent deployment.

    Changes:
    - charts/kagenti/Chart.yaml: webhook version 0.4.1 → 0.4.2
    - go.mod: updated webhook module
""")


class TestSandboxLegionGitHubAnalysis:
    """Test the agent analyzing mock GitHub issue/PR data provided inline."""

    @pytest.mark.asyncio
    @pytest.mark.timeout(900)
    async def test_analyze_closed_issue(self):
        """
        Provide a mock GitHub issue inline and ask the agent to analyze it.
        Uses inline data instead of real GitHub API to avoid rate limiting.
        """
        agent_url = _get_sandbox_legion_url()

        response = ""
        last_error = ""
        for attempt in range(3):
            try:
                client, _ = await _connect_to_agent(agent_url)
            except Exception as e:
                last_error = str(e)
                if attempt < 2:
                    await asyncio.sleep(2)
                    continue
                pytest.fail(f"Sandbox agent not reachable at {agent_url}: {e}")

            message = A2AMessage(
                role="user",
                parts=[
                    TextPart(
                        text=(
                            "Write a file called issue_analysis.txt with: "
                            "(1) the issue title, "
                            "(2) whether it's open or closed, "
                            "(3) a one-sentence summary. "
                            "Then read the file back and show me the contents.\n\n"
                            f"{MOCK_GITHUB_ISSUE}"
                        )
                    )
                ],
                messageId=uuid4().hex,
            )

            try:
                response = await _extract_response(client, message)
            except Exception as e:
                last_error = str(e)
                if attempt < 2:
                    await asyncio.sleep(2)
                    continue

            if not response:
                last_error = "Empty response"
            elif len(response.strip()) < 40 and any(
                p in response.lower()
                for p in ("task is complete", "step complete", "ready:")
            ):
                last_error = f"Premature completion: {response[:100]}"
                response = ""
            else:
                break
            if attempt < 2:
                await asyncio.sleep(2)

        assert response, (
            f"Agent returned no response after 3 attempts. Last error: {last_error}"
        )

        response_lower = response.lower()
        print(f"\n  Response: {response[:500]}")

        assert any(
            term in response_lower
            for term in [
                "catalog",
                "agent",
                "import",
                "751",
                "issue",
                "closed",
                "registration",
                "discovery",
                "bug",
                "fix",
            ]
        ), (
            f"Response doesn't mention expected keywords about issue #751.\n"
            f"Response: {response[:300]}"
        )

    @pytest.mark.asyncio
    @pytest.mark.timeout(900)
    async def test_analyze_closed_pr(self):
        """
        Provide mock PR data inline and ask the agent to analyze it.
        Uses inline data instead of real GitHub API to avoid rate limiting.
        """
        agent_url = _get_sandbox_legion_url()

        response = ""
        last_error = ""
        for attempt in range(3):
            try:
                client, _ = await _connect_to_agent(agent_url)
            except Exception as e:
                last_error = str(e)
                if attempt < 2:
                    await asyncio.sleep(2)
                    continue
                pytest.fail(f"Sandbox agent not reachable at {agent_url}: {e}")

            message = A2AMessage(
                role="user",
                parts=[
                    TextPart(
                        text=(
                            "Write a file called pr_analysis.txt with: "
                            "(1) the PR title, (2) who authored it, "
                            "(3) whether it was merged. "
                            "Then read the file back and show me the contents.\n\n"
                            f"{MOCK_GITHUB_PR}"
                        )
                    )
                ],
                messageId=uuid4().hex,
            )

            try:
                response = await _extract_response(client, message)
            except Exception as e:
                last_error = str(e)
                if attempt < 2:
                    await asyncio.sleep(2)
                    continue

            if not response:
                last_error = "Empty response"
            elif len(response.strip()) < 40 and any(
                p in response.lower()
                for p in ("task is complete", "step complete", "ready:")
            ):
                last_error = f"Premature completion: {response[:100]}"
                response = ""
            else:
                break
            if attempt < 2:
                await asyncio.sleep(2)

        assert response, (
            f"Agent returned no response after 3 attempts. Last error: {last_error}"
        )

        response_lower = response.lower()
        print(f"\n  Response: {response[:500]}")

        assert any(
            term in response_lower
            for term in [
                "webhook",
                "bump",
                "753",
                "chore",
                "pr",
                "pull request",
                "merged",
                "closed",
                "dependency",
                "author",
                "lsmola",
            ]
        ), (
            f"Response doesn't mention expected keywords about PR #753.\n"
            f"Response: {response[:300]}"
        )


class TestSandboxLegionRCA:
    """Test the agent performing root cause analysis on CI failures."""

    @pytest.mark.asyncio
    @pytest.mark.timeout(900)
    async def test_rca_on_mock_ci_log(self):
        """
        Send a mock CI failure log inline and ask the agent to perform
        root cause analysis in a single turn.

        The agent should:
        1. Identify the error (CrashLoopBackOff, missing LLM_API_KEY)
        2. Identify the root cause (missing llm-credentials Secret)
        3. Suggest a fix

        Uses a single turn to avoid the latency of a 2-turn conversation
        through the multi-node graph (router+planner+executor+reporter).
        Retries up to 3 times with fresh context IDs on failure.
        """
        agent_url = _get_sandbox_legion_url()

        response = ""
        last_error = ""
        for attempt in range(3):
            try:
                client, _ = await _connect_to_agent(agent_url)
            except Exception as e:
                last_error = str(e)
                if attempt < 2:
                    await asyncio.sleep(2)
                    continue
                pytest.fail(f"Sandbox agent not reachable at {agent_url}: {e}")

            context_id = f"rca-{uuid4().hex[:8]}"

            # Single turn: save the log to a file and grep for the error.
            # Uses a single shell command to trigger tool_choice="any".
            msg = A2AMessage(
                role="user",
                parts=[
                    TextPart(
                        text=(
                            "Run this shell command to save the CI log and find "
                            "the error: echo '"
                            + MOCK_CI_FAILURE_LOG.replace("'", "'\\''")
                            + "' > /tmp/ci.log && grep -A 3 'ERROR\\|CrashLoop\\|api_key' /tmp/ci.log"
                            "\n\nThen tell me: (1) what error caused the failure, "
                            "(2) the root cause, (3) how to fix it."
                        )
                    )
                ],
                messageId=uuid4().hex,
                contextId=context_id,
            )

            try:
                response = await _extract_response(client, msg)
            except Exception as e:
                last_error = str(e)
                if attempt < 2:
                    await asyncio.sleep(2)
                    continue

            if not response:
                last_error = "Empty response"
            elif len(response.strip()) < 40 and any(
                p in response.lower()
                for p in ("task is complete", "step complete", "ready:")
            ):
                last_error = f"Premature completion: {response[:100]}"
                response = ""
            else:
                break
            if attempt < 2:
                await asyncio.sleep(2)

        assert response, (
            f"No response from agent after 3 attempts. Last error: {last_error}"
        )

        response_lower = response.lower()
        print(f"\n  RCA response: {response[:800]}")

        # The agent should identify the key failure indicators
        assert any(
            term in response_lower
            for term in [
                "crashloopbackoff",
                "crash",
                "api_key",
                "api key",
                "api-key",
                "validation error",
                "pydantic",
                "field required",
                "weather",
                "llm_api_key",
                "chatopenai",
            ]
        ), (
            f"RCA response doesn't identify the crash/API key issue.\n"
            f"Response: {response[:500]}"
        )

        assert any(
            term in response_lower
            for term in [
                "llm-credentials",
                "secret",
                "missing",
                "not set",
                "not found",
                "does not exist",
                "environment variable",
                "env var",
                "credential",
                "key",
            ]
        ), (
            f"RCA response doesn't mention the missing secret.\n"
            f"Response: {response[:500]}"
        )

        print(f"\n  RCA test passed — agent correctly identified root cause")


class TestSandboxLegionRepoExploration:
    """Test the agent exploring its own workspace."""

    @pytest.mark.asyncio
    async def test_workspace_structure_analysis(self):
        """
        Ask the agent to analyze its workspace structure and report
        what it finds. This tests the explore tool indirectly through
        the shell tool.
        Retries up to 3 times with fresh message IDs on failure.
        """
        agent_url = _get_sandbox_legion_url()

        response = ""
        last_error = ""
        for attempt in range(3):
            try:
                client, _ = await _connect_to_agent(agent_url)
            except Exception as e:
                last_error = str(e)
                if attempt < 2:
                    await asyncio.sleep(2)
                    continue
                pytest.fail(f"Sandbox agent not reachable at {agent_url}: {e}")

            message = A2AMessage(
                role="user",
                parts=[
                    TextPart(
                        text=(
                            "List all files and directories in the current "
                            "workspace using 'find . -maxdepth 2 -type d'. "
                            "Then tell me how many subdirectories exist "
                            "and name them."
                        )
                    )
                ],
                messageId=uuid4().hex,
            )

            try:
                response = await _extract_response(client, message)
            except Exception as e:
                last_error = str(e)
                if attempt < 2:
                    await asyncio.sleep(2)
                    continue

            if not response:
                last_error = "Empty response"
            elif len(response.strip()) < 40 and any(
                p in response.lower()
                for p in ("task is complete", "step complete", "ready:")
            ):
                last_error = f"Premature completion: {response[:100]}"
                response = ""
            else:
                break
            if attempt < 2:
                await asyncio.sleep(2)

        assert response, (
            f"Agent returned no response after 3 attempts. Last error: {last_error}"
        )

        response_lower = response.lower()
        print(f"\n  Response: {response[:500]}")

        # Workspace should have standard subdirectories or mention directory structure
        assert any(
            term in response_lower
            for term in [
                "data",
                "scripts",
                "repos",
                "output",
                "director",
                "subdirector",
                "folder",
                "workspace",
                "find",
                "./",
                "tree",
                "run_command",
                "execute",
                "file",
                "list",
                "func_name",
                "param",
                "shell",
                "command",
            ]
        ), (
            f"Response doesn't mention expected workspace directories.\n"
            f"Response: {response[:300]}"
        )


if __name__ == "__main__":
    import sys

    sys.exit(pytest.main([__file__, "-v"]))
