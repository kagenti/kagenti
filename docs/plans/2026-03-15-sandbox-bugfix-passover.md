# Sandbox Agent Bugfix Passover

> **Date:** 2026-03-15
> **Cluster:** kagenti-team-sandbox42 (deploying fresh)
> **Worktrees:** `.worktrees/sandbox-agent` (kagenti), `.worktrees/agent-examples` (agent code)
> **Branch:** `feat/sandbox-agent` (both repos)

## Bug 1: Prompt Data Missing for Some Nodes

### Problem

Not all nodes render full prompt data in the UI Prompt Inspector. The data pipeline
has inconsistencies in what fields each node provides, what the serializer extracts,
and what loopBuilder copies to the UI step object.

### Root Cause: Three-Layer Inconsistency

**Layer 1 — Agent nodes (reasoning.py):**
All 4 LLM-calling nodes (planner, executor, reflector, reporter) correctly call
`invoke_llm()` and spread `capture.debug_fields()` into their result dict. This
returns `_system_prompt`, `_prompt_messages`, `_llm_response`, `_bound_tools`.

- Router and step_selector do NOT call LLM (expected, no prompt data).
- Early-exit paths (budget exceeded, loop detected, stall) construct manual debug
  fields instead of LLMCallCapture — these are synthetic and may miss fields.

**Layer 2 — Serializer (event_serializer.py):**
`_extract_prompt_data()` pulls `_system_prompt`, `_prompt_messages`, `_bound_tools`,
`_llm_response` from the node result dict. This works for all 4 LLM nodes.
All serialized event types include `system_prompt`, `prompt_messages`, `bound_tools`,
`llm_response` when the data is present.

Status: OK — serializer is consistent.

**Layer 3 — UI loopBuilder (loopBuilder.ts):**
HERE IS THE BUG. When building `AgentLoopStep` objects from events, loopBuilder
copies prompt fields **inconsistently**:

| Event Type | Copies `system_prompt`? | Copies `prompt_messages`? | Copies `bound_tools`? | Copies `llm_response`? |
|------------|:-:|:-:|:-:|:-:|
| `planner_output` | Yes | Yes | **NO** | **NO** |
| `executor_step` | Yes | Yes | Yes | **NO** |
| `tool_call` | N/A | N/A | N/A | N/A |
| `tool_result` | N/A | N/A | N/A | N/A |
| `reflector_decision` | Yes | Yes | **NO** | **NO** |
| `reporter_output` | Yes | Yes | **NO** | **NO** |
| `micro_reasoning` | Yes | Yes | Yes | **NO** |
| `thinking` | Yes | Yes | Yes | Yes |

**Consequence:** Prompt Inspector renders without bound_tools for planner/reflector/reporter,
and without llm_response for ALL node types except thinking iterations.

### Fix

**loopBuilder.ts** — For every event type that produces an `AgentLoopStep`, copy ALL
four prompt fields:

```typescript
// Standardize for every LLM-calling event type:
systemPrompt: le.system_prompt,
promptMessages: le.prompt_messages,
boundTools: le.bound_tools,
llmResponse: le.llm_response,
```

**agentLoop.ts** — Add `llmResponse?: string` to `AgentLoopStep` type.

**PromptInspector.tsx** — Already generic and renders all provided fields. Just needs
the `llmResponse` prop wired (may need a "Response" section if not already present).

### Affected Files

```
UI:
  loopBuilder.ts — copy all 4 fields for all event types
  agentLoop.ts — add llmResponse to AgentLoopStep type
  PromptInspector.tsx — verify Response section renders
  LoopDetail.tsx — pass llmResponse to PromptInspector

Agent: No changes needed (already sends all fields)
Serializer: No changes needed (already extracts all fields)
```

---

## Bug 2: Workspace Path Preamble Missing in invoke_with_tool_loop

### Problem

