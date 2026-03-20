"""Framework-specific event serializers for structured JSON streaming.

Each agent framework (LangGraph, CrewAI, AG2) has its own internal event
format. Serializers convert framework events into a common JSON schema
that the backend and frontend understand.

Event types:
    tool_call     — LLM decided to call one or more tools
    tool_result   — A tool returned output
    llm_response  — LLM generated text (no tool calls)
    plan          — Planner produced a numbered plan
    plan_step     — Executor is working on a specific plan step
    reflection    — Reflector reviewed step output
    error         — An error occurred during execution
    hitl_request  — Human-in-the-loop approval is needed
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from typing import Any


class FrameworkEventSerializer(ABC):
    """Base class for framework-specific event serialization.

    Subclass this for each agent framework (LangGraph, CrewAI, AG2).
    The ``serialize`` method must return a JSON string with at least
    a ``type`` field.
    """

    @abstractmethod
    def serialize(self, key: str, value: dict) -> str:
        """Serialize a framework event into a JSON string.

        Parameters
        ----------
        key:
            The graph node name (e.g. "assistant", "tools").
        value:
            The event payload from the framework's streaming API.

        Returns
        -------
        str
            A JSON string with at least ``{"type": "..."}``
        """
        ...


class LangGraphSerializer(FrameworkEventSerializer):
    """Serialize LangGraph ``stream_mode='updates'`` events.

    LangGraph emits events like::

        {"assistant": {"messages": [AIMessage(...)]}}
        {"tools": {"messages": [ToolMessage(...)]}}

    This serializer extracts tool calls, tool results, and LLM
    responses into structured JSON.

    When the graph uses a plan-execute-reflect reasoning loop, all
    events include a ``loop_id`` so the frontend can group them into
    an expandable AgentLoopCard.
    """

    def __init__(self, loop_id: str | None = None) -> None:
        import uuid

        self._loop_id = loop_id or str(uuid.uuid4())[:8]
        self._step_index = 0

    def serialize(self, key: str, value: dict) -> str:
        # Reasoning-loop nodes may emit state fields instead of messages
        if key == "planner":
            return self._serialize_planner(value)
        elif key == "reflector":
            return self._serialize_reflector(value)
        elif key == "reporter":
            return self._serialize_reporter(value)

        msgs = value.get("messages", [])
        if not msgs:
            return json.dumps({"type": "llm_response", "content": f"[{key}]"})

        msg = msgs[-1]

        if key == "executor":
            return self._serialize_executor(msg)
        elif key == "tools":
            return self._serialize_tool_result(msg)
        else:
            # Unknown node — treat as informational
            content = getattr(msg, "content", "")
            if isinstance(content, list):
                text = self._extract_text_blocks(content)
            else:
                text = str(content)[:2000] if content else f"[{key}]"
            return json.dumps({"type": "llm_response", "content": text})

    def _serialize_assistant(self, msg: Any) -> str:
        """Serialize an assistant (LLM) node output.

        When the LLM calls tools, it often also produces reasoning text.
        We emit BOTH the thinking content and the tool call as separate
        JSON lines so the UI shows the full chain:
            {"type": "llm_response", "content": "Let me check..."}
            {"type": "tool_call", "tools": [...]}
        """
        tool_calls = getattr(msg, "tool_calls", [])
        content = getattr(msg, "content", "")

        # Extract any text content from the LLM
        if isinstance(content, list):
            text = self._extract_text_blocks(content)
        else:
            text = str(content)[:2000] if content else ""

        if tool_calls:
            parts = []
            # Emit thinking/reasoning text first (if present)
            if text.strip():
                parts.append(json.dumps({"type": "llm_response", "content": text}))
            # Then emit the tool call
            parts.append(
                json.dumps(
                    {
                        "type": "tool_call",
                        "tools": [
                            {
                                "name": tc.get("name", "unknown")
                                if isinstance(tc, dict)
                                else getattr(tc, "name", "unknown"),
                                "args": tc.get("args", {})
                                if isinstance(tc, dict)
                                else getattr(tc, "args", {}),
                            }
                            for tc in tool_calls
                        ],
                    }
                )
            )
            return "\n".join(parts)

        return json.dumps({"type": "llm_response", "content": text})

    def _serialize_executor(self, msg: Any) -> str:
        """Serialize an executor node output with loop_id for AgentLoopCard."""
        tool_calls = getattr(msg, "tool_calls", [])
        content = getattr(msg, "content", "")

        if isinstance(content, list):
            text = self._extract_text_blocks(content)
        else:
            text = str(content)[:2000] if content else ""

        parts = []

        # Emit plan_step event so UI shows which step is executing
        parts.append(
            json.dumps(
                {
                    "type": "plan_step",
                    "loop_id": self._loop_id,
                    "step": self._step_index,
                    "description": text[:200] if text else "",
                }
            )
        )

        if tool_calls:
            if text.strip():
                parts.append(
                    json.dumps(
                        {
                            "type": "llm_response",
                            "loop_id": self._loop_id,
                            "content": text,
                        }
                    )
                )
            parts.append(
                json.dumps(
                    {
                        "type": "tool_call",
                        "loop_id": self._loop_id,
                        "step": self._step_index,
                        "tools": [
                            {
                                "name": tc.get("name", "unknown")
                                if isinstance(tc, dict)
                                else getattr(tc, "name", "unknown"),
                                "args": tc.get("args", {})
                                if isinstance(tc, dict)
                                else getattr(tc, "args", {}),
                            }
                            for tc in tool_calls
                        ],
                    }
                )
            )
            return "\n".join(parts)

        if text:
            parts.append(
                json.dumps(
                    {
                        "type": "llm_response",
                        "loop_id": self._loop_id,
                        "content": text,
                    }
                )
            )

        return (
            "\n".join(parts)
            if parts
            else json.dumps(
                {
                    "type": "llm_response",
                    "loop_id": self._loop_id,
                    "content": "",
                }
            )
        )

    def _serialize_tool_result(self, msg: Any) -> str:
        """Serialize a tool node output with loop_id."""
        name = getattr(msg, "name", "unknown")
        content = getattr(msg, "content", "")
        return json.dumps(
            {
                "type": "tool_result",
                "loop_id": self._loop_id,
                "step": self._step_index,
                "name": str(name),
                "output": str(content)[:2000],
            }
        )

    def _serialize_planner(self, value: dict) -> str:
        """Serialize a planner node output — emits the plan steps."""
        plan = value.get("plan", [])
        iteration = value.get("iteration", 1)

        # Also include any LLM text from the planner's message
        msgs = value.get("messages", [])
        text = ""
        if msgs:
            content = getattr(msgs[-1], "content", "")
            if isinstance(content, list):
                text = self._extract_text_blocks(content)
            else:
                text = str(content)[:2000] if content else ""

        return json.dumps(
            {
                "type": "plan",
                "loop_id": self._loop_id,
                "steps": plan,
                "iteration": iteration,
                "content": text,
            }
        )

    def _serialize_reflector(self, value: dict) -> str:
        """Serialize a reflector node output — emits the decision."""
        done = value.get("done", False)
        current_step = value.get("current_step", 0)
        step_results = value.get("step_results", [])

        # Extract decision text from message if present
        msgs = value.get("messages", [])
        text = ""
        if msgs:
            content = getattr(msgs[-1], "content", "")
            if isinstance(content, list):
                text = self._extract_text_blocks(content)
            else:
                text = str(content)[:500] if content else ""

        # Advance step index when reflector completes a step
        self._step_index = current_step

        return json.dumps(
            {
                "type": "reflection",
                "loop_id": self._loop_id,
                "done": done,
                "current_step": current_step,
                "assessment": text,
                "content": text,
            }
        )

    def _serialize_reporter(self, value: dict) -> str:
        """Serialize a reporter node output — emits the final answer."""
        final_answer = value.get("final_answer", "")

        # Also check messages for the reporter's LLM response
        if not final_answer:
            msgs = value.get("messages", [])
            if msgs:
                content = getattr(msgs[-1], "content", "")
                if isinstance(content, list):
                    final_answer = self._extract_text_blocks(content)
                else:
                    final_answer = str(content)[:2000] if content else ""

        return json.dumps(
            {
                "type": "llm_response",
                "loop_id": self._loop_id,
                "content": final_answer[:2000],
            }
        )

    @staticmethod
    def _extract_text_blocks(content: list) -> str:
        """Extract text from a list of content blocks."""
        return " ".join(
            b.get("text", "")
            for b in content
            if isinstance(b, dict) and b.get("type") == "text"
        )[:2000]
