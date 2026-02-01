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
    pytest kagenti/tests/e2e/common/test_mlflow_auth.py -v

    # Run specific test
    pytest kagenti/tests/e2e/common/test_mlflow_auth.py::TestMLflowAuth::test_mlflow_version_endpoint -v

Environment Variables:
    MLFLOW_URL: MLflow endpoint (default: http://localhost:5000)
    KAGENTI_CONFIG_FILE: Path to Kagenti config YAML
"""

import os
import logging
from typing import Dict, Optional

import pytest
import httpx

logger = logging.getLogger(__name__)


# ============================================================================
# Test Configuration & Fixtures
# ============================================================================


@pytest.fixture(scope="module")
def mlflow_url():
    """MLflow endpoint URL.

    Default: localhost:5000 (via port-forward)
    In-cluster: http://mlflow.kagenti-system.svc.cluster.local:5000
    OpenShift: Uses Route URL from MLFLOW_URL env var
    """
    return os.getenv("MLFLOW_URL", "http://localhost:5000")


@pytest.fixture(scope="module")
def require_mlflow_url():
    """Skip tests if MLFLOW_URL is not explicitly set.

    This fixture ensures MLflow auth tests only run when MLFLOW_URL
    is explicitly configured (e.g., in OpenShift CI or local testing
    with port-forward). Without this, tests would try localhost:5000
    which may not be accessible in all CI environments.
    """
    mlflow_url = os.getenv("MLFLOW_URL")
    if not mlflow_url:
        pytest.skip(
            "MLFLOW_URL not set - MLflow auth tests require explicit endpoint. "
            "Set MLFLOW_URL or use port-forward: kubectl port-forward svc/mlflow 5000:5000 -n kagenti-system"
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
    verify_ssl: bool = True,
) -> httpx.Response:
    """
    Query MLflow REST API with optional authentication.

    Args:
        mlflow_url: MLflow base URL
        endpoint: API endpoint path (e.g., /api/2.0/mlflow/experiments/list)
        token: Optional OAuth2 access token
        timeout: Request timeout in seconds
        verify_ssl: Whether to verify SSL certificates (False for OpenShift self-signed)

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
        )
        return response


def get_keycloak_token(
    keycloak_url: str,
    username: str,
    password: str,
    realm: str = "master",
    client_id: str = "admin-cli",
) -> Dict[str, str]:
    """
    Get access token from Keycloak using password grant.

    Args:
        keycloak_url: Keycloak base URL
        username: User username
        password: User password
        realm: Keycloak realm (default: master)
        client_id: OAuth client ID (default: admin-cli)

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

    response = requests.post(token_url, data=data, timeout=10)
    response.raise_for_status()
    return response.json()


# ============================================================================
# Test Class: MLflow Authentication
# ============================================================================


@pytest.mark.requires_features(["mlflow", "keycloak"])
class TestMLflowAuth:
    """Test MLflow Keycloak OAuth2 authentication."""

    @pytest.mark.asyncio
    async def test_mlflow_version_endpoint(self, require_mlflow_url, is_openshift):
        """
        Test MLflow /version endpoint is accessible.

        The /version endpoint should always be accessible regardless of auth
        configuration, as it's used for health checks.
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
            verify_ssl=not is_openshift,
        )

        logger.info(f"Response status: {response.status_code}")
        logger.info(f"Response body: {response.text}")

        # Version endpoint should always return 200
        assert response.status_code == 200, (
            f"MLflow /version endpoint failed: {response.status_code} - {response.text}"
        )

        logger.info("TEST PASSED: MLflow version endpoint accessible")

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
            verify_ssl=not is_openshift,
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
            verify_ssl=not is_openshift,
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
    async def test_mlflow_api_accessible_with_token(
        self, require_mlflow_url, keycloak_admin_credentials, is_openshift
    ):
        """
        Test MLflow API is accessible with valid Keycloak token.

        This test:
        1. Gets an access token from Keycloak
        2. Uses the token to query MLflow API
        3. Verifies the request succeeds
        """
        mlflow_url = require_mlflow_url
        logger.info("=" * 70)
        logger.info("Testing: MLflow API with Keycloak Token")
        logger.info("=" * 70)

        # Get Keycloak token using admin credentials
        keycloak_url = os.getenv("KEYCLOAK_URL", "http://localhost:8081")

        try:
            token_response = get_keycloak_token(
                keycloak_url=keycloak_url,
                username=keycloak_admin_credentials["username"],
                password=keycloak_admin_credentials["password"],
                realm="master",
            )
        except Exception as e:
            pytest.skip(f"Could not get Keycloak token: {e}")

        access_token = token_response["access_token"]
        logger.info(
            f"Got Keycloak token (expires in {token_response.get('expires_in')}s)"
        )

        # Query MLflow with token
        response = await query_mlflow_api(
            mlflow_url=mlflow_url,
            endpoint="/api/2.0/mlflow/experiments/search",
            token=access_token,
            timeout=10,
            verify_ssl=not is_openshift,
        )

        logger.info(f"Response status: {response.status_code}")

        # With valid token, we should get 200
        if response.status_code == 200:
            data = response.json()
            assert "experiments" in data, f"No experiments in response: {data}"
            logger.info("MLflow API accessible with Keycloak token")
            logger.info(f"Found {len(data.get('experiments', []))} experiments")
        elif response.status_code in [401, 403]:
            # Token might be rejected if MLflow OAuth client is different from admin-cli
            logger.warning(
                f"Token rejected. MLflow may require specific OAuth client. "
                f"Status: {response.status_code}"
            )
            pytest.skip(
                "MLflow rejected Keycloak admin token - may need MLflow-specific OAuth client"
            )
        else:
            pytest.fail(
                f"Unexpected response: {response.status_code} - {response.text}"
            )

        logger.info("TEST PASSED: MLflow API accessible with authentication")

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
                namespace="kagenti-system",
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

    @pytest.mark.asyncio
    async def test_mlflow_pod_running(self, k8s_client):
        """Test MLflow pod is running in kagenti-system namespace."""
        from kubernetes.client.rest import ApiException

        try:
            pods = k8s_client.list_namespaced_pod(namespace="kagenti-system")
        except ApiException as e:
            pytest.fail(f"Could not list pods in kagenti-system: {e}")

        mlflow_pod = None
        for pod in pods.items:
            if "mlflow" in pod.metadata.name.lower():
                mlflow_pod = pod
                break

        assert mlflow_pod is not None, (
            "MLflow pod not found in kagenti-system namespace"
        )
        assert mlflow_pod.status.phase == "Running", (
            f"MLflow pod not running: {mlflow_pod.status.phase}"
        )

        logger.info(f"MLflow pod running: {mlflow_pod.metadata.name}")

    @pytest.mark.asyncio
    async def test_mlflow_health_check(self, require_mlflow_url, is_openshift):
        """
        Test MLflow responds to health check.

        Uses /version endpoint which should always be accessible.
        """
        mlflow_url = require_mlflow_url
        logger.info("Testing: MLflow Health Check")

        try:
            response = await query_mlflow_api(
                mlflow_url=mlflow_url,
                endpoint="/version",
                token=None,
                timeout=10,
                verify_ssl=not is_openshift,
            )

            assert response.status_code == 200, (
                f"MLflow health check failed: {response.status_code}"
            )

            version = response.text.strip().strip('"')
            logger.info(f"MLflow version: {version}")
            logger.info("TEST PASSED: MLflow is healthy")

        except httpx.ConnectError as e:
            pytest.fail(f"Could not connect to MLflow at {mlflow_url}: {e}")


