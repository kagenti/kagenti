"""
LiteLLM Proxy E2E tests.

Tests the LiteLLM proxy gateway deployed in kagenti-system.
Requires port-forward to litellm-proxy service (91-test-litellm.sh sets this up).

Environment variables:
    LITELLM_PROXY_URL: LiteLLM proxy URL (default: http://localhost:14000)
    LITELLM_MASTER_KEY: Master API key for admin operations
    LITELLM_VIRTUAL_KEY: Virtual key for agent operations (optional)
"""

import os

import httpx
import pytest


LITELLM_PROXY_URL = os.getenv("LITELLM_PROXY_URL", "http://localhost:14000")
LITELLM_MASTER_KEY = os.getenv("LITELLM_MASTER_KEY", "")
LITELLM_VIRTUAL_KEY = os.getenv("LITELLM_VIRTUAL_KEY", "")

pytestmark = pytest.mark.skipif(
    not LITELLM_MASTER_KEY,
    reason="LITELLM_MASTER_KEY not set — LiteLLM proxy not deployed",
)


@pytest.fixture(scope="module")
def master_client():
    """HTTP client authenticated with master key."""
    return httpx.Client(
        base_url=LITELLM_PROXY_URL,
        headers={"Authorization": f"Bearer {LITELLM_MASTER_KEY}"},
        timeout=30.0,
    )


@pytest.fixture(scope="module")
def virtual_client():
    """HTTP client authenticated with virtual (agent) key."""
    if not LITELLM_VIRTUAL_KEY:
        pytest.skip("LITELLM_VIRTUAL_KEY not set")
    return httpx.Client(
        base_url=LITELLM_PROXY_URL,
        headers={"Authorization": f"Bearer {LITELLM_VIRTUAL_KEY}"},
        timeout=30.0,
    )


class TestLiteLLMHealth:
    """Health and readiness checks."""

    def test_readiness(self):
        resp = httpx.get(f"{LITELLM_PROXY_URL}/health/readiness", timeout=10)
        assert resp.status_code == 200, f"Readiness check failed: {resp.text}"

    def test_liveliness(self):
        resp = httpx.get(f"{LITELLM_PROXY_URL}/health/liveliness", timeout=10)
        assert resp.status_code == 200, f"Liveliness check failed: {resp.text}"


class TestLiteLLMModels:
    """Model listing and configuration."""

    def test_list_models(self, master_client):
        resp = master_client.get("/v1/models")
        assert resp.status_code == 200, f"Model listing failed: {resp.text}"
        data = resp.json()
        assert "data" in data, "Response missing 'data' field"
        model_ids = [m["id"] for m in data["data"]]
        assert len(model_ids) > 0, "No models returned"

    def test_maas_models_present(self, master_client):
        """MAAS models (llama, mistral, deepseek) are always expected."""
        resp = master_client.get("/v1/models")
        model_ids = [m["id"] for m in resp.json()["data"]]
        for expected in ["llama-4-scout", "mistral-small", "deepseek-r1"]:
            assert expected in model_ids, (
                f"Expected model '{expected}' not in {model_ids}"
            )

    @pytest.mark.skipif(
        not os.environ.get("OPENAI_API_KEY"),
        reason="OPENAI_API_KEY not configured",
    )
    def test_openai_models_present(self, master_client):
        """OpenAI models present when OPENAI_API_KEY is configured."""
        resp = master_client.get("/v1/models")
        model_ids = [m["id"] for m in resp.json()["data"]]
        assert "gpt-4o-mini" in model_ids
        assert "gpt-4o" in model_ids

    def test_model_info(self, master_client):
        resp = master_client.get("/model/info")
        assert resp.status_code == 200, f"Model info failed: {resp.text}"
        data = resp.json()["data"]
        assert len(data) >= 3, f"Expected >= 3 models, got {len(data)}"


