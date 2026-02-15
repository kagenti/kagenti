# Agent Context Isolation - Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a sandboxed agent that runs shell tools within per-context isolated workspaces on a shared RWX PVC, with settings.json/sources.json operation control and LangGraph PostgreSQL checkpointing.

**Architecture:** Fork the weather_service agent as `sandbox_agent` in the agent-examples worktree. Add a permission checker (settings.json), a capability loader (sources.json), a context workspace manager, and a sandbox executor that runs shell commands confined to the context's workspace subdirectory. Wire LangGraph `AsyncPostgresSaver` for cross-pod state persistence. Deploy with a shared RWX PVC.

**Tech Stack:** Python 3.12, LangGraph, A2A SDK, AsyncPostgresSaver (langgraph-checkpoint-postgres), asyncio subprocess, Pydantic, Starlette

---

## Task 1: Scaffold sandbox_agent from weather_service

**Files:**
- Create: `.worktrees/agent-examples/a2a/sandbox_agent/pyproject.toml`
- Create: `.worktrees/agent-examples/a2a/sandbox_agent/src/sandbox_agent/__init__.py`
- Create: `.worktrees/agent-examples/a2a/sandbox_agent/src/sandbox_agent/configuration.py`
- Create: `.worktrees/agent-examples/a2a/sandbox_agent/Dockerfile`
- Reference: `.worktrees/agent-examples/a2a/weather_service/pyproject.toml`
- Reference: `.worktrees/agent-examples/a2a/weather_service/Dockerfile`

**Step 1: Create pyproject.toml**

```toml
[project]
name = "sandbox-agent"
version = "0.0.1"
description = "LangGraph agent with sandboxed shell execution and per-context workspace isolation."
authors = []
readme = "README.md"
license = { text = "Apache" }
requires-python = ">=3.11"
dependencies = [
    "a2a-sdk>=0.2.16",
    "langgraph>=0.2.55",
    "langchain-community>=0.3.9",
    "langchain-openai>=0.3.7",
    "langgraph-checkpoint-postgres>=3.0.0",
    "psycopg[binary]>=3.1.0",
    "pydantic-settings>=2.8.1",
    "opentelemetry-exporter-otlp",
    "opentelemetry-instrumentation-starlette",
]

[project.scripts]
server = "sandbox_agent.agent:run"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"
```

**Step 2: Create configuration.py**

```python
from pydantic_settings import BaseSettings


class Configuration(BaseSettings):
    llm_model: str = "llama3.1"
    llm_api_base: str = "http://localhost:11434/v1"
    llm_api_key: str = "dummy"
    workspace_root: str = "/workspace"
    checkpoint_db_url: str = "postgresql://kagenti:kagenti@localhost:5432/kagenti_checkpoints"
    context_ttl_days: int = 7
```

**Step 3: Create empty `__init__.py`**

```python
```

**Step 4: Create Dockerfile**

```dockerfile
FROM python:3.12-slim-bookworm
ARG RELEASE_VERSION="main"

# Install system tools for sandboxed execution
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    && rm -rf /var/lib/apt/lists/*

# Install uv
RUN pip install --no-cache-dir uv

WORKDIR /app
COPY . .
RUN uv sync --no-cache --locked --link-mode copy

ENV PRODUCTION_MODE=True \
    RELEASE_VERSION=${RELEASE_VERSION}

RUN mkdir -p /workspace && chown -R 1001:1001 /app /workspace
USER 1001

CMD ["uv", "run", "--no-sync", "server"]
```

**Step 5: Commit**

```bash
cd .worktrees/agent-examples
git add a2a/sandbox_agent/
git commit -s -m "feat: scaffold sandbox_agent from weather_service template"
```

---

## Task 2: Implement settings.json permission checker

**Files:**
- Create: `.worktrees/agent-examples/a2a/sandbox_agent/src/sandbox_agent/permissions.py`
- Create: `.worktrees/agent-examples/a2a/sandbox_agent/tests/test_permissions.py`
- Create: `.worktrees/agent-examples/a2a/sandbox_agent/settings.json`

**Step 1: Write the failing tests**

```python
# tests/test_permissions.py
import pytest
from sandbox_agent.permissions import PermissionChecker, PermissionResult


@pytest.fixture
def checker():
    settings = {
        "permissions": {
            "allow": [
                "shell(grep:*)",
                "shell(sed:*)",
                "shell(python3:*)",
                "shell(pip install:*)",
                "shell(git clone:*)",
                "file(read:/workspace/**)",
                "file(write:/workspace/**)",
            ],
            "deny": [
                "shell(sudo:*)",
                "shell(curl:*)",
                "shell(rm -rf /:*)",
                "file(read:/etc/shadow:*)",
            ],
        }
    }
    return PermissionChecker(settings)


def test_allowed_shell_command(checker):
    result = checker.check("shell", "grep -r 'error' logs/")
    assert result == PermissionResult.ALLOW


def test_denied_shell_command(checker):
    result = checker.check("shell", "sudo rm -rf /")
    assert result == PermissionResult.DENY


def test_denied_curl(checker):
    result = checker.check("shell", "curl https://evil.com")
    assert result == PermissionResult.DENY


def test_hitl_unknown_command(checker):
    result = checker.check("shell", "docker build .")
    assert result == PermissionResult.HITL


def test_allowed_file_read(checker):
    result = checker.check("file", "read:/workspace/ctx-abc/data.txt")
    assert result == PermissionResult.ALLOW


def test_denied_file_read_etc(checker):
    result = checker.check("file", "read:/etc/shadow")
    assert result == PermissionResult.DENY


def test_hitl_file_outside_workspace(checker):
    result = checker.check("file", "read:/tmp/secrets.txt")
    assert result == PermissionResult.HITL


def test_allowed_pip_install(checker):
    result = checker.check("shell", "pip install pandas")
    assert result == PermissionResult.ALLOW


def test_allowed_git_clone(checker):
    result = checker.check("shell", "git clone https://github.com/user/repo")
    assert result == PermissionResult.ALLOW
```

