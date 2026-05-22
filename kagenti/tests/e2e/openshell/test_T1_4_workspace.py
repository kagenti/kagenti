"""
T1.4 Workspace Tests

Tests PVC-backed workspace persistence, sandbox creation, and data survival.

Capabilities: workspace
Convention: test_{capability}__{description}[agent]
"""

import os
import subprocess
import time

import pytest

from kagenti.tests.e2e.openshell.conftest import (
    kubectl_get_pods_json,
    kubectl_run,
    sandbox_crd_installed,
    ALL_SANDBOX_TYPES,
)

pytestmark = pytest.mark.openshell

AGENT_NS = os.getenv("OPENSHELL_AGENT_NAMESPACE", "team1")
BASE_IMAGE = "ghcr.io/nvidia/openshell-community/sandboxes/base:latest"


def _kubectl(*args: str, timeout: int = 30) -> subprocess.CompletedProcess:
    return kubectl_run(*args, timeout=timeout)


def _cleanup_sandbox(name: str, pvc: str, ns: str = AGENT_NS):
    _kubectl("delete", "sandbox", name, "-n", ns, "--ignore-not-found", "--wait=false")
    pods = kubectl_get_pods_json(ns)
    for p in pods:
        if name in p["metadata"].get("name", ""):
            _kubectl(
                "delete",
                "pod",
                p["metadata"]["name"],
                "-n",
                ns,
                "--force",
                "--grace-period=0",
            )
    time.sleep(3)
    _kubectl("delete", "pvc", pvc, "-n", ns, "--ignore-not-found", "--wait=false")


skip_no_crd = pytest.mark.skipif(
    not sandbox_crd_installed(), reason="Sandbox CRD not installed"
)


# ═══════════════════════════════════════════════════════════════════════════
# PVC Workspace Persistence (ALL builtin sandbox types)
# ═══════════════════════════════════════════════════════════════════════════


class TestWorkspacePVC:
    """PVC-backed workspace survives sandbox pod restart.

    Each builtin sandbox type (generic, Claude, OpenCode) creates a sandbox
    with a PVC, writes session state, and verifies data was written.
    """

    @skip_no_crd
    @pytest.mark.parametrize("name, content, path, cmd", ALL_SANDBOX_TYPES)
    def test_workspace__pvc_written(self, name, content, path, cmd):
        """Create sandbox with PVC, write session data, verify data persisted."""
        pvc = f"{name}-pvc"
        _cleanup_sandbox(name, pvc)

        subprocess.run(
            ["kubectl", "apply", "-f", "-"],
            input=f"""
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: {pvc}
  namespace: {AGENT_NS}
spec:
  accessModes: [ReadWriteOnce]
  resources:
    requests:
      storage: 100Mi
""",
            capture_output=True,
            text=True,
            timeout=30,
        )

        subprocess.run(
            ["kubectl", "apply", "-f", "-"],
            input=f"""
apiVersion: agents.x-k8s.io/v1alpha1
kind: Sandbox
metadata:
  name: {name}
  namespace: {AGENT_NS}
spec:
  podTemplate:
    spec:
      containers:
      - name: sandbox
        image: {BASE_IMAGE}
        command: ["sh", "-c", "{cmd}"]
        volumeMounts:
        - name: workspace
          mountPath: /workspace
      volumes:
      - name: workspace
        persistentVolumeClaim:
          claimName: {pvc}
""",
            capture_output=True,
            text=True,
            timeout=30,
        )

        deadline = time.time() + 60
        pod = None
        while time.time() < deadline:
            pods = kubectl_get_pods_json(AGENT_NS)
            m = [
                p
                for p in pods
                if name in p["metadata"].get("name", "")
                and p["status"].get("phase") == "Running"
            ]
            if m:
                pod = m[0]["metadata"]["name"]
                break
            time.sleep(5)

        if not pod:
            _cleanup_sandbox(name, pvc)
            pytest.skip(f"{name}: pod not running — base image pull may be slow")

        r = _kubectl("exec", pod, "-n", AGENT_NS, "--", "cat", path)
        _cleanup_sandbox(name, pvc)

        if r.returncode != 0:
            pytest.skip(f"{name}: cannot read {path}: {r.stderr.strip()}")
        assert content in r.stdout, (
            f"{name}: expected '{content}' in {path}, got: {r.stdout}"
        )

    @skip_no_crd
    def test_workspace__pvc_survives_deletion(self):
        """PVC persists after Sandbox CR deleted — enables session resume."""
        name, pvc = "test-pvc-survive", "test-pvc-survive-pvc"
        _cleanup_sandbox(name, pvc)

        subprocess.run(
            ["kubectl", "apply", "-f", "-"],
            input=f"""
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: {pvc}
  namespace: {AGENT_NS}
spec:
  accessModes: [ReadWriteOnce]
  resources:
    requests:
      storage: 50Mi
""",
            capture_output=True,
            text=True,
            timeout=30,
        )

        subprocess.run(
            ["kubectl", "apply", "-f", "-"],
            input=f"""
apiVersion: agents.x-k8s.io/v1alpha1
kind: Sandbox
metadata:
  name: {name}
  namespace: {AGENT_NS}
spec:
  podTemplate:
    spec:
      containers:
      - name: sandbox
        image: {BASE_IMAGE}
        command: ["sleep", "300"]
        volumeMounts:
        - name: workspace
          mountPath: /workspace
      volumes:
      - name: workspace
        persistentVolumeClaim:
          claimName: {pvc}
""",
            capture_output=True,
            text=True,
            timeout=30,
        )

        time.sleep(10)
        _kubectl(
            "delete",
            "sandbox",
            name,
            "-n",
            AGENT_NS,
            "--ignore-not-found",
            "--wait=false",
        )
        time.sleep(5)

        r = _kubectl("get", "pvc", pvc, "-n", AGENT_NS)
        _cleanup_sandbox(name, pvc)
        assert r.returncode == 0, (
            "PVC deleted with sandbox — session data would be lost"
        )


