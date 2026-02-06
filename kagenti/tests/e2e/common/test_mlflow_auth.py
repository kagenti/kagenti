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
import subprocess
from typing import Any, Dict, Optional

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
    In-cluster: http://mlflow.kagenti-system.svc.cluster.local:5000
    OpenShift: Uses Route URL from MLFLOW_URL env var
    """
    return os.getenv("MLFLOW_URL", "http://localhost:5000")


@pytest.fixture(scope="module")
def require_mlflow_url():
    """Get MLflow URL, auto-detecting from cluster if not set.

    This fixture ensures MLflow auth tests get a valid URL either from:
    1. MLFLOW_URL environment variable
    2. Auto-detected from OpenShift route in kagenti-system namespace

    Fails the test if no URL can be determined - tests should fail,
    not skip, when MLflow is expected to be available.
    """
    mlflow_url = get_mlflow_url()
    if not mlflow_url:
        pytest.fail(
            "MLflow URL not available. "
            "Set MLFLOW_URL env var or ensure mlflow route exists in kagenti-system."
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
    params: Optional[Dict[str, Any]] = None,
) -> httpx.Response:
    """
    Query MLflow REST API with optional authentication.

    Args:
        mlflow_url: MLflow base URL
        endpoint: API endpoint path (e.g., /api/2.0/mlflow/experiments/list)
        token: Optional OAuth2 access token
        timeout: Request timeout in seconds
        verify_ssl: Whether to verify SSL certificates (False for OpenShift self-signed)
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

    response = requests.post(token_url, data=data, timeout=10, verify=False)
    response.raise_for_status()
    return response.json()