class TestLiteLLMChatCompletions:
    """Chat completion through the proxy."""

    def test_chat_completion_llama4(self, master_client):
        """Test chat completion with Llama 4 Scout (default model)."""
        resp = master_client.post(
            "/v1/chat/completions",
            json={
                "model": "llama-4-scout",
                "messages": [{"role": "user", "content": "Say hello in one word."}],
                "max_tokens": 10,
            },
            timeout=60.0,
        )
        assert resp.status_code == 200, f"Chat failed: {resp.text}"
        data = resp.json()
        assert "choices" in data, "Response missing 'choices'"
        assert len(data["choices"]) > 0, "No choices returned"
        content = data["choices"][0]["message"]["content"]
        assert len(content) > 0, "Empty response content"

    def test_chat_completion_has_usage(self, master_client):
        """Verify token usage is returned in response."""
        resp = master_client.post(
            "/v1/chat/completions",
            json={
                "model": "llama-4-scout",
                "messages": [{"role": "user", "content": "Say hi."}],
                "max_tokens": 5,
            },
            timeout=60.0,
        )
        data = resp.json()
        assert "usage" in data, "Response missing 'usage'"
        usage = data["usage"]
        assert usage.get("prompt_tokens", 0) > 0, "No prompt tokens"
        assert usage.get("completion_tokens", 0) > 0, "No completion tokens"
        assert usage.get("total_tokens", 0) > 0, "No total tokens"

    def test_chat_with_metadata(self, master_client):
        """Verify metadata tagging works for spend attribution."""
        resp = master_client.post(
            "/v1/chat/completions",
            json={
                "model": "llama-4-scout",
                "messages": [{"role": "user", "content": "Say test."}],
                "max_tokens": 5,
                "metadata": {
                    "session_id": "e2e-test-session",
                    "agent_name": "e2e-test-agent",
                    "namespace": "team1",
                },
            },
            timeout=60.0,
        )
        assert resp.status_code == 200, f"Chat with metadata failed: {resp.text}"

    def test_chat_mistral(self, master_client):
        """Test chat completion with Mistral Small."""
        resp = master_client.post(
            "/v1/chat/completions",
            json={
                "model": "mistral-small",
                "messages": [{"role": "user", "content": "Say hello in one word."}],
                "max_tokens": 10,
            },
            timeout=60.0,
        )
        assert resp.status_code == 200, f"Mistral chat failed: {resp.text}"
        content = resp.json()["choices"][0]["message"]["content"]
        assert len(content) > 0, "Empty response"

    def test_chat_deepseek(self, master_client):
        """Test chat completion with DeepSeek R1.

        DeepSeek R1 is a reasoning model that may return content in the
        'reasoning_content' field or wrap output in <think> tags. The content
        field itself can be None when all output is reasoning.
        """
        resp = master_client.post(
            "/v1/chat/completions",
            json={
                "model": "deepseek-r1",
                "messages": [{"role": "user", "content": "Say hello in one word."}],
                "max_tokens": 50,
            },
            timeout=60.0,
        )
        assert resp.status_code == 200, f"DeepSeek chat failed: {resp.text}"
        message = resp.json()["choices"][0]["message"]
        # DeepSeek R1 may put output in content or reasoning_content
        content = message.get("content") or ""
        reasoning = message.get("reasoning_content") or ""
        assert len(content) + len(reasoning) > 0, (
            "Both content and reasoning_content are empty"
        )


_openai_configured = pytest.mark.skipif(
    not os.environ.get("OPENAI_API_KEY"),
    reason="OPENAI_API_KEY not configured",
)


class TestLiteLLMOpenAI:
    """OpenAI model tests (skipped if OPENAI_API_KEY not configured)."""

    @_openai_configured
    def test_chat_gpt4o_mini(self, master_client):
        """Test chat completion with GPT-4o mini."""
        resp = master_client.post(
            "/v1/chat/completions",
            json={
                "model": "gpt-4o-mini",
                "messages": [{"role": "user", "content": "Say hello in one word."}],
                "max_tokens": 10,
            },
            timeout=30.0,
        )
        assert resp.status_code == 200, f"GPT-4o-mini chat failed: {resp.text}"
        content = resp.json()["choices"][0]["message"]["content"]
        assert len(content) > 0, "Empty response"

    @_openai_configured
    def test_chat_gpt4o(self, master_client):
        """Test chat completion with GPT-4o."""
        resp = master_client.post(
            "/v1/chat/completions",
            json={
                "model": "gpt-4o",
                "messages": [{"role": "user", "content": "Say hello in one word."}],
                "max_tokens": 10,
            },
            timeout=30.0,
        )
        assert resp.status_code == 200, f"GPT-4o chat failed: {resp.text}"
        content = resp.json()["choices"][0]["message"]["content"]
        assert len(content) > 0, "Empty response"

    @_openai_configured
    def test_gpt4o_mini_has_usage(self, master_client):
        """Verify token usage tracking works for OpenAI models."""
        resp = master_client.post(
            "/v1/chat/completions",
            json={
                "model": "gpt-4o-mini",
                "messages": [{"role": "user", "content": "Say hi."}],
                "max_tokens": 5,
            },
            timeout=30.0,
        )
        usage = resp.json()["usage"]
        assert usage["total_tokens"] > 0, "No tokens tracked for OpenAI model"


class TestLiteLLMVirtualKeys:
    """Virtual key authentication for agent namespaces."""

    def test_virtual_key_can_list_models(self, virtual_client):
        """Virtual key should be able to list available models."""
        resp = virtual_client.get("/v1/models")
        assert resp.status_code == 200, f"Virtual key model list failed: {resp.text}"

    def test_virtual_key_can_chat(self, virtual_client):
        """Virtual key should be able to make chat completions."""
        resp = virtual_client.post(
            "/v1/chat/completions",
            json={
                "model": "llama-4-scout",
                "messages": [{"role": "user", "content": "Say ok."}],
                "max_tokens": 5,
            },
            timeout=60.0,
        )
        assert resp.status_code == 200, f"Virtual key chat failed: {resp.text}"

    def test_invalid_key_rejected(self):
        """Invalid API key should be rejected."""
        resp = httpx.post(
            f"{LITELLM_PROXY_URL}/v1/chat/completions",
            headers={"Authorization": "Bearer sk-invalid-key-12345"},
            json={
                "model": "llama-4-scout",
                "messages": [{"role": "user", "content": "test"}],
                "max_tokens": 5,
            },
            timeout=10.0,
        )
        assert resp.status_code == 401, (
            f"Expected 401 for invalid key, got {resp.status_code}"
        )


class TestLiteLLMSpendTracking:
    """Spend and usage tracking via database."""

    def test_spend_logs_endpoint(self, master_client):
        """Verify spend logs endpoint returns data."""
        resp = master_client.get("/spend/logs")
        assert resp.status_code == 200, f"Spend logs failed: {resp.text}"

    def test_global_spend(self, master_client):
        """Verify global spend endpoint returns aggregated data."""
        resp = master_client.get("/global/spend")
        # 200 with data or empty list both acceptable
        assert resp.status_code == 200, f"Global spend failed: {resp.text}"
