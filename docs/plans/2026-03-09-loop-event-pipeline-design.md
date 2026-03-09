# Loop Event Pipeline — Complete Tool Call Visibility

> **Date:** 2026-03-09
> **Status:** Draft — awaiting approval
> **Scope:** Agent serializer + AgentLoopCard rendering

---

## Problem

Some agent sessions show loop cards with no tool call details. The event serializer emits `tool_call`/`tool_result` events only when the LLM uses **structured tool calling** (`response.tool_calls`). When the LLM uses **text-based tool invocation** (Llama 4 Scout via LiteLLM), the executor parses tools from text via `parse_text_tool_calls()` but the serializer never emits events for those.

Additionally, the AgentLoopCard rendering could show richer information: fuller descriptions, timing per step, and clearer tool call/result pairing.

## Current Pipeline

```
executor_node returns AIMessage
  ├─ response.tool_calls populated? → serializer emits tool_call event ✓
  └─ text-parsed tools? → serializer emits executor_step only, no tool_call ✗

ToolNode returns ToolMessage
  └─ serializer emits tool_result event ✓ (but only if tool_call was emitted first)
```

## Design

### Part 1: Serializer — Emit tool_call for text-parsed tools

**File:** `event_serializer.py` → `_serialize_executor()`

When executor_node returns state with text-parsed tool calls (tools found via `parse_text_tool_calls()` in reasoning.py), the executor should include them in the returned state so the serializer can emit `tool_call` events.

**Change in `reasoning.py` executor_node (~line 500):**
- After `parse_text_tool_calls()` extracts tools from text, include them in the return dict as `parsed_tools: [{name, args}]`
- The serializer checks for both `response.tool_calls` (structured) and `state.parsed_tools` (text-parsed)

**Change in `event_serializer.py` `_serialize_executor()`:**
- After emitting `executor_step`, check if `parsed_tools` exists in the state update
- If present, emit a `tool_call` event with the parsed tools (same format as structured calls)

**Change in `event_serializer.py` `_serialize_tools()`:**
- When text-based tool results come back (not via ToolMessage but via executor's own execution), emit `tool_result` events for them

### Part 2: Richer executor_step description

**File:** `event_schema.py` + `event_serializer.py`

Currently `executor_step.description` is truncated to 200 chars. Increase to 500 chars and add a `reasoning` field for the full LLM text (up to 2000 chars, matching reporter_output limit).

**New fields on executor_step:**
- `reasoning: str` — full LLM response text (up to 2000 chars)
- `duration_ms: int` — step execution time (if available)

### Part 3: AgentLoopCard rendering enhancements

**Files:** `LoopDetail.tsx`, `AgentLoopCard.tsx`

| Enhancement | Description |
|------------|-------------|
| **Expandable reasoning** | Show full executor reasoning text in collapsible block |
| **Tool call timing** | Show duration between tool_call and tool_result if available |
| **Model badge per step** | Show which model was used for each LLM step |
| **Step status icons** | Clearer done/running/failed icons per step |
| **Token display** | Show tokens inline with each step header |

### Part 4: History rendering parity

Ensure `loadInitialHistory` in `SandboxPage.tsx` reconstructs all new fields:
- `reasoning` text on executor steps
- Tool calls from both structured and text-parsed sources
- Duration data (when available)

## Data Flow After Fix

```
executor_node
  ├─ structured tool_calls → tool_call event (name, args) ✓ (existing)
  ├─ text-parsed tools → tool_call event (name, args) ✓ (NEW)
  └─ executor_step with full reasoning ✓ (ENHANCED)

ToolNode / executor's own execution
  └─ tool_result event (name, output) ✓ (both paths)
```

## Files to Change

| File | Worktree | Changes |
|------|----------|---------|
| `reasoning.py` | agent-examples | Include parsed_tools in executor return |
| `event_serializer.py` | agent-examples | Emit tool_call for parsed_tools |
| `event_schema.py` | agent-examples | Add reasoning field to ExecutorStep |
| `LoopDetail.tsx` | sandbox-agent | Expandable reasoning, model badges |
| `AgentLoopCard.tsx` | sandbox-agent | Enhanced step rendering |
| `agentLoop.ts` | sandbox-agent | Add reasoning field to AgentLoopStep |
| `SandboxPage.tsx` | sandbox-agent | Handle new fields in SSE + history |

## Testing

- Existing consistency test verifies streaming = historical parity
- Variant tests (4 agents) verify tool calls appear in loop cards
- Add assertion: loop cards must have `toolCalls.length > 0` when agent uses tools

## Non-goals

- Token budget UI (already working via budget events)
- Sub-session loop rendering (separate feature)
- Looper message queuing (next phase)
