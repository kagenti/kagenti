# Loop Event Pipeline Design — Streaming & Historical Rendering Parity

> **Date:** 2026-03-09
> **Status:** Draft — iterating with live testing on sbox42
> **Goal:** AgentLoopCard renders identically during SSE streaming and after page reload from history

---

## 1. Problem Statement

The sandbox agent UI has two rendering paths for agent reasoning:

1. **Streaming** — SSE events arrive in real-time, the frontend builds `AgentLoop` state incrementally
2. **Historical** — On page reload, the backend returns persisted `loop_events` from the DB, the frontend reconstructs `AgentLoop` from that array

These two paths produce **different results**:
- Streaming sometimes shows flat text blocks instead of AgentLoopCards (event detection fails)
- Historical shows wrong/incomplete content (e.g., "Respond to the user" as the plan)
- Some events visible during streaming disappear after reload
- The planner step shows the last replan instead of the original plan

**Root cause:** The pipeline has 5 transformation stages with no shared contract or logging, making it impossible to tell where data is lost or malformed.

---

## 2. Architecture Overview

```
                    STANDARD A2A PROTOCOL
                    =====================

  +-----------+     JSON-RPC 2.0        +-----------+
  |  Backend  | ----message/stream----> |   Agent   |
  |  (proxy)  |                         | (sandbox) |
  |           | <---SSE stream--------- |           |
  +-----------+                         +-----------+
       |                                      |
       |  OUR EXTENSION:                      |  OUR EXTENSION:
       |  Parse loop events                   |  Serialize LangGraph
       |  from message text                   |  events as JSON lines
       |  and forward with                    |  inside A2A message
       |  loop_id at top level                |  text parts
       |                                      |
       v                                      v
  +-----------+                         +-----------+
  | Frontend  |                         | LangGraph |
  | AgentLoop |                         | Serializer|
  | Cards     |                         |           |
  +-----------+                         +-----------+
```

### What A2A Provides (Standard Protocol)

A2A (Agent-to-Agent) is Google's protocol for agent communication. It defines:

- **JSON-RPC 2.0** request/response over HTTP
- **SSE streaming** for long-running tasks
- **Task lifecycle**: `working` -> `completed` / `failed` / `input_required`
- **Message structure**: role + parts (text, file, data)

A2A does NOT provide:
- Any concept of "reasoning steps" or "plan-execute-reflect" loops
- Tool call/result visibility
- Token usage or iteration tracking

### What We Add (Kagenti Extension)

We embed structured JSON events inside the A2A `message.parts[0].text` field to expose LangGraph's internal reasoning loop to the UI. This is our custom extension layer.

---

## 3. The Five Stages — Detailed Data Flow

### Stage 1: LangGraph Execution -> Event Serialization

**File:** `agent-examples/a2a/sandbox_agent/src/sandbox_agent/event_serializer.py`

LangGraph emits framework events as the graph executes nodes. Each event is a dict keyed by node name:

```python
# LangGraph stream event examples
{"planner": {"plan": ["Step 1", "Step 2"], "messages": [AIMessage(...)], "model": "llama-4-scout", ...}}
{"executor": {"messages": [AIMessage(content="...", tool_calls=[...])], ...}}
{"tools": {"messages": [ToolMessage(content="result...", name="shell")]}}
{"reflector": {"done": False, "current_step": 1, ...}}
{"reporter": {"final_answer": "Here is the result...", ...}}
```

The `LangGraphSerializer` converts each event to one or more JSON lines:

```python
# Input: LangGraph event
event = {"planner": {"plan": ["Clone repo", "Run tests"], "model": "llama-4-scout", ...}}

# Output: JSON lines (newline-separated)
'{"type":"planner_output","loop_id":"a1b2c3d4","steps":["Clone repo","Run tests"],"iteration":1,"content":"Planning...","model":"llama-4-scout","prompt_tokens":1200,"completion_tokens":300}\n{"type":"plan","loop_id":"a1b2c3d4","steps":["Clone repo","Run tests"],...}'
```

