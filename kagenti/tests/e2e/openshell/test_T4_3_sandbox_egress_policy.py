"""
T4.3 Sandbox Egress Policy Tests

Tests that sandbox network policy can be configured to allow curl
access to specific external domains (e.g., github.com).

Three test classes:
  - TestKubectlSandboxEgressPolicy: uses kubectl exec on a Sandbox CRD pod
    (bypasses proxy) — verifies raw network egress works.
  - TestOpenShellSandboxWithPolicy: uses the openshell CLI to create a sandbox
    WITH a --policy allowing github.com/api.anthropic.com, validates that the
    proxy enforces traffic mediation and policy endpoints are configured.
  - TestOpenShellSandboxWithoutPolicy: uses the openshell CLI to create a sandbox
    WITHOUT network_policies, verifies that all egress is blocked.

Capabilities: sandbox, network_policy
Convention: test_{capability}__{description}
"""

import json
import os
import subprocess
import tempfile
import time

import pytest

from kagenti.tests.e2e.openshell.conftest import (
    kubectl_get_pods_json,
    kubectl_run,
    sandbox_crd_installed,
)

pytestmark = [pytest.mark.openshell, pytest.mark.mvp]

AGENT_NS = os.getenv("OPENSHELL_AGENT_NAMESPACE", "team1")
BASE_IMAGE = "ghcr.io/nvidia/openshell-community/sandboxes/base:latest"
SANDBOX_NAME = "test-egress-policy"

OPENSHELL_CLI = os.getenv("OPENSHELL_CLI", os.path.expanduser("~/.local/bin/openshell"))
XDG_CONFIG_HOME = os.getenv(
    "XDG_CONFIG_HOME",
    os.path.expanduser("~/sandbox/kagenti-mvp/kagenti-rc/.config"),
)
SSL_CERT_FILE = os.getenv(
    "SSL_CERT_FILE",
    os.path.join(XDG_CONFIG_HOME, "openshell", "ca-bundle.crt"),
)

KEYCLOAK_URL = os.getenv("OPENSHELL_KEYCLOAK_URL", "")
KEYCLOAK_USER = os.getenv("OPENSHELL_KEYCLOAK_USER", "alice")
KEYCLOAK_PASS = os.getenv("OPENSHELL_KEYCLOAK_PASS", "alice123")
OPENSHELL_GATEWAY = os.getenv("OPENSHELL_GATEWAY", "openshell-team1")

# Policy that allows egress to github.com and api.anthropic.com
EGRESS_ALLOW_POLICY = """\
version: 1
filesystem_policy:
  include_workdir: true
  read_only:
    - /usr
    - /lib
    - /lib64
    - /etc
    - /bin
    - /sbin
  read_write:
    - /tmp
    - /sandbox
    - /dev/null
    - /dev/urandom
network_policies:
  external:
    name: "Allow target APIs"
    endpoints:
      - host: "github.com"
        port: 443
      - host: "api.anthropic.com"
        port: 443
"""

# Policy with NO network_policies section — blocks all egress
EGRESS_DENY_POLICY = """\
version: 1
filesystem_policy:
  include_workdir: true
  read_only:
    - /usr
    - /lib
    - /lib64
    - /etc
    - /bin
    - /sbin
  read_write:
    - /tmp
    - /sandbox
    - /dev/null
    - /dev/urandom
"""


# ─── Helpers ─────────────────────────────────────────────────────────────────


def _kubectl(*args: str, timeout: int = 30) -> subprocess.CompletedProcess:
    return kubectl_run(*args, timeout=timeout)


def _openshell_run(*args: str, timeout: int = 30) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["XDG_CONFIG_HOME"] = XDG_CONFIG_HOME
    env["SSL_CERT_FILE"] = SSL_CERT_FILE
    return subprocess.run(
        [OPENSHELL_CLI, *args],
        capture_output=True,
        text=True,
        timeout=timeout,
        env=env,
    )


def _openshell_cli_available() -> bool:
    return os.path.isfile(OPENSHELL_CLI) and os.access(OPENSHELL_CLI, os.X_OK)


def _openshell_gateway_authenticated() -> bool:
    token_path = os.path.join(
        XDG_CONFIG_HOME,
        "openshell",
        "gateways",
        OPENSHELL_GATEWAY,
        "oidc_token.json",
    )
    if not os.path.isfile(token_path):
        return False
    try:
        with open(token_path) as f:
            token = json.load(f)
        return token.get("expires_at", 0) > time.time()
    except (json.JSONDecodeError, OSError):
        return False


