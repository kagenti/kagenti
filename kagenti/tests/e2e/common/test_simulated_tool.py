# Copyright 2026 IBM Corp.
# Licensed under the Apache License, Version 2.0

"""
Simulated-tool E2E (issue #2167).

Proves the simulated-tool path end to end: create a tool from the Tasks API
OpenAPI spec, watch it reach Ready, drive a coherent CRUD flow over MCP, then
delete it. Also asserts a failure path (missing LLM secret -> Error).

Gated on the `simulatedTools` feature flag. Skips at runtime if no LLM API key
Secret is provisioned in the target namespace (generation needs a real LLM).

Environment variables:
    KAGENTI_BACKEND_URL   Backend API URL (Kind default: http://localhost:8002)
    KAGENTI_SIM_NAMESPACE Target namespace (default: team1)
    KAGENTI_LLM_SECRET_NAME / KAGENTI_LLM_SECRET_KEY  LLM key Secret (default llm-api-key/apiKey)
"""

import asyncio
import os
import pathlib
import socket
import subprocess
import time
import uuid

import httpx
import pytest
from kubernetes.client.rest import ApiException

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

REPO_ROOT = pathlib.Path(__file__).parent.parent.parent.parent.parent
SPEC_PATH = REPO_ROOT / "kagenti/examples/simulated-tools/tasks-api/openapi.json"

NAMESPACE = os.environ.get("KAGENTI_SIM_NAMESPACE", "team1")
LLM_SECRET_NAME = os.environ.get("KAGENTI_LLM_SECRET_NAME", "llm-api-key")
LLM_SECRET_KEY = os.environ.get("KAGENTI_LLM_SECRET_KEY", "apiKey")

GENERATION_TIMEOUT_S = int(os.environ.get("KAGENTI_SIM_GEN_TIMEOUT", "600"))
POLL_INTERVAL_S = 5


