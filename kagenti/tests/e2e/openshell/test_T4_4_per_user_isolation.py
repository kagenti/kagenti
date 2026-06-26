"""
Per-User Sandbox Ownership Isolation E2E Tests (Issue #1976, Task C)

Validates that per-user ownership filtering works on a single shared gateway:
- Create stamps openshell.ai/owner from verified identity
- Client-supplied owner label is stripped (anti-spoofing)
- List filtered to caller's sandboxes only
- Get/Delete cross-user → PermissionDenied
- Admin bypasses ownership filter

Prerequisites:
    - One tenant deployed with OIDC enabled (team1 gateway with v0.0.56-rc.2+)
    - Keycloak openshell realm with alice, bob, admin users
    - Both alice and bob can authenticate to team1's gateway (both have team1 audience)

Environment variables:
    OPENSHELL_KEYCLOAK_URL: Keycloak URL (default: auto-detected from svc)
    OPENSHELL_OIDC_ENABLED: Set to "false" to skip (default: true)
    OPENSHELL_GATEWAY_NAMESPACE: Namespace with the shared gateway (default: team1)
"""

import json
import os
import socket
import subprocess
import time

import pytest

from kagenti.tests.e2e.openshell.conftest import find_free_port, kubectl_run

pytestmark = [pytest.mark.openshell, pytest.mark.mvp]


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

GATEWAY_NS = os.getenv("OPENSHELL_GATEWAY_NAMESPACE", "team1")
KEYCLOAK_NS = os.getenv("KEYCLOAK_NS", "keycloak")
OIDC_CLIENT_ID = "openshell-cli"
OIDC_REALM = "openshell"

ALICE = {
    "username": os.getenv("OPENSHELL_ALICE_USERNAME", "alice"),
    "password": os.getenv("OPENSHELL_ALICE_PASSWORD", "alice123"),
}
BOB = {
    "username": os.getenv("OPENSHELL_BOB_USERNAME", "bob"),
    "password": os.getenv("OPENSHELL_BOB_PASSWORD", "bob123"),
}
ADMIN = {
    "username": os.getenv("OPENSHELL_ADMIN_USERNAME", "admin"),
    "password": os.getenv("OPENSHELL_ADMIN_PASSWORD", "admin123"),
}

OWNER_LABEL_KEY = "openshell.ai/owner"
SANDBOX_NAME_ALICE = "test-ownership-alice"
SANDBOX_NAME_BOB = "test-ownership-bob"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _oidc_enabled() -> bool:
    return os.getenv("OPENSHELL_OIDC_ENABLED", "true").lower() != "false"


def _get_keycloak_url() -> str | None:
    explicit = os.getenv("OPENSHELL_KEYCLOAK_URL")
    if explicit:
        return explicit.rstrip("/")

    result = kubectl_run(
        "get",
        "svc",
        "keycloak",
        "-n",
        KEYCLOAK_NS,
        "-o",
        "jsonpath={.spec.clusterIP}",
    )
    if result.returncode != 0:
        return None

    cluster_ip = result.stdout.strip()
    if not cluster_ip:
        return None
    return f"http://{cluster_ip}:8080"


def _get_token(keycloak_url: str, username: str, password: str) -> str | None:
    import urllib.parse
    import urllib.request

    token_url = f"{keycloak_url}/realms/{OIDC_REALM}/protocol/openid-connect/token"
    data = urllib.parse.urlencode(
        {
            "grant_type": "password",
            "client_id": OIDC_CLIENT_ID,
            "username": username,
            "password": password,
        }
    ).encode()

    try:
        req = urllib.request.Request(token_url, data=data)
        with urllib.request.urlopen(req, timeout=10) as resp:
            body = json.loads(resp.read())
            return body.get("access_token")
    except Exception:
        return None


def _decode_jwt_payload(token: str) -> dict:
    import base64

    parts = token.split(".")
    if len(parts) != 3:
        return {}
    payload = parts[1]
    payload += "=" * (4 - len(payload) % 4)
    try:
        return json.loads(base64.urlsafe_b64decode(payload))
    except Exception:
        return {}


