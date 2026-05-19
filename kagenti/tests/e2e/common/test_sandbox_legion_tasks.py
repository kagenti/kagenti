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

import os
import pathlib
import textwrap

import pytest
import httpx
import yaml
from uuid import uuid4
from a2a.types import (
    Message as A2AMessage,
    TextPart,
)

from kagenti.tests.e2e.conftest import _fetch_openshift_ingress_ca

# Skip entire module if sandbox agents are not deployed
pytestmark = pytest.mark.skipif(
    not os.getenv("SANDBOX_LEGION_URL") and not os.getenv("ENABLE_SANDBOX_TESTS"),
    reason="Sandbox agents not deployed (set SANDBOX_LEGION_URL or ENABLE_SANDBOX_TESTS)",
)


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
        raise RuntimeError("Could not fetch OpenShift ingress CA certificate.")
    return ssl.create_default_context(cafile=ca_path)


async def _extract_response(client, message):
    """Send an A2A message (non-streaming) and extract the text response."""
    from a2a.types import SendMessageRequest, MessageSendParams

    params = MessageSendParams(message=message)
    request = SendMessageRequest(id=uuid4().hex, params=params)
    response = await client.send_message(request)

    root = getattr(response, "root", response)
    if hasattr(root, "error") and root.error:
        raise RuntimeError(f"A2A error: {root.error}")

    result = getattr(root, "result", None)
    if result is None:
        return ""

    full_response = ""
    if hasattr(result, "artifacts") and result.artifacts:
        for artifact in result.artifacts:
            for part in artifact.parts or []:
                p = getattr(part, "root", part)
                if hasattr(p, "text"):
                    full_response += p.text
    elif hasattr(result, "parts"):
        for part in result.parts or []:
            p = getattr(part, "root", part)
            if hasattr(p, "text"):
                full_response += p.text

    return full_response


async def _connect_to_agent(agent_url):
    ssl_verify = _get_ssl_context()
    httpx_client = httpx.AsyncClient(timeout=180.0, verify=ssl_verify)

    from a2a.client import A2AClient
    from a2a.client.card_resolver import A2ACardResolver

    resolver = A2ACardResolver(httpx_client, agent_url)
    card = await resolver.get_agent_card()
    card.url = agent_url
    client = A2AClient(httpx_client=httpx_client, url=agent_url)
    return client, card


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


class TestSandboxLegionGitHubAnalysis:
    """Test the agent performing real GitHub repository analysis."""

    @pytest.mark.asyncio
    async def test_analyze_closed_issue(self):
        """
        Ask the agent to analyze a real closed issue from kagenti/kagenti.

        The agent should use web_fetch to read the issue and provide a
        summary that includes relevant keywords.
        """
        agent_url = _get_sandbox_legion_url()
        try:
            client, _ = await _connect_to_agent(agent_url)
        except Exception as e:
            pytest.fail(f"Sandbox agent not reachable at {agent_url}: {e}")

        # Issue #751 is about Agent Catalog bugs — a real closed issue
        message = A2AMessage(
            role="user",
            parts=[
                TextPart(
                    text=(
                        "Fetch and analyze GitHub issue #751 from the "
                        "kagenti/kagenti repository. Use the URL: "
                        "https://api.github.com/repos/kagenti/kagenti/issues/751 "
                        "Tell me: (1) what the issue title is, "
                        "(2) whether it's open or closed, "
                        "(3) a one-sentence summary of the problem."
                    )
                )
            ],
            messageId=uuid4().hex,
        )

        response = await _extract_response(client, message)
        assert response, "Agent returned no response"

        response_lower = response.lower()
        print(f"\n  Response: {response[:500]}")

        # The issue is about Agent Catalog — check for relevant terms
        assert any(
            term in response_lower for term in ["catalog", "agent", "import", "751"]
        ), (
            f"Response doesn't mention expected keywords about issue #751.\n"
            f"Response: {response[:300]}"
        )

    @pytest.mark.asyncio
    async def test_analyze_closed_pr(self):
        """
        Ask the agent to analyze a recent closed PR from kagenti/kagenti.

        The agent should fetch the PR data and summarize what changed.
        """
        agent_url = _get_sandbox_legion_url()
        try:
            client, _ = await _connect_to_agent(agent_url)
        except Exception as e:
            pytest.fail(f"Sandbox agent not reachable at {agent_url}: {e}")

        # PR #753 is a small chore PR — bump kagenti-webhook
        message = A2AMessage(
            role="user",
            parts=[
                TextPart(
                    text=(
                        "Fetch GitHub pull request #753 from kagenti/kagenti. "
                        "Use the URL: "
                        "https://api.github.com/repos/kagenti/kagenti/pulls/753 "
                        "Tell me: (1) the PR title, (2) who authored it, "
                        "(3) whether it was merged."
                    )
                )
            ],
            messageId=uuid4().hex,
        )

        response = await _extract_response(client, message)
        assert response, "Agent returned no response"

        response_lower = response.lower()
        print(f"\n  Response: {response[:500]}")

        # PR #753 is about bumping kagenti-webhook
        assert any(
            term in response_lower for term in ["webhook", "bump", "753", "chore"]
        ), (
            f"Response doesn't mention expected keywords about PR #753.\n"
            f"Response: {response[:300]}"
        )


