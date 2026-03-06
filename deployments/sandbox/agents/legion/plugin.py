"""Legion agent plugin — implements the platform_base plugin contract.

This module is loaded by the platform entrypoint via AGENT_MODULE=legion.plugin.
It exports build_executor() and get_agent_card() as required by the contract.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from pathlib import Path
from textwrap import dedent
from typing import TYPE_CHECKING

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
from langchain_core.messages import HumanMessage
from langgraph.checkpoint.memory import MemorySaver

if TYPE_CHECKING:
    from platform_base.permissions import PermissionChecker
    from platform_base.sources import SourcesConfig
    from platform_base.workspace import WorkspaceManager

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Plugin contract: get_agent_card
# ---------------------------------------------------------------------------


def get_agent_card(host: str, port: int) -> AgentCard:
    """Return an A2A AgentCard for the Sandbox Legion."""
    capabilities = AgentCapabilities(streaming=True)
    skill = AgentSkill(
        id="sandbox_legion",
        name="Sandbox Legion",
        description=(
            "**Sandbox Legion** -- Executes shell commands, reads and writes "
            "files in an isolated per-context workspace with permission checks."
        ),
        tags=["shell", "file", "workspace", "sandbox"],
        examples=[
            "Run 'ls -la' in my workspace",
            "Create a Python script that prints hello world",
            "Read the contents of output/results.txt",
        ],
    )
    return AgentCard(
        name="Sandbox Legion",
        description=dedent(
            """\
            A sandboxed coding assistant that can execute shell commands, \
            read files, and write files inside isolated per-context workspaces.

            ## Key Features
            - **Shell execution** with three-tier permission checks (allow/deny/HITL)
            - **File read/write** with path-traversal prevention
            - **Per-context workspaces** for multi-turn isolation
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
    """Build and return a LegionAgentExecutor wired to platform services."""
    return LegionAgentExecutor(
        workspace_manager=workspace_manager,
        permission_checker=permission_checker,
        sources_config=sources_config,
    )


# ---------------------------------------------------------------------------
# Agent Executor
# ---------------------------------------------------------------------------


