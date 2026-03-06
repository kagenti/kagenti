"""OpenCode agent plugin — implements the platform_base plugin contract.

Wraps OpenCode's `opencode serve` headless HTTP server as an A2A agent.
OpenCode is started as a subprocess on port 4096 (default). A2A requests
are proxied to its HTTP API, and responses are returned as A2A events.

API: POST /session to create, POST /session/:id/message to send prompts.

This module is loaded by the platform entrypoint via AGENT_MODULE=opencode.plugin.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import subprocess
from pathlib import Path
from textwrap import dedent
from typing import TYPE_CHECKING

import httpx
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events.event_queue import EventQueue
from a2a.server.tasks import TaskUpdater
from a2a.types import (
    AgentCapabilities,
    AgentCard,
    AgentSkill,
    TaskState,
    TextPart,
)
from a2a.utils import new_agent_text_message, new_task

if TYPE_CHECKING:
    from platform_base.permissions import PermissionChecker
    from platform_base.sources import SourcesConfig
    from platform_base.workspace import WorkspaceManager

logger = logging.getLogger(__name__)

OPENCODE_PORT = int(os.environ.get("OPENCODE_PORT", "4096"))
OPENCODE_URL = f"http://localhost:{OPENCODE_PORT}"


# ---------------------------------------------------------------------------
# Plugin contract: get_agent_card
# ---------------------------------------------------------------------------


def get_agent_card(host: str, port: int) -> AgentCard:
    """Return an A2A AgentCard for the OpenCode agent."""
    capabilities = AgentCapabilities(streaming=True)
    skill = AgentSkill(
        id="opencode_coding",
        name="OpenCode Coding",
        description=(
            "**OpenCode** -- Full-featured coding agent with 75+ LLM support. "
            "Executes shell commands, edits files, and manages projects."
        ),
        tags=["shell", "file", "coding", "opencode"],
        examples=[
            "Create a Python FastAPI server with health endpoint",
            "Fix the bug in src/main.py line 42",
            "Refactor the authentication module to use JWT",
        ],
    )
    return AgentCard(
        name="OpenCode Agent",
        description=dedent(
            """\
            OpenCode wrapped as an A2A service. Supports 75+ LLM providers \
            including ChatGPT, Copilot, and local models.

            ## Key Features
            - **Full coding agent** with shell, file, and project management
            - **75+ LLM providers** via Models.dev
            - **MCP native** with OAuth 2.0 tool integration
            """,
        ),
        url=f"http://{host}:{port}/",
        version="1.0.0",
        default_input_modes=["text"],
        default_output_modes=["text"],
        capabilities=capabilities,
        skills=[skill],
    )


# ---------------------------------------------------------------------------
# Plugin contract: build_executor
# ---------------------------------------------------------------------------


def build_executor(
    workspace_manager: WorkspaceManager,
    permission_checker: PermissionChecker,
    sources_config: SourcesConfig,
    **kwargs,
) -> AgentExecutor:
    """Build and return an OpenCodeExecutor wired to platform services."""
    return OpenCodeExecutor(
        workspace_manager=workspace_manager,
        permission_checker=permission_checker,
        sources_config=sources_config,
    )


# ---------------------------------------------------------------------------
# OpenCode subprocess management
# ---------------------------------------------------------------------------


class OpenCodeProcess:
    """Manages the opencode serve subprocess lifecycle."""

    def __init__(self, port: int = OPENCODE_PORT, workspace: str = "/workspace"):
        self.port = port
        self.workspace = workspace
        self._process: subprocess.Popen | None = None
        self._started = False

    async def ensure_running(self) -> None:
        """Start opencode serve if not already running."""
        if self._started:
            return

        logger.info("Starting opencode serve on port %d", self.port)
        self._process = subprocess.Popen(
            ["oh-my-opencode", "serve", "--port", str(self.port)],
            cwd=self.workspace,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        # Wait for health check
        async with httpx.AsyncClient() as client:
            for attempt in range(30):
                try:
                    resp = await client.get(f"http://localhost:{self.port}/health")
                    if resp.status_code == 200:
                        logger.info(
                            "opencode serve ready after %d attempts", attempt + 1
                        )
                        self._started = True
                        return
                except httpx.ConnectError:
                    pass
                await asyncio.sleep(1)

        raise RuntimeError(
            f"opencode serve failed to start within 30s on port {self.port}"
        )

    def stop(self) -> None:
        if self._process:
            self._process.terminate()
            self._process.wait(timeout=5)
            self._started = False


# ---------------------------------------------------------------------------
# Agent Executor
# ---------------------------------------------------------------------------


class OpenCodeExecutor(AgentExecutor):
    """A2A executor that proxies requests to OpenCode's HTTP API."""

    def __init__(
        self,
        workspace_manager: WorkspaceManager,
        permission_checker: PermissionChecker,
        sources_config: SourcesConfig,
    ) -> None:
        self._workspace_manager = workspace_manager
        self._permission_checker = permission_checker
        self._sources_config = sources_config
        self._opencode = OpenCodeProcess()
        self._client = httpx.AsyncClient(timeout=300)

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        """Execute a user request by proxying to OpenCode."""
        task = context.current_task
        if not task:
            task = new_task(context.message)  # type: ignore
            await event_queue.enqueue_event(task)

        task_updater = TaskUpdater(event_queue, task.id, task.context_id)

        # Resolve workspace
        context_id = task.context_id
        if context_id:
            workspace_path = self._workspace_manager.ensure_workspace(context_id)
        else:
            workspace_path = "/tmp/opencode-stateless"
            Path(workspace_path).mkdir(parents=True, exist_ok=True)

        try:
            # Ensure opencode serve is running
            self._opencode.workspace = workspace_path
            await self._opencode.ensure_running()

            # Send prompt to OpenCode via its REST API
            user_input = context.get_user_input()
            await task_updater.update_status(
                TaskState.working,
                new_agent_text_message(
                    json.dumps(
                        {
                            "type": "llm_response",
                            "content": "Processing with OpenCode...",
                        }
                    ),
                    task_updater.context_id,
                    task_updater.task_id,
                ),
            )

            # Create a session (or reuse context_id as session)
            session_id = context_id or "default"

            # POST /session/:id/message — send prompt and wait for response
            resp = await self._client.post(
                f"{OPENCODE_URL}/session/{session_id}/message",
                json={"content": user_input},
                timeout=300,
            )

            # Fall back to POST /session for older API versions
            if resp.status_code == 404:
                resp = await self._client.post(
                    f"{OPENCODE_URL}/session",
                    json={"prompt": user_input},
                    timeout=300,
                )

            resp.raise_for_status()
            result = resp.json()

            # Extract response — OpenCode may return different shapes
            answer = (
                result.get("content")
                or result.get("response")
                or result.get("output")
                or result.get("text")
                or "No response from OpenCode."
            )
            if isinstance(answer, dict):
                answer = answer.get("text", json.dumps(answer))
            if isinstance(answer, list):
                answer = "\n".join(
                    str(item.get("text", item)) if isinstance(item, dict) else str(item)
                    for item in answer
                )

            parts = [TextPart(text=str(answer))]
            await task_updater.add_artifact(parts)
            await task_updater.complete()

        except Exception as e:
            logger.error("OpenCode execution error: %s", e)
            error_msg = json.dumps({"type": "error", "message": str(e)})
            await task_updater.update_status(
                TaskState.working,
                new_agent_text_message(
                    error_msg,
                    task_updater.context_id,
                    task_updater.task_id,
                ),
            )
            parts = [TextPart(text=f"Error: {e}")]
            await task_updater.add_artifact(parts)
            await task_updater.failed()

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        raise Exception("cancel not supported")
