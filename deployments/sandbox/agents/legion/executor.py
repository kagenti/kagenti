"""Sandbox executor -- runs shell commands inside a context workspace.

Every command is checked against the :class:`PermissionChecker` before
execution.  The three possible outcomes are:

  DENY  -- an error :class:`ExecutionResult` is returned immediately
  HITL  -- :class:`HitlRequired` is raised so the LangGraph graph can
           trigger an ``interrupt()`` for human approval
  ALLOW -- the command is executed via ``asyncio.create_subprocess_shell``
           inside *workspace_path* with a timeout from :class:`SourcesConfig`
"""

from __future__ import annotations

import asyncio
import logging
import shlex
from dataclasses import dataclass

from platform_base.permissions import PermissionChecker, PermissionResult
from platform_base.sources import SourcesConfig

logger = logging.getLogger(__name__)

# Shell interpreters that can execute arbitrary code via -c / -e flags.
_INTERPRETERS = frozenset({"bash", "sh", "python", "python3", "perl", "ruby", "node"})

# Flags that take an inline command string as the next argument.
_EXEC_FLAGS = frozenset({"-c", "-e", "--eval"})


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class HitlRequired(Exception):
    """Raised when an operation needs human approval.

    Attributes
    ----------
    command:
        The shell command that requires approval.
    """

    def __init__(self, command: str) -> None:
        self.command = command
        super().__init__(f"Human approval required for command: {command}")


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------


@dataclass
class ExecutionResult:
    """Captures the outcome of a shell command execution."""

    stdout: str
    stderr: str
    exit_code: int


# ---------------------------------------------------------------------------
# Executor
# ---------------------------------------------------------------------------


