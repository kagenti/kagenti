#!/usr/bin/env -S uv run --no-project --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["litellm", "httpx>=0.27"]
# ///
"""Simple LLM test agent that makes two LiteLLM calls via a LiteLLM proxy.

Env vars (first found wins):
    OPENAI_API_BASE or ANTHROPIC_BASE_URL  — LiteLLM proxy URL
    OPENAI_API_KEY  or ANTHROPIC_AUTH_TOKEN — Virtual key (must start with sk-)
    LITELLM_MODEL                          — Model name (default: anthropic/claude-sonnet-4-20250514)

Usage:
    export ANTHROPIC_BASE_URL=https://ete-litellm.ai-models.vpc-int.res.ibm.com
    export ANTHROPIC_AUTH_TOKEN=sk-...
    ./scripts/simple_llm_test_agent.py

Optional test flags (disabled by default):
    ./simple_llm_test_agent.py --test-network              # test HTTP connectivity to known hosts
    ./simple_llm_test_agent.py --test-credentials URL      # test credential injection against a service
    ./simple_llm_test_agent.py --skip-llm --test-network   # skip LLM calls, only run tests
"""
from __future__ import annotations

import argparse
import os
import sys

import httpx
import litellm

MODEL = os.environ.get("ANTHROPIC_MODEL") or os.environ.get("LITELLM_MODEL", "claude-sonnet-4-6")
BASE_URL = os.environ.get("OPENAI_API_BASE") or os.environ.get("ANTHROPIC_BASE_URL", "")
API_KEY = os.environ.get("OPENAI_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN", "")


def call_llm(messages: list[dict], step: str) -> str:
    print(f"\n{'='*60}")
    print(f"Step: {step}")
    print(f"{'='*60}")

    response = litellm.completion(
        model=f"openai/{MODEL}",
        messages=messages,
        api_base=BASE_URL,
        api_key=API_KEY,
        max_tokens=256,
    )

    content = response.choices[0].message.content
    print(f"Response:\n{content}")
    return content


def test_network():
    """Test HTTP connectivity to known hosts (bypasses HTTPS_PROXY to test raw access)."""
    print(f"\n{'='*60}")
    print("Network access tests")
    print(f"{'='*60}")

    targets = [
        ("https://github.com", "github.com (should be allowed)"),
        ("https://www.cnn.com", "cnn.com (should be denied)"),
    ]

    for url, desc in targets:
        try:
            resp = httpx.get(url, timeout=10, follow_redirects=True, proxy=None)
            print(f"  [PASS] {desc} — status {resp.status_code}")
        except httpx.ConnectError:
            print(f"  [BLOCKED] {desc} — connection refused/unreachable")
        except httpx.TimeoutException:
            print(f"  [BLOCKED] {desc} — timeout")
        except Exception as e:
            print(f"  [FAIL] {desc} — {type(e).__name__}: {e}")


def test_credentials(validate_url: str):
    """Test credential injection against a validation service.

    Tests two scenarios:
    1. Send the configured API_KEY (placeholder or real) — should be accepted if credential
       injection works correctly (rossocortex replaces placeholder with real key)
    2. Send a random wrong key — should be rejected (proves the service validates)
    """
    print(f"\n{'='*60}")
    print(f"Credential injection test → {validate_url}")
    print(f"{'='*60}")

    key = API_KEY
    if not key:
        print(f"  [SKIP] No API key configured (set OPENAI_API_KEY)")
        return

    import secrets as _secrets
    wrong_key = f"sk-wrong-{_secrets.token_hex(8)}"

    print(f"  Key used: {key[:12]}..." if len(key) > 12 else f"  Key used: {key}")

    try:
        resp = httpx.post(
            validate_url,
            headers={"Authorization": f"Bearer {key}"},
            timeout=5,
            proxy=None,
        )
        data = resp.json()
        if resp.status_code == 200:
            print(f"  [PASS] Correct key accepted: {data.get('key_prefix', '')}")
        else:
            print(f"  [FAIL] Correct key rejected ({resp.status_code}): {data}")
    except httpx.ConnectError:
        print(f"  [FAIL] Cannot connect to {validate_url} — is test_credential_service.py running?")
        return
    except Exception as e:
        print(f"  [FAIL] {type(e).__name__}: {e}")
        return

    try:
        resp2 = httpx.post(
            validate_url,
            headers={"Authorization": f"Bearer {wrong_key}"},
            timeout=5,
            proxy=None,
        )
        if resp2.status_code == 401:
            print(f"  [PASS] Wrong key rejected (401) — service validates correctly")
        else:
            print(f"  [FAIL] Wrong key was accepted ({resp2.status_code}) — service is broken")
    except Exception as e:
        print(f"  [FAIL] Wrong-key test: {type(e).__name__}: {e}")


def main():
    parser = argparse.ArgumentParser(description="Simple LLM test agent")
    parser.add_argument("--test-network", action="store_true", help="Test HTTP connectivity to known hosts")
    parser.add_argument("--test-credentials", metavar="URL", help="Test credential injection against a validation service URL")
    parser.add_argument("--skip-llm", action="store_true", help="Skip LLM calls (only run tests)")
    args = parser.parse_args()

    if not args.skip_llm:
        if not BASE_URL:
            print("ERROR: Set OPENAI_API_BASE or ANTHROPIC_BASE_URL (e.g. https://ete-litellm.ai-models.vpc-int.res.ibm.com)")
            raise SystemExit(1)
        if not API_KEY:
            print("ERROR: Set OPENAI_API_KEY or ANTHROPIC_AUTH_TOKEN (LiteLLM virtual key, starts with sk-)")
            raise SystemExit(1)

        print(f"Simple LLM test agent")
        print(f"Model: {MODEL}")
        print(f"Base URL: {BASE_URL}")

        plan = call_llm(
            messages=[
                {"role": "system", "content": "You are a coding assistant. Be very brief."},
                {"role": "user", "content": "Plan a Python function that computes fibonacci(n). Just describe the approach in 2 sentences."},
            ],
            step="Planning",
        )

        call_llm(
            messages=[
                {"role": "system", "content": "You are a coding assistant. Output only code, no explanation."},
                {"role": "user", "content": f"Based on this plan: {plan}\n\nWrite the Python function fibonacci(n)."},
            ],
            step="Code generation",
        )

        print(f"\n{'='*60}")
        print("Agent complete — 2 LLM calls made.")

    if args.test_network:
        test_network()

    if args.test_credentials:
        test_credentials(args.test_credentials)

    if args.skip_llm and not args.test_network and not args.test_credentials:
        print("Nothing to do. Use --test-network or --test-credentials with --skip-llm.")


if __name__ == "__main__":
    main()