class GatewayClient:
    """HTTP client for the OpenShell gateway sandbox API."""

    def __init__(self, base_url: str, token: str):
        self.base_url = base_url
        self.token = token

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
        }

    def _request(
        self, method: str, path: str, body: dict | None = None
    ) -> tuple[int, dict | str]:
        import urllib.request

        url = f"{self.base_url}{path}"
        data = json.dumps(body).encode() if body else None
        req = urllib.request.Request(
            url, data=data, headers=self._headers(), method=method
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                content = resp.read().decode()
                try:
                    return resp.status, json.loads(content)
                except (json.JSONDecodeError, ValueError):
                    return resp.status, content
        except urllib.error.HTTPError as e:
            content = e.read().decode() if e.fp else ""
            try:
                return e.code, json.loads(content)
            except (json.JSONDecodeError, ValueError):
                return e.code, content

    def create_sandbox(
        self, name: str, labels: dict | None = None
    ) -> tuple[int, dict | str]:
        body: dict = {"name": name}
        if labels:
            body["labels"] = labels
        return self._request("POST", "/api/sandboxes", body)

    def list_sandboxes(self) -> tuple[int, dict | str]:
        return self._request("GET", "/api/sandboxes")

    def get_sandbox(self, name: str) -> tuple[int, dict | str]:
        return self._request("GET", f"/api/sandboxes/{name}")

    def delete_sandbox(self, name: str) -> tuple[int, dict | str]:
        return self._request("DELETE", f"/api/sandboxes/{name}")


# ---------------------------------------------------------------------------
# Skip conditions
# ---------------------------------------------------------------------------

skip_no_oidc = pytest.mark.skipif(
    not _oidc_enabled(),
    reason="OIDC disabled (OPENSHELL_OIDC_ENABLED=false)",
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def keycloak_url():
    url = _get_keycloak_url()
    if not url:
        pytest.skip("Keycloak URL not resolvable")
    return url


@pytest.fixture(scope="module")
def alice_token(keycloak_url):
    token = _get_token(keycloak_url, ALICE["username"], ALICE["password"])
    if not token:
        pytest.fail(f"Could not get token for alice from {keycloak_url}")
    return token


@pytest.fixture(scope="module")
def bob_token(keycloak_url):
    token = _get_token(keycloak_url, BOB["username"], BOB["password"])
    if not token:
        pytest.fail(f"Could not get token for bob from {keycloak_url}")
    return token


@pytest.fixture(scope="module")
def admin_token(keycloak_url):
    token = _get_token(keycloak_url, ADMIN["username"], ADMIN["password"])
    if not token:
        pytest.fail(f"Could not get token for admin from {keycloak_url}")
    return token


@pytest.fixture(scope="module")
def gateway_url():
    """Port-forward to the shared gateway and yield the local URL."""
    local_port = find_free_port()
    proc = subprocess.Popen(
        [
            "kubectl",
            "port-forward",
            "svc/openshell-server",
            f"{local_port}:8080",
            "-n",
            GATEWAY_NS,
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    for _ in range(10):
        time.sleep(1)
        try:
            sock = socket.create_connection(("localhost", local_port), timeout=2)
            sock.close()
            break
        except (ConnectionRefusedError, OSError):
            continue
    else:
        proc.terminate()
        proc.wait()
        pytest.skip("Could not port-forward to gateway")

    yield f"http://localhost:{local_port}"

    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()


@pytest.fixture(scope="module")
def alice_client(gateway_url, alice_token) -> GatewayClient:
    return GatewayClient(gateway_url, alice_token)


@pytest.fixture(scope="module")
def bob_client(gateway_url, bob_token) -> GatewayClient:
    return GatewayClient(gateway_url, bob_token)


@pytest.fixture(scope="module")
def admin_client(gateway_url, admin_token) -> GatewayClient:
    return GatewayClient(gateway_url, admin_token)


@pytest.fixture(autouse=True, scope="module")
def cleanup_sandboxes(alice_client, bob_client):
    """Clean up test sandboxes before and after the test module."""
    for name in [SANDBOX_NAME_ALICE, SANDBOX_NAME_BOB]:
        alice_client.delete_sandbox(name)
        bob_client.delete_sandbox(name)
    time.sleep(1)

    yield

    for name in [SANDBOX_NAME_ALICE, SANDBOX_NAME_BOB]:
        alice_client.delete_sandbox(name)
        bob_client.delete_sandbox(name)


# ===========================================================================
# Test: Owner label stamped on create
# ===========================================================================


@skip_no_oidc
class TestOwnershipCreate:
    """Verify CreateSandbox stamps openshell.ai/owner from verified identity."""

    def test_create_stamps_owner_label(self, alice_client, alice_token):
        """Alice creates a sandbox → response contains openshell.ai/owner label."""
        status, body = alice_client.create_sandbox(SANDBOX_NAME_ALICE)
        assert status in (200, 201), f"Create failed: {status} {body}"

        # Extract sandbox metadata from response
        sandbox = body if isinstance(body, dict) else {}
        labels = sandbox.get("metadata", {}).get("labels", {}) or sandbox.get(
            "labels", {}
        )
        assert OWNER_LABEL_KEY in labels, f"Owner label not stamped. Labels: {labels}"

        # Verify the owner matches alice's JWT subject
        alice_sub = _decode_jwt_payload(alice_token).get("sub", "")
        assert labels[OWNER_LABEL_KEY] == alice_sub, (
            f"Owner mismatch: label={labels[OWNER_LABEL_KEY]}, sub={alice_sub}"
        )

    def test_client_supplied_owner_stripped(self, bob_client, bob_token):
        """Client-supplied openshell.ai/owner is overwritten by server."""
        spoofed_owner = "attacker-fake-id"
        status, body = bob_client.create_sandbox(
            SANDBOX_NAME_BOB,
            labels={OWNER_LABEL_KEY: spoofed_owner},
        )
        assert status in (200, 201), f"Create failed: {status} {body}"

        sandbox = body if isinstance(body, dict) else {}
        labels = sandbox.get("metadata", {}).get("labels", {}) or sandbox.get(
            "labels", {}
        )
        assert OWNER_LABEL_KEY in labels
        assert labels[OWNER_LABEL_KEY] != spoofed_owner, (
            "Server did NOT strip client-supplied owner — spoofing possible"
        )

        # Should be bob's actual subject
        bob_sub = _decode_jwt_payload(bob_token).get("sub", "")
        assert labels[OWNER_LABEL_KEY] == bob_sub


# ===========================================================================
# Test: List filtered by ownership
# ===========================================================================


@skip_no_oidc
class TestOwnershipList:
    """Verify ListSandboxes returns only the caller's sandboxes."""

    def test_alice_list_shows_own_sandbox(self, alice_client):
        """Alice's list includes her own sandbox."""
        # Ensure alice's sandbox exists
        alice_client.create_sandbox(SANDBOX_NAME_ALICE)
        time.sleep(1)

        status, body = alice_client.list_sandboxes()
        assert status == 200, f"List failed: {status} {body}"

        sandboxes = body if isinstance(body, list) else body.get("sandboxes", [])
        names = [
            s.get("name") or s.get("metadata", {}).get("name", "") for s in sandboxes
        ]
        assert SANDBOX_NAME_ALICE in names, (
            f"Alice's sandbox not in her list. Got: {names}"
        )

    def test_bob_list_excludes_alice_sandbox(self, alice_client, bob_client):
        """Bob's list does NOT include Alice's sandbox."""
        # Ensure alice's sandbox exists
        alice_client.create_sandbox(SANDBOX_NAME_ALICE)
        time.sleep(1)

        status, body = bob_client.list_sandboxes()
        assert status == 200, f"List failed: {status} {body}"

        sandboxes = body if isinstance(body, list) else body.get("sandboxes", [])
        names = [
            s.get("name") or s.get("metadata", {}).get("name", "") for s in sandboxes
        ]
        assert SANDBOX_NAME_ALICE not in names, (
            f"Bob can see Alice's sandbox — ownership filter broken. Got: {names}"
        )

    def test_bob_list_shows_own_sandbox(self, bob_client):
        """Bob's list includes his own sandbox."""
        bob_client.create_sandbox(SANDBOX_NAME_BOB)
        time.sleep(1)

        status, body = bob_client.list_sandboxes()
        assert status == 200, f"List failed: {status} {body}"

        sandboxes = body if isinstance(body, list) else body.get("sandboxes", [])
        names = [
            s.get("name") or s.get("metadata", {}).get("name", "") for s in sandboxes
        ]
        assert SANDBOX_NAME_BOB in names, f"Bob's sandbox not in his list. Got: {names}"


# ===========================================================================
# Test: Get/Delete cross-user → PermissionDenied
# ===========================================================================


@skip_no_oidc
class TestOwnershipAccessDenied:
    """Verify cross-user get/delete returns PermissionDenied."""

    def test_bob_get_alice_sandbox_denied(self, alice_client, bob_client):
        """Bob cannot Get Alice's sandbox."""
        alice_client.create_sandbox(SANDBOX_NAME_ALICE)
        time.sleep(1)

        status, body = bob_client.get_sandbox(SANDBOX_NAME_ALICE)
        assert status in (403, 404), f"Expected 403/404 but got {status}: {body}"

    def test_bob_delete_alice_sandbox_denied(self, alice_client, bob_client):
        """Bob cannot Delete Alice's sandbox."""
        alice_client.create_sandbox(SANDBOX_NAME_ALICE)
        time.sleep(1)

        status, body = bob_client.delete_sandbox(SANDBOX_NAME_ALICE)
        assert status in (403, 404), f"Expected 403/404 but got {status}: {body}"

    def test_alice_get_bob_sandbox_denied(self, alice_client, bob_client):
        """Alice cannot Get Bob's sandbox."""
        bob_client.create_sandbox(SANDBOX_NAME_BOB)
        time.sleep(1)

        status, body = alice_client.get_sandbox(SANDBOX_NAME_BOB)
        assert status in (403, 404), f"Expected 403/404 but got {status}: {body}"


# ===========================================================================
# Test: Admin bypass
# ===========================================================================


@skip_no_oidc
class TestOwnershipAdminBypass:
    """Verify admin can see and manage all users' sandboxes."""

    def test_admin_list_shows_all_sandboxes(
        self, alice_client, bob_client, admin_client
    ):
        """Admin's list includes both Alice's and Bob's sandboxes."""
        alice_client.create_sandbox(SANDBOX_NAME_ALICE)
        bob_client.create_sandbox(SANDBOX_NAME_BOB)
        time.sleep(1)

        status, body = admin_client.list_sandboxes()
        assert status == 200, f"Admin list failed: {status} {body}"

        sandboxes = body if isinstance(body, list) else body.get("sandboxes", [])
        names = [
            s.get("name") or s.get("metadata", {}).get("name", "") for s in sandboxes
        ]
        assert SANDBOX_NAME_ALICE in names, (
            f"Admin cannot see Alice's sandbox. Got: {names}"
        )
        assert SANDBOX_NAME_BOB in names, (
            f"Admin cannot see Bob's sandbox. Got: {names}"
        )

    def test_admin_get_alice_sandbox(self, alice_client, admin_client):
        """Admin can Get Alice's sandbox."""
        alice_client.create_sandbox(SANDBOX_NAME_ALICE)
        time.sleep(1)

        status, body = admin_client.get_sandbox(SANDBOX_NAME_ALICE)
        assert status == 200, f"Admin get failed: {status} {body}"

    def test_admin_delete_bob_sandbox(self, bob_client, admin_client):
        """Admin can Delete Bob's sandbox."""
        bob_client.create_sandbox(SANDBOX_NAME_BOB)
        time.sleep(1)

        status, body = admin_client.delete_sandbox(SANDBOX_NAME_BOB)
        assert status in (200, 204), f"Admin delete failed: {status} {body}"