**Key fields added by serializer:**

| Field | Source | Purpose |
|-------|--------|---------|
| `loop_id` | UUID generated once per serializer instance | Groups all events in one reasoning loop |
| `type` | Node name mapping | Identifies event kind for rendering |
| `step` | Tracked by serializer (`_step_index`) | Associates tools with plan steps |
| `iteration` | From graph state | Tracks plan-execute-reflect cycles |
| `prompt_tokens`, `completion_tokens` | From LLM response metadata | Token accounting |
| `reasoning` | First 2000 chars of LLM output | Executor's thinking process |

**Event types emitted:**

| Type | Node | Legacy Alias | Purpose |
|------|------|-------------|---------|
| `planner_output` | planner | `plan` | Plan steps array, iteration |
| `executor_step` | executor | `plan_step` | Step description, reasoning |
| `tool_call` | executor | -- | Tool name + args (from AIMessage.tool_calls) |
| `tool_result` | tools | -- | Tool output (from ToolMessage) |
| `reflector_decision` | reflector | `reflection` | Decision: continue/replan/done/hitl |
| `reporter_output` | reporter | -- | Final answer text |
| `budget` | budget check | -- | Token/iteration counts |

**IMPORTANT:** Both new types AND legacy aliases are emitted in every event. Legacy types exist for backward compatibility with older frontends.

### Stage 2: A2A SDK Wrapping

**Files:**
- `a2a/server/tasks/task_updater.py` (SDK internal)
- `sandbox_agent/agent.py` lines 430-450

The serialized JSON lines are wrapped in an A2A `TaskStatusUpdateEvent`:

```python
# Agent code (agent.py ~line 440)
serialized_lines = serializer.serialize(node_name, node_value)
# serialized_lines = "line1_json\nline2_json\n..."

message = Message(
    role=Role.agent,
    parts=[TextPart(kind="text", text=serialized_lines)],
    context_id=session_id,
    task_id=task_id,
    message_id=uuid4(),
)

await task_updater.update_status(TaskState.working, message)
```

This creates a `TaskStatusUpdateEvent` and enqueues it in the A2A `EventQueue`.

**What gets sent on the wire (A2A SSE):**

```
data: {"id":"req-uuid","jsonrpc":"2.0","result":{"kind":"status-update","taskId":"task-uuid","contextId":"session-uuid","final":false,"status":{"state":"working","message":{"role":"agent","parts":[{"kind":"text","text":"{\"type\":\"planner_output\",\"loop_id\":\"a1b2c3d4\",...}\n{\"type\":\"plan\",\"loop_id\":\"a1b2c3d4\",...}"}]}}}}
```

Note the **double JSON encoding**: loop events are JSON objects serialized as a string inside the `text` field of a JSON message. The backend must parse the outer JSON-RPC envelope, extract `message.parts[0].text`, split by newlines, and parse each line as JSON again.

**Final SSE sentinel:**
```
data: [DONE]
```

### Stage 3: Backend SSE Proxy — Event Extraction & Forwarding

**File:** `kagenti/backend/app/routers/sandbox.py` lines 1550-1800

#### 3a. The A2A Request (Backend -> Agent)

The backend sends a JSON-RPC `message/stream` request:

```json
{
  "jsonrpc": "2.0",
  "id": "<uuid>",
  "method": "message/stream",
  "params": {
    "message": {
      "role": "user",
      "parts": [{"kind": "text", "text": "analyze CI failures for repo X"}],
      "messageId": "<uuid>",
      "contextId": "<session_id>",
      "metadata": {"username": "admin", "skill": "rca:ci"}
    }
  }
}
```

#### 3b. SSE Consumption & Loop Event Extraction

The backend consumes the A2A SSE response line by line:

```python
# sandbox.py ~line 1590
if line.startswith("data: "):
    data = line[6:]
    if data == "[DONE]":
        # Terminal — persist and close
        break

    chunk = json.loads(data)  # Parse JSON-RPC envelope
    result = chunk["result"]  # A2A event payload
```

