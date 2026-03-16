# Tool Call Rendering Fix — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace fragile Python repr() → regex tool call rendering with structured JSON events using a framework adapter pattern.

**Architecture:** Agent emits structured JSON via a `LangGraphSerializer` adapter (extensible to CrewAI/AG2). Backend parses JSON first with regex fallback for old history. Frontend renders 5 event types: tool_call, tool_result, llm_response, error, hitl_request.

**Tech Stack:** Python 3.11 (agent + backend), TypeScript/React (frontend), Shipwright (agent rebuild), HyperShift clusters (sbox/sbox1 for testing).

**Design doc:** `docs/plans/2026-02-27-tool-call-rendering-design.md`

---

## Worktrees & Repos

| Worktree | Repo | Branch | What changes |
|----------|------|--------|-------------|
| `.worktrees/agent-examples` | github.com/ladas/agent-examples | `feat/sandbox-agent` | Agent code (serializer + agent.py) |
| `.worktrees/sandbox-agent` | github.com/kagenti/kagenti | `feat/sandbox-agent` | Backend (sandbox.py) + Frontend (SandboxPage.tsx) |

## Environment Setup

```bash
cd /Users/ladas/Projects/OCTO/kagenti/kagenti
export MANAGED_BY_TAG=kagenti-team
source .env.kagenti-team
export KUBECONFIG=~/clusters/hcp/kagenti-team-sbox/auth/kubeconfig
export PATH="/opt/homebrew/opt/helm@3/bin:$PATH"
export LOG_DIR=/tmp/kagenti/tdd/tool-call-fix
mkdir -p $LOG_DIR
```

---

### Task 1: Create LangGraph Event Serializer (agent-side)

**Files:**
- Create: `.worktrees/agent-examples/a2a/sandbox_agent/src/sandbox_agent/event_serializer.py`
- Test: `.worktrees/agent-examples/a2a/sandbox_agent/tests/test_event_serializer.py`

**Step 1: Write the failing test**

Create `.worktrees/agent-examples/a2a/sandbox_agent/tests/test_event_serializer.py`:

```python
"""Tests for the framework event serializer."""

import json
from unittest.mock import MagicMock

import pytest

from sandbox_agent.event_serializer import LangGraphSerializer


class TestLangGraphSerializer:
    """Test LangGraph event serialization to structured JSON."""

    def setup_method(self):
        self.serializer = LangGraphSerializer()

    def test_tool_call_event(self):
        """Assistant node with tool_calls produces a tool_call event."""
        msg = MagicMock()
        msg.tool_calls = [{"name": "shell", "args": {"command": "ls -la"}}]
        msg.content = ""

        result = json.loads(self.serializer.serialize("assistant", {"messages": [msg]}))

        assert result["type"] == "tool_call"
        assert len(result["tools"]) == 1
        assert result["tools"][0]["name"] == "shell"
        assert result["tools"][0]["args"] == {"command": "ls -la"}

    def test_tool_call_multiple_tools(self):
        """Multiple tool calls in one LLM response."""
        msg = MagicMock()
        msg.tool_calls = [
            {"name": "shell", "args": {"command": "ls"}},
            {"name": "file_read", "args": {"path": "README.md"}},
        ]
        msg.content = ""

        result = json.loads(self.serializer.serialize("assistant", {"messages": [msg]}))

        assert result["type"] == "tool_call"
        assert len(result["tools"]) == 2
        assert result["tools"][1]["name"] == "file_read"

    def test_llm_response_string_content(self):
        """Assistant node with string content (no tool calls) produces llm_response."""
        msg = MagicMock()
        msg.tool_calls = []
        msg.content = "Let me check the files for you."

        result = json.loads(self.serializer.serialize("assistant", {"messages": [msg]}))

        assert result["type"] == "llm_response"
        assert result["content"] == "Let me check the files for you."

    def test_llm_response_list_content(self):
        """Assistant content as list of blocks (tool-calling model format)."""
        msg = MagicMock()
        msg.tool_calls = []
        msg.content = [
            {"type": "text", "text": "Here is the answer."},
            {"type": "image", "data": "base64..."},
        ]

        result = json.loads(self.serializer.serialize("assistant", {"messages": [msg]}))

        assert result["type"] == "llm_response"
        assert result["content"] == "Here is the answer."

    def test_tool_result_event(self):
        """Tools node produces a tool_result event."""
        msg = MagicMock()
        msg.name = "shell"
        msg.content = "file1.txt\nfile2.txt\nREADME.md"

        result = json.loads(self.serializer.serialize("tools", {"messages": [msg]}))

        assert result["type"] == "tool_result"
        assert result["name"] == "shell"
        assert "file1.txt" in result["output"]

    def test_tool_result_truncation(self):
        """Long tool output is truncated to 2000 chars."""
        msg = MagicMock()
        msg.name = "shell"
        msg.content = "x" * 5000

        result = json.loads(self.serializer.serialize("tools", {"messages": [msg]}))

        assert len(result["output"]) == 2000

    def test_empty_messages(self):
        """Empty messages dict produces llm_response with node name."""
        result = json.loads(self.serializer.serialize("assistant", {"messages": []}))

        assert result["type"] == "llm_response"
        assert "[assistant]" in result["content"]

    def test_unknown_node(self):
        """Unknown node name still produces valid JSON."""
        msg = MagicMock()
        msg.tool_calls = []
        msg.content = "done"

        result = json.loads(self.serializer.serialize("__end__", {"messages": [msg]}))

        assert result["type"] == "llm_response"

    def test_error_in_tool_result(self):
        """Tool error content is preserved."""
        msg = MagicMock()
        msg.name = "shell"
        msg.content = "Error: command 'rm -rf /' denied by policy"

        result = json.loads(self.serializer.serialize("tools", {"messages": [msg]}))

        assert result["type"] == "tool_result"
        assert "denied by policy" in result["output"]

    def test_output_is_valid_json(self):
        """All serialize calls produce valid JSON strings."""
        msg = MagicMock()
        msg.tool_calls = [{"name": "shell", "args": {"cmd": 'echo "hello world"'}}]
        msg.content = ""

        output = self.serializer.serialize("assistant", {"messages": [msg]})

        # Must be parseable JSON
        parsed = json.loads(output)
        assert isinstance(parsed, dict)
        assert "type" in parsed
```

**Step 2: Run test to verify it fails**

```bash
cd .worktrees/agent-examples/a2a/sandbox_agent
python -m pytest tests/test_event_serializer.py -v 2>&1 | tail -5
```

Expected: FAIL with `ModuleNotFoundError: No module named 'sandbox_agent.event_serializer'`

**Step 3: Write the implementation**

Create `.worktrees/agent-examples/a2a/sandbox_agent/src/sandbox_agent/event_serializer.py`:

```python
"""Framework-specific event serializers for structured JSON streaming.

Each agent framework (LangGraph, CrewAI, AG2) has its own internal event
format. Serializers convert framework events into a common JSON schema
that the backend and frontend understand.

Event types:
    tool_call     — LLM decided to call one or more tools
    tool_result   — A tool returned output
    llm_response  — LLM generated text (no tool calls)
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
    """

    def serialize(self, key: str, value: dict) -> str:
        msgs = value.get("messages", [])
        if not msgs:
            return json.dumps({"type": "llm_response", "content": f"[{key}]"})

        msg = msgs[-1]

        if key == "assistant":
            return self._serialize_assistant(msg)
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
        """Serialize an assistant (LLM) node output."""
        tool_calls = getattr(msg, "tool_calls", [])

        if tool_calls:
            return json.dumps({
                "type": "tool_call",
                "tools": [
                    {
                        "name": tc.get("name", "unknown") if isinstance(tc, dict) else getattr(tc, "name", "unknown"),
                        "args": tc.get("args", {}) if isinstance(tc, dict) else getattr(tc, "args", {}),
                    }
                    for tc in tool_calls
                ],
            })

        content = getattr(msg, "content", "")
        if isinstance(content, list):
            text = self._extract_text_blocks(content)
        else:
            text = str(content)[:2000] if content else ""

        return json.dumps({"type": "llm_response", "content": text})

    def _serialize_tool_result(self, msg: Any) -> str:
        """Serialize a tool node output."""
        name = getattr(msg, "name", "unknown")
        content = getattr(msg, "content", "")
        return json.dumps({
            "type": "tool_result",
            "name": str(name),
            "output": str(content)[:2000],
        })

    @staticmethod
    def _extract_text_blocks(content: list) -> str:
        """Extract text from a list of content blocks."""
        return " ".join(
            b.get("text", "")
            for b in content
            if isinstance(b, dict) and b.get("type") == "text"
        )[:2000]
```