The WORKSPACE_PREAMBLE (tells LLM "you MUST work inside `/workspace/<session_id>/`")
is not injected into thinking, tool-call, or multi-cycle LLM calls. The executor
can therefore generate commands that write outside the session directory.

### Root Cause

`context_builders.py` `invoke_with_tool_loop()` hardcodes `workspace_path=""` in
three places:

```python
# Line 574 — Thinking phase: EMPTY
reason_response, reason_capture = await invoke_llm(
    llm_reason, thinking_messages,
    node=f"{node}-think-{cycle+1}.{i+1}", session_id=session_id,
    workspace_path="",  # BUG: should be workspace_path
)

# Line 611 — Tool call phase: EMPTY
response, capture = await invoke_llm(
    llm_with_tools, tool_messages,
    node=f"{node}-tool-{cycle+1}", session_id=session_id,
    workspace_path="",  # BUG: should be workspace_path
)

# Line 622 — Single-phase after cycle 0: EMPTY
response, capture = await invoke_llm(
    llm_with_tools, cycle_messages,
    node=f"{node}-{cycle+1}" if max_cycles > 1 else node,
    session_id=session_id,
    workspace_path=workspace_path if cycle == 0 else "",  # BUG: should always pass
)
```

### Why This Was Done

Likely intentional to avoid prepending the workspace preamble to EVERY sub-call
(thinking iterations see repeated SystemMessages). But the correct fix is to inject
the preamble once into the first SystemMessage and let subsequent calls inherit it
through the message history.

### Impact

- Planner gets workspace preamble (direct `invoke_llm` call) — plans have correct paths
- Executor thinking phase: NO preamble — thinking about wrong dirs
- Executor tool call phase: NO preamble — may call shell with wrong cwd
- Executor cycles >0: NO preamble — loses workspace context mid-step
- Reporter with tools: Same bug (also uses `invoke_with_tool_loop`)

### Fix

Change all three lines to pass `workspace_path=workspace_path`:

```python
# Line 574
workspace_path=workspace_path,

# Line 611
workspace_path=workspace_path,

# Line 622
workspace_path=workspace_path,  # Always, not just cycle 0
```

The `invoke_llm()` function already handles deduplication — it only prepends the
preamble to the FIRST SystemMessage, so repeated calls are safe.

### Verification

After fix, check the Prompt Inspector for executor tool-call events. The system_prompt
section should show the WORKSPACE_PREAMBLE text:
```
WORKSPACE RULES (MANDATORY):
Your dedicated workspace is at: /workspace/<session_id>/
ALL file operations MUST use paths under this directory.
```

### Affected Files

```
Agent:
  context_builders.py:574 — workspace_path=workspace_path
  context_builders.py:611 — workspace_path=workspace_path
  context_builders.py:622 — workspace_path=workspace_path
```

---

## Bug 3: UI Should Render Prompts Generically for All Node Types

### Problem

The Prompt button appears inconsistently across node types. Some nodes show it,
others don't, even though the backend sends prompt data for all LLM-calling nodes.

### Current State

**PromptInspector.tsx** — Already fully generic. Renders whatever fields are provided:
system_prompt, prompt_messages, bound_tools, response. No node-type conditionals.

**LoopDetail.tsx** — Prompt button visibility:

| Context | Condition | Issue |
|---------|-----------|-------|
| Main step header | `onOpenInspector && (step.systemPrompt \|\| step.promptMessages)` | Data-dependent — correct |
| Micro-reasoning | `onOpenInspector` (always shown) | No data check — could show empty |
| Thinking iteration | `onOpenInspector` (always shown) | No data check — could show empty |

The Prompt button is rendered for ALL step types IF prompt data exists. The real
issue is **Bug 1** — loopBuilder doesn't copy all fields, so the condition
`step.systemPrompt || step.promptMessages` may fail even when data was sent.

### Fix

