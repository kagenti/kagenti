# Coding Agent Variants Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Extend the existing sandbox agent (`feat/sandbox-agent`) to support multiple agent frameworks — OpenCode, Claude Agent SDK, and OpenHands — deployed as A2A services on Kagenti alongside the current LangGraph-based sandbox-legion.

**Architecture:** The existing sandbox agent A2A wrapper pattern (`SandboxAgentExecutor` in `.worktrees/agent-examples/a2a/sandbox_agent/`) becomes the template. Each new framework variant gets its own agent directory following the same structure: `pyproject.toml`, `Dockerfile`, `src/<name>/agent.py` (A2A wrapper), and framework-specific logic. All variants share Kagenti infrastructure (AuthBridge, Squid proxy, agent-sandbox CRDs, Istio, OTEL).

**Deployment priority (updated March 2026):**
1. Sandbox Legion (LangGraph) — current, already built
2. **OpenCode** — 100K+ stars, `opencode serve` headless, 75+ LLMs, MIT, BYOK
3. Claude Agent SDK — exact Claude Code capabilities, proprietary
4. OpenHands — Docker-native sandbox, REST API, richest UI

**Tech Stack:** Python 3.11+, a2a-sdk >= 0.2.16, opencode (Phase 1), claude-agent-sdk (Phase 2), openhands-ai (Phase 3), LangGraph (existing), uv package manager, Shipwright builds, Kubernetes

**Base branches:** `feat/sandbox-agent` in both `.worktrees/sandbox-agent/` and `.worktrees/agent-examples/`

**Research doc:** `docs/plans/2026-02-26-coding-agent-variants-research.md`

---

## Phase 1: OpenCode + A2A Wrapper (Deploy Next)

> OpenCode is the #1 open-source coding agent (100K+ stars, 2.5M monthly devs). Its `opencode serve` headless HTTP server enables A2A wrapping. Supports 75+ LLM providers including existing ChatGPT/Copilot subscriptions. MIT licensed.

### Task 0: Scaffold the OpenCode agent directory

**Files:**
- Create: `.worktrees/agent-examples/a2a/opencode_agent/pyproject.toml`
- Create: `.worktrees/agent-examples/a2a/opencode_agent/Dockerfile`
- Create: `.worktrees/agent-examples/a2a/opencode_agent/src/opencode_agent/__init__.py`

**Step 1: Create pyproject.toml**

```toml
[project]
name = "opencode-agent"
version = "0.0.1"
description = "OpenCode wrapped as an A2A service for Kagenti."
requires-python = ">=3.11"
dependencies = [
    "a2a-sdk>=0.2.16",
    "httpx>=0.27.0",
    "pydantic-settings>=2.8.1",
    "opentelemetry-exporter-otlp",
    "opentelemetry-instrumentation-starlette",
]

[project.scripts]
server = "opencode_agent.agent:run"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"
```

Note: OpenCode itself is installed as a system binary (npm/brew), not a Python dependency. The agent wrapper calls it via `opencode serve` HTTP API.

**Step 2: Create Dockerfile**

```dockerfile
FROM python:3.11-slim

RUN apt-get update && apt-get install -y curl git && rm -rf /var/lib/apt/lists/*

# Install OpenCode CLI
RUN curl -fsSL https://opencode.ai/install | bash

WORKDIR /app

RUN pip install --no-cache-dir uv

COPY pyproject.toml uv.lock* ./
RUN uv pip install --system -e .

COPY src/ src/

EXPOSE 8000
EXPOSE 19876

# Start both opencode serve (port 19876) and A2A wrapper (port 8000)
CMD ["server"]
```

**Step 3: Create `__init__.py`**

```python
"""OpenCode Agent — OpenCode wrapped as A2A service for Kagenti."""
```

**Step 4: Commit**

```bash
cd .worktrees/agent-examples
git add a2a/opencode_agent/
git commit -s -m "feat: scaffold opencode-agent directory"
```

---

### Task 0b: Write the A2A wrapper for OpenCode

**Files:**
- Create: `.worktrees/agent-examples/a2a/opencode_agent/src/opencode_agent/agent.py`
- Create: `.worktrees/agent-examples/a2a/opencode_agent/tests/test_agent_card.py`

**Step 1: Write the failing test**

```python
"""Test agent card generation."""
from opencode_agent.agent import get_agent_card


def test_agent_card_has_required_fields():
    card = get_agent_card("localhost", 8000)
    assert card.name == "OpenCode Agent"
    assert card.url == "http://localhost:8000/"
    assert card.version == "1.0.0"
    assert card.capabilities.streaming is True
    assert len(card.skills) >= 1
    assert card.skills[0].id == "opencode_coding"


def test_agent_card_description():
    card = get_agent_card("localhost", 8000)
    assert "OpenCode" in card.description
    assert "MIT" in card.description or "open-source" in card.description.lower()
```

**Step 2: Write the A2A wrapper**

The wrapper starts `opencode serve` as a subprocess and proxies A2A requests to its HTTP API:

```python
"""A2A agent server wrapping OpenCode via opencode serve."""

import asyncio
import logging
import os
import subprocess
from textwrap import dedent

import httpx
import uvicorn
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.apps import A2AStarletteApplication
from a2a.server.events.event_queue import EventQueue
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.tasks import InMemoryTaskStore, TaskUpdater
from a2a.types import (
    AgentCapabilities,
    AgentCard,
    AgentSkill,
    Part,
    TaskState,
    TextPart,
)
from a2a.utils import new_agent_text_message, new_task
from starlette.routing import Route

logger = logging.getLogger(__name__)

OPENCODE_PORT = int(os.environ.get("OPENCODE_PORT", "19876"))


def get_agent_card(host: str, port: int) -> AgentCard:
    """Return the A2A AgentCard for the OpenCode Agent."""
    return AgentCard(
        name="OpenCode Agent",
        description=dedent("""\
            OpenCode (open-source, MIT, 100K+ stars) wrapped as A2A service.
            ## Key Features
            - **75+ LLM providers** — use existing ChatGPT/Copilot subscriptions
            - **MCP native** with OAuth 2.0 for remote servers
            - **BYOK** — bring your own API key, no vendor lock-in
            - **Custom agents** via markdown files
            """),
        url=f"http://{host}:{port}/",
        version="1.0.0",
        default_input_modes=["text"],
        default_output_modes=["text"],
        capabilities=AgentCapabilities(streaming=True),
        skills=[
            AgentSkill(
                id="opencode_coding",
                name="OpenCode Coding",
                description="Open-source autonomous coding agent with 75+ LLM support.",
                tags=["coding", "opencode", "open-source", "multi-llm"],
                examples=[
                    "Fix the failing test in test_auth.py",
                    "Add input validation to the API endpoints",
                    "Refactor the database module to use async",
                ],
            ),
        ],
    )


class OpenCodeExecutor(AgentExecutor):
    """A2A executor delegating to OpenCode serve HTTP API."""

    def __init__(self):
        self._opencode_url = f"http://localhost:{OPENCODE_PORT}"
        self._process = None

    async def _ensure_opencode_running(self):
        """Start opencode serve if not already running."""
        if self._process is None or self._process.poll() is not None:
            workspace = os.environ.get("WORKSPACE_DIR", "/workspace")
            self._process = subprocess.Popen(
                ["opencode", "serve", "--port", str(OPENCODE_PORT)],
                cwd=workspace,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            # Wait for server to be ready
            for _ in range(30):
                try:
                    async with httpx.AsyncClient() as client:
                        resp = await client.get(f"{self._opencode_url}/health")
                        if resp.status_code == 200:
                            return
                except httpx.ConnectError:
                    pass
                await asyncio.sleep(1)
            raise RuntimeError("OpenCode serve did not start within 30s")

    async def execute(
        self, context: RequestContext, event_queue: EventQueue
    ) -> None:
        task = context.current_task
        if not task:
            task = new_task(context.message)
            await event_queue.enqueue_event(task)

        task_updater = TaskUpdater(event_queue, task.id, task.context_id)
        await task_updater.update_status(
            TaskState.working,
            new_agent_text_message("Processing with OpenCode..."),
        )

        user_input = context.get_user_input()

        try:
            await self._ensure_opencode_running()

            async with httpx.AsyncClient(timeout=300.0) as client:
                resp = await client.post(
                    f"{self._opencode_url}/sessions",
                    json={"prompt": user_input},
                )
                resp.raise_for_status()
                result = resp.json()

                response_text = result.get("response", str(result))
                parts: list[Part] = [TextPart(text=response_text)]
                await task_updater.add_artifact(parts)
                await task_updater.complete()

        except Exception as e:
            logger.exception("OpenCode execution failed")
            await task_updater.update_status(
                TaskState.failed,
                new_agent_text_message(f"Error: {e}"),
            )
            raise


def run() -> None:
    """Create A2A server and run with uvicorn."""
    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", "8000"))

    agent_card = get_agent_card(host=host, port=port)
    request_handler = DefaultRequestHandler(
        agent_executor=OpenCodeExecutor(),
        task_store=InMemoryTaskStore(),
    )
    server = A2AStarletteApplication(
        agent_card=agent_card,
        http_handler=request_handler,
    )
    app = server.build()
    app.routes.insert(
        0,
        Route(
            "/.well-known/agent-card.json",
            server._handle_get_agent_card,
            methods=["GET"],
        ),
    )

    logger.info("OpenCode Agent starting on %s:%d", host, port)
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    run()
```

**Step 3: Run tests, commit**

```bash
cd .worktrees/agent-examples/a2a/opencode_agent
uv run pytest tests/ -v
git add -A && git commit -s -m "feat: add OpenCode A2A wrapper with opencode serve proxy"
```

---

### Task 0c: Create OpenCode K8s manifests and E2E test

Follow the same patterns as Tasks 4 and 5 below but with:
- `kagenti.io/framework: opencode`
- `app.kubernetes.io/name: opencode-agent`
- Image: `registry.cr-system.svc.cluster.local:5000/opencode-agent:v0.0.1`
- Env vars: `LLM_PROVIDER`, `LLM_MODEL`, `OPENAI_API_KEY` or `ANTHROPIC_API_KEY` (BYOK)
- No model lock-in — configurable at deployment time

```bash
git add kagenti/examples/agents/opencode_agent_* kagenti/tests/e2e/common/test_opencode_agent.py
git commit -s -m "feat: add K8s manifests and E2E tests for opencode-agent"
```

---

## Phase 2: Claude Agent SDK + A2A Wrapper

### Task 1: Scaffold the Claude Agent SDK agent directory

**Files:**
- Create: `.worktrees/agent-examples/a2a/claude_code_agent/pyproject.toml`
- Create: `.worktrees/agent-examples/a2a/claude_code_agent/Dockerfile`
- Create: `.worktrees/agent-examples/a2a/claude_code_agent/README.md`
- Create: `.worktrees/agent-examples/a2a/claude_code_agent/src/claude_code_agent/__init__.py`

**Step 1: Create pyproject.toml**

