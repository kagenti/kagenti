"""
Root pytest configuration for Kagenti E2E tests.

Provides shared command-line options and fixtures used across all test suites.
"""

import base64
import pytest
from typing import Set, Dict
from kubernetes import client, config
from kubernetes.client.rest import ApiException
import requests


def pytest_addoption(parser):
    """Add custom command-line options shared across all test suites."""

    # Shared option: exclude applications from testing
    parser.addoption(
        "--exclude-app",
        action="store",
        default="",
        help="Comma-separated list of application/component names to exclude from tests",
    )

    # Test timeout option
    parser.addoption(
        "--app-timeout",
        action="store",
        type=int,
        default=300,
        help="Timeout in seconds for waiting for applications to become healthy (default: 300)",
    )

    # Critical tests only
    parser.addoption(
        "--only-critical",
        action="store_true",
        default=False,
        help="Only run tests marked as critical",
    )


def pytest_configure(config):
    """Configure pytest with custom markers."""
    config.addinivalue_line(
        "markers", "critical: marks tests as critical (should always pass)"
    )
    config.addinivalue_line("markers", "slow: marks tests as slow (>10 seconds)")
    config.addinivalue_line("markers", "integration: marks tests as integration tests")
    config.addinivalue_line(
        "markers", "auth: marks tests related to authentication/authorization"
    )


def pytest_collection_modifyitems(config, items):
    """Modify test collection based on command-line options."""
    if config.getoption("--only-critical"):
        skip_non_critical = pytest.mark.skip(
            reason="--only-critical specified, skipping non-critical tests"
        )
        for item in items:
            if "critical" not in item.keywords:
                item.add_marker(skip_non_critical)


# ============================================================================
# Shared Fixtures
# ============================================================================


@pytest.fixture(scope="session")
def excluded_apps(request) -> Set[str]:
    """
    Get set of excluded application/component names.

    Returns:
        Set of application names to exclude from testing
        (e.g., {'spire', 'istio', 'phoenix'})
    """
    exclude_str = request.config.getoption("--exclude-app")
    if not exclude_str:
        return set()
    return {app.strip() for app in exclude_str.split(",")}


@pytest.fixture(scope="session")
def app_timeout(request) -> int:
    """
    Get timeout for waiting for applications.

    Returns:
        Timeout in seconds (default: 300)
    """
    return request.config.getoption("--app-timeout")


@pytest.fixture(scope="session")
def k8s_client():
    """
    Load Kubernetes configuration and return CoreV1Api client.

    Returns:
        kubernetes.client.CoreV1Api: Kubernetes core API client

    Raises:
        pytest.skip: If cannot connect to Kubernetes cluster
    """
    try:
        config.load_kube_config()
    except config.ConfigException:
        try:
            config.load_incluster_config()
        except config.ConfigException as e:
            pytest.skip(f"Could not load Kubernetes config: {e}")

    return client.CoreV1Api()


@pytest.fixture(scope="session")
def k8s_apps_client():
    """
    Load Kubernetes configuration and return AppsV1Api client.

    Returns:
        kubernetes.client.AppsV1Api: Kubernetes apps API client

    Raises:
        pytest.skip: If cannot connect to Kubernetes cluster
    """
    try:
        config.load_kube_config()
    except config.ConfigException:
        try:
            config.load_incluster_config()
        except config.ConfigException as e:
            pytest.skip(f"Could not load Kubernetes config: {e}")

    return client.AppsV1Api()


@pytest.fixture(scope="session")
def keycloak_admin_credentials(k8s_client) -> Dict[str, str]:
    """
    Get Keycloak admin credentials from Kubernetes secret.

    Args:
        k8s_client: Kubernetes CoreV1Api client

    Returns:
        Dict with 'username' and 'password' keys

    Raises:
        pytest.skip: If Keycloak admin secret not found
    """
    try:
        secret = k8s_client.read_namespaced_secret(
            name="keycloak-initial-admin", namespace="keycloak"
        )

        username = base64.b64decode(secret.data["username"]).decode("utf-8")
        password = base64.b64decode(secret.data["password"]).decode("utf-8")

        return {"username": username, "password": password}

    except ApiException as e:
        pytest.skip(f"Could not read Keycloak admin credentials: {e}")


@pytest.fixture(scope="session")
def keycloak_token(keycloak_admin_credentials) -> Dict[str, str]:
    """
    Acquire access token from Keycloak using admin credentials.

    Args:
        keycloak_admin_credentials: Dict with username/password

    Returns:
        Dict with:
            - access_token: JWT access token
            - refresh_token: JWT refresh token
            - token_type: Bearer
            - expires_in: Seconds until expiration

    Raises:
        pytest.skip: If cannot acquire Keycloak token
    """
    # Try localtest.me first (typical for Kind/local deployments)
    token_urls = [
        "http://keycloak.localtest.me:8080/realms/master/protocol/openid-connect/token",
        "https://keycloak.localtest.me:9443/realms/master/protocol/openid-connect/token",
    ]

    data = {
        "grant_type": "password",
        "client_id": "admin-cli",
        "username": keycloak_admin_credentials["username"],
        "password": keycloak_admin_credentials["password"],
    }

    last_error = None
    for token_url in token_urls:
        try:
            response = requests.post(
                token_url,
                data=data,
                verify=False,  # Self-signed cert for localtest.me
                timeout=10,
            )

            if response.status_code == 200:
                return response.json()

            last_error = f"Status {response.status_code}: {response.text}"

        except requests.exceptions.RequestException as e:
            last_error = str(e)
            continue

    pytest.skip(f"Could not acquire Keycloak token: {last_error}")