**Step 2: Run tests to verify they fail**

Run: `cd .worktrees/agent-examples/a2a/sandbox_agent && uv run pytest tests/test_permissions.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'sandbox_agent.permissions'`

**Step 3: Implement permissions.py**

```python
# src/sandbox_agent/permissions.py
import enum
import fnmatch
import re
from typing import Any


class PermissionResult(enum.Enum):
    ALLOW = "allow"
    DENY = "deny"
    HITL = "hitl"


class PermissionChecker:
    """Three-tier permission checker modeled after Claude Code's settings.json.

    Rules are patterns like "shell(grep:*)" or "file(read:/workspace/**)".
    Pattern matching:
      - "shell(grep:*)" matches any shell command starting with "grep"
      - "file(read:/workspace/**)" matches file reads under /workspace/
      - "*" matches any single path segment
      - "**" matches any depth of path segments
    """

    def __init__(self, settings: dict[str, Any]):
        perms = settings.get("permissions", {})
        self._allow_rules: list[str] = perms.get("allow", [])
        self._deny_rules: list[str] = perms.get("deny", [])

    def check(self, operation_type: str, operation: str) -> PermissionResult:
        """Check if an operation is allowed, denied, or needs HITL approval.

        Deny rules are checked first (deny takes precedence).
        Then allow rules.
        If neither matches, HITL.
        """
        canonical = f"{operation_type}({operation})"

        for rule in self._deny_rules:
            if self._matches(rule, canonical):
                return PermissionResult.DENY

        for rule in self._allow_rules:
            if self._matches(rule, canonical):
                return PermissionResult.ALLOW

        return PermissionResult.HITL

    def _matches(self, rule: str, canonical: str) -> bool:
        """Match a rule pattern against a canonical operation string.

        Rule format: "type(command_prefix:*)" or "type(path_pattern)"
        Canonical format: "type(actual_command_or_path)"
        """
        # Extract type and pattern from rule
        rule_match = re.match(r"^(\w+)\((.+)\)$", rule)
        if not rule_match:
            return False
        rule_type, rule_pattern = rule_match.group(1), rule_match.group(2)

        # Extract type and value from canonical
        canon_match = re.match(r"^(\w+)\((.+)\)$", canonical)
        if not canon_match:
            return False
        canon_type, canon_value = canon_match.group(1), canon_match.group(2)

        if rule_type != canon_type:
            return False

        # For shell rules: "command_prefix:*" means the command starts with command_prefix
        if rule_pattern.endswith(":*"):
            prefix = rule_pattern[:-2]  # Remove ":*"
            return canon_value.startswith(prefix) or canon_value == prefix

        # For file rules with glob patterns
        # Convert ** to match any depth
        glob_pattern = rule_pattern.replace("**", "DOUBLESTAR")
        glob_pattern = glob_pattern.replace("*", "[^/]*")
        glob_pattern = glob_pattern.replace("DOUBLESTAR", ".*")
        return bool(re.match(f"^{glob_pattern}$", canon_value))
```

**Step 4: Run tests to verify they pass**

Run: `cd .worktrees/agent-examples/a2a/sandbox_agent && uv run pytest tests/test_permissions.py -v`
Expected: All 9 tests PASS

**Step 5: Create settings.json**

Copy the full settings.json from the design doc (lines 173-241 of the design).

**Step 6: Commit**

```bash
cd .worktrees/agent-examples
git add a2a/sandbox_agent/src/sandbox_agent/permissions.py a2a/sandbox_agent/tests/test_permissions.py a2a/sandbox_agent/settings.json
git commit -s -m "feat: add settings.json permission checker (allow/deny/HITL)"
```

---

## Task 3: Implement sources.json capability loader

**Files:**
- Create: `.worktrees/agent-examples/a2a/sandbox_agent/src/sandbox_agent/sources.py`
- Create: `.worktrees/agent-examples/a2a/sandbox_agent/tests/test_sources.py`
- Create: `.worktrees/agent-examples/a2a/sandbox_agent/sources.json`

**Step 1: Write the failing tests**

```python
# tests/test_sources.py
import pytest
from sandbox_agent.sources import SourcesConfig


@pytest.fixture
def sources():
    return SourcesConfig.from_dict({
        "agent_type": "python-data-agent",
        "package_managers": {
            "pip": {
                "enabled": True,
                "registries": [
                    {"name": "pypi", "url": "https://pypi.org/simple/", "trusted": True}
                ],
                "max_install_size_mb": 500,
                "blocked_packages": ["subprocess32", "pyautogui"],
            },
            "npm": {"enabled": False},
        },
        "web_access": {
            "enabled": True,
            "allowed_domains": ["api.github.com", "pypi.org"],
            "blocked_domains": ["*.internal"],
        },
        "git": {
            "enabled": True,
            "allowed_remotes": ["https://github.com/*"],
            "max_clone_size_mb": 1000,
        },
        "runtime": {
            "languages": ["python3.11", "bash"],
            "max_execution_time_seconds": 300,
            "max_memory_mb": 2048,
        },
    })


def test_pip_enabled(sources):
    assert sources.is_package_manager_enabled("pip")


def test_npm_disabled(sources):
    assert not sources.is_package_manager_enabled("npm")


def test_blocked_package(sources):
    assert sources.is_package_blocked("pip", "subprocess32")


def test_allowed_package(sources):
    assert not sources.is_package_blocked("pip", "pandas")


def test_allowed_git_remote(sources):
    assert sources.is_git_remote_allowed("https://github.com/user/repo")


def test_blocked_git_remote(sources):
    assert not sources.is_git_remote_allowed("https://gitlab.com/user/repo")


def test_max_execution_time(sources):
    assert sources.max_execution_time_seconds == 300


def test_max_memory(sources):
    assert sources.max_memory_mb == 2048
```