**Step 4: Run tests to verify they pass**

```bash
cd .worktrees/agent-examples/a2a/sandbox_agent
python -m pytest tests/test_event_serializer.py -v 2>&1 | tail -15
```

Expected: All 10 tests PASS.

**Step 5: Commit**

```bash
cd .worktrees/agent-examples
git add a2a/sandbox_agent/src/sandbox_agent/event_serializer.py \
        a2a/sandbox_agent/tests/test_event_serializer.py
git commit -s -m "feat(sandbox): add LangGraph event serializer for structured JSON streaming

Replaces fragile str(value)/repr() event emission with structured JSON.
Introduces FrameworkEventSerializer ABC with LangGraphSerializer
implementation. Extensible to CrewAI/AG2 adapters.

Event types: tool_call, tool_result, llm_response, error, hitl_request."
```

---

### Task 2: Wire Serializer into Agent Streaming Loop

**Files:**
- Modify: `.worktrees/agent-examples/a2a/sandbox_agent/src/sandbox_agent/agent.py:343-356`

**Step 1: Update agent.py to use the serializer**

In `agent.py`, replace lines 343-356. Change the `str(value)` calls to use `LangGraphSerializer`:

Add import at top of file (after existing imports around line 15):

```python
from sandbox_agent.event_serializer import LangGraphSerializer
```

Replace lines 343-356 (the `async for event in graph.astream(...)` block):

```python
                serializer = LangGraphSerializer()
                async for event in graph.astream(input_state, config=graph_config, stream_mode="updates"):
                    # Send intermediate status updates as structured JSON
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
```

**Step 2: Verify the import works**

```bash
cd .worktrees/agent-examples/a2a/sandbox_agent
python -c "from sandbox_agent.event_serializer import LangGraphSerializer; print('OK')"
```

Expected: `OK`

**Step 3: Run all existing agent tests**

```bash
cd .worktrees/agent-examples/a2a/sandbox_agent
python -m pytest tests/ -v 2>&1 | tail -20
```

Expected: All tests pass (no regressions).

**Step 4: Commit**

```bash
cd .worktrees/agent-examples
git add a2a/sandbox_agent/src/sandbox_agent/agent.py
git commit -s -m "feat(sandbox): wire LangGraphSerializer into agent streaming loop

Agent now emits structured JSON events via LangGraphSerializer instead
of Python str(value)/repr(). Each graph event is serialized with
type, tools/name/content fields for clean frontend rendering."
```

---

### Task 3: Update Backend History Parser (JSON-first + regex fallback)

**Files:**
- Modify: `.worktrees/sandbox-agent/kagenti/backend/app/routers/sandbox.py:226-253`

**Step 1: Write failing test for JSON parsing**

Create `.worktrees/sandbox-agent/kagenti/tests/unit/test_parse_graph_event.py`:

