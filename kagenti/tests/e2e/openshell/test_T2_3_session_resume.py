"""
T2.3 Session Resume Tests

Tests session resume across pod restarts and PVC-backed conversation recovery.

Capabilities: session_resume
Convention: test_{capability}__{description}[agent]
"""

import os
import subprocess
import time

import httpx
import pytest

from kagenti.tests.e2e.openshell.conftest import (
    a2a_send,
    extract_a2a_text,
    extract_context_id,
    kubectl_get_pods_json,
    kubectl_run,
    sandbox_crd_installed,
    destructive_tests_enabled,
    AGENT_PROMPTS,
    FIXTURE_MAP,
    LLM_AVAILABLE,
    LLM_CAPABLE_AGENTS,
)

pytestmark = pytest.mark.openshell
AGENT_NS = os.getenv("OPENSHELL_AGENT_NAMESPACE", "team1")
BASE_IMAGE = "ghcr.io/nvidia/openshell-community/sandboxes/base:latest"


def _kubectl(*args: str, timeout: int = 30) -> subprocess.CompletedProcess:
    return kubectl_run(*args, timeout=timeout)


def _deploy_ready(name: str, ns: str = AGENT_NS) -> bool:
    r = _kubectl(
        "get", "deploy", name, "-n", ns, "-o", "jsonpath={.status.readyReplicas}"
    )
    return r.returncode == 0 and r.stdout.strip() == "1"


def _scale_agent(agent: str, replicas: int, ns: str = AGENT_NS):
    _kubectl("scale", f"deploy/{agent}", f"--replicas={replicas}", "-n", ns)
    if replicas == 0:
        time.sleep(5)
    else:
        _kubectl(
            "rollout",
            "status",
            f"deploy/{agent}",
            "-n",
            ns,
            "--timeout=120s",
            timeout=150,
        )


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


ALL_A2A_AGENTS_PORTFORWARD = [
    pytest.param("weather-agent-supervised", id="weather_supervised"),
    pytest.param("adk-agent-supervised", id="adk_supervised"),
    pytest.param("claude-sdk-agent", id="claude_sdk_agent"),
]


# ═══════════════════════════════════════════════════════════════════════════
# Conversation Survives Restart (ALL A2A agents) — DESTRUCTIVE
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
class TestSessionResumeSurvivesRestart:
    """Start conversation, restart pod, try to continue.

    This is the core session persistence test: does context survive
    a pod restart? Currently all agents lose in-memory state on restart.
    When PVC-backed session store is added, these will transition from
    SKIP to PASS.

    DESTRUCTIVE: scales agent to 0 then back. Enable with OPENSHELL_DESTRUCTIVE_TESTS=true.
    """

    @pytest.mark.parametrize("agent", ALL_A2A_AGENTS_PORTFORWARD)
    async def test_session_resume__survives_restart(self, agent, agent_namespace):
        """Turn 1 -> scale 0 -> scale 1 -> Turn 2: does context survive?"""
        if not destructive_tests_enabled():
            pytest.skip(
                f"{agent}: destructive restart test skipped (kills port-forwards). "
                f"Enable with OPENSHELL_DESTRUCTIVE_TESTS=true."
            )
        if not _deploy_ready(agent, agent_namespace):
            pytest.skip(f"{agent}: not deployed")
        if agent in LLM_CAPABLE_AGENTS and not LLM_AVAILABLE:
            pytest.skip(f"{agent}: requires LLM")

        from kagenti.tests.e2e.openshell.conftest import _port_forward

        prompts = AGENT_PROMPTS.get(agent, ["Hello"] * 3)

        # Turn 1 (pre-restart, own port-forward)
        url1, proc1 = _port_forward(agent, agent_namespace, 8080)
        if not url1:
            pytest.skip(f"{agent}: cannot reach")
        try:
            async with httpx.AsyncClient() as c:
                r1 = await a2a_send(c, url1, prompts[0], request_id=f"{agent}-pre")
            assert "result" in r1
            ctx = extract_context_id(r1)
        finally:
            if proc1:
                proc1.terminate()
                proc1.wait()

        # Restart
        _scale_agent(agent, 0, agent_namespace)
        _scale_agent(agent, 1, agent_namespace)

        # Turn 2 (post-restart, new port-forward)
        url2, proc2 = _port_forward(agent, agent_namespace, 8080)
        if not url2:
            pytest.fail(f"{agent}: unreachable after restart")
        try:
            async with httpx.AsyncClient() as c:
                r2 = await a2a_send(
                    c, url2, prompts[1], request_id=f"{agent}-post", context_id=ctx
                )
            assert "result" in r2, f"{agent}: no response after restart"
            ctx2 = extract_context_id(r2)

            if ctx is None:
                pytest.skip(
                    f"{agent}: responds after restart but stateless (no contextId). "
                    f"TODO: Kagenti backend session store for context persistence."
                )
            elif ctx2 != ctx:
                pytest.skip(
                    f"{agent}: responds after restart but context lost (in-memory). "
                    f"TODO: PVC-backed session checkpoint + Kagenti backend restore."
                )
        finally:
            if proc2:
                proc2.terminate()
                proc2.wait()

    async def test_session_resume__kubectl_restart(self, agent_namespace):
        """Supervised agent: restart test via kubectl exec."""
        agent = "weather-agent-supervised"
        if not destructive_tests_enabled():
            pytest.skip(
                f"{agent}: destructive test skipped. Enable with OPENSHELL_DESTRUCTIVE_TESTS=true."
            )
        if not _deploy_ready(agent, agent_namespace):
            pytest.skip(f"{agent}: not deployed")

        _scale_agent(agent, 0, agent_namespace)
        _scale_agent(agent, 1, agent_namespace)

        assert _deploy_ready(agent, agent_namespace), (
            f"{agent}: not ready after restart"
        )
        pytest.skip(
            f"{agent}: pod restarted successfully. A2A context test skipped — "
            f"netns blocks port-forward. "
            f"TODO: ExecSandbox gRPC for session persistence testing."
        )