class SandboxExecutor:
    """Runs shell commands in a workspace directory with permission checks.

    Parameters
    ----------
    workspace_path:
        Absolute path to the workspace directory where commands execute.
    permission_checker:
        A :class:`PermissionChecker` instance for evaluating operations.
    sources_config:
        A :class:`SourcesConfig` instance providing runtime limits.
    """

    def __init__(
        self,
        workspace_path: str,
        permission_checker: PermissionChecker,
        sources_config: SourcesConfig,
    ) -> None:
        self._workspace_path = workspace_path
        self._permission_checker = permission_checker
        self._sources_config = sources_config

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def run_shell(self, command: str) -> ExecutionResult:
        """Run a shell command after checking permissions and sources.json.

        Parameters
        ----------
        command:
            The shell command string to execute.

        Returns
        -------
        ExecutionResult
            On success (ALLOW) or on DENY (with a non-zero exit code and
            an error message in stderr).

        Raises
        ------
        HitlRequired
            When the command matches neither allow nor deny rules and
            requires human approval.
        """
        # 1. Extract the command prefix for permission matching.
        #    Try "cmd subcmd" first (e.g. "pip install"), then fall back
        #    to just "cmd" (e.g. "grep").
        operation = command.strip()

        # 1a. Check for interpreter bypass (e.g. bash -c "curl evil.com").
        #     If the outer command is an interpreter with -c/-e, recursively
        #     check the inner command against the same permission + sources
        #     pipeline.  This prevents circumventing deny rules by wrapping
        #     a blocked command in `bash -c "..."`.
        bypass_denial = self._check_interpreter_bypass(operation)
        if bypass_denial is not None:
            return ExecutionResult(
                stdout="",
                stderr=bypass_denial,
                exit_code=1,
            )

        permission = self._check_permission(operation)

        # 2. Act on the permission result.
        if permission is PermissionResult.DENY:
            return ExecutionResult(
                stdout="",
                stderr=f"Permission denied: command '{command}' is denied by policy.",
                exit_code=1,
            )

        if permission is PermissionResult.HITL:
            raise HitlRequired(command)

        # 3. Check sources.json enforcement (package blocking, git remote
        #    allowlist) as a second layer of defense-in-depth.
        sources_denial = self._check_sources(operation)
        if sources_denial:
            return ExecutionResult(
                stdout="",
                stderr=sources_denial,
                exit_code=1,
            )

        # 4. ALLOW -- execute the command.
        return await self._execute(command)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _check_interpreter_bypass(self, command: str) -> str | None:
        """Check if a command uses an interpreter to bypass restrictions.

        Detects patterns like ``bash -c "curl evil.com"`` or
        ``python3 -c "import os; os.system('rm -rf /')"`` and recursively
        checks the inner command against permissions and sources policy.

        Returns
        -------
        str or None
            An error message if the inner command is denied, or *None* if
            no interpreter bypass was detected (or the inner command is OK).
        """
        try:
            parts = shlex.split(command)
        except ValueError:
            return None

        if len(parts) < 3:
            return None

        # Resolve the binary name (handle /usr/bin/bash -> bash).
        cmd = parts[0].rsplit("/", 1)[-1]
        if cmd not in _INTERPRETERS:
            return None

        if parts[1] not in _EXEC_FLAGS:
            return None

        # Everything after the exec flag is the inner command.
        inner_command = " ".join(parts[2:])
        logger.warning(
            "Interpreter bypass detected: '%s' wraps inner command '%s'",
            command,
            inner_command,
        )

        # Recursively check the inner command against permission rules.
        inner_permission = self._check_permission(inner_command)
        if inner_permission is PermissionResult.DENY:
            return (
                f"Permission denied: interpreter bypass detected. "
                f"Inner command '{inner_command}' is denied by policy."
            )

        # Also check the inner command against sources.json policy
        # (e.g. git clone to a disallowed remote inside bash -c).
        inner_sources_denial = self._check_sources(inner_command)
        if inner_sources_denial:
            return (
                f"Blocked: interpreter bypass detected. "
                f"Inner command violates sources policy: {inner_sources_denial}"
            )

        return None

    def _check_permission(self, operation: str) -> PermissionResult:
        """Check the permission for a shell operation.

        The permission checker expects the full command string as the
        operation.  It internally handles prefix matching (e.g. matching
        "grep -r foo" against the rule ``shell(grep:*)``).
        """
        return self._permission_checker.check("shell", operation)

    def _check_sources(self, operation: str) -> str | None:
        """Check sources.json enforcement for package and git operations.

        Returns an error message string if the operation is blocked by
        sources.json, or None if it is allowed.
        """
        import re

        parts = operation.split()
        if not parts:
            return None

        # --- Package manager checks ---
        # pip install <package>
        if len(parts) >= 3 and parts[0] == "pip" and parts[1] == "install":
            if not self._sources_config.is_package_manager_enabled("pip"):
                return "Blocked by sources.json: pip is not enabled."
            for pkg in parts[2:]:
                if pkg.startswith("-"):
                    continue  # skip flags
                # Strip version specifiers (e.g. "requests>=2.0")
                pkg_name = re.split(r"[><=!~]", pkg)[0]
                if pkg_name and self._sources_config.is_package_blocked(
                    "pip", pkg_name
                ):
                    return f"Blocked by sources.json: package '{pkg_name}' is on the blocked list."

        # npm install <package>
        if len(parts) >= 3 and parts[0] == "npm" and parts[1] == "install":
            if not self._sources_config.is_package_manager_enabled("npm"):
                return "Blocked by sources.json: npm is not enabled."
            for pkg in parts[2:]:
                if pkg.startswith("-"):
                    continue
                pkg_name = re.split(r"[@><=!~]", pkg)[0]
                if pkg_name and self._sources_config.is_package_blocked(
                    "npm", pkg_name
                ):
                    return f"Blocked by sources.json: package '{pkg_name}' is on the blocked list."

        # --- Git remote checks ---
        # git clone <url>
        if len(parts) >= 3 and parts[0] == "git" and parts[1] == "clone":
            # Find the URL argument (skip flags like --depth, --branch)
            url = None
            i = 2
            while i < len(parts):
                if parts[i].startswith("-"):
                    # Skip flag and its value if it takes one
                    if parts[i] in ("--depth", "--branch", "-b"):
                        i += 2
                        continue
                    i += 1
                    continue
                url = parts[i]
                break
            if url and not self._sources_config.is_git_remote_allowed(url):
                return f"Blocked by sources.json: git remote '{url}' is not in allowed_remotes."

        return None

    async def _execute(self, command: str) -> ExecutionResult:
        """Execute *command* in the workspace directory with a timeout."""
        timeout = self._sources_config.max_execution_time_seconds

        try:
            process = await asyncio.create_subprocess_shell(
                command,
                cwd=self._workspace_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            try:
                stdout_bytes, stderr_bytes = await asyncio.wait_for(
                    process.communicate(),
                    timeout=timeout,
                )
            except asyncio.TimeoutError:
                # Kill the process and its children.
                try:
                    process.kill()
                except ProcessLookupError:
                    pass  # already exited
                # Wait for the process to be reaped.
                await process.wait()
                return ExecutionResult(
                    stdout="",
                    stderr=(
                        f"Command timed out after {timeout} seconds "
                        f"and was killed: '{command}'"
                    ),
                    exit_code=-1,
                )

            return ExecutionResult(
                stdout=(stdout_bytes or b"").decode("utf-8", errors="replace"),
                stderr=(stderr_bytes or b"").decode("utf-8", errors="replace"),
                exit_code=process.returncode if process.returncode is not None else -1,
            )

        except OSError as exc:
            return ExecutionResult(
                stdout="",
                stderr=f"Failed to start command: {exc}",
                exit_code=-1,
            )
