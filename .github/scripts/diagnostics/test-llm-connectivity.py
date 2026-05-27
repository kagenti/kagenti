#!/usr/bin/env python3
"""Test LLM endpoint connectivity from inside an agent pod.

Verifies DNS, TLS, httpx, and OpenAI client connectivity to the
configured LLM endpoint. Used by 74-deploy-weather-agent.sh after
deployment to surface the actual failure layer when the agent can't
reach external LLM services.

Remove once kagenti-extensions#428 properly handles external egress
in authbridge proxy-sidecar mode.
"""

import os
import socket
import ssl
import sys


def main():
    host = os.environ.get("LLM_HOST", "")
    url = os.environ.get("LLM_URL", "")
    if not host or not url:
        print("LLM_HOST and LLM_URL must be set")
        sys.exit(1)

    port = 443
    ok = True

    for k in (
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "http_proxy",
        "https_proxy",
        "NO_PROXY",
        "no_proxy",
    ):
        v = os.environ.get(k)
        if v:
            print(f"PROXY: {k}={v}")

    try:
        ip = socket.getaddrinfo(host, port)[0][4][0]
        print(f"DNS OK: {host} -> {ip}")
    except Exception as e:
        print(f"DNS FAIL: {host} -> {e}")
        sys.exit(1)

    try:
        ctx = ssl.create_default_context()
        with socket.create_connection((host, port), timeout=10) as sock:
            with ctx.wrap_socket(sock, server_hostname=host) as ssock:
                print(f"TLS OK: {ssock.version()}")
    except Exception as e:
        print(f"TLS FAIL: {host}:{port} -> {e}")
        sys.exit(1)

    try:
        import httpx

        r = httpx.get(
            url + "/models", timeout=15, headers={"Authorization": "Bearer test"}
        )
        print(f"HTTPX OK: status={r.status_code}")
    except Exception as e:
        print(f"HTTPX FAIL: {type(e).__name__}: {e}")
        ok = False

    try:
        import openai

        c = openai.OpenAI(
            base_url=url, api_key=os.environ.get("OPENAI_API_KEY", "test")
        )
        c.models.list()
        print("OPENAI OK")
    except Exception as e:
        cause = getattr(e, "__cause__", e)
        print(f"OPENAI FAIL: {type(e).__name__}: {cause}")
        ok = False

    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
