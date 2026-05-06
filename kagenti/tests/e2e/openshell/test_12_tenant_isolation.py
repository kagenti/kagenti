"""
Multi-Tenant Isolation E2E Tests (MVP Validation Criteria #6, #7, #8)

Validates tenant isolation across three dimensions:
- Auth isolation (#6): Alice's JWT (aud=team1) is rejected by team2's gateway
- RBAC isolation (#7): team1's gateway SA cannot access team2's resources
- Credential isolation (#8): Providers configured on team1 are invisible from team2

Prerequisites:
    - Two tenants deployed: team1, team2 (via deploy-tenant.sh)
    - Keycloak openshell realm with alice (team1) and bob (team2) users
    - OIDC enabled on both gateways (oidc.enabled=true)

Environment variables:
    OPENSHELL_KEYCLOAK_URL: Keycloak URL (default: auto-detected from svc)
    OPENSHELL_OIDC_ENABLED: Set to "false" to skip auth tests (default: true)
    OPENSHELL_SECOND_TENANT: Second tenant namespace (default: team2)
"""

import json
import os
import subprocess

import pytest

from kagenti.tests.e2e.openshell.conftest import kubectl_run

pytestmark = [pytest.mark.openshell, pytest.mark.mvp]


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

TENANT_1 = os.getenv("OPENSHELL_AGENT_NAMESPACE", "team1")
TENANT_2 = os.getenv("OPENSHELL_SECOND_TENANT", "team2")
KEYCLOAK_NS = os.getenv("KEYCLOAK_NS", "keycloak")
OIDC_CLIENT_ID = "openshell-cli"
OIDC_REALM = "openshell"

# Test users — passwords from deploy-shared.sh
ALICE = {"username": "alice", "password": "alice123", "tenant": "team1"}
BOB = {"username": "bob", "password": "bob123", "tenant": "team2"}


def _oidc_enabled() -> bool:
    return os.getenv("OPENSHELL_OIDC_ENABLED", "true").lower() != "false"


def _get_keycloak_url() -> str | None:
    """Resolve Keycloak URL accessible from the test runner."""
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

    # Port-forward or nodeport — for Kind, Keycloak uses port 8080
    return f"http://{cluster_ip}:8080"


def _get_token(keycloak_url: str, username: str, password: str) -> str | None:
    """Get an access token via Resource Owner Password Grant (direct access)."""
    import urllib.request
    import urllib.parse

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
    """Decode JWT payload (no signature verification — test-only)."""
    import base64

    parts = token.split(".")
    if len(parts) != 3:
        return {}
    payload = parts[1]
    # Add padding
    payload += "=" * (4 - len(payload) % 4)
    try:
        return json.loads(base64.urlsafe_b64decode(payload))
    except Exception:
        return {}


def _gateway_service_exists(namespace: str) -> bool:
    """Check if openshell-server service exists in namespace."""
    result = kubectl_run(
        "get",
        "svc",
        "openshell-server",
        "-n",
        namespace,
    )
    return result.returncode == 0


def _get_gateway_sa(namespace: str) -> str:
    """Get the ServiceAccount name used by the gateway pod in a namespace."""
    result = kubectl_run(
        "get",
        "statefulset",
        "openshell-server",
        "-n",
        namespace,
        "-o",
        "jsonpath={.spec.template.spec.serviceAccountName}",
    )
    if result.returncode == 0 and result.stdout.strip():
        return result.stdout.strip()
    return "default"


# ---------------------------------------------------------------------------
# Skip conditions
# ---------------------------------------------------------------------------

skip_no_oidc = pytest.mark.skipif(
    not _oidc_enabled(),
    reason="OIDC disabled (OPENSHELL_OIDC_ENABLED=false)",
)

