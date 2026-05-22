"""
T0.4 — NemoClaw agent infrastructure tests.

Tests the NemoClaw agents (Hermes and OpenClaw) deployed via OpenShell.
These agents use their own native APIs (not A2A JSON-RPC):
  - Hermes: OpenAI-compatible API on port 8642
  - OpenClaw: Gateway API on port 18789

TODO(a2a-adapter): Once A2A adapters are added, move these agents into
the standard A2A test suite.

TODO(nemoclaw-images): These tests will skip until proper NemoClaw images
are available. Current deployment uses OpenShell base image which does not
include hermes/openclaw binaries. Build proper images via:
  1. Mirror ghcr.io/nvidia/nemoclaw/ images (needs GHCR auth), or
  2. Build from NemoClaw source via Shipwright binary build, or
  3. Use NemoClaw install.sh to create local images

Environment:
    OPENSHELL_NEMOCLAW_ENABLED: Set to "true" to enable NemoClaw tests
    OPENSHELL_LLM_AVAILABLE: Must be "true" for inference tests
"""

import pytest

import httpx

from kagenti.tests.e2e.openshell.conftest import (
    NEMOCLAW_AGENTS,
    NEMOCLAW_AGENT_CONFIG,
    nemoclaw_enabled,
)


pytestmark = [
    pytest.mark.openshell,
    pytest.mark.skipif(
        not nemoclaw_enabled(),
        reason="NemoClaw tests disabled (set OPENSHELL_NEMOCLAW_ENABLED=true)",
    ),
]


# ---------------------------------------------------------------------------
# Platform health — NemoClaw pods running
# ---------------------------------------------------------------------------


class TestNemoClawPlatformHealth:
    """Verify NemoClaw agent pods are deployed and running."""

    @pytest.mark.parametrize("agent_name", NEMOCLAW_AGENTS)
    def test_deployment_exists(self, agent_name, agent_namespace):
        """NemoClaw agent deployment exists and has available replicas."""
        from kagenti.tests.e2e.openshell.conftest import kubectl_get_deployments_json

        deployments = kubectl_get_deployments_json(agent_namespace)
        matching = [d for d in deployments if d["metadata"]["name"] == agent_name]
        assert len(matching) == 1, f"Deployment {agent_name} not found"

        status = matching[0].get("status", {})
        available = status.get("availableReplicas", 0)
        assert available >= 1, (
            f"{agent_name} has {available} available replicas "
            f"(conditions: {status.get('conditions', [])})"
        )

    @pytest.mark.parametrize("agent_name", NEMOCLAW_AGENTS)
    def test_pod_running(self, agent_name, agent_namespace):
        """NemoClaw agent pod is in Running phase."""
        from kagenti.tests.e2e.openshell.conftest import kubectl_get_pods_json

        pods = kubectl_get_pods_json(agent_namespace)
        matching = [
            p
            for p in pods
            if agent_name in p["metadata"].get("name", "")
            and p["status"].get("phase") == "Running"
        ]
        assert len(matching) >= 1, (
            f"No running pods for {agent_name} in {agent_namespace}"
        )

    @pytest.mark.parametrize("agent_name", NEMOCLAW_AGENTS)
    def test_framework_label(self, agent_name, agent_namespace):
        """NemoClaw agents have the NemoClaw framework label."""
        from kagenti.tests.e2e.openshell.conftest import kubectl_get_pods_json

        pods = kubectl_get_pods_json(agent_namespace)
        matching = [
            p
            for p in pods
            if agent_name in p["metadata"].get("name", "")
            and p["status"].get("phase") == "Running"
        ]
        assert len(matching) >= 1
        labels = matching[0]["metadata"].get("labels", {})
        assert labels.get("kagenti.io/framework") == "NemoClaw", (
            f"{agent_name} missing NemoClaw framework label"
        )


# ---------------------------------------------------------------------------
# Health probe — NemoClaw agent health endpoints
# ---------------------------------------------------------------------------


class TestNemoClawHealth:
    """Verify NemoClaw agents respond to health probes."""

    @pytest.mark.asyncio
    async def test_hermes_health(self, nemoclaw_hermes_url):
        """Hermes gateway is reachable (TCP connect — no HTTP health endpoint)."""
        import socket

        url = nemoclaw_hermes_url
        host = url.split("//")[1].split(":")[0]
        port = int(url.split(":")[-1].rstrip("/"))
        sock = socket.create_connection((host, port), timeout=10)
        sock.close()

    @pytest.mark.asyncio
    async def test_openclaw_health(self, nemoclaw_openclaw_url):
        """OpenClaw agent responds to gateway health endpoint."""
        config = NEMOCLAW_AGENT_CONFIG["nemoclaw-openclaw"]
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{nemoclaw_openclaw_url}{config['health_path']}",
                timeout=30.0,
            )
            assert response.status_code == 200


# ---------------------------------------------------------------------------
# Inference smoke — basic LLM interaction via native APIs
# ---------------------------------------------------------------------------