1. Fix Bug 1 (copy all prompt fields in loopBuilder) — this automatically enables
   Prompt buttons for all nodes that have data
2. Unify the button condition: always use data check
   `onOpenInspector && (step.systemPrompt || step.promptMessages || step.boundTools)`
3. No changes needed to PromptInspector.tsx itself

### Design Principle

Every rendered node that made an LLM call should have the SAME Prompt Inspector
structure:

```
+--------------------------------------------------+
| Prompt Inspector: [Node Type] [Model]             |
|                                                   |
| System Prompt                                     |
| [full system prompt text, collapsible]            |
|                                                   |
| Bound Tools (N tools)                             |
| [tool name: description, collapsible]             |
|                                                   |
| Messages (N messages)                             |
| [SystemMessage | HumanMessage | AIMessage list]   |
|                                                   |
| LLM Response                                      |
| [raw response text/tool_calls, collapsible]       |
|                                                   |
| Tokens: prompt=X completion=Y                     |
+--------------------------------------------------+
```

Bound Tools can be empty (e.g., reflector with read-only tools still lists them;
bare LLM thinking calls show "0 tools"). This is informative — shows the user
whether tools were available.

### Affected Files

```
UI:
  loopBuilder.ts — Bug 1 fix (copy all fields)
  agentLoop.ts — add llmResponse to type
  LoopDetail.tsx — pass llmResponse, unify button condition
  PromptInspector.tsx — add Response section if missing
```

---

## Bug 4: Historical + Streaming Message Loading Complexity

### Current Architecture

Two parallel paths converge on the same `applyLoopEvent()` reducer:

```
HISTORY PATH                          STREAMING PATH
─────────────                         ──────────────
GET /history                          SSE /subscribe
  ↓                                     ↓
HistoryPage {                         data: {loop_id, loop_event}
  messages[],                           ↓
  loop_events[]                       applyLoopEvent(loop, event)
}                                       ↓
  ↓                                   setAgentLoops(incremental)
messages.map(toMessage)
  ↓
buildAgentLoops(events)
  = events.forEach(applyLoopEvent)
  ↓
pairMessagesWithLoops()
  = loops[i].userMessage = userMsgs[i]  (positional pairing)
  ↓
setAgentLoops(batch) + setMessages(unpaired)
```

### What Works Well

1. **Canonical reducer** — Both paths use `applyLoopEvent()`, guaranteeing rendering
   parity between streaming and history reload
2. **Event-index ordering** — History events sorted by `event_index` before replay
3. **Deduplication** — Backend uses `seen_event_json` set to dedupe

### What's Fragile

#### 4a. Positional Message-Loop Pairing

`pairMessagesWithLoops()` pairs user messages with loops by **array position**:
```typescript
loops[0].userMessage = userMessages[0]
loops[1].userMessage = userMessages[1]
// ...
```

This breaks when:
- A user message exists without a corresponding loop (cancel before agent starts)
- A loop exists without a user message (system-initiated, sidecar)
- Messages arrive out of order from different tasks

**Better approach:** Each loop event already has a `task_id` (from A2A). The backend
could include the user message text directly in the first event of each loop
(e.g., in the `router` event which starts every loop). Then pairing becomes:
```typescript
// In applyLoopEvent for 'router' type:
loop.userMessage = le.user_message;  // Carried by the event itself
```
No separate pairing step needed.

#### 4b. `messages[]` vs `agentLoops` Dual State

The UI maintains two separate state variables:
- `messages: Message[]` — flat message list (legacy path, used when no loops)
- `agentLoops: Map<string, AgentLoop>` — loop cards with embedded user messages

When loops exist, `messages[]` holds only **unpaired** messages. The rendering
path switches entirely to loop cards. This creates confusion:
- Which state holds the user's message? Depends on whether a loop exists.
- Polling adds messages to `messages[]` but they may already be in a loop.
- Race conditions on stream end → history reload → state replacement.