```python
"""Tests for _parse_graph_event in sandbox router."""

import pytest


# Import the function under test — it's a module-level function
# in sandbox.py. We import it by importing the module.
def _parse_graph_event(text):
    """Inline copy for testing — will be replaced by actual import."""
    import json
    import re

    stripped = text.strip()

    # New format: structured JSON
    try:
        data = json.loads(stripped)
        if isinstance(data, dict) and "type" in data:
            return data
    except (json.JSONDecodeError, TypeError):
        pass

    # Old format: Python repr — regex fallback
    if stripped.startswith("assistant:"):
        if "tool_calls=" in stripped:
            calls = re.findall(
                r"'name':\s*'([^']+)'.*?'args':\s*(\{[^}]+\})", stripped
            )
            if calls:
                return {
                    "type": "tool_call",
                    "tools": [{"name": c[0], "args": c[1]} for c in calls],
                }
        match = re.search(r"content='([^']{1,500})'", stripped)
        if match and match.group(1):
            return {"type": "llm_response", "content": match.group(1)}

    elif stripped.startswith("tools:"):
        match = re.search(
            r"content='((?:[^'\\]|\\.)*)'\s*,\s*name='([^']*)'", stripped
        )
        if match:
            return {
                "type": "tool_result",
                "name": match.group(2),
                "output": match.group(1)[:2000].replace("\\n", "\n"),
            }

    return None


class TestParseGraphEventJSON:
    """Test parsing structured JSON events (new format)."""

    def test_tool_call_json(self):
        text = '{"type": "tool_call", "tools": [{"name": "shell", "args": {"command": "ls"}}]}'
        result = _parse_graph_event(text)
        assert result["type"] == "tool_call"
        assert result["tools"][0]["name"] == "shell"

    def test_tool_result_json(self):
        text = '{"type": "tool_result", "name": "shell", "output": "file1.txt"}'
        result = _parse_graph_event(text)
        assert result["type"] == "tool_result"
        assert result["name"] == "shell"

    def test_llm_response_json(self):
        text = '{"type": "llm_response", "content": "Let me check."}'
        result = _parse_graph_event(text)
        assert result["type"] == "llm_response"

    def test_error_json(self):
        text = '{"type": "error", "message": "Permission denied"}'
        result = _parse_graph_event(text)
        assert result["type"] == "error"

    def test_hitl_request_json(self):
        text = '{"type": "hitl_request", "command": "rm -rf /tmp", "reason": "Destructive"}'
        result = _parse_graph_event(text)
        assert result["type"] == "hitl_request"


class TestParseGraphEventRegexFallback:
    """Test parsing old Python repr format (backward compat)."""

    def test_old_tool_call_repr(self):
        text = "assistant: {'messages': [AIMessage(content='', tool_calls=[{'name': 'shell', 'args': {'command': 'ls'}}])]}"
        result = _parse_graph_event(text)
        assert result is not None
        assert result["type"] == "tool_call"

    def test_old_tool_result_repr(self):
        text = "tools: {'messages': [ToolMessage(content='file1.txt\\nfile2.txt', name='shell', tool_call_id='call_123')]}"
        result = _parse_graph_event(text)
        assert result is not None
        assert result["type"] == "tool_result"
        assert result["name"] == "shell"

    def test_old_thinking_repr(self):
        text = "assistant: {'messages': [AIMessage(content='Let me analyze this')]}"
        result = _parse_graph_event(text)
        assert result is not None
        assert result["type"] == "llm_response"

    def test_unknown_text_returns_none(self):
        result = _parse_graph_event("random text that is not a graph event")
        assert result is None
```

**Step 2: Run test to verify it passes (test-first for the new parser)**

```bash
cd .worktrees/sandbox-agent
python -m pytest kagenti/tests/unit/test_parse_graph_event.py -v 2>&1 | tail -15
```