**Step 2: Run tests to verify they fail**

Run: `cd .worktrees/agent-examples/a2a/sandbox_agent && uv run pytest tests/test_sources.py -v`
Expected: FAIL with `ModuleNotFoundError`

**Step 3: Implement sources.py**

```python
# src/sandbox_agent/sources.py
import fnmatch
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class SourcesConfig:
    """Declares what an agent can access. Baked into the agent image."""

    agent_type: str = ""
    _package_managers: dict[str, Any] = field(default_factory=dict)
    _web_access: dict[str, Any] = field(default_factory=dict)
    _git: dict[str, Any] = field(default_factory=dict)
    _runtime: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SourcesConfig":
        return cls(
            agent_type=data.get("agent_type", ""),
            _package_managers=data.get("package_managers", {}),
            _web_access=data.get("web_access", {}),
            _git=data.get("git", {}),
            _runtime=data.get("runtime", {}),
        )

    @classmethod
    def from_file(cls, path: str | Path) -> "SourcesConfig":
        with open(path) as f:
            return cls.from_dict(json.load(f))

    def is_package_manager_enabled(self, name: str) -> bool:
        pm = self._package_managers.get(name, {})
        return pm.get("enabled", False)

    def is_package_blocked(self, manager: str, package: str) -> bool:
        pm = self._package_managers.get(manager, {})
        blocked = pm.get("blocked_packages", [])
        return package in blocked

    def is_git_remote_allowed(self, url: str) -> bool:
        if not self._git.get("enabled", False):
            return False
        allowed = self._git.get("allowed_remotes", [])
        return any(fnmatch.fnmatch(url, pattern) for pattern in allowed)

    @property
    def max_execution_time_seconds(self) -> int:
        return self._runtime.get("max_execution_time_seconds", 300)

    @property
    def max_memory_mb(self) -> int:
        return self._runtime.get("max_memory_mb", 2048)
```

**Step 4: Run tests to verify they pass**

Run: `cd .worktrees/agent-examples/a2a/sandbox_agent && uv run pytest tests/test_sources.py -v`
Expected: All 8 tests PASS

**Step 5: Create sources.json**

Copy the full sources.json from the design doc (lines 280-330 of the design).

**Step 6: Commit**

```bash
cd .worktrees/agent-examples
git add a2a/sandbox_agent/src/sandbox_agent/sources.py a2a/sandbox_agent/tests/test_sources.py a2a/sandbox_agent/sources.json
git commit -s -m "feat: add sources.json capability loader"
```

---

## Task 4: Implement context workspace manager

**Files:**
- Create: `.worktrees/agent-examples/a2a/sandbox_agent/src/sandbox_agent/workspace.py`
- Create: `.worktrees/agent-examples/a2a/sandbox_agent/tests/test_workspace.py`

**Step 1: Write the failing tests**

```python
# tests/test_workspace.py
import json
import os
import pytest
import tempfile
from sandbox_agent.workspace import WorkspaceManager


@pytest.fixture
def workspace_root(tmp_path):
    return str(tmp_path / "workspace")


@pytest.fixture
def manager(workspace_root):
    return WorkspaceManager(
        workspace_root=workspace_root,
        agent_name="test-agent",
        namespace="team1",
        ttl_days=7,
    )


def test_ensure_workspace_creates_dirs(manager, workspace_root):
    ctx_id = "ctx-abc123"
    path = manager.ensure_workspace(ctx_id)
    assert os.path.isdir(path)
    assert os.path.isdir(os.path.join(path, "scripts"))
    assert os.path.isdir(os.path.join(path, "data"))
    assert os.path.isdir(os.path.join(path, "repos"))
    assert os.path.isdir(os.path.join(path, "output"))


def test_ensure_workspace_creates_context_json(manager):
    ctx_id = "ctx-abc123"
    path = manager.ensure_workspace(ctx_id)
    context_file = os.path.join(path, ".context.json")
    assert os.path.exists(context_file)
    with open(context_file) as f:
        data = json.load(f)
    assert data["context_id"] == ctx_id
    assert data["agent"] == "test-agent"
    assert data["namespace"] == "team1"
    assert data["ttl_days"] == 7


def test_ensure_workspace_idempotent(manager):
    ctx_id = "ctx-abc123"
    path1 = manager.ensure_workspace(ctx_id)
    path2 = manager.ensure_workspace(ctx_id)
    assert path1 == path2


def test_ensure_workspace_updates_last_accessed(manager):
    ctx_id = "ctx-abc123"
    path = manager.ensure_workspace(ctx_id)
    with open(os.path.join(path, ".context.json")) as f:
        data1 = json.load(f)
    # Call again to update timestamp
    manager.ensure_workspace(ctx_id)
    with open(os.path.join(path, ".context.json")) as f:
        data2 = json.load(f)
    assert data2["last_accessed_at"] >= data1["last_accessed_at"]


def test_get_workspace_path(manager, workspace_root):
    ctx_id = "ctx-abc123"
    path = manager.get_workspace_path(ctx_id)
    assert path == os.path.join(workspace_root, ctx_id)


def test_list_contexts_empty(manager):
    assert manager.list_contexts() == []


def test_list_contexts(manager):
    manager.ensure_workspace("ctx-aaa")
    manager.ensure_workspace("ctx-bbb")
    contexts = manager.list_contexts()
    assert sorted(contexts) == ["ctx-aaa", "ctx-bbb"]


def test_no_workspace_without_context_id(manager):
    """No context_id = no workspace created."""
    path = manager.get_workspace_path("")
    assert not os.path.exists(path)
```

**Step 2: Run tests to verify they fail**

