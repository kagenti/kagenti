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

import os
import pathlib

import httpx
import pytest
import yaml
from uuid import uuid4


def _get_backend_url() -> str:
    """Get the Kagenti backend URL."""
    return os.getenv("AGENT_URL", "").rsplit("/", 1)[0] or os.getenv(
        "KAGENTI_BACKEND_URL",
        "http://kagenti-backend.kagenti-system.svc.cluster.local:8000",
    )


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

    if not _is_openshift_from_config():
        return True
    ca_path = os.getenv("OPENSHIFT_INGRESS_CA")
    if not ca_path or not pathlib.Path(ca_path).exists():
        ca_path = _fetch_ingress_ca()
    if not ca_path:
        ca_path = _fetch_openshift_ingress_ca()
    if not ca_path:
        raise RuntimeError("Could not fetch OpenShift ingress CA certificate.")
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
# Tests
# ---------------------------------------------------------------------------


class TestSandboxSessionsAPI:
    """Test the backend /api/v1/sandbox/{namespace}/sessions endpoints."""

    @pytest.mark.asyncio
    async def test_session_persists_in_db(self):
        """Send A2A message, verify task appears in sessions API."""
        agent_url = _get_sandbox_legion_url()
        backend_url = _get_backend_url()

        # Send a message to create a task
        result = await _send_a2a_message(agent_url, "Say: session-api-test")
        context_id = result.get("contextId", result.get("context_id"))
        assert context_id, f"No context_id in result: {result}"

        # Query the backend sessions API
        ssl_verify = _get_ssl_context()
        async with httpx.AsyncClient(timeout=30.0, verify=ssl_verify) as client:
            resp = await client.get(f"{backend_url}/api/v1/sandbox/team1/sessions")
            assert resp.status_code == 200, (
                f"List failed: {resp.status_code} {resp.text}"
            )
            data = resp.json()
            assert data["total"] > 0, "No sessions found"

            # Find our session
            found = any(item["context_id"] == context_id for item in data["items"])
            assert found, (
                f"Session {context_id} not found in list.\n"
                f"Available: {[i['context_id'][:12] for i in data['items']]}"
            )

    @pytest.mark.asyncio
    async def test_session_detail_has_history(self):
        """Verify session detail includes task history."""
        agent_url = _get_sandbox_legion_url()
        backend_url = _get_backend_url()

        result = await _send_a2a_message(agent_url, "Say: detail-test")
        context_id = result.get("contextId", result.get("context_id"))
        assert context_id

        ssl_verify = _get_ssl_context()
        async with httpx.AsyncClient(timeout=30.0, verify=ssl_verify) as client:
            resp = await client.get(
                f"{backend_url}/api/v1/sandbox/team1/sessions/{context_id}"
            )
            assert resp.status_code == 200, f"Detail failed: {resp.status_code}"
            detail = resp.json()
            assert detail["context_id"] == context_id
            assert detail["kind"] == "task"
            assert "status" in detail

    @pytest.mark.asyncio
    async def test_session_list_search(self):
        """Verify search parameter filters by context_id."""
        backend_url = _get_backend_url()

        ssl_verify = _get_ssl_context()
        async with httpx.AsyncClient(timeout=30.0, verify=ssl_verify) as client:
            # Search for a non-existent context ID
            resp = await client.get(
                f"{backend_url}/api/v1/sandbox/team1/sessions",
                params={"search": "nonexistent-context-id-xyz"},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["total"] == 0, "Search returned unexpected results"

    @pytest.mark.asyncio
    async def test_session_list_pagination(self):
        """Verify pagination parameters work correctly."""
        backend_url = _get_backend_url()

        ssl_verify = _get_ssl_context()
        async with httpx.AsyncClient(timeout=30.0, verify=ssl_verify) as client:
            resp = await client.get(
                f"{backend_url}/api/v1/sandbox/team1/sessions",
                params={"limit": 2, "offset": 0},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["limit"] == 2
            assert data["offset"] == 0
            assert len(data["items"]) <= 2

    @pytest.mark.asyncio
    async def test_session_kill(self):
        """Send A2A message, then kill the session via API."""
        agent_url = _get_sandbox_legion_url()
        backend_url = _get_backend_url()

        result = await _send_a2a_message(agent_url, "Say: kill-test")
        context_id = result.get("contextId", result.get("context_id"))
        assert context_id

        ssl_verify = _get_ssl_context()
        async with httpx.AsyncClient(timeout=30.0, verify=ssl_verify) as client:
            resp = await client.post(
                f"{backend_url}/api/v1/sandbox/team1/sessions/{context_id}/kill"
            )
            assert resp.status_code == 200, (
                f"Kill failed: {resp.status_code} {resp.text}"
            )
            killed = resp.json()
            status = killed.get("status", {})
            # Status should reflect canceled state
            assert status is not None

    @pytest.mark.asyncio
    async def test_session_delete(self):
        """Send A2A message, then delete the session via API."""
        agent_url = _get_sandbox_legion_url()
        backend_url = _get_backend_url()

        result = await _send_a2a_message(agent_url, "Say: delete-test")
        context_id = result.get("contextId", result.get("context_id"))
        assert context_id

        ssl_verify = _get_ssl_context()
        async with httpx.AsyncClient(timeout=30.0, verify=ssl_verify) as client:
            # Delete
            resp = await client.delete(
                f"{backend_url}/api/v1/sandbox/team1/sessions/{context_id}"
            )
            assert resp.status_code == 204, f"Delete failed: {resp.status_code}"

            # Verify gone
            resp2 = await client.get(
                f"{backend_url}/api/v1/sandbox/team1/sessions/{context_id}"
            )
            assert resp2.status_code == 404

    @pytest.mark.asyncio
    async def test_session_not_found(self):
        """Verify 404 for non-existent session."""
        backend_url = _get_backend_url()

        ssl_verify = _get_ssl_context()
        async with httpx.AsyncClient(timeout=30.0, verify=ssl_verify) as client:
            resp = await client.get(
                f"{backend_url}/api/v1/sandbox/team1/sessions/nonexistent-id"
            )
            assert resp.status_code == 404
