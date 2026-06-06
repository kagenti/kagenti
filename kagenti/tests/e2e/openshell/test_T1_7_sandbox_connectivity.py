"""
Sandbox Connectivity E2E Tests (MVP Validation Criterion #2)

Validates that interactive sessions can be established with sandboxes:
- Gateway API is reachable and responds
- Sandbox pods support kubectl exec (compute driver mechanism)
- Sandbox containers can run commands interactively

This is the E2E equivalent of ``openshell term`` — verifying that the
infrastructure for interactive access is functional.
"""

import os
import subprocess
import time

import pytest

from kagenti.tests.e2e.openshell.conftest import (
    find_free_port,
    kubectl_get_pods_json,
    kubectl_run,
)

pytestmark = [pytest.mark.openshell, pytest.mark.mvp]

SANDBOX_NS = os.getenv("OPENSHELL_AGENT_NAMESPACE", "team1")


class TestGatewayConnectivity:
    """Verify gateway is reachable and accepting connections."""

    def test_gateway_pod_running(self):
        """Gateway StatefulSet has at least one running pod."""
        pods = kubectl_get_pods_json(SANDBOX_NS)
        gateway_pods = [
            p
            for p in pods
            if p["metadata"]["name"].startswith("openshell-server")
            and p["status"].get("phase") == "Running"
        ]
        assert gateway_pods, f"No running openshell-server pod in {SANDBOX_NS}"

    def test_gateway_service_has_endpoints(self):
        """Gateway service has at least one ready endpoint."""
        result = kubectl_run(
            "get",
            "endpoints",
            "openshell-server",
            "-n",
            SANDBOX_NS,
            "-o",
            "jsonpath={.subsets[0].addresses[0].ip}",
        )
        assert result.returncode == 0 and result.stdout.strip(), (
            f"openshell-server service in {SANDBOX_NS} has no endpoints"
        )

    def test_gateway_port_forward_reachable(self):
        """Gateway responds to HTTP requests via port-forward."""
        import socket

        local_port = find_free_port()
        proc = subprocess.Popen(
            [
                "kubectl",
                "port-forward",
                "svc/openshell-server",
                f"{local_port}:8080",
                "-n",
                SANDBOX_NS,
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
                    return  # Success — port is reachable
                except (ConnectionRefusedError, OSError):
                    continue

            pytest.fail("Gateway port 8080 not reachable via port-forward")
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()


class TestSandboxExec:
    """Verify interactive command execution inside sandbox pods.

    Uses an existing running pod in the namespace rather than creating a
    new one — the namespace has a ResourceQuota (sandbox-quota) that limits
    pod count, and the deployed agents already fill the quota.
    """

    # Gateway images (v0.0.56+) are distroless — no shell or coreutils.
    # Skip these when looking for a pod to exec into.
    _DISTROLESS_PREFIXES = ("openshell-server",)

    def _find_exec_pod(self) -> tuple[str, str] | None:
        """Find a running pod with a ready container suitable for exec testing.

        Skips distroless pods (gateway) that lack a shell. Selects the first
        pod where the target container is actually ready.
        """
        pods = kubectl_get_pods_json(SANDBOX_NS)
        running = [p for p in pods if p["status"].get("phase") == "Running"]
        for pod in running:
            name = pod["metadata"]["name"]
            if any(name.startswith(pfx) for pfx in self._DISTROLESS_PREFIXES):
                continue
            containers = pod["spec"].get("containers", [])
            if not containers:
                continue
            container_name = containers[0]["name"]
            ready_containers = {
                cs["name"]
                for cs in pod["status"].get("containerStatuses", [])
                if cs.get("ready")
            }
            if container_name in ready_containers:
                return name, container_name
        return None

    def test_sandbox_exec_basic(self):
        """Execute a command inside a running pod (validates exec mechanism)."""
        target = self._find_exec_pod()
        if not target:
            pytest.skip(f"No running pod in {SANDBOX_NS} for exec test")

        pod_name, container = target
        exec_result = subprocess.run(
            [
                "kubectl",
                "exec",
                pod_name,
                "-n",
                SANDBOX_NS,
                "-c",
                container,
                "--",
                "echo",
                "hello-from-sandbox",
            ],
            capture_output=True,
            text=True,
            timeout=15,
        )
        assert exec_result.returncode == 0, f"kubectl exec failed: {exec_result.stderr}"
        assert "hello-from-sandbox" in exec_result.stdout

    def test_sandbox_exec_shell_interactive(self):
        """Sandbox supports shell command execution (simulates terminal session)."""
        target = self._find_exec_pod()
        if not target:
            pytest.skip(f"No running pod in {SANDBOX_NS} for exec test")

        pod_name, container = target
        exec_result = subprocess.run(
            [
                "kubectl",
                "exec",
                pod_name,
                "-n",
                SANDBOX_NS,
                "-c",
                container,
                "--",
                "sh",
                "-c",
                "id -u && pwd && echo SESSION_OK",
            ],
            capture_output=True,
            text=True,
            timeout=15,
        )
        assert exec_result.returncode == 0, f"Shell exec failed: {exec_result.stderr}"
        assert "SESSION_OK" in exec_result.stdout
