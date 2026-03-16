# Session Beta-3 — Per-Session Filesystem Isolation

> **Date:** 2026-03-16
> **Cluster:** kagenti-team-sandbox42
> **Branch:** `feat/sandbox-agent`
> **Previous:** session-beta-handoff.md, session-gamma-plan.md

## Problem Statement

The sandbox agent can run in two modes:

1. **Pod-per-session** (agent-sandbox SandboxClaim) — each session = separate pod.
   Isolation is handled by Kubernetes (separate PID/mount namespace).

2. **Multi-session pod** (A2A server, e.g. sandbox-legion) — one pod serves
   many sessions concurrently. All sessions share the same UID, process, and
   filesystem view.

In mode 2, **session A can read session B's files**. The current isolation is
application-level only (path validation in Python), which is bypassable via:
- Shell commands with absolute paths (`cat /workspace/other-session/secret.txt`)
- Symlink attacks (`ln -s /workspace/other-session/ /workspace/my-session/link`)
- LLM prompt injection causing the agent to operate outside its workspace

## Current Isolation Audit

### What Exists (4 layers)

| Layer | Mechanism | Scope | Enforced By | Bypassable? |
|-------|-----------|-------|-------------|-------------|
| 1. SecurityContext | Drop caps, non-root, read-only root | Pod | Kernel | No |
| 2. Landlock (nono-launcher) | Restrict to `/workspace/` + system paths | Pod (startup) | Kernel | No, but too broad |
| 3. PermissionChecker | Allow/deny rules before shell exec | Request | Application | Yes (bypass in shell) |
| 4. Path validation | `is_relative_to()` in file tools | Tool call | Application | Yes (symlinks, shell) |

### Key Gaps

| Gap | Risk | Location |
|-----|------|----------|
| **Shell subprocess has no Landlock** | Shell can `cd /workspace/other-session/` | `executor.py:292` |
| **Landlock allows ALL of `/workspace/`** | Session A can access `/workspace/B/` | `nono-launcher.py:56` |
| **No per-session Landlock** | Can't restrict subprocess to `/workspace/{session_id}/` | Missing |
| **Symlinks followed in file tools** | `ln -s /etc/passwd /workspace/A/link` → reads /etc/passwd | `graph.py:353` |
| **glob tool has no `is_relative_to()`** | Could return files outside workspace | `graph.py:465` |
| **Shell CWD is advisory** | `cd / && cat /etc/passwd` works despite CWD | `executor.py:294` |

## Design: Per-Tool-Call Subprocess Landlock

### Key Decision: Per-Tool-Call Fork (not Per-Session Worker)

Landlock is **irreversible** — once applied, rules can never be loosened.
Two options were evaluated:

| | Per-Session Worker | Per-Tool-Call Fork |
|---|---|---|
| Fork count | 1 per session | 1 per tool call |
| Landlock apply | Once | Every call |
| Tool call latency | ~0ms (IPC) | ~7ms (fork + Landlock) |
| Memory | 10MB per session (resident) | 0 (exits after call) |
| Complexity | High (IPC, process lifecycle) | Low (fork, run, exit) |
| Failure isolation | Worker crash kills remaining calls | Each call independent |

**Decision: Per-tool-call fork** — simpler, no IPC, each call independent.
The 7ms overhead is negligible vs 2-10s LLM calls. For 30 tool calls per
session = 210ms total overhead.

### Dependency Decision: `landlock` Python Package (Option A)

Evaluated two options:
- **Option A:** `landlock` package (8KB, pure Python, wraps syscalls)
- **Option B:** Raw `ctypes` syscalls (zero deps, ~60 lines)

**Decision: Option A** — the ABI version handling alone justifies using the
package. Landlock v1/v2/v3/v4 each add flags; getting struct packing wrong
in ctypes is a silent security vulnerability. The package is pure Python
with no C extensions. Add to `pyproject.toml` (baked into image).

If the package is ever abandoned, vendor the ~200 lines into our source.

### Architecture

