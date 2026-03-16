# Tool Call Rendering Fix — Structured JSON Events

**Date:** 2026-02-27
**Status:** Design approved
**Clusters:** sbox (kagenti-team-sbox), sbox1 (kagenti-team-sbox1)

## Problem

The sandbox agent emits LangGraph graph events using `str(value)` (Python repr),
producing strings like:

```
assistant: {'messages': [AIMessage(content='...', tool_calls=[ToolCall(...)])]}
tools: {'messages': [ToolMessage(content='output', name='shell')]}
```

The backend uses fragile regex (`_parse_graph_event()`) to extract tool call data
from these repr strings. This breaks on multi-line args, nested dicts, and special
characters. The frontend `ToolCallStep` component exists but receives malformed data.

## Solution

### Architecture: Framework Adapter Pattern

Since Kagenti supports multiple agent frameworks (LangGraph, CrewAI, AG2), the
event serialization should be **framework-specific** through an adapter pattern.
The adapter is selected based on the agent's `kagenti.io/framework` label.

```
┌─────────────────────────────────────────────────┐
│ Agent (any framework)                           │
│   graph.astream() / crew.run() / ag2.chat()     │
│        │                                        │
│        ▼                                        │
│   FrameworkAdapter.serialize(event)              │
│   ├── LangGraphAdapter                          │
│   ├── CrewAIAdapter (future)                    │
│   └── AG2Adapter (future)                       │
│        │                                        │
│        ▼                                        │
│   Structured JSON event                         │
│   {"type": "tool_call", "tools": [...]}         │
│        │                                        │
│        ▼                                        │
│   A2A TaskStatusUpdateEvent (text part)          │
└───────────────────┬─────────────────────────────┘
                    │ SSE
                    ▼
┌─────────────────────────────────────────────────┐
│ Backend (sandbox.py)                            │
│   json.loads(text) → structured event           │
│   Fallback: regex for old repr format           │
│        │                                        │
│        ▼                                        │
│   A2A SSE → Frontend                            │
└───────────────────┬─────────────────────────────┘
                    │
                    ▼
┌─────────────────────────────────────────────────┐
│ Frontend (SandboxPage.tsx)                      │
│   ToolCallStep renders all 5 event types        │
│   - tool_call → blue expandable with args       │
│   - tool_result → green expandable with output  │
│   - llm_response → gray italic thinking         │
│   - error → red error box                       │
│   - hitl_request → orange approval card         │
└─────────────────────────────────────────────────┘
```

### Event Types (5 core types)

| Type | When | Data Fields |
|------|------|-------------|
| `tool_call` | LLM decides to call tools | `tools: [{name, args}]` |
| `tool_result` | Tool returns output | `name, output` |
| `llm_response` | LLM generates text (no tool calls) | `content` |
| `error` | Graph or tool error | `message, node?` |
| `hitl_request` | HITL approval needed | `command, reason` |

### Event JSON Format

```json
{"type": "tool_call", "tools": [{"name": "shell", "args": {"command": "ls -la"}}]}
{"type": "tool_result", "name": "shell", "output": "file1.txt\nfile2.txt"}
{"type": "llm_response", "content": "Let me check the directory structure..."}
{"type": "error", "message": "Permission denied", "node": "tools"}
{"type": "hitl_request", "command": "rm -rf /tmp", "reason": "Destructive command"}
```

## Changes

### 1. Agent: LangGraph Adapter (`agent.py`)

New module: `event_serializer.py` with framework adapter pattern:

```python
import json
from abc import ABC, abstractmethod

class FrameworkEventSerializer(ABC):
    """Base class for framework-specific event serialization."""

    @abstractmethod
    def serialize(self, key: str, value: dict) -> str:
        """Serialize a framework event into JSON string."""
        ...

class LangGraphSerializer(FrameworkEventSerializer):
    """Serialize LangGraph stream_mode='updates' events."""

    def serialize(self, key: str, value: dict) -> str:
        msgs = value.get("messages", [])
        if not msgs:
            return json.dumps({"type": "llm_response", "content": f"[{key}]"})

        msg = msgs[-1]

        if key == "assistant":
            tool_calls = getattr(msg, "tool_calls", [])
            if tool_calls:
                return json.dumps({
                    "type": "tool_call",
                    "tools": [
                        {"name": tc["name"], "args": tc.get("args", {})}
                        for tc in tool_calls
                    ],
                })
            content = getattr(msg, "content", "")
            if isinstance(content, list):
                text = " ".join(
                    b.get("text", "")
                    for b in content
                    if isinstance(b, dict) and b.get("type") == "text"
                )
            else:
                text = str(content)
            return json.dumps({"type": "llm_response", "content": text[:2000]})

        elif key == "tools":
            name = getattr(msg, "name", "unknown")
            content = getattr(msg, "content", "")
            return json.dumps({
                "type": "tool_result",
                "name": name,
                "output": str(content)[:2000],
            })

        return json.dumps({"type": "llm_response", "content": f"[{key}]"})
```

Change in `agent.py` streaming loop:

```python
# Before:
"\n".join(
    f"{key}: {str(value)[:256] + '...' if len(str(value)) > 256 else str(value)}"
    for key, value in event.items()
)

# After:
serializer = LangGraphSerializer()
"\n".join(
    serializer.serialize(key, value)
    for key, value in event.items()
)
```

### 2. Backend: JSON-first parsing (`sandbox.py`)

Replace `_parse_graph_event()`:

```python
def _parse_graph_event(text: str) -> Optional[Dict[str, Any]]:
    """Parse a graph event — try JSON first, regex fallback for old format."""
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

### 3. Frontend: Enhanced ToolCallStep (`SandboxPage.tsx`)

Update `ToolCallData` interface:

```typescript
interface ToolCallData {
  type: 'tool_call' | 'tool_result' | 'thinking' | 'llm_response' | 'error' | 'hitl_request';
  name?: string;
  args?: string;
  output?: string;
  content?: string;
  message?: string;
  command?: string;
  reason?: string;
  tools?: Array<{ name: string; args: string | Record<string, unknown> }>;
}
```

Add rendering for `llm_response`, `error`, and `hitl_request` in `ToolCallStep`:

- `llm_response` → gray italic text (same as current `thinking`)
- `error` → red-bordered expandable with error message
- `hitl_request` → orange-bordered card showing command that needs approval

## Testing Plan

1. Deploy updated agent to sbox via Shipwright rebuild
2. **New session test:** Send a message, verify events render as structured JSON
3. **Old session test:** Load existing session, verify regex fallback works
4. **Tool call test:** Ask agent to run `ls`, verify tool_call → tool_result flow
5. **LLM response test:** Ask a question that doesn't need tools
6. **Error test:** Ask agent to do something forbidden, verify error event
7. **Multi-tool test:** Ask agent to run multiple commands

## Files

| File | Location | Change |
|------|----------|--------|
| `event_serializer.py` | `.worktrees/agent-examples/a2a/sandbox_agent/src/sandbox_agent/` | New: framework adapter |
| `agent.py` | `.worktrees/agent-examples/a2a/sandbox_agent/src/sandbox_agent/` | Use serializer |
| `sandbox.py` | `.worktrees/sandbox-agent/kagenti/backend/app/routers/` | JSON-first parsing |
| `SandboxPage.tsx` | `.worktrees/sandbox-agent/kagenti/ui-v2/src/pages/` | Enhanced ToolCallStep |

## Backward Compatibility

- Old sessions with Python repr format continue to render (regex fallback)
- No data migration needed
- Frontend handles both old (`thinking`) and new (`llm_response`) types