```toml
[project]
name = "claude-code-agent"
version = "0.0.1"
description = "Claude Agent SDK wrapped as an A2A service for Kagenti."
requires-python = ">=3.11"
dependencies = [
    "a2a-sdk>=0.2.16",
    "claude-agent-sdk>=0.1.0",
    "pydantic-settings>=2.8.1",
    "opentelemetry-exporter-otlp",
    "opentelemetry-instrumentation-starlette",
]

[project.scripts]
server = "claude_code_agent.agent:run"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"
```

**Step 2: Create Dockerfile**

Follow the pattern from `.worktrees/agent-examples/a2a/weather_service/Dockerfile`:

```dockerfile
FROM python:3.11-slim

WORKDIR /app

RUN pip install --no-cache-dir uv

COPY pyproject.toml uv.lock* ./
RUN uv pip install --system -e .

COPY src/ src/

EXPOSE 8000

CMD ["server"]
```

**Step 3: Create empty `__init__.py`**

```python
"""Claude Code Agent — Claude Agent SDK wrapped as A2A service."""
```

**Step 4: Commit**

```bash
cd .worktrees/agent-examples
git add a2a/claude_code_agent/
git commit -s -m "feat: scaffold claude-code-agent directory"
```

---

### Task 2: Write the A2A wrapper for Claude Agent SDK

**Files:**
- Create: `.worktrees/agent-examples/a2a/claude_code_agent/src/claude_code_agent/agent.py`

**Step 1: Write the failing test**

Create: `.worktrees/agent-examples/a2a/claude_code_agent/tests/test_agent_card.py`

```python
"""Test agent card generation."""
from claude_code_agent.agent import get_agent_card


def test_agent_card_has_required_fields():
    card = get_agent_card("localhost", 8000)
    assert card.name == "Claude Code Agent"
    assert card.url == "http://localhost:8000/"
    assert card.version == "1.0.0"
    assert card.capabilities.streaming is True
    assert len(card.skills) >= 1
    assert card.skills[0].id == "claude_code"


def test_agent_card_labels():
    card = get_agent_card("localhost", 8000)
    # Verify the card description mentions Claude Agent SDK
    assert "Claude" in card.description
```

**Step 2: Run test to verify it fails**

```bash
cd .worktrees/agent-examples/a2a/claude_code_agent
uv run pytest tests/test_agent_card.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'claude_code_agent.agent'`

**Step 3: Write the A2A wrapper**

Create: `.worktrees/agent-examples/a2a/claude_code_agent/src/claude_code_agent/agent.py`

```python
"""A2A agent server wrapping Claude Agent SDK."""

import logging
import os
from textwrap import dedent

import uvicorn
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.apps import A2AStarletteApplication
from a2a.server.events.event_queue import EventQueue
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.tasks import InMemoryTaskStore, TaskUpdater
from a2a.types import (
    AgentCapabilities,
    AgentCard,
    AgentSkill,
    Part,
    TaskState,
    TextPart,
)
from a2a.utils import new_agent_text_message, new_task
from starlette.routing import Route

logger = logging.getLogger(__name__)


def get_agent_card(host: str, port: int) -> AgentCard:
    """Return the A2A AgentCard for the Claude Code Agent."""
    return AgentCard(
        name="Claude Code Agent",
        description=dedent("""\
            Claude Agent SDK wrapped as an A2A service on Kagenti.
            ## Key Features
            - **Claude Code capabilities** — Read, Write, Edit, Bash, Glob, Grep
            - **MCP integration** — connects to external MCP servers
            - **Hooks** — PreToolUse/PostToolUse for policy enforcement
            """),
        url=f"http://{host}:{port}/",
        version="1.0.0",
        default_input_modes=["text"],
        default_output_modes=["text"],
        capabilities=AgentCapabilities(streaming=True),
        skills=[
            AgentSkill(
                id="claude_code",
                name="Claude Code",
                description="Autonomous coding agent with file and shell access.",
                tags=["coding", "claude", "agent-sdk"],
                examples=[
                    "Find and fix the bug in auth.py",
                    "Write tests for the user service",
                    "Refactor the database module",
                ],
            ),
        ],
    )


class ClaudeCodeExecutor(AgentExecutor):
    """A2A executor delegating to Claude Agent SDK query()."""

    async def execute(
        self, context: RequestContext, event_queue: EventQueue
    ) -> None:
        task = context.current_task
        if not task:
            task = new_task(context.message)
            await event_queue.enqueue_event(task)

        task_updater = TaskUpdater(event_queue, task.id, task.context_id)
        await task_updater.update_status(
            TaskState.working,
            new_agent_text_message("Processing with Claude Agent SDK..."),
        )

        user_input = context.get_user_input()
        workspace = os.environ.get("WORKSPACE_DIR", "/workspace")
        model = os.environ.get("LLM_MODEL", "claude-sonnet-4-6")

        try:
            from claude_agent_sdk import query, ClaudeCodeAgentOptions

            full_response = ""
            async for message in query(
                prompt=user_input,
                options=ClaudeCodeAgentOptions(
                    allowed_tools=["Read", "Edit", "Bash", "Glob", "Grep", "Write"],
                    model=model,
                    cwd=workspace,
                ),
            ):
                if hasattr(message, "content") and message.content:
                    chunk = str(message.content)
                    full_response += chunk
                    await task_updater.update_status(
                        TaskState.working,
                        new_agent_text_message(chunk),
                    )

            parts: list[Part] = [TextPart(text=full_response)]
            await task_updater.add_artifact(parts)
            await task_updater.complete()

        except Exception as e:
            logger.exception("Claude Agent SDK execution failed")
            await task_updater.update_status(
                TaskState.failed,
                new_agent_text_message(f"Error: {e}"),
            )
            raise


def run() -> None:
    """Create A2A server and run with uvicorn."""
    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", "8000"))

    agent_card = get_agent_card(host=host, port=port)
    request_handler = DefaultRequestHandler(
        agent_executor=ClaudeCodeExecutor(),
        task_store=InMemoryTaskStore(),
    )
    server = A2AStarletteApplication(
        agent_card=agent_card,
        http_handler=request_handler,
    )
    app = server.build()
    app.routes.insert(
        0,
        Route(
            "/.well-known/agent-card.json",
            server._handle_get_agent_card,
            methods=["GET"],
        ),
    )

    logger.info("Claude Code Agent starting on %s:%d", host, port)
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    run()
```