Run: `cd .worktrees/agent-examples/a2a/sandbox_agent && uv run pytest tests/test_workspace.py -v`
Expected: FAIL

**Step 3: Implement workspace.py**

```python
# src/sandbox_agent/workspace.py
import json
import os
from datetime import datetime, timezone


WORKSPACE_SUBDIRS = ["scripts", "data", "repos", "output"]


class WorkspaceManager:
    """Manages per-context workspace directories on the shared RWX PVC."""

    def __init__(
        self,
        workspace_root: str,
        agent_name: str,
        namespace: str = "",
        ttl_days: int = 7,
    ):
        self.workspace_root = workspace_root
        self.agent_name = agent_name
        self.namespace = namespace
        self.ttl_days = ttl_days

    def get_workspace_path(self, context_id: str) -> str:
        """Return the workspace path for a context_id."""
        return os.path.join(self.workspace_root, context_id)

    def ensure_workspace(self, context_id: str) -> str:
        """Create workspace directory structure if it doesn't exist.
        Updates last_accessed timestamp on every call.
        Returns the workspace path.
        """
        path = self.get_workspace_path(context_id)
        for subdir in WORKSPACE_SUBDIRS:
            os.makedirs(os.path.join(path, subdir), exist_ok=True)

        context_file = os.path.join(path, ".context.json")
        now = datetime.now(timezone.utc).isoformat()

        if os.path.exists(context_file):
            with open(context_file) as f:
                data = json.load(f)
            data["last_accessed_at"] = now
        else:
            data = {
                "context_id": context_id,
                "agent": self.agent_name,
                "namespace": self.namespace,
                "created_at": now,
                "last_accessed_at": now,
                "ttl_days": self.ttl_days,
                "disk_usage_bytes": 0,
            }

        with open(context_file, "w") as f:
            json.dump(data, f, indent=2)

        return path

    def list_contexts(self) -> list[str]:
        """List all context_ids with workspaces."""
        if not os.path.exists(self.workspace_root):
            return []
        return [
            d
            for d in os.listdir(self.workspace_root)
            if os.path.isdir(os.path.join(self.workspace_root, d))
        ]
```

**Step 4: Run tests to verify they pass**

Run: `cd .worktrees/agent-examples/a2a/sandbox_agent && uv run pytest tests/test_workspace.py -v`
Expected: All 8 tests PASS

**Step 5: Commit**

```bash
cd .worktrees/agent-examples
git add a2a/sandbox_agent/src/sandbox_agent/workspace.py a2a/sandbox_agent/tests/test_workspace.py
git commit -s -m "feat: add context workspace manager"
```

---

## Task 5: Implement sandbox executor

**Files:**
- Create: `.worktrees/agent-examples/a2a/sandbox_agent/src/sandbox_agent/executor.py`
- Create: `.worktrees/agent-examples/a2a/sandbox_agent/tests/test_executor.py`

**Step 1: Write the failing tests**

```python
# tests/test_executor.py
import os
import pytest
from sandbox_agent.executor import SandboxExecutor, ExecutionResult
from sandbox_agent.permissions import PermissionChecker
from sandbox_agent.sources import SourcesConfig


@pytest.fixture
def workspace(tmp_path):
    ws = tmp_path / "workspace" / "ctx-test"
    ws.mkdir(parents=True)
    (ws / "scripts").mkdir()
    (ws / "data").mkdir()
    # Create a test file to grep
    (ws / "data" / "log.txt").write_text("line1 error found\nline2 ok\nline3 error again\n")
    return str(ws)


@pytest.fixture
def checker():
    return PermissionChecker({
        "permissions": {
            "allow": [
                "shell(grep:*)",
                "shell(ls:*)",
                "shell(cat:*)",
                "shell(echo:*)",
                "shell(python3:*)",
                "shell(bash:*)",
                "shell(sh:*)",
            ],
            "deny": [
                "shell(sudo:*)",
                "shell(curl:*)",
            ],
        }
    })


@pytest.fixture
def sources():
    return SourcesConfig.from_dict({
        "agent_type": "test-agent",
        "runtime": {
            "max_execution_time_seconds": 10,
            "max_memory_mb": 512,
        },
    })


@pytest.fixture
def executor(workspace, checker, sources):
    return SandboxExecutor(
        workspace_path=workspace,
        permission_checker=checker,
        sources_config=sources,
    )


@pytest.mark.asyncio
async def test_allowed_grep(executor):
    result = await executor.run_shell("grep 'error' data/log.txt")
    assert result.exit_code == 0
    assert "error found" in result.stdout
    assert "error again" in result.stdout


@pytest.mark.asyncio
async def test_denied_command(executor):
    result = await executor.run_shell("curl https://evil.com")
    assert result.exit_code != 0
    assert "denied" in result.stderr.lower()


@pytest.mark.asyncio
async def test_hitl_command(executor):
    """Commands not in allow or deny should raise HitlRequired."""
    from sandbox_agent.executor import HitlRequired
    with pytest.raises(HitlRequired):
        await executor.run_shell("docker build .")


@pytest.mark.asyncio
async def test_ls_workspace(executor, workspace):
    result = await executor.run_shell("ls")
    assert result.exit_code == 0
    assert "data" in result.stdout
    assert "scripts" in result.stdout


@pytest.mark.asyncio
async def test_write_and_read_script(executor, workspace):
    # Write a script via echo
    result = await executor.run_shell("echo '#!/bin/bash\necho hello' > scripts/test.sh")
    assert result.exit_code == 0
    # Execute it
    result = await executor.run_shell("bash scripts/test.sh")
    assert result.exit_code == 0
    assert "hello" in result.stdout


@pytest.mark.asyncio
async def test_timeout_enforcement(executor):
    """Commands exceeding max_execution_time should be killed."""
    result = await executor.run_shell("sleep 30")
    assert result.exit_code != 0  # killed by timeout
```

