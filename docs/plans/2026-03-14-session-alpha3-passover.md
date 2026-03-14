# Session Alpha-3 (2026-03-14) Passover — Streaming Architecture & Event Pipeline

> **Date:** 2026-03-14
> **Cluster:** sbox42 (KUBECONFIG=/tmp/kagenti/sbox42-kubeconfig)
> **Worktrees:** `.worktrees/sandbox-agent` (kagenti), `.worktrees/agent-examples` (agent code)
> **Branch:** `feat/sandbox-agent` (both repos)
> **RCA Test:** Passing (1.0m, quality 5/5, 29K tokens)
> **Unit Tests:** 152+ passing across 5 test files
> **Previous:** session-gamma-passover.md, session-gamma2-passover.md

## Session Summary

Continuation of Gamma sessions — focused on:
1. Two-phase executor (reasoning + tool call)
2. Event pipeline analysis (A2A → backend → UI)
3. Persistence debugging (incremental persist not firing)
4. `SANDBOX_FORCE_TOOL_CHOICE` env var wiring
5. Bound tools in prompt inspector
6. System prompt deduplication fix

---

## Event Pipeline Architecture

### Data Flow: Agent → Backend → UI

```
┌──────────────────────────────────────────────────────────────┐
│  AGENT (graph.py + reasoning.py + event_serializer.py)       │
│                                                               │
│  LangGraph astream(stream_mode="updates")                    │
│    → {"executor": {"messages": [AIMessage(...)]}}            │
│                                                               │
│  LangGraphSerializer.serialize("executor", value)            │
│    → JSON lines (FREE-FORMAT — our schema):                  │
│      {"type":"micro_reasoning","loop_id":"abc",              │
│       "node_visit":4,"sub_index":0,"event_index":12,...}     │
│      {"type":"tool_call","call_id":"tc1",...}                │
│                                                               │
│  A2A TaskStatusUpdateEvent (PRESCRIBED — A2A protocol):      │
│    status.message.parts[0].text = JSON lines above           │
└─────────────────────────┬────────────────────────────────────┘
                          │ SSE (HTTP streaming)
                          ▼
┌──────────────────────────────────────────────────────────────┐
│  BACKEND (sandbox.py)                                        │
│                                                               │
│  1. Receive SSE line: "data: {A2A JSON-RPC envelope}"        │
│  2. Parse envelope → extract status.message.parts[0].text    │
│  3. Split text by \n → json.loads() each JSON line           │
│  4. Filter: skip legacy types (plan, plan_step, reflection)  │
│  5. Forward to UI: SSE {"loop_id":"abc","loop_event":{...}}  │
│  6. Accumulate: loop_events.append(parsed_event)             │
│  7. Persist: _persist_loop_events_incremental()              │
│     → UPDATE tasks SET metadata.loop_events = $1 WHERE id=$2 │
│  8. Finally: spawn _persist_and_recover() background task    │
└─────────────────────────┬────────────────────────────────────┘
                          │ SSE to UI (live) / REST on reload
                          ▼
┌──────────────────────────────────────────────────────────────┐
│  UI (SandboxPage.tsx + loopBuilder.ts)                       │
│                                                               │
│  LIVE PATH:                                                   │
│    SSE handler → data.loop_event as LoopEvent                │
│    → applyLoopEvent(existingLoop, event) per event           │
│    → React state update → AgentLoopCard render               │
│                                                               │
│  RELOAD PATH:                                                 │
│    GET /sessions/{id} → response.loop_events from DB         │
│    → buildAgentLoops(events)                                 │
│    → sort by event_index → replay via applyLoopEvent()       │
│    → Map<string, AgentLoop> → render                         │
│                                                               │
│  BOTH paths use the SAME applyLoopEvent() reducer            │
│  → guaranteed streaming/history parity                       │
└──────────────────────────────────────────────────────────────┘
```

### Format Boundaries