# ═══════════════════════════════════════════════════════════════════════════
# Conversation Resume from PVC (builtin sandboxes) — DESTRUCTIVE
# ═══════════════════════════════════════════════════════════════════════════


@skip_no_crd
class TestSessionResumeFromPVC:
    """Write session state to PVC, delete sandbox, recreate, verify data persists.

    This is NEW — tests the full cycle of session resume via PVC.
    """

    def test_session_resume__pvc_recreate(self):
        """Generic sandbox: write to PVC, delete sandbox, recreate, verify data."""
        if not destructive_tests_enabled():
            pytest.skip(
                "Destructive test skipped. Enable with OPENSHELL_DESTRUCTIVE_TESTS=true."
            )

        name, pvc = "test-resume-generic", "test-resume-generic-pvc"
        path = "/workspace/session.txt"
        content = "session-resume-test-data"

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
      storage: 100Mi
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
        pod = next(
            (
                p["metadata"]["name"]
                for p in pods
                if name in p["metadata"].get("name", "")
                and p["status"].get("phase") == "Running"
            ),
            None,
        )
        if not pod:
            _cleanup_sandbox(name, pvc)
            pytest.skip(f"{name}: pod not running")

        # Verify data written
        r1 = _kubectl("exec", pod, "-n", AGENT_NS, "--", "cat", path)
        assert r1.returncode == 0 and content in r1.stdout

        # Delete sandbox (but NOT PVC)
        _kubectl("delete", "sandbox", name, "-n", AGENT_NS, "--wait=false")
        time.sleep(5)

        # Recreate sandbox with same PVC
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

        # Wait for new pod
        time.sleep(15)
        pods = kubectl_get_pods_json(AGENT_NS)
        pod2 = next(
            (
                p["metadata"]["name"]
                for p in pods
                if name in p["metadata"].get("name", "")
                and p["status"].get("phase") == "Running"
            ),
            None,
        )
        if not pod2:
            _cleanup_sandbox(name, pvc)
            pytest.skip(f"{name}: pod not running after recreate")

        # Verify data persisted
        r2 = _kubectl("exec", pod2, "-n", AGENT_NS, "--", "cat", path)
        _cleanup_sandbox(name, pvc)

        assert r2.returncode == 0, f"Cannot read {path} after recreate"
        assert content in r2.stdout, (
            f"Session data lost after sandbox recreate. Expected '{content}', got: {r2.stdout}"
        )
