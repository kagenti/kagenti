"""Sub-agent spawning tools for the sandbox agent.

Provides three tools:

1. **explore**: Read-only in-process sub-graph (grep, read_file, list_files).
   Good for codebase research and analysis.

2. **delegate**: Multi-mode delegation with 4 strategies:
   - in-process: LangGraph subgraph, shared filesystem (fast)
   - shared-pvc: Separate pod with parent's PVC mounted
   - isolated: Separate pod via SandboxClaim (full isolation)
   - sidecar: New container in parent pod

   The LLM auto-selects the best mode, or the caller can specify.
"""

from __future__ import annotations

import asyncio
import logging
import os
import subprocess
import uuid
from pathlib import Path
from typing import Any, Optional

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.tools import tool
from langgraph.graph import MessagesState, StateGraph
from langgraph.prebuilt import ToolNode, tools_condition

logger = logging.getLogger(__name__)

# Maximum iterations for in-process sub-agents
_MAX_SUB_AGENT_ITERATIONS = 15

# Delegation mode configuration
_DELEGATION_MODES = os.environ.get(
    "DELEGATION_MODES", "in-process,shared-pvc,isolated,sidecar"
).split(",")
_DEFAULT_MODE = os.environ.get("DEFAULT_DELEGATION_MODE", "in-process")

# Maximum iterations for in-process sub-agents to prevent runaway loops.
_MAX_SUB_AGENT_ITERATIONS = 15


# ---------------------------------------------------------------------------
# In-process sub-agent: explore (C20, mode 1)
# ---------------------------------------------------------------------------


def _make_explore_tools(workspace: str) -> list[Any]:
    """Build a read-only tool set for the explore sub-agent."""
    ws_root = Path(workspace).resolve()

    @tool
    async def grep(pattern: str, path: str = ".") -> str:
        """Search for a regex pattern in files under the workspace.

        Args:
            pattern: Regex pattern to search for.
            path: Relative path to search in (default: workspace root).

        Returns:
            Matching lines with file paths and line numbers.
        """
        target = (ws_root / path).resolve()
        if not target.is_relative_to(ws_root):
            return "Error: path resolves outside the workspace."

        try:
            result = subprocess.run(
                [
                    "grep",
                    "-rn",
                    "--include=*.py",
                    "--include=*.md",
                    "--include=*.yaml",
                    "--include=*.yml",
                    "--include=*.json",
                    "--include=*.txt",
                    "--include=*.sh",
                    "--include=*.go",
                    pattern,
                    str(target),
                ],
                capture_output=True,
                text=True,
                timeout=30,
                cwd=str(ws_root),
            )
            output = result.stdout[:10000]
            if not output:
                return f"No matches found for pattern '{pattern}'"
            return output
        except subprocess.TimeoutExpired:
            return "Search timed out after 30 seconds."
        except FileNotFoundError:
            return "grep command not available."

    @tool
    async def read_file(path: str) -> str:
        """Read a file from the workspace (read-only).

        Args:
            path: Relative path within the workspace.

        Returns:
            File contents (truncated to 20000 chars).
        """
        resolved = (ws_root / path).resolve()
        if not str(resolved).startswith(str(ws_root)):
            return "Error: path resolves outside the workspace."
        if not resolved.is_file():
            return f"Error: file not found at '{path}'."
        try:
            content = resolved.read_text(encoding="utf-8", errors="replace")
            if len(content) > 20000:
                content = content[:20000] + "\n\n[Truncated at 20000 chars]"
            return content
        except OSError as exc:
            return f"Error reading file: {exc}"

    @tool
    async def list_files(path: str = ".", pattern: str = "*") -> str:
        """List files matching a glob pattern in the workspace.

        Args:
            path: Relative directory to search in (default: workspace root).
            pattern: Glob pattern (default: all files).

        Returns:
            Newline-separated list of matching file paths.
        """
        target = (ws_root / path).resolve()
        if not target.is_relative_to(ws_root):
            return "Error: path resolves outside the workspace."
        if not target.is_dir():
            return f"Error: directory not found at '{path}'."

        matches = sorted(
            str(p.relative_to(ws_root)) for p in target.rglob(pattern) if p.is_file()
        )
        if len(matches) > 200:
            matches = matches[:200]
            matches.append(f"... and more (truncated at 200)")
        return "\n".join(matches) if matches else "No files found."

    return [grep, read_file, list_files]


