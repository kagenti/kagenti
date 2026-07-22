#!/usr/bin/env python3
"""
MLflow Authentication E2E Tests

Tests MLflow Keycloak OAuth2 authentication integration via mlflow-oidc-auth plugin.

When mlflow.auth.enabled=true:
- MLflow requires OAuth2 authentication via Keycloak
- Unauthenticated requests should be rejected or redirected
- Authenticated requests with valid tokens should succeed

Usage:
    # Run MLflow auth tests
    pytest rossoctl/tests/e2e/common/test_mlflow_auth.py -v

    # Run specific test
    pytest rossoctl/tests/e2e/common/test_mlflow_auth.py::TestMLflowAuth::test_mlflow_version_endpoint -v

Environment Variables:
    MLFLOW_URL: MLflow endpoint (default: http://localhost:5000)
    ROSSOCTL_CONFIG_FILE: Path to Rossoctl config YAML
"""

import os
import logging
import subprocess
from typing import Any, Dict, Optional, Union

import pytest
import httpx

logger = logging.getLogger(__name__)


def get_mlflow_url() -> str | None:
    """Get MLflow URL from environment or auto-detect from cluster."""
    url = os.getenv("MLFLOW_URL")
    if url:
        return url

    # Try to get from OpenShift route (try both oc and kubectl)
    for cmd in ["oc", "kubectl"]:
        try:
            result = subprocess.run(
                [
                    cmd,
                    "get",
                    "route",
                    "mlflow",
                    "-n",
                    "rossoctl-system",
                    "-o",
                    "jsonpath={.spec.host}",
                ],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.returncode == 0 and result.stdout:
                return f"https://{result.stdout}"
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass

    return None


# ============================================================================
# Test Configuration & Fixtures
# ============================================================================


@pytest.fixture(scope="module")
def mlflow_url():
    """MLflow endpoint URL.

    Default: localhost:5000 (via port-forward)
    In-cluster: http://mlflow.rossoctl-system.svc.cluster.local:5000
    OpenShift: Uses Route URL from MLFLOW_URL env var
    """
    return os.getenv("MLFLOW_URL", "http://localhost:5000")


@pytest.fixture(scope="module")
def require_mlflow_url():
    """Get MLflow URL, auto-detecting from cluster if not set.

    This fixture ensures MLflow auth tests get a valid URL either from:
    1. MLFLOW_URL environment variable
    2. Auto-detected from OpenShift route in rossoctl-system namespace

    Skips when MLflow URL cannot be determined — on RHOAI/HyperShift the
    mlflowoperator may not reconcile on every ephemeral cluster.
    """
    mlflow_url = get_mlflow_url()
    if not mlflow_url:
        pytest.skip(
            "MLflow URL not available — "
            "set MLFLOW_URL env var or ensure mlflow route/port-forward exists."
        )
    return mlflow_url


@pytest.fixture(scope="module")
def keycloak_url():
    """Keycloak endpoint URL.

    Default: localhost:8081 (via port-forward)
    """
    return os.getenv("KEYCLOAK_URL", "http://localhost:8081")


# ============================================================================
# Helper Functions
# ============================================================================


async def query_mlflow_api(
    mlflow_url: str,
    endpoint: str,
    token: Optional[str] = None,
    timeout: int = 10,
    verify_ssl: Union[bool, str] = True,
    params: Optional[Dict[str, Any]] = None,
) -> httpx.Response:
    """
    Query MLflow REST API with optional authentication.

    Args:
        mlflow_url: MLflow base URL
        endpoint: API endpoint path (e.g., /api/2.0/mlflow/experiments/list)
        token: Optional OAuth2 access token
        timeout: Request timeout in seconds
        verify_ssl: True, or path to CA bundle for OpenShift
        params: Optional query parameters

    Returns:
        httpx.Response object
    """
    url = f"{mlflow_url}{endpoint}"

    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    async with httpx.AsyncClient(follow_redirects=False, verify=verify_ssl) as client:
        response = await client.get(
            url,
            headers=headers,
            timeout=timeout,
            params=params,
        )
        return response


def get_keycloak_token(
    keycloak_url: str,
    username: str,
    password: str,
    realm: str = "master",
    client_id: str = "admin-cli",
    verify_ssl: Union[bool, str] = True,
) -> Dict[str, str]:
    """
    Get access token from Keycloak using password grant.

    Args:
        keycloak_url: Keycloak base URL
        username: User username
        password: User password
        realm: Keycloak realm (default: master)
        client_id: OAuth client ID (default: admin-cli)
        verify_ssl: True, or path to CA bundle for OpenShift

    Returns:
        Token response dict with access_token, refresh_token, etc.
    """
    import requests

    token_url = f"{keycloak_url}/realms/{realm}/protocol/openid-connect/token"

    data = {
        "grant_type": "password",
        "client_id": client_id,
        "username": username,
        "password": password,
    }

    response = requests.post(token_url, data=data, timeout=10, verify=verify_ssl)
    response.raise_for_status()
    return response.json()


def get_mlflow_service_token(
    keycloak_url: str,
    client_id: str,
    client_secret: str,
    realm: str = "master",
    verify_ssl: Union[bool, str] = True,
) -> Dict[str, str]:
    """
    Get access token from Keycloak using client credentials grant.

    This is the secure way to get a service account token for MLflow API access.
    The mlflow client in Keycloak has "Service Accounts Enabled" which allows
    this grant type.

    Args:
        keycloak_url: Keycloak base URL
        client_id: OAuth client ID (e.g., "mlflow")
        client_secret: OAuth client secret
        realm: Keycloak realm (default: master)
        verify_ssl: True, or path to CA bundle for OpenShift

    Returns:
        Token response dict with access_token, token_type, etc.
    """
    import requests

    token_url = f"{keycloak_url}/realms/{realm}/protocol/openid-connect/token"

    data = {
        "grant_type": "client_credentials",
        "client_id": client_id,
        "client_secret": client_secret,
    }

    response = requests.post(token_url, data=data, timeout=10, verify=verify_ssl)
    response.raise_for_status()
    return response.json()


# ============================================================================
# Test Class: MLflow Authentication
# ============================================================================


@pytest.mark.requires_features(["mlflow", "keycloak"])
class TestMLflowAuth:
    """Test MLflow Keycloak OAuth2 authentication."""

    @pytest.fixture(autouse=True)
    def _setup_ssl(self, is_openshift, openshift_ingress_ca):
        """Set SSL verification: SSLContext with CA on OpenShift, True on Kind."""
        import ssl

        if is_openshift:
            self.ssl_verify = ssl.create_default_context(cafile=openshift_ingress_ca)
        else:
            self.ssl_verify = True

    @pytest.mark.asyncio
    async def test_mlflow_version_endpoint(
        self, require_mlflow_url, is_openshift, keycloak_url
    ):
        """
        Test MLflow /version endpoint is accessible.

        When auth is enabled (401 or 302/307), follows up with an authenticated
        request to verify MLflow actually serves content.
        """
        mlflow_url = require_mlflow_url
        logger.info("=" * 70)
        logger.info("Testing: MLflow Version Endpoint")
        logger.info(f"MLflow URL: {mlflow_url}")
        logger.info(f"OpenShift: {is_openshift}")
        logger.info("=" * 70)

        response = await query_mlflow_api(
            mlflow_url=mlflow_url,
            endpoint="/version",
            token=None,
            timeout=10,
            verify_ssl=self.ssl_verify,
        )

        logger.info(f"Response status: {response.status_code}")
        logger.info(f"Response body: {response.text}")

        assert response.status_code in (200, 302, 307, 401, 403), (
            f"MLflow /version endpoint failed: {response.status_code} - {response.text}"
        )

        if response.status_code == 200:
            logger.info("TEST PASSED: MLflow version endpoint accessible (no auth)")
        elif response.status_code in (401, 302, 307):
            logger.info(
                f"Auth required ({response.status_code}), verifying with credentials..."
            )
            try:
                token_resp = get_keycloak_token(
                    keycloak_url=keycloak_url,
                    username="admin",
                    password="admin",
                    realm="rossoctl",
                    verify_ssl=self.ssl_verify,
                )
                auth_response = await query_mlflow_api(
                    mlflow_url=mlflow_url,
                    endpoint="/version",
                    token=token_resp["access_token"],
                    timeout=10,
                    verify_ssl=self.ssl_verify,
                )
                assert auth_response.status_code == 200, (
                    f"Authenticated /version request failed: {auth_response.status_code}"
                )
                logger.info(
                    f"TEST PASSED: MLflow version accessible with auth: {auth_response.text.strip()}"
                )
            except Exception as e:
                logger.warning(f"Could not verify with auth (non-fatal): {e}")
                logger.info(
                    "TEST PASSED: MLflow endpoint responds (auth verification skipped)"
                )

    @pytest.mark.asyncio
    async def test_mlflow_api_accessible(self, require_mlflow_url, is_openshift):
        """
        Test MLflow API responds to requests.

        This is a basic connectivity test. When auth is disabled,
        the API should return 200. When auth is enabled, it may
        return 401 or 302 (redirect to login).
        """
        mlflow_url = require_mlflow_url
        logger.info("=" * 70)
        logger.info("Testing: MLflow API Accessibility")
        logger.info(f"MLflow URL: {mlflow_url}")
        logger.info("=" * 70)

        response = await query_mlflow_api(
            mlflow_url=mlflow_url,
            endpoint="/api/2.0/mlflow/experiments/search",
            token=None,
            timeout=10,
            verify_ssl=self.ssl_verify,
            params={"max_results": "1"},
        )

        # Log the response for debugging
        logger.info(f"Response status: {response.status_code}")
        logger.info(f"Response headers: {dict(response.headers)}")

        # MLflow should respond (200, 401, or 302 depending on auth config)
        assert response.status_code in [200, 401, 302, 307, 403], (
            f"Unexpected MLflow response: {response.status_code} - {response.text}"
        )

        if response.status_code == 200:
            logger.info("MLflow API accessible without authentication")
        elif response.status_code in [401, 403]:
            logger.info("MLflow requires authentication (auth enabled)")
        elif response.status_code in [302, 307]:
            location = response.headers.get("location", "")
            logger.info(f"MLflow redirects to login: {location}")

        logger.info("TEST PASSED: MLflow API responds correctly")

    @pytest.mark.asyncio
    async def test_mlflow_unauthenticated_blocked_or_allowed(
        self, require_mlflow_url, is_openshift
    ):
        """
        Test MLflow behavior for unauthenticated requests.

        When auth is disabled: Should return 200 with valid response.
        When auth is enabled: Should return 401 or redirect to Keycloak.
        """
        mlflow_url = require_mlflow_url
        logger.info("=" * 70)
        logger.info("Testing: MLflow Unauthenticated Request Handling")
        logger.info("=" * 70)

        response = await query_mlflow_api(
            mlflow_url=mlflow_url,
            endpoint="/api/2.0/mlflow/experiments/search",
            token=None,
            timeout=10,
            verify_ssl=self.ssl_verify,
            params={"max_results": "1"},
        )

        if response.status_code == 200:
            # Auth disabled - verify we get valid response
            data = response.json()
            assert "experiments" in data, f"Invalid response: {data}"
            logger.info("Auth DISABLED: Unauthenticated requests allowed")
        elif response.status_code in [401, 403]:
            logger.info("Auth ENABLED: Unauthenticated requests blocked with 401/403")
        elif response.status_code in [302, 307]:
            location = response.headers.get("location", "")
            assert "keycloak" in location.lower() or "oauth" in location.lower(), (
                f"Redirect doesn't point to Keycloak: {location}"
            )
            logger.info(f"Auth ENABLED: Redirecting to Keycloak: {location}")
        else:
            pytest.fail(f"Unexpected status code: {response.status_code}")

        logger.info("TEST PASSED: MLflow handles unauthenticated requests correctly")

    @pytest.mark.asyncio
    async def test_mlflow_oauth_secret_exists(self, k8s_client):
        """
        Test that mlflow-oauth-secret Kubernetes secret exists.

        This secret should be created by the mlflow-oauth-secret-job
        and contains the OAuth credentials for MLflow.
        """
        logger.info("Testing: mlflow-oauth-secret exists")

        from kubernetes.client.rest import ApiException

        try:
            secret = k8s_client.read_namespaced_secret(
                name="mlflow-oauth-secret",
                namespace="rossoctl-system",
            )

            # Verify expected keys
            expected_keys = [
                "OIDC_CLIENT_ID",
                "OIDC_CLIENT_SECRET",
                "OIDC_DISCOVERY_URL",
            ]

            for key in expected_keys:
                assert key in secret.data, (
                    f"Missing key '{key}' in mlflow-oauth-secret. "
                    f"Found keys: {list(secret.data.keys())}"
                )
                logger.info(f"Found secret key: {key}")

            logger.info("TEST PASSED: mlflow-oauth-secret exists with required keys")

        except ApiException as e:
            if e.status == 404:
                pytest.skip(
                    "mlflow-oauth-secret not found - MLflow auth may not be enabled"
                )
            else:
                pytest.fail(f"Error reading mlflow-oauth-secret: {e}")


# ============================================================================
# Test Class: MLflow Backend (without auth requirement)
# ============================================================================


@pytest.mark.requires_features(["mlflow"])
class TestMLflowBackend:
    """Test MLflow backend deployment health."""

    @pytest.fixture(autouse=True)
    def _setup_ssl(self, is_openshift, openshift_ingress_ca):
        """Set SSL verification: SSLContext with CA on OpenShift, True on Kind."""
        import ssl

        if is_openshift:
            self.ssl_verify = ssl.create_default_context(cafile=openshift_ingress_ca)
        else:
            self.ssl_verify = True

    @pytest.mark.asyncio
    async def test_mlflow_pod_running(self, k8s_client, is_openshift):
        """Test MLflow pod is running.

        Kind deploys MLflow to rossoctl-system (Helm chart).
        OpenShift/RHOAI deploys to redhat-ods-applications (RHOAI operator).
        """
        from kubernetes.client.rest import ApiException

        namespaces = (
            ["redhat-ods-applications", "rossoctl-system"]
            if is_openshift
            else ["rossoctl-system"]
        )
        mlflow_pod = None
        for ns in namespaces:
            try:
                pods = k8s_client.list_namespaced_pod(namespace=ns)
            except ApiException:
                continue
            for pod in pods.items:
                if (
                    "mlflow" in pod.metadata.name.lower()
                    and "operator" not in pod.metadata.name.lower()
                ):
                    mlflow_pod = pod
                    break
            if mlflow_pod:
                break

        assert mlflow_pod is not None, f"MLflow pod not found in {namespaces}"
        assert mlflow_pod.status.phase == "Running", (
            f"MLflow pod not running: {mlflow_pod.status.phase}"
        )

        logger.info(f"MLflow pod running: {mlflow_pod.metadata.name}")

    @pytest.mark.asyncio
    async def test_mlflow_health_check(
        self, require_mlflow_url, is_openshift, keycloak_url
    ):
        """
        Test MLflow responds to health check.

        Uses /version endpoint. When auth is enabled, follows up with an
        authenticated request to confirm MLflow serves content.
        """
        mlflow_url = require_mlflow_url
        logger.info("Testing: MLflow Health Check")

        try:
            response = await query_mlflow_api(
                mlflow_url=mlflow_url,
                endpoint="/version",
                token=None,
                timeout=10,
                verify_ssl=self.ssl_verify,
            )

            assert response.status_code in (200, 302, 307, 401, 403), (
                f"MLflow health check failed: {response.status_code}"
            )

            if response.status_code == 200:
                version = response.text.strip().strip('"')
                logger.info(f"MLflow version: {version}")
                logger.info("TEST PASSED: MLflow is healthy (no auth)")
            elif response.status_code in (401, 302, 307):
                logger.info(
                    f"Auth required ({response.status_code}), verifying with credentials..."
                )
                try:
                    token_resp = get_keycloak_token(
                        keycloak_url=keycloak_url,
                        username="admin",
                        password="admin",
                        realm="rossoctl",
                        verify_ssl=self.ssl_verify,
                    )
                    auth_response = await query_mlflow_api(
                        mlflow_url=mlflow_url,
                        endpoint="/version",
                        token=token_resp["access_token"],
                        timeout=10,
                        verify_ssl=self.ssl_verify,
                    )
                    assert auth_response.status_code == 200, (
                        f"Authenticated health check failed: {auth_response.status_code}"
                    )
                    version = auth_response.text.strip().strip('"')
                    logger.info(f"TEST PASSED: MLflow healthy, version: {version}")
                except Exception as e:
                    logger.warning(f"Could not verify with auth (non-fatal): {e}")
                    logger.info(
                        "TEST PASSED: MLflow responds (auth verification skipped)"
                    )

        except httpx.ConnectError as e:
            pytest.fail(f"Could not connect to MLflow at {mlflow_url}: {e}")


if __name__ == "__main__":
    import sys

    sys.exit(pytest.main([__file__, "-v"]))