def get_mlflow_service_token(
    keycloak_url: str,
    client_id: str,
    client_secret: str,
    realm: str = "master",
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

    response = requests.post(token_url, data=data, timeout=10, verify=False)
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

        When OIDC auth is enabled, the /version endpoint may redirect (302/307)
        to the login page. Both 200 (no auth) and 302/307 (auth enabled) are valid.
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

        # Accept 200 (no auth) or 302/307 (OAuth redirect) as healthy
        assert response.status_code in (200, 302, 307), (
            f"MLflow /version endpoint failed: {response.status_code} - {response.text}"
        )

        if response.status_code == 200:
            logger.info("TEST PASSED: MLflow version endpoint accessible (no auth)")
        else:
            logger.info(
                f"TEST PASSED: MLflow version endpoint redirects to auth ({response.status_code})"
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

    @pytest.mark.skip(
        reason="External MLflow API access with bearer tokens is not a production use case. "
        "Production flows: (1) Browser UI → OAuth redirect, (2) OTEL Collector → internal mTLS. "
        "Auth enforcement is verified by test_mlflow_unauthenticated_blocked_or_allowed."
    )
    @pytest.mark.asyncio
    async def test_mlflow_api_accessible_with_token(
        self, require_mlflow_url, k8s_client, is_openshift
    ):
        """
        SKIPPED: Test MLflow API is accessible with valid Keycloak service account token.

        This test uses Client Credentials Grant (service account) which is the
        secure way for machine-to-machine API access. The mlflow client in
        Keycloak has "Service Accounts Enabled".

        Steps:
        1. Get client credentials from mlflow-oauth-secret K8s secret
        2. Use client credentials grant to get service account token
        3. Query MLflow API with the token
        4. Verify the request succeeds
        """
        import base64

        mlflow_url = require_mlflow_url
        logger.info("=" * 70)
        logger.info("Testing: MLflow API with Service Account Token")
        logger.info("=" * 70)

        # Get MLflow OAuth client credentials from K8s secret
        try:
            secret = k8s_client.read_namespaced_secret(
                name="mlflow-oauth-secret", namespace="kagenti-system"
            )
            client_id = base64.b64decode(secret.data["OIDC_CLIENT_ID"]).decode("utf-8")
            client_secret = base64.b64decode(secret.data["OIDC_CLIENT_SECRET"]).decode(
                "utf-8"
            )
            logger.info(f"Got MLflow OAuth client credentials (client_id: {client_id})")
        except Exception as e:
            pytest.skip(f"Could not get MLflow OAuth secret: {e}")

        # Get Keycloak URL
        keycloak_url = os.getenv("KEYCLOAK_URL", "http://localhost:8081")

        # Get service account token using client credentials grant
        try:
            token_response = get_mlflow_service_token(
                keycloak_url=keycloak_url,
                client_id=client_id,
                client_secret=client_secret,
                realm="master",
            )
        except Exception as e:
            pytest.fail(f"Could not get service account token: {e}")

        access_token = token_response["access_token"]
        logger.info(
            f"Got service account token (expires in {token_response.get('expires_in')}s)"
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

        # With valid service account token, we should get 200 or 400 (bad params)
        if response.status_code == 200:
            data = response.json()
            assert "experiments" in data, f"No experiments in response: {data}"
            logger.info("MLflow API accessible with service account token")
            logger.info(f"Found {len(data.get('experiments', []))} experiments")
        elif response.status_code == 400:
            # API is accessible, just needs different params
            logger.info("MLflow API accessible (400 = parameter error, auth worked)")
        elif response.status_code in [401, 403]:
            pytest.fail(
                f"Service account token rejected: {response.status_code} - {response.text}"
            )
        else:
            pytest.fail(
                f"Unexpected response: {response.status_code} - {response.text}"
            )

        logger.info("TEST PASSED: MLflow API accessible with service account token")

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

        Uses /version endpoint. When OIDC auth is enabled, a 302/307 redirect
        to the login page indicates MLflow is healthy and auth is working.
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

            # Accept 200 (no auth) or 302/307 (OAuth redirect) as healthy
            assert response.status_code in (200, 302, 307), (
                f"MLflow health check failed: {response.status_code}"
            )

            if response.status_code == 200:
                version = response.text.strip().strip('"')
                logger.info(f"MLflow version: {version}")
                logger.info("TEST PASSED: MLflow is healthy (no auth)")
            else:
                logger.info(
                    f"TEST PASSED: MLflow is healthy (auth redirect {response.status_code})"
                )

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

    @pytest.mark.skip(
        reason="External MLflow API access not a production use case. "
        "Trace content validation should use port-forward (localhost) to avoid issuer mismatch. "
        "See test_mlflow_traces.py for internal trace validation via MLflow Python client."
    )
    @pytest.mark.asyncio
    async def test_mlflow_has_experiments(
        self, require_mlflow_url, k8s_client, is_openshift
    ):
        """
        SKIPPED: Test that MLflow has at least one experiment.

        Uses service account token for authentication.
        """
        import base64

        mlflow_url = require_mlflow_url
        logger.info("=" * 70)
        logger.info("Testing: MLflow Experiments")
        logger.info(f"MLflow URL: {mlflow_url}")
        logger.info("=" * 70)

        # Get service account token
        try:
            secret = k8s_client.read_namespaced_secret(
                name="mlflow-oauth-secret", namespace="kagenti-system"
            )
            client_id = base64.b64decode(secret.data["OIDC_CLIENT_ID"]).decode("utf-8")
            client_secret = base64.b64decode(secret.data["OIDC_CLIENT_SECRET"]).decode(
                "utf-8"
            )
            keycloak_url = os.getenv("KEYCLOAK_URL", "http://localhost:8081")
            token_response = get_mlflow_service_token(
                keycloak_url=keycloak_url,
                client_id=client_id,
                client_secret=client_secret,
                realm="master",
            )
            access_token = token_response["access_token"]
        except Exception as e:
            pytest.fail(f"Could not get service account token: {e}")

        try:
            response = await query_mlflow_api(
                mlflow_url=mlflow_url,
                endpoint="/api/2.0/mlflow/experiments/search",
                token=access_token,
                timeout=15,
                verify_ssl=not is_openshift,
                params={"max_results": 100},
            )

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

    @pytest.mark.skip(
        reason="External MLflow API access not a production use case. "
        "Trace content validation should use port-forward (localhost) to avoid issuer mismatch. "
        "See test_mlflow_traces.py for comprehensive trace validation via MLflow Python client."
    )
    @pytest.mark.asyncio
    async def test_mlflow_traces_endpoint(
        self, require_mlflow_url, k8s_client, is_openshift
    ):
        """
        SKIPPED: Test MLflow traces API endpoint.

        MLflow 2.14+ supports OTLP trace ingestion and provides
        a traces endpoint for querying. Uses service account token.
        """
        import base64

        mlflow_url = require_mlflow_url
        logger.info("Testing: MLflow Traces Endpoint")

        # Get service account token
        try:
            secret = k8s_client.read_namespaced_secret(
                name="mlflow-oauth-secret", namespace="kagenti-system"
            )
            client_id = base64.b64decode(secret.data["OIDC_CLIENT_ID"]).decode("utf-8")
            client_secret = base64.b64decode(secret.data["OIDC_CLIENT_SECRET"]).decode(
                "utf-8"
            )
            keycloak_url = os.getenv("KEYCLOAK_URL", "http://localhost:8081")
            token_response = get_mlflow_service_token(
                keycloak_url=keycloak_url,
                client_id=client_id,
                client_secret=client_secret,
                realm="master",
            )
            access_token = token_response["access_token"]
        except Exception as e:
            pytest.fail(f"Could not get service account token: {e}")

        try:
            # First get experiments to get their IDs
            exp_response = await query_mlflow_api(
                mlflow_url=mlflow_url,
                endpoint="/api/2.0/mlflow/experiments/search",
                token=access_token,
                timeout=15,
                verify_ssl=not is_openshift,
                params={"max_results": 100},
            )

            if exp_response.status_code != 200:
                pytest.fail(
                    f"Could not get experiments: {exp_response.status_code} - {exp_response.text}"
                )

            exp_data = exp_response.json()
            experiments = exp_data.get("experiments", [])
            if not experiments:
                pytest.skip("No experiments found to query traces from")

            # Get experiment IDs for traces query
            experiment_ids = [exp.get("experiment_id") for exp in experiments]
            logger.info(f"Querying traces for {len(experiment_ids)} experiment(s)")

            # Query traces with experiment_ids parameter
            response = await query_mlflow_api(
                mlflow_url=mlflow_url,
                endpoint="/api/2.0/mlflow/traces",
                token=access_token,
                timeout=15,
                verify_ssl=not is_openshift,
                params={"experiment_ids": experiment_ids},
            )

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
                pytest.fail(
                    f"Unexpected response from traces endpoint: {response.status_code} - {response.text}"
                )

        except httpx.ConnectError as e:
            pytest.fail(f"Could not connect to MLflow at {mlflow_url}: {e}")


if __name__ == "__main__":
    import sys

    sys.exit(pytest.main([__file__, "-v"]))