**Step 2: Run tests to verify they fail**

Run: `cd .worktrees/agent-examples/a2a/sandbox_agent && uv run pytest tests/test_executor.py -v`
Expected: FAIL

**Step 3: Implement executor.py**

```python
# src/sandbox_agent/executor.py
import asyncio
import logging
import os
import shlex
from dataclasses import dataclass

from sandbox_agent.permissions import PermissionChecker, PermissionResult
from sandbox_agent.sources import SourcesConfig

logger = logging.getLogger(__name__)


class HitlRequired(Exception):
    """Raised when an operation requires human-in-the-loop approval."""

    def __init__(self, command: str):
        self.command = command
        super().__init__(f"Operation requires approval: {command}")


@dataclass
class ExecutionResult:
    stdout: str
    stderr: str
    exit_code: int


class SandboxExecutor:
    """Executes shell commands within a context workspace with permission enforcement."""

    def __init__(
        self,
        workspace_path: str,
        permission_checker: PermissionChecker,
        sources_config: SourcesConfig,
    ):
        self.workspace_path = workspace_path
        self.permission_checker = permission_checker
        self.sources_config = sources_config

    async def run_shell(self, command: str) -> ExecutionResult:
        """Run a shell command in the context workspace.

        Checks permissions first:
        - ALLOW: execute immediately
        - DENY: return error result
        - HITL: raise HitlRequired
        """
        # Extract the command name for permission checking
        cmd_parts = command.split()
        if not cmd_parts:
            return ExecutionResult(stdout="", stderr="Empty command", exit_code=1)

        # Build the canonical command prefix for matching
        # Try progressively longer prefixes: "git clone", "git", etc.
        result = self._check_permission(command)

        if result == PermissionResult.DENY:
            logger.warning("Denied command: %s", command)
            return ExecutionResult(
                stdout="",
                stderr=f"Denied by settings.json: {command}",
                exit_code=1,
            )

        if result == PermissionResult.HITL:
            raise HitlRequired(command)

        # Execute the command
        return await self._execute(command)

    def _check_permission(self, command: str) -> PermissionResult:
        """Check permission using progressively longer command prefixes."""
        parts = command.split()
        # Try "cmd subcmd" first (e.g. "git clone"), then "cmd" (e.g. "git")
        for length in range(min(len(parts), 2), 0, -1):
            prefix = " ".join(parts[:length])
            result = self.permission_checker.check("shell", prefix)
            if result != PermissionResult.HITL:
                return result
        # If no specific match, check the first word
        return self.permission_checker.check("shell", parts[0])

    async def _execute(self, command: str) -> ExecutionResult:
        """Execute a command in the workspace directory with resource limits."""
        timeout = self.sources_config.max_execution_time_seconds

        try:
            process = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=self.workspace_path,
            )

            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(), timeout=timeout
                )
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
                return ExecutionResult(
                    stdout="",
                    stderr=f"Command timed out after {timeout}s: {command}",
                    exit_code=124,
                )

            return ExecutionResult(
                stdout=stdout.decode("utf-8", errors="replace"),
                stderr=stderr.decode("utf-8", errors="replace"),
                exit_code=process.returncode or 0,
            )

        except Exception as e:
            logger.error("Execution error: %s", e)
            return ExecutionResult(
                stdout="",
                stderr=str(e),
                exit_code=1,
            )
```

**Step 4: Run tests to verify they pass**

Run: `cd .worktrees/agent-examples/a2a/sandbox_agent && uv run pytest tests/test_executor.py -v`
Expected: All 6 tests PASS

**Step 5: Commit**

```bash
cd .worktrees/agent-examples
git add a2a/sandbox_agent/src/sandbox_agent/executor.py a2a/sandbox_agent/tests/test_executor.py
git commit -s -m "feat: add sandbox executor with permission enforcement"
```

---

## Task 6: Implement LangGraph graph with shell tools and checkpointing

**Files:**
- Create: `.worktrees/agent-examples/a2a/sandbox_agent/src/sandbox_agent/graph.py`
- Create: `.worktrees/agent-examples/a2a/sandbox_agent/tests/test_graph.py`
- Reference: `.worktrees/agent-examples/a2a/weather_service/src/weather_service/graph.py`

**Step 1: Write the failing tests**

```python
# tests/test_graph.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from sandbox_agent.graph import build_graph, SandboxState


def test_sandbox_state_has_required_fields():
    """SandboxState must have messages, context_id, workspace_path, and final_answer."""
    state = SandboxState(
        messages=[],
        context_id="ctx-test",
        workspace_path="/workspace/ctx-test",
    )
    assert state["context_id"] == "ctx-test"
    assert state["workspace_path"] == "/workspace/ctx-test"
    assert state["final_answer"] == ""


@pytest.mark.asyncio
async def test_build_graph_returns_compiled_graph():
    """build_graph should return a compiled LangGraph graph."""
    with patch("sandbox_agent.graph.ChatOpenAI"):
        graph = build_graph(
            workspace_path="/workspace/ctx-test",
            permission_checker=MagicMock(),
            sources_config=MagicMock(),
        )
    assert graph is not None
    # Compiled graphs have an invoke method
    assert hasattr(graph, "ainvoke")
```

**Step 2: Run tests to verify they fail**

Run: `cd .worktrees/agent-examples/a2a/sandbox_agent && uv run pytest tests/test_graph.py -v`
Expected: FAIL

**Step 3: Implement graph.py**