For `status-update` events, the backend extracts the message text and parses JSON lines:

```python
# sandbox.py ~line 1724
status_message = _extract_text_from_parts(status["message"]["parts"])
# status_message = '{"type":"planner_output","loop_id":"a1b2c3d4",...}\n{"type":"plan",...}'

for msg_line in status_message.split("\n"):
    parsed = json.loads(msg_line)

    if isinstance(parsed, dict) and "loop_id" in parsed:
        # LOOP EVENT detected — forward to frontend with loop_id at top level
        loop_payload = {
            "session_id": session_id,
            "loop_id": parsed["loop_id"],
            "loop_event": parsed,
        }
        yield f"data: {json.dumps(loop_payload)}\n\n"

        # Persist only NEW types (skip legacy)
        if parsed["type"] not in {"plan", "plan_step", "reflection", "llm_response"}:
            loop_events.append(parsed)
```

#### 3c. What the Frontend Receives (Streaming SSE)

```
data: {"session_id":"abc","loop_id":"a1b2c3d4","loop_event":{"type":"planner_output","loop_id":"a1b2c3d4","steps":["Clone repo","Run tests"],"iteration":1,...}}

data: {"session_id":"abc","loop_id":"a1b2c3d4","loop_event":{"type":"plan","loop_id":"a1b2c3d4","steps":[...],...}}

data: {"session_id":"abc","loop_id":"a1b2c3d4","loop_event":{"type":"executor_step","loop_id":"a1b2c3d4","step":0,"description":"Clone repo",...}}

data: {"session_id":"abc","loop_id":"a1b2c3d4","loop_event":{"type":"tool_call","loop_id":"a1b2c3d4","step":0,"tools":[{"name":"shell","args":{"command":"git clone ..."}}]}}

data: {"session_id":"abc","loop_id":"a1b2c3d4","loop_event":{"type":"tool_result","loop_id":"a1b2c3d4","step":0,"name":"shell","output":"Cloning into..."}}

data: {"session_id":"abc","loop_id":"a1b2c3d4","loop_event":{"type":"reflector_decision","loop_id":"a1b2c3d4","decision":"continue","assessment":"Step completed..."}}

data: {"session_id":"abc","loop_id":"a1b2c3d4","loop_event":{"type":"reporter_output","loop_id":"a1b2c3d4","content":"Here is the analysis..."}}

data: {"session_id":"abc","done":true}
```

**KEY PROBLEM:** Legacy types (`plan`, `plan_step`, `reflection`) ARE forwarded during streaming but NOT persisted. The frontend skips them, but they pollute the SSE stream and increase the chance of subtle divergence.

#### 3d. What Gets Persisted to DB (task.metadata.loop_events)

```json
[
  {"type":"planner_output","loop_id":"a1b2c3d4","steps":["Clone repo","Run tests"],...},
  {"type":"executor_step","loop_id":"a1b2c3d4","step":0,...},
  {"type":"tool_call","loop_id":"a1b2c3d4","step":0,"tools":[...]},
  {"type":"tool_result","loop_id":"a1b2c3d4","step":0,...},
  {"type":"reflector_decision","loop_id":"a1b2c3d4","decision":"continue",...},
  {"type":"reporter_output","loop_id":"a1b2c3d4","content":"..."}
]
```

Legacy types (`plan`, `plan_step`, `reflection`, `llm_response`) are NOT in this array.

### Stage 4: History Endpoint — DB to Frontend

**File:** `kagenti/backend/app/routers/sandbox.py` lines 380-625

On page reload, the frontend calls `GET /sandbox/{ns}/sessions/{ctx}/history`:

```python
# History endpoint logic (~line 444)
all_loop_events = []
seen_event_json = set()

for row in task_rows:  # One row per user message turn
    meta = json.loads(row["metadata"])
    if meta.get("loop_events"):
        for evt in meta["loop_events"]:
            evt_json = json.dumps(evt, sort_keys=True)
            if evt_json not in seen_event_json:
                seen_event_json.add(evt_json)
                all_loop_events.append(evt)
```

