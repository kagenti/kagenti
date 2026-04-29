"""
LiteLLM + Claude Code Sandbox Infrastructure Tests

Validates the three fixes from PR #1395:
1. No plaintext API keys in LiteLLM ConfigMap (security)
2. Istio waypoint Gateway exists for namespaces with use-waypoint label
3. Claude Code works in sandbox via LiteLLM → LiteMaaS

These tests verify infrastructure correctness, not agent behavior.
"""

import json
import os
import subprocess

import pytest

from kagenti.tests.e2e.openshell.conftest import (
    kubectl_run,
    sandbox_crd_installed,
    run_claude_in_sandbox,
    CANONICAL_DIFF,
)

pytestmark = pytest.mark.openshell

AGENT_NS = os.getenv("OPENSHELL_AGENT_NAMESPACE", "team1")
LLM_AVAILABLE = os.getenv("OPENSHELL_LLM_AVAILABLE", "").lower() == "true"
skip_no_llm = pytest.mark.skipif(not LLM_AVAILABLE, reason="LLM not available")
skip_no_crd = pytest.mark.skipif(
    not sandbox_crd_installed(), reason="Sandbox CRD not installed"
)


class TestLiteLLMSecureConfig:
    """Verify LiteLLM proxy config uses secret references, not plaintext keys."""

    def test_configmap_no_plaintext_api_keys(self):
        """LiteLLM ConfigMap must not contain plaintext API keys."""
        result = kubectl_run(
            "get", "configmap", "litellm-config", "-n", AGENT_NS, "-o", "json"
        )
        if result.returncode != 0:
            pytest.skip("LiteLLM ConfigMap not found")

        cm = json.loads(result.stdout)
        config_yaml = cm.get("data", {}).get("config.yaml", "")

        for line in config_yaml.splitlines():
            stripped = line.strip()
            if stripped.startswith("api_key:"):
                value = stripped.split(":", 1)[1].strip().strip('"').strip("'")
                assert value.startswith("os.environ/"), (
                    f"LiteLLM config has plaintext api_key: '{value}'. "
                    f"Must use os.environ/VAR_NAME referencing a K8s Secret."
                )

    def test_litemaas_secret_exists(self):
        """K8s Secret for LiteMaaS credentials must exist."""
        result = kubectl_run("get", "secret", "litemaas-credentials", "-n", AGENT_NS)
        if result.returncode != 0:
            pytest.skip("litemaas-credentials secret not found (no LLM backend)")

        result = kubectl_run(
            "get",
            "secret",
            "litemaas-credentials",
            "-n",
            AGENT_NS,
            "-o",
            "jsonpath={.data.api-key}",
        )
        assert result.returncode == 0
        assert len(result.stdout.strip()) > 0, "litemaas-credentials api-key is empty"

    def test_litellm_deployment_uses_secret_ref(self):
        """LiteLLM Deployment must mount API key via secretKeyRef, not literal."""
        result = kubectl_run(
            "get", "deploy", "litellm-model-proxy", "-n", AGENT_NS, "-o", "json"
        )
        if result.returncode != 0:
            pytest.skip("LiteLLM deployment not found")

        deploy = json.loads(result.stdout)
        containers = deploy["spec"]["template"]["spec"]["containers"]
        litellm_container = next(
            (c for c in containers if c["name"] == "litellm"), None
        )
        assert litellm_container, "No 'litellm' container in deployment"

        env_vars = litellm_container.get("env", [])
        key_env = next((e for e in env_vars if e["name"] == "LITEMAAS_API_KEY"), None)
        assert key_env is not None, (
            "LiteLLM deployment missing LITEMAAS_API_KEY env var"
        )
        assert "valueFrom" in key_env, (
            "LITEMAAS_API_KEY has literal value instead of secretKeyRef"
        )
        assert "secretKeyRef" in key_env["valueFrom"], (
            "LITEMAAS_API_KEY uses valueFrom but not secretKeyRef"
        )

    def test_litellm_uses_hosted_vllm_provider(self):
        """LiteLLM config must use hosted_vllm/ provider, not openai/."""
        result = kubectl_run(
            "get", "configmap", "litellm-config", "-n", AGENT_NS, "-o", "json"
        )
        if result.returncode != 0:
            pytest.skip("LiteLLM ConfigMap not found")

        cm = json.loads(result.stdout)
        config_yaml = cm.get("data", {}).get("config.yaml", "")

        for line in config_yaml.splitlines():
            stripped = line.strip()
            if stripped.startswith("model:") and "openai/" in stripped:
                pytest.fail(
                    f"LiteLLM config uses openai/ provider: '{stripped}'. "
                    f"Must use hosted_vllm/ to avoid Responses API bridge."
                )

    def test_litellm_anthropic_settings(self):
        """LiteLLM config must have settings for Anthropic Messages translation."""
        result = kubectl_run(
            "get", "configmap", "litellm-config", "-n", AGENT_NS, "-o", "json"
        )
        if result.returncode != 0:
            pytest.skip("LiteLLM ConfigMap not found")

        cm = json.loads(result.stdout)
        config_yaml = cm.get("data", {}).get("config.yaml", "")

        assert "use_chat_completions_url_for_anthropic_messages" in config_yaml, (
            "LiteLLM config missing use_chat_completions_url_for_anthropic_messages. "
            "Required for Claude Code → LiteLLM → LiteMaaS flow."
        )
        assert "drop_params" in config_yaml, (
            "LiteLLM config missing drop_params. "
            "Required to drop Claude Code's unsupported params (reasoning_effort)."
        )