```
┌─ Pod (A2A Server, UID 1000) ───────────────────────────────┐
│                                                             │
│  Main Process (asyncio event loop)                          │
│    │                                                        │
│    ├─ Session A (coroutine)                                 │
│    │   ├─ LLM calls → in-process (safe, text only)         │
│    │   ├─ file_read → in-process with path validation       │
│    │   └─ shell_tool → fork per call ────┐                  │
│    │                                      │                 │
│    │        ┌─ Child Process (ephemeral) ─┤                 │
│    │        │ 1. Apply Landlock:          │                 │
│    │        │    /workspace/A/ → RW       │                 │
│    │        │    /tmp/A/ → RW             │                 │
│    │        │    system paths → RO        │                 │
│    │        │ 2. exec bash -c "command"   │                 │
│    │        │ 3. CANNOT access /workspace/B/                │
│    │        │ 4. Process exits after call │                 │
│    │        └─────────────────────────────┘                 │
│    │                                                        │
│    ├─ Session B (coroutine)                                 │
│    │   └─ shell_tool → fork per call ────┐                  │
│    │        ┌─ Child Process (ephemeral) ─┤                 │
│    │        │ Landlock: /workspace/B/ only │                │
│    │        │ Process exits after call     │                │
│    │        └─────────────────────────────┘                 │
│    │                                                        │
│  /workspace/A/   /workspace/B/   /workspace/C/             │
└─────────────────────────────────────────────────────────────┘
```

### Implementation Plan

#### Step 1: Sandboxed Subprocess Wrapper

New file: `sandbox_agent/sandbox_subprocess.py`

```python
"""
Subprocess execution with per-session Landlock isolation.

Applies IRREVERSIBLE Landlock rules in the child process before
executing the command. The child can ONLY access the session's
workspace directory.
"""

import asyncio
import json
import os
import sys
from pathlib import Path


# Landlock application script (runs in child process before exec)
_LANDLOCK_PREEXEC_SCRIPT = '''
import os, sys
try:
    import landlock
    rs = landlock.Ruleset()
    # Session workspace — read-write
    rs.allow(os.environ["SANDBOX_WORKSPACE"], landlock.AccessFS.READ_WRITE)
    # Temp — read-write (isolated per session)
    tmp = os.environ.get("SANDBOX_TMP", "/tmp")
    if os.path.exists(tmp):
        rs.allow(tmp, landlock.AccessFS.READ_WRITE)
    # System paths — read-only (for bash, python, git, etc.)
    for p in ["/usr", "/bin", "/lib", "/lib64", "/opt", "/etc",
              "/proc", "/dev/null", "/dev/urandom"]:
        if os.path.exists(p):
            rs.allow(p, landlock.AccessFS.READ)
    # Python/uv paths
    for p in ["/app", sys.prefix]:
        if os.path.exists(p):
            rs.allow(p, landlock.AccessFS.READ)
    rs.apply()  # IRREVERSIBLE
except ImportError:
    pass  # landlock (Python package) not installed — no Landlock (degraded mode)
'''


async def sandboxed_subprocess(
    command: str,
    workspace_path: str,
    timeout: float = 120.0,
    env: dict[str, str] | None = None,
) -> tuple[int, str, str]:
    """Execute command in a Landlock-isolated subprocess.

    The child process applies Landlock rules restricting filesystem
    access to workspace_path before executing the command.

    Returns (returncode, stdout, stderr).
    """
    child_env = {**os.environ, **(env or {})}
    child_env["SANDBOX_WORKSPACE"] = str(Path(workspace_path).resolve())
    child_env["SANDBOX_TMP"] = f"/tmp/{Path(workspace_path).name}"

    # Create session-specific tmp dir
    os.makedirs(child_env["SANDBOX_TMP"], exist_ok=True)

    proc = await asyncio.create_subprocess_exec(
        sys.executable, "-c",
        _LANDLOCK_PREEXEC_SCRIPT + f"\nimport subprocess, sys\n"
        f"r = subprocess.run({command!r}, shell=True, "
        f"cwd={str(workspace_path)!r}, capture_output=True, text=True, "
        f"timeout={timeout})\n"
        f"sys.stdout.write(r.stdout)\n"
        f"sys.stderr.write(r.stderr)\n"
        f"sys.exit(r.returncode)",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=child_env,
    )

    try:
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(), timeout=timeout + 5
        )
        return proc.returncode or 0, stdout.decode(), stderr.decode()
    except asyncio.TimeoutError:
        proc.kill()
        return 124, "", "Execution timed out"
```

#### Step 2: Wire into SandboxExecutor