| Stage | Format | Free vs Prescribed |
|-------|--------|-------------------|
| LangGraph output | `{node_name: state_dict}` | Framework-specific |
| Serialized events | JSON lines with `loop_id`, `type`, `node_visit`, etc. | **FREE** (our schema) |
| A2A envelope | `TaskStatusUpdateEvent.message.parts[0].text` | **PRESCRIBED** (A2A protocol) |
| Backend → UI SSE | `{loop_id, loop_event: {...}}` | **HYBRID** |
| DB storage | `tasks.metadata['loop_events']` JSONB array | **FREE** |
| UI state | `AgentLoop` / `AgentLoopStep` objects | Application-specific |

### Key Parsing Points

1. **Agent → A2A**: `LangGraphSerializer` produces JSON lines, embedded in `TextPart.text`
2. **Backend parse** (sandbox.py:2179): `json.loads(msg_line)` per JSON line
3. **Backend → UI**: Loop events forwarded as SSE with `loop_event` field
4. **UI streaming**: `applyLoopEvent()` canonical reducer
5. **UI reload**: `buildAgentLoops()` sorts by `event_index`, replays events

### Event Schema (our free-format)

Every event has these common fields:
```json
{
  "type": "planner_output|executor_step|tool_call|tool_result|micro_reasoning|reflector_decision|reporter_output|step_selector|budget_update",
  "loop_id": "abc12345",      // unique per session
  "step": 1,                   // plan step (1-based)
  "node_visit": 5,             // graph node visit counter
  "sub_index": 2,              // position within node_visit
  "event_index": 42,           // global sequence number
  "model": "llama4-scout",
  "prompt_tokens": 150,
  "completion_tokens": 50
}
```

Type-specific fields:
- `executor_step`: `description`, `reasoning`, `system_prompt`, `prompt_messages`, `bound_tools`
- `tool_call`: `call_id`, `tools: [{name, args}]`
- `tool_result`: `call_id`, `name`, `output`, `status`
- `micro_reasoning`: `micro_step`, `reasoning`, `next_action`, `after_call_id`
- `planner_output`: `steps: [string]`, `iteration`, `content`
- `reflector_decision`: `decision`, `assessment`
- `reporter_output`: `content`
- `budget_update`: `tokens_used`, `tokens_budget`, `wall_clock_s`

### Node Visit Model

```
node_visit increments on node TYPE transitions only:
  router(1) → planner(2) → step_selector(3) → executor(4) → reflector(5)
                                                    ↑ ↓
                                              tools (stays 4)
  executor→tools→executor tool loop = same node_visit

UI groups by node_visit → each visit is a collapsible section
```

---

## P0: Persistence Bug — Events Lost on Reload

### Symptom
- Live streaming shows all events (60+)
- Page reload shows only 4 events (router, planner, budget, step_selector)
- Session state stuck in "working" (never reaches "completed")

### Root Cause Chain

1. **Incremental persist not firing**: `_persist_loop_events_incremental()` should fire
   on every event (threshold=1, all types are triggers). But the SSE streaming code
   path doesn't call it consistently — the `_last_persisted_count` tracking has a bug
   where it stops incrementing after the initial events.

2. **BG persist in finally block**: The `_persist_and_recover()` background task receives
   the `loop_events` list from the finally block. It attempts to write them to DB.

3. **Recovery mechanism fails**: After writing, it tries to recover by polling the agent's
   task state. But the task is stuck in "working" (never transitioned to terminal).
   Recovery polls 10 times with exponential backoff, then gives up with
   "No loop events recovered."

4. **Task state stuck**: The agent's A2A task stays in "working" because the reporter
   node's output doesn't always trigger the task state transition to "completed".

### Fix Needed

**Option A** (simplest): Fix BG persist to write `loop_events` regardless of recovery
outcome. Currently the recovery failure may prevent the final DB write.

**Option B** (proper): Fix incremental persist to fire during SSE streaming. The
`_should_persist_incrementally()` function returns True but the calling code might
not await the persist coroutine properly.