class LegionAgentExecutor(AgentExecutor):
    """A2A executor that delegates to the LangGraph sandbox graph."""

    _context_locks: dict[str, asyncio.Lock] = {}
    _context_locks_mutex: asyncio.Lock = asyncio.Lock()

    async def _get_context_lock(self, context_id: str) -> asyncio.Lock:
        async with self._context_locks_mutex:
            lock = self._context_locks.get(context_id)
            if lock is None:
                lock = asyncio.Lock()
                self._context_locks[context_id] = lock
            return lock

    def __init__(
        self,
        workspace_manager: WorkspaceManager,
        permission_checker: PermissionChecker,
        sources_config: SourcesConfig,
    ) -> None:
        self._workspace_manager = workspace_manager
        self._permission_checker = permission_checker
        self._sources_config = sources_config

        from legion.configuration import Configuration

        config = Configuration()  # type: ignore[call-arg]

        self._checkpoint_db_url = config.checkpoint_db_url
        self._checkpointer = None
        self._checkpointer_initialized = False
        if not self._checkpoint_db_url or self._checkpoint_db_url == "memory":
            self._checkpointer = MemorySaver()
            self._checkpointer_initialized = True
            logger.info("Using in-memory checkpointer")
        else:
            logger.info(
                "PostgreSQL checkpointer configured: %s",
                self._checkpoint_db_url.split("@")[-1],
            )

        cleaned = self._workspace_manager.cleanup_expired()
        if cleaned:
            logger.info("Cleaned up %d expired workspaces: %s", len(cleaned), cleaned)

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        """Execute a user request through the LangGraph sandbox graph."""
        from legion.event_serializer import LangGraphSerializer
        from legion.graph import build_graph

        task = context.current_task
        if not task:
            task = new_task(context.message)  # type: ignore
            await event_queue.enqueue_event(task)

        task_updater = TaskUpdater(event_queue, task.id, task.context_id)

        context_id = task.context_id
        if context_id:
            workspace_path = self._workspace_manager.ensure_workspace(context_id)
            logger.info("Using workspace context_id=%s: %s", context_id, workspace_path)
        else:
            workspace_path = "/tmp/sandbox-stateless"
            Path(workspace_path).mkdir(parents=True, exist_ok=True)

        # Lazy-init PostgreSQL checkpointer
        if not self._checkpointer_initialized and self._checkpoint_db_url:
            from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

            cm = AsyncPostgresSaver.from_conn_string(self._checkpoint_db_url)
            self._checkpointer = await cm.__aenter__()
            self._checkpointer_cm = cm
            await self._checkpointer.setup()
            self._checkpointer_initialized = True
            logger.info("PostgreSQL checkpointer initialized")

        graph = build_graph(
            workspace_path=workspace_path,
            permission_checker=self._permission_checker,
            sources_config=self._sources_config,
            checkpointer=self._checkpointer,
            context_id=context_id or "stateless",
        )

        lock = await self._get_context_lock(context_id or "stateless")

        async with lock:
            messages = [HumanMessage(content=context.get_user_input())]
            input_state = {"messages": messages}
            graph_config = {"configurable": {"thread_id": context_id or "stateless"}}

            try:
                output = None
                serializer = LangGraphSerializer()

                max_retries = 3
                for attempt in range(max_retries + 1):
                    try:
                        async for event in graph.astream(
                            input_state, config=graph_config, stream_mode="updates"
                        ):
                            await task_updater.update_status(
                                TaskState.working,
                                new_agent_text_message(
                                    "\n".join(
                                        serializer.serialize(key, value)
                                        for key, value in event.items()
                                    )
                                    + "\n",
                                    task_updater.context_id,
                                    task_updater.task_id,
                                ),
                            )
                            output = event
                        break
                    except Exception as retry_err:
                        err_str = str(retry_err).lower()
                        is_quota = "insufficient_quota" in err_str
                        is_rate_limit = "rate_limit" in err_str or "429" in err_str

                        if is_quota:
                            logger.error("LLM quota exceeded: %s", retry_err)
                            error_msg = (
                                "LLM API quota exceeded. Please check your API billing."
                            )
                            await task_updater.update_status(
                                TaskState.working,
                                new_agent_text_message(
                                    json.dumps({"type": "error", "message": error_msg}),
                                    task_updater.context_id,
                                    task_updater.task_id,
                                ),
                            )
                            parts = [TextPart(text=error_msg)]
                            await task_updater.add_artifact(parts)
                            await task_updater.failed()
                            return
                        elif is_rate_limit and attempt < max_retries:
                            delay = 2 ** (attempt + 1)
                            logger.warning(
                                "Rate limited (attempt %d/%d), retrying in %ds",
                                attempt + 1,
                                max_retries,
                                delay,
                            )
                            await task_updater.update_status(
                                TaskState.working,
                                new_agent_text_message(
                                    json.dumps(
                                        {
                                            "type": "error",
                                            "message": f"Rate limited, retrying in {delay}s...",
                                        }
                                    ),
                                    task_updater.context_id,
                                    task_updater.task_id,
                                ),
                            )
                            await asyncio.sleep(delay)
                            continue
                        else:
                            raise

                # Extract final answer
                final_answer = None
                if output:
                    reporter_output = output.get("reporter", {})
                    if isinstance(reporter_output, dict):
                        final_answer = reporter_output.get("final_answer")

                    if not final_answer:
                        for node_name in ("reporter", "executor", "assistant"):
                            node_output = output.get(node_name, {})
                            if isinstance(node_output, dict):
                                msgs = node_output.get("messages", [])
                                if msgs:
                                    content = getattr(msgs[-1], "content", None)
                                    if isinstance(content, list):
                                        final_answer = (
                                            "\n".join(
                                                block.get("text", "")
                                                if isinstance(block, dict)
                                                else str(block)
                                                for block in content
                                                if isinstance(block, dict)
                                                and block.get("type") == "text"
                                            )
                                            or None
                                        )
                                    elif content:
                                        final_answer = str(content)
                                    if final_answer:
                                        break

                if final_answer is None:
                    final_answer = "No response generated."

                parts = [TextPart(text=final_answer)]
                await task_updater.add_artifact(parts)
                await task_updater.complete()

            except Exception as e:
                logger.error("Graph execution error: %s", e)
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

        # Periodic lock cleanup
        async with self._context_locks_mutex:
            stale = [cid for cid, lk in self._context_locks.items() if not lk.locked()]
            if len(stale) > 1000:
                for cid in stale:
                    del self._context_locks[cid]

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        raise Exception("cancel not supported")