**Simplification:** Always use `agentLoops` as primary data structure. Even a simple
text response (no plan/steps) could be wrapped in a minimal loop:
```typescript
{
  id: "simple-response",
  status: "done",
  userMessage: "user's question",
  finalAnswer: "agent's text reply",
  steps: [],  // empty = simple response
}
```
This eliminates the dual-state problem entirely.

#### 4c. Backend Event Extraction from Message Text

The backend extracts loop events by parsing JSON lines from agent message text
(A2A message parts). This is:
- Fragile (depends on JSON formatting)
- Expensive (SQL jsonb functions on large text blobs)
- Duplicated (both in `_extract_events_from_metadata` and `_parse_agent_messages`)

**Better approach:** Store loop events in a **dedicated column** or **separate table**
alongside the task. The agent serializer already produces structured events — store
them directly rather than embedding in message text and re-parsing.

#### 4d. Polling Complexity

After stream ends, a polling mechanism periodically calls `/history` to catch
events that arrived after SSE disconnected. This adds:
- `lastUpdatedRef` tracking
- `justFinishedStreamingRef` guard to prevent overwriting live state
- `events_since` parameter for incremental event fetching
- Race conditions between poll results and late-arriving stream events

**Simplification:** If events were stored in a dedicated table with sequential IDs,
polling becomes a simple `GET /events?after=lastEventId` that returns only new
events and replays them through `applyLoopEvent()`. No full history reload needed.

### Proposed Simplification Roadmap

**Phase 1 (quick wins):**
- Carry `user_message` in `router` event → eliminate positional pairing
- Copy all prompt fields in loopBuilder (Bug 1 fix)
- Always use loop cards even for simple responses

**Phase 2 (backend refactor):**
- Store loop events in `task.metadata.loop_events` during streaming (not just
  at session end via background persist)
- Add `events_since` incremental polling that returns only new events
- Remove duplicate extraction from message text

**Phase 3 (architecture cleanup):**
- Dedicated `loop_events` table with `(task_id, event_index, event_json)` schema
- Single polling path: `GET /events?after=N` → replay → done
- Remove `messages[]` state entirely — everything flows through loop cards

---

## Priority Matrix

| Bug | Impact | Effort | Priority |
|-----|--------|--------|----------|
| Bug 2: workspace_path="" | Security (sandbox escape) | 3 lines | **P0** |
| Bug 1: Missing prompt fields in loopBuilder | UX (debugging broken) | ~30 lines | **P1** |
| Bug 3: Generic prompt rendering | UX (inconsistent) | Depends on Bug 1 | **P1** |
| Bug 4a: Positional pairing | Correctness (wrong pairing) | ~20 lines | **P1** |
| Bug 4b: Dual state | Complexity | Medium refactor | **P2** |
| Bug 4c: Event extraction | Performance | Backend refactor | **P2** |
| Bug 4d: Polling simplification | Reliability | Needs Bug 4c | **P3** |

---

## Test Plan

After fixes, run these E2E tests on sandbox42:

```bash
export KUBECONFIG=~/clusters/hcp/kagenti-team-sandbox42/auth/kubeconfig
export LOG_DIR=/tmp/kagenti/tdd/sandbox42 && mkdir -p $LOG_DIR

# Smoke: verify deployment works
npx playwright test e2e/sandbox.spec.ts

# Prompt inspector: verify all nodes show prompt data
npx playwright test e2e/sandbox-rendering.spec.ts

# RCA workflow: verify workspace paths correct
RCA_FORCE_TOOL_CHOICE=1 RCA_AGENT_NAME=rca-agent-emptydir \
  npx playwright test e2e/agent-rca-workflow.spec.ts --timeout=600000

# History consistency: verify stream = history render
npx playwright test e2e/agent-loop-consistency.spec.ts

# Sessions: verify pairing works across sessions
npx playwright test e2e/sandbox-sessions.spec.ts
```