def create_explore_graph(workspace: str, llm: Any) -> Any:
    """Create a read-only explore sub-graph.

    The sub-graph has access only to grep, read_file, and list_files.
    It is bounded to ``_MAX_SUB_AGENT_ITERATIONS`` steps.
    """
    tools = _make_explore_tools(workspace)
    llm_with_tools = llm.bind_tools(tools)

    async def assistant(state: MessagesState) -> dict[str, Any]:
        system = SystemMessage(
            content=(
                "You are a codebase research assistant. Your job is to find "
                "specific information in the workspace using grep, read_file, "
                "and list_files. Be concise. Return a focused summary of what "
                "you found. Do NOT modify any files."
            )
        )
        messages = [system] + state["messages"]
        response = await llm_with_tools.ainvoke(messages)
        return {"messages": [response]}

    graph = StateGraph(MessagesState)
    graph.add_node("assistant", assistant)
    graph.add_node("tools", ToolNode(tools))
    graph.set_entry_point("assistant")
    graph.add_conditional_edges("assistant", tools_condition)
    graph.add_edge("tools", "assistant")

    return graph.compile()


def make_explore_tool(workspace: str, llm: Any) -> Any:
    """Return a LangChain tool that spawns an in-process explore sub-agent."""

    @tool
    async def explore(query: str) -> str:
        """Spawn a read-only sub-agent to research the codebase.

        The sub-agent has access to grep, read_file, and list_files
        but cannot write files or execute shell commands. Use this for
        codebase exploration, finding definitions, and analyzing code.

        Args:
            query: What to search for or investigate in the codebase.

        Returns:
            A summary of findings from the explore sub-agent.
        """
        sub_graph = create_explore_graph(workspace, llm)
        try:
            result = await asyncio.wait_for(
                sub_graph.ainvoke(
                    {"messages": [HumanMessage(content=query)]},
                    config={"recursion_limit": _MAX_SUB_AGENT_ITERATIONS},
                ),
                timeout=120,
            )
            messages = result.get("messages", [])
            if messages:
                last = messages[-1]
                return last.content if hasattr(last, "content") else str(last)
            return "No results from explore sub-agent."
        except asyncio.TimeoutError:
            return "Explore sub-agent timed out after 120 seconds."
        except Exception as exc:
            return f"Explore sub-agent error: {exc}"

    return explore


# ---------------------------------------------------------------------------
# Multi-mode delegation (Session E)
# ---------------------------------------------------------------------------


async def _run_in_process(
    task: str,
    workspace: str,
    llm: Any,
    child_context_id: str,
    tools_list: list[Any] | None = None,
    timeout: int = 120,
) -> str:
    """Execute a task as an in-process LangGraph subgraph."""
    if tools_list is None:
        tools_list = _make_explore_tools(workspace)

    llm_with_tools = llm.bind_tools(tools_list)

    async def assistant(state: MessagesState) -> dict[str, Any]:
        system = SystemMessage(
            content=(
                "You are a sub-agent working on a delegated task. Complete the task "
                "efficiently using the available tools. Return a clear summary of "
                "what you did and the results."
            )
        )
        messages = [system] + state["messages"]
        response = await llm_with_tools.ainvoke(messages)
        return {"messages": [response]}

    graph = StateGraph(MessagesState)
    graph.add_node("assistant", assistant)
    graph.add_node("tools", ToolNode(tools_list))
    graph.set_entry_point("assistant")
    graph.add_conditional_edges("assistant", tools_condition)
    graph.add_edge("tools", "assistant")
    sub_graph = graph.compile()

    try:
        result = await asyncio.wait_for(
            sub_graph.ainvoke(
                {"messages": [HumanMessage(content=task)]},
                config={
                    "recursion_limit": _MAX_SUB_AGENT_ITERATIONS,
                    "configurable": {"thread_id": child_context_id},
                },
            ),
            timeout=timeout,
        )
        messages = result.get("messages", [])
        if messages:
            last = messages[-1]
            return last.content if hasattr(last, "content") else str(last)
        return "No results from in-process sub-agent."
    except asyncio.TimeoutError:
        return f"In-process sub-agent timed out after {timeout} seconds."
    except Exception as exc:
        logger.exception("In-process delegation failed for %s", child_context_id)
        return f"In-process sub-agent error: {exc}"


