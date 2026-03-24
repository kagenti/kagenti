"""
Root pytest configuration for Kagenti tests.

Registers custom markers and provides shared fixtures.
"""

import base64
import os
from typing import Dict, Optional

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
def k8s_batch_client():
    """
    Load Kubernetes configuration and return BatchV1Api client.

    Returns:
        kubernetes.client.BatchV1Api: Kubernetes batch API client for Jobs

    Raises:
        pytest.fail: If cannot connect to Kubernetes cluster
    """
    try:
        config.load_kube_config()
    except config.ConfigException:
        try:
            config.load_incluster_config()
        except config.ConfigException as e:
            pytest.fail(f"Could not load Kubernetes config: {e}")

    return client.BatchV1Api()


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

    Environment Variables:
        KEYCLOAK_URL: Keycloak endpoint URL (default: http://localhost:8081)
            For OpenShift: https://keycloak-keycloak.apps.cluster.example.com
        KEYCLOAK_VERIFY_SSL: Set to "false" to disable SSL verification (default: true)
        KEYCLOAK_CA_BUNDLE: Path to CA certificate bundle for SSL verification

    Args:
        keycloak_admin_credentials: Dict with username/password

    Returns:
        Dict with:
            - access_token: JWT access token
            - refresh_token: JWT refresh token
            - token_type: Bearer
            - expires_in: Seconds until expiration

    Raises:
        pytest.fail: If cannot acquire Keycloak token
    """
    # Use KEYCLOAK_URL env var, or fall back to port-forwarded Keycloak for Kind
    keycloak_base_url = os.environ.get("KEYCLOAK_URL", "http://localhost:8081")
    token_url = f"{keycloak_base_url}/realms/master/protocol/openid-connect/token"

    # SSL verification: True by default, can be disabled via env var for self-signed certs
    # Can also set KEYCLOAK_CA_BUNDLE to path of CA certificate bundle
    verify_ssl: bool | str = True
    if os.environ.get("KEYCLOAK_VERIFY_SSL", "true").lower() == "false":
        verify_ssl = False
    elif os.environ.get("KEYCLOAK_CA_BUNDLE"):
        verify_ssl = os.environ["KEYCLOAK_CA_BUNDLE"]

    data = {
        "grant_type": "password",
        "client_id": "admin-cli",
        "username": keycloak_admin_credentials["username"],
        "password": keycloak_admin_credentials["password"],
    }

    try:
        response = requests.post(token_url, data=data, timeout=10, verify=verify_ssl)

        if response.status_code == 200:
            return response.json()

        pytest.fail(
            f"Could not acquire Keycloak token. Status {response.status_code}: {response.text}\n"
            f"Keycloak URL: {keycloak_base_url}"
        )

    except requests.exceptions.RequestException as e:
        pytest.fail(
            f"Could not acquire Keycloak token: {e}\n"
            f"Keycloak URL: {keycloak_base_url}\n"
            f"Hint: Set KEYCLOAK_URL env var to your Keycloak endpoint"
        )


def _keycloak_ssl_verify() -> "bool | str":
    """Return the ``verify`` parameter for requests to the Keycloak endpoint.

    Prefers an explicit CA bundle, then fetches the cluster root CA from
    kube-root-ca.crt.  Falls back to the default system CA store.
    Never returns ``False``.
    """
    if os.environ.get("KEYCLOAK_CA_BUNDLE"):
        return os.environ["KEYCLOAK_CA_BUNDLE"]
    if os.environ.get("KEYCLOAK_VERIFY_SSL", "true").lower() == "false":
        from kagenti.tests.e2e.conftest import _fetch_openshift_ingress_ca

        ca_path = _fetch_openshift_ingress_ca()
        if ca_path:
            return ca_path
    return True


@pytest.fixture(scope="session")
def keycloak_agent_token(k8s_client) -> Optional[str]:
    """
    Acquire a Bearer token from the kagenti realm for authenticating
    to agents via AuthBridge.

    Reads credentials from the ``kagenti-test-user`` secret (created/
    updated by ``87-setup-test-credentials.sh`` or the agent-oauth-secret
    Helm Job) and acquires a token via Direct Access Grant.

    Returns:
        Access token string, or None if the secret is absent.
    """
    import time

    secret = None
    for attempt in range(12):
        try:
            secret = k8s_client.read_namespaced_secret(
                name="kagenti-test-user", namespace="keycloak"
            )
            break
        except ApiException:
            if attempt < 11:
                time.sleep(5)

    if secret is None:
        print(
            "\n[keycloak_agent_token] kagenti-test-user secret not found "
            "in keycloak namespace after 60s — agent auth will be skipped"
        )
        return None

    username = base64.b64decode(secret.data["username"]).decode("utf-8")
    password = base64.b64decode(secret.data["password"]).decode("utf-8")
    realm = base64.b64decode(secret.data["realm"]).decode("utf-8")

    keycloak_base_url = os.environ.get("KEYCLOAK_URL", "http://localhost:8081")
    token_url = f"{keycloak_base_url}/realms/{realm}/protocol/openid-connect/token"
    verify_ssl = _keycloak_ssl_verify()

    try:
        response = requests.post(
            token_url,
            data={
                "grant_type": "password",
                "client_id": "admin-cli",
                "username": username,
                "password": password,
            },
            timeout=10,
            verify=verify_ssl,
        )
        if response.status_code == 200:
            token = response.json()["access_token"]
            print(
                f"\n[keycloak_agent_token] Acquired token for realm={realm} "
                f"user={username} (token length={len(token)})"
            )
            return token
        print(
            f"\n[keycloak_agent_token] Token request failed: "
            f"HTTP {response.status_code} — {response.text[:200]}"
        )
    except requests.exceptions.RequestException as e:
        print(f"\n[keycloak_agent_token] Token request error: {e}")

    return None
