"""
OpenShell E2E test fixtures.

Provides A2A client helpers, agent URL resolution, and namespace
configuration for the OpenShell PoC agents.

Environment variables:
    OPENSHELL_AGENT_NAMESPACE: Namespace where agents are deployed (default: team1)
    OPENSHELL_GATEWAY_NAMESPACE: Namespace for the gateway (default: openshell-system)
    OPENSHELL_AGENT_PORT: Agent service port (default: 8080)
    OPENSHELL_LLM_AVAILABLE: Set to "true" if an LLM backend is reachable

Run:
    pytest kagenti/tests/e2e/openshell/ -v -m openshell
"""

import json
import os
import subprocess

import httpx
import pytest


# ---------------------------------------------------------------------------
# Custom marker registration
# ---------------------------------------------------------------------------


def pytest_configure(config):
    """Register the openshell marker."""
    config.addinivalue_line(
        "markers",
        "openshell: OpenShell PoC tests (gateway, agents, sandbox lifecycle)",
    )


# ---------------------------------------------------------------------------
# Namespace / environment helpers
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def agent_namespace():
    """Namespace where OpenShell agents are deployed."""
    return os.getenv("OPENSHELL_AGENT_NAMESPACE", "team1")


@pytest.fixture(scope="session")
def gateway_namespace():
    """Namespace where the OpenShell gateway runs."""
    return os.getenv("OPENSHELL_GATEWAY_NAMESPACE", "openshell-system")


@pytest.fixture(scope="session")
def agent_port():
    """Port used by agent services (ClusterIP)."""
    return int(os.getenv("OPENSHELL_AGENT_PORT", "8080"))


@pytest.fixture(scope="session")
def llm_available():
    """Whether an LLM backend is available for LLM-dependent tests."""
    return os.getenv("OPENSHELL_LLM_AVAILABLE", "false").lower() == "true"


# ---------------------------------------------------------------------------
# Agent URL helpers
# ---------------------------------------------------------------------------


def _find_free_port() -> int:
    """Find a free local port for port-forwarding."""
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        return s.getsockname()[1]