**Step 4: Run test to verify it passes**

```bash
cd .worktrees/agent-examples/a2a/claude_code_agent
uv run pytest tests/test_agent_card.py -v
```

Expected: PASS

**Step 5: Commit**

```bash
git add -A
git commit -s -m "feat: add Claude Agent SDK A2A wrapper"
```

---

### Task 3: Write executor unit tests

**Files:**
- Create: `.worktrees/agent-examples/a2a/claude_code_agent/tests/test_executor.py`

**Step 1: Write the tests**

```python
"""Test ClaudeCodeExecutor with mocked Claude Agent SDK."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from claude_code_agent.agent import ClaudeCodeExecutor


@pytest.fixture
def executor():
    return ClaudeCodeExecutor()


@pytest.fixture
def mock_context():
    ctx = MagicMock()
    ctx.current_task = None
    ctx.message = MagicMock()
    ctx.message.parts = [MagicMock(text="Write hello world in Python")]
    ctx.get_user_input.return_value = "Write hello world in Python"
    return ctx


@pytest.fixture
def mock_event_queue():
    queue = AsyncMock()
    queue.enqueue_event = AsyncMock()
    return queue


@pytest.mark.asyncio
@patch("claude_code_agent.agent.query")
async def test_executor_sends_prompt_to_sdk(mock_query, executor, mock_context, mock_event_queue):
    """Verify executor delegates to claude_agent_sdk.query()."""
    mock_message = MagicMock()
    mock_message.content = "print('hello world')"

    async def fake_query(**kwargs):
        yield mock_message

    mock_query.side_effect = fake_query

    await executor.execute(mock_context, mock_event_queue)

    mock_query.assert_called_once()
    call_kwargs = mock_query.call_args
    assert "Write hello world" in call_kwargs.kwargs["prompt"]


@pytest.mark.asyncio
@patch("claude_code_agent.agent.query")
async def test_executor_handles_sdk_error(mock_query, executor, mock_context, mock_event_queue):
    """Verify executor handles Claude Agent SDK errors gracefully."""
    async def failing_query(**kwargs):
        raise RuntimeError("API key invalid")
        yield  # make it a generator

    mock_query.side_effect = failing_query

    with pytest.raises(RuntimeError, match="API key invalid"):
        await executor.execute(mock_context, mock_event_queue)
```

**Step 2: Run tests**

```bash
cd .worktrees/agent-examples/a2a/claude_code_agent
uv run pytest tests/ -v
```

Expected: PASS (all tests including agent_card and executor)

**Step 3: Commit**

```bash
git add tests/
git commit -s -m "test: add executor unit tests for claude-code-agent"
```

---

### Task 4: Create Kubernetes deployment manifests

**Files:**
- Create: `kagenti/examples/agents/claude_code_agent_shipwright_build.yaml`
- Create: `kagenti/examples/agents/claude_code_agent_deployment.yaml`
- Create: `kagenti/examples/agents/claude_code_agent_service.yaml`

**Step 1: Create Shipwright Build**

Follow pattern from `weather_agent_shipwright_build.yaml`:

```yaml
apiVersion: shipwright.io/v1beta1
kind: Build
metadata:
  name: claude-code-agent
  namespace: team1
  labels:
    app.kubernetes.io/created-by: e2e-test
    app.kubernetes.io/name: claude-code-agent
    kagenti.io/type: agent
    kagenti.io/protocol: a2a
    kagenti.io/framework: claude-agent-sdk
  annotations:
    kagenti.io/agent-config: |
      {
        "protocol": "a2a",
        "framework": "claude-agent-sdk",
        "createHttpRoute": false
      }
spec:
  source:
    type: Git
    git:
      url: https://github.com/ladas/agent-examples
      revision: feat/sandbox-agent
    contextDir: a2a/claude_code_agent
  strategy:
    name: buildah-insecure-push
    kind: ClusterBuildStrategy
  paramValues:
    - name: dockerfile
      value: Dockerfile
  output:
    image: registry.cr-system.svc.cluster.local:5000/claude-code-agent:v0.0.1
  timeout: 15m
  retention:
    succeededLimit: 3
    failedLimit: 3
```

**Step 2: Create Deployment**

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: claude-code-agent
  namespace: team1
  labels:
    kagenti.io/type: agent
    kagenti.io/protocol: a2a
    kagenti.io/framework: claude-agent-sdk
    kagenti.io/workload-type: deployment
    app.kubernetes.io/name: claude-code-agent