```python
# src/sandbox_agent/graph.py
import logging
import os
from typing import TypedDict

from langchain_core.messages import AIMessage, SystemMessage
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI
from langgraph.graph import StateGraph, MessagesState, START
from langgraph.prebuilt import tools_condition, ToolNode

from sandbox_agent.configuration import Configuration
from sandbox_agent.executor import SandboxExecutor, HitlRequired
from sandbox_agent.permissions import PermissionChecker
from sandbox_agent.sources import SourcesConfig

logger = logging.getLogger(__name__)
config = Configuration()


class SandboxState(MessagesState):
    context_id: str = ""
    workspace_path: str = ""
    final_answer: str = ""


def _make_shell_tool(executor: SandboxExecutor):
    """Create a LangGraph tool for shell execution."""

    @tool
    async def shell(command: str) -> str:
        """Run a shell command in the context workspace.

        Available commands include: grep, sed, awk, find, cat, head, tail,
        ls, tree, mkdir, cp, mv, python3, pip install, git clone, bash scripts.

        Args:
            command: The shell command to execute.
        """
        try:
            result = await executor.run_shell(command)
            output = result.stdout
            if result.stderr:
                output += f"\nSTDERR: {result.stderr}"
            if result.exit_code != 0:
                output += f"\nExit code: {result.exit_code}"
            return output or "(no output)"
        except HitlRequired as e:
            # In a full implementation, this triggers LangGraph interrupt()
            return f"APPROVAL_REQUIRED: {e.command}"

    return shell


def _make_file_read_tool(workspace_path: str):
    """Create a tool for reading files in the workspace."""

    @tool
    def read_file(path: str) -> str:
        """Read a file from the context workspace.

        Args:
            path: Relative path within the workspace (e.g., "data/results.csv").
        """
        full_path = os.path.join(workspace_path, path)
        # Prevent path traversal
        real_path = os.path.realpath(full_path)
        if not real_path.startswith(os.path.realpath(workspace_path)):
            return "Error: Path traversal not allowed"
        try:
            with open(real_path) as f:
                return f.read()
        except FileNotFoundError:
            return f"Error: File not found: {path}"

    return read_file


def _make_file_write_tool(workspace_path: str):
    """Create a tool for writing files in the workspace."""

    @tool
    def write_file(path: str, content: str) -> str:
        """Write content to a file in the context workspace.

        Args:
            path: Relative path within the workspace (e.g., "scripts/analyze.py").
            content: The content to write to the file.
        """
        full_path = os.path.join(workspace_path, path)
        real_path = os.path.realpath(full_path)
        if not real_path.startswith(os.path.realpath(workspace_path)):
            return "Error: Path traversal not allowed"
        os.makedirs(os.path.dirname(real_path), exist_ok=True)
        with open(real_path, "w") as f:
            f.write(content)
        return f"Written {len(content)} bytes to {path}"

    return write_file


def build_graph(
    workspace_path: str,
    permission_checker: PermissionChecker,
    sources_config: SourcesConfig,
    checkpointer=None,
):
    """Build the LangGraph graph with shell tools and file operations."""

    executor = SandboxExecutor(
        workspace_path=workspace_path,
        permission_checker=permission_checker,
        sources_config=sources_config,
    )

    tools = [
        _make_shell_tool(executor),
        _make_file_read_tool(workspace_path),
        _make_file_write_tool(workspace_path),
    ]

    llm = ChatOpenAI(
        model=config.llm_model,
        openai_api_key=config.llm_api_key,
        openai_api_base=config.llm_api_base,
        temperature=0,
    )
    llm_with_tools = llm.bind_tools(tools)

    sys_msg = SystemMessage(
        content=(
            "You are a capable assistant with access to a sandboxed workspace. "
            "You can run shell commands (grep, sed, find, python, pip install, git clone, etc.), "
            "read files, and write files within your workspace. "
            "Use the shell tool for command execution and file tools for reading/writing. "
            "All operations are confined to your workspace directory."
        )
    )

    def assistant(state: SandboxState) -> SandboxState:
        result = llm_with_tools.invoke([sys_msg] + state["messages"])
        state["messages"].append(result)
        if isinstance(result, AIMessage) and not result.tool_calls:
            state["final_answer"] = result.content
        return state

    builder = StateGraph(SandboxState)
    builder.add_node("assistant", assistant)
    builder.add_node("tools", ToolNode(tools))
    builder.add_edge(START, "assistant")
    builder.add_conditional_edges("assistant", tools_condition)
    builder.add_edge("tools", "assistant")

    return builder.compile(checkpointer=checkpointer)
```

**Step 4: Run tests to verify they pass**

Run: `cd .worktrees/agent-examples/a2a/sandbox_agent && uv run pytest tests/test_graph.py -v`
Expected: All 2 tests PASS

**Step 5: Commit**

```bash
cd .worktrees/agent-examples
git add a2a/sandbox_agent/src/sandbox_agent/graph.py a2a/sandbox_agent/tests/test_graph.py
git commit -s -m "feat: add LangGraph graph with shell/file tools"
```

---

## Task 7: Implement A2A agent server with checkpointing

**Files:**
- Create: `.worktrees/agent-examples/a2a/sandbox_agent/src/sandbox_agent/agent.py`
- Reference: `.worktrees/agent-examples/a2a/weather_service/src/weather_service/agent.py`

**Step 1: Implement agent.py**