async def _run_shared_pvc(
    task: str,
    child_context_id: str,
    namespace: str = "team1",
    variant: str = "sandbox-legion",
    timeout_minutes: int = 30,
) -> str:
    """Spawn a pod that mounts the parent's PVC (placeholder)."""
    logger.info("shared-pvc delegation: child=%s task=%s", child_context_id, task)
    return (
        f"Shared-PVC delegation requested for '{task}' "
        f"(child={child_context_id}, namespace={namespace}). "
        "Requires RWX StorageClass. Not yet implemented."
    )


async def _run_isolated(
    task: str,
    child_context_id: str,
    namespace: str = "team1",
    variant: str = "sandbox-legion",
    timeout_minutes: int = 30,
) -> str:
    """Spawn an isolated pod via SandboxClaim CRD (placeholder)."""
    logger.info("isolated delegation: child=%s task=%s", child_context_id, task)
    return (
        f"Isolated delegation requested for '{task}' "
        f"(child={child_context_id}, namespace={namespace}). "
        "Requires SandboxClaim CRD + controller. Not yet implemented."
    )


async def _run_sidecar(
    task: str,
    child_context_id: str,
    variant: str = "sandbox-legion",
) -> str:
    """Inject a sidecar container (placeholder)."""
    logger.info("sidecar delegation: child=%s task=%s", child_context_id, task)
    return (
        f"Sidecar delegation requested for '{task}' "
        f"(child={child_context_id}). Not yet implemented."
    )


def make_delegate_tool(
    workspace: str,
    llm: Any,
    parent_context_id: str = "",
    tools_list: list[Any] | None = None,
    namespace: str = "team1",
) -> Any:
    """Return a LangChain tool for multi-mode delegation.

    Args:
        workspace: Path to the parent's workspace.
        llm: The LLM instance for in-process subgraphs.
        parent_context_id: The parent session's context_id.
        tools_list: Optional tools for in-process subgraphs.
        namespace: Kubernetes namespace for out-of-process modes.
    """

    @tool
    async def delegate(
        task: str,
        mode: str = "auto",
        variant: str = "sandbox-legion",
        timeout_minutes: int = 30,
    ) -> str:
        """Delegate a task to a child session.

        Spawns a child agent to work on the task independently.

        Args:
            task: Description of the task for the child session.
            mode: Delegation mode — "auto" (LLM picks), "in-process",
                "shared-pvc", "isolated", or "sidecar".
            variant: Agent variant for out-of-process modes.
            timeout_minutes: Timeout for the child session.

        Returns:
            The child session's result or status message.
        """
        child_context_id = f"child-{uuid.uuid4().hex[:12]}"

        selected_mode = mode
        if mode == "auto":
            task_lower = task.lower()
            if any(
                w in task_lower for w in ("explore", "read", "analyze", "check", "find")
            ):
                selected_mode = "in-process"
            elif any(
                w in task_lower
                for w in ("pr", "branch", "build", "deploy", "implement")
            ):
                selected_mode = "isolated"
            elif any(w in task_lower for w in ("test", "verify", "validate", "run")):
                selected_mode = "shared-pvc"
            else:
                selected_mode = _DEFAULT_MODE

        if selected_mode not in _DELEGATION_MODES:
            return f"Mode '{selected_mode}' not enabled. Available: {', '.join(_DELEGATION_MODES)}"

        logger.info(
            "Delegating: child=%s mode=%s parent=%s",
            child_context_id,
            selected_mode,
            parent_context_id,
        )

        if selected_mode == "in-process":
            return await _run_in_process(
                task, workspace, llm, child_context_id, tools_list, timeout_minutes * 60
            )
        elif selected_mode == "shared-pvc":
            return await _run_shared_pvc(
                task, child_context_id, namespace, variant, timeout_minutes
            )
        elif selected_mode == "isolated":
            return await _run_isolated(
                task, child_context_id, namespace, variant, timeout_minutes
            )
        elif selected_mode == "sidecar":
            return await _run_sidecar(task, child_context_id, variant)
        return f"Unknown mode: {selected_mode}"

    return delegate