**Response:**
```json
{
  "messages": [
    {"role": "user", "parts": [{"text": "analyze CI failures"}]},
    {"role": "assistant", "parts": [{"text": "Here is the analysis..."}]}
  ],
  "total": 2,
  "has_more": false,
  "loop_events": [
    {"type":"planner_output","loop_id":"a1b2c3d4",...},
    {"type":"executor_step","loop_id":"a1b2c3d4",...},
    ...
  ]
}
```

### Stage 5: Frontend — Building AgentLoop

**File:** `kagenti/ui-v2/src/pages/SandboxPage.tsx`

Two separate code paths build the same `AgentLoop` state:

#### Path A: SSE Streaming (lines 1507-1694)

```typescript
if (data.loop_id) {
  const le = data.loop_event || data;
  // Skip legacy types
  if (['plan', 'plan_step', 'reflection', 'llm_response'].includes(le.type)) continue;

  updateLoop(loopId, (loop) => {
    if (le.type === 'planner_output') {
      return { ...loop, plan: le.steps, status: 'planning', ... };
    }
    if (le.type === 'executor_step') { ... }
    if (le.type === 'tool_call') { ... }
    // ... etc
  });
}
```

#### Path B: History Reconstruction (lines 990-1150)

```typescript
for (const le of events) {
  // Skip legacy types
  if (['plan', 'plan_step', 'reflection', 'llm_response'].includes(le.type)) continue;

  const existing = loops.get(loopId) || defaultAgentLoop;
  if (le.type === 'planner_output') {
    existing.plan = le.steps;
    existing.steps.push(plannerStep);
  }
  // ... same event handling but DIFFERENT code
  loops.set(loopId, existing);
}
```

**THE CORE PROBLEM:** These are two separate implementations of the same logic. They diverge over time as fixes are applied to one but not the other.

---

## 4. Known Failure Modes

### 4.1 Format Error Crashes Agent (FIXED)

**Symptom:** "Error: Replacement index 0 out of range for positional args tuple"
**Cause:** Executor prompt template contained literal `{...}` interpreted by `.format()`.
**Fix:** Escaped braces + `_safe_format()` wrapper. Fixed in build 47.

### 4.2 Metadata Duplication Across Tasks (FIXED)

**Symptom:** All tasks in a multi-turn session share the same `loop_events`.
**Cause:** `finally` block merged metadata from ALL task rows into the latest one.
**Fix:** `stream_task_id` tracks each stream's own DB row. Writes target `WHERE id = $2`.

### 4.3 "Respond to the user" as Plan

**Symptom:** Planner step shows trivial plan instead of real multi-step plan.
**Root causes (multiple):**
1. Agent's planner outputs single-step plan for simple requests (by design)
2. Last replan was overwriting `loop.plan` (fixed: now preserved as `replans`)
3. History reconstruction may process events in wrong order
4. `planner_output.steps` might contain different data than expected

**Needs:** Logging at Stage 1 to see what `steps` the planner actually produces.

### 4.4 Flat Text Instead of AgentLoopCards

**Symptom:** Session shows raw text blocks instead of structured loop cards.
**Root causes (multiple):**
1. Backend's `_extract_text_from_parts()` returns text without `loop_id`
2. Agent emits plain text (not JSON lines) for some graph events
3. The JSON line doesn't parse correctly (truncated, malformed)
4. `status_message` contains non-JSON content mixed with JSON lines

**Needs:** Logging at Stage 3 to see the raw `status_message` before parsing.

### 4.5 Historical Loop Cards Missing Events

**Symptom:** After reload, loop cards show fewer steps than during streaming.
**Cause:** Legacy types forwarded during streaming but not persisted.
**Fix:** Filter legacy at backend before forwarding (see Section 8).

### 4.6 SSE Timeout Drops Events (FIXED)

**Symptom:** RCA agent sessions lose events mid-stream.
**Cause:** Nginx `proxy_read_timeout 300s` kills idle connections.
**Fix:** 15s keepalive pings + event recovery from agent task store.