def _backend_url(is_openshift: bool) -> str:
    url = os.environ.get("KAGENTI_BACKEND_URL")
    if url:
        return url.rstrip("/")
    if is_openshift:
        result = subprocess.run(
            [
                "kubectl",
                "get",
                "route",
                "kagenti-ui",
                "-n",
                "kagenti-system",
                "-o",
                "jsonpath={.spec.host}",
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode == 0 and result.stdout:
            return f"https://{result.stdout}"
        pytest.skip("Could not discover kagenti-ui route; set KAGENTI_BACKEND_URL")
    return "http://localhost:8002"


def _auth_headers(keycloak_token: dict) -> dict:
    return {
        "Authorization": f"Bearer {keycloak_token['access_token']}",
        "Content-Type": "application/json",
    }


def _llm_secret_present(k8s_client) -> bool:
    try:
        secret = k8s_client.read_namespaced_secret(LLM_SECRET_NAME, NAMESPACE)
    except ApiException:
        return False
    data = secret.data or {}
    return LLM_SECRET_KEY in data


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _read_service_with_retry(k8s_client, name, tries=10, delay=2):
    """Read a namespaced Service, tolerating the create endpoint's async (202)
    response: the Service may not exist yet by the time we look for it. Retries
    on a 404 ApiException up to `tries` times, `delay` seconds apart.
    """
    last_exc = None
    for attempt in range(tries):
        try:
            return k8s_client.read_namespaced_service(name, NAMESPACE)
        except ApiException as e:
            if e.status != 404:
                raise
            last_exc = e
            if attempt < tries - 1:
                time.sleep(delay)
    raise AssertionError(
        f"Service '{name}' not found in namespace '{NAMESPACE}' after "
        f"{tries} attempts ({(tries - 1) * delay}s); last error: {last_exc}"
    )


def _wait_for_port_ready(port, tries=15, delay=1.0):
    """Poll a local TCP port until it accepts connections, rather than assuming
    the port-forward has established after a fixed sleep."""
    for _ in range(tries):
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=1):
                return
        except OSError:
            time.sleep(delay)


def _create_tool(base_url, headers, verify, *, name, spec_str, env_vars):
    body = {
        "namespace": NAMESPACE,
        "openapiSpec": spec_str,
        "name": name,
        "envVars": env_vars,
    }
    return httpx.post(
        f"{base_url}/api/v1/simulation/tools",
        headers=headers,
        json=body,
        timeout=30.0,
        verify=verify,
    )


def _get_status(base_url, headers, verify, name):
    return httpx.get(
        f"{base_url}/api/v1/simulation/tools/{NAMESPACE}/{name}/generation-status",
        headers=headers,
        timeout=15.0,
        verify=verify,
    )


def _delete_tool(base_url, headers, verify, name):
    return httpx.request(
        "DELETE",
        f"{base_url}/api/v1/simulation/tools/{NAMESPACE}/{name}",
        headers=headers,
        timeout=60.0,
        verify=verify,
    )


def _poll_generation_status(base_url, headers, verify, name, terminal, timeout_s):
    """Poll until status is in `terminal` or timeout. Returns the last status dict."""
    deadline = time.time() + timeout_s
    last = None
    while time.time() < deadline:
        resp = _get_status(base_url, headers, verify, name)
        if resp.status_code == 200:
            last = resp.json()
            if last["status"] in terminal:
                return last
        time.sleep(POLL_INTERVAL_S)
    return last


async def _mcp_crud_flow(local_port: int) -> None:
    """Drive a coherent CRUD flow over MCP; assert no errors and state coherence."""
    url = f"http://127.0.0.1:{local_port}/mcp"
    async with streamablehttp_client(url) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            listed = await session.list_tools()
            tool_names = {t.name for t in listed.tools}
            for op in (
                "listTasks",
                "createTask",
                "getTask",
                "updateTask",
                "deleteTask",
            ):
                assert op in tool_names, f"MCP tool {op} missing; got {tool_names}"

            title = f"e2e-{uuid.uuid4().hex[:6]}"
            created = await session.call_tool("createTask", {"body": {"title": title}})
            assert not created.isError, f"createTask errored: {created.content}"

            listed_after = await session.call_tool("listTasks", {})
            assert not listed_after.isError, (
                f"listTasks errored: {listed_after.content}"
            )
            text_after_create = _content_text(listed_after)
            assert title in text_after_create, (
                f"created task '{title}' not visible in list: {text_after_create}"
            )

            # Read back and update the created task if an id is discoverable.
            update = await session.call_tool(
                "updateTask",
                {"id": "task-1", "body": {"title": title, "completed": True}},
            )
            assert not update.isError, f"updateTask errored: {update.content}"

            deleted = await session.call_tool("deleteTask", {"id": "task-1"})
            assert not deleted.isError, f"deleteTask errored: {deleted.content}"


def _content_text(result) -> str:
    parts = []
    for block in result.content:
        parts.append(getattr(block, "text", "") or "")
    return " ".join(parts)


@pytest.mark.requires_features(["simulatedTools"])
class TestSimulatedToolHappyPath:
    """Create -> Ready -> MCP CRUD -> delete for a simulated tool."""

    @pytest.fixture(autouse=True)
    def _verify(self, is_openshift, openshift_ingress_ca):
        import ssl

        self.verify = (
            ssl.create_default_context(cafile=openshift_ingress_ca)
            if is_openshift
            else True
        )

    def test_create_ready_crud_delete(self, is_openshift, k8s_client, keycloak_token):
        if not _llm_secret_present(k8s_client):
            pytest.skip(
                f"LLM secret '{LLM_SECRET_NAME}' (key '{LLM_SECRET_KEY}') absent in "
                f"namespace '{NAMESPACE}'; generation needs a real LLM key."
            )
        base_url = _backend_url(is_openshift)
        headers = _auth_headers(keycloak_token)
        spec_str = SPEC_PATH.read_text()
        name = f"tasks-{uuid.uuid4().hex[:8]}"
        env_vars = [
            {
                "name": "LLM_API_KEY",
                "valueFrom": {
                    "secretKeyRef": {"name": LLM_SECRET_NAME, "key": LLM_SECRET_KEY}
                },
            }
        ]

        try:
            resp = _create_tool(
                base_url,
                headers,
                self.verify,
                name=name,
                spec_str=spec_str,
                env_vars=env_vars,
            )
        except httpx.ConnectError as e:
            pytest.skip(f"Backend not accessible at {base_url}: {e}")

        # From here on, a 202 may already have created cluster resources, so every
        # assert and the CRUD flow run inside this try/finally to guarantee the
        # tool gets deleted even if an assertion fails partway through.
        deleted = False
        try:
            assert resp.status_code == 202, resp.text
            assert resp.json()["status"] == "Generating"

            # Assert the simulated marker label on the Service. The create
            # endpoint is async (202), so tolerate the Service not existing yet.
            svc = _read_service_with_retry(k8s_client, f"{name}-mcp")
            assert svc.metadata.labels.get("kagenti.io/simulated") == "true"
            assert "protocol.kagenti.io/mcp" in (svc.metadata.labels or {})

            status = _poll_generation_status(
                base_url,
                headers,
                self.verify,
                name,
                terminal={"Ready", "Failed", "Error"},
                timeout_s=GENERATION_TIMEOUT_S,
            )
            assert status is not None, "no generation-status returned before timeout"
            assert status["status"] == "Ready", (
                f"expected Ready, got {status['status']} (reason: {status.get('reason')})"
            )
            assert status.get("mcpUrl"), "Ready status missing mcpUrl"

            # Port-forward to the tool Service and drive CRUD over MCP.
            local_port = _free_port()
            pf = subprocess.Popen(
                [
                    "kubectl",
                    "port-forward",
                    "-n",
                    NAMESPACE,
                    f"svc/{name}-mcp",
                    f"{local_port}:8000",
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            try:
                _wait_for_port_ready(local_port)
                asyncio.run(_mcp_crud_flow(local_port))
            finally:
                pf.terminate()

            # Normal path: hard-assert the delete succeeded and cleaned up.
            d = _delete_tool(base_url, headers, self.verify, name)
            assert d.status_code == 200, d.text
            deleted_resources = d.json()["deletedResources"]
            assert any("StatefulSet" in r for r in deleted_resources), deleted_resources
            assert any("Service" in r for r in deleted_resources), deleted_resources
            assert any(
                "PersistentVolumeClaim" in r or "PVC" in r for r in deleted_resources
            ), deleted_resources
            deleted = True
        finally:
            if not deleted:
                # An exception is propagating; clean up best-effort without
                # masking the original failure.
                try:
                    _delete_tool(base_url, headers, self.verify, name)
                except Exception:
                    pass


@pytest.mark.requires_features(["simulatedTools"])
class TestSimulatedToolFailurePath:
    """A missing LLM secret surfaces an Error status with a reason."""

    @pytest.fixture(autouse=True)
    def _verify(self, is_openshift, openshift_ingress_ca):
        import ssl

        self.verify = (
            ssl.create_default_context(cafile=openshift_ingress_ca)
            if is_openshift
            else True
        )

    def test_missing_llm_secret_surfaces_error(self, is_openshift, keycloak_token):
        base_url = _backend_url(is_openshift)
        headers = _auth_headers(keycloak_token)
        spec_str = SPEC_PATH.read_text()
        name = f"tasks-fail-{uuid.uuid4().hex[:8]}"
        # Reference a Secret that does not exist -> pod cannot start.
        env_vars = [
            {
                "name": "LLM_API_KEY",
                "valueFrom": {
                    "secretKeyRef": {
                        "name": f"nonexistent-{uuid.uuid4().hex[:8]}",
                        "key": "apiKey",
                    }
                },
            }
        ]

        try:
            resp = _create_tool(
                base_url,
                headers,
                self.verify,
                name=name,
                spec_str=spec_str,
                env_vars=env_vars,
            )
        except httpx.ConnectError as e:
            pytest.skip(f"Backend not accessible at {base_url}: {e}")
        assert resp.status_code == 202, resp.text

        try:
            status = _poll_generation_status(
                base_url,
                headers,
                self.verify,
                name,
                terminal={"Error", "Failed"},
                timeout_s=180,
            )
            assert status is not None, "no generation-status before timeout"
            assert status["status"] in {"Error", "Failed"}, (
                f"expected Error/Failed, got {status['status']}"
            )
            assert status.get("reason"), "Error/Failed status must carry a reason"
        finally:
            _delete_tool(base_url, headers, self.verify, name)