**Option C** (belt + suspenders): Both A + B.

### Debugging Steps

```bash
# Check what's persisted for a session
kubectl exec -n team1 postgres-sessions-0 -- psql -U kagenti -d sessions -c "
SELECT context_id, status::json->>'state' as state,
  CASE WHEN (metadata::jsonb->'loop_events') IS NOT NULL
  THEN jsonb_array_length(metadata::jsonb->'loop_events') ELSE 0 END as events,
  length(COALESCE(history::text,'')) as hist_len
FROM tasks WHERE context_id = '<CTX_ID>'"

# Check backend persist logs
kubectl logs deploy/kagenti-backend -n kagenti-system -c backend --tail=500 | \
  grep -E "persist|finally|BG|recover|loop_event"
```

---

## Two-Phase Executor

When `SANDBOX_FORCE_TOOL_CHOICE=1`:

```
Phase 1: Bare LLM (no tools bound) → text reasoning
  "I need to clone the repo first because the gh CLI requires
   a git context. I'll use git clone with the workspace path."

Phase 2: LLM with tool_choice="any" → structured tool call
  shell({"command": "git clone https://github.com/kagenti/kagenti.git /workspace/<ctx>/repos/kagenti"})
```

**Why bare LLM for Phase 1**: With tools bound, Llama 4 Scout always produces structured
tool_calls even with implicit auto — defeating the reasoning purpose. Bare LLM (no
`bind_tools`) forces text-only output.

**Result**: Micro-reasoning events now contain real text reasoning, not just
"Decided next action: → shell(...)".

### Token Cost

Two-phase doubles LLM calls. With 10 tool calls per step:
- Step 3: 167K tokens (20 LLM calls × ~8K per call)
- Step 4: +153K tokens
- Step 5: +250K tokens (context grows with reflection HumanMessages)

**Mitigation**: Lower `MAX_TOOL_CALLS_PER_STEP` from 10 to 5.

---

## tool_choice Experiment Results

| Mode | Structured tool_calls | Text reasoning | Works? |
|------|----------------------|----------------|--------|
| `tool_choice="any"` (required) | 100% | Never (empty content) | ✓ for tools |
| `tool_choice="auto"` (explicit) | 0% | Yes (tools as text) | ✗ |
| implicit auto (omitted) | 0% | Yes (tools as text) | ✗ |
| bare LLM (no tools) | N/A | 100% text | ✓ for reasoning |

See `docs/plans/2026-03-13-vllm-tool-choice-auto-issue.md` for the 300-call study.

---

## Commits This Session

### Agent (agent-examples repo)

| Commit | Description |
|--------|-------------|
| 7600399 | Read SANDBOX_FORCE_TOOL_CHOICE env var |
| 29f2d2f | Two-phase executor (reasoning + tool call) |
| 580184c | Phase 1 uses bare LLM (no tools) for text reasoning |
| 67043a5 | Revert to tool_choice="any" after auto experiments |
| a5cc813 | Capture bound tools in invoke_llm debug |

### UI + Backend (kagenti repo)

| Commit | Description |
|--------|-------------|
| aa9f09f4 | RCA test supports RCA_FORCE_TOOL_CHOICE=0 variant |
| 31f12726 | Bound tools section in prompt inspector |
| e412ec69 | Backend persist threshold=1, all event types |

---

## Remaining Issues

### P0: Fix event persistence (events lost on reload)
See persistence bug section above.

### P1: Backend incremental persist debugging
The `_persist_loop_events_incremental` function exists and config is correct
(threshold=1, all types), but it doesn't fire during SSE streaming.

### P2: Run both RCA test variants
- Forced tool choice (current): `RCA_AGENT_NAME=rca-agent-emptydir`
- Without force: `RCA_FORCE_TOOL_CHOICE=0 RCA_AGENT_NAME=rca-auto`