Update `executor.py` to use `sandboxed_subprocess` instead of raw
`asyncio.create_subprocess_shell`:

```python
# executor.py — _execute method
async def _execute(self, command: str) -> ExecutionResult:
    if self._use_landlock:  # New flag from env var
        returncode, stdout, stderr = await sandboxed_subprocess(
            command,
            workspace_path=self._workspace_path,
            timeout=self._sources_config.max_execution_time_seconds,
        )
    else:
        # Legacy: direct subprocess (for Kind/local without Landlock)
        process = await asyncio.create_subprocess_shell(
            command,
            cwd=self._workspace_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout_bytes, stderr_bytes = await asyncio.wait_for(
            process.communicate(),
            timeout=self._sources_config.max_execution_time_seconds,
        )
        returncode = process.returncode or 0
        stdout = stdout_bytes.decode()
        stderr = stderr_bytes.decode()

    return ExecutionResult(
        returncode=returncode,
        stdout=stdout[:self.MAX_OUTPUT_SIZE],
        stderr=stderr[:self.MAX_OUTPUT_SIZE],
    )
```

Enable via env var:
```
SANDBOX_LANDLOCK_SUBPROCESS=1  # Enable per-session Landlock
```

#### Step 3: Fix Symlink Vulnerability in File Tools

Update `graph.py` file tools to block symlinks that escape the workspace:

```python
# In _make_file_read_tool:
resolved = (ws_root / path).resolve()

# Block symlinks that escape workspace
if not resolved.is_relative_to(ws_root):
    return f"Error: path '{path}' resolves outside the workspace."

# Additional: check for symlinks in the path components
raw_path = ws_root / path
for parent in raw_path.parents:
    if parent.is_symlink() and not parent.resolve().is_relative_to(ws_root):
        return f"Error: symlink in path escapes workspace."
```

#### Step 4: Fix glob Tool Missing Path Check

Add `is_relative_to()` check to glob tool results:

```python
# In _make_glob_tool:
matches = []
for p in ws_root.rglob("*"):
    if not p.resolve().is_relative_to(ws_root):
        continue  # Skip files that resolve outside workspace
    if fnmatch.fnmatch(p.name, pattern):
        matches.append(str(p.relative_to(ws_root)))
```

#### Step 5: Per-Session /tmp Isolation

The shell subprocess should use a session-specific tmp directory:

```python
# In sandboxed_subprocess:
session_tmp = f"/tmp/{session_id}"
os.makedirs(session_tmp, exist_ok=True)
child_env["TMPDIR"] = session_tmp
child_env["SANDBOX_TMP"] = session_tmp
# Landlock only allows this session's /tmp/{session_id}
```

### What About File Tools (In-Process)?

File tools (file_read, file_write, grep, glob) run **in the main process**,
not in subprocesses. For these:

- **Current:** Application-level path validation (is_relative_to)
- **Enhanced:** Add symlink protection (Step 3)
- **Optional:** Also run in sandboxed subprocess for maximum isolation

Running file tools in subprocess adds ~5ms per call. For file_read/write this
is acceptable. For grep/glob on large workspaces, the overhead is minimal
compared to I/O time.

Decision: **Start with shell only**, extend to file tools if needed.

### What About PVC vs emptyDir?

This design works with BOTH:

| Storage | Isolation | Notes |
|---------|-----------|-------|
| **emptyDir** | Per-pod (sessions share pod) | Landlock subprocess isolates per-session within pod |
| **PVC** | Same as emptyDir when shared pod | Same Landlock isolation |
| **Per-session PVC** | Per-session (different mount) | Landlock not needed (already isolated) |

### Performance Impact

| Operation | Current | With Landlock Subprocess |
|-----------|---------|------------------------|
| Shell command | ~2ms (subprocess_shell) | ~7-12ms (fork + Landlock + exec) |
| file_read | ~0.1ms (in-process) | ~0.1ms (unchanged) |
| LLM call | ~2-10s | ~2-10s (unchanged) |

The 5-10ms overhead per shell call is negligible compared to LLM inference time.

## Testing Plan

### Unit Tests