def _refresh_openshell_token() -> bool:
    if not KEYCLOAK_URL:
        return False
    try:
        result = subprocess.run(
            [
                "curl",
                "-sk",
                KEYCLOAK_URL,
                "-d",
                "grant_type=password",
                "-d",
                "client_id=openshell-cli",
                "-d",
                f"username={KEYCLOAK_USER}",
                "-d",
                f"password={KEYCLOAK_PASS}",
                "-d",
                "scope=openid team1-audience",
            ],
            capture_output=True,
            text=True,
            timeout=15,
            env={**os.environ, "SSL_CERT_FILE": SSL_CERT_FILE},
        )
        if result.returncode != 0:
            return False
        data = json.loads(result.stdout)
        if "access_token" not in data:
            return False
        token_file = {
            "access_token": data["access_token"],
            "refresh_token": data["refresh_token"],
            "expires_at": int(time.time()) + data["expires_in"],
            "issuer": KEYCLOAK_URL.rsplit("/protocol", 1)[0],
            "client_id": "openshell-cli",
        }
        token_path = os.path.join(
            XDG_CONFIG_HOME,
            "openshell",
            "gateways",
            OPENSHELL_GATEWAY,
            "oidc_token.json",
        )
        os.makedirs(os.path.dirname(token_path), exist_ok=True)
        with open(token_path, "w") as f:
            json.dump(token_file, f, indent=2)
        return True
    except (subprocess.TimeoutExpired, json.JSONDecodeError, OSError):
        return False


def _ensure_openshell_ready():
    """Common precondition checks for openshell CLI tests."""
    if not _openshell_cli_available():
        pytest.skip("openshell CLI not available")
    if not _openshell_gateway_authenticated():
        if not _refresh_openshell_token():
            pytest.skip("Cannot authenticate to openshell gateway")
    result = _openshell_run("gateway", "select", OPENSHELL_GATEWAY)
    if result.returncode != 0:
        pytest.skip(f"Cannot select gateway {OPENSHELL_GATEWAY}: {result.stderr[:200]}")


def _create_openshell_sandbox(name: str, policy_content: str) -> str:
    """Create an openshell sandbox with a given policy. Returns sandbox name."""
    # Clean up leftover
    result = _openshell_run("sandbox", "list")
    if name in result.stdout:
        _openshell_run("sandbox", "delete", name, timeout=15)
        time.sleep(2)

    # Write policy to temp file
    policy_file = tempfile.NamedTemporaryFile(
        mode="w", suffix=".yaml", delete=False, prefix="policy-"
    )
    policy_file.write(policy_content)
    policy_file.close()

    try:
        # SSH will fail (ForwardTcp Unimplemented), but sandbox is created
        try:
            _openshell_run(
                "sandbox",
                "create",
                "--name",
                name,
                "--policy",
                policy_file.name,
                timeout=45,
            )
        except subprocess.TimeoutExpired:
            pass

        # Wait for Ready
        deadline = time.time() + 30
        while time.time() < deadline:
            result = _openshell_run("sandbox", "list")
            if name in result.stdout and "Ready" in result.stdout:
                return name
            time.sleep(3)

        pytest.fail(f"OpenShell sandbox {name} not Ready after 30s")
    finally:
        os.unlink(policy_file.name)


# ─── Fixtures: Sandbox CRD (kubectl exec) ──────────────────────────────────


def _cleanup_sandbox():
    _kubectl(
        "delete",
        "sandbox",
        SANDBOX_NAME,
        "-n",
        AGENT_NS,
        "--ignore-not-found",
        "--wait=false",
    )
    deadline = time.time() + 30
    while time.time() < deadline:
        pods = kubectl_get_pods_json(AGENT_NS)
        matching = [p for p in pods if SANDBOX_NAME in p["metadata"].get("name", "")]
        if not matching:
            break
        time.sleep(2)