### P3: Lower MAX_TOOL_CALLS_PER_STEP
From 10 to 5 — most productive steps complete in 1-3 calls.

### P4: Context window reporting to UI
Report context window sizes (planner, executor, reflector) as part of
debug events so the UI can show how much context each node sees.

### P5: Wire reflector and reporter through invoke_llm
Currently only planner and executor use `invoke_llm`. Reflector and
reporter still use direct `llm.ainvoke()` with manual debug fields.

---

## Current A2A Usage (Design Review)

### How We Use A2A Today

The agent emits ALL serialized events as concatenated JSON lines in a SINGLE
`TextPart.text` field per graph node visit. The backend splits by `\n` and
parses each line.

```
Agent serializer output (multiple JSON lines):
  {"type":"micro_reasoning","loop_id":"abc","node_visit":4,...}
  {"type":"executor_step","loop_id":"abc","node_visit":4,...}
  {"type":"tool_call","loop_id":"abc","call_id":"tc1",...}

Wrapped in A2A TaskStatusUpdateEvent:
  {
    "status": {
      "state": "working",
      "message": {
        "role": "agent",
        "parts": [{
          "kind": "text",
          "text": "{\"type\":\"micro_reasoning\",...}\n{\"type\":\"executor_step\",...}\n{\"type\":\"tool_call\",...}"
        }]
      }
    },
    "taskId": "..."
  }
```

**Problems with current approach:**
1. Multiple events crammed into one TextPart — backend must split/parse
2. No semantic structure — everything is a text blob
3. A2A artifacts not used for file outputs
4. Task state transitions not aligned with graph node transitions
5. Single message per node visit — no granularity for individual sub-events

### Proper A2A Usage (Target Design)

Each sub-event should be a separate A2A message or part:

```
// Node visit = one TaskStatusUpdateEvent with structured parts
{
  "status": {
    "state": "working",
    "message": {
      "role": "agent",
      "parts": [
        // Part 1: human-readable reasoning (TextPart)
        {
          "kind": "text",
          "text": "I need to clone the repo first because gh CLI requires git context."
        },
        // Part 2: machine-readable event (DataPart)
        {
          "kind": "data",
          "data": {
            "type": "executor_step",
            "node_visit": 4,
            "step": 1,
            "tool_call": {
              "name": "shell",
              "args": {"command": "git clone ..."},
              "call_id": "tc1"
            }
          }
        }
      ]
    }
  }
}

// Tool result = separate TaskStatusUpdateEvent
{
  "status": {
    "state": "working",
    "message": {
      "parts": [
        {
          "kind": "data",
          "data": {
            "type": "tool_result",
            "call_id": "tc1",
            "name": "shell",
            "output": "Cloning into 'repos/kagenti'...",
            "status": "success"
          }
        }
      ]
    }
  }
}
```

### Full Agent-to-UI Data Flow (Current Implementation)

