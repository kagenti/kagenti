"""
Root pytest configuration for Kagenti tests.

Registers custom markers and provides shared fixtures.
"""

import base64
from typing import Dict

import pytest
import requests
from kubernetes import client, config
from kubernetes.client.rest import ApiException


def pytest_configure(config):
    """Register custom markers to avoid 'Unknown mark' warnings."""
    config.addinivalue_line(
        "markers",
        "requires_features(features): skip test if required features are not enabled "
        "(auto-detected from KAGENTI_CONFIG_FILE)",
    )
    config.addinivalue_line(
        "markers",
        "critical: marks tests as critical (should always pass)",
    )


# ============================================================================
# Shared Fixtures
# ============================================================================


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

    This fixture uses the port-forwarded Keycloak endpoint (localhost:8081)
    which is set up by the test infrastructure (85-start-port-forward.sh).

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
    # Use port-forwarded Keycloak (set up by 85-start-port-forward.sh)
    token_url = "http://localhost:8081/realms/master/protocol/openid-connect/token"

    data = {
        "grant_type": "password",
        "client_id": "admin-cli",
        "username": keycloak_admin_credentials["username"],
        "password": keycloak_admin_credentials["password"],
    }

    try:
        response = requests.post(token_url, data=data, timeout=10)

        if response.status_code == 200:
            return response.json()

        pytest.skip(
            f"Could not acquire Keycloak token. Status {response.status_code}: {response.text}"
        )

    except requests.exceptions.RequestException as e:
        pytest.skip(f"Could not acquire Keycloak token: {e}")