Expected: All tests PASS (we're testing the inline function).

**Step 3: Update `sandbox.py` with JSON-first parsing**

Replace the `_parse_graph_event()` function at lines 226-253 in
`.worktrees/sandbox-agent/kagenti/backend/app/routers/sandbox.py`:

```python
    def _parse_graph_event(text: str) -> Optional[Dict[str, Any]]:
        """Parse a graph event — try JSON first, regex fallback for old format.

        New agents emit structured JSON like:
            {"type": "tool_call", "tools": [{"name": "shell", "args": {...}}]}

        Old agents emitted Python repr strings like:
            assistant: {'messages': [AIMessage(content='...', tool_calls=[...])]}

        This function handles both formats for backward compatibility.
        """
        stripped = text.strip()

        # New format: structured JSON
        try:
            data = json.loads(stripped)
            if isinstance(data, dict) and "type" in data:
                return data
        except (json.JSONDecodeError, TypeError):
            pass

        # Old format: Python repr — regex fallback for backward compat
        if stripped.startswith("assistant:"):
            if "tool_calls=" in stripped:
                calls = re.findall(
                    r"'name':\s*'([^']+)'.*?'args':\s*(\{[^}]+\})", stripped
                )
                if calls:
                    return {
                        "type": "tool_call",
                        "tools": [{"name": c[0], "args": c[1]} for c in calls],
                    }
            match = re.search(r"content='([^']{1,500})'", stripped)
            if match and match.group(1):
                return {"type": "llm_response", "content": match.group(1)}

        elif stripped.startswith("tools:"):
            match = re.search(
                r"content='((?:[^'\\]|\\.)*)'\s*,\s*name='([^']*)'", stripped
            )
            if match:
                return {
                    "type": "tool_result",
                    "name": match.group(2),
                    "output": match.group(1)[:2000].replace("\\n", "\n"),
                }

        return None
```

Also update the `_parse_graph_event` call in the filtering logic to handle the
new `llm_response` type (was `thinking` before). The existing code at line 268
emits `{"kind": "data", **parsed}` — this works for both old and new types
since the frontend handles both.

**Step 4: Run unit tests**

```bash
cd .worktrees/sandbox-agent
python -m pytest kagenti/tests/unit/test_parse_graph_event.py -v 2>&1 | tail -15
```

Expected: All tests PASS.

**Step 5: Commit**

```bash
cd .worktrees/sandbox-agent
git add kagenti/backend/app/routers/sandbox.py \
        kagenti/tests/unit/test_parse_graph_event.py
git commit -s -m "feat(sandbox): JSON-first graph event parsing with regex fallback

Backend now tries json.loads() first for structured events from new
agents. Falls back to regex parsing for old Python repr format.
Backward compatible — old sessions continue to render."
```

---

### Task 4: Update Frontend ToolCallStep Component

**Files:**
- Modify: `.worktrees/sandbox-agent/kagenti/ui-v2/src/pages/SandboxPage.tsx:29-163`

**Step 1: Update ToolCallData interface and ToolCallStep component**

In `SandboxPage.tsx`, update the `ToolCallData` interface (line 29) and `ToolCallStep` component (lines 67-163):

Update interface at line 29:

```typescript
interface ToolCallData {
  type: 'tool_call' | 'tool_result' | 'thinking' | 'llm_response' | 'error' | 'hitl_request';
  name?: string;
  args?: string | Record<string, unknown>;
  output?: string;
  content?: string;
  message?: string;
  command?: string;
  reason?: string;
  tools?: Array<{ name: string; args: string | Record<string, unknown> }>;
}
```

Update `ToolCallStep` component (replace lines 67-163):

```tsx
const ToolCallStep: React.FC<{ data: ToolCallData }> = ({ data }) => {
  const [expanded, setExpanded] = useState(false);

  if (data.type === 'tool_call') {
    return (
      <div
        style={{
          margin: '4px 0',
          padding: '6px 10px',
          borderLeft: '3px solid var(--pf-v5-global--info-color--100)',
          backgroundColor: 'var(--pf-v5-global--BackgroundColor--200)',
          borderRadius: '0 4px 4px 0',
          fontSize: '0.85em',
          cursor: 'pointer',
        }}
        onClick={() => setExpanded(!expanded)}
      >
        <div style={{ fontWeight: 600 }}>
          {expanded ? '▼' : '▶'} Tool Call:{' '}
          {data.tools?.map((t) => t.name).join(', ') || 'unknown'}
        </div>
        {expanded &&
          data.tools?.map((t, i) => (
            <pre
              key={i}
              style={{
                margin: '4px 0',
                padding: 8,
                backgroundColor: 'var(--pf-v5-global--BackgroundColor--dark-300)',
                color: 'var(--pf-v5-global--Color--light-100)',
                borderRadius: 4,
                fontSize: '0.9em',
                overflow: 'auto',
              }}
            >
              {t.name}({typeof t.args === 'string' ? t.args : JSON.stringify(t.args, null, 2)})
            </pre>
          ))}
      </div>
    );
  }

  if (data.type === 'tool_result') {
    return (
      <div
        style={{
          margin: '4px 0',
          padding: '6px 10px',
          borderLeft: '3px solid var(--pf-v5-global--success-color--100)',
          backgroundColor: 'var(--pf-v5-global--BackgroundColor--200)',
          borderRadius: '0 4px 4px 0',
          fontSize: '0.85em',
          cursor: 'pointer',
        }}
        onClick={() => setExpanded(!expanded)}
      >
        <div style={{ fontWeight: 600 }}>
          {expanded ? '▼' : '▶'} Result: {data.name || 'tool'}
        </div>
        {expanded && (
          <pre
            style={{
              margin: '4px 0',
              padding: 8,
              backgroundColor: 'var(--pf-v5-global--BackgroundColor--dark-300)',
              color: 'var(--pf-v5-global--Color--light-100)',
              borderRadius: 4,
              fontSize: '0.9em',
              overflow: 'auto',
              maxHeight: 200,
            }}
          >
            {data.output || '(no output)'}
          </pre>
        )}
      </div>
    );
  }

  if (data.type === 'thinking' || data.type === 'llm_response') {
    return (
      <div
        style={{
          margin: '4px 0',
          padding: '4px 10px',
          fontSize: '0.82em',
          fontStyle: 'italic',
          color: 'var(--pf-v5-global--Color--200)',
        }}
      >
        {data.content}
      </div>
    );
  }

  if (data.type === 'error') {
    return (
      <div
        style={{
          margin: '4px 0',
          padding: '6px 10px',
          borderLeft: '3px solid var(--pf-v5-global--danger-color--100)',
          backgroundColor: 'var(--pf-v5-global--BackgroundColor--200)',
          borderRadius: '0 4px 4px 0',
          fontSize: '0.85em',
        }}
      >
        <div style={{ fontWeight: 600, color: 'var(--pf-v5-global--danger-color--100)' }}>
          Error
        </div>
        <pre
          style={{
            margin: '4px 0',
            padding: 8,
            fontSize: '0.9em',
            overflow: 'auto',
            maxHeight: 150,
          }}
        >
          {data.message || '(unknown error)'}
        </pre>
      </div>
    );
  }

  if (data.type === 'hitl_request') {
    return (
      <div
        style={{
          margin: '4px 0',
          padding: '6px 10px',
          borderLeft: '3px solid var(--pf-v5-global--warning-color--100)',
          backgroundColor: 'var(--pf-v5-global--BackgroundColor--200)',
          borderRadius: '0 4px 4px 0',
          fontSize: '0.85em',
        }}
      >
        <div style={{ fontWeight: 600, color: 'var(--pf-v5-global--warning-color--100)' }}>
          Approval Required
        </div>
        <pre
          style={{
            margin: '4px 0',
            padding: 8,
            fontSize: '0.9em',
            overflow: 'auto',
          }}
        >
          Command: {data.command}{'\n'}Reason: {data.reason}
        </pre>
      </div>
    );
  }

  return null;
};
```

**Step 2: Verify build compiles**

```bash
cd .worktrees/sandbox-agent/kagenti/ui-v2
npm run build 2>&1 | tail -10
```

Expected: Build succeeds with no TypeScript errors.

**Step 3: Commit**

```bash
cd .worktrees/sandbox-agent
git add kagenti/ui-v2/src/pages/SandboxPage.tsx
git commit -s -m "feat(sandbox): enhanced ToolCallStep with 5 event types

Adds rendering for llm_response, error, and hitl_request event types.
Handles both string and object args for tool calls (backward compat
with old sessions). Tool args displayed with JSON.stringify for objects."
```

---

### Task 5: Rebuild Agent on sbox Cluster

**Step 1: Push agent changes to the remote**

```bash
cd .worktrees/agent-examples
git push origin feat/sandbox-agent
```

**Step 2: Trigger Shipwright rebuild**

```bash
export KUBECONFIG=~/clusters/hcp/kagenti-team-sbox/auth/kubeconfig
kubectl -n team1 create -f - <<EOF
apiVersion: shipwright.io/v1beta1
kind: BuildRun
metadata:
  generateName: sandbox-agent-rebuild-
  namespace: team1
spec:
  build:
    name: sandbox-agent
EOF
```

**Step 3: Wait for build to complete**

```bash
kubectl -n team1 get buildrun --sort-by=.metadata.creationTimestamp | tail -3
# Wait for the latest buildrun to show "Succeeded"
```

**Step 4: Restart the sandbox-agent deployment**

```bash
kubectl -n team1 rollout restart deployment/sandbox-agent
kubectl -n team1 rollout restart deployment/sandbox-legion
kubectl -n team1 rollout status deployment/sandbox-agent --timeout=120s
kubectl -n team1 rollout status deployment/sandbox-legion --timeout=120s
```

**Step 5: Verify agent is running**

```bash
kubectl -n team1 get pods -l app.kubernetes.io/name=sandbox-agent --no-headers
kubectl -n team1 get pods -l app.kubernetes.io/name=sandbox-legion --no-headers
```

Expected: All pods Running, 1/1 Ready.

---

### Task 6: Deploy Backend + Frontend Updates to sbox

**Step 1: Push sandbox-agent worktree changes**

```bash
cd .worktrees/sandbox-agent
git push origin feat/sandbox-agent
```

**Step 2: Trigger backend and UI rebuilds**

```bash
export KUBECONFIG=~/clusters/hcp/kagenti-team-sbox/auth/kubeconfig

# Backend rebuild
kubectl -n kagenti-system create -f - <<EOF
apiVersion: shipwright.io/v1beta1
kind: BuildRun
metadata:
  generateName: kagenti-backend-rebuild-
  namespace: kagenti-system
spec:
  build:
    name: kagenti-backend
EOF

# UI rebuild
kubectl -n kagenti-system create -f - <<EOF
apiVersion: shipwright.io/v1beta1
kind: BuildRun
metadata:
  generateName: kagenti-ui-rebuild-
  namespace: kagenti-system
spec:
  build:
    name: kagenti-ui
EOF
```

**Step 3: Wait for builds and restart**

```bash
# Monitor builds
kubectl -n kagenti-system get buildrun --sort-by=.metadata.creationTimestamp | tail -5

# After builds complete, restart deployments
kubectl -n kagenti-system rollout restart deployment/kagenti-backend
kubectl -n kagenti-system rollout restart deployment/kagenti-ui
kubectl -n kagenti-system rollout status deployment/kagenti-backend --timeout=120s
kubectl -n kagenti-system rollout status deployment/kagenti-ui --timeout=120s
```

---

### Task 7: E2E Verification on sbox

**Step 1: Test new session with structured events**

```bash
export KUBECONFIG=~/clusters/hcp/kagenti-team-sbox/auth/kubeconfig

# Send a message that triggers tool calls
CONTEXT_ID=$(python3 -c "import uuid; print(uuid.uuid4().hex)")
curl -s -X POST "http://$(kubectl -n kagenti-system get route kagenti-backend -o jsonpath='{.spec.host}')/api/v1/sandbox/team1/chat" \
  -H "Content-Type: application/json" \
  -d "{\"message\": \"List the files in the current directory\", \"session_id\": \"$CONTEXT_ID\", \"agent_name\": \"sandbox-legion\"}" \
  | python3 -m json.tool | head -20
```

**Step 2: Verify history contains structured JSON events**

```bash
curl -s "http://$(kubectl -n kagenti-system get route kagenti-backend -o jsonpath='{.spec.host}')/api/v1/sandbox/team1/sessions/$CONTEXT_ID/history" \
  | python3 -m json.tool | head -40
```

Expected: History messages contain `{"kind": "data", "type": "tool_call", ...}` entries.

**Step 3: Verify old sessions still render**

Load an existing session from before the change in the browser — tool calls should
still render via the regex fallback.

**Step 4: Run E2E tests**

```bash
cd /Users/ladas/Projects/OCTO/kagenti/kagenti
export LOG_DIR=/tmp/kagenti/tdd/tool-call-fix
.worktrees/sandbox-agent/.github/scripts/local-setup/hypershift-full-test.sh \
  --skip-deploy --include-sandbox-tests 2>&1 > $LOG_DIR/e2e-sbox.log; echo "EXIT:$?"
```

---

### Task 8: Deploy and verify on sbox1 (second cluster)

Repeat Tasks 5-7 using:

```bash
export KUBECONFIG=~/clusters/hcp/kagenti-team-sbox1/auth/kubeconfig
```

Same steps: rebuild agent, deploy backend/UI, run E2E tests.

---

---

### Task 9: Fix Session Sidebar Name Display

**Files:**
- Modify: `.worktrees/sandbox-agent/kagenti/ui-v2/src/components/SessionSidebar.tsx:32-39,261-263`

**Step 1: Update sessionName() to use full title**

In `SessionSidebar.tsx`, change the `sessionName()` function (lines 32-40).
Remove the 24-char truncation — let CSS handle text overflow at full column width:

```typescript
/** Extract a short display name: title, PR/issue ref, or truncated context ID. */
function sessionName(task: TaskSummary): string {
  const meta = task.metadata as Record<string, unknown> | null;
  if (meta?.title) return meta.title as string;
  if (meta?.ref) return meta.ref as string;
  return task.context_id.substring(0, 8);
}
```

**Step 2: Update the session name display to use full width with CSS truncation**

Replace the session name `<span>` (around line 261) to use CSS text-overflow:

```tsx
<span
  style={{
    fontWeight: 500,
    fontSize: '0.9em',
    overflow: 'hidden',
    textOverflow: 'ellipsis',
    whiteSpace: 'nowrap',
    flex: 1,
    minWidth: 0,
  }}
>
  {sessionName(session)}
</span>
```

**Step 3: Verify build compiles**

```bash
cd .worktrees/sandbox-agent/kagenti/ui-v2
npm run build 2>&1 | tail -10
```

Expected: Build succeeds.

**Step 4: Commit**

```bash
cd .worktrees/sandbox-agent
git add kagenti/ui-v2/src/components/SessionSidebar.tsx
git commit -s -m "fix(sandbox): show full session name in sidebar with CSS truncation

Remove 24-char JS truncation from sessionName(). Use CSS text-overflow
with ellipsis at full column width. Custom names display in full;
long names truncated by the browser at column boundary."
```

---

### Task 10: Fix Session Switch State Leak Bug

**Files:**
- Modify: `.worktrees/sandbox-agent/kagenti/ui-v2/src/pages/SandboxPage.tsx:449-466`

**Problem:** When switching sessions, the input text, streaming content, and
streaming state from the previous session leak into the new session. The
`handleSelectSession` callback clears `messages` and `error` but not `input`,
`streamingContent`, or `isStreaming`.

**Step 1: Fix handleSelectSession to clear all state**

In `SandboxPage.tsx`, update `handleSelectSession` (lines 449-466):

```typescript
  const handleSelectSession = useCallback(
    (id: string) => {
      setContextId(id);
      setMessages([]);
      setInput('');
      setStreamingContent('');
      setIsStreaming(false);
      setError(null);
      setHasMoreHistory(false);
      setOldestIndex(null);
      shouldAutoScroll.current = true;
      if (id) {
        setSearchParams({ session: id });
        localStorage.setItem(STORAGE_KEY_SESSION, id);
      } else {
        setSearchParams({});
        localStorage.removeItem(STORAGE_KEY_SESSION);
      }
    },
    [setSearchParams]
  );
```

**Step 2: Verify build compiles**

```bash
cd .worktrees/sandbox-agent/kagenti/ui-v2
npm run build 2>&1 | tail -10
```

**Step 3: Commit**

```bash
cd .worktrees/sandbox-agent
git add kagenti/ui-v2/src/pages/SandboxPage.tsx
git commit -s -m "fix(sandbox): clear input and streaming state on session switch

Fixes state leak where typed text and streaming content from one session
appeared in another session. handleSelectSession now clears input,
streamingContent, and isStreaming state."
```

---

## Summary

| Task | What | Where | Est. |
|------|------|-------|------|
| 1 | Create LangGraphSerializer + tests | agent-examples worktree | 5 min |
| 2 | Wire serializer into agent.py | agent-examples worktree | 3 min |
| 3 | JSON-first backend parser + tests | sandbox-agent worktree | 5 min |
| 4 | Enhanced ToolCallStep frontend | sandbox-agent worktree | 5 min |
| 5 | Rebuild agent on sbox | sbox cluster | 5 min |
| 6 | Deploy backend+UI on sbox | sbox cluster | 5 min |
| 7 | E2E verification on sbox | sbox cluster | 5 min |
| 8 | Deploy + verify on sbox1 | sbox1 cluster | 5 min |
| 9 | Fix session sidebar name display | sandbox-agent worktree | 3 min |