```python
# test_sandbox_subprocess.py

class TestSandboxedSubprocess:
    async def test_can_read_own_workspace(self):
        """Subprocess can read files in its workspace."""
        ws = "/tmp/test-ws-a"
        os.makedirs(ws, exist_ok=True)
        Path(ws, "test.txt").write_text("hello")
        rc, out, _ = await sandboxed_subprocess("cat test.txt", ws)
        assert rc == 0
        assert "hello" in out

    async def test_cannot_read_other_workspace(self):
        """Subprocess CANNOT read another session's workspace."""
        ws_a = "/tmp/test-ws-a"
        ws_b = "/tmp/test-ws-b"
        os.makedirs(ws_a, exist_ok=True)
        os.makedirs(ws_b, exist_ok=True)
        Path(ws_b, "secret.txt").write_text("secret-data")

        rc, out, err = await sandboxed_subprocess(
            f"cat {ws_b}/secret.txt", ws_a
        )
        assert rc != 0 or "secret-data" not in out

    async def test_cannot_read_etc_passwd(self):
        """Subprocess CANNOT read system files."""
        ws = "/tmp/test-ws-c"
        os.makedirs(ws, exist_ok=True)
        rc, out, err = await sandboxed_subprocess("cat /etc/passwd", ws)
        # Landlock blocks read — returns permission denied
        assert rc != 0 or "root:" not in out

    async def test_symlink_blocked(self):
        """Symlink to outside workspace is blocked."""
        ws = "/tmp/test-ws-d"
        os.makedirs(ws, exist_ok=True)
        os.symlink("/etc/passwd", f"{ws}/link")
        rc, out, _ = await sandboxed_subprocess("cat link", ws)
        assert "root:" not in out
```

### E2E Tests

Add to `test_sandbox_variants.py`:

```python
class TestWorkspaceIsolation:
    def test_cannot_access_other_session(self):
        """Session A cannot read session B's files via shell."""
        # Create session A, write a file
        session_a = create_session("sandbox-legion")
        send_message(session_a, "Write 'secret-A' to /workspace/{id}/secret.txt")

        # Create session B, try to read session A's file
        session_b = create_session("sandbox-legion")
        response = send_message(session_b,
            f"Read the file at /workspace/{session_a.id}/secret.txt")

        # Session B should NOT see session A's data
        assert "secret-A" not in response.content

    def test_symlink_escape_blocked(self):
        """Agent cannot create symlink to escape workspace."""
        session = create_session("sandbox-legion")
        response = send_message(session,
            "Create symlink: ln -s /etc/passwd /workspace/{id}/link && cat link")
        assert "root:" not in response.content
```

## Files to Change

```
Agent (agent-examples):
  NEW  src/sandbox_agent/sandbox_subprocess.py   # Landlock subprocess wrapper
  EDIT src/sandbox_agent/executor.py             # Use sandboxed_subprocess
  EDIT src/sandbox_agent/graph.py                # Fix symlink + glob path checks
  NEW  tests/test_sandbox_subprocess.py          # Unit tests

Deployment (kagenti):
  EDIT deployments/sandbox/nono-launcher.py      # Tighten to /workspace/{session}
  EDIT deployments/sandbox/sandbox-template.yaml # Add SANDBOX_LANDLOCK_SUBPROCESS=1

Tests (kagenti):
  EDIT kagenti/tests/e2e/common/test_sandbox_variants.py  # Cross-session isolation test
```

## Dependency

`landlock (Python package)` package must be installed in the sandbox agent image.
Currently installed at runtime via `pip install` in the container command.
For subprocess isolation, it must be available to child processes too.

**Recommendation:** Bake `landlock (Python package)` into the Dockerfile instead of runtime pip install:
```dockerfile
RUN pip install landlock (Python package)
```

## Open Questions

1. **Degraded mode:** If `landlock (Python package)` is not installed (e.g., Kind without Landlock
   kernel support), should we fall back to CWD-only confinement? Or fail hard?

2. **File tools in subprocess:** Should file_read/file_write also use sandboxed
   subprocess? Adds ~5ms per call but provides kernel-level path enforcement.

3. **Per-session /tmp:** Should we use separate /tmp per session (prevents
   temp file attacks) or a shared /tmp? Landlock can restrict to /tmp/{session_id}.

4. **landlock (Python package) in image:** Bake into Dockerfile vs runtime install? Dockerfile is
   cleaner but requires image rebuild for landlock (Python package) updates.
