"""
T0.5 — LiteLLM proxy and Istio waypoint infrastructure tests.

Validates:
1. No plaintext API keys in LiteLLM ConfigMap (security)
2. Istio waypoint Gateway exists for namespaces with use-waypoint label
3. LiteLLM Anthropic Messages API passthrough

These tests verify infrastructure correctness, not agent behavior.
"""

import json
import os

import httpx
import pytest

from kagenti.tests.e2e.openshell.conftest import (
    LLM_AVAILABLE,
    skip_no_llm,
    kubectl_run,
    LLM_MODELS,
    LLM_PROVIDER,
)

pytestmark = pytest.mark.openshell

AGENT_NS = os.getenv("OPENSHELL_AGENT_NAMESPACE", "team1")
IS_OLLAMA = LLM_PROVIDER == "ollama"


class TestLiteLLMSecureConfig:
    """Verify LiteLLM proxy config uses secret references, not plaintext keys."""

    def test_configmap_no_plaintext_api_keys(self):
        """LiteLLM ConfigMap must not contain plaintext API keys.

        Ollama mode: no api_key lines expected (local models, no auth).
        Remote mode: api_key must use os.environ/VAR_NAME.
        """
        result = kubectl_run(
            "get", "configmap", "litellm-config", "-n", AGENT_NS, "-o", "json"
        )
        if result.returncode != 0:
            pytest.skip("LiteLLM ConfigMap not found")

        cm = json.loads(result.stdout)
        config_yaml = cm.get("data", {}).get("config.yaml", "")

        if IS_OLLAMA:
            for line in config_yaml.splitlines():
                stripped = line.strip()
                if stripped.startswith("api_key:"):
                    pytest.fail(
                        f"Ollama mode should not have api_key in config: '{stripped}'"
                    )
            return

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
        """LiteLLM Deployment must mount API key via secretKeyRef (remote) or literal (Ollama)."""
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

        if IS_OLLAMA:
            if key_env and "value" in key_env:
                return
            pytest.skip("Ollama mode: LITEMAAS_API_KEY not required")
            return

        assert key_env is not None, (
            "LiteLLM deployment missing LITEMAAS_API_KEY env var"
        )
        assert "valueFrom" in key_env, (
            "LITEMAAS_API_KEY has literal value instead of secretKeyRef"
        )
        assert "secretKeyRef" in key_env["valueFrom"], (
            "LITEMAAS_API_KEY uses valueFrom but not secretKeyRef"
        )

    def test_litellm_uses_correct_provider(self):
        """LiteLLM config must use hosted_vllm/ (remote) or ollama/ (local), not openai/."""
        result = kubectl_run(
            "get", "configmap", "litellm-config", "-n", AGENT_NS, "-o", "json"
        )
        if result.returncode != 0:
            pytest.skip("LiteLLM ConfigMap not found")

        cm = json.loads(result.stdout)
        config_yaml = cm.get("data", {}).get("config.yaml", "")

        expected_provider = "ollama/" if IS_OLLAMA else "hosted_vllm/"
        for line in config_yaml.splitlines():
            stripped = line.strip()
            if stripped.startswith("model:") and "openai/" in stripped:
                pytest.fail(
                    f"LiteLLM config uses openai/ provider: '{stripped}'. "
                    f"Must use {expected_provider} to avoid Responses API bridge."
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
        if gw_result.returncode != 0:
            pytest.skip(
                f"Namespace {namespace} has istio.io/use-waypoint={waypoint_label} "
                f"but no waypoint Gateway deployed. "
                f"Deploy with: kubectl apply -f deployments/openshell/waypoint.yaml"
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
        from kagenti.tests.e2e.openshell.conftest import _port_forward

        url, proc = _port_forward("litellm-model-proxy", AGENT_NS, 4000)
        if not url:
            pytest.skip("Cannot port-forward to LiteLLM proxy")
        try:
            resp = httpx.post(
                f"{url}/v1/messages",
                json={
                    "model": "claude-sonnet-4-20250514",
                    "max_tokens": 50,
                    "messages": [
                        {
                            "role": "user",
                            "content": "What is 2+2? Reply with just the number.",
                        }
                    ],
                },
                headers={
                    "x-api-key": "test",
                    "anthropic-version": "2023-06-01",
                },
                timeout=30.0,
            )
            assert resp.status_code == 200, (
                f"Anthropic Messages API returned {resp.status_code}: {resp.text[:200]}"
            )
            data = resp.json()
            assert data.get("type") == "message", (
                f"Expected type=message, got {data.get('type')}"
            )
            assert len(data.get("content", [])) > 0, "Response has no content"
            text = data["content"][0].get("text", "")
            assert "4" in text, f"Expected '4' in response, got: {text}"
        finally:
            if proc:
                proc.terminate()
                proc.wait()

    @skip_no_llm
    def test_claude_model_alias_in_model_list(self):
        """LiteLLM /v1/models must list claude-sonnet-4-20250514."""
        from kagenti.tests.e2e.openshell.conftest import _port_forward

        url, proc = _port_forward("litellm-model-proxy", AGENT_NS, 4000)
        if not url:
            pytest.skip("Cannot port-forward to LiteLLM proxy")
        try:
            resp = httpx.get(f"{url}/v1/models", timeout=10.0)
            assert resp.status_code == 200, f"Model list failed: {resp.text[:200]}"
            models = [m["id"] for m in resp.json().get("data", [])]
            assert "claude-sonnet-4-20250514" in models, (
                f"claude-sonnet-4-20250514 not in model list: {models}"
            )
        finally:
            if proc:
                proc.terminate()
                proc.wait()


class TestLiteLLMModelRouting:
    """Per-model routing tests — verify each configured model responds via LiteLLM."""

    @skip_no_llm
    @pytest.mark.parametrize(
        "model",
        LLM_MODELS if LLM_MODELS else ["gpt-4o-mini"],
        ids=lambda m: m.replace(":", "_").replace("/", "_"),
    )
    def test_litellm_model_routing__responds(self, model):
        """Each configured model must respond via LiteLLM chat completions."""
        from kagenti.tests.e2e.openshell.conftest import _port_forward

        url, proc = _port_forward("litellm-model-proxy", AGENT_NS, 4000)
        if not url:
            pytest.skip("Cannot port-forward to LiteLLM proxy")
        try:
            resp = httpx.post(
                f"{url}/v1/chat/completions",
                json={
                    "model": model,
                    "messages": [
                        {
                            "role": "user",
                            "content": "What is 2+2? Reply with just the number.",
                        }
                    ],
                    "max_tokens": 50,
                },
                timeout=120.0,
            )
            assert resp.status_code == 200, (
                f"Model {model} returned {resp.status_code}: {resp.text[:300]}"
            )
            data = resp.json()
            choices = data.get("choices", [])
            assert len(choices) > 0, f"Model {model} returned no choices"
            content = choices[0].get("message", {}).get("content", "")
            assert len(content) > 0, f"Model {model} returned empty content"
        finally:
            if proc:
                proc.terminate()
                proc.wait()

    @skip_no_llm
    def test_litellm_model_routing__all_models_in_list(self):
        """All configured models must appear in LiteLLM /v1/models."""
        if not LLM_MODELS:
            pytest.skip("No OPENSHELL_LLM_MODELS configured")
        from kagenti.tests.e2e.openshell.conftest import _port_forward

        url, proc = _port_forward("litellm-model-proxy", AGENT_NS, 4000)
        if not url:
            pytest.skip("Cannot port-forward to LiteLLM proxy")
        try:
            resp = httpx.get(f"{url}/v1/models", timeout=10.0)
            assert resp.status_code == 200
            available = {m["id"] for m in resp.json().get("data", [])}
            for model in LLM_MODELS:
                assert model in available, (
                    f"Model {model} not in LiteLLM model list. Available: {sorted(available)}"
                )
        finally:
            if proc:
                proc.terminate()
                proc.wait()