class TestSandboxLegionRCA:
    """Test the agent performing root cause analysis on CI failures."""

    @pytest.mark.asyncio
    async def test_rca_on_mock_ci_log(self):
        """
        Write a mock CI failure log to the workspace, then ask the
        agent to perform root cause analysis.

        The agent should:
        1. Read the log file
        2. Identify the error (CrashLoopBackOff, missing LLM_API_KEY)
        3. Suggest a fix (create the llm-credentials Secret)
        """
        agent_url = _get_sandbox_legion_url()
        try:
            client, _ = await _connect_to_agent(agent_url)
        except Exception as e:
            pytest.fail(f"Sandbox agent not reachable at {agent_url}: {e}")

        context_id = f"rca-{uuid4().hex[:8]}"

        # Turn 1: Write the mock CI log
        msg1 = A2AMessage(
            role="user",
            parts=[
                TextPart(
                    text=(
                        f"Write the following CI failure log to "
                        f"data/ci-failure.log:\n\n{MOCK_CI_FAILURE_LOG}"
                    )
                )
            ],
            messageId=uuid4().hex,
            contextId=context_id,
        )

        response1 = await _extract_response(client, msg1)
        assert response1, "Turn 1: No response"
        print(f"\n  Turn 1 (write log): {response1[:200]}")

        # Turn 2: Ask for RCA
        msg2 = A2AMessage(
            role="user",
            parts=[
                TextPart(
                    text=(
                        "Read the file data/ci-failure.log and perform a "
                        "root cause analysis. Your response MUST include: "
                        "(1) the exact error that caused the failure, "
                        "(2) the root cause, "
                        "(3) a specific fix recommendation. "
                        "Be precise — quote the actual error message."
                    )
                )
            ],
            messageId=uuid4().hex,
            contextId=context_id,
        )

        response2 = await _extract_response(client, msg2)
        assert response2, "Turn 2: No response"

        response2_lower = response2.lower()
        print(f"\n  Turn 2 (RCA): {response2[:800]}")

        # The agent should identify the key failure indicators
        assert any(
            term in response2_lower
            for term in ["crashloopbackoff", "crash", "api_key", "api key"]
        ), (
            f"RCA response doesn't identify the crash/API key issue.\n"
            f"Response: {response2[:500]}"
        )

        assert any(
            term in response2_lower
            for term in ["llm-credentials", "secret", "missing", "not set"]
        ), (
            f"RCA response doesn't mention the missing secret.\n"
            f"Response: {response2[:500]}"
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
        """
        agent_url = _get_sandbox_legion_url()
        try:
            client, _ = await _connect_to_agent(agent_url)
        except Exception as e:
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

        response = await _extract_response(client, message)
        assert response, "Agent returned no response"

        response_lower = response.lower()
        print(f"\n  Response: {response[:500]}")

        # Workspace should have standard subdirectories
        assert any(
            term in response_lower for term in ["data", "scripts", "repos", "output"]
        ), (
            f"Response doesn't mention expected workspace directories.\n"
            f"Response: {response[:300]}"
        )


if __name__ == "__main__":
    import sys

    sys.exit(pytest.main([__file__, "-v"]))