---

## 5. Logging Strategy

To diagnose rendering parity issues, add structured logging at every stage boundary. Each log line includes `session_id` and `loop_id` for correlation.

### Stage 1: Agent Serializer

```python
# event_serializer.py — after serialize()
logger.info("SERIALIZE session=%s loop=%s type=%s step=%s",
    context_id, self._loop_id, event_type, self._step_index)
```

### Stage 2: A2A Wrapping

```python
# agent.py — after task_updater.update_status()
logger.info("A2A_EMIT session=%s lines=%d types=%s",
    context_id, len(lines), [json.loads(l).get("type") for l in lines if l.strip()])
```

### Stage 3: Backend SSE Proxy

```python
# sandbox.py — when forwarding loop event
logger.info("LOOP_FWD session=%s loop=%s type=%s step=%s persisted=%s",
    session_id, loop_id, evt_type, evt.get("step"), evt_type not in _LEGACY)

# sandbox.py — when raw status_message doesn't parse as loop event
logger.info("FLAT_FWD session=%s content_len=%d first_80=%s",
    session_id, len(status_message), status_message[:80])
```

### Stage 4: History Endpoint

```python
# sandbox.py — history endpoint
logger.info("HISTORY session=%s tasks=%d total_events=%d unique=%d types=%s",
    context_id, len(rows), total_count, len(all_loop_events),
    [e.get("type") for e in all_loop_events[:10]])
```

### Stage 5: Frontend

```typescript
// SandboxPage.tsx — SSE handler
console.log(`[sse] LOOP_RECV loop=${loopId.substring(0,8)} type=${eventType} step=${le.step ?? ''}`);

// SandboxPage.tsx — history reconstruction
console.log(`[history] LOOP_REBUILD loop=${loopId.substring(0,8)} total_events=${events.length} types=${typeList}`);
```

### Correlation

After a test run, correlate logs across stages:

```bash
SESSION=<session_id>

# What the agent serialized
kubectl logs deploy/sandbox-agent -n team1 | grep "SERIALIZE session=$SESSION"

# What the backend forwarded to frontend
kubectl logs deploy/kagenti-backend -n kagenti-system | grep "LOOP_FWD session=$SESSION"

# What the backend persisted to DB
kubectl logs deploy/kagenti-backend -n kagenti-system | grep "HISTORY session=$SESSION"

# Expected: SERIALIZE count >= LOOP_FWD count >= HISTORY events count
# (SERIALIZE includes legacy, LOOP_FWD includes legacy, HISTORY excludes legacy)
```

---

## 6. Design Principles

### P1: Single Source of Truth

The `loop_events` array persisted in `task.metadata` IS the source of truth. Both streaming and history must produce the same `AgentLoop` state from the same events.

**Rule:** If an event affects rendering, it MUST be in `loop_events`. No rendering logic should depend on transient SSE-only data.

### P2: Idempotent Reconstruction

`applyLoopEvent(loop, event) -> loop` must be a pure function. Given the same events, it produces the same `AgentLoop` regardless of incremental (streaming) or batch (history) application.

**Rule:** Extract the loop-building logic into a shared function used by BOTH paths.

### P3: No Legacy Types in Pipeline

Legacy event types (`plan`, `plan_step`, `reflection`, `llm_response`) should be:
- Still emitted by serializer (backward compat with older frontends)
- Filtered OUT at the backend before forwarding (not just at persistence)
- Never processed by the current frontend

**Rule:** Filter legacy types at the EARLIEST point (backend), not at every downstream stage.

### P4: Per-Task Isolation

Each user message creates one A2A task. Each task has its own `loop_events`. No cross-task merging.

**Rule:** `stream_task_id` identifies this stream's DB row. All writes go to `WHERE id = stream_task_id`.

### P5: Observable Pipeline

Every stage transformation must be logged with `session_id` + `loop_id` for end-to-end correlation.

**Rule:** A test failure should be diagnosable from logs alone, without reproducing.

---