class TestIstioWaypoint:
    """Verify Istio waypoint Gateways exist for namespaces with use-waypoint label."""

    @pytest.mark.parametrize("namespace", ["team1", "team2"])
    def test_waypoint_exists_if_labeled(self, namespace):
        """Namespace with istio.io/use-waypoint must have a waypoint Gateway."""
        ns_result = kubectl_run(
            "get",
            "ns",
            namespace,
            "-o",
            "jsonpath={.metadata.labels.istio\\.io/use-waypoint}",
        )
        if ns_result.returncode != 0:
            pytest.skip(f"Namespace {namespace} not found")

        waypoint_label = ns_result.stdout.strip()
        if not waypoint_label:
            pytest.skip(f"{namespace} has no istio.io/use-waypoint label")

        gw_result = kubectl_run(
            "get",
            "gateway",
            waypoint_label,
            "-n",
            namespace,
        )
        assert gw_result.returncode == 0, (
            f"Namespace {namespace} has istio.io/use-waypoint={waypoint_label} "
            f"but no waypoint Gateway deployed. "
            f"Without it, ztunnel resets ALL L7 connections."
        )

    def test_waypoint_pod_running(self):
        """Waypoint proxy pod must be running in team1."""
        result = kubectl_run(
            "get",
            "pods",
            "-n",
            AGENT_NS,
            "-l",
            "gateway.networking.k8s.io/gateway-name=waypoint",
            "-o",
            "jsonpath={.items[0].status.phase}",
        )
        if result.returncode != 0 or not result.stdout.strip():
            pytest.skip("No waypoint pod found")

        assert result.stdout.strip() == "Running", (
            f"Waypoint pod phase is {result.stdout.strip()}, expected Running"
        )


class TestLiteLLMAnthropicPassthrough:
    """Verify LiteLLM correctly translates Anthropic Messages API to chat completions."""

    @skip_no_llm
    def test_anthropic_messages_api_returns_response(self):
        """LiteLLM /v1/messages endpoint returns valid Anthropic-format response."""
        litellm_svc = kubectl_run(
            "get", "svc", "litellm-model-proxy", "-n", AGENT_NS, timeout=10
        )
        if litellm_svc.returncode != 0:
            pytest.skip("LiteLLM service not found")

        result = subprocess.run(
            [
                "kubectl",
                "exec",
                "deploy/litellm-model-proxy",
                "-n",
                AGENT_NS,
                "--",
                "python3",
                "-c",
                """
import urllib.request, json
req = urllib.request.Request(
    "http://localhost:4000/v1/messages",
    data=json.dumps({
        "model": "claude-sonnet-4-20250514",
        "max_tokens": 50,
        "messages": [{"role": "user", "content": "What is 2+2? Reply with just the number."}]
    }).encode(),
    headers={
        "Content-Type": "application/json",
        "x-api-key": "test",
        "anthropic-version": "2023-06-01",
    },
)
resp = urllib.request.urlopen(req, timeout=30)
data = json.loads(resp.read())
print(json.dumps(data))
""",
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert result.returncode == 0, f"Anthropic Messages API failed: {result.stderr}"

        data = json.loads(result.stdout.strip())
        assert data.get("type") == "message", (
            f"Expected type=message, got {data.get('type')}"
        )
        assert len(data.get("content", [])) > 0, "Response has no content"
        text = data["content"][0].get("text", "")
        assert "4" in text, f"Expected '4' in response, got: {text}"

    @skip_no_llm
    def test_claude_model_alias_in_model_list(self):
        """LiteLLM /v1/models must list claude-sonnet-4-20250514."""
        result = subprocess.run(
            [
                "kubectl",
                "exec",
                "deploy/litellm-model-proxy",
                "-n",
                AGENT_NS,
                "--",
                "python3",
                "-c",
                """
import urllib.request, json
req = urllib.request.Request("http://localhost:4000/v1/models")
resp = urllib.request.urlopen(req, timeout=10)
data = json.loads(resp.read())
models = [m["id"] for m in data.get("data", [])]
print(json.dumps(models))
""",
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0, f"Model list failed: {result.stderr}"
        models = json.loads(result.stdout.strip())
        assert "claude-sonnet-4-20250514" in models, (
            f"claude-sonnet-4-20250514 not in model list: {models}"
        )


class TestClaudeCodeSandbox:
    """Verify Claude Code works inside sandbox pods via LiteLLM proxy."""

    @skip_no_llm
    @skip_no_crd
    def test_claude_code_simple_prompt(self):
        """Claude Code in sandbox responds to a simple math prompt."""
        output = run_claude_in_sandbox("What is 2+2? Reply with just the number.")
        if output is None:
            pytest.skip(
                "Claude Code sandbox not available. "
                "Needs: Sandbox CRD + LiteLLM + claude-sonnet-4 alias."
            )
        assert "4" in output, f"Expected '4' in Claude Code output: {output[:200]}"

    @skip_no_llm
    @skip_no_crd
    def test_claude_code_code_review(self):
        """Claude Code in sandbox can review code for security issues."""
        output = run_claude_in_sandbox(
            f"Review this diff for security issues. Be brief:\n{CANONICAL_DIFF[:500]}"
        )
        if output is None:
            pytest.skip("Claude Code sandbox not available.")
        assert len(output) > 20, f"Claude Code response too short: {output[:200]}"
        output_lower = output.lower()
        assert any(
            term in output_lower
            for term in ["sql", "injection", "security", "vulnerable", "command"]
        ), f"Response doesn't mention security issues: {output[:300]}"