spec:
  replicas: 1
  selector:
    matchLabels:
      kagenti.io/type: agent
      app.kubernetes.io/name: claude-code-agent
  template:
    metadata:
      labels:
        kagenti.io/type: agent
        kagenti.io/protocol: a2a
        kagenti.io/framework: claude-agent-sdk
        app.kubernetes.io/name: claude-code-agent
    spec:
      containers:
        - name: agent
          image: registry.cr-system.svc.cluster.local:5000/claude-code-agent:v0.0.1
          imagePullPolicy: Always
          env:
            - name: PORT
              value: "8000"
            - name: LLM_MODEL
              value: "claude-sonnet-4-6"
            - name: WORKSPACE_DIR
              value: "/workspace"
            - name: ANTHROPIC_API_KEY
              valueFrom:
                secretKeyRef:
                  name: anthropic-secret
                  key: apikey
            - name: OTEL_EXPORTER_OTLP_ENDPOINT
              value: "http://otel-collector.kagenti-system.svc.cluster.local:8335"
          ports:
            - containerPort: 8000
              name: http
          resources:
            requests:
              cpu: 100m
              memory: 256Mi
            limits:
              cpu: 500m
              memory: 1Gi
          volumeMounts:
            - name: workspace
              mountPath: /workspace
      volumes:
        - name: workspace
          emptyDir:
            sizeLimit: 2Gi
```

**Step 3: Create Service**

```yaml
apiVersion: v1
kind: Service
metadata:
  name: claude-code-agent
  namespace: team1
  labels:
    kagenti.io/type: agent
    kagenti.io/protocol: a2a
    kagenti.io/framework: claude-agent-sdk
    app.kubernetes.io/name: claude-code-agent
spec:
  selector:
    app.kubernetes.io/name: claude-code-agent
  ports:
    - port: 8000
      targetPort: http
      protocol: TCP
      name: http
```

**Step 4: Commit**

```bash
git add kagenti/examples/agents/claude_code_agent_*
git commit -s -m "feat: add K8s manifests for claude-code-agent"
```

---

### Task 5: Write E2E test for Claude Code Agent

**Files:**
- Create: `kagenti/tests/e2e/common/test_claude_code_agent.py`

**Step 1: Write the E2E test**

Follow the pattern from `test_agent_conversation.py`:

```python
"""E2E test for Claude Code Agent via A2A protocol."""
import os
import pytest
import httpx
from uuid import uuid4
from a2a.client import ClientConfig, ClientFactory
from a2a.client.card_resolver import A2ACardResolver
from a2a.types import (
    Message as A2AMessage,
    TextPart,
    TaskArtifactUpdateEvent,
)


AGENT_URL = os.getenv("CLAUDE_AGENT_URL", "http://claude-code-agent.team1.svc.cluster.local:8000")
SSL_VERIFY = os.getenv("SSL_VERIFY", "true").lower() == "true"


@pytest.fixture
async def a2a_client():
    """Create A2A client connected to Claude Code Agent."""
    httpx_client = httpx.AsyncClient(timeout=120.0, verify=SSL_VERIFY)
    resolver = A2ACardResolver(httpx_client, AGENT_URL)
    card = await resolver.get_agent_card()
    card.url = AGENT_URL
    config = ClientConfig(httpx_client=httpx_client)
    client = await ClientFactory.connect(card, client_config=config)
    yield client
    await httpx_client.aclose()


class TestClaudeCodeAgent:
    """Test Claude Code Agent responds via A2A."""

    @pytest.mark.asyncio
    async def test_agent_card_discovery(self):
        """Verify agent card at /.well-known/agent-card.json."""
        async with httpx.AsyncClient(verify=SSL_VERIFY) as client:
            resp = await client.get(f"{AGENT_URL}/.well-known/agent-card.json")
            assert resp.status_code == 200
            card = resp.json()
            assert card["name"] == "Claude Code Agent"
            assert card["capabilities"]["streaming"] is True
            assert any(s["id"] == "claude_code" for s in card["skills"])

    @pytest.mark.asyncio
    async def test_agent_card_framework_label(self):
        """Verify agent card identifies as claude-agent-sdk framework."""
        async with httpx.AsyncClient(verify=SSL_VERIFY) as client:
            resp = await client.get(f"{AGENT_URL}/.well-known/agent-card.json")
            card = resp.json()
            assert "Claude" in card["description"]

    @pytest.mark.asyncio
    async def test_simple_query(self, a2a_client):
        """Test agent responds to a simple coding query."""
        message = A2AMessage(
            role="user",
            parts=[TextPart(text="What is 2 + 2?")],
            messageId=uuid4().hex,
        )

        full_response = ""
        async for result in a2a_client.send_message(message):
            if isinstance(result, tuple):
                _, event = result
                if isinstance(event, TaskArtifactUpdateEvent) and event.artifact:
                    for part in event.artifact.parts or []:
                        if hasattr(part, "text"):
                            full_response += part.text

        assert full_response, "Agent did not return a response"
        assert "4" in full_response
```

**Step 2: Run test locally (requires running agent)**

```bash
CLAUDE_AGENT_URL=http://localhost:8000 uv run pytest kagenti/tests/e2e/common/test_claude_code_agent.py -v -k test_agent_card_discovery
```

**Step 3: Commit**

```bash
git add kagenti/tests/e2e/common/test_claude_code_agent.py
git commit -s -m "test: add E2E tests for claude-code-agent A2A"
```

---

## Phase 3: OpenHands + A2A Wrapper

### Task 6: Scaffold the OpenHands agent directory

**Files:**
- Create: `.worktrees/agent-examples/a2a/openhands_agent/pyproject.toml`
- Create: `.worktrees/agent-examples/a2a/openhands_agent/Dockerfile`
- Create: `.worktrees/agent-examples/a2a/openhands_agent/src/openhands_agent/__init__.py`

**Step 1: Create pyproject.toml**

```toml
[project]
name = "openhands-agent"
version = "0.0.1"
description = "OpenHands wrapped as an A2A service for Kagenti."
requires-python = ">=3.11"
dependencies = [
    "a2a-sdk>=0.2.16",
    "openhands-ai>=0.30.0",
    "litellm>=1.50.0",
    "pydantic-settings>=2.8.1",
    "opentelemetry-exporter-otlp",
    "opentelemetry-instrumentation-starlette",
]

