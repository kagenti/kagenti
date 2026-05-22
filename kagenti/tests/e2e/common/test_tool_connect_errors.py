# Copyright 2025 IBM Corp.
# Licensed under the Apache License, Version 2.0

"""
Tool Connection Error E2E Tests

Tests that the backend returns correct HTTP status codes when MCP tools
are unreachable, instead of a generic 500 Internal Server Error.

Validates fix for: https://github.com/kagenti/kagenti/issues/1144

Usage:
    pytest tests/e2e/common/test_tool_connect_errors.py -v

Environment Variables:
    KAGENTI_BACKEND_URL: Backend API URL
        Kind: http://localhost:8002 (via port-forward)
        OpenShift: https://kagenti-ui-kagenti-system.apps.cluster.example.com/api
"""

import os
import time

import httpx
import pytest


class TestToolConnectErrors:
    """Test that tool connection failures return correct HTTP status codes."""

    @pytest.fixture(autouse=True)
    def _setup_ssl(self, is_openshift, openshift_ingress_ca):
        """Set SSL context for OpenShift routes."""
        import ssl

        if is_openshift:
            self._verify = ssl.create_default_context(cafile=openshift_ingress_ca)
        else:
            self._verify = True

    @pytest.fixture(autouse=True)
    def _require_backend_auth(self, _setup_ssl, backend_url, auth_headers):
        """Skip if backend JWKS keys aren't loaded yet (CI timing issue)."""
        url = f"{backend_url}/api/v1/tools?namespace=team1"
        for attempt in range(3):
            try:
                resp = httpx.get(
                    url, headers=auth_headers, timeout=10.0, verify=self._verify
                )
                if resp.status_code != 401 or "signing key" not in resp.text.lower():
                    return
            except httpx.ConnectError:
                pass
            if attempt < 2:
                time.sleep(5)

        pytest.skip(
            "Backend auth layer not ready (JWKS keys not loaded). "
            "Transient CI issue — not a test failure."
        )

    @pytest.fixture
    def backend_url(self, is_openshift):
        """Get the backend API URL based on environment."""
        url = os.environ.get("KAGENTI_BACKEND_URL")
        if url:
            return url.rstrip("/")

        if is_openshift:
            import subprocess

            result = subprocess.run(
                [
                    "kubectl",
                    "get",
                    "route",
                    "kagenti-ui",
                    "-n",
                    "kagenti-system",
                    "-o",
                    "jsonpath={.spec.host}",
                ],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.returncode == 0 and result.stdout:
                return f"https://{result.stdout}"
            pytest.fail(
                "Could not discover kagenti-ui route. Set KAGENTI_BACKEND_URL env var."
            )
        else:
            return "http://localhost:8002"

    @pytest.fixture
    def auth_headers(self, keycloak_token):
        """Build Authorization header from Keycloak token."""
        return {
            "Authorization": f"Bearer {keycloak_token['access_token']}",
            "Content-Type": "application/json",
        }

    @pytest.mark.critical
    def test_connect_unreachable_tool_returns_502(self, backend_url, auth_headers):
        """
        Verify connecting to an unreachable MCP tool returns 502, not 500.

        When a tool's port is wrong or the tool is not running, the backend
        should return 502 (Bad Gateway) to indicate the upstream tool server
        is unreachable, rather than 500 (Internal Server Error) which
        misleads users into thinking the problem is with Kagenti itself.

        Reproduces: https://github.com/kagenti/kagenti/issues/1144
        """
        # Use a non-existent tool name — the backend will try to connect
        # to a service that doesn't exist, causing a connection error.
        url = f"{backend_url}/api/v1/tools/team1/nonexistent-tool-1144/connect"

        try:
            response = httpx.post(
                url,
                headers=auth_headers,
                timeout=30.0,
                verify=self._verify,
            )
        except httpx.ConnectError as e:
            pytest.skip(
                f"Backend not accessible at {backend_url}. "
                f"Port-forward may not be set up. Error: {e}"
            )

        # The key assertion: must NOT be 500.
        # Should be 502 (Bad Gateway) or 504 (Gateway Timeout).
        assert response.status_code != 500, (
            f"Backend returned 500 for unreachable tool (issue #1144). "
            f"Expected 502 or 504. Response: {response.text}"
        )
        assert response.status_code in (502, 504), (
            f"Expected 502 (Bad Gateway) or 504 (Gateway Timeout) for "
            f"unreachable tool, got {response.status_code}. "
            f"Response: {response.text}"
        )

    @pytest.mark.critical
    def test_connect_unreachable_tool_error_message(self, backend_url, auth_headers):
        """
        Verify the error message mentions the tool URL, not a generic error.

        Users need to know that the problem is with reaching the tool server,
        not with Kagenti itself.
        """
        url = f"{backend_url}/api/v1/tools/team1/nonexistent-tool-1144/connect"

        try:
            response = httpx.post(
                url,
                headers=auth_headers,
                timeout=30.0,
                verify=self._verify,
            )
        except httpx.ConnectError as e:
            pytest.skip(f"Backend not accessible: {e}")

        if response.status_code == 500:
            pytest.fail(
                "Backend still returns 500 for unreachable tool (issue #1144 not fixed)"
            )

        data = response.json()
        detail = data.get("detail", "")

        assert "MCP server" in detail or "connect" in detail.lower(), (
            f"Error message should mention MCP server connection failure. Got: {detail}"
        )