```python
# src/sandbox_agent/agent.py
import json
import logging
import os
import uvicorn
from pathlib import Path
from textwrap import dedent

from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.apps import A2AStarletteApplication
from a2a.server.events.event_queue import EventQueue
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.tasks import InMemoryTaskStore, TaskUpdater
from a2a.types import AgentCapabilities, AgentCard, AgentSkill, TaskState, TextPart
from a2a.utils import new_agent_text_message, new_task
from langchain_core.messages import HumanMessage
from starlette.routing import Route

from sandbox_agent.configuration import Configuration
from sandbox_agent.graph import build_graph
from sandbox_agent.permissions import PermissionChecker
from sandbox_agent.sources import SourcesConfig
from sandbox_agent.workspace import WorkspaceManager

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

config = Configuration()


def _load_json(filename: str) -> dict:
    """Load a JSON file from the agent's package directory."""
    here = Path(__file__).parent.parent.parent  # up to sandbox_agent root
    path = here / filename
    if path.exists():
        with open(path) as f:
            return json.load(f)
    logger.warning("File not found: %s, using empty config", path)
    return {}


def get_agent_card(host: str, port: int):
    capabilities = AgentCapabilities(streaming=True)
    skill = AgentSkill(
        id="sandbox_assistant",
        name="Sandbox Assistant",
        description="**Sandbox Assistant** - Agent with shell tools, file operations, and per-context isolated workspace.",
        tags=["sandbox", "shell", "workspace"],
        examples=[
            "Search for errors in the log files",
            "Write a Python script that processes data",
            "Clone a git repo and analyze its contents",
            "Install pandas and run a data analysis",
        ],
    )
    return AgentCard(
        name="Sandbox Assistant",
        description=dedent("""\
            Agent with sandboxed shell execution and per-context workspace isolation.
            Can run shell commands (grep, sed, python, pip install, git clone),
            read/write files, and execute scripts within an isolated workspace.
            """),
        url=f"http://{host}:{port}/",
        version="1.0.0",
        default_input_modes=["text"],
        default_output_modes=["text"],
        capabilities=capabilities,
        skills=[skill],
    )


class SandboxAgentExecutor(AgentExecutor):
    def __init__(self):
        self._permission_checker = PermissionChecker(_load_json("settings.json"))
        self._sources_config = SourcesConfig.from_dict(_load_json("sources.json"))
        self._workspace_manager = WorkspaceManager(
            workspace_root=config.workspace_root,
            agent_name="sandbox-agent",
        )

    async def execute(self, context: RequestContext, event_queue: EventQueue):
        task = context.current_task
        if not task:
            task = new_task(context.message)
            await event_queue.enqueue_event(task)
        task_updater = TaskUpdater(event_queue, task.id, task.context_id)

        # Determine context_id and workspace
        context_id = task.context_id or ""
        workspace_path = ""

        if context_id:
            # Ensure workspace exists for this context
            workspace_path = self._workspace_manager.ensure_workspace(context_id)
            logger.info("Using workspace: %s for context: %s", workspace_path, context_id)
        else:
            logger.info("No context_id, running stateless (no workspace)")

        # Build graph with workspace-aware tools
        graph = build_graph(
            workspace_path=workspace_path or "/tmp/sandbox-stateless",
            permission_checker=self._permission_checker,
            sources_config=self._sources_config,
        )

        messages = [HumanMessage(content=context.get_user_input())]
        input_state = {
            "messages": messages,
            "context_id": context_id,
            "workspace_path": workspace_path,
        }

        # Use context_id as thread_id for checkpointing
        graph_config = {}
        if context_id:
            graph_config = {"configurable": {"thread_id": context_id}}

        try:
            output = None
            async for event in graph.astream(input_state, config=graph_config, stream_mode="updates"):
                await task_updater.update_status(
                    TaskState.working,
                    new_agent_text_message(
                        "\n".join(
                            f"{key}: {str(value)[:256]}"
                            for key, value in event.items()
                        ),
                        task_updater.context_id,
                        task_updater.task_id,
                    ),
                )
                output = event

            final_answer = output.get("assistant", {}).get("final_answer", "") if output else ""
            parts = [TextPart(text=str(final_answer))]
            await task_updater.add_artifact(parts)
            await task_updater.complete()

        except Exception as e:
            logger.error("Execution error: %s", e)
            parts = [TextPart(text=f"Error: {e}")]
            await task_updater.add_artifact(parts)
            await task_updater.failed()

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        raise Exception("cancel not supported")


def run():
    agent_card = get_agent_card(host="0.0.0.0", port=8000)

    request_handler = DefaultRequestHandler(
        agent_executor=SandboxAgentExecutor(),
        task_store=InMemoryTaskStore(),
    )

    server = A2AStarletteApplication(
        agent_card=agent_card,
        http_handler=request_handler,
    )

    app = server.build()

    app.routes.insert(0, Route(
        "/.well-known/agent-card.json",
        server._handle_get_agent_card,
        methods=["GET"],
        name="agent_card_new",
    ))

    uvicorn.run(app, host="0.0.0.0", port=8000)
```

**Step 2: Verify the module loads**

Run: `cd .worktrees/agent-examples/a2a/sandbox_agent && uv run python -c "from sandbox_agent.agent import get_agent_card; print(get_agent_card('localhost', 8000).name)"`
Expected: `Sandbox Assistant`

**Step 3: Commit**

```bash
cd .worktrees/agent-examples
git add a2a/sandbox_agent/src/sandbox_agent/agent.py
git commit -s -m "feat: add A2A agent server with workspace integration"
```

---

## Task 8: Create Kubernetes deployment manifests

**Files:**
- Create: `kagenti/examples/agents/sandbox_agent_deployment.yaml`
- Create: `kagenti/examples/agents/sandbox_agent_pvc.yaml`
- Create: `kagenti/examples/agents/sandbox_agent_service.yaml`
- Reference: `kagenti/examples/agents/weather_service_deployment.yaml`

**Step 1: Create the RWX PVC manifest**

```yaml
# kagenti/examples/agents/sandbox_agent_pvc.yaml
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: sandbox-agent-workspace
  namespace: team1
  labels:
    kagenti.io/type: agent-workspace
    kagenti.io/agent: sandbox-agent
spec:
  accessModes:
    - ReadWriteMany
  # Set storageClassName per environment:
  #   Kind: nfs
  #   OpenShift: ocs-storagecluster-cephfs
  #   AWS: efs-sc
  storageClassName: nfs
  resources:
    requests:
      storage: 5Gi
```

**Step 2: Create the Deployment manifest**

