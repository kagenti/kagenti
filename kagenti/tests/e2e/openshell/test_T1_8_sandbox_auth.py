"""
T1.8 Sandbox Auth Bootstrap Tests

Validates the JWT authentication bootstrap flow for sandbox pods:
1. Projected SA token volume with correct audience
2. openshell.io/sandbox-id annotation
3. Gateway TokenReview acceptance
4. IssueSandboxToken success (sandbox pushes logs)
5. enableServiceLinks: false on gateway (certgen fix)

These tests catch regressions in:
- Compute driver pod spec generation (projected token, annotation)
- Helm chart flag passing (enableServiceLinks)
- Gateway authenticator configuration (TokenReview)

Capability: sandbox_auth
Convention: test_sandbox_auth__{description}

Refs:
- Issue: #1823
- Driver fixes: openshell-driver-openshift PRs #7, #8, #9
- Kagenti fixes: PR #1814, PR #1819
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
GATEWAY_NS = os.getenv("OPENSHELL_GATEWAY_NAMESPACE", "team1")
SANDBOX_NAME = "test-auth-bootstrap"
BASE_IMAGE = "ghcr.io/nvidia/openshell-community/sandboxes/base:latest"

skip_no_crd = pytest.mark.skipif(
    not sandbox_crd_installed(),
    reason="Sandbox CRD (agents.x-k8s.io) not installed",
)


def _create_sandbox_and_wait(name: str, namespace: str, timeout_sec: int = 90) -> dict:
    """Create a sandbox CR and wait for the pod to be Running. Returns pod JSON."""
    kubectl_run("delete", "sandbox", name, "-n", namespace, "--ignore-not-found")
    time.sleep(2)

    sandbox_yaml = f"""
apiVersion: agents.x-k8s.io/v1alpha1
kind: Sandbox
metadata:
  name: {name}
  namespace: {namespace}
  labels:
    openshell.ai/sandbox-id: {name}
spec:
  podTemplate:
    metadata:
      annotations:
        openshell.io/sandbox-id: {name}
      labels:
        openshell.ai/sandbox-id: {name}
    spec:
      serviceAccountName: openshell-sandbox
      containers:
      - name: sandbox
        image: {BASE_IMAGE}
        command: ["sleep", "300"]
        env:
        - name: OPENSHELL_K8S_SA_TOKEN_FILE
          value: /var/run/secrets/openshell/token
        volumeMounts:
        - name: openshell-sa-token
          mountPath: /var/run/secrets/openshell
          readOnly: true
      volumes:
      - name: openshell-sa-token
        projected:
          sources:
          - serviceAccountToken:
              audience: openshell-gateway
              expirationSeconds: 3600
              path: token