```
AGENT PROCESS
=============

  LangGraph StateGraph.astream(stream_mode="updates")
  │
  │  Yields per graph node:
  │  {"executor": {"messages": [AIMessage(content="", tool_calls=[...])],
  │                "current_step": 0, "_tool_call_count": 1, ...}}
  │
  ▼
  LangGraphSerializer.serialize(key="executor", value={...})
  │
  │  Produces JSON lines (our free-format schema):
  │  Line 1: {"type":"micro_reasoning","loop_id":"d042","node_visit":4,
  │           "sub_index":0,"event_index":12,"step":1,"micro_step":1,
  │           "reasoning":"I need to clone...","model":"llama4-scout",
  │           "prompt_tokens":2365,"completion_tokens":42,
  │           "system_prompt":"WORKSPACE...","prompt_messages":[...]}
  │  Line 2: {"type":"executor_step","loop_id":"d042","node_visit":4,
  │           "sub_index":1,"event_index":13,"step":1,
  │           "description":"Clone repo","plan_step":0}
  │  Line 3: {"type":"plan_step",...}  ← legacy alias, same event_index
  │  Line 4: {"type":"tool_call","loop_id":"d042","node_visit":4,
  │           "sub_index":2,"event_index":14,"step":1,
  │           "call_id":"chatcmpl-tool-abc123",
  │           "tools":[{"name":"shell","args":{"command":"git clone..."}}]}
  │  Line 5: {"type":"budget_update","tokens_used":4730,...}
  │
  ▼
  A2A TaskUpdater.update_status(TaskState.working, message)
  │
  │  Wraps in A2A envelope:
  │  TaskStatusUpdateEvent {
  │    status: {
  │      state: "working",
  │      message: {
  │        role: "agent",
  │        parts: [{
  │          kind: "text",
  │          text: "line1\nline2\nline3\nline4\nline5"  ← all lines concatenated
  │        }],
  │        contextId: "a26c7b13...",
  │        taskId: "646ebd32..."
  │      }
  │    }
  │  }
  │
  ▼
  A2A server SSE stream
  │
  │  HTTP SSE format:
  │  data: {"jsonrpc":"2.0","id":"...","result":{
  │    "id":"646ebd32...","status":{"state":"working","message":{...}},
  │    "contextId":"a26c7b13..."
  │  }}
  │
  ═══════════════════════════════════════════════════════════════
                    HTTP SSE (agent:8000 → backend:8000)
  ═══════════════════════════════════════════════════════════════
  │
  ▼

BACKEND PROCESS (sandbox.py)
============================

  SSE line receiver (async for line in response.aiter_lines())
  │
  │  1. Strip "data: " prefix
  │  2. json.loads() → A2A JSON-RPC result
  │  3. Extract status.message.parts[0].text
  │
  ▼
  Loop event parser
  │
  │  1. Split text by "\n" → msg_lines[]
  │  2. For each line: json.loads(line) → parsed event dict
  │  3. Check: "loop_id" in parsed? → it's a loop event
  │  4. Filter: skip legacy types {"plan","plan_step","reflection"}
  │  5. Accumulate: loop_events.append(parsed)
  │
  ▼                                          ▼
  Forward to UI (SSE)                        Persist to DB
  │                                          │
  │  yield f"data: {json.dumps({            │  _persist_loop_events_incremental()
  │    'session_id': ctx_id,                 │  UPDATE tasks SET metadata =
  │    'loop_id': parsed['loop_id'],         │    jsonb_set(metadata, '{loop_events}',
  │    'loop_event': parsed,                 │    $events::jsonb)
  │    'username': owner,                    │  WHERE id = $task_id
  │  })}\n\n"                                │
  │                                          │  ❌ BUG: not firing during SSE
  │                                          │  ✓ BG persist in finally block
  │                                          │
  ═══════════════════════════════════════════════════════════════
                    HTTP SSE (backend → browser)
  ═══════════════════════════════════════════════════════════════
  │
  ▼

UI PROCESS (SandboxPage.tsx + loopBuilder.ts)
=============================================

  SSE handler (fetch with ReadableStream)
  │
  │  Parse: data = JSON.parse(line.slice(6))
  │  Extract: evt = data.loop_event as LoopEvent
  │
  ▼
  applyLoopEvent(existingLoop, evt)  ← CANONICAL REDUCER
  │
  │  Groups by node_visit (not step):
  │  │
  │  ├─ "planner_output" / "replanner_output"
  │  │   → update loop.plan, loop.status = 'planning'
  │  │   → create step with nodeType='planner'
  │  │
  │  ├─ "step_selector"
  │  │   → update loop.currentStep
  │  │   → create step with nodeType='planner'
  │  │
  │  ├─ "executor_step"
  │  │   → findOrCreateStep(nv) with nodeType='executor'
  │  │   → update description, model, tokens, systemPrompt
  │  │
  │  ├─ "tool_call"
  │  │   → findOrCreateStep(nv) → step.toolCalls.push(...)
  │  │
  │  ├─ "tool_result"
  │  │   → findOrCreateStep(nv) → step.toolResults.push(...)
  │  │
  │  ├─ "micro_reasoning"
  │  │   → findOrCreateStep(nv) → step.microReasonings.push(...)
  │  │
  │  ├─ "reflector_decision"
  │  │   → create step with nodeType='reflector'
  │  │   → update loop.reflectorDecision
  │  │
  │  ├─ "reporter_output"
  │  │   → set loop.finalAnswer, loop.status = 'done'
  │  │
  │  └─ "budget_update"
  │      → update loop.budget
  │
  ▼
  React state: Map<string, AgentLoop>
  │
  ▼
  AgentLoopCard → CollapsibleStepSection → StepSection
  │
  │  Renders:
  │  ┌─────────────────────────────────────────────────┐
  │  │ Plan (always visible):                          │
  │  │  1. ✓ Clone repo                               │
  │  │  2. → List failures (current)                   │
  │  │  3.   Download logs                             │
  │  │                                                  │
  │  │ LoopSummaryBar: 5 steps · [49]                  │
  │  │                                                  │
  │  │ ▶ [4] Step 1/5 executor ✓ 2 tools, 1 reasoning │
  │  │ ▶ [5] reflector ✓ continue                      │
  │  │ ▶ [7] Step 2/5 executor ⏳ 1 tool, 1 reasoning │
  │  └─────────────────────────────────────────────────┘
  │
  │  Expanded CollapsibleStepSection:
  │  ┌─────────────────────────────────────────────────┐
  │  │ ▼ [4] Step 1/5 executor ✓ 2 tools, 1 success   │
  │  │ │                                                │
  │  │ │  Micro-reasoning 1 (2,365 tokens)     [Prompt]│
  │  │ │  "I need to clone the repo because..."        │
  │  │ │                                                │
  │  │ │  ▶ Tool Call: shell                            │
  │  │ │    git clone .../kagenti.git /workspace/.../   │
  │  │ │  ✓ Result: shell                               │
  │  │ │    Cloning into 'repos/kagenti'...             │
  │  │ │                                                │
  │  │ │  Micro-reasoning 2 (2,864 tokens)     [Prompt]│
  │  │ │  "Clone successful. Step complete."            │
  │  │ │                                                │
  │  │ │  [Prompt Inspector: System Prompt |            │
  │  │ │   Bound Tools (7) | Input Messages (4) |      │
  │  │ │   LLM Response]                               │
  │  │ └                                                │
  │  └─────────────────────────────────────────────────┘

  RELOAD PATH (page refresh):
  │
  │  GET /api/v1/sandbox/{ns}/sessions/{ctx_id}
  │  → response.loop_events[] from DB (tasks.metadata.loop_events)
  │  → buildAgentLoops(events)
  │     → sort by event_index
  │     → replay each via applyLoopEvent() ← SAME REDUCER
  │  → identical AgentLoop state as live streaming
```