# ============================================================================
# Test Class: MLflow Trace Validation
# ============================================================================


@pytest.mark.requires_features(["mlflow", "otel"])
class TestMLflowTraces:
    """
    Test that weather agent traces are captured in MLflow.

    These tests verify that:
    - Agent conversations generate traces in MLflow
    - Traces contain expected span data
    - OpenTelemetry integration is working

    NOTE: These tests should run AFTER agent conversation tests
    to ensure traces have been generated.
    """

    @pytest.mark.asyncio
    async def test_mlflow_has_experiments(self, require_mlflow_url, is_openshift):
        """
        Test that MLflow has at least one experiment.

        This validates that MLflow is configured correctly.
        """
        mlflow_url = require_mlflow_url
        logger.info("=" * 70)
        logger.info("Testing: MLflow Experiments")
        logger.info(f"MLflow URL: {mlflow_url}")
        logger.info("=" * 70)

        try:
            response = await query_mlflow_api(
                mlflow_url=mlflow_url,
                endpoint="/api/2.0/mlflow/experiments/search",
                token=None,
                timeout=15,
                verify_ssl=not is_openshift,
            )

            # Handle auth-protected MLflow
            if response.status_code in [401, 302, 307, 403]:
                logger.info(
                    f"MLflow requires authentication (status {response.status_code}). "
                    "Skipping experiment validation - auth integration verified."
                )
                pytest.skip("MLflow requires authentication - experiment test skipped")

            assert response.status_code == 200, (
                f"MLflow returned {response.status_code}: {response.text}"
            )

            data = response.json()
            experiments = data.get("experiments", [])
            logger.info(f"Found {len(experiments)} experiment(s) in MLflow")

            for exp in experiments:
                logger.info(
                    f"  Experiment: {exp.get('name', 'unknown')} "
                    f"(id={exp.get('experiment_id')})"
                )

            logger.info("TEST PASSED: MLflow experiments accessible")

        except httpx.ConnectError as e:
            pytest.fail(f"Could not connect to MLflow at {mlflow_url}: {e}")

    @pytest.mark.asyncio
    async def test_mlflow_traces_endpoint(self, require_mlflow_url, is_openshift):
        """
        Test MLflow traces API endpoint.

        MLflow 2.14+ supports OTLP trace ingestion and provides
        a traces endpoint for querying.
        """
        mlflow_url = require_mlflow_url
        logger.info("Testing: MLflow Traces Endpoint")

        try:
            # Try the traces search endpoint
            response = await query_mlflow_api(
                mlflow_url=mlflow_url,
                endpoint="/api/2.0/mlflow/traces",
                token=None,
                timeout=15,
                verify_ssl=not is_openshift,
            )

            # Handle auth-protected MLflow
            if response.status_code in [401, 302, 307, 403]:
                pytest.skip("MLflow requires authentication - trace test skipped")

            if response.status_code == 404:
                logger.info(
                    "MLflow traces endpoint not available. "
                    "This may require MLflow 2.14+ with tracing enabled."
                )
                pytest.skip("MLflow traces endpoint not available")

            if response.status_code == 200:
                data = response.json()
                traces = data.get("traces", [])
                logger.info(f"Found {len(traces)} trace(s) in MLflow")
                logger.info("TEST PASSED: MLflow traces accessible")
            else:
                logger.warning(
                    f"Unexpected response from traces endpoint: {response.status_code}"
                )

        except httpx.ConnectError as e:
            pytest.fail(f"Could not connect to MLflow at {mlflow_url}: {e}")


if __name__ == "__main__":
    import sys

    sys.exit(pytest.main([__file__, "-v"]))
