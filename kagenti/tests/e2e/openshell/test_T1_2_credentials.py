"""
T1.2 Credentials Tests

Validates that agent pods handle credentials securely:
1. Secrets are delivered via K8s secretKeyRef (not hardcoded in deployment YAML)
2. Agent containers don't have unnecessary secrets in env
3. Policy ConfigMaps are properly mounted

Capability: credentials
Convention: test_credentials__{description}[agent]
"""

import json
import subprocess

import pytest

from kagenti.tests.e2e.openshell.conftest import (
    ALL_AGENT_NAMES,
    A2A_AGENT_NAMES,
    NEMOCLAW_AGENT_NAMES,
    kubectl_get_pods_json,
    nemoclaw_enabled,
    sandbox_crd_installed,
)


pytestmark = pytest.mark.openshell

_AGENTS = ALL_AGENT_NAMES
_LLM_AGENTS = A2A_AGENT_NAMES
_NEMOCLAW_AGENTS = NEMOCLAW_AGENT_NAMES

skip_no_nemoclaw = pytest.mark.skipif(
    not nemoclaw_enabled(), reason="NemoClaw tests disabled"
)


def _get_pod_name(agent: str, namespace: str) -> str:
    pods = kubectl_get_pods_json(namespace)
    for pod in pods:
        if (
            pod["metadata"]["name"].startswith(agent)
            and pod["status"].get("phase") == "Running"
        ):
            return pod["metadata"]["name"]
    pytest.skip(f"No running pod found for {agent} in {namespace}")


def _kubectl_exec(pod: str, ns: str, cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["kubectl", "exec", pod, "-n", ns, "-c", "agent", "--", *cmd],
        capture_output=True,
        text=True,
        timeout=15,
    )


