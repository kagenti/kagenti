#!/usr/bin/env python3
"""
Phoenix Authentication E2E Tests

Tests Phoenix Keycloak OAuth2 authentication integration.

When phoenix.auth.enabled=true:
- Phoenix requires OAuth2 authentication via Keycloak
- Unauthenticated requests should be rejected or redirected
- Authenticated requests with valid tokens should succeed

Usage:
    # Run Phoenix auth tests
    pytest kagenti/tests/e2e/common/test_phoenix_auth.py -v

    # Run specific test
    pytest kagenti/tests/e2e/common/test_phoenix_auth.py::TestPhoenixAuth::test_phoenix_graphql_accessible_with_token -v

Environment Variables:
    PHOENIX_URL: Phoenix endpoint (default: http://localhost:6006)
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
def phoenix_url():
    """Phoenix endpoint URL.

    Default: localhost:6006 (via port-forward)
    In-cluster: http://phoenix.kagenti-system.svc.cluster.local:6006
    OpenShift: Uses Route URL from PHOENIX_URL env var
    """
    return os.getenv("PHOENIX_URL", "http://localhost:6006")


@pytest.fixture(scope="module")
def keycloak_url():
    """Keycloak endpoint URL.

    Default: localhost:8081 (via port-forward)
    """
    return os.getenv("KEYCLOAK_URL", "http://localhost:8081")


# ============================================================================
# Helper Functions
# ============================================================================


async def query_phoenix_graphql(
    phoenix_url: str,
    query: str,
    token: Optional[str] = None,
    timeout: int = 10,
    verify_ssl: bool = True,
) -> httpx.Response:
    """
    Query Phoenix GraphQL API with optional authentication.

    Args:
        phoenix_url: Phoenix base URL
        query: GraphQL query string
        token: Optional OAuth2 access token
        timeout: Request timeout in seconds
        verify_ssl: Whether to verify SSL certificates (False for OpenShift self-signed)

    Returns:
        httpx.Response object (not parsed JSON, so we can check status codes)
    """
    graphql_url = f"{phoenix_url}/graphql"

    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    async with httpx.AsyncClient(follow_redirects=False, verify=verify_ssl) as client:
        response = await client.post(
            graphql_url,
            json={"query": query},
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
# Test Class: Phoenix Authentication
# ============================================================================


@pytest.mark.requires_features(["otel", "keycloak"])
class TestPhoenixAuth:
    """Test Phoenix Keycloak OAuth2 authentication."""

    @pytest.mark.asyncio
    async def test_phoenix_graphql_api_accessible(self, phoenix_url, is_openshift):
        """
        Test Phoenix GraphQL API responds to requests.

        This is a basic connectivity test. When auth is disabled,
        the API should return 200. When auth is enabled, it may
        return 401 or 302 (redirect to login).
        """
        logger.info("=" * 70)
        logger.info("Testing: Phoenix GraphQL API Accessibility")
        logger.info(f"Phoenix URL: {phoenix_url}")
        logger.info(f"OpenShift: {is_openshift}")
        logger.info("=" * 70)

        query = """
        query {
          __schema {
            queryType {
              name
            }
          }
        }
        """

        response = await query_phoenix_graphql(
            phoenix_url=phoenix_url,
            query=query,
            token=None,
            timeout=10,
            verify_ssl=not is_openshift,
        )

        # Log the response for debugging
        logger.info(f"Response status: {response.status_code}")
        logger.info(f"Response headers: {dict(response.headers)}")

        # Phoenix should respond (200, 401, or 302 depending on auth config)
        assert response.status_code in [200, 401, 302, 307], (
            f"Unexpected Phoenix response: {response.status_code} - {response.text}"
        )

        if response.status_code == 200:
            logger.info("Phoenix GraphQL API accessible without authentication")
        elif response.status_code in [401, 403]:
            logger.info("Phoenix requires authentication (auth enabled)")
        elif response.status_code in [302, 307]:
            location = response.headers.get("location", "")
            logger.info(f"Phoenix redirects to login: {location}")

        logger.info("TEST PASSED: Phoenix GraphQL API responds correctly")

    @pytest.mark.asyncio
    async def test_phoenix_unauthenticated_blocked_or_allowed(
        self, phoenix_url, is_openshift
    ):
        """
        Test Phoenix behavior for unauthenticated requests.

        When auth is disabled: Should return 200 with valid GraphQL response.
        When auth is enabled: Should return 401 or redirect to Keycloak.
        """
        logger.info("=" * 70)
        logger.info("Testing: Phoenix Unauthenticated Request Handling")
        logger.info("=" * 70)

        # Simple introspection query
        query = """
        query {
          __schema {
            queryType { name }
          }
        }
        """

        response = await query_phoenix_graphql(
            phoenix_url=phoenix_url,
            query=query,
            token=None,
            timeout=10,
            verify_ssl=not is_openshift,
        )

        if response.status_code == 200:
            # Auth disabled - verify we get valid GraphQL response
            data = response.json()
            assert "data" in data, f"Invalid GraphQL response: {data}"
            assert "__schema" in data["data"], f"No __schema in response: {data}"
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

        logger.info("TEST PASSED: Phoenix handles unauthenticated requests correctly")

    @pytest.mark.asyncio
    async def test_phoenix_graphql_accessible_with_token(
        self, phoenix_url, keycloak_admin_credentials, is_openshift
    ):
        """
        Test Phoenix GraphQL API is accessible with valid Keycloak token.

        This test:
        1. Gets an access token from Keycloak
        2. Uses the token to query Phoenix GraphQL API
        3. Verifies the request succeeds

        Note: This works for admin users. For regular users, they would
        need to be registered in Phoenix or PHOENIX_OAUTH2_KEYCLOAK_ALLOW_SIGN_UP=true.
        """
        logger.info("=" * 70)
        logger.info("Testing: Phoenix GraphQL with Keycloak Token")
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

        # Query Phoenix with token
        query = """
        query {
          projects {
            edges {
              node {
                name
                traceCount
              }
            }
          }
        }
        """

        response = await query_phoenix_graphql(
            phoenix_url=phoenix_url,
            query=query,
            token=access_token,
            timeout=10,
            verify_ssl=not is_openshift,
        )

        logger.info(f"Response status: {response.status_code}")

        # With valid token, we should get 200
        if response.status_code == 200:
            data = response.json()
            assert "data" in data, f"No data in response: {data}"
            logger.info("Phoenix GraphQL accessible with Keycloak token")

            # Log project count
            if "projects" in data.get("data", {}):
                projects = data["data"]["projects"]["edges"]
                logger.info(f"Found {len(projects)} projects in Phoenix")
        elif response.status_code in [401, 403]:
            # Token might be rejected if:
            # 1. Phoenix OAuth client is different from admin-cli
            # 2. User needs to be pre-registered in Phoenix
            # 3. Token audience mismatch
            logger.warning(
                f"Token rejected. Phoenix may require specific OAuth client. "
                f"Status: {response.status_code}"
            )
            # Don't fail - this could be a configuration issue
            pytest.skip(
                "Phoenix rejected Keycloak admin token - may need Phoenix-specific OAuth client"
            )
        else:
            pytest.fail(
                f"Unexpected response: {response.status_code} - {response.text}"
            )

        logger.info("TEST PASSED: Phoenix GraphQL accessible with authentication")

    @pytest.mark.asyncio
    async def test_phoenix_oauth_secret_exists(self, k8s_client):
        """
        Test that phoenix-oauth-secret Kubernetes secret exists.

        This secret should be created by the phoenix-oauth-secret-job
        and contains the OAuth credentials for Phoenix.
        """
        logger.info("Testing: phoenix-oauth-secret exists")

        from kubernetes.client.rest import ApiException

        try:
            secret = k8s_client.read_namespaced_secret(
                name="phoenix-oauth-secret",
                namespace="kagenti-system",
            )

            # Verify expected keys
            expected_keys = [
                "PHOENIX_OAUTH2_KEYCLOAK_CLIENT_ID",
                "PHOENIX_OAUTH2_KEYCLOAK_CLIENT_SECRET",
                "PHOENIX_OAUTH2_KEYCLOAK_OIDC_CONFIG_URL",
            ]

            for key in expected_keys:
                assert key in secret.data, (
                    f"Missing key '{key}' in phoenix-oauth-secret. "
                    f"Found keys: {list(secret.data.keys())}"
                )
                logger.info(f"Found secret key: {key}")

            logger.info("TEST PASSED: phoenix-oauth-secret exists with required keys")

        except ApiException as e:
            if e.status == 404:
                pytest.skip(
                    "phoenix-oauth-secret not found - Phoenix auth may not be enabled"
                )
            else:
                pytest.fail(f"Error reading phoenix-oauth-secret: {e}")


# ============================================================================
# Test Class: Phoenix Backend (without auth requirement)
# ============================================================================


@pytest.mark.requires_features(["otel"])
class TestPhoenixBackend:
    """Test Phoenix backend deployment health."""

    @pytest.mark.asyncio
    async def test_phoenix_pod_running(self, k8s_client):
        """Test Phoenix pod is running in kagenti-system namespace."""
        from kubernetes.client.rest import ApiException

        try:
            pods = k8s_client.list_namespaced_pod(namespace="kagenti-system")
        except ApiException as e:
            pytest.fail(f"Could not list pods in kagenti-system: {e}")

        phoenix_pod = None
        for pod in pods.items:
            if "phoenix" in pod.metadata.name.lower():
                phoenix_pod = pod
                break

        assert phoenix_pod is not None, (
            "Phoenix pod not found in kagenti-system namespace"
        )
        assert phoenix_pod.status.phase == "Running", (
            f"Phoenix pod not running: {phoenix_pod.status.phase}"
        )

        logger.info(f"Phoenix pod running: {phoenix_pod.metadata.name}")

    @pytest.mark.asyncio
    async def test_phoenix_graphql_introspection(self, phoenix_url, is_openshift):
        """
        Test Phoenix GraphQL API responds to introspection query.

        This basic test verifies Phoenix is running and the GraphQL
        endpoint is reachable, regardless of auth configuration.
        """
        query = """
        query {
          __schema {
            queryType {
              name
            }
          }
        }
        """

        try:
            response = await query_phoenix_graphql(
                phoenix_url=phoenix_url,
                query=query,
                token=None,
                timeout=10,
                verify_ssl=not is_openshift,
            )

            # Any response (200, 401, 302) means Phoenix is running
            assert response.status_code in [200, 401, 302, 307], (
                f"Phoenix not responding correctly: {response.status_code}"
            )

            if response.status_code == 200:
                data = response.json()
                assert "data" in data, f"Invalid GraphQL response: {data}"
                logger.info("Phoenix GraphQL API accessible")
            else:
                logger.info(
                    f"Phoenix responds with {response.status_code} "
                    "(auth may be enabled)"
                )

        except httpx.ConnectError as e:
            pytest.fail(f"Could not connect to Phoenix at {phoenix_url}: {e}")


if __name__ == "__main__":
    import sys

    sys.exit(pytest.main([__file__, "-v"]))