### Context Windows (What Each Node Sees)

```
PLANNER (build_planner_context):
┌──────────────────────────────────────────────┐
│ SystemMessage: WORKSPACE_PREAMBLE + PLANNER  │
│ HumanMessage: "Analyze CI failures PR #860"  │
│ ToolMessage: "cloned OK" (last few results)  │
│                                               │
│ NO: own previous AIMessages (prevents dedup)  │
│ NO: executor/reflector messages               │
└──────────────────────────────────────────────┘

EXECUTOR — Phase 1 (bare LLM, no tools):
┌──────────────────────────────────────────────┐
│ SystemMessage: WORKSPACE_PREAMBLE + EXECUTOR │
│ HumanMessage: "Execute step 1: Clone repo"  │
│ AIMessage: tool_call(shell(git clone ...))   │ ← from state
│ ToolMessage: "Cloning into 'repos/kagenti'"  │ ← from state
│ HumanMessage: "Tool 'shell' call 1 OK.       │ ← injected reflection
│   Goal: 'Clone repo'. If ACHIEVED → stop."   │
│                                               │
│ NO: planner AIMessage (stopped at boundary)   │
│ NO: messages from other steps                 │
└──────────────────────────────────────────────┘

EXECUTOR — Phase 2 (tool_choice="any"):
┌──────────────────────────────────────────────┐
│ [same as Phase 1 context, plus:]             │
│ AIMessage: "I need to list failures next..." │ ← Phase 1 reasoning
│ HumanMessage: "Now call exactly ONE tool."   │
└──────────────────────────────────────────────┘

REFLECTOR (build_reflector_context):
┌──────────────────────────────────────────────┐
│ SystemMessage: WORKSPACE_PREAMBLE + REFLECTOR│
│ AIMessage: tool_call(shell(gh run list))     │ ← last 3 pairs
│ ToolMessage: "completed  failure  feat..."   │
│ AIMessage: tool_call(shell(gh run view))     │
│ ToolMessage: "STDERR: HTTP 410..."           │
│                                               │
│ NO: planner AIMessage (filtered: no tool_calls)
│ NO: HumanMessages (filtered)                  │
│ NO: messages older than 3 AI→Tool pairs       │
└──────────────────────────────────────────────┘

REPORTER (full history — intentional):
┌──────────────────────────────────────────────┐
│ SystemMessage: REPORTER prompt               │
│ [all messages from state["messages"]]        │
│   — filtered only for dedup sentinels        │
└──────────────────────────────────────────────┘
```