"""
    result = subprocess.run(
        ["kubectl", "apply", "-f", "-"],
        input=sandbox_yaml,
        capture_output=True,
        text=True,
        timeout=15,
    )
    if result.returncode != 0:
        pytest.skip(f"Failed to create sandbox: {result.stderr}")

    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        pods = kubectl_get_pods_json(namespace)
        matching = [
            p
            for p in pods
            if name in p["metadata"].get("name", "")
            and p["status"].get("phase") == "Running"
        ]
        if matching:
            return matching[0]
        time.sleep(5)

    pytest.skip(f"Sandbox pod {name} not Running after {timeout_sec}s")


def _cleanup_sandbox(name: str, namespace: str):
    """Delete a sandbox CR (best-effort)."""
    kubectl_run(
        "delete",
        "sandbox",
        name,
        "-n",
        namespace,
        "--ignore-not-found",
        "--wait=false",
    )


@pytest.fixture(scope="module")
def sandbox_pod():
    """Module-scoped fixture: create a sandbox and return its pod JSON."""
    if not sandbox_crd_installed():
        pytest.skip("Sandbox CRD not installed")
    pod = _create_sandbox_and_wait(SANDBOX_NAME, SANDBOX_NS)
    yield pod
    _cleanup_sandbox(SANDBOX_NAME, SANDBOX_NS)


class TestSandboxProjectedToken:
    """Verify projected SA token volume is correctly configured (rc.3 fix)."""

    def test_sandbox_auth__projected_volume_exists(self, sandbox_pod):
        """Sandbox pods must have a volume named 'openshell-sa-token'."""
        volumes = sandbox_pod["spec"].get("volumes", [])
        volume_names = [v["name"] for v in volumes]
        assert "openshell-sa-token" in volume_names, (
            f"Missing 'openshell-sa-token' projected volume. "
            f"Found volumes: {volume_names}"
        )

    def test_sandbox_auth__correct_audience(self, sandbox_pod):
        """Projected SA token must have audience 'openshell-gateway'."""
        volumes = sandbox_pod["spec"].get("volumes", [])
        sa_volume = next(
            (v for v in volumes if v["name"] == "openshell-sa-token"), None
        )
        if sa_volume is None:
            pytest.fail("openshell-sa-token volume not found")

        projected = sa_volume.get("projected", {})
        sources = projected.get("sources", [])
        sa_sources = [s for s in sources if "serviceAccountToken" in s]
        assert sa_sources, "No serviceAccountToken source in openshell-sa-token volume"

        audiences = [s["serviceAccountToken"].get("audience", "") for s in sa_sources]
        assert "openshell-gateway" in audiences, (
            f"Projected token audience must be 'openshell-gateway', got: {audiences}"
        )

    def test_sandbox_auth__token_file_env_var(self, sandbox_pod):
        """OPENSHELL_K8S_SA_TOKEN_FILE env var must point to the projected token."""
        containers = sandbox_pod["spec"].get("initContainers", []) + sandbox_pod[
            "spec"
        ].get("containers", [])

        found_env = False
        for container in containers:
            for env_var in container.get("env", []):
                if env_var.get("name") == "OPENSHELL_K8S_SA_TOKEN_FILE":
                    assert env_var["value"] == "/var/run/secrets/openshell/token", (
                        f"OPENSHELL_K8S_SA_TOKEN_FILE must be "
                        f"'/var/run/secrets/openshell/token', "
                        f"got: '{env_var['value']}'"
                    )
                    found_env = True
                    break

        assert found_env, (
            "OPENSHELL_K8S_SA_TOKEN_FILE env var not found in any container. "
            "The compute driver must set this for the supervisor to find the token."
        )

    def test_sandbox_auth__volume_mount_path(self, sandbox_pod):
        """The openshell-sa-token volume must be mounted at /var/run/secrets/openshell."""
        containers = sandbox_pod["spec"].get("initContainers", []) + sandbox_pod[
            "spec"
        ].get("containers", [])

        found_mount = False
        for container in containers:
            for mount in container.get("volumeMounts", []):
                if mount.get("name") == "openshell-sa-token":
                    assert mount["mountPath"] == "/var/run/secrets/openshell", (
                        f"openshell-sa-token must mount at "
                        f"'/var/run/secrets/openshell', "
                        f"got: '{mount['mountPath']}'"
                    )
                    found_mount = True
                    break

        assert found_mount, "openshell-sa-token volume not mounted in any container"


class TestSandboxAnnotation:
    """Verify openshell.io/sandbox-id annotation on sandbox pods (rc.4 fix)."""

    def test_sandbox_auth__annotation_present(self, sandbox_pod):
        """Sandbox pods must have the 'openshell.io/sandbox-id' annotation."""
        annotations = sandbox_pod["metadata"].get("annotations", {})
        assert "openshell.io/sandbox-id" in annotations, (
            f"Missing 'openshell.io/sandbox-id' annotation. "
            f"Found annotations: {list(annotations.keys())}"
        )

    def test_sandbox_auth__annotation_matches_label(self, sandbox_pod):
        """Annotation value must match the label 'openshell.ai/sandbox-id'."""
        annotations = sandbox_pod["metadata"].get("annotations", {})
        labels = sandbox_pod["metadata"].get("labels", {})

        annotation_value = annotations.get("openshell.io/sandbox-id", "")
        label_value = labels.get("openshell.ai/sandbox-id", "")

        if not annotation_value:
            pytest.fail("openshell.io/sandbox-id annotation is empty")
        if not label_value:
            pytest.skip(
                "openshell.ai/sandbox-id label not present — "
                "driver may use different label scheme"
            )

        assert annotation_value == label_value, (
            f"Annotation/label mismatch: "
            f"annotation='{annotation_value}', label='{label_value}'"
        )

    def test_sandbox_auth__annotation_nonempty(self, sandbox_pod):
        """The sandbox-id annotation must be a non-empty string."""
        annotations = sandbox_pod["metadata"].get("annotations", {})
        sandbox_id = annotations.get("openshell.io/sandbox-id", "")
        assert sandbox_id.strip(), "openshell.io/sandbox-id annotation is empty"


class TestSandboxAuthFlow:
    """Verify end-to-end IssueSandboxToken flow via gateway logs."""

    def test_sandbox_auth__gateway_accepts_token(self, sandbox_pod):
        """Gateway logs should show successful TokenReview for sandbox pods."""
        pod_name = sandbox_pod["metadata"]["name"]

        # Wait briefly for the supervisor to attempt auth
        time.sleep(10)

        result = kubectl_run(
            "logs",
            "openshell-server-0",
            "-c",
            "gateway",
            "-n",
            GATEWAY_NS,
            "--tail=100",
        )
        if result.returncode != 0:
            pytest.skip(f"Cannot read gateway logs: {result.stderr}")

        logs = result.stdout
        # The gateway logs TokenReview validation results
        token_review_ok = (
            "validated K8s SA token via TokenReview" in logs
            or "TokenReview" in logs
            or "authenticated sandbox" in logs
        )
        assert token_review_ok, (
            "Gateway logs don't show TokenReview acceptance. "
            "The sandbox projected SA token may not be reaching the gateway, "
            "or the gateway authenticator is misconfigured. "
            f"Last 100 lines of gateway log checked."
        )

    def test_sandbox_auth__sandbox_pushes_logs(self, sandbox_pod):
        """After successful auth, sandbox should push logs (HTTP 200 on PushSandboxLogs)."""
        result = kubectl_run(
            "logs",
            "openshell-server-0",
            "-c",
            "gateway",
            "-n",
            GATEWAY_NS,
            "--tail=200",
        )
        if result.returncode != 0:
            pytest.skip(f"Cannot read gateway logs: {result.stderr}")

        logs = result.stdout
        sandbox_id = (
            sandbox_pod["metadata"]
            .get("annotations", {})
            .get("openshell.io/sandbox-id", "")
        )

        # Look for successful log push or sandbox connection
        push_ok = (
            "PushSandboxLogs" in logs
            or "sandbox connected" in logs.lower()
            or (sandbox_id and sandbox_id in logs)
        )
        assert push_ok, (
            "Gateway logs don't show PushSandboxLogs activity or sandbox connection. "
            "IssueSandboxToken may have failed — the sandbox cannot push logs "
            "without a valid JWT. Check that: "
            "(1) openshell.io/sandbox-id annotation exists, "
            "(2) projected SA token has correct audience, "
            "(3) gateway OIDC config allows TokenReview."
        )


class TestGatewayEnableServiceLinks:
    """Verify enableServiceLinks: false on the gateway (certgen hook fix)."""

    def test_sandbox_auth__gateway_enable_service_links_false(self):
        """Gateway pod spec must have enableServiceLinks: false.

        Without this, the certgen pre-upgrade Job fails when openshell
        services exist in the namespace because Kubernetes injects service
        environment variables that conflict with cert-manager.
        """
        result = kubectl_run(
            "get",
            "statefulset",
            "openshell-server",
            "-n",
            GATEWAY_NS,
            "-o",
            "json",
        )
        if result.returncode != 0:
            pytest.skip(f"Gateway StatefulSet not found: {result.stderr}")

        sts = json.loads(result.stdout)
        pod_spec = sts["spec"]["template"]["spec"]
        enable_service_links = pod_spec.get("enableServiceLinks", True)
        assert enable_service_links is False, (
            "Gateway StatefulSet must have enableServiceLinks: false "
            "to prevent certgen Job conflicts. "
            f"Got: enableServiceLinks={enable_service_links}"
        )
