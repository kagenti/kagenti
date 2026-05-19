#!/usr/bin/env python3
"""
Sandbox Sessions API E2E Tests

Tests the backend sandbox sessions API that reads from the A2A SDK's
DatabaseTaskStore. Verifies:
- Session list pagination and search
- Session detail retrieval (history, artifacts)
- Session delete and kill operations
- Data persistence across agent pod restarts

Prerequisites:
    - sandbox-legion deployed in team1 namespace with TASK_STORE_DB_URL set
    - postgres-sessions StatefulSet running in team1
    - At least one A2A message sent to create a task in the DB

Usage:
    SANDBOX_LEGION_URL=http://... pytest tests/e2e/common/test_sandbox_sessions_api.py -v
"""

import base64
import logging
import os
import pathlib
import subprocess

import httpx
import pytest
import yaml
from uuid import uuid4

logger = logging.getLogger(__name__)

VERIFY_SSL = os.environ.get("VERIFY_SSL", "false").lower() == "true"


def _get_backend_url() -> str:
    """Get the Kagenti backend URL.

    Tries in order:
    1. KAGENTI_BACKEND_URL env var (explicit)
    2. Auto-discover from OpenShift route (kagenti-backend in kagenti-system)
    3. Fallback to in-cluster DNS
    """
    explicit = os.getenv("KAGENTI_BACKEND_URL")
    if explicit:
        return explicit

    # Auto-discover from route
    try:
        result = subprocess.run(
            [
                "kubectl",
                "get",
                "route",
                "kagenti-api",
                "-n",
                "kagenti-system",
                "-o",
                "jsonpath={.spec.host}",
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0 and result.stdout:
            return f"https://{result.stdout}"
    except Exception:
        pass

    return "http://kagenti-backend.kagenti-system.svc.cluster.local:8000"


# ---------------------------------------------------------------------------
# Auth helper — acquire Keycloak token for backend API calls
# ---------------------------------------------------------------------------

_cached_auth_headers: dict | None = None


def _get_auth_headers() -> dict:
    """Get Authorization headers for backend API calls.

    When Keycloak auth is enabled, acquires a token using admin credentials
    from the keycloak-initial-admin secret. When auth is disabled (Kind
    without Keycloak), returns empty headers.

    The token is cached for the module lifetime to avoid repeated token
    requests.
    """
    global _cached_auth_headers
    if _cached_auth_headers is not None:
        return _cached_auth_headers

    # Try to get Keycloak credentials from K8s secret
    try:
        import kubernetes.client
        import kubernetes.config
        from kubernetes.config import ConfigException

        try:
            if os.getenv("KUBERNETES_SERVICE_HOST"):
                kubernetes.config.load_incluster_config()
            else:
                kubernetes.config.load_kube_config()
        except ConfigException:
            logger.info("No K8s config — assuming auth disabled, using empty headers")
            _cached_auth_headers = {}
            return _cached_auth_headers

        api = kubernetes.client.CoreV1Api()
        try:
            secret = api.read_namespaced_secret(
                name="keycloak-initial-admin", namespace="keycloak"
            )
        except Exception:
            logger.info(
                "keycloak-initial-admin secret not found — auth likely disabled"
            )
            _cached_auth_headers = {}
            return _cached_auth_headers

        if not secret.data:
            _cached_auth_headers = {}
            return _cached_auth_headers

        username = base64.b64decode(secret.data["username"]).decode("utf-8")
        password = base64.b64decode(secret.data["password"]).decode("utf-8")

    except ImportError:
        logger.info("kubernetes package not available — assuming auth disabled")
        _cached_auth_headers = {}
        return _cached_auth_headers

    # Acquire token from Keycloak
    keycloak_base_url = os.environ.get("KEYCLOAK_URL", "http://localhost:8081")
    token_url = f"{keycloak_base_url}/realms/master/protocol/openid-connect/token"

    verify_ssl: bool | str = True
    if os.environ.get("KEYCLOAK_VERIFY_SSL", "true").lower() == "false":
        verify_ssl = VERIFY_SSL
    elif os.environ.get("KEYCLOAK_CA_BUNDLE"):
        verify_ssl = os.environ["KEYCLOAK_CA_BUNDLE"]

    try:
        resp = httpx.post(
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
        if resp.status_code == 200:
            token_data = resp.json()
            access_token = token_data["access_token"]
            _cached_auth_headers = {"Authorization": f"Bearer {access_token}"}
            logger.info("Acquired Keycloak token for backend API calls")
            return _cached_auth_headers
        else:
            logger.warning(
                "Keycloak token request failed (%d) — using empty headers: %s",
                resp.status_code,
                resp.text[:200],
            )
    except Exception as exc:
        logger.warning(
            "Could not reach Keycloak at %s — assuming auth disabled: %s",
            keycloak_base_url,
            exc,
        )

    _cached_auth_headers = {}
    return _cached_auth_headers


def _check_sandbox_api_available() -> bool:
    """Check if the backend has the sandbox sessions API endpoint.

    Sends a request with auth headers (if available). Accepts 200 or 401
    as proof the endpoint exists (401 means auth is required but endpoint
    is registered). Only 404 means the endpoint is not deployed.
    """
    url = _get_backend_url()
    headers = _get_auth_headers()
    # Use verify=False at module-import time (SSL helpers defined later in file)
    ssl_env = os.environ.get("KEYCLOAK_VERIFY_SSL", "true").lower()
    ssl_verify = VERIFY_SSL if ssl_env in ("false", "0", "no") else True
    try:
        resp = httpx.get(
            f"{url}/api/v1/sandbox/team1/sessions",
            timeout=10,
            verify=ssl_verify,
            headers=headers,
        )
        # 404 = endpoint not registered; anything else = endpoint exists
        return resp.status_code != 404
    except Exception:
        return False


# Skip entire module if sandbox agents are not deployed
pytestmark = [
    pytest.mark.skipif(
        not os.getenv("SANDBOX_LEGION_URL") and not os.getenv("ENABLE_SANDBOX_TESTS"),
        reason="Sandbox agents not deployed (set SANDBOX_LEGION_URL or ENABLE_SANDBOX_TESTS)",
    ),
    pytest.mark.skipif(
        not _check_sandbox_api_available(),
        reason="Backend sandbox sessions API not available (needs backend rebuild from source)",
    ),
]


def _get_sandbox_legion_url() -> str:
    """Get the sandbox legion URL."""
    return os.getenv(
        "SANDBOX_LEGION_URL",
        "http://sandbox-legion.team1.svc.cluster.local:8000",
    )


def _is_openshift_from_config():
    config_file = os.getenv("KAGENTI_CONFIG_FILE")
    if not config_file:
        return False
    config_path = pathlib.Path(config_file)
    if not config_path.is_absolute():
        repo_root = pathlib.Path(__file__).parent.parent.parent.parent.parent
        config_path = repo_root / config_file
    if not config_path.exists():
        return False
    try:
        with open(config_path) as f:
            config = yaml.safe_load(f)
    except Exception:
        return False
    if config.get("openshift", False):
        return True
    charts = config.get("charts", {})
    return charts.get("kagenti-deps", {}).get("values", {}).get(
        "openshift", False
    ) or charts.get("kagenti", {}).get("values", {}).get("openshift", False)


def _get_ssl_context():
    import ssl

    from kagenti.tests.e2e.conftest import _fetch_openshift_ingress_ca

    # Honour KEYCLOAK_VERIFY_SSL=false — disable SSL verification entirely
    # (needed on HyperShift clusters with self-signed ingress certs).
    if os.environ.get("KEYCLOAK_VERIFY_SSL", "true").lower() in ("false", "0", "no"):
        return VERIFY_SSL

    if not _is_openshift_from_config():
        return True
    ca_path = os.getenv("OPENSHIFT_INGRESS_CA")
    if not ca_path or not pathlib.Path(ca_path).exists():
        ca_path = _fetch_ingress_ca()
    if not ca_path:
        ca_path = _fetch_openshift_ingress_ca()
    if not ca_path:
        # Fallback: disable verification when the CA cannot be obtained
        # (e.g. HyperShift clusters where the ingress CA configmap is absent).
        logger.warning(
            "Could not fetch OpenShift ingress CA — falling back to VERIFY_SSL=%s",
            VERIFY_SSL,
        )
        return VERIFY_SSL
    return ssl.create_default_context(cafile=ca_path)


def _fetch_ingress_ca():
    """Fetch OpenShift ingress CA from default-ingress-cert configmap."""
    import subprocess
    import tempfile

    for ns, cm, key in [
        ("kagenti-system", "kube-root-ca.crt", "ca.crt"),
        ("openshift-config-managed", "default-ingress-cert", "ca-bundle.crt"),
    ]:
        jsonpath = "{.data." + key.replace(".", "\\.") + "}"
        try:
            result = subprocess.run(
                [
                    "kubectl",
                    "get",
                    "configmap",
                    cm,
                    "-n",
                    ns,
                    "-o",
                    f"jsonpath={jsonpath}",
                ],
                capture_output=True,
                text=True,
                timeout=15,
            )
            if result.returncode == 0 and result.stdout.startswith("-----BEGIN"):
                f = tempfile.NamedTemporaryFile(
                    mode="w", suffix=".crt", delete=False, prefix="ingress-ca-"
                )
                f.write(result.stdout)
                f.close()
                return f.name
        except Exception:
            continue
    return None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _send_a2a_message(agent_url: str, text: str, context_id: str | None = None):
    """Send an A2A message to sandbox-legion and return the task result."""
    ssl_verify = _get_ssl_context()
    async with httpx.AsyncClient(timeout=120.0, verify=ssl_verify) as client:
        msg = {
            "jsonrpc": "2.0",
            "method": "message/send",
            "id": f"test-{uuid4().hex[:8]}",
            "params": {
                "message": {
                    "role": "user",
                    "parts": [{"kind": "text", "text": text}],
                    "messageId": uuid4().hex,
                }
            },
        }
        if context_id:
            msg["params"]["message"]["contextId"] = context_id

        resp = await client.post(f"{agent_url}/", json=msg)
        data = resp.json()
        if "error" in data:
            pytest.fail(f"A2A error: {data['error']}")
        return data.get("result", {})


# ---------------------------------------------------------------------------
# Polling helper — TaskStore commits asynchronously so tests must wait
# ---------------------------------------------------------------------------

_MAX_POLL_ATTEMPTS = 10
_POLL_INTERVAL_S = 2


async def _wait_for_session(
    backend_url: str,
    context_id: str,
    *,
    max_attempts: int = _MAX_POLL_ATTEMPTS,
    interval: float = _POLL_INTERVAL_S,
) -> dict | None:
    """Poll the sessions API until *context_id* appears, returning the detail.

    Uses exponential backoff and includes auth headers. Logs non-200
    status codes to aid debugging when the session never appears.
    """
    import asyncio

    ssl_verify = _get_ssl_context()
    headers = _get_auth_headers()
    last_status = None
    last_body = ""
    for attempt in range(max_attempts):
        # Exponential backoff capped at 15s
        delay = min(interval * (1.5**attempt), 15)
        await asyncio.sleep(delay)
        try:
            async with httpx.AsyncClient(timeout=30.0, verify=ssl_verify) as client:
                resp = await client.get(
                    f"{backend_url}/api/v1/sandbox/team1/sessions/{context_id}",
                    headers=headers,
                )
                last_status = resp.status_code
                if resp.status_code == 200:
                    return resp.json()
                if resp.status_code == 404:
                    # Session not yet in DB — keep polling
                    continue
                # Auth or server errors — log and keep trying (DB pool may
                # need time to initialise)
                last_body = resp.text[:300]
                logger.warning(
                    "Poll attempt %d/%d for session %s: HTTP %d — %s",
                    attempt + 1,
                    max_attempts,
                    context_id,
                    resp.status_code,
                    last_body,
                )
        except httpx.HTTPError as exc:
            last_status = None
            last_body = str(exc)
            logger.warning(
                "Poll attempt %d/%d for session %s: connection error — %s",
                attempt + 1,
                max_attempts,
                context_id,
                exc,
            )
    # Return None with a clear log message for the assertion
    logger.error(
        "Session %s not found after %d poll attempts (last status=%s, body=%s)",
        context_id,
        max_attempts,
        last_status,
        last_body[:200],
    )
    return None


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestSandboxSessionsAPI:
    """Test the backend /api/v1/sandbox/{namespace}/sessions endpoints."""

    @pytest.mark.asyncio
    async def test_session_persists_in_db(self):
        """Send A2A message, verify task appears in sessions API."""
        agent_url = _get_sandbox_legion_url()
        backend_url = _get_backend_url()

        result = await _send_a2a_message(agent_url, "Say: session-api-test")
        context_id = result.get("contextId", result.get("context_id"))
        assert context_id, f"No context_id in result: {result}"

        detail = await _wait_for_session(backend_url, context_id)
        assert detail is not None, (
            f"Session {context_id} not found after {_MAX_POLL_ATTEMPTS} attempts"
        )

    @pytest.mark.asyncio
    async def test_session_detail_has_history(self):
        """Verify session detail includes task history."""
        agent_url = _get_sandbox_legion_url()
        backend_url = _get_backend_url()

        result = await _send_a2a_message(agent_url, "Say: detail-test")
        context_id = result.get("contextId", result.get("context_id"))
        assert context_id

        detail = await _wait_for_session(backend_url, context_id)
        assert detail is not None, f"Session {context_id} not found"
        assert detail["context_id"] == context_id
        assert detail["kind"] == "task"
        assert "status" in detail
        # Verify the session actually has history content (not just an empty shell)
        history = detail.get("history", [])
        assert len(history) > 0, (
            f"Session {context_id} has no history entries — expected at least the user message"
        )

    @pytest.mark.asyncio
    async def test_session_list_search(self):
        """Verify search parameter filters by context_id."""
        backend_url = _get_backend_url()
        headers = _get_auth_headers()

        ssl_verify = _get_ssl_context()
        async with httpx.AsyncClient(timeout=30.0, verify=ssl_verify) as client:
            # Search for a non-existent context ID
            resp = await client.get(
                f"{backend_url}/api/v1/sandbox/team1/sessions",
                params={"search": "nonexistent-context-id-xyz"},
                headers=headers,
            )
            assert resp.status_code == 200, (
                f"List sessions failed: HTTP {resp.status_code} — {resp.text[:300]}"
            )
            data = resp.json()
            assert data["total"] == 0, "Search returned unexpected results"

    @pytest.mark.asyncio
    async def test_session_list_pagination(self):
        """Verify pagination parameters work correctly."""
        backend_url = _get_backend_url()
        headers = _get_auth_headers()

        ssl_verify = _get_ssl_context()
        async with httpx.AsyncClient(timeout=30.0, verify=ssl_verify) as client:
            resp = await client.get(
                f"{backend_url}/api/v1/sandbox/team1/sessions",
                params={"limit": 2, "offset": 0},
                headers=headers,
            )
            assert resp.status_code == 200, (
                f"List sessions failed: HTTP {resp.status_code} — {resp.text[:300]}"
            )
            data = resp.json()
            assert data["limit"] == 2
            assert data["offset"] == 0
            assert len(data["items"]) <= 2

    @pytest.mark.asyncio
    async def test_session_kill(self):
        """Send A2A message, then kill the session via API."""
        agent_url = _get_sandbox_legion_url()
        backend_url = _get_backend_url()
        headers = _get_auth_headers()

        result = await _send_a2a_message(agent_url, "Say: kill-test")
        context_id = result.get("contextId", result.get("context_id"))
        assert context_id

        # Wait for DB commit before operating
        detail = await _wait_for_session(backend_url, context_id)
        assert detail is not None, f"Session {context_id} not found before kill"

        ssl_verify = _get_ssl_context()
        async with httpx.AsyncClient(timeout=30.0, verify=ssl_verify) as client:
            resp = await client.post(
                f"{backend_url}/api/v1/sandbox/team1/sessions/{context_id}/kill",
                headers=headers,
            )
            assert resp.status_code == 200, (
                f"Kill failed: {resp.status_code} {resp.text}"
            )
            killed = resp.json()
            status = killed.get("status", {})
            state = status.get("state", "").lower()
            assert state in ("canceled", "cancelled", "failed"), (
                f"Kill should set state to canceled, got: {state!r} (full status: {status})"
            )

    @pytest.mark.asyncio
    async def test_session_delete(self):
        """Send A2A message, then delete the session via API."""
        agent_url = _get_sandbox_legion_url()
        backend_url = _get_backend_url()
        headers = _get_auth_headers()

        result = await _send_a2a_message(agent_url, "Say: delete-test")
        context_id = result.get("contextId", result.get("context_id"))
        assert context_id

        # Wait for DB commit before operating
        detail = await _wait_for_session(backend_url, context_id)
        assert detail is not None, f"Session {context_id} not found before delete"

        ssl_verify = _get_ssl_context()
        async with httpx.AsyncClient(timeout=30.0, verify=ssl_verify) as client:
            # Delete
            resp = await client.delete(
                f"{backend_url}/api/v1/sandbox/team1/sessions/{context_id}",
                headers=headers,
            )
            assert resp.status_code == 204, (
                f"Delete failed: HTTP {resp.status_code} — {resp.text[:300]}"
            )

            # Verify gone
            resp2 = await client.get(
                f"{backend_url}/api/v1/sandbox/team1/sessions/{context_id}",
                headers=headers,
            )
            assert resp2.status_code == 404

    @pytest.mark.asyncio
    async def test_session_not_found(self):
        """Verify 404 for non-existent session."""
        backend_url = _get_backend_url()
        headers = _get_auth_headers()

        ssl_verify = _get_ssl_context()
        async with httpx.AsyncClient(timeout=30.0, verify=ssl_verify) as client:
            resp = await client.get(
                f"{backend_url}/api/v1/sandbox/team1/sessions/nonexistent-id",
                headers=headers,
            )
            assert resp.status_code == 404, (
                f"Expected 404 but got HTTP {resp.status_code} — {resp.text[:300]}"
            )