## 7. Proposed Fix: Shared Loop Builder

### Current Problem

Two separate code paths build `AgentLoop`:
- SSE handler: `updateLoop()` callbacks inline (~200 lines)
- History: `loadInitialHistory()` with similar but subtly different logic (~150 lines)

These diverge over time as fixes are applied to one path but not the other.

### Solution

Extract a single `applyLoopEvent(loop: AgentLoop, event: LoopEvent): AgentLoop` function:

```typescript
// src/utils/loopBuilder.ts

export function applyLoopEvent(loop: AgentLoop, le: LoopEvent): AgentLoop {
  const et = le.type;

  // Skip legacy types
  if (['plan', 'plan_step', 'reflection', 'llm_response'].includes(et)) return loop;

  switch (et) {
    case 'planner_output': {
      const isReplan = loop.plan.length > 0;
      return {
        ...loop,
        status: 'planning',
        plan: isReplan ? loop.plan : le.steps || [],
        replans: isReplan
          ? [...loop.replans, { iteration: le.iteration, steps: le.steps, model: le.model }]
          : loop.replans,
        totalSteps: isReplan ? loop.totalSteps : (le.steps || []).length,
        iteration: le.iteration ?? loop.iteration,
        model: le.model || loop.model,
        steps: [...loop.steps, {
          index: loop.steps.length,
          description: `${isReplan ? 'Replan' : 'Plan'} (iteration ${(le.iteration ?? 0) + 1})`,
          nodeType: isReplan ? 'replanner' : 'planner',
          tokens: { prompt: le.prompt_tokens || 0, completion: le.completion_tokens || 0 },
          toolCalls: [], toolResults: [], durationMs: 0,
          status: 'done',
        }],
      };
    }
    case 'executor_step': { /* merge or create step at le.step index */ }
    case 'tool_call':     { /* append tools to step at le.step index */ }
    case 'tool_result':   { /* append result to step, mark done */ }
    case 'reflector_decision': { /* set reflection, decision, add reflector step */ }
    case 'reporter_output':    { /* set finalAnswer, status=done, add reporter step */ }
    case 'budget':             { /* update budget counters */ }
    default: return loop;
  }
}

export function buildAgentLoop(loopId: string, events: LoopEvent[]): AgentLoop {
  let loop = createDefaultAgentLoop(loopId);
  for (const evt of events) {
    loop = applyLoopEvent(loop, evt);
  }
  return loop;
}
```

**Usage in SSE handler:**
```typescript
updateLoop(loopId, (prev) => applyLoopEvent(prev, le));
```

**Usage in history reconstruction:**
```typescript
// Group events by loop_id
const eventsByLoop = new Map<string, LoopEvent[]>();
for (const evt of loop_events) {
  const arr = eventsByLoop.get(evt.loop_id) || [];
  arr.push(evt);
  eventsByLoop.set(evt.loop_id, arr);
}

// Build each loop
for (const [loopId, events] of eventsByLoop) {
  const loop = buildAgentLoop(loopId, events);
  loop.status = 'done'; // Historical loops are always done
  loop.steps.sort((a, b) => a.index - b.index);
  setAgentLoops(prev => new Map(prev).set(loopId, loop));
}
```

### Benefits

1. **Parity guaranteed** — same function, same output
2. **Testable** — unit test `applyLoopEvent` with known event sequences
3. **Single fix point** — bug fix applies to both streaming and history
4. **Auditable** — log `events.length` + `loop.steps.length` after build for validation

---

## 8. Proposed Fix: Backend Legacy Event Filtering

### Current Problem

Legacy types are forwarded to the frontend during streaming but not persisted. The frontend receives events during streaming that it will never see on reload.

### Solution

Filter legacy types at the backend BEFORE forwarding:

```python
# sandbox.py — in the loop event parsing block
_LEGACY = {"plan", "plan_step", "reflection", "llm_response"}

for msg_line in status_message.split("\n"):
    parsed = json.loads(msg_line)
    if isinstance(parsed, dict) and "loop_id" in parsed:
        evt_type = parsed.get("type", "")

        # Skip legacy types entirely — don't forward, don't persist
        if evt_type in _LEGACY:
            logger.debug("LEGACY_SKIP session=%s type=%s", session_id, evt_type)
            continue

        # Forward + persist
        loop_payload = {"session_id": sid, "loop_id": parsed["loop_id"], "loop_event": parsed}
        yield f"data: {json.dumps(loop_payload)}\n\n"
        loop_events.append(parsed)
```

---

## 9. Verification Plan

### Test 1: End-to-End Event Correlation

```bash
# 1. Send a message to sandbox-legion
# 2. Capture agent logs: SERIALIZE events
# 3. Capture backend logs: LOOP_FWD events
# 4. Capture frontend console: LOOP_RECV events
# 5. Reload page
# 6. Capture frontend console: LOOP_REBUILD events
# 7. Compare: LOOP_RECV types/counts == LOOP_REBUILD types/counts
```

### Test 2: Playwright Parity Assertion

```typescript
test('streaming and history produce identical loop cards', async ({ page }) => {
  // Send message, wait for loop card during streaming
  const streamingSnapshot = await captureLoopState(page);

  // Reload page, wait for loop card from history
  await page.reload();
  await page.waitForSelector('[data-testid="agent-loop-card"]');
  const historySnapshot = await captureLoopState(page);

  // Compare
  expect(historySnapshot.loopCount).toBe(streamingSnapshot.loopCount);
  expect(historySnapshot.stepCount).toBe(streamingSnapshot.stepCount);
  expect(historySnapshot.toolCallCount).toBe(streamingSnapshot.toolCallCount);
  expect(historySnapshot.planSteps).toEqual(streamingSnapshot.planSteps);
  expect(historySnapshot.finalAnswer).toBe(streamingSnapshot.finalAnswer);
});
```

### Test 3: Backend Pipeline Unit Test

```python
def test_forwarded_events_match_persisted():
    """Events forwarded to frontend == events persisted to DB."""
    # Mock SSE stream with known events
    # Run _stream_sandbox_response
    # Capture yielded payloads (forwarded) and loop_events list (persisted)
    assert len(forwarded) == len(persisted)
    for f, p in zip(forwarded, persisted):
        assert f["loop_event"]["type"] == p["type"]
        assert f["loop_event"]["loop_id"] == p["loop_id"]
```

---

## 10. Implementation Order

1. **Add logging** at all 5 stages (agent, backend, frontend) — enables diagnosis
2. **Extract `applyLoopEvent()`** into `src/utils/loopBuilder.ts` — shared function
3. **Refactor SSE handler** to use `applyLoopEvent()` instead of inline logic
4. **Refactor `loadInitialHistory`** to use `buildAgentLoop()` instead of inline logic
5. **Filter legacy at backend** — stop forwarding legacy types entirely
6. **Run RCA test** — send a real query, capture logs at every stage
7. **Compare streaming vs history** — verify parity from logs
8. **Fix any divergence** — iterate until identical
9. **Add Playwright parity test** — automated regression guard

---

## 11. Key Files Reference

| File | Stage | Purpose |
|------|-------|---------|
| `agent-examples/.../event_serializer.py` | 1 | LangGraph -> JSON events |
| `agent-examples/.../agent.py` | 2 | Event -> A2A TaskStatusUpdate |
| `agent-examples/.../reasoning.py` | 1 | Plan/execute/reflect node logic |
| `kagenti/backend/.../sandbox.py` | 3+4 | SSE proxy + history endpoint |
| `kagenti/ui-v2/.../SandboxPage.tsx` | 5 | SSE handler + history reconstruction |
| `kagenti/ui-v2/.../types/agentLoop.ts` | 5 | AgentLoop type definitions |
| `kagenti/ui-v2/.../components/AgentLoopCard.tsx` | 5 | Loop card rendering |
| `kagenti/ui-v2/.../components/LoopDetail.tsx` | 5 | Step/tool/reasoning detail |