def _port_forward(name: str, namespace: str, remote_port: int):
    """Start kubectl port-forward and return (local_url, process).

    Tests connectivity first — if port-forward fails (e.g., agent uses
    OpenShell netns which blocks external access), returns None.
    """
    local_port = _find_free_port()
    try:
        proc = subprocess.Popen(
            [
                "kubectl",
                "port-forward",
                f"svc/{name}",
                f"{local_port}:{remote_port}",
                "-n",
                namespace,
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except FileNotFoundError:
        return None, None

    import socket
    import time

    for attempt in range(6):
        time.sleep(3)
        if proc.poll() is not None:
            return None, None
        try:
            sock = socket.create_connection(("localhost", local_port), timeout=5)
            sock.close()
            return f"http://localhost:{local_port}", proc
        except (ConnectionRefusedError, OSError, TimeoutError):
            if attempt >= 5:
                proc.terminate()
                proc.wait()
                return None, None


@pytest.fixture(scope="session")
def adk_agent_supervised_url(agent_namespace, agent_port):
    """Port-forward to supervised ADK agent via port-bridge sidecar."""
    url, proc = _port_forward("adk-agent-supervised", agent_namespace, agent_port)
    if not url:
        pytest.skip(
            "Cannot reach supervised ADK agent — "
            "port-bridge sidecar may not be deployed"
        )
    yield url
    if proc:
        proc.terminate()
        proc.wait()


@pytest.fixture(scope="session")
def claude_sdk_agent_url(agent_namespace, agent_port):
    """Port-forward to Claude SDK agent (may fail if supervisor netns blocks it)."""
    url, proc = _port_forward("claude-sdk-agent", agent_namespace, agent_port)
    if not url:
        pytest.skip(
            "Cannot reach Claude SDK agent — supervisor netns blocks port-forward"
        )
    yield url
    if proc:
        proc.terminate()
        proc.wait()


@pytest.fixture(scope="session")
def nemoclaw_hermes_url(agent_namespace):
    """Port-forward to NemoClaw Hermes agent (OpenAI-compatible API on 8642)."""
    url, proc = _port_forward("nemoclaw-hermes", agent_namespace, 8642)
    if not url:
        pytest.skip("Cannot reach nemoclaw-hermes (not deployed or image missing)")
    yield url
    if proc:
        proc.terminate()
        proc.wait()


@pytest.fixture(scope="session")
def nemoclaw_openclaw_url(agent_namespace):
    """Port-forward to NemoClaw OpenClaw agent (gateway via socat on 8080)."""
    url, proc = _port_forward("nemoclaw-openclaw", agent_namespace, 8080)
    if not url:
        pytest.skip("Cannot reach nemoclaw-openclaw (not deployed or image missing)")
    yield url
    if proc:
        proc.terminate()
        proc.wait()


def nemoclaw_enabled() -> bool:
    """Check if NemoClaw agent tests are enabled."""
    return os.getenv("OPENSHELL_NEMOCLAW_ENABLED", "").lower() == "true"


# ---------------------------------------------------------------------------
# A2A JSON-RPC helper
# ---------------------------------------------------------------------------


async def a2a_send(
    client: httpx.AsyncClient,
    url: str,
    text: str,
    *,
    request_id: str = "test-1",
    context_id: str | None = None,
    timeout: float = 120.0,
) -> dict:
    """Send an A2A ``message/send`` JSON-RPC request and return the parsed response.

    Args:
        client: httpx async client.
        url: Agent A2A endpoint URL.
        text: User message text.
        request_id: JSON-RPC request id.
        context_id: Optional context ID for multi-turn conversations.
        timeout: Per-request timeout in seconds.

    Returns:
        Parsed JSON response dict.
    """
    params: dict = {
        "message": {
            "role": "user",
            "messageId": f"msg-{request_id}",
            "parts": [{"type": "text", "text": text}],
        }
    }
    if context_id:
        params["contextId"] = context_id

    payload = {
        "jsonrpc": "2.0",
        "id": request_id,
        "method": "message/send",
        "params": params,
    }
    response = await client.post(url, json=payload, timeout=timeout)
    response.raise_for_status()
    return response.json()


def extract_context_id(response: dict) -> str | None:
    """Extract contextId from an A2A response for multi-turn conversations."""
    result = response.get("result", {})
    return result.get("contextId")


def extract_a2a_text(response: dict) -> str:
    """Extract concatenated text from an A2A JSON-RPC response.

    Handles both ``result.artifacts[].parts`` and
    ``result.status.message.parts`` shapes.
    """
    result = response.get("result", {})
    texts: list[str] = []

    # Artifacts — handle both "type" and "kind" field names (A2A spec variants)
    for artifact in result.get("artifacts", []):
        for part in artifact.get("parts", []):
            if part.get("type") == "text" or part.get("kind") == "text":
                texts.append(part.get("text", ""))

    # Status message fallback
    status_msg = result.get("status", {}).get("message", {})
    for part in status_msg.get("parts", []):
        if part.get("type") == "text" or part.get("kind") == "text":
            texts.append(part.get("text", ""))

    return "\n".join(texts)


# ---------------------------------------------------------------------------
# Shared kubectl helpers (used across test files — import from conftest)
# ---------------------------------------------------------------------------


def kubectl_run(*args: str, timeout: int = 30) -> subprocess.CompletedProcess:
    """Run a kubectl command and return the result."""
    return subprocess.run(
        ["kubectl", *args], capture_output=True, text=True, timeout=timeout
    )


def sandbox_crd_installed() -> bool:
    """Check if the Sandbox CRD (agents.x-k8s.io) is installed."""
    return kubectl_run("get", "crd", "sandboxes.agents.x-k8s.io").returncode == 0


# ---------------------------------------------------------------------------
# kubectl JSON helper
# ---------------------------------------------------------------------------


def kubectl_get_pods_json(namespace: str) -> list[dict]:
    """Return parsed pod list from ``kubectl get pods -n <ns> -o json``.

    Raises ``pytest.skip`` if kubectl is unavailable or the command fails.
    """
    try:
        result = subprocess.run(
            ["kubectl", "get", "pods", "-n", namespace, "-o", "json"],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except FileNotFoundError:
        pytest.skip("kubectl not found on PATH")

    if result.returncode != 0:
        pytest.skip(
            f"kubectl failed for namespace {namespace}: {result.stderr.strip()}"
        )

    data = json.loads(result.stdout)
    return data.get("items", [])


def kubectl_get_deployments_json(namespace: str) -> list[dict]:
    """Return parsed deployment list from ``kubectl get deployments -n <ns> -o json``."""
    try:
        result = subprocess.run(
            ["kubectl", "get", "deployments", "-n", namespace, "-o", "json"],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except FileNotFoundError:
        pytest.skip("kubectl not found on PATH")

    if result.returncode != 0:
        pytest.skip(
            f"kubectl failed for namespace {namespace}: {result.stderr.strip()}"
        )

    data = json.loads(result.stdout)
    return data.get("items", [])


# ---------------------------------------------------------------------------
# OpenCode sandbox helper
# ---------------------------------------------------------------------------

BASE_IMAGE = "ghcr.io/nvidia/openshell-community/sandboxes/base:latest"


def run_opencode_in_sandbox(
    prompt: str,
    namespace: str = "team1",
    model: str = "litellm/gpt-4o-mini",
    timeout_sec: int = 120,
) -> str | None:
    """Create a sandbox with OpenCode, run a prompt, return the output.

    Uses the @ai-sdk/openai-compatible provider so OpenCode calls
    /v1/chat/completions instead of /v1/responses (which LiteMaaS
    doesn't support).

    Returns the OpenCode output text, or None if the sandbox failed to
    start or OpenCode failed to run.
    """
    import time

    name = "test-opencode-skill-run"
    litellm_svc = kubectl_run(
        "get",
        "svc",
        "litellm-model-proxy",
        "-n",
        namespace,
        timeout=10,
    )
    if litellm_svc.returncode != 0:
        return None

    litellm_url = f"http://litellm-model-proxy.{namespace}.svc:4000/v1"

    kubectl_run(
        "delete",
        "sandbox",
        name,
        "-n",
        namespace,
        "--ignore-not-found",
        "--wait=false",
    )
    time.sleep(2)

    sandbox_yaml = f"""
apiVersion: agents.x-k8s.io/v1alpha1
kind: Sandbox
metadata:
  name: {name}
  namespace: {namespace}
spec:
  podTemplate:
    spec:
      containers:
      - name: sandbox
        image: {BASE_IMAGE}
        command: ["sleep", "300"]
        env:
        - name: OPENAI_API_KEY
          valueFrom:
            secretKeyRef:
              name: litellm-virtual-keys
              key: api-key
        - name: OPENAI_BASE_URL
          value: "{litellm_url}"
"""
    result = subprocess.run(
        ["kubectl", "apply", "-f", "-"],
        input=sandbox_yaml,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        return None

    deadline = time.time() + 60
    pod_name = None
    while time.time() < deadline:
        pods = kubectl_get_pods_json(namespace)
        matching = [
            p
            for p in pods
            if name in p["metadata"].get("name", "")
            and p["status"].get("phase") == "Running"
        ]
        if matching:
            pod_name = matching[0]["metadata"]["name"]
            break
        time.sleep(5)

    if not pod_name:
        kubectl_run(
            "delete",
            "sandbox",
            name,
            "-n",
            namespace,
            "--ignore-not-found",
            "--wait=false",
        )
        return None

    opencode_config = (
        '{"provider":{"litellm":{"npm":"@ai-sdk/openai-compatible",'
        f'"options":{{"baseURL":"{litellm_url}"}},'
        '"models":{"gpt-4o-mini":{}}}}}'
    )
    kubectl_run(
        "exec",
        pod_name,
        "-n",
        namespace,
        "--",
        "sh",
        "-c",
        f"mkdir -p $HOME/.config/opencode && echo '{opencode_config}' > $HOME/.config/opencode/config.json",
        timeout=10,
    )

    exec_result = kubectl_run(
        "exec",
        pod_name,
        "-n",
        namespace,
        "--",
        "timeout",
        str(timeout_sec),
        "opencode",
        "run",
        "-m",
        model,
        prompt,
        timeout=timeout_sec + 30,
    )

    kubectl_run(
        "delete",
        "sandbox",
        name,
        "-n",
        namespace,
        "--ignore-not-found",
        "--wait=false",
    )

    if exec_result.returncode != 0:
        return None

    return exec_result.stdout


def run_claude_in_sandbox(
    prompt: str,
    namespace: str = "team1",
    timeout_sec: int = 120,
) -> str | None:
    """Create a sandbox with Claude Code, run a prompt via LiteLLM, return output.

    Claude Code uses ANTHROPIC_BASE_URL + ANTHROPIC_AUTH_TOKEN to reach
    the LiteLLM proxy which translates Anthropic Messages API format to
    OpenAI format for LiteMaaS.

    Requires LiteLLM config with:
    - hosted_vllm/ provider (avoids OpenAI Responses API bridge)
    - use_chat_completions_url_for_anthropic_messages: true
    - drop_params: true (Claude Code sends reasoning_effort etc.)
    - claude-sonnet-4-20250514 model alias
    """
    import time

    name = "test-claude-skill-run"
    litellm_svc = kubectl_run(
        "get", "svc", "litellm-model-proxy", "-n", namespace, timeout=10
    )
    if litellm_svc.returncode != 0:
        return None

    litellm_url = f"http://litellm-model-proxy.{namespace}.svc:4000"

    kubectl_run(
        "delete",
        "sandbox",
        name,
        "-n",
        namespace,
        "--ignore-not-found",
        "--wait=false",
    )
    time.sleep(2)

    sandbox_yaml = f"""
apiVersion: agents.x-k8s.io/v1alpha1
kind: Sandbox
metadata:
  name: {name}
  namespace: {namespace}
spec:
  podTemplate:
    spec:
      containers:
      - name: sandbox
        image: {BASE_IMAGE}
        command: ["sleep", "300"]
        env:
        - name: ANTHROPIC_BASE_URL
          value: "{litellm_url}"
        - name: ANTHROPIC_AUTH_TOKEN
          valueFrom:
            secretKeyRef:
              name: litellm-virtual-keys
              key: api-key
"""
    result = subprocess.run(
        ["kubectl", "apply", "-f", "-"],
        input=sandbox_yaml,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        return None

    deadline = time.time() + 60
    pod_name = None
    while time.time() < deadline:
        pods = kubectl_get_pods_json(namespace)
        matching = [
            p
            for p in pods
            if name in p["metadata"].get("name", "")
            and p["status"].get("phase") == "Running"
        ]
        if matching:
            pod_name = matching[0]["metadata"]["name"]
            break
        time.sleep(5)

    if not pod_name:
        kubectl_run(
            "delete",
            "sandbox",
            name,
            "-n",
            namespace,
            "--ignore-not-found",
            "--wait=false",
        )
        return None

    exec_result = kubectl_run(
        "exec",
        pod_name,
        "-n",
        namespace,
        "--",
        "timeout",
        str(timeout_sec),
        "claude",
        "--print",
        "--bare",
        "--model",
        "claude-sonnet-4-20250514",
        prompt,
        timeout=timeout_sec + 30,
    )

    kubectl_run(
        "delete",
        "sandbox",
        name,
        "-n",
        namespace,
        "--ignore-not-found",
        "--wait=false",
    )

    if exec_result.returncode != 0:
        return None

    return exec_result.stdout


# ---------------------------------------------------------------------------
# Canonical test data (shared across all test files)
# ---------------------------------------------------------------------------

CANONICAL_DIFF = """
diff --git a/app/handler.py b/app/handler.py
--- a/app/handler.py
+++ b/app/handler.py
@@ -15,6 +15,10 @@ def handle_request(request):
     user_input = request.params.get("query", "")
-    result = db.execute(f"SELECT * FROM data WHERE id='{user_input}'")
+    result = db.execute("SELECT * FROM data WHERE id=%s", (user_input,))
     return {"data": result}
+
+def admin_action(request):
+    cmd = request.params.get("cmd")
+    os.system(cmd)  # Run admin command
+    return {"status": "done"}
"""

CANONICAL_CODE = """
import pickle, os, subprocess

def load_data(path):
    return pickle.load(open(path, 'rb'))

def run(cmd):
    return subprocess.check_output(cmd, shell=True)

def query(name):
    return db.execute(f"SELECT * FROM users WHERE name='{name}'")
"""

CANONICAL_CI_LOG = """
2026-04-22T08:00:00Z Run 12345 — E2E Kind
2026-04-22T08:01:00Z Installing Kagenti...
2026-04-22T08:05:00Z ERROR: Pod kagenti-controller-manager CrashLoopBackOff
2026-04-22T08:05:01Z Back-off restarting failed container
2026-04-22T08:05:02Z Events: Warning FailedMount — secret "webhook-tls" not found
2026-04-22T08:05:10Z FAILED: test_platform_health — operator not Running
"""

# ---------------------------------------------------------------------------
# Agent registry — defines ALL agents and their properties
# ---------------------------------------------------------------------------

ALL_A2A_AGENTS = [
    pytest.param("claude-sdk-agent", id="claude_sdk_agent"),
    pytest.param("adk-agent-supervised", id="adk_supervised"),
    pytest.param("weather-agent-supervised", id="weather_supervised"),
]

# NemoClaw agents — OpenAI-compatible (hermes) and gateway (openclaw) APIs.
# These do NOT speak A2A JSON-RPC; they have their own native APIs.
# TODO(a2a-adapter): Wrap with A2A adapter so they join ALL_A2A_AGENTS.
NEMOCLAW_AGENTS = [
    pytest.param("nemoclaw-hermes", id="nemoclaw_hermes"),
    pytest.param("nemoclaw-openclaw", id="nemoclaw_openclaw"),
]

LLM_CAPABLE_AGENTS = {
    "adk-agent-supervised",
    "claude-sdk-agent",
    "nemoclaw-hermes",
    "nemoclaw-openclaw",
}

ALL_SANDBOX_TYPES = [
    pytest.param(
        "test-generic-ws",
        "session-data-12345",
        "/workspace/session.txt",
        "echo 'session-data-12345' > /workspace/session.txt && sleep 300",
        id="openshell_generic",
    ),
    pytest.param(
        "test-claude-ws",
        "claude-session-001",
        "/workspace/.claude/session.json",
        "mkdir -p /workspace/.claude /workspace/project && "
        "echo 'session-id: claude-session-001' > /workspace/.claude/session.json && "
        "echo 'def main(): pass' > /workspace/project/main.py && sleep 300",
        id="openshell_claude",
    ),
    pytest.param(
        "test-opencode-ws",
        "opencode-session-001",
        "/workspace/.opencode/config.txt",
        "mkdir -p /workspace/.opencode /workspace/project && "
        "echo session=opencode-session-001 > /workspace/.opencode/config.txt && "
        "echo hello from opencode > /workspace/project/app.py && sleep 300",
        id="openshell_opencode",
    ),
]

# Agent-specific prompts for multi-turn tests
AGENT_PROMPTS = {
    "claude-sdk-agent": [
        "Review: def add(a,b): return a+b",
        "Add type hints.",
        "Add tests.",
    ],
    "adk-agent-supervised": [
        "I have a Python JSON parser.",
        "Add error handling.",
        "Review the result.",
    ],
    "weather-agent-supervised": [
        "Weather in Berlin?",
        "What about Tokyo?",
        "Which is colder?",
    ],
    "nemoclaw-hermes": [
        "What is 2 + 2?",
        "Multiply that by 3.",
        "Is the result even or odd?",
    ],
    "nemoclaw-openclaw": [
        "List 3 prime numbers.",
        "Which is the largest?",
        "Is it divisible by 2?",
    ],
}

# Map agent name to fixture name (for parametrized tests)
FIXTURE_MAP = {
    "claude-sdk-agent": "claude_sdk_agent_url",
    "adk-agent-supervised": "adk_agent_supervised_url",
}

# NemoClaw agent port/protocol mapping
NEMOCLAW_AGENT_CONFIG = {
    "nemoclaw-hermes": {
        "port": 8642,
        "health_path": "/health",
        "api_path": "/v1/chat/completions",
        "protocol": "openai",
    },
    "nemoclaw-openclaw": {
        "port": 8080,
        "health_path": "/",
        "api_path": "/",
        "protocol": "gateway",
    },
}


# ---------------------------------------------------------------------------
# Shared helpers (used across test files)
# ---------------------------------------------------------------------------


def _read_skill(skill_name: str) -> str:
    """Read a kagenti skill markdown file."""
    repo_root = os.getenv(
        "REPO_ROOT",
        os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."),
    )
    skill_path = os.path.join(repo_root, ".claude", "skills", skill_name, "SKILL.md")
    if not os.path.exists(skill_path):
        pytest.skip(f"Skill file not found: {skill_path}")
    with open(skill_path) as f:
        content = f.read()
    return content[:2000]


def destructive_tests_enabled() -> bool:
    """Check if destructive tests (restart, delete) are enabled."""
    return os.getenv("OPENSHELL_DESTRUCTIVE_TESTS", "").lower() == "true"