[project.scripts]
server = "openhands_agent.agent:run"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"
```

**Step 2: Create Dockerfile**

```dockerfile
FROM python:3.11-slim

RUN apt-get update && apt-get install -y git curl && rm -rf /var/lib/apt/lists/*

WORKDIR /app

RUN pip install --no-cache-dir uv

COPY pyproject.toml uv.lock* ./
RUN uv pip install --system -e .

COPY src/ src/

EXPOSE 8000

CMD ["server"]
```

**Step 3: Create `__init__.py`**

```python
"""OpenHands Agent — OpenHands wrapped as A2A service."""
```

**Step 4: Commit**

```bash
cd .worktrees/agent-examples
git add a2a/openhands_agent/
git commit -s -m "feat: scaffold openhands-agent directory"
```

---

### Task 7: Write the A2A wrapper for OpenHands

**Files:**
- Create: `.worktrees/agent-examples/a2a/openhands_agent/src/openhands_agent/agent.py`
- Create: `.worktrees/agent-examples/a2a/openhands_agent/tests/test_agent_card.py`

**Step 1: Write the failing test**

```python
"""Test agent card generation."""
from openhands_agent.agent import get_agent_card


def test_agent_card_has_required_fields():
    card = get_agent_card("localhost", 8000)
    assert card.name == "OpenHands Agent"
    assert card.url == "http://localhost:8000/"
    assert card.version == "1.0.0"
    assert card.capabilities.streaming is True
    assert len(card.skills) >= 1
    assert card.skills[0].id == "openhands_coding"


def test_agent_card_description():
    card = get_agent_card("localhost", 8000)
    assert "OpenHands" in card.description
    assert "MIT" in card.description or "open-source" in card.description.lower()
```

**Step 2: Run test to verify it fails**

```bash
cd .worktrees/agent-examples/a2a/openhands_agent
uv run pytest tests/test_agent_card.py -v
```

Expected: FAIL

**Step 3: Write the A2A wrapper**

```python
"""A2A agent server wrapping OpenHands."""

import logging
import os
from textwrap import dedent

import uvicorn
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.apps import A2AStarletteApplication
from a2a.server.events.event_queue import EventQueue
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.tasks import InMemoryTaskStore, TaskUpdater
from a2a.types import (
    AgentCapabilities,
    AgentCard,
    AgentSkill,
    Part,
    TaskState,
    TextPart,
)
from a2a.utils import new_agent_text_message, new_task
from starlette.routing import Route

logger = logging.getLogger(__name__)


def get_agent_card(host: str, port: int) -> AgentCard:
    """Return the A2A AgentCard for the OpenHands Agent."""
    return AgentCard(
        name="OpenHands Agent",
        description=dedent("""\
            OpenHands (open-source, MIT) wrapped as an A2A service on Kagenti.
            ## Key Features
            - **100+ LLM providers** via LiteLLM
            - **Docker-native sandboxing** per session
            - **Rich capabilities** — shell, browser, Jupyter, VS Code
            - **MCP integration** via V1 SDK
            """),
        url=f"http://{host}:{port}/",
        version="1.0.0",
        default_input_modes=["text"],
        default_output_modes=["text"],
        capabilities=AgentCapabilities(streaming=True),
        skills=[
            AgentSkill(
                id="openhands_coding",
                name="OpenHands Coding",
                description="Open-source autonomous coding agent with Docker sandbox.",
                tags=["coding", "openhands", "open-source", "docker"],
                examples=[
                    "Create a REST API with FastAPI",
                    "Debug the failing test in test_auth.py",
                    "Set up a React frontend with routing",
                ],
            ),
        ],
    )


class OpenHandsExecutor(AgentExecutor):
    """A2A executor delegating to OpenHands AgentController."""

    async def execute(
        self, context: RequestContext, event_queue: EventQueue
    ) -> None:
        task = context.current_task
        if not task:
            task = new_task(context.message)
            await event_queue.enqueue_event(task)

        task_updater = TaskUpdater(event_queue, task.id, task.context_id)
        await task_updater.update_status(
            TaskState.working,
            new_agent_text_message("Processing with OpenHands..."),
        )

        user_input = context.get_user_input()
        workspace = os.environ.get("WORKSPACE_DIR", "/workspace")
        model = os.environ.get("LLM_MODEL", "openai/gpt-4o")

        try:
            from openhands.core.config import AppConfig, SandboxConfig, LLMConfig
            from openhands.controller import AgentController
            from openhands.events.action import MessageAction

            config = AppConfig(
                workspace_dir=workspace,
                sandbox=SandboxConfig(runtime_cls="local"),
                llm=LLMConfig(model=model),
            )
            controller = AgentController(config=config)

            full_response = ""
            initial_action = MessageAction(content=user_input)

            async for event in controller.run(initial_action):
                if hasattr(event, "content") and event.content:
                    chunk = str(event.content)
                    full_response += chunk
                    await task_updater.update_status(
                        TaskState.working,
                        new_agent_text_message(chunk),
                    )

            parts: list[Part] = [TextPart(text=full_response)]
            await task_updater.add_artifact(parts)
            await task_updater.complete()

        except Exception as e:
            logger.exception("OpenHands execution failed")
            await task_updater.update_status(
                TaskState.failed,
                new_agent_text_message(f"Error: {e}"),
            )
            raise


def run() -> None:
    """Create A2A server and run with uvicorn."""
    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", "8000"))

    agent_card = get_agent_card(host=host, port=port)
    request_handler = DefaultRequestHandler(
        agent_executor=OpenHandsExecutor(),
        task_store=InMemoryTaskStore(),
    )
    server = A2AStarletteApplication(
        agent_card=agent_card,
        http_handler=request_handler,
    )
    app = server.build()
    app.routes.insert(
        0,
        Route(
            "/.well-known/agent-card.json",
            server._handle_get_agent_card,
            methods=["GET"],
        ),
    )

    logger.info("OpenHands Agent starting on %s:%d", host, port)
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    run()
```

**Step 4: Run tests**

```bash
uv run pytest tests/ -v
```

Expected: PASS

**Step 5: Commit**

```bash
git add -A
git commit -s -m "feat: add OpenHands A2A wrapper"
```

---

### Task 8: Create OpenHands K8s manifests and E2E test

**Files:**
- Create: `kagenti/examples/agents/openhands_agent_shipwright_build.yaml`
- Create: `kagenti/examples/agents/openhands_agent_deployment.yaml`
- Create: `kagenti/examples/agents/openhands_agent_service.yaml`
- Create: `kagenti/tests/e2e/common/test_openhands_agent.py`

Follow the exact same patterns as Task 4 and Task 5 but with:
- `kagenti.io/framework: openhands`
- `app.kubernetes.io/name: openhands-agent`
- Image: `registry.cr-system.svc.cluster.local:5000/openhands-agent:v0.0.1`
- No `ANTHROPIC_API_KEY` — use `LLM_API_BASE` + `LLM_MODEL` (model-agnostic via LiteLLM)
- E2E test class: `TestOpenHandsAgent`

**Commit:**

```bash
git add kagenti/examples/agents/openhands_agent_* kagenti/tests/e2e/common/test_openhands_agent.py
git commit -s -m "feat: add K8s manifests and E2E tests for openhands-agent"
```

---

## Phase 4: Multi-Framework Integration

### Task 9: Add framework label to Kagenti UI agent catalog

**Files:**
- Modify: `kagenti/ui-v2/src/pages/AgentCatalogPage.tsx`

**Step 1: Identify the agent table columns**

The existing agent catalog shows Name, Description, Status, Labels. Add a dedicated **Framework** column that reads `kagenti.io/framework` from labels and renders a colored badge:

- `langgraph` → green badge
- `claude-agent-sdk` → purple badge
- `openhands` → orange badge
- `goose` → yellow badge
- default → gray badge

**Step 2: Add framework badge component**

Add to the existing labels rendering logic in the agent catalog table. The label `kagenti.io/framework` should render as a distinct badge separate from other labels.

**Step 3: Commit**

```bash
git add kagenti/ui-v2/src/pages/AgentCatalogPage.tsx
git commit -s -m "feat(ui): add framework badge to agent catalog"
```

---

### Task 10: Add multi-agent deploy script

**Files:**
- Create: `.github/scripts/kagenti-operator/40-deploy-multi-framework-agents.sh`

**Step 1: Write the deploy script**

Script that deploys all three agent variants (weather/LangGraph, claude-code-agent, openhands-agent) to a cluster, following the pattern of existing deploy scripts in `.github/scripts/kagenti-operator/`.

```bash
#!/usr/bin/env bash
set -euo pipefail

# 40-deploy-multi-framework-agents.sh
# Deploys multiple agent framework variants to demonstrate Kagenti's framework neutrality.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
NAMESPACE="${AGENT_NAMESPACE:-team1}"

echo "=== Deploying Multi-Framework Agents to $NAMESPACE ==="

# 1. Deploy LangGraph agent (existing weather service)
echo "--- LangGraph Agent (weather-service) ---"
kubectl apply -f "$REPO_ROOT/kagenti/examples/agents/weather_agent_shipwright_build.yaml" -n "$NAMESPACE"
kubectl apply -f "$REPO_ROOT/kagenti/examples/agents/weather_service_deployment.yaml" -n "$NAMESPACE"
kubectl apply -f "$REPO_ROOT/kagenti/examples/agents/weather_service_service.yaml" -n "$NAMESPACE"

# 2. Deploy Claude Agent SDK agent
echo "--- Claude Agent SDK (claude-code-agent) ---"
kubectl apply -f "$REPO_ROOT/kagenti/examples/agents/claude_code_agent_shipwright_build.yaml" -n "$NAMESPACE"
kubectl apply -f "$REPO_ROOT/kagenti/examples/agents/claude_code_agent_deployment.yaml" -n "$NAMESPACE"
kubectl apply -f "$REPO_ROOT/kagenti/examples/agents/claude_code_agent_service.yaml" -n "$NAMESPACE"

# 3. Deploy OpenHands agent
echo "--- OpenHands (openhands-agent) ---"
kubectl apply -f "$REPO_ROOT/kagenti/examples/agents/openhands_agent_shipwright_build.yaml" -n "$NAMESPACE"
kubectl apply -f "$REPO_ROOT/kagenti/examples/agents/openhands_agent_deployment.yaml" -n "$NAMESPACE"
kubectl apply -f "$REPO_ROOT/kagenti/examples/agents/openhands_agent_service.yaml" -n "$NAMESPACE"

echo ""
echo "=== Waiting for deployments ==="
kubectl rollout status deployment/weather-service -n "$NAMESPACE" --timeout=120s || true
kubectl rollout status deployment/claude-code-agent -n "$NAMESPACE" --timeout=120s || true
kubectl rollout status deployment/openhands-agent -n "$NAMESPACE" --timeout=120s || true

echo ""
echo "=== Agent A2A Discovery ==="
for agent in weather-service claude-code-agent openhands-agent; do
    echo -n "$agent: "
    kubectl exec -n "$NAMESPACE" deploy/$agent -- \
        curl -s http://localhost:8000/.well-known/agent-card.json | \
        python3 -c "import sys,json; d=json.load(sys.stdin); print(f'{d[\"name\"]} ({d[\"version\"]})')" \
        2>/dev/null || echo "not ready"
done

echo ""
echo "=== Framework Labels ==="
kubectl get deploy -n "$NAMESPACE" -l kagenti.io/type=agent \
    -o custom-columns='NAME:.metadata.name,FRAMEWORK:.metadata.labels.kagenti\.io/framework,PROTOCOL:.metadata.labels.kagenti\.io/protocol'
```

**Step 2: Make executable and commit**

```bash
chmod +x .github/scripts/kagenti-operator/40-deploy-multi-framework-agents.sh
git add .github/scripts/kagenti-operator/40-deploy-multi-framework-agents.sh
git commit -s -m "feat: add multi-framework agent deploy script"
```

---

### Task 11: Write multi-framework E2E test

**Files:**
- Create: `kagenti/tests/e2e/common/test_multi_framework.py`

**Step 1: Write the test**

```python
"""E2E test verifying multiple agent frameworks coexist on Kagenti."""
import os
import pytest
import httpx


NAMESPACE = os.getenv("AGENT_NAMESPACE", "team1")
AGENTS = {
    "weather-service": {
        "url": os.getenv("WEATHER_AGENT_URL", f"http://weather-service.{NAMESPACE}.svc.cluster.local:8000"),
        "framework": "LangGraph",
    },
    "claude-code-agent": {
        "url": os.getenv("CLAUDE_AGENT_URL", f"http://claude-code-agent.{NAMESPACE}.svc.cluster.local:8000"),
        "framework": "claude-agent-sdk",
    },
    "openhands-agent": {
        "url": os.getenv("OPENHANDS_AGENT_URL", f"http://openhands-agent.{NAMESPACE}.svc.cluster.local:8000"),
        "framework": "openhands",
    },
}
SSL_VERIFY = os.getenv("SSL_VERIFY", "true").lower() == "true"


class TestMultiFrameworkCoexistence:
    """Verify all agent frameworks are deployed and discoverable."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("agent_name", AGENTS.keys())
    async def test_agent_card_discoverable(self, agent_name):
        """Each agent exposes a valid A2A agent card."""
        agent = AGENTS[agent_name]
        async with httpx.AsyncClient(verify=SSL_VERIFY, timeout=30.0) as client:
            resp = await client.get(f"{agent['url']}/.well-known/agent-card.json")
            assert resp.status_code == 200, f"{agent_name} agent card not reachable"
            card = resp.json()
            assert "name" in card
            assert "capabilities" in card
            assert "skills" in card
            assert len(card["skills"]) >= 1

    @pytest.mark.asyncio
    @pytest.mark.parametrize("agent_name", AGENTS.keys())
    async def test_agent_has_streaming(self, agent_name):
        """Each agent supports streaming."""
        agent = AGENTS[agent_name]
        async with httpx.AsyncClient(verify=SSL_VERIFY, timeout=30.0) as client:
            resp = await client.get(f"{agent['url']}/.well-known/agent-card.json")
            card = resp.json()
            assert card["capabilities"]["streaming"] is True

    @pytest.mark.asyncio
    async def test_all_agents_have_unique_names(self):
        """No two agents share the same A2A agent name."""
        names = []
        async with httpx.AsyncClient(verify=SSL_VERIFY, timeout=30.0) as client:
            for agent_name, agent in AGENTS.items():
                resp = await client.get(f"{agent['url']}/.well-known/agent-card.json")
                if resp.status_code == 200:
                    names.append(resp.json()["name"])
        assert len(names) == len(set(names)), f"Duplicate agent names: {names}"
```

**Step 2: Commit**

```bash
git add kagenti/tests/e2e/common/test_multi_framework.py
git commit -s -m "test: add multi-framework coexistence E2E tests"
```

---

## Summary

| Phase | Task | Description | Effort |
|-------|------|-------------|--------|
| 1 | 0 | Scaffold opencode-agent directory | 15 min |
| 1 | 0b | Write A2A wrapper for OpenCode (opencode serve proxy) | 30 min |
| 1 | 0c | Create OpenCode K8s manifests + E2E test | 30 min |
| 2 | 1 | Scaffold claude-code-agent directory | 15 min |
| 2 | 2 | Write A2A wrapper for Claude Agent SDK | 30 min |
| 2 | 3 | Write executor unit tests | 20 min |
| 2 | 4 | Create K8s deployment manifests | 15 min |
| 2 | 5 | Write E2E test | 20 min |
| 3 | 6 | Scaffold openhands-agent directory | 15 min |
| 3 | 7 | Write A2A wrapper for OpenHands | 30 min |
| 3 | 8 | Create K8s manifests + E2E test | 30 min |
| 4 | 9 | Add framework badge to Kagenti UI | 30 min |
| 4 | 10 | Multi-agent deploy script | 20 min |
| 4 | 11 | Multi-framework E2E test | 20 min |

**Total:** ~5.5 hours across 14 tasks

**Dependencies:**
- Tasks 0-0c (Phase 1: OpenCode) — deploy first after sandbox-legion
- Tasks 1-5 (Phase 2: Claude Agent SDK) — can run in parallel with Phase 1
- Tasks 6-8 (Phase 3: OpenHands) — can run in parallel with Phases 1-2
- Tasks 9-11 (Phase 4: Multi-Framework) — depends on at least 2 agent variants deployed