```yaml
# kagenti/examples/agents/sandbox_agent_deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: sandbox-agent
  namespace: team1
  labels:
    kagenti.io/type: agent
    kagenti.io/protocol: a2a
    kagenti.io/framework: LangGraph
    kagenti.io/workload-type: deployment
    app.kubernetes.io/name: sandbox-agent
    app.kubernetes.io/managed-by: kagenti-e2e
    app.kubernetes.io/component: agent
  annotations:
    kagenti.io/description: "Sandbox agent with per-context workspace isolation"
spec:
  replicas: 1
  selector:
    matchLabels:
      kagenti.io/type: agent
      app.kubernetes.io/name: sandbox-agent
  template:
    metadata:
      labels:
        kagenti.io/type: agent
        kagenti.io/protocol: a2a
        kagenti.io/framework: LangGraph
        app.kubernetes.io/name: sandbox-agent
    spec:
      containers:
      - name: agent
        image: registry.cr-system.svc.cluster.local:5000/sandbox-agent:v0.0.1
        imagePullPolicy: Always
        env:
        - name: PORT
          value: "8000"
        - name: HOST
          value: "0.0.0.0"
        - name: WORKSPACE_ROOT
          value: "/workspace"
        - name: OTEL_EXPORTER_OTLP_ENDPOINT
          value: "http://otel-collector.kagenti-system.svc.cluster.local:8335"
        - name: LLM_API_BASE
          value: "http://dockerhost:11434/v1"
        - name: LLM_API_KEY
          value: "dummy"
        - name: LLM_MODEL
          value: "qwen2.5:3b"
        ports:
        - containerPort: 8000
          name: http
          protocol: TCP
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
        - name: cache
          mountPath: /app/.cache
      volumes:
      - name: workspace
        persistentVolumeClaim:
          claimName: sandbox-agent-workspace
      - name: cache
        emptyDir: {}
```

**Step 3: Create the Service manifest**

```yaml
# kagenti/examples/agents/sandbox_agent_service.yaml
apiVersion: v1
kind: Service
metadata:
  name: sandbox-agent
  namespace: team1
  labels:
    kagenti.io/type: agent
    app.kubernetes.io/name: sandbox-agent
spec:
  selector:
    kagenti.io/type: agent
    app.kubernetes.io/name: sandbox-agent
  ports:
  - port: 8000
    targetPort: 8000
    protocol: TCP
    name: http
```

**Step 4: Commit**

```bash
git add kagenti/examples/agents/sandbox_agent_deployment.yaml kagenti/examples/agents/sandbox_agent_pvc.yaml kagenti/examples/agents/sandbox_agent_service.yaml
git commit -s -m "feat: add sandbox agent Kubernetes manifests with RWX PVC"
```

---

## Task 9: Generate uv.lock and verify builds

**Step 1: Generate lock file**

Run:
```bash
cd .worktrees/agent-examples/a2a/sandbox_agent
uv lock
```

**Step 2: Run all tests**

Run:
```bash
cd .worktrees/agent-examples/a2a/sandbox_agent
uv sync
uv run pytest tests/ -v
```
Expected: All tests pass (permissions, sources, workspace, executor, graph)

**Step 3: Verify Docker build**

Run:
```bash
cd .worktrees/agent-examples/a2a/sandbox_agent
docker build -t sandbox-agent:test .
```
Expected: Build succeeds

**Step 4: Commit lock file**

```bash
cd .worktrees/agent-examples
git add a2a/sandbox_agent/uv.lock
git commit -s -m "chore: add uv.lock for sandbox_agent"
```

---

## Task 10: Add NFS provisioner to Kind setup (for RWX PVC support)

**Files:**
- Modify: `.github/scripts/local-setup/kind-full-test.sh` (or create a helper script)

This task adds the nfs-ganesha-server-and-external-provisioner to the Kind cluster setup so RWX PVCs work locally.

**Step 1: Research current Kind setup script**

Read `.github/scripts/local-setup/kind-full-test.sh` to find where to add the NFS provisioner Helm install.

**Step 2: Add NFS provisioner install**

Add after the Kind cluster is created and Helm repos are configured:

```bash
# Install NFS provisioner for RWX PVC support
echo "Installing NFS provisioner for RWX PVC support..."
helm repo add nfs-ganesha https://kubernetes-sigs.github.io/nfs-ganesha-server-and-external-provisioner/
helm install nfs-server-provisioner nfs-ganesha/nfs-server-provisioner \
  --set persistence.enabled=true \
  --set persistence.storageClass=standard \
  --set persistence.size=10Gi \
  --wait --timeout 120s
```

**Step 3: Verify NFS StorageClass exists**

Run:
```bash
kubectl get storageclass nfs
```
Expected: StorageClass `nfs` is available

**Step 4: Commit**

```bash
git add .github/scripts/local-setup/
git commit -s -m "feat: add NFS provisioner to Kind setup for RWX PVC support"
```

---

## Summary: Dependency Order

```
Task 1 (scaffold) ─────────────────────────────────┐
Task 2 (permissions) ──────────────────────────┐    │
Task 3 (sources) ──────────────────────────┐   │    │
Task 4 (workspace) ────────────────────┐   │   │    │
                                       ▼   ▼   ▼    │
Task 5 (executor) ─── depends on 2,3 ─┤            │
                                       │            │
Task 6 (graph) ─── depends on 5 ──────┤            │
                                       │            │
Task 7 (agent server) ── depends on 4,6 ──────────┤
                                                    │
Task 8 (k8s manifests) ─── depends on 7 ───────────┤
                                                    │
Task 9 (lock + verify) ─── depends on all ──────────┘
                                                    │
Task 10 (NFS provisioner) ─── independent ──────────┘
```

Tasks 1-4 can be parallelized. Tasks 5-7 are sequential. Tasks 8-10 can run after 7.
