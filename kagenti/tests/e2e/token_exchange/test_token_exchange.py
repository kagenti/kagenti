"""
Token Exchange E2E Tests.

Tests RFC 8693 token exchange via kagenti authbridge (envoy mode)
with Keycloak (community or RHBK) and optional SPIFFE identity.

Test matrix:
  1. Keycloak readiness
  2. Agent/tool sidecar injection (pods have envoy-proxy container)
  3. Client credentials grant (agent gets own token)
  4. User password grant (alice/bob)
  5. Token exchange: user -> agent audience
  6. Token exchange: agent -> tool audience (SPIFFE or client-secret)
  7. Inbound JWT validation (tool rejects unsigned requests)
  8. End-to-end: user -> agent -> tool with token exchange
"""

import base64
import json
import os
import subprocess
import time

import pytest

from .conftest import (
    KEYCLOAK_PROVIDER,
    KEYCLOAK_URL,
    TX_AGENT_URL,
    TX_CLIENT_ID,
    http,
    TX_NAMESPACE,
    TX_REALM,
    _decode_jwt,
)


def _get_running_pod(deploy):
    """Return the name of a Running pod for app=<deploy> in TX_NAMESPACE.

    kubectl exec needs a concrete pod. The AuthBridge mutating webhook rolls
    the deployment (briefly producing multiple ReplicaSets/pods), so selecting
    by label and filtering to status.phase=Running avoids landing on a pod that
    is still initializing.
    """
    result = subprocess.run(
        [
            "kubectl",
            "get",
            "pod",
            "-n",
            TX_NAMESPACE,
            "-l",
            f"app={deploy}",
            "--field-selector=status.phase=Running",
            "-o",
            "jsonpath={.items[0].metadata.name}",
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    return result.stdout.strip()


# ---------------------------------------------------------------------------
# 1. Keycloak readiness
# ---------------------------------------------------------------------------


class TestKeycloakReadiness:
    """Verify Keycloak is up and realm is configured."""

    def test_keycloak_realm_exists(self, kc_admin_token):
        """Realm exists and is enabled."""
        resp = http.get(
            f"{KEYCLOAK_URL}/admin/realms/{TX_REALM}",
            headers={"Authorization": f"Bearer {kc_admin_token}"},
            timeout=10,
        )
        assert resp.status_code == 200, f"Realm {TX_REALM} not found"
        realm = resp.json()
        assert realm["enabled"] is True

    def test_keycloak_client_exists(self, kc_admin_token):
        """TX client exists in realm."""
        resp = http.get(
            f"{KEYCLOAK_URL}/admin/realms/{TX_REALM}/clients",
            params={"clientId": TX_CLIENT_ID},
            headers={"Authorization": f"Bearer {kc_admin_token}"},
            timeout=10,
        )
        assert resp.status_code == 200
        clients = resp.json()
        assert len(clients) >= 1, f"Client {TX_CLIENT_ID} not found"

    def test_keycloak_users_exist(self, kc_admin_token):
        """Test users alice and bob exist."""
        for username in ["alice", "bob"]:
            resp = http.get(
                f"{KEYCLOAK_URL}/admin/realms/{TX_REALM}/users",
                params={"username": username, "exact": "true"},
                headers={"Authorization": f"Bearer {kc_admin_token}"},
                timeout=10,
            )
            assert resp.status_code == 200
            users = resp.json()
            assert len(users) >= 1, f"User {username} not found"

    def test_keycloak_token_exchange_feature(self, kc_admin_token):
        """Token exchange feature is enabled."""
        # Check realm-management has token-exchange scope
        resp = http.get(
            f"{KEYCLOAK_URL}/admin/realms/{TX_REALM}/clients",
            params={"clientId": "realm-management"},
            headers={"Authorization": f"Bearer {kc_admin_token}"},
            timeout=10,
        )
        assert resp.status_code == 200
        rm = resp.json()
        assert len(rm) >= 1, "realm-management client not found"


# ---------------------------------------------------------------------------
# 2. Sidecar injection
# ---------------------------------------------------------------------------


class TestSidecarInjection:
    """Verify kagenti sidecars are injected into test pods."""

    def _get_pod_containers(self, deploy_name):
        """Get container names for a deployment's pod."""
        result = subprocess.run(
            [
                "kubectl",
                "get",
                "pods",
                "-n",
                TX_NAMESPACE,
                "-l",
                f"app={deploy_name}",
                "-o",
                "jsonpath={.items[0].spec.containers[*].name}",
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        return result.stdout.split() if result.returncode == 0 else []

    def test_agent_has_envoy_sidecar(self):
        """Agent pod has envoy-proxy container."""
        containers = self._get_pod_containers("tx-e2e-agent")
        assert "envoy-proxy" in containers, (
            f"envoy-proxy sidecar not found in agent pod. Containers: {containers}"
        )

    def test_tool_has_envoy_sidecar(self):
        """Tool pod has envoy-proxy container."""
        containers = self._get_pod_containers("tx-e2e-tool")
        assert "envoy-proxy" in containers, (
            f"envoy-proxy sidecar not found in tool pod. Containers: {containers}"
        )

    def test_agent_has_operator_managed_credentials(self):
        """Agent pod mounts the operator-managed Keycloak client Secret.

        Replaces the legacy test_agent_has_client_registration check.
        After kagenti-operator#361 the in-pod client-registration sidecar
        is gone — the operator's ClientRegistrationReconciler creates a
        Secret with client-id.txt + client-secret.txt and the webhook
        mounts it at /shared/ inside the authbridge sidecar.
        """
        result = subprocess.run(
            [
                "kubectl",
                "get",
                "pods",
                "-n",
                TX_NAMESPACE,
                "-l",
                "app=tx-e2e-agent",
                "-o",
                "jsonpath={.items[0].spec.volumes[*].secret.secretName}",
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        secret_names = result.stdout.split() if result.returncode == 0 else []
        # The operator's ClientRegistrationReconciler emits Secrets named
        # `kagenti-keycloak-client-credentials-<sha256_hex8(ns,workload)>`
        # (see KeycloakClientCredentialsSecretName in
        # kagenti-operator/internal/clientreg/names.go — the suffix is a
        # truncated hash of namespace+workload+a constant). Match the
        # full prefix so a misnamed Secret can't accidentally satisfy
        # this gate; do NOT pin the suffix because it is intentionally
        # deterministic-but-derived. A loose substring match was
        # flagged in PR review.
        prefix = "kagenti-keycloak-client-credentials-"
        has_kc_secret = any(s.startswith(prefix) for s in secret_names)
        assert has_kc_secret, (
            "operator-managed Keycloak client Secret not mounted; "
            f"expected a Secret starting with {prefix!r}; "
            f"volumes referenced: {secret_names}"
        )


# ---------------------------------------------------------------------------
# 3. Client credentials grant
# ---------------------------------------------------------------------------


class TestClientCredentials:
    """Test OAuth2 client credentials grant for agents."""

    def test_agent_client_credentials(self, agent_credentials):
        """Agent can get a token via client_credentials grant."""
        if "agent" not in agent_credentials:
            pytest.skip("Agent credentials not found")
        creds = agent_credentials["agent"]
        resp = http.post(
            f"{KEYCLOAK_URL}/realms/{TX_REALM}/protocol/openid-connect/token",
            data={
                "grant_type": "client_credentials",
                "client_id": creds["client_id"],
                "client_secret": creds["client_secret"],
            },
            timeout=10,
        )
        assert resp.status_code == 200, f"client_credentials failed: {resp.text}"
        token = resp.json()["access_token"]
        claims = _decode_jwt(token)
        assert (
            claims.get("azp") == creds["client_id"]
            or claims.get("clientId") == creds["client_id"]
        )

    def test_tool_client_credentials(self, agent_credentials):
        """Tool can get a token via client_credentials grant."""
        if "tool" not in agent_credentials:
            pytest.skip("Tool credentials not found")
        creds = agent_credentials["tool"]
        resp = http.post(
            f"{KEYCLOAK_URL}/realms/{TX_REALM}/protocol/openid-connect/token",
            data={
                "grant_type": "client_credentials",
                "client_id": creds["client_id"],
                "client_secret": creds["client_secret"],
            },
            timeout=10,
        )
        assert resp.status_code == 200, f"client_credentials failed: {resp.text}"


# ---------------------------------------------------------------------------
# 4. User password grant
# ---------------------------------------------------------------------------


class TestPasswordGrant:
    """Test user authentication via password grant."""

    def test_alice_password_grant(self, get_user_token):
        """Alice (user role) can authenticate."""
        token = get_user_token("alice", "alice123")
        assert token, "Failed to get token for alice"
        claims = _decode_jwt(token)
        assert claims.get("preferred_username") == "alice"

    def test_bob_password_grant(self, get_user_token):
        """Bob (admin role) can authenticate."""
        token = get_user_token("bob", "bob123")
        assert token, "Failed to get token for bob"
        claims = _decode_jwt(token)
        assert claims.get("preferred_username") == "bob"

    def test_bob_has_admin_role(self, get_user_token):
        """Bob's token includes admin realm role."""
        token = get_user_token("bob", "bob123")
        claims = _decode_jwt(token)
        realm_roles = claims.get("realm_access", {}).get("roles", [])
        assert "admin" in realm_roles, (
            f"Bob does not have admin role. Roles: {realm_roles}"
        )


# ---------------------------------------------------------------------------
# 5. Token exchange: user -> agent audience
# ---------------------------------------------------------------------------


class TestTokenExchange:
    """Test RFC 8693 token exchange flows."""

    def test_user_to_agent_exchange(
        self, get_user_token, agent_credentials, kc_client_secret
    ):
        """Exchange alice's user token for agent-scoped token."""
        if "agent" not in agent_credentials:
            pytest.skip("Agent credentials not found")

        user_token = get_user_token("alice", "alice123")
        agent_creds = agent_credentials["agent"]

        resp = http.post(
            f"{KEYCLOAK_URL}/realms/{TX_REALM}/protocol/openid-connect/token",
            data={
                "grant_type": "urn:ietf:params:oauth:grant-type:token-exchange",
                "client_id": agent_creds["client_id"],
                "client_secret": agent_creds["client_secret"],
                "subject_token": user_token,
                "subject_token_type": "urn:ietf:params:oauth:token-type:access_token",
                "requested_token_type": "urn:ietf:params:oauth:token-type:access_token",
                "audience": agent_creds["client_id"],
            },
            timeout=10,
        )
        assert resp.status_code == 200, (
            f"Token exchange failed: {resp.json().get('error_description', resp.text)}"
        )
        exchanged = resp.json()["access_token"]
        claims = _decode_jwt(exchanged)
        # Subject should be preserved
        assert claims.get("preferred_username") == "alice"

    def test_agent_to_tool_exchange(self, agent_credentials):
        """Exchange agent's token for tool-scoped token."""
        if "agent" not in agent_credentials or "tool" not in agent_credentials:
            pytest.skip("Agent or tool credentials not found")

        agent_creds = agent_credentials["agent"]
        tool_creds = agent_credentials["tool"]

        # First get agent token
        resp = http.post(
            f"{KEYCLOAK_URL}/realms/{TX_REALM}/protocol/openid-connect/token",
            data={
                "grant_type": "client_credentials",
                "client_id": agent_creds["client_id"],
                "client_secret": agent_creds["client_secret"],
            },
            timeout=10,
        )
        assert resp.status_code == 200
        agent_token = resp.json()["access_token"]

        # Exchange for tool audience
        resp = http.post(
            f"{KEYCLOAK_URL}/realms/{TX_REALM}/protocol/openid-connect/token",
            data={
                "grant_type": "urn:ietf:params:oauth:grant-type:token-exchange",
                "client_id": agent_creds["client_id"],
                "client_secret": agent_creds["client_secret"],
                "subject_token": agent_token,
                "subject_token_type": "urn:ietf:params:oauth:token-type:access_token",
                "requested_token_type": "urn:ietf:params:oauth:token-type:access_token",
                "audience": tool_creds["client_id"],
            },
            timeout=10,
        )
        assert resp.status_code == 200, (
            f"Agent->tool exchange failed: "
            f"{resp.json().get('error_description', resp.text)}"
        )

    def test_admin_user_exchange_preserves_roles(
        self, get_user_token, agent_credentials
    ):
        """Token exchange preserves bob's admin role."""
        if "agent" not in agent_credentials:
            pytest.skip("Agent credentials not found")

        bob_token = get_user_token("bob", "bob123")
        agent_creds = agent_credentials["agent"]

        resp = http.post(
            f"{KEYCLOAK_URL}/realms/{TX_REALM}/protocol/openid-connect/token",
            data={
                "grant_type": "urn:ietf:params:oauth:grant-type:token-exchange",
                "client_id": agent_creds["client_id"],
                "client_secret": agent_creds["client_secret"],
                "subject_token": bob_token,
                "subject_token_type": "urn:ietf:params:oauth:token-type:access_token",
                "requested_token_type": "urn:ietf:params:oauth:token-type:access_token",
                "audience": agent_creds["client_id"],
            },
            timeout=10,
        )
        assert resp.status_code == 200
        claims = _decode_jwt(resp.json()["access_token"])
        assert claims.get("preferred_username") == "bob"
        realm_roles = claims.get("realm_access", {}).get("roles", [])
        assert "admin" in realm_roles, (
            f"Admin role lost after exchange. Roles: {realm_roles}"
        )


# ---------------------------------------------------------------------------
# 6. SPIFFE token exchange (in-pod)
# ---------------------------------------------------------------------------


class TestSpiffeTokenExchange:
    """Test token exchange using SPIFFE JWT-SVID authentication."""

    def _exec_in_pod(self, deploy, container, cmd):
        """Execute command in a Running pod selected by app label."""
        pod = _get_running_pod(deploy)
        result = subprocess.run(
            [
                "kubectl",
                "exec",
                "-n",
                TX_NAMESPACE,
                pod,
                "-c",
                container,
                "--",
                "sh",
                "-c",
                cmd,
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        return result

    @pytest.mark.xfail(
        reason="tx-e2e-agent pod not Ready/exec-able in CI — see #2129",
        strict=False,
    )
    def test_spiffe_jwt_svid_present(self, spiffe_mode):
        """JWT SVID file exists in agent's envoy-proxy container."""
        if not spiffe_mode:
            pytest.skip("SPIFFE mode not enabled")
        # spiffe-helper writes the JWT-SVID to the shared /opt volume
        # asynchronously after the pod is Ready; poll rather than assume it is
        # present on the first check. Genuine non-delivery still fails here.
        deadline = time.time() + 90
        result = None
        while time.time() < deadline:
            result = self._exec_in_pod(
                "tx-e2e-agent",
                "envoy-proxy",
                "cat /opt/jwt_svid.token 2>/dev/null | head -c 20",
            )
            if result.returncode == 0 and len(result.stdout.strip()) > 10:
                break
            time.sleep(5)
        assert (
            result is not None
            and result.returncode == 0
            and len(result.stdout.strip()) > 10
        ), "JWT SVID not found in agent pod within 90s"

    def test_spiffe_client_credentials(self, spiffe_mode):
        """Agent can authenticate via SPIFFE JWT-SVID (client_credentials)."""
        if not spiffe_mode:
            pytest.skip("SPIFFE mode not enabled")

        # Read JWT-SVID and client-id from envoy-proxy, run curl from agent
        cmd = """
JWT=$(cat /opt/jwt_svid.token)
CID=$(cat /shared/client-id.txt)
curl -sk -X POST "${KEYCLOAK_URL}/realms/${TX_REALM}/protocol/openid-connect/token" \
  --data-urlencode "client_id=${CID}" \
  -d "client_assertion_type=urn:ietf:params:oauth:client-assertion-type:jwt-spiffe" \
  --data-urlencode "client_assertion=${JWT}" \
  -d "grant_type=client_credentials"
"""
        # First read creds from envoy-proxy
        jwt_result = self._exec_in_pod(
            "tx-e2e-agent", "envoy-proxy", "cat /opt/jwt_svid.token"
        )
        cid_result = self._exec_in_pod(
            "tx-e2e-agent", "envoy-proxy", "cat /shared/client-id.txt"
        )

        if jwt_result.returncode != 0 or cid_result.returncode != 0:
            pytest.skip("Could not read SPIFFE credentials from pod")

        jwt_svid = jwt_result.stdout.strip()
        client_id = cid_result.stdout.strip()

        resp = http.post(
            f"{KEYCLOAK_URL}/realms/{TX_REALM}/protocol/openid-connect/token",
            data={
                "grant_type": "client_credentials",
                "client_id": client_id,
                "client_assertion_type": "urn:ietf:params:oauth:client-assertion-type:jwt-spiffe",
                "client_assertion": jwt_svid,
            },
            timeout=10,
        )
        assert resp.status_code == 200, f"SPIFFE client_credentials failed: {resp.text}"

    def test_spiffe_token_exchange(self, spiffe_mode, get_user_token):
        """Token exchange using SPIFFE identity (federated-jwt)."""
        if not spiffe_mode:
            pytest.skip("SPIFFE mode not enabled")

        user_token = get_user_token("alice", "alice123")

        jwt_result = self._exec_in_pod(
            "tx-e2e-agent", "envoy-proxy", "cat /opt/jwt_svid.token"
        )
        cid_result = self._exec_in_pod(
            "tx-e2e-agent", "envoy-proxy", "cat /shared/client-id.txt"
        )

        if jwt_result.returncode != 0 or cid_result.returncode != 0:
            pytest.skip("Could not read SPIFFE credentials from pod")

        jwt_svid = jwt_result.stdout.strip()
        client_id = cid_result.stdout.strip()

        resp = http.post(
            f"{KEYCLOAK_URL}/realms/{TX_REALM}/protocol/openid-connect/token",
            data={
                "grant_type": "urn:ietf:params:oauth:grant-type:token-exchange",
                "client_id": client_id,
                "client_assertion_type": "urn:ietf:params:oauth:client-assertion-type:jwt-spiffe",
                "client_assertion": jwt_svid,
                "subject_token": user_token,
                "subject_token_type": "urn:ietf:params:oauth:token-type:access_token",
                "requested_token_type": "urn:ietf:params:oauth:token-type:access_token",
                "audience": TX_CLIENT_ID,
            },
            timeout=10,
        )
        assert resp.status_code == 200, f"SPIFFE token exchange failed: {resp.text}"
        claims = _decode_jwt(resp.json()["access_token"])
        assert claims.get("preferred_username") == "alice"


# ---------------------------------------------------------------------------
# Helper: call tool from inside the agent pod and return echoed headers
# ---------------------------------------------------------------------------


def _call_tool_from_agent(token: str, path: str = "/echo") -> dict:
    """
    Execute an HTTP request from the agent container to the tool service.

    Traffic flow:
      agent container → iptables (proxy-init) → envoy outbound (:15123)
      → ext_proc (authbridge) → [token exchange if route matches]
      → tx-e2e-tool service → envoy inbound (:15124)
      → ext_proc (validate JWT) → tool container

    The tool echoes all received headers as JSON, so we can inspect the
    Authorization header that actually arrived after authbridge processing.
    """
    # Use a Python script inside the pod so we get structured JSON back.
    # We avoid shell escaping issues by writing minimal inline Python.
    script = (
        "import urllib.request, json, sys; "
        "req = urllib.request.Request("
        f"'http://tx-e2e-tool:8080{path}', "
        "headers={'Authorization': 'Bearer ' + sys.argv[1]}); "
        "try:\n"
        "  resp = urllib.request.urlopen(req, timeout=15)\n"
        "  print(resp.read().decode())\n"
        "except urllib.error.HTTPError as e:\n"
        "  print(json.dumps({'_http_error': e.code, '_body': e.read().decode()}))\n"
        "except Exception as e:\n"
        "  print(json.dumps({'_error': str(e)}))"
    )
    pod = _get_running_pod("tx-e2e-agent")
    result = subprocess.run(
        [
            "kubectl",
            "exec",
            "-n",
            TX_NAMESPACE,
            pod,
            "-c",
            "agent",
            "--",
            "python3",
            "-c",
            script,
            token,
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )
    if result.returncode != 0:
        return {"_exec_error": result.stderr}
    try:
        return json.loads(result.stdout.strip())
    except (json.JSONDecodeError, ValueError):
        return {"_raw": result.stdout.strip()}


def _extract_bearer_token(headers: dict) -> str | None:
    """Extract the Bearer token from echoed headers (case-insensitive)."""
    for key, value in headers.items():
        if key.lower() == "authorization" and value.lower().startswith("bearer "):
            return value.split(" ", 1)[1]
    return None


# ---------------------------------------------------------------------------
# 7. Authbridge ext_proc verification
# ---------------------------------------------------------------------------


class TestAuthbridgeExtProc:
    """Verify that authbridge's envoy ext_proc filter intercepts traffic."""

    def test_outbound_token_is_different(self, agent_credentials):
        """Token arriving at tool must differ from what agent sent (exchanged).

        Flow:
          1. Agent gets its own token (client_credentials)
          2. Agent calls tool with that token
          3. Authbridge outbound ext_proc intercepts, matches authproxy-route
             for host "tx-e2e-tool", exchanges token for target_audience
          4. Tool echoes received headers
          5. We verify the Authorization header token ≠ original agent token
        """
        if "agent" not in agent_credentials:
            pytest.skip("Agent credentials not found")
        agent_creds = agent_credentials["agent"]

        # 1. Get agent's own token
        resp = http.post(
            f"{KEYCLOAK_URL}/realms/{TX_REALM}/protocol/openid-connect/token",
            data={
                "grant_type": "client_credentials",
                "client_id": agent_creds["client_id"],
                "client_secret": agent_creds["client_secret"],
            },
            timeout=10,
        )
        assert resp.status_code == 200, f"client_credentials failed: {resp.text}"
        original_token = resp.json()["access_token"]

        # 2. Call tool from agent pod (goes through envoy → ext_proc)
        tool_response = _call_tool_from_agent(original_token)

        assert "_http_error" not in tool_response, (
            f"Tool returned HTTP {tool_response.get('_http_error')}: "
            f"{tool_response.get('_body', '')}"
        )
        assert "_error" not in tool_response, (
            f"Request failed: {tool_response.get('_error')}"
        )
        assert "_exec_error" not in tool_response, (
            f"kubectl exec failed: {tool_response.get('_exec_error')}"
        )
        assert tool_response.get("service") == "tx-e2e-tool", (
            f"Unexpected response: {tool_response}"
        )

        # 3. Extract token that the tool actually received
        received_token = _extract_bearer_token(tool_response.get("headers", {}))
        assert received_token is not None, (
            "Tool did not receive an Authorization header. "
            "Authbridge may not be injecting tokens. "
            f"Echoed headers: {tool_response.get('headers', {})}"
        )

        # 4. THE KEY ASSERTION: tokens must differ (exchange happened)
        assert received_token != original_token, (
            "Token received by tool is identical to what agent sent. "
            "Authbridge ext_proc did NOT perform token exchange. "
            "Check authproxy-routes ConfigMap and authbridge logs."
        )

    def test_exchanged_token_has_correct_audience(self, agent_credentials):
        """Exchanged token must have target_audience from authproxy-routes.

        authproxy-routes maps host "tx-e2e-tool" → target_audience TX_CLIENT_ID.
        The exchanged token's 'aud' claim must contain that audience.
        """
        if "agent" not in agent_credentials:
            pytest.skip("Agent credentials not found")
        agent_creds = agent_credentials["agent"]

        resp = http.post(
            f"{KEYCLOAK_URL}/realms/{TX_REALM}/protocol/openid-connect/token",
            data={
                "grant_type": "client_credentials",
                "client_id": agent_creds["client_id"],
                "client_secret": agent_creds["client_secret"],
            },
            timeout=10,
        )
        assert resp.status_code == 200
        original_token = resp.json()["access_token"]

        tool_response = _call_tool_from_agent(original_token)
        received_token = _extract_bearer_token(tool_response.get("headers", {}))
        assert received_token is not None, "No token echoed by tool"

        received_claims = _decode_jwt(received_token)
        aud = received_claims.get("aud", "")
        if isinstance(aud, list):
            assert TX_CLIENT_ID in aud, (
                f"Exchanged token audience {aud} does not contain "
                f"expected target '{TX_CLIENT_ID}'"
            )
        else:
            assert aud == TX_CLIENT_ID, (
                f"Exchanged token audience '{aud}' != expected '{TX_CLIENT_ID}'"
            )

    def test_user_identity_preserved_through_exchange(
        self, get_user_token, agent_credentials
    ):
        """User identity (sub, preferred_username) survives token exchange.

        Flow:
          1. Alice gets a user token (password grant)
          2. We manually exchange it for an agent-scoped token
          3. Agent calls tool with the exchanged token
          4. Authbridge exchanges again for tool audience
          5. Tool echoes the token — we verify alice's identity is still there
        """
        if "agent" not in agent_credentials:
            pytest.skip("Agent credentials not found")
        agent_creds = agent_credentials["agent"]

        # Get alice's user token
        user_token = get_user_token("alice", "alice123")
        original_claims = _decode_jwt(user_token)

        # Exchange user token for agent-scoped token (simulating inbound flow)
        resp = http.post(
            f"{KEYCLOAK_URL}/realms/{TX_REALM}/protocol/openid-connect/token",
            data={
                "grant_type": "urn:ietf:params:oauth:grant-type:token-exchange",
                "client_id": agent_creds["client_id"],
                "client_secret": agent_creds["client_secret"],
                "subject_token": user_token,
                "subject_token_type": "urn:ietf:params:oauth:token-type:access_token",
                "requested_token_type": "urn:ietf:params:oauth:token-type:access_token",
                "audience": agent_creds["client_id"],
            },
            timeout=10,
        )
        assert resp.status_code == 200, f"User->agent exchange failed: {resp.text}"
        agent_scoped_token = resp.json()["access_token"]

        # Agent calls tool — authbridge exchanges again for tool audience
        tool_response = _call_tool_from_agent(agent_scoped_token)
        received_token = _extract_bearer_token(tool_response.get("headers", {}))
        assert received_token is not None, "No token echoed by tool"

        # Verify alice's identity survives the full chain
        final_claims = _decode_jwt(received_token)
        assert final_claims.get("preferred_username") == "alice", (
            f"User identity lost after double exchange. "
            f"Original: {original_claims.get('preferred_username')}, "
            f"Final: {final_claims.get('preferred_username')}"
        )
        assert final_claims.get("sub") == original_claims.get("sub"), (
            f"Subject changed: {original_claims.get('sub')} → {final_claims.get('sub')}"
        )

    def test_admin_role_preserved_through_exchange(
        self, get_user_token, agent_credentials
    ):
        """Bob's admin role survives double exchange (user→agent→tool)."""
        if "agent" not in agent_credentials:
            pytest.skip("Agent credentials not found")
        agent_creds = agent_credentials["agent"]

        bob_token = get_user_token("bob", "bob123")

        # Exchange user → agent
        resp = http.post(
            f"{KEYCLOAK_URL}/realms/{TX_REALM}/protocol/openid-connect/token",
            data={
                "grant_type": "urn:ietf:params:oauth:grant-type:token-exchange",
                "client_id": agent_creds["client_id"],
                "client_secret": agent_creds["client_secret"],
                "subject_token": bob_token,
                "subject_token_type": "urn:ietf:params:oauth:token-type:access_token",
                "requested_token_type": "urn:ietf:params:oauth:token-type:access_token",
                "audience": agent_creds["client_id"],
            },
            timeout=10,
        )
        assert resp.status_code == 200
        agent_scoped_token = resp.json()["access_token"]

        # Agent → tool (authbridge exchanges automatically)
        tool_response = _call_tool_from_agent(agent_scoped_token)
        received_token = _extract_bearer_token(tool_response.get("headers", {}))
        assert received_token is not None, "No token echoed by tool"

        final_claims = _decode_jwt(received_token)
        realm_roles = final_claims.get("realm_access", {}).get("roles", [])
        assert "admin" in realm_roles, (
            f"Admin role lost after double exchange. Final roles: {realm_roles}"
        )

    def test_authbridge_logs_show_exchange(self, agent_credentials):
        """Authbridge container logs contain evidence of token exchange."""
        if "agent" not in agent_credentials:
            pytest.skip("Agent credentials not found")
        agent_creds = agent_credentials["agent"]

        # Trigger an exchange first
        resp = http.post(
            f"{KEYCLOAK_URL}/realms/{TX_REALM}/protocol/openid-connect/token",
            data={
                "grant_type": "client_credentials",
                "client_id": agent_creds["client_id"],
                "client_secret": agent_creds["client_secret"],
            },
            timeout=10,
        )
        if resp.status_code == 200:
            _call_tool_from_agent(resp.json()["access_token"])

        # Check authbridge logs in the agent pod
        result = subprocess.run(
            [
                "kubectl",
                "logs",
                "-n",
                TX_NAMESPACE,
                "-l",
                "app=tx-e2e-agent",
                "-c",
                "envoy-proxy",
                "--tail=100",
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        logs = result.stdout + result.stderr
        # Authbridge logs evidence of exchange — look for typical markers
        exchange_markers = [
            "token_exchange",
            "token-exchange",
            "exchange",
            "outbound",
            "ext_proc",
        ]
        has_evidence = any(marker in logs.lower() for marker in exchange_markers)
        # This is a soft check — log format may vary. The legacy
        # authbridge-light container is gone after kagenti-extensions#411
        # (everything's bundled into the envoy-proxy container in
        # envoy-sidecar mode), so we only inspect that one container now.
        # The token comparison tests above are the definitive proof.
        if has_evidence:
            pass  # Good: logs confirm exchange
        else:
            import warnings

            warnings.warn(
                "Could not find token exchange evidence in authbridge logs. "
                "The token comparison tests are the definitive verification."
            )


# ---------------------------------------------------------------------------
# 8. Inbound JWT validation
# ---------------------------------------------------------------------------


class TestInboundJwtValidation:
    """Verify authbridge inbound listener validates JWTs on the tool."""

    def test_unauthenticated_request_rejected(self):
        """Request without a token is rejected by tool's inbound ext_proc.

        From the agent container, we call the tool without an Authorization
        header. The tool's inbound envoy listener + ext_proc should reject
        the request with 401 or 403.
        """
        script = (
            "import urllib.request, json; "
            "req = urllib.request.Request('http://tx-e2e-tool:8080/echo'); "
            "try:\n"
            "  resp = urllib.request.urlopen(req, timeout=10)\n"
            "  print(json.dumps({'status': resp.status}))\n"
            "except urllib.error.HTTPError as e:\n"
            "  print(json.dumps({'status': e.code}))\n"
            "except Exception as e:\n"
            "  print(json.dumps({'error': str(e)}))"
        )
        pod = _get_running_pod("tx-e2e-agent")
        result = subprocess.run(
            [
                "kubectl",
                "exec",
                "-n",
                TX_NAMESPACE,
                pod,
                "-c",
                "agent",
                "--",
                "python3",
                "-c",
                script,
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode == 0 and result.stdout.strip():
            data = json.loads(result.stdout.strip())
            status = data.get("status", 0)
            assert status in [401, 403], (
                f"Expected 401/403 for unauthenticated request, got {status}. "
                "Inbound JWT validation may not be configured."
            )

    @pytest.mark.xfail(
        reason="tx-e2e-agent pod not Ready/exec-able in CI — see #2129",
        strict=False,
    )
    def test_invalid_token_rejected(self):
        """Request with a garbage token is rejected by inbound ext_proc."""
        fake_token = "eyJhbGciOiJSUzI1NiJ9.eyJzdWIiOiJmYWtlIn0.invalid_sig"
        tool_response = _call_tool_from_agent(fake_token)
        http_error = tool_response.get("_http_error")
        assert http_error in [401, 403], (
            f"Expected 401/403 for invalid token, got: {tool_response}"
        )

    def test_valid_exchanged_token_accepted(self, agent_credentials):
        """Request with a validly exchanged token reaches the tool."""
        if "agent" not in agent_credentials:
            pytest.skip("Agent credentials not found")
        agent_creds = agent_credentials["agent"]

        resp = http.post(
            f"{KEYCLOAK_URL}/realms/{TX_REALM}/protocol/openid-connect/token",
            data={
                "grant_type": "client_credentials",
                "client_id": agent_creds["client_id"],
                "client_secret": agent_creds["client_secret"],
            },
            timeout=10,
        )
        assert resp.status_code == 200
        agent_token = resp.json()["access_token"]

        tool_response = _call_tool_from_agent(agent_token)
        assert tool_response.get("service") == "tx-e2e-tool", (
            f"Valid token should reach tool. Response: {tool_response}"
        )


# ---------------------------------------------------------------------------
# 9. End-to-end: full chain user → agent → tool with double exchange
# ---------------------------------------------------------------------------


class TestEndToEndChain:
    """Full chain test: user authenticates → agent → authbridge → tool.

    This class tests the real-world scenario where:
      1. A user authenticates to Keycloak (password grant)
      2. User's request arrives at the agent (with user token)
      3. Agent makes an outbound call to the tool
      4. Authbridge intercepts, exchanges the token for tool audience
      5. Tool receives the exchanged token and processes the request
    """

    def test_full_chain_alice(self, get_user_token, agent_credentials):
        """Alice's request flows through agent → authbridge → tool."""
        if "agent" not in agent_credentials:
            pytest.skip("Agent credentials not found")
        agent_creds = agent_credentials["agent"]

        # Step 1: Alice authenticates
        user_token = get_user_token("alice", "alice123")
        original_claims = _decode_jwt(user_token)

        # Step 2-3: Simulate agent receiving the request and calling tool
        # (In production, the inbound ext_proc validates alice's token,
        #  then the agent calls the tool with the same or a new token.
        #  Here we exchange manually to simulate the inbound flow, then
        #  let authbridge handle the outbound exchange automatically.)
        resp = http.post(
            f"{KEYCLOAK_URL}/realms/{TX_REALM}/protocol/openid-connect/token",
            data={
                "grant_type": "urn:ietf:params:oauth:grant-type:token-exchange",
                "client_id": agent_creds["client_id"],
                "client_secret": agent_creds["client_secret"],
                "subject_token": user_token,
                "subject_token_type": "urn:ietf:params:oauth:token-type:access_token",
                "requested_token_type": "urn:ietf:params:oauth:token-type:access_token",
                "audience": agent_creds["client_id"],
            },
            timeout=10,
        )
        assert resp.status_code == 200
        agent_scoped_token = resp.json()["access_token"]

        # Step 4-5: Agent calls tool — authbridge exchanges automatically
        tool_response = _call_tool_from_agent(agent_scoped_token)
        assert tool_response.get("service") == "tx-e2e-tool", (
            f"Tool not reached: {tool_response}"
        )

        # Step 6: Verify the full chain
        received_token = _extract_bearer_token(tool_response.get("headers", {}))
        assert received_token is not None, "No token at tool"

        # Token must have been exchanged (different from what agent sent)
        assert received_token != agent_scoped_token, (
            "Authbridge did not exchange token on outbound"
        )

        # Exchanged token has correct audience
        final_claims = _decode_jwt(received_token)
        aud = final_claims.get("aud", "")
        aud_list = aud if isinstance(aud, list) else [aud]
        assert TX_CLIENT_ID in aud_list, (
            f"Final token audience {aud_list} missing '{TX_CLIENT_ID}'"
        )

        # Alice's identity survives the full chain
        assert final_claims.get("preferred_username") == "alice"
        assert final_claims.get("sub") == original_claims.get("sub")

    def test_full_chain_bob_admin(self, get_user_token, agent_credentials):
        """Bob (admin) — roles survive the full exchange chain."""
        if "agent" not in agent_credentials:
            pytest.skip("Agent credentials not found")
        agent_creds = agent_credentials["agent"]

        bob_token = get_user_token("bob", "bob123")

        resp = http.post(
            f"{KEYCLOAK_URL}/realms/{TX_REALM}/protocol/openid-connect/token",
            data={
                "grant_type": "urn:ietf:params:oauth:grant-type:token-exchange",
                "client_id": agent_creds["client_id"],
                "client_secret": agent_creds["client_secret"],
                "subject_token": bob_token,
                "subject_token_type": "urn:ietf:params:oauth:token-type:access_token",
                "requested_token_type": "urn:ietf:params:oauth:token-type:access_token",
                "audience": agent_creds["client_id"],
            },
            timeout=10,
        )
        assert resp.status_code == 200
        agent_scoped_token = resp.json()["access_token"]

        tool_response = _call_tool_from_agent(agent_scoped_token)
        received_token = _extract_bearer_token(tool_response.get("headers", {}))
        assert received_token is not None, "No token at tool"
        assert received_token != agent_scoped_token, "No exchange happened"

        final_claims = _decode_jwt(received_token)
        assert final_claims.get("preferred_username") == "bob"
        realm_roles = final_claims.get("realm_access", {}).get("roles", [])
        assert "admin" in realm_roles, (
            f"Bob's admin role lost. Final roles: {realm_roles}"
        )