def _create_sandbox_crd():
    sandbox_yaml = f"""
apiVersion: agents.x-k8s.io/v1alpha1
kind: Sandbox
metadata:
  name: {SANDBOX_NAME}
  namespace: {AGENT_NS}
spec:
  podTemplate:
    spec:
      containers:
      - name: sandbox
        image: {BASE_IMAGE}
        command: ["sleep", "600"]
"""
    result = subprocess.run(
        ["kubectl", "apply", "-f", "-"],
        input=sandbox_yaml,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, f"Failed to create sandbox: {result.stderr}"

    deadline = time.time() + 90
    while time.time() < deadline:
        pods = kubectl_get_pods_json(AGENT_NS)
        matching = [
            p
            for p in pods
            if SANDBOX_NAME in p["metadata"].get("name", "")
            and p["status"].get("phase") == "Running"
        ]
        if matching:
            return matching[0]["metadata"]["name"]
        time.sleep(5)

    pytest.fail(f"Sandbox pod {SANDBOX_NAME} not Running after 90s")


@pytest.fixture(scope="module")
def sandbox_pod():
    """Create a Sandbox CRD pod for kubectl exec testing."""
    if not sandbox_crd_installed():
        pytest.skip("Sandbox CRD not installed")
    _cleanup_sandbox()
    time.sleep(2)
    pod_name = _create_sandbox_crd()
    yield pod_name
    _cleanup_sandbox()


# ─── Fixtures: OpenShell CLI sandboxes ─────────────────────────────────────


@pytest.fixture(scope="module")
def openshell_sandbox_with_policy():
    """Create an openshell sandbox WITH egress policy (allows github.com)."""
    _ensure_openshell_ready()
    name = "test-egress-allow"
    sandbox_name = _create_openshell_sandbox(name, EGRESS_ALLOW_POLICY)
    yield sandbox_name
    _openshell_run("sandbox", "delete", name, timeout=15)


@pytest.fixture(scope="module")
def openshell_sandbox_without_policy():
    """Create an openshell sandbox WITHOUT network policy (deny all)."""
    _ensure_openshell_ready()
    name = "test-egress-deny"
    sandbox_name = _create_openshell_sandbox(name, EGRESS_DENY_POLICY)
    yield sandbox_name
    _openshell_run("sandbox", "delete", name, timeout=15)


# ═══════════════════════════════════════════════════════════════════════════════
# Test Class: kubectl exec (bypasses proxy, verifies raw egress)
# ═══════════════════════════════════════════════════════════════════════════════


class TestKubectlSandboxEgressPolicy:
    """Verify sandbox can reach allowed external domains via kubectl exec."""

    def test_kubectl_egress__curl_github_reachable(self, sandbox_pod):
        """kubectl exec: sandbox can reach github.com via HTTPS."""
        result = _kubectl(
            "exec",
            sandbox_pod,
            "-n",
            AGENT_NS,
            "--",
            "curl",
            "-sS",
            "-o",
            "/dev/null",
            "-w",
            "%{http_code}",
            "--max-time",
            "15",
            "https://github.com",
            timeout=30,
        )
        assert result.returncode == 0, (
            f"curl to github.com failed: rc={result.returncode} "
            f"stderr={result.stderr[:200]}"
        )
        http_code = result.stdout.strip()
        assert http_code in ("200", "301", "302"), (
            f"Expected HTTP 200/301/302 from github.com, got {http_code}"
        )

    def test_kubectl_egress__curl_anthropic_reachable(self, sandbox_pod):
        """kubectl exec: sandbox can reach api.anthropic.com."""
        result = _kubectl(
            "exec",
            sandbox_pod,
            "-n",
            AGENT_NS,
            "--",
            "curl",
            "-sS",
            "-o",
            "/dev/null",
            "-w",
            "%{http_code}",
            "--max-time",
            "15",
            "https://api.anthropic.com",
            timeout=30,
        )
        assert result.returncode == 0, (
            f"curl to api.anthropic.com failed: rc={result.returncode} "
            f"stderr={result.stderr[:200]}"
        )
        http_code = result.stdout.strip()
        assert http_code != "000", (
            "Connection failed (HTTP 000) — sandbox has no outbound connectivity"
        )

    def test_kubectl_egress__dns_resolution_works(self, sandbox_pod):
        """kubectl exec: sandbox can resolve external DNS names."""
        result = _kubectl(
            "exec",
            sandbox_pod,
            "-n",
            AGENT_NS,
            "--",
            "getent",
            "hosts",
            "github.com",
            timeout=15,
        )
        assert result.returncode == 0, (
            f"DNS resolution failed for github.com: {result.stderr[:200]}"
        )
        assert result.stdout.strip(), "DNS returned empty result"

    def test_kubectl_egress__curl_returns_content(self, sandbox_pod):
        """kubectl exec: sandbox can download actual content from github.com."""
        result = _kubectl(
            "exec",
            sandbox_pod,
            "-n",
            AGENT_NS,
            "--",
            "curl",
            "-sS",
            "--max-time",
            "15",
            "https://github.com",
            timeout=30,
        )
        assert result.returncode == 0, (
            f"curl failed: rc={result.returncode} stderr={result.stderr[:200]}"
        )
        assert len(result.stdout) > 100, (
            f"Response too short ({len(result.stdout)} bytes) — "
            "expected HTML content from github.com"
        )


# ═══════════════════════════════════════════════════════════════════════════════
# Test Class: OpenShell CLI sandbox WITH policy (egress allowed)
# ═══════════════════════════════════════════════════════════════════════════════


class TestOpenShellSandboxWithPolicy:
    """
    Verify openshell sandbox created WITH egress policy allowing github.com.

    The sandbox enforces network policy via:
      1. seccomp filter blocking raw sockets (direct connections impossible)
      2. HTTP CONNECT proxy (10.200.0.1:3128) for all outbound traffic
      3. OPA policy evaluation (checks binary identity + policy endpoints)

    With the EGRESS_ALLOW_POLICY, the proxy SHOULD allow traffic to
    github.com:443 and api.anthropic.com:443. However, binary identification
    requires an SSH session (ForwardTcp). On gateway versions < 0.0.52,
    the proxy returns 403 because it cannot verify the calling binary.

    These tests verify the policy is applied and the proxy is mediating traffic.
    """

    def test_openshell_with_policy__sandbox_created(
        self, openshell_sandbox_with_policy
    ):
        """Sandbox with egress policy is created and Ready."""
        result = _openshell_run("sandbox", "list")
        assert openshell_sandbox_with_policy in result.stdout
        assert "Ready" in result.stdout

    def test_openshell_with_policy__exec_works(self, openshell_sandbox_with_policy):
        """Basic exec works in policy-enabled sandbox."""
        result = _openshell_run(
            "sandbox",
            "exec",
            "--name",
            openshell_sandbox_with_policy,
            "--",
            "echo",
            "policy-sandbox-ok",
            timeout=15,
        )
        assert result.returncode == 0, (
            f"exec failed: rc={result.returncode} stderr={result.stderr[:200]}"
        )
        assert "policy-sandbox-ok" in result.stdout

    def test_openshell_with_policy__proxy_configured(
        self, openshell_sandbox_with_policy
    ):
        """Proxy env vars are set, directing traffic through the supervisor."""
        result = _openshell_run(
            "sandbox",
            "exec",
            "--name",
            openshell_sandbox_with_policy,
            "--",
            "env",
            timeout=15,
        )
        assert result.returncode == 0
        env_lower = result.stdout.lower()
        assert "https_proxy=" in env_lower, "HTTPS_PROXY not configured"
        assert "10.200.0.1:3128" in result.stdout, (
            "Proxy not pointing to supervisor (10.200.0.1:3128)"
        )

    def test_openshell_with_policy__dns_configured(self, openshell_sandbox_with_policy):
        """Sandbox has DNS resolver configuration."""
        result = _openshell_run(
            "sandbox",
            "exec",
            "--name",
            openshell_sandbox_with_policy,
            "--",
            "cat",
            "/etc/resolv.conf",
            timeout=15,
        )
        assert result.returncode == 0
        assert "nameserver" in result.stdout

    def test_openshell_with_policy__curl_github_returns_200(
        self, openshell_sandbox_with_policy
    ):
        """
        curl to github.com should return HTTP 200 when policy allows it.

        The EGRESS_ALLOW_POLICY permits github.com:443. The proxy should
        evaluate the policy and allow the CONNECT tunnel through.
        """
        result = _openshell_run(
            "sandbox",
            "exec",
            "--name",
            openshell_sandbox_with_policy,
            "--",
            "curl",
            "-sS",
            "-o",
            "/dev/null",
            "-w",
            "%{http_code}",
            "--max-time",
            "15",
            "https://github.com",
            timeout=25,
        )
        assert result.returncode == 0, (
            f"curl to github.com failed: rc={result.returncode} "
            f"stderr={result.stderr[:200]}"
        )
        http_code = result.stdout.strip()
        assert http_code == "200", (
            f"Expected HTTP 200 from github.com (policy allows it), "
            f"got {http_code}. stderr={result.stderr[:200]}"
        )

    def test_openshell_with_policy__direct_socket_blocked(
        self, openshell_sandbox_with_policy
    ):
        """Direct socket bypassing proxy is blocked by seccomp."""
        result = _openshell_run(
            "sandbox",
            "exec",
            "--name",
            openshell_sandbox_with_policy,
            "--",
            "curl",
            "--noproxy",
            "*",
            "-sS",
            "-o",
            "/dev/null",
            "-w",
            "%{http_code}",
            "--max-time",
            "10",
            "https://github.com",
            timeout=20,
        )
        assert result.returncode != 0
        combined = result.stdout + result.stderr
        assert (
            "Could not resolve" in combined
            or "Couldn't connect" in combined
            or "000" in combined
        ), f"Expected seccomp block, got: {combined[:200]}"


# ═══════════════════════════════════════════════════════════════════════════════
# Test Class: OpenShell CLI sandbox WITHOUT policy (egress denied)
# ═══════════════════════════════════════════════════════════════════════════════


class TestOpenShellSandboxWithoutPolicy:
    """
    Verify openshell sandbox created WITHOUT network_policies blocks all egress.

    When no network_policies section is present in the policy YAML, the sandbox
    still routes traffic through the supervisor proxy (10.200.0.1:3128) and the
    seccomp filter still blocks direct socket connections. All network access
    is denied.
    """

    def test_openshell_no_policy__sandbox_created(
        self, openshell_sandbox_without_policy
    ):
        """Sandbox without network policy is created and Ready."""
        result = _openshell_run("sandbox", "list")
        assert openshell_sandbox_without_policy in result.stdout
        assert "Ready" in result.stdout

    def test_openshell_no_policy__exec_works(self, openshell_sandbox_without_policy):
        """Basic exec works in no-policy sandbox (non-network commands ok)."""
        result = _openshell_run(
            "sandbox",
            "exec",
            "--name",
            openshell_sandbox_without_policy,
            "--",
            "echo",
            "no-policy-sandbox-ok",
            timeout=15,
        )
        assert result.returncode == 0, (
            f"exec failed: rc={result.returncode} stderr={result.stderr[:200]}"
        )
        assert "no-policy-sandbox-ok" in result.stdout

    def test_openshell_no_policy__proxy_still_configured(
        self, openshell_sandbox_without_policy
    ):
        """Proxy is still configured even without network policy (enforcement active)."""
        result = _openshell_run(
            "sandbox",
            "exec",
            "--name",
            openshell_sandbox_without_policy,
            "--",
            "env",
            timeout=15,
        )
        assert result.returncode == 0
        env_lower = result.stdout.lower()
        assert "https_proxy=" in env_lower, (
            "HTTPS_PROXY not set — enforcement not active"
        )

    def test_openshell_no_policy__curl_github_blocked(
        self, openshell_sandbox_without_policy
    ):
        """
        curl to github.com is blocked (no network_policies = deny all).

        The proxy denies the CONNECT request because no endpoints are allowed.
        """
        result = _openshell_run(
            "sandbox",
            "exec",
            "--name",
            openshell_sandbox_without_policy,
            "--",
            "curl",
            "-sS",
            "-o",
            "/dev/null",
            "-w",
            "%{http_code}",
            "--max-time",
            "10",
            "https://github.com",
            timeout=20,
        )
        combined = result.stdout + result.stderr
        blocked = (
            "403" in combined
            or "CONNECT tunnel failed" in combined
            or "Could not resolve" in combined
        )
        assert blocked, (
            f"Expected blocked egress (403 or connection failure), "
            f"got: {combined[:200]}"
        )

    def test_openshell_no_policy__curl_anthropic_blocked(
        self, openshell_sandbox_without_policy
    ):
        """curl to api.anthropic.com is also blocked without policy."""
        result = _openshell_run(
            "sandbox",
            "exec",
            "--name",
            openshell_sandbox_without_policy,
            "--",
            "curl",
            "-sS",
            "-o",
            "/dev/null",
            "-w",
            "%{http_code}",
            "--max-time",
            "10",
            "https://api.anthropic.com",
            timeout=20,
        )
        combined = result.stdout + result.stderr
        blocked = (
            "403" in combined
            or "CONNECT tunnel failed" in combined
            or "Could not resolve" in combined
        )
        assert blocked, f"Expected blocked egress, got: {combined[:200]}"

    def test_openshell_no_policy__direct_socket_blocked(
        self, openshell_sandbox_without_policy
    ):
        """Direct socket bypassing proxy is blocked by seccomp."""
        result = _openshell_run(
            "sandbox",
            "exec",
            "--name",
            openshell_sandbox_without_policy,
            "--",
            "curl",
            "--noproxy",
            "*",
            "-sS",
            "-o",
            "/dev/null",
            "-w",
            "%{http_code}",
            "--max-time",
            "10",
            "https://github.com",
            timeout=20,
        )
        assert result.returncode != 0
        combined = result.stdout + result.stderr
        assert (
            "Could not resolve" in combined
            or "Couldn't connect" in combined
            or "000" in combined
        ), f"Expected seccomp block, got: {combined[:200]}"
