"""
T7.1 Teleport Tests

Validates session teleporting — packaging local context into a sandbox,
executing prompts with context, and cleanup.

Tests are assertive: if infrastructure is deployed, they MUST pass.
"""

import os
import subprocess

import pytest

from kagenti.tests.e2e.openshell.conftest import (
    kubectl_run,
    sandbox_crd_installed,
)

pytestmark = [pytest.mark.openshell]

TELEPORT_NS = os.getenv("OPENSHELL_AGENT_NAMESPACE", "team1")
LLM_AVAILABLE = os.getenv("OPENSHELL_LLM_AVAILABLE", "").lower() == "true"

skip_no_crd = pytest.mark.skipif(
    not sandbox_crd_installed(), reason="Sandbox CRD not installed"
)


def _teleport_script() -> str:
    repo_root = os.getenv(
        "REPO_ROOT",
        os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."),
    )
    script = os.path.join(repo_root, "scripts", "openshell", "teleport-session.sh")
    assert os.path.isfile(script), f"teleport-session.sh not found at {script}"
    return script


def _run_teleport(*args: str, timeout: int = 60) -> subprocess.CompletedProcess:
    return subprocess.run(
        [_teleport_script(), *args, "--namespace", TELEPORT_NS],
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def _gateway_running() -> bool:
    result = kubectl_run(
        "get",
        "pods",
        "-n",
        TELEPORT_NS,
        "-l",
        "app.kubernetes.io/name=openshell",
        "--no-headers",
    )
    return result.returncode == 0 and "Running" in result.stdout


class TestTeleportPackage:
    """Package and cleanup — no sandbox pod needed."""

    @skip_no_crd
    def test_teleport__package_creates_configmap(self):
        """Packaging creates a ConfigMap with CLAUDE.md content."""
        result = _run_teleport("--package")
        assert result.returncode == 0, f"Package failed: {result.stderr}"

        session_id = result.stdout.strip().split("\n")[-1]
        assert len(session_id) == 8, f"Expected 8-char session ID, got: {session_id}"

        cm_name = f"teleport-ctx-{session_id}"
        check = kubectl_run("get", "configmap", cm_name, "-n", TELEPORT_NS)
        assert check.returncode == 0, f"ConfigMap {cm_name} not found"

        _run_teleport("--cleanup", "--session", session_id)

    @skip_no_crd
    def test_teleport__cleanup_removes_resources(self):
        """Cleanup deletes ConfigMap."""
        result = _run_teleport("--package")
        assert result.returncode == 0
        session_id = result.stdout.strip().split("\n")[-1]

        _run_teleport("--cleanup", "--session", session_id)

        cm = kubectl_run(
            "get", "configmap", f"teleport-ctx-{session_id}", "-n", TELEPORT_NS
        )
        assert cm.returncode != 0, "ConfigMap should be deleted after cleanup"

    def test_teleport__script_exists(self):
        """Teleport script exists and is executable."""
        script = _teleport_script()
        assert os.access(script, os.X_OK), f"{script} is not executable"


@pytest.mark.xfail(
    reason="Requires compute-driver to enrich Sandbox CRs with projected tokens",
    strict=False,
)
class TestTeleportLifecycle:
    """Full lifecycle in a single sandbox: deploy, verify context, prompt, cleanup.

    Uses ONE sandbox for all steps to avoid resource contention from
    creating multiple sandbox pods on CI runners with limited CPU.
    """

    @skip_no_crd
    def test_teleport__full_lifecycle(self):
        """Package → deploy → verify CLAUDE.md → optional prompt → cleanup."""
        if not _gateway_running():
            pytest.fail("OpenShell gateway not running — compute driver required")

        result = _run_teleport("--package")
        assert result.returncode == 0, f"Package failed: {result.stderr}"
        session_id = result.stdout.strip().split("\n")[-1]

        try:
            # Deploy sandbox with context
            deploy = _run_teleport("--deploy", "--session", session_id, timeout=120)
            assert deploy.returncode == 0, (
                f"Deploy failed:\nstdout: {deploy.stdout[-500:]}\n"
                f"stderr: {deploy.stderr[-500:]}"
            )

            # Find the running pod
            sb_name = f"teleport-{session_id}"
            pods = kubectl_run("get", "pods", "-n", TELEPORT_NS, "--no-headers")
            pod_name = ""
            for line in pods.stdout.strip().split("\n"):
                if sb_name in line and "Running" in line:
                    pod_name = line.split()[0]
                    break
            assert pod_name, f"No running pod matching {sb_name}"

            # Verify CLAUDE.md is unpacked in $HOME
            check = kubectl_run(
                "exec",
                pod_name,
                "-n",
                TELEPORT_NS,
                "-c",
                "sandbox",
                "--",
                "sh",
                "-c",
                "cat $HOME/CLAUDE.md",
                timeout=15,
            )
            assert check.returncode == 0, (
                f"CLAUDE.md not found in sandbox $HOME.\n"
                f"Check: kubectl exec {pod_name} -n {TELEPORT_NS} "
                f"-c sandbox -- sh -c 'ls -la $HOME/ && id'\n"
                f"stderr: {check.stderr}"
            )
            assert "Kagenti" in check.stdout, (
                f"CLAUDE.md doesn't mention Kagenti: {check.stdout[:200]}"
            )

            # If LLM available, send a prompt that reads the context
            if LLM_AVAILABLE:
                prompt = _run_teleport(
                    "--session",
                    session_id,
                    "--prompt",
                    "What is the name of the project described in CLAUDE.md? "
                    "Reply with just the project name, nothing else.",
                    timeout=180,
                )
                assert prompt.returncode == 0, f"Prompt failed: {prompt.stderr[-300:]}"
                output = prompt.stdout.strip()
                assert len(output) > 0, "Empty response from teleported session"
                # Check full output (may include tool-call text before answer)
                full = output.lower()
                assert any(
                    term in full
                    for term in ["kagenti", "agent", "platform", "claude.md"]
                ), f"Response doesn't reference the project: {output[-500:]}"

        finally:
            _run_teleport("--cleanup", "--session", session_id)


class TestTeleportFull:
    """--full mode: package → deploy → prompt → cleanup in one command."""

    @skip_no_crd
    def test_teleport__full_mode(self):
        """--full runs the entire lifecycle and returns prompt output."""
        if not _gateway_running():
            pytest.fail("OpenShell gateway not running — compute driver required")
        if not LLM_AVAILABLE:
            pytest.skip("LLM not available (OPENSHELL_LLM_AVAILABLE)")

        result = _run_teleport(
            "--full",
            "Say the word kagenti three times",
            timeout=240,
        )
        assert result.returncode == 0, f"Full mode failed: {result.stderr[-500:]}"
        assert "kagenti" in result.stdout.lower(), (
            f"Response doesn't contain kagenti: {result.stdout[-300:]}"
        )


class TestTeleportSkills:
    """Verify skills are teleported when TELEPORT_SKILLS is set."""

    @skip_no_crd
    def test_teleport__skills_packaged(self):
        """Skills listed in TELEPORT_SKILLS are included in the ConfigMap."""
        import os

        env = os.environ.copy()
        env["TELEPORT_SKILLS"] = "sandbox:teleport"

        result = subprocess.run(
            [_teleport_script(), "--package", "--namespace", TELEPORT_NS],
            capture_output=True,
            text=True,
            timeout=60,
            env=env,
        )
        assert result.returncode == 0, f"Package failed: {result.stderr}"
        session_id = result.stdout.strip().split("\n")[-1]

        try:
            assert "1 selected" in result.stderr, (
                f"Expected '1 selected' in output: {result.stderr}"
            )

            cm = kubectl_run(
                "get",
                "configmap",
                f"teleport-ctx-{session_id}",
                "-n",
                TELEPORT_NS,
                "-o",
                "jsonpath={.data}",
            )
            assert cm.returncode == 0
            assert "skill--sandbox_teleport.md" in cm.stdout, (
                f"Skill not in ConfigMap keys: {cm.stdout[:300]}"
            )
        finally:
            _run_teleport("--cleanup", "--session", session_id)


@pytest.mark.xfail(
    reason="Requires compute-driver to enrich Sandbox CRs with projected tokens",
    strict=False,
)
class TestTeleportSpawn:
    """--spawn mode: bare sandbox without local context."""

    @skip_no_crd
    def test_teleport__spawn_creates_sandbox(self):
        """--spawn creates a running sandbox without ConfigMap."""
        if not _gateway_running():
            pytest.fail("OpenShell gateway not running — compute driver required")

        result = _run_teleport("--spawn")
        assert result.returncode == 0, f"Spawn failed: {result.stderr[-500:]}"
        session_id = result.stdout.strip().split("\n")[-1]
        assert len(session_id) == 8, f"Expected 8-char session ID, got: {session_id}"

        try:
            sb_name = f"teleport-{session_id}"
            pods = kubectl_run("get", "pods", "-n", TELEPORT_NS, "--no-headers")
            assert sb_name in pods.stdout, f"No pod for {sb_name}"
            assert "Running" in pods.stdout.split(sb_name)[1].split("\n")[0]

            if LLM_AVAILABLE:
                prompt = _run_teleport(
                    "--session",
                    session_id,
                    "--prompt",
                    "What is 2+2? Reply with just the number.",
                    timeout=120,
                )
                assert prompt.returncode == 0, f"Prompt failed: {prompt.stderr[-300:]}"
                assert "4" in prompt.stdout
        finally:
            _run_teleport("--cleanup", "--session", session_id)

    @skip_no_crd
    def test_teleport__spawn_credential_isolation(self):
        """Spawned sandbox only sees LiteLLM virtual key, not real API keys."""
        if not _gateway_running():
            pytest.fail("OpenShell gateway not running — compute driver required")

        result = _run_teleport("--spawn")
        assert result.returncode == 0
        session_id = result.stdout.strip().split("\n")[-1]

        try:
            sb_name = f"teleport-{session_id}"
            pods = kubectl_run("get", "pods", "-n", TELEPORT_NS, "--no-headers")
            pod_name = ""
            for line in pods.stdout.strip().split("\n"):
                if sb_name in line and "Running" in line:
                    pod_name = line.split()[0]
                    break
            assert pod_name, f"No running pod for {sb_name}"

            env_check = kubectl_run(
                "exec",
                pod_name,
                "-n",
                TELEPORT_NS,
                "-c",
                "sandbox",
                "--",
                "sh",
                "-c",
                "env | grep -iE 'API_KEY|AUTH_TOKEN|ANTHROPIC|OPENAI|SECRET'",
                timeout=10,
            )
            env_output = env_check.stdout

            assert "ANTHROPIC_BASE_URL=http://litellm-model-proxy" in env_output, (
                "Missing ANTHROPIC_BASE_URL pointing to LiteLLM"
            )
            assert "ANTHROPIC_AUTH_TOKEN=" in env_output, "Missing virtual key"
            assert "litellm-model-proxy" in env_output, (
                "Should point to LiteLLM, not directly to provider"
            )
            for bad in ["OPENAI_API_KEY", "MAAS_API_KEY", "VERTEX_", "GOOGLE_"]:
                assert bad not in env_output, (
                    f"Real provider credential {bad} exposed in sandbox"
                )
        finally:
            _run_teleport("--cleanup", "--session", session_id)


class TestTeleportErrors:
    """Error handling — invalid inputs, missing prerequisites."""

    def test_teleport__no_action(self):
        """Script fails with usage when no action given."""
        result = subprocess.run(
            [_teleport_script()],
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode != 0

    def test_teleport__deploy_without_session(self):
        """--deploy without --session fails."""
        result = _run_teleport("--deploy")
        assert result.returncode != 0
        assert "session" in result.stderr.lower()

    def test_teleport__prompt_without_session(self):
        """--prompt without --session fails."""
        result = _run_teleport("--prompt", "hello")
        assert result.returncode != 0
        assert "session" in result.stderr.lower()

    def test_teleport__cleanup_without_session(self):
        """--cleanup without --session fails."""
        result = _run_teleport("--cleanup")
        assert result.returncode != 0
        assert "session" in result.stderr.lower()