class TestSecretDelivery:
    """Verify secrets are delivered via K8s secretKeyRef, not hardcoded."""

    @pytest.mark.parametrize("agent", _LLM_AGENTS)
    def test_credentials__key_from_secret(self, agent, agent_namespace):
        """API key env var must come from a K8s Secret, not a literal value."""
        result = subprocess.run(
            [
                "kubectl",
                "get",
                "deployment",
                agent,
                "-n",
                agent_namespace,
                "-o",
                "json",
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            pytest.skip(f"Deployment {agent} not found")

        dep = json.loads(result.stdout)
        containers = dep["spec"]["template"]["spec"]["containers"]
        agent_container = next((c for c in containers if c["name"] == "agent"), None)
        assert agent_container, f"No 'agent' container in {agent}"

        env_vars = agent_container.get("env", [])
        key_envs = [
            e
            for e in env_vars
            if "API_KEY" in e.get("name", "") or "api_key" in e.get("name", "")
        ]

        for env in key_envs:
            assert "valueFrom" in env, (
                f"{agent}: {env['name']} has literal value instead of secretKeyRef. "
                f"Secrets must be delivered via K8s Secrets."
            )
            assert "secretKeyRef" in env["valueFrom"], (
                f"{agent}: {env['name']} uses valueFrom but not secretKeyRef"
            )


class TestNoHardcodedSecrets:
    """Verify no real API keys are hardcoded in deployment YAML."""

    @pytest.mark.parametrize("agent", _AGENTS)
    def test_credentials__no_literal_keys(self, agent, agent_namespace):
        """Deployment YAML must not contain literal API key values."""
        result = subprocess.run(
            [
                "kubectl",
                "get",
                "deployment",
                agent,
                "-n",
                agent_namespace,
                "-o",
                "yaml",
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            pytest.skip(f"Deployment {agent} not found")

        yaml_text = result.stdout.lower()
        dangerous_patterns = ["sk-", "api_key: sk", "key: ghp_", "key: ghs_"]
        for pattern in dangerous_patterns:
            assert pattern not in yaml_text, (
                f"{agent}: Found potential hardcoded secret pattern '{pattern}' in YAML"
            )


class TestAgentEnvSecurity:
    """Verify agent process environment doesn't leak unnecessary secrets."""

    @pytest.mark.parametrize("agent", _AGENTS)
    def test_credentials__no_k8s_token(self, agent, agent_namespace):
        """Agent shouldn't have the K8s service account token in env."""
        pod_name = _get_pod_name(agent, agent_namespace)
        result = _kubectl_exec(pod_name, agent_namespace, ["env"])
        if result.returncode != 0:
            pytest.skip(f"Cannot exec into {agent}: {result.stderr}")

        env_lines = result.stdout.strip().splitlines()
        for line in env_lines:
            assert not line.startswith("KUBERNETES_SERVICE_ACCOUNT_TOKEN="), (
                f"{agent}: K8s SA token found in env (should be file-mounted only)"
            )


class TestPolicyConfigMapMounted:
    """Verify OPA policy ConfigMap is properly mounted in agent pods."""

    @pytest.mark.parametrize("agent", _AGENTS)
    def test_credentials__policy_file_exists(self, agent, agent_namespace):
        """The OPA policy file should be mounted at /etc/openshell/."""
        pod_name = _get_pod_name(agent, agent_namespace)
        result = _kubectl_exec(pod_name, agent_namespace, ["ls", "/etc/openshell/"])
        if result.returncode != 0:
            pytest.skip(f"Cannot exec into {agent}: {result.stderr}")

        assert "policy.yaml" in result.stdout, (
            f"{agent}: No policy.yaml found at /etc/openshell/. "
            f"Contents: {result.stdout}"
        )

    @pytest.mark.parametrize("agent", _AGENTS)
    def test_credentials__policy_valid_yaml(self, agent, agent_namespace):
        """The mounted policy file must be valid YAML with expected fields."""
        pod_name = _get_pod_name(agent, agent_namespace)
        result = _kubectl_exec(
            pod_name, agent_namespace, ["cat", "/etc/openshell/policy.yaml"]
        )
        if result.returncode != 0:
            pytest.skip(f"Cannot read policy: {result.stderr}")

        content = result.stdout
        assert "version:" in content, "Policy missing 'version' field"
        assert "filesystem_policy:" in content or "network_policies:" in content, (
            "Policy missing filesystem or network policy section"
        )


class TestSandboxCredentials:
    """Verify Claude Code and OpenCode sandbox pods get credentials from secrets."""

    @pytest.mark.skipif(not sandbox_crd_installed(), reason="Sandbox CRD not installed")
    def test_credentials__openshell_claude__anthropic_from_secret(self):
        """Claude Code sandbox must get ANTHROPIC_AUTH_TOKEN from secretKeyRef."""
        pods = kubectl_get_pods_json("team1")
        matching = [
            p
            for p in pods
            if "claude" in p["metadata"].get("name", "")
            and "test-" in p["metadata"].get("name", "")
            and p["status"].get("phase") == "Running"
        ]
        if not matching:
            pytest.skip(
                "openshell_claude: No running Claude sandbox pod. "
                "Run T3 skill tests first to create sandbox."
            )

        pod = matching[0]
        containers = pod["spec"]["containers"]
        sandbox_container = next(
            (c for c in containers if c["name"] == "sandbox"), None
        )
        if not sandbox_container:
            pytest.skip("No 'sandbox' container in Claude Code pod")

        env_vars = sandbox_container.get("env", [])
        auth_env = next(
            (e for e in env_vars if e["name"] == "ANTHROPIC_AUTH_TOKEN"), None
        )
        if auth_env is None:
            pytest.skip(
                "ANTHROPIC_AUTH_TOKEN not set — sandbox uses different credential path"
            )
        assert "valueFrom" in auth_env, (
            "ANTHROPIC_AUTH_TOKEN has literal value instead of secretKeyRef"
        )
        assert "secretKeyRef" in auth_env["valueFrom"], (
            "ANTHROPIC_AUTH_TOKEN uses valueFrom but not secretKeyRef"
        )

    @pytest.mark.skipif(not sandbox_crd_installed(), reason="Sandbox CRD not installed")
    def test_credentials__openshell_opencode__openai_key_from_secret(self):
        """OpenCode sandbox must get OPENAI_API_KEY from secretKeyRef."""
        pods = kubectl_get_pods_json("team1")
        matching = [
            p
            for p in pods
            if "opencode" in p["metadata"].get("name", "")
            and "test-" in p["metadata"].get("name", "")
            and p["status"].get("phase") == "Running"
        ]
        if not matching:
            pytest.skip(
                "openshell_opencode: No running OpenCode sandbox pod. "
                "Run T3 skill tests first to create sandbox."
            )

        pod = matching[0]
        containers = pod["spec"]["containers"]
        sandbox_container = next(
            (c for c in containers if c["name"] == "sandbox"), None
        )
        if not sandbox_container:
            pytest.skip("No 'sandbox' container in OpenCode pod")

        env_vars = sandbox_container.get("env", [])
        key_env = next((e for e in env_vars if e["name"] == "OPENAI_API_KEY"), None)
        if key_env is None:
            pytest.skip(
                "OPENAI_API_KEY not set — sandbox uses different credential path"
            )
        assert "valueFrom" in key_env, (
            "OPENAI_API_KEY has literal value instead of secretKeyRef"
        )
        assert "secretKeyRef" in key_env["valueFrom"], (
            "OPENAI_API_KEY uses valueFrom but not secretKeyRef"
        )


class TestNemoClawCredentials:
    """Verify NemoClaw agent credential security."""

    @skip_no_nemoclaw
    @pytest.mark.parametrize("agent", _NEMOCLAW_AGENTS)
    def test_credentials__nemoclaw__key_from_secret(self, agent, agent_namespace):
        """NemoClaw OPENAI_API_KEY must come from a K8s Secret."""
        result = subprocess.run(
            [
                "kubectl",
                "get",
                "deployment",
                agent,
                "-n",
                agent_namespace,
                "-o",
                "json",
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            pytest.skip(f"Deployment {agent} not found")

        dep = json.loads(result.stdout)
        containers = dep["spec"]["template"]["spec"]["containers"]
        for container in containers:
            for env_var in container.get("env", []):
                if "API_KEY" in env_var.get("name", ""):
                    assert "valueFrom" in env_var, (
                        f"{agent}/{container['name']}: {env_var['name']} "
                        f"has literal value instead of secretKeyRef"
                    )

    @skip_no_nemoclaw
    @pytest.mark.parametrize("agent", _NEMOCLAW_AGENTS)
    def test_credentials__nemoclaw__no_literal_keys(self, agent, agent_namespace):
        """NemoClaw deployment YAML must not contain plaintext API keys."""
        result = subprocess.run(
            [
                "kubectl",
                "get",
                "deployment",
                agent,
                "-n",
                agent_namespace,
                "-o",
                "yaml",
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            pytest.skip(f"Deployment {agent} not found")

        yaml_text = result.stdout.lower()
        dangerous_patterns = ["sk-", "api_key: sk", "key: ghp_", "key: ghs_"]
        for pattern in dangerous_patterns:
            assert pattern not in yaml_text, (
                f"{agent}: Found potential hardcoded secret '{pattern}' in YAML"
            )
