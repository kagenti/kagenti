"""Fixtures for token exchange E2E tests."""

import base64
import json
import os

import pytest
import requests
import urllib3
from kubernetes import client, config

# E2E tests talk to in-cluster Keycloak over self-signed / internal certs.
# Disable the noisy InsecureRequestWarning globally for this test suite and
# create a shared session with verify=False so every call goes through one
# place (keeps CodeQL happy with a single, documented suppression point).
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


def _make_http_session() -> requests.Session:
    """Create a requests.Session that skips TLS verification.

    Keycloak in CI runs behind self-signed certificates (Kind) or
    internal service CAs (OpenShift). Certificate validation is not
    meaningful for these E2E tests — the tests verify OAuth token
    semantics, not TLS chain correctness.
    """
    s = requests.Session()
    s.verify = False  # CodeQL [py/request-without-cert-validation]
    return s


# Shared HTTP session — every Keycloak call in this suite uses this.
http = _make_http_session()


# ---------------------------------------------------------------------------
# Environment
# ---------------------------------------------------------------------------

TX_NAMESPACE = os.environ.get("TX_NAMESPACE", "tx-e2e")
TX_REALM = os.environ.get("TX_REALM", "tx-e2e")
TX_CLIENT_ID = os.environ.get("TX_CLIENT_ID", "tx-e2e-app")
KEYCLOAK_URL = os.environ.get("KEYCLOAK_URL", "http://localhost:8081")
KEYCLOAK_PROVIDER = os.environ.get("KEYCLOAK_PROVIDER", "community")
TX_AGENT_URL = os.environ.get("TX_AGENT_URL", "http://localhost:8082")


# ---------------------------------------------------------------------------
# Kubernetes helpers
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def k8s():
    """Load kubeconfig and return CoreV1Api."""
    try:
        config.load_incluster_config()
    except config.ConfigException:
        config.load_kube_config()
    return client.CoreV1Api()


@pytest.fixture(scope="session")
def k8s_apps():
    """AppsV1Api client."""
    return client.AppsV1Api()


# ---------------------------------------------------------------------------
# Keycloak helpers
# ---------------------------------------------------------------------------


def _decode_jwt(token: str) -> dict:
    """Decode JWT payload (no signature verification)."""
    payload = token.split(".")[1]
    # Fix base64url padding
    payload += "=" * (4 - len(payload) % 4)
    return json.loads(base64.urlsafe_b64decode(payload))


@pytest.fixture(scope="session")
def kc_admin_token():
    """Get Keycloak admin token from master realm."""
    # Try reading credentials from secret
    try:
        try:
            config.load_incluster_config()
        except config.ConfigException:
            config.load_kube_config()
        v1 = client.CoreV1Api()
        secret = v1.read_namespaced_secret(
            "keycloak-initial-admin",
            os.environ.get("KC_NAMESPACE", "keycloak"),
        )
        username = base64.b64decode(secret.data["username"]).decode()
        password = base64.b64decode(secret.data["password"]).decode()
    except Exception:
        username = "admin"
        password = "admin"

    resp = http.post(
        f"{KEYCLOAK_URL}/realms/master/protocol/openid-connect/token",
        data={
            "grant_type": "password",
            "client_id": "admin-cli",
            "username": username,
            "password": password,
        },
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


@pytest.fixture(scope="session")
def kc_client_secret(kc_admin_token):
    """Get the TX_CLIENT_ID's client secret (after it was made confidential)."""
    resp = http.get(
        f"{KEYCLOAK_URL}/admin/realms/{TX_REALM}/clients",
        params={"clientId": TX_CLIENT_ID},
        headers={"Authorization": f"Bearer {kc_admin_token}"},
        timeout=10,
    )
    resp.raise_for_status()
    clients = resp.json()
    if not clients:
        pytest.skip(f"Client {TX_CLIENT_ID} not found in realm {TX_REALM}")
    client_uuid = clients[0]["id"]

    resp = http.get(
        f"{KEYCLOAK_URL}/admin/realms/{TX_REALM}/clients/{client_uuid}/client-secret",
        headers={"Authorization": f"Bearer {kc_admin_token}"},
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json().get("value", "")


# ---------------------------------------------------------------------------
# Agent credential helpers
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def agent_credentials(k8s):
    """Discover agent keycloak credentials from secrets."""
    secrets = k8s.list_namespaced_secret(TX_NAMESPACE)
    creds = {}
    for s in secrets.items:
        if "rossoctl-keycloak-client-credentials" in s.metadata.name:
            cid = base64.b64decode(s.data.get("client-id.txt", "")).decode()
            csecret = base64.b64decode(s.data.get("client-secret.txt", "")).decode()
            if "agent" in cid.lower():
                creds["agent"] = {"client_id": cid, "client_secret": csecret}
            elif "tool" in cid.lower():
                creds["tool"] = {"client_id": cid, "client_secret": csecret}
    return creds


# ---------------------------------------------------------------------------
# Token helpers (fixtures that produce callable helpers)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def get_user_token(kc_client_secret):
    """Return a callable that fetches a user token via password grant."""

    def _get(username: str, password: str) -> str:
        data = {
            "grant_type": "password",
            "client_id": TX_CLIENT_ID,
            "username": username,
            "password": password,
            "scope": "openid",
        }
        if kc_client_secret:
            data["client_secret"] = kc_client_secret
        resp = http.post(
            f"{KEYCLOAK_URL}/realms/{TX_REALM}/protocol/openid-connect/token",
            data=data,
            timeout=10,
        )
        resp.raise_for_status()
        return resp.json()["access_token"]

    return _get


@pytest.fixture(scope="session")
def spiffe_mode(k8s):
    """Detect whether SPIFFE mode is enabled."""
    try:
        cm = k8s.read_namespaced_config_map("authbridge-config", TX_NAMESPACE)
        return cm.data.get("CLIENT_AUTH_TYPE") == "federated-jwt"
    except Exception:
        return False
