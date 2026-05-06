"""
Sandbox Connectivity E2E Tests (MVP Validation Criterion #2)

Validates that interactive sessions can be established with sandboxes:
- Gateway API is reachable and responds
- Sandbox pods support kubectl exec (compute driver mechanism)
- Sandbox containers can run commands interactively

This is the E2E equivalent of ``openshell term`` — verifying that the
infrastructure for interactive access is functional.
"""

import json
import os
import subprocess
import time

import pytest

from kagenti.tests.e2e.openshell.conftest import (
    kubectl_get_pods_json,
    kubectl_run,
    sandbox_crd_installed,
)

pytestmark = [pytest.mark.openshell, pytest.mark.mvp]

SANDBOX_NS = os.getenv("OPENSHELL_AGENT_NAMESPACE", "team1")
BASE_IMAGE = "ghcr.io/nvidia/openshell-community/sandboxes/base:latest"
SANDBOX_NAME = "test-connectivity-exec"

skip_no_crd = pytest.mark.skipif(
    not sandbox_crd_installed(),
    reason="Sandbox CRD (agents.x-k8s.io) not installed",
)


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

        local_port = _find_free_port()
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
            proc.wait()


class TestSandboxExec:
    """Verify interactive command execution inside sandbox pods."""

    @skip_no_crd
    def test_create_sandbox_and_exec(self):
        """Create a sandbox pod and execute a command inside it."""
        # Cleanup
        kubectl_run(
            "delete",
            "sandbox",
            SANDBOX_NAME,
            "-n",
            SANDBOX_NS,
            "--ignore-not-found",
            "--wait=false",
        )
        time.sleep(2)

        sandbox_yaml = f"""
apiVersion: agents.x-k8s.io/v1alpha1
kind: Sandbox
metadata:
  name: {SANDBOX_NAME}
  namespace: {SANDBOX_NS}
spec:
  podTemplate:
    spec:
      containers:
      - name: sandbox
        image: {BASE_IMAGE}
        command: ["sleep", "120"]
"""
        result = subprocess.run(
            ["kubectl", "apply", "-f", "-"],
            input=sandbox_yaml,
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0, f"Failed to create sandbox: {result.stderr}"

        # Wait for pod to be Running
        pod_name = None
        deadline = time.time() + 60
        while time.time() < deadline:
            pods = kubectl_get_pods_json(SANDBOX_NS)
            matching = [
                p
                for p in pods
                if SANDBOX_NAME in p["metadata"].get("name", "")
                and p["status"].get("phase") == "Running"
            ]
            if matching:
                pod_name = matching[0]["metadata"]["name"]
                break
            time.sleep(3)

        assert pod_name, f"Sandbox pod did not reach Running state within 60s"

        try:
            # Execute a command inside the sandbox
            exec_result = subprocess.run(
                [
                    "kubectl",
                    "exec",
                    pod_name,
                    "-n",
                    SANDBOX_NS,
                    "-c",
                    "sandbox",
                    "--",
                    "echo",
                    "hello-from-sandbox",
                ],
                capture_output=True,
                text=True,
                timeout=15,
            )
            assert exec_result.returncode == 0, (
                f"kubectl exec failed: {exec_result.stderr}"
            )
            assert "hello-from-sandbox" in exec_result.stdout

        finally:
            kubectl_run(
                "delete",
                "sandbox",
                SANDBOX_NAME,
                "-n",
                SANDBOX_NS,
                "--ignore-not-found",
                "--wait=false",
            )

    @skip_no_crd
    def test_sandbox_exec_shell_interactive(self):
        """Sandbox supports shell command execution (simulates terminal session)."""
        # Use an existing running sandbox pod if available
        pods = kubectl_get_pods_json(SANDBOX_NS)
        sandbox_pods = [
            p
            for p in pods
            if "sandbox" in p["metadata"].get("name", "").lower()
            and p["status"].get("phase") == "Running"
        ]

        if not sandbox_pods:
            pytest.skip("No running sandbox pod available for exec test")

        pod_name = sandbox_pods[0]["metadata"]["name"]
        container = sandbox_pods[0]["spec"]["containers"][0]["name"]

        # Run a multi-command shell script to simulate interactive session
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
                "whoami && pwd && echo SESSION_OK",
            ],
            capture_output=True,
            text=True,
            timeout=15,
        )
        assert exec_result.returncode == 0, f"Shell exec failed: {exec_result.stderr}"
        assert "SESSION_OK" in exec_result.stdout


def _find_free_port() -> int:
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        return s.getsockname()[1]