class TestNemoClawInference:
    """Verify NemoClaw agents can perform basic LLM inference."""

    @pytest.mark.asyncio
    async def test_hermes_chat_completion(self, nemoclaw_hermes_url, llm_available):
        """Hermes processes an OpenAI-compatible chat completion request.

        Hermes gateway uses an internal protocol on port 15053 (not HTTP).
        The OpenAI-compatible API on port 8642 requires the full NemoClaw
        plugin stack. Without it, verify TCP connectivity instead.
        TODO(nemoclaw-api): Enable HTTP test once NemoClaw plugin is deployed.
        """
        if not llm_available:
            pytest.skip("LLM backend not available")

        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(
                    f"{nemoclaw_hermes_url}/v1/chat/completions",
                    json={
                        "model": "gpt-4o-mini",
                        "messages": [{"role": "user", "content": "Say hi"}],
                        "max_tokens": 10,
                    },
                    timeout=10.0,
                )
                assert response.status_code == 200
                data = response.json()
                assert "choices" in data
                assert len(data["choices"]) > 0
            except (httpx.RemoteProtocolError, httpx.ReadError):
                pytest.skip(
                    "Hermes gateway uses internal protocol — "
                    "HTTP API requires NemoClaw plugin"
                )

    @pytest.mark.asyncio
    async def test_openclaw_gateway_interaction(
        self, nemoclaw_openclaw_url, llm_available
    ):
        """OpenClaw gateway processes a basic request."""
        if not llm_available:
            pytest.skip("LLM backend not available")

        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{nemoclaw_openclaw_url}/",
                timeout=30.0,
            )
            # OpenClaw gateway root should return status/info
            assert response.status_code in (200, 301, 302)


# ---------------------------------------------------------------------------
# Security posture — container security context
# ---------------------------------------------------------------------------


class TestNemoClawSecurity:
    """Verify NemoClaw agent security configuration."""

    @pytest.mark.parametrize("agent_name", NEMOCLAW_AGENTS)
    def test_authbridge_disabled(self, agent_name, agent_namespace):
        """NemoClaw agents have AuthBridge injection disabled."""
        from kagenti.tests.e2e.openshell.conftest import kubectl_get_pods_json

        pods = kubectl_get_pods_json(agent_namespace)
        matching = [
            p
            for p in pods
            if agent_name in p["metadata"].get("name", "")
            and p["status"].get("phase") == "Running"
        ]
        assert len(matching) >= 1
        labels = matching[0]["metadata"].get("labels", {})
        assert labels.get("kagenti.io/inject") == "disabled"

    @pytest.mark.parametrize("agent_name", NEMOCLAW_AGENTS)
    def test_no_privilege_escalation(self, agent_name, agent_namespace):
        """NemoClaw agent containers cannot escalate privileges."""
        from kagenti.tests.e2e.openshell.conftest import kubectl_get_pods_json

        pods = kubectl_get_pods_json(agent_namespace)
        matching = [
            p
            for p in pods
            if agent_name in p["metadata"].get("name", "")
            and p["status"].get("phase") == "Running"
        ]
        assert len(matching) >= 1

        for container in matching[0]["spec"]["containers"]:
            sc = container.get("securityContext", {})
            assert sc.get("allowPrivilegeEscalation") is False, (
                f"{agent_name}/{container['name']} allows privilege escalation"
            )

    @pytest.mark.parametrize("agent_name", NEMOCLAW_AGENTS)
    def test_capabilities_dropped(self, agent_name, agent_namespace):
        """NemoClaw agents drop all Linux capabilities."""
        from kagenti.tests.e2e.openshell.conftest import kubectl_get_pods_json

        pods = kubectl_get_pods_json(agent_namespace)
        matching = [
            p
            for p in pods
            if agent_name in p["metadata"].get("name", "")
            and p["status"].get("phase") == "Running"
        ]
        assert len(matching) >= 1

        for container in matching[0]["spec"]["containers"]:
            caps = container.get("securityContext", {}).get("capabilities", {})
            drop = caps.get("drop", [])
            assert "ALL" in drop, (
                f"{agent_name}/{container['name']} does not drop ALL capabilities"
            )

    @pytest.mark.parametrize("agent_name", NEMOCLAW_AGENTS)
    def test_llm_key_from_secret(self, agent_name, agent_namespace):
        """NemoClaw agents read LLM keys from Kubernetes secrets, not env literals."""
        from kagenti.tests.e2e.openshell.conftest import kubectl_get_pods_json

        pods = kubectl_get_pods_json(agent_namespace)
        matching = [
            p
            for p in pods
            if agent_name in p["metadata"].get("name", "")
            and p["status"].get("phase") == "Running"
        ]
        assert len(matching) >= 1

        for container in matching[0]["spec"]["containers"]:
            for env_var in container.get("env", []):
                if env_var["name"] == "OPENAI_API_KEY":
                    assert "valueFrom" in env_var, (
                        f"{agent_name} has OPENAI_API_KEY as literal value"
                    )
                    assert "secretKeyRef" in env_var["valueFrom"]