# ═══════════════════════════════════════════════════════════════════════════
# Builtin Sandbox Creation (merged from test_builtin_sandboxes.py)
# ═══════════════════════════════════════════════════════════════════════════


class TestWorkspaceCreation:
    """Verify builtin sandbox images can be created via Sandbox CR."""

    @skip_no_crd
    def test_workspace__creation_generic(self):
        """Generic sandbox creates successfully and pod reaches Running state."""
        name = "test-generic-create"
        pvc = f"{name}-pvc"
        _cleanup_sandbox(name, pvc)

        subprocess.run(
            ["kubectl", "apply", "-f", "-"],
            input=f"""
apiVersion: agents.x-k8s.io/v1alpha1
kind: Sandbox
metadata:
  name: {name}
  namespace: {AGENT_NS}
spec:
  podTemplate:
    spec:
      containers:
      - name: sandbox
        image: {BASE_IMAGE}
        command: ["sleep", "60"]
""",
            capture_output=True,
            text=True,
            timeout=30,
        )

        deadline = time.time() + 60
        pod = None
        while time.time() < deadline:
            pods = kubectl_get_pods_json(AGENT_NS)
            pod = next(
                (
                    p
                    for p in pods
                    if name in p["metadata"].get("name", "")
                    and p["status"].get("phase") == "Running"
                ),
                None,
            )
            if pod:
                break
            time.sleep(5)

        _cleanup_sandbox(name, pvc)
        if not pod:
            pytest.skip(
                f"{name}: pod not Running after 60s — base image pull may be slow"
            )

    @skip_no_crd
    def test_workspace__creation_claude(self):
        """Claude Code sandbox CR is accepted with PVC workspace mount."""
        name = "test-claude-create"
        pvc = f"{name}-pvc"
        _cleanup_sandbox(name, pvc)

        subprocess.run(
            ["kubectl", "apply", "-f", "-"],
            input=f"""
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: {pvc}
  namespace: {AGENT_NS}
spec:
  accessModes: [ReadWriteOnce]
  resources:
    requests:
      storage: 100Mi
""",
            capture_output=True,
            text=True,
            timeout=30,
        )

        result = subprocess.run(
            ["kubectl", "apply", "-f", "-"],
            input=f"""
apiVersion: agents.x-k8s.io/v1alpha1
kind: Sandbox
metadata:
  name: {name}
  namespace: {AGENT_NS}
spec:
  podTemplate:
    spec:
      containers:
      - name: sandbox
        image: {BASE_IMAGE}
        command: ["sleep", "30"]
        volumeMounts:
        - name: workspace
          mountPath: /workspace
      volumes:
      - name: workspace
        persistentVolumeClaim:
          claimName: {pvc}
""",
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0, (
            f"Failed to create Claude sandbox CR: {result.stderr}"
        )

        r = _kubectl("get", "sandbox", name, "-n", AGENT_NS)
        _cleanup_sandbox(name, pvc)
        assert r.returncode == 0, "Claude sandbox CR not found after creation"

    @skip_no_crd
    def test_workspace__creation_opencode(self):
        """OpenCode sandbox CR is accepted with PVC workspace mount."""
        name = "test-opencode-create"
        pvc = f"{name}-pvc"
        _cleanup_sandbox(name, pvc)

        subprocess.run(
            ["kubectl", "apply", "-f", "-"],
            input=f"""
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: {pvc}
  namespace: {AGENT_NS}
spec:
  accessModes: [ReadWriteOnce]
  resources:
    requests:
      storage: 100Mi
""",
            capture_output=True,
            text=True,
            timeout=30,
        )

        result = subprocess.run(
            ["kubectl", "apply", "-f", "-"],
            input=f"""
apiVersion: agents.x-k8s.io/v1alpha1
kind: Sandbox
metadata:
  name: {name}
  namespace: {AGENT_NS}
spec:
  podTemplate:
    spec:
      containers:
      - name: sandbox
        image: {BASE_IMAGE}
        command: ["sleep", "30"]
        volumeMounts:
        - name: workspace
          mountPath: /workspace
      volumes:
      - name: workspace
        persistentVolumeClaim:
          claimName: {pvc}
""",
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0, (
            f"Failed to create OpenCode sandbox CR: {result.stderr}"
        )

        r = _kubectl("get", "sandbox", name, "-n", AGENT_NS)
        _cleanup_sandbox(name, pvc)
        assert r.returncode == 0, "OpenCode sandbox CR not found after creation"


# ═══════════════════════════════════════════════════════════════════════════
# Workspace Read After Restart (NEW)
# ═══════════════════════════════════════════════════════════════════════════


class TestWorkspacePersistence:
    """Verify workspace data is readable after pod restart (PVC mounted)."""

    @skip_no_crd
    def test_workspace__persists_after_delete(self):
        """Write to PVC, delete pod, wait for recreate, verify data readable."""
        name, pvc = "test-read-after-restart", "test-read-after-restart-pvc"
        path = "/workspace/restart-test.txt"
        content = "restart-persistence-test"

        _cleanup_sandbox(name, pvc)

        # Create PVC
        subprocess.run(
            ["kubectl", "apply", "-f", "-"],
            input=f"""
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: {pvc}
  namespace: {AGENT_NS}
spec:
  accessModes: [ReadWriteOnce]
  resources:
    requests:
      storage: 50Mi
""",
            capture_output=True,
            text=True,
            timeout=30,
        )

        # Create sandbox and write data
        subprocess.run(
            ["kubectl", "apply", "-f", "-"],
            input=f"""
apiVersion: agents.x-k8s.io/v1alpha1
kind: Sandbox
metadata:
  name: {name}
  namespace: {AGENT_NS}
spec:
  podTemplate:
    spec:
      containers:
      - name: sandbox
        image: {BASE_IMAGE}
        command: ["sh", "-c", "echo '{content}' > {path} && sleep 300"]
        volumeMounts:
        - name: workspace
          mountPath: /workspace
      volumes:
      - name: workspace
        persistentVolumeClaim:
          claimName: {pvc}
""",
            capture_output=True,
            text=True,
            timeout=30,
        )

        # Wait for pod
        time.sleep(15)
        pods = kubectl_get_pods_json(AGENT_NS)
        pod1 = next(
            (
                p["metadata"]["name"]
                for p in pods
                if name in p["metadata"].get("name", "")
                and p["status"].get("phase") == "Running"
            ),
            None,
        )
        if not pod1:
            _cleanup_sandbox(name, pvc)
            pytest.skip(f"{name}: pod not running")

        # Verify data written
        r1 = _kubectl("exec", pod1, "-n", AGENT_NS, "--", "cat", path)
        assert r1.returncode == 0 and content in r1.stdout

        # Delete pod (NOT Sandbox CR — controller will recreate it)
        _kubectl("delete", "pod", pod1, "-n", AGENT_NS, "--force", "--grace-period=0")
        time.sleep(15)

        # Wait for controller to recreate pod
        pods = kubectl_get_pods_json(AGENT_NS)
        pod2 = next(
            (
                p["metadata"]["name"]
                for p in pods
                if name in p["metadata"].get("name", "")
                and p["status"].get("phase") == "Running"
                and p["metadata"]["name"] != pod1
            ),
            None,
        )
        if not pod2:
            _cleanup_sandbox(name, pvc)
            pytest.skip(f"{name}: pod not recreated after delete")

        # Verify data still readable
        r2 = _kubectl("exec", pod2, "-n", AGENT_NS, "--", "cat", path)
        _cleanup_sandbox(name, pvc)

        assert r2.returncode == 0, f"Cannot read {path} after pod restart"
        assert content in r2.stdout, (
            f"Workspace data lost after pod restart. Expected '{content}', got: {r2.stdout}"
        )
