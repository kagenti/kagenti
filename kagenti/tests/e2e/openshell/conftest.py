"""
OpenShell E2E test fixtures.

Provides A2A client helpers, agent URL resolution, and namespace
configuration for the OpenShell PoC agents.

Environment variables:
    OPENSHELL_AGENT_NAMESPACE: Namespace where agents are deployed (default: team1)
    OPENSHELL_GATEWAY_NAMESPACE: Namespace for the gateway (default: team1)
    OPENSHELL_AGENT_PORT: Agent service port (default: 8080)
    OPENSHELL_LLM_AVAILABLE: Set to "true" if an LLM backend is reachable
    OPENSHELL_LLM_MODELS: Comma-separated model list for per-model tests
    OPENSHELL_LLM_PROVIDER: "remote" (LiteMaaS) or "ollama" (local)

Run:
    pytest kagenti/tests/e2e/openshell/ -v -m openshell
"""

import json
import logging
import os
import subprocess
import time as _time
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

import httpx
import pytest


# ---------------------------------------------------------------------------
# Custom marker registration
# ---------------------------------------------------------------------------


def pytest_configure(config):
    """Register custom markers."""
    config.addinivalue_line(
        "markers",
        "openshell: OpenShell PoC tests (gateway, agents, sandbox lifecycle)",
    )
    config.addinivalue_line(
        "markers",
        "mvp: Multi-tenant MVP validation criteria (Section 9.2)",
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
    return os.getenv("OPENSHELL_GATEWAY_NAMESPACE", "team1")


@pytest.fixture(scope="session")
def agent_port():
    """Port used by agent services (ClusterIP)."""
    return int(os.getenv("OPENSHELL_AGENT_PORT", "8080"))


# True when LiteLLM proxy is deployed and reachable (set by openshell-full-test.sh)
LLM_AVAILABLE = os.getenv("OPENSHELL_LLM_AVAILABLE", "false").lower() == "true"
skip_no_llm = pytest.mark.skipif(not LLM_AVAILABLE, reason="LLM proxy not available")

# True when kagenti-backend is deployed and reachable
BACKEND_AVAILABLE = os.getenv("OPENSHELL_BACKEND_AVAILABLE", "false").lower() == "true"
skip_no_backend = pytest.mark.skipif(
    not BACKEND_AVAILABLE, reason="Backend not deployed"
)


@pytest.fixture(scope="session")
def llm_available():
    """Whether an LLM backend is available for LLM-dependent tests."""
    return LLM_AVAILABLE


# ---------------------------------------------------------------------------
# Agent URL helpers
# ---------------------------------------------------------------------------


def find_free_port() -> int:
    """Find a free local port for port-forwarding."""
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _port_forward(name: str, namespace: str, remote_port: int):
    """Start kubectl port-forward and return (local_url, process).

    Tests connectivity first — if port-forward fails (e.g., agent uses
    OpenShell netns which blocks external access), returns None.
    """
    local_port = find_free_port()
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


@pytest.fixture(scope="session")
def backend_url(agent_namespace):
    """Port-forward to kagenti-backend (port 8000), session-scoped."""
    if not BACKEND_AVAILABLE:
        pytest.skip("Backend not deployed (OPENSHELL_BACKEND_AVAILABLE != true)")
    url, proc = _port_forward("kagenti-backend", agent_namespace, 8000)
    if not url:
        pytest.skip("Cannot reach kagenti-backend — not deployed")
    yield url
    if proc:
        proc.terminate()
        proc.wait()


async def backend_send(
    client: httpx.AsyncClient,
    backend_url: str,
    namespace: str,
    agent_name: str,
    text: str,
    session_id: str | None = None,
    timeout: float = 120.0,
) -> dict:
    """Send a message through kagenti-backend's A2A proxy.

    Returns the JSON response. If the backend returns 503 (agent unreachable,
    typically supervisor netns blocking), raises pytest.skip instead of failing.
    """
    payload = {"message": text}
    if session_id:
        payload["session_id"] = session_id
    response = await client.post(
        f"{backend_url}/api/v1/chat/{namespace}/{agent_name}/send",
        json=payload,
        timeout=timeout,
    )
    if response.status_code == 503:
        detail = response.json().get("detail", "")
        pytest.skip(
            f"{agent_name}: backend cannot reach agent (503). "
            f"Supervised agents use netns which blocks in-cluster connections. "
            f"Detail: {detail[:200]}"
        )
    response.raise_for_status()
    return response.json()


async def backend_stream(
    client: httpx.AsyncClient,
    backend_url: str,
    namespace: str,
    agent_name: str,
    text: str,
    session_id: str | None = None,
    timeout: float = 120.0,
) -> httpx.Response:
    """Stream from kagenti-backend's A2A proxy. Returns raw response for SSE parsing."""
    payload = {"message": text}
    if session_id:
        payload["session_id"] = session_id
    response = await client.post(
        f"{backend_url}/api/v1/chat/{namespace}/{agent_name}/stream",
        json=payload,
        headers={"Accept": "text/event-stream"},
        timeout=timeout,
    )
    response.raise_for_status()
    return response


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


_claude_sandbox_pod: dict[str, str | None] = {}


def _ensure_claude_sandbox(namespace: str = "team1") -> str | None:
    """Ensure a shared Claude Code sandbox pod is running. Returns pod name."""
    import time

    cache_key = namespace
    if cache_key in _claude_sandbox_pod:
        pod_name = _claude_sandbox_pod[cache_key]
        if pod_name:
            check = kubectl_run(
                "get",
                "pod",
                pod_name,
                "-n",
                namespace,
                "-o",
                "jsonpath={.status.phase}",
            )
            if check.returncode == 0 and check.stdout.strip() == "Running":
                return pod_name

    name = "test-claude-shared"
    litellm_svc = kubectl_run(
        "get", "svc", "litellm-model-proxy", "-n", namespace, timeout=10
    )
    if litellm_svc.returncode != 0:
        logger.warning(
            f"LiteLLM service not found in {namespace} — sandbox tests will skip",
        )
        _claude_sandbox_pod[cache_key] = None
        return None

    litellm_url = f"http://litellm-model-proxy.{namespace}.svc:4000"

    kubectl_run(
        "delete",
        "sandbox",
        name,
        "-n",
        namespace,
        "--ignore-not-found",
        "--wait=true",
        timeout=30,
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
        command: ["sleep", "1800"]
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
        logger.warning(
            f"Sandbox CR creation failed: {result.stderr[:200]}",
        )
        _claude_sandbox_pod[cache_key] = None
        return None

    deadline = time.time() + 180
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
            _claude_sandbox_pod[cache_key] = pod_name
            return pod_name
        time.sleep(5)

    logger.warning("Sandbox pod %s not Running after 180s in %s", name, namespace)
    _claude_sandbox_pod[cache_key] = None
    return None


def run_claude_in_sandbox(
    prompt: str,
    namespace: str = "team1",
    timeout_sec: int = 120,
) -> str | None:
    """Run Claude Code in a shared sandbox pod via LiteLLM, return output.

    Reuses a single sandbox pod across tests (created on first call).
    Multiple Claude Code invocations exec into the same pod, avoiding
    the create/delete race that caused flaky test failures.

    Requires LiteLLM config with:
    - hosted_vllm/ provider (avoids OpenAI Responses API bridge)
    - use_chat_completions_url_for_anthropic_messages: true
    - drop_params: true (Claude Code sends reasoning_effort etc.)
    - claude-sonnet-4-20250514 model alias
    """
    pod_name = _ensure_claude_sandbox(namespace)
    if not pod_name:
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

    if exec_result.returncode != 0:
        logger.warning(
            "Claude exec failed (rc=%d): %s",
            exec_result.returncode,
            exec_result.stderr[:200],
        )
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
# ═══════════════════════════════════════════════════════════════════════════
# Agent Registry — single source of truth for all test parametrization
# ═══════════════════════════════════════════════════════════════════════════

# A2A agents — speak A2A JSON-RPC, reachable via port-forward
A2A_AGENTS = [
    pytest.param("claude-sdk-agent", id="claude_sdk_agent"),
    pytest.param("adk-agent-supervised", id="adk_supervised"),
]

# Exec-only agents — reachable via kubectl exec (netns blocks port-forward)
EXEC_AGENTS = [
    pytest.param("weather-agent-supervised", id="weather_supervised"),
]

# All supervised/A2A agents (union of A2A + exec)
ALL_A2A_AGENTS = A2A_AGENTS + EXEC_AGENTS

# NemoClaw agents — own protocols, NOT A2A
NEMOCLAW_AGENTS = [
    pytest.param("nemoclaw-hermes", id="nemoclaw_hermes"),
    pytest.param("nemoclaw-openclaw", id="nemoclaw_openclaw"),
]

# All deployed agents (A2A + NemoClaw)
ALL_DEPLOYED_AGENTS = ALL_A2A_AGENTS + NEMOCLAW_AGENTS

# Plain string lists (for non-parametrized lookups)
A2A_AGENT_NAMES = ["claude-sdk-agent", "adk-agent-supervised"]
EXEC_AGENT_NAMES = ["weather-agent-supervised"]
ALL_AGENT_NAMES = A2A_AGENT_NAMES + EXEC_AGENT_NAMES
NEMOCLAW_AGENT_NAMES = ["nemoclaw-hermes", "nemoclaw-openclaw"]
ALL_DEPLOYED_AGENT_NAMES = ALL_AGENT_NAMES + NEMOCLAW_AGENT_NAMES

# Agents with LLM capability (can execute skills)
LLM_CAPABLE_AGENTS = {
    "adk-agent-supervised",
    "claude-sdk-agent",
    "nemoclaw-hermes",
    "nemoclaw-openclaw",
}

# CLI agents — accessed via kubectl exec into sandbox pods (not A2A)
CLI_AGENTS = [
    pytest.param("openshell-claude", id="openshell_claude"),
    pytest.param("openshell-opencode", id="openshell_opencode"),
]
CLI_AGENT_NAMES = ["openshell-claude", "openshell-opencode"]

# All agents (full test matrix)
ALL_AGENTS = ALL_DEPLOYED_AGENTS + CLI_AGENTS
ALL_AGENT_NAMES_FULL = ALL_DEPLOYED_AGENT_NAMES + CLI_AGENT_NAMES

# Backend-proxied agents — A2A agents accessible via kagenti-backend proxy
BACKEND_AGENTS = [
    pytest.param("claude-sdk-agent", id="claude_sdk_agent"),
    pytest.param("adk-agent-supervised", id="adk_supervised"),
    pytest.param("weather-agent-supervised", id="weather_supervised"),
]
BACKEND_AGENT_NAMES = [
    "claude-sdk-agent",
    "adk-agent-supervised",
    "weather-agent-supervised",
]

# Agents without LLM (skip skill tests)
NO_LLM_AGENTS = {"weather-agent-supervised"}

# Agents without agent CLI (skip skill/tool tests)
NO_AGENT_CLI = {"openshell-generic"}

# ---------------------------------------------------------------------------
# Per-model parametrization
# ---------------------------------------------------------------------------

LLM_MODELS: list[str] = []
_raw_models = os.getenv("OPENSHELL_LLM_MODELS", "")
if _raw_models:
    LLM_MODELS = [m.strip() for m in _raw_models.split(",") if m.strip()]

LLM_PROVIDER = os.getenv("OPENSHELL_LLM_PROVIDER", "remote")

# ---------------------------------------------------------------------------
# LLM metrics recording
# ---------------------------------------------------------------------------

_METRICS_FILE = os.path.join(os.getenv("LOG_DIR", "/tmp/kagenti"), "llm-metrics.json")


def record_llm_metric(
    test_name: str,
    model: str,
    agent: str,
    capability: str,
    status: str,
    response: dict,
    duration_s: float,
    response_text: str = "",
    keywords: list[str] | None = None,
):
    """Record per-model LLM performance metrics to JSONL file."""
    usage = response.get("usage", {})
    keywords_found = 0
    if keywords and response_text:
        keywords_found = sum(1 for k in keywords if k in response_text.lower())

    metric = {
        "test": test_name,
        "model": model,
        "agent": agent,
        "capability": capability,
        "status": status,
        "tokens_in": usage.get("prompt_tokens", 0),
        "tokens_out": usage.get("completion_tokens", 0),
        "tokens_total": usage.get("total_tokens", 0),
        "duration_s": round(duration_s, 2),
        "response_length": len(response_text),
        "keywords_found": keywords_found,
        "keywords_expected": keywords or [],
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    try:
        os.makedirs(os.path.dirname(_METRICS_FILE), exist_ok=True)
        with open(_METRICS_FILE, "a") as f:
            f.write(json.dumps(metric) + "\n")
    except OSError:
        pass


# ---------------------------------------------------------------------------
# Per-model LiteLLM direct call
# ---------------------------------------------------------------------------

LITELLM_PROXY_URL = "http://litellm-model-proxy.{ns}.svc:4000"

_litellm_port_forward: dict[str, tuple] = {}


def _cleanup_litellm_port_forwards():
    """Kill any leaked port-forward processes on exit."""
    for _ns, (_, proc) in _litellm_port_forward.items():
        if proc and proc.poll() is None:
            proc.terminate()
            proc.wait()
    _litellm_port_forward.clear()


import atexit

atexit.register(_cleanup_litellm_port_forwards)


def _ensure_litellm_port_forward(namespace: str = "team1") -> str | None:
    """Get a URL to LiteLLM proxy, using port-forward if needed."""
    if namespace in _litellm_port_forward:
        url, proc = _litellm_port_forward[namespace]
        if proc and proc.poll() is None:
            return url

    url, proc = _port_forward("litellm-model-proxy", namespace, 4000)
    if url:
        _litellm_port_forward[namespace] = (url, proc)
    return url


async def litellm_chat(
    client: httpx.AsyncClient,
    prompt: str,
    model: str,
    namespace: str = "team1",
    max_tokens: int = 500,
    timeout: float = 180.0,
) -> dict:
    """Call LiteLLM proxy directly with a specific model.

    Uses port-forward to reach the proxy from outside the cluster.
    Returns the full response dict including usage stats.
    """
    base_url = _ensure_litellm_port_forward(namespace)
    if not base_url:
        pytest.skip("Cannot port-forward to LiteLLM proxy")
    resp = await client.post(
        f"{base_url}/v1/chat/completions",
        json={
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": max_tokens,
        },
        timeout=timeout,
    )
    resp.raise_for_status()
    return resp.json()


def litellm_chat_text(response: dict) -> str:
    """Extract text content from a LiteLLM chat completion response."""
    choices = response.get("choices", [])
    if not choices:
        return ""
    return choices[0].get("message", {}).get("content", "")


# ---------------------------------------------------------------------------
# OpenClaw gateway helper
# ---------------------------------------------------------------------------


async def openclaw_chat(
    client: httpx.AsyncClient,
    url: str,
    prompt: str,
    model: str = "gpt-4o-mini",
    timeout: float = 120.0,
) -> dict | None:
    """Send a chat completion request through the OpenClaw gateway.

    Tries multiple endpoint patterns since OpenClaw gateway protocol varies
    by version. Returns None if no chat endpoint is available.
    """
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 500,
    }
    endpoints = [
        "/v1/chat/completions",
        "/chat/completions",
        "/api/chat",
    ]
    for endpoint in endpoints:
        try:
            resp = await client.post(
                f"{url}{endpoint}",
                json=payload,
                timeout=timeout,
            )
            if resp.status_code == 404:
                continue
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                continue
            raise
        except (httpx.ReadError, httpx.RemoteProtocolError):
            continue

    # Last resort: POST to root with JSON body
    try:
        resp = await client.post(f"{url}/", json=payload, timeout=30.0)
        if resp.status_code == 200:
            try:
                data = resp.json()
                if "choices" in data or "message" in data or "response" in data:
                    return data
            except (ValueError, KeyError):
                pass
    except (httpx.HTTPError, httpx.ReadError, httpx.RemoteProtocolError):
        pass

    return None


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