### invoke_llm Wrapper (Guarantees)

```python
response, capture = await invoke_llm(
    llm, messages,
    node="executor",
    session_id=state.get("context_id", ""),
    workspace_path=state.get("workspace_path", "/workspace"),
)

# What invoke_llm does:
# 1. Injects WORKSPACE_PREAMBLE into first SystemMessage
# 2. Calls llm.ainvoke(messages) — tools come from bind_tools, NOT messages
# 3. Captures EXACT messages sent + response received
# 4. Extracts bound_tools from llm.kwargs["tools"]
# 5. Returns (response, LLMCallCapture)
#
# LLMCallCapture provides:
#   .debug_fields() → {_system_prompt, _prompt_messages, _llm_response, _bound_tools}
#   .token_fields() → {model, prompt_tokens, completion_tokens}
#   .messages      → exact list sent to ainvoke (with preamble)
#   .bound_tools   → tool schemas from bind_tools
#
# Debug fields are CONDITIONAL on SANDBOX_DEBUG_PROMPTS env var
# Token fields are ALWAYS included
```

---

## How to Continue

```bash
export KUBECONFIG=/tmp/kagenti/sbox42-kubeconfig
export LOG_DIR=/tmp/kagenti/tdd/ui-sbox42
mkdir -p $LOG_DIR

# Agent code
cd .worktrees/agent-examples
git add -u && git commit -s -m "fix(agent): ..." && git push
oc -n team1 start-build sandbox-agent
oc -n team1 rollout restart deploy/rca-agent-emptydir

# UI code
cd .worktrees/sandbox-agent/kagenti/ui-v2
git add -u && git commit -s -m "fix(ui): ..." && git push
oc -n kagenti-system start-build kagenti-ui
oc -n kagenti-system rollout restart deploy/kagenti-ui

# Backend code (same repo as UI)
oc -n kagenti-system start-build kagenti-backend
oc -n kagenti-system rollout restart deploy/kagenti-backend

# Test (with forced tools — default)
RCA_SKIP_DEPLOY=1 RCA_AGENT_NAME=rca-agent-emptydir \
  npx playwright test e2e/agent-rca-workflow.spec.ts --timeout=600000

# Test (without forced tools — via wizard)
RCA_FORCE_TOOL_CHOICE=0 RCA_AGENT_NAME=rca-auto \
  npx playwright test e2e/agent-rca-workflow.spec.ts --timeout=600000
```