skip_no_tenant2 = pytest.mark.skipif(
    not _gateway_service_exists(TENANT_2) if os.getenv("KUBECONFIG") else True,
    reason=f"Second tenant ({TENANT_2}) not deployed",
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def keycloak_url():
    """Resolve and cache the Keycloak URL."""
    url = _get_keycloak_url()
    if not url:
        pytest.skip("Keycloak URL not resolvable (no svc or env var)")
    return url


@pytest.fixture(scope="module")
def alice_token(keycloak_url):
    """Get a JWT for alice (team1 audience)."""
    token = _get_token(keycloak_url, ALICE["username"], ALICE["password"])
    if not token:
        pytest.skip("Could not obtain token for alice")
    return token


@pytest.fixture(scope="module")
def bob_token(keycloak_url):
    """Get a JWT for bob (team2 audience)."""
    token = _get_token(keycloak_url, BOB["username"], BOB["password"])
    if not token:
        pytest.skip("Could not obtain token for bob")
    return token


# ===========================================================================
# Criterion #6: Tenant Isolation (Auth)
# Alice's JWT (aud=team1) rejected by team2's gateway
# ===========================================================================


@skip_no_oidc
class TestTenantIsolationAuth:
    """Validate JWT audience-based tenant isolation."""

    def test_alice_token_has_team1_audience(self, alice_token):
        """Alice's token contains team1 in the audience claim."""
        payload = _decode_jwt_payload(alice_token)
        aud = payload.get("aud", [])
        if isinstance(aud, str):
            aud = [aud]
        assert "team1" in aud, f"Expected team1 in aud, got: {aud}"

    def test_bob_token_has_team2_audience(self, bob_token):
        """Bob's token contains team2 in the audience claim."""
        payload = _decode_jwt_payload(bob_token)
        aud = payload.get("aud", [])
        if isinstance(aud, str):
            aud = [aud]
        assert "team2" in aud, f"Expected team2 in aud, got: {aud}"

    @skip_no_tenant2
    def test_alice_token_rejected_by_team2_gateway(self, alice_token):
        """Alice's JWT (aud=team1) must be rejected by team2's gateway.

        The gateway validates OPENSHELL_OIDC_AUDIENCE == JWT.aud.
        Alice's token has aud=team1, so team2's gateway (audience=team2)
        should reject it with 401/403.
        """
        # Port-forward to team2's gateway
        import socket
        import time

        local_port = _find_free_port()
        proc = subprocess.Popen(
            [
                "kubectl",
                "port-forward",
                "svc/openshell-server",
                f"{local_port}:8080",
                "-n",
                TENANT_2,
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        try:
            # Wait for port-forward to be ready
            for _ in range(10):
                time.sleep(1)
                try:
                    sock = socket.create_connection(
                        ("localhost", local_port), timeout=2
                    )
                    sock.close()
                    break
                except (ConnectionRefusedError, OSError):
                    continue
            else:
                pytest.skip("Could not establish port-forward to team2 gateway")

            # Make request with alice's token to team2's gateway
            import urllib.request

            req = urllib.request.Request(
                f"http://localhost:{local_port}/api/sandboxes",
                headers={"Authorization": f"Bearer {alice_token}"},
            )
            try:
                with urllib.request.urlopen(req, timeout=10) as resp:
                    # If we get 200, isolation is broken
                    pytest.fail(
                        f"Alice's token was ACCEPTED by team2's gateway "
                        f"(status {resp.status}) — tenant isolation broken"
                    )
            except urllib.error.HTTPError as e:
                # 401 or 403 means isolation is working
                assert e.code in (401, 403), (
                    f"Expected 401/403 but got {e.code}: {e.reason}"
                )
        finally:
            proc.terminate()
            proc.wait()

    @skip_no_tenant2
    def test_bob_token_rejected_by_team1_gateway(self, bob_token):
        """Bob's JWT (aud=team2) must be rejected by team1's gateway."""
        import socket
        import time

        local_port = _find_free_port()
        proc = subprocess.Popen(
            [
                "kubectl",
                "port-forward",
                "svc/openshell-server",
                f"{local_port}:8080",
                "-n",
                TENANT_1,
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        try:
            for _ in range(10):
                time.sleep(1)
                try:
                    sock = socket.create_connection(
                        ("localhost", local_port), timeout=2
                    )
                    sock.close()
                    break
                except (ConnectionRefusedError, OSError):
                    continue
            else:
                pytest.skip("Could not establish port-forward to team1 gateway")

            import urllib.request

            req = urllib.request.Request(
                f"http://localhost:{local_port}/api/sandboxes",
                headers={"Authorization": f"Bearer {bob_token}"},
            )
            try:
                with urllib.request.urlopen(req, timeout=10) as resp:
                    pytest.fail(
                        f"Bob's token was ACCEPTED by team1's gateway "
                        f"(status {resp.status}) — tenant isolation broken"
                    )
            except urllib.error.HTTPError as e:
                assert e.code in (401, 403), (
                    f"Expected 401/403 but got {e.code}: {e.reason}"
                )
        finally:
            proc.terminate()
            proc.wait()

    def test_tokens_have_different_audiences(self, alice_token, bob_token):
        """Alice and Bob tokens must have non-overlapping audience claims."""
        alice_payload = _decode_jwt_payload(alice_token)
        bob_payload = _decode_jwt_payload(bob_token)

        alice_aud = set(
            alice_payload.get("aud", [])
            if isinstance(alice_payload.get("aud"), list)
            else [alice_payload.get("aud", "")]
        )
        bob_aud = set(
            bob_payload.get("aud", [])
            if isinstance(bob_payload.get("aud"), list)
            else [bob_payload.get("aud", "")]
        )

        tenant_overlap = alice_aud & bob_aud - {"account"}
        assert not tenant_overlap, (
            f"Tenant audiences overlap: {tenant_overlap}. "
            f"Alice: {alice_aud}, Bob: {bob_aud}"
        )


# ===========================================================================
# Criterion #7: Tenant Isolation (RBAC)
# team1's gateway SA cannot list sandboxes in team2
# ===========================================================================


class TestTenantIsolationRBAC:
    """Validate Kubernetes RBAC isolates tenants."""

    @skip_no_tenant2
    def test_team1_sa_cannot_list_sandboxes_in_team2(self):
        """team1's gateway ServiceAccount cannot list Sandbox CRs in team2."""
        sa = _get_gateway_sa(TENANT_1)
        result = kubectl_run(
            "auth",
            "can-i",
            "list",
            "sandboxes.agents.x-k8s.io",
            "-n",
            TENANT_2,
            f"--as=system:serviceaccount:{TENANT_1}:{sa}",
        )
        assert result.stdout.strip() == "no", (
            f"RBAC violation: {TENANT_1}:{sa} CAN list sandboxes in {TENANT_2}"
        )

    @skip_no_tenant2
    def test_team2_sa_cannot_list_sandboxes_in_team1(self):
        """team2's gateway ServiceAccount cannot list Sandbox CRs in team1."""
        sa = _get_gateway_sa(TENANT_2)
        result = kubectl_run(
            "auth",
            "can-i",
            "list",
            "sandboxes.agents.x-k8s.io",
            "-n",
            TENANT_1,
            f"--as=system:serviceaccount:{TENANT_2}:{sa}",
        )
        assert result.stdout.strip() == "no", (
            f"RBAC violation: {TENANT_2}:{sa} CAN list sandboxes in {TENANT_1}"
        )

    @skip_no_tenant2
    def test_team1_sa_cannot_get_pods_in_team2(self):
        """team1's gateway SA cannot get pods in team2's namespace."""
        sa = _get_gateway_sa(TENANT_1)
        result = kubectl_run(
            "auth",
            "can-i",
            "get",
            "pods",
            "-n",
            TENANT_2,
            f"--as=system:serviceaccount:{TENANT_1}:{sa}",
        )
        assert result.stdout.strip() == "no", (
            f"RBAC violation: {TENANT_1}:{sa} CAN get pods in {TENANT_2}"
        )

    @skip_no_tenant2
    def test_team1_sa_cannot_read_secrets_in_team2(self):
        """team1's gateway SA cannot read secrets in team2's namespace."""
        sa = _get_gateway_sa(TENANT_1)
        result = kubectl_run(
            "auth",
            "can-i",
            "get",
            "secrets",
            "-n",
            TENANT_2,
            f"--as=system:serviceaccount:{TENANT_1}:{sa}",
        )
        assert result.stdout.strip() == "no", (
            f"RBAC violation: {TENANT_1}:{sa} CAN read secrets in {TENANT_2}"
        )

    @skip_no_tenant2
    def test_team2_sa_cannot_read_secrets_in_team1(self):
        """team2's gateway SA cannot read secrets in team1's namespace."""
        sa = _get_gateway_sa(TENANT_2)
        result = kubectl_run(
            "auth",
            "can-i",
            "get",
            "secrets",
            "-n",
            TENANT_1,
            f"--as=system:serviceaccount:{TENANT_2}:{sa}",
        )
        assert result.stdout.strip() == "no", (
            f"RBAC violation: {TENANT_2}:{sa} CAN read secrets in {TENANT_1}"
        )

    @skip_no_tenant2
    def test_team1_sa_has_sandbox_access_in_own_namespace(self):
        """team1's gateway SA CAN manage sandboxes in its own namespace."""
        sa = _get_gateway_sa(TENANT_1)
        result = kubectl_run(
            "auth",
            "can-i",
            "create",
            "sandboxes.agents.x-k8s.io",
            "-n",
            TENANT_1,
            f"--as=system:serviceaccount:{TENANT_1}:{sa}",
        )
        assert result.stdout.strip() == "yes", (
            f"{TENANT_1}:{sa} cannot create sandboxes in own namespace"
        )


# ===========================================================================
# Criterion #8: Credential Isolation
# Providers on team1's gateway invisible from team2
# ===========================================================================


class TestCredentialIsolation:
    """Validate that credentials configured per-tenant are isolated."""

    @skip_no_tenant2
    def test_team1_secrets_not_in_team2(self):
        """Secrets in team1 are not accessible from team2 namespace."""
        # List secrets in team1
        result_t1 = kubectl_run(
            "get",
            "secrets",
            "-n",
            TENANT_1,
            "-o",
            "jsonpath={.items[*].metadata.name}",
        )
        if result_t1.returncode != 0:
            pytest.skip(f"Cannot list secrets in {TENANT_1}")

        team1_secrets = set(result_t1.stdout.strip().split())

        # List secrets in team2
        result_t2 = kubectl_run(
            "get",
            "secrets",
            "-n",
            TENANT_2,
            "-o",
            "jsonpath={.items[*].metadata.name}",
        )
        if result_t2.returncode != 0:
            pytest.skip(f"Cannot list secrets in {TENANT_2}")

        team2_secrets = set(result_t2.stdout.strip().split())

        # Provider-related secrets (LLM keys, credentials) should not leak
        provider_secrets = {
            s
            for s in team1_secrets
            if "litellm" in s or "api-key" in s or "credential" in s
        }

        leaked = provider_secrets & team2_secrets
        assert not leaked, (
            f"Provider secrets from {TENANT_1} found in {TENANT_2}: {leaked}"
        )

    @skip_no_tenant2
    def test_credentials_configmap_scoped_to_tenant(self):
        """Each tenant has its own credentials ConfigMap, not shared."""
        for tenant in [TENANT_1, TENANT_2]:
            result = kubectl_run(
                "get",
                "configmap",
                "openshell-credentials",
                "-n",
                tenant,
                "-o",
                "jsonpath={.data.credentials\\.yaml}",
            )
            if result.returncode != 0:
                # ConfigMap might not exist if credentials driver is disabled
                continue

            config_data = result.stdout.strip()
            if not config_data:
                continue

            # Verify it references the tenant's own namespace/resources
            # (not the other tenant's)
            other_tenant = TENANT_2 if tenant == TENANT_1 else TENANT_1
            assert other_tenant not in config_data, (
                f"Credentials ConfigMap in {tenant} references {other_tenant}"
            )

    @skip_no_tenant2
    def test_gateway_env_does_not_leak_other_tenant(self):
        """Gateway StatefulSet env vars must not reference other tenant."""
        for tenant in [TENANT_1, TENANT_2]:
            other = TENANT_2 if tenant == TENANT_1 else TENANT_1
            result = kubectl_run(
                "get",
                "statefulset",
                "openshell-server",
                "-n",
                tenant,
                "-o",
                "json",
            )
            if result.returncode != 0:
                pytest.skip(f"StatefulSet not found in {tenant}")

            sts = json.loads(result.stdout)
            containers = sts["spec"]["template"]["spec"]["containers"]
            for container in containers:
                for env in container.get("env", []):
                    value = env.get("value", "")
                    # Namespace references to the other tenant indicate leakage
                    if f".{other}.svc" in value or f"namespace: {other}" in value:
                        pytest.fail(
                            f"Container {container['name']} in {tenant} "
                            f"references {other}: {env['name']}={value}"
                        )

    @skip_no_tenant2
    def test_litellm_proxy_isolated_per_tenant(self):
        """LiteLLM proxy (if deployed) exists only in its designated tenant."""
        # LiteLLM is deployed per-tenant — check it's not cross-accessible
        for tenant in [TENANT_1, TENANT_2]:
            other = TENANT_2 if tenant == TENANT_1 else TENANT_1
            sa = _get_gateway_sa(tenant)

            # Gateway SA in this tenant should not access LiteLLM in other tenant
            result = kubectl_run(
                "auth",
                "can-i",
                "get",
                "endpoints",
                "-n",
                other,
                f"--as=system:serviceaccount:{tenant}:{sa}",
            )
            # "no" is expected (proper isolation)
            if result.stdout.strip() == "yes":
                pytest.fail(
                    f"{tenant}:{sa} can access endpoints in {other} "
                    f"— potential credential proxy leakage"
                )


# ---------------------------------------------------------------------------
# Helper (duplicated from conftest to keep this file self-contained for CI)
# ---------------------------------------------------------------------------


def _find_free_port() -> int:
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]
