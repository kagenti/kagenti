# Session Alpha-3 (2026-03-14) Passover — Unified LLM Call Pattern

> **Date:** 2026-03-14
> **Cluster:** sbox42 (KUBECONFIG=/tmp/kagenti/sbox42-kubeconfig)
> **Worktrees:** `.worktrees/sandbox-agent` (kagenti), `.worktrees/agent-examples` (agent code)
> **Branch:** `feat/sandbox-agent` (both repos)
> **RCA Tests:** Both variants passing (V1 forced: 2.1m/5/5, V2 auto: 1.7m/5/5)
> **Unit Tests:** 142 passing (agent), 6 passing (UI loopBuilder)
> **Previous:** session-gamma-passover.md, session-gamma2-passover.md

## P0: Unified invoke_llm Pattern for All Nodes

### Problem

Only `executor_node` and `planner_node` use `invoke_llm`. The `reflector_node`
and `reporter_node` still call `llm.ainvoke()` directly with manual debug field
construction (`_DEBUG_PROMPTS` conditionals). This causes:

1. **bound_tools missing** in prompt inspector — reflector/reporter don't capture tools
2. **No workspace preamble** on reflector/reporter LLM calls
3. **Inconsistent debug data** — some nodes have `_system_prompt`, some don't
4. **No per-call event emission** — Phase 1/2 of two-phase executor are bundled

### Fix: Wire ALL Nodes Through invoke_llm

Every LLM call must go through `invoke_llm()` which:
- Injects WORKSPACE_PREAMBLE into SystemMessage
- Captures exact messages sent + response received
- Extracts bound_tools from the LLM binding
- Returns `(response, LLMCallCapture)` with `.debug_fields()` and `.token_fields()`

```python
# BEFORE (reflector_node — manual debug):
response = await llm.ainvoke(reflect_messages)
result = {
    "messages": [response],
    **({"_system_prompt": system_content[:10000]} if _DEBUG_PROMPTS else {}),
    **({"_prompt_messages": _summarize_messages(reflect_messages)} if _DEBUG_PROMPTS else {}),
    **({"_llm_response": _format_llm_response(response)} if _DEBUG_PROMPTS else {}),
}

# AFTER:
from sandbox_agent.context_builders import invoke_llm
response, capture = await invoke_llm(
    llm, reflect_messages,
    node="reflector", session_id=state.get("context_id", ""),
    workspace_path=state.get("workspace_path", "/workspace"),
)
result = {
    "messages": [response],
    **capture.debug_fields(),   # _system_prompt, _prompt_messages, _llm_response, _bound_tools
    **capture.token_fields(),   # model, prompt_tokens, completion_tokens
}
```

### Nodes to Update

| Node | File | Current | Change |
|------|------|---------|--------|
| `planner_node` | reasoning.py:694 | Uses `invoke_llm` ✓ | Keep — already done |
| `executor_node` | reasoning.py:870 | Uses `invoke_llm` ✓ | Keep — already done |
| `reflector_node` | reasoning.py:1222 | Direct `llm.ainvoke()` | Wire through `invoke_llm` |
| `reporter_node` | reasoning.py:1486 | Direct `llm.ainvoke()` | Wire through `invoke_llm` |
| Planner tool passthrough | reasoning.py:728 | Manual debug fields | Use `planner_capture.debug_fields()` |
| Reflector tool passthrough | reasoning.py:1244 | Manual debug fields | Use capture |

### P0b: Extract Micro-Reasoning/Tool-Call Loop as Reusable Function

Currently the two-phase executor has Phase 1 (reasoning) and Phase 2 (tool call)
hardcoded. Any node with tools (planner, reflector) should get the same loop
automatically.

```python
async def invoke_with_tool_loop(
    llm_with_tools: Any,
    llm_reason: Any | None,  # bare LLM for reasoning (None = single-phase)
    messages: list[BaseMessage],
    *,
    node: str,
    session_id: str,
    workspace_path: str,
    max_tool_calls: int = 10,
) -> tuple[AIMessage, LLMCallCapture, list[dict]]:
    """Invoke LLM with optional two-phase reasoning + tool call loop.

    Returns (response, capture, sub_events) where sub_events is a list
    of micro_reasoning event dicts — one per Phase 1 call.

    When llm_reason is provided (two-phase mode):
      Phase 1: bare LLM (no tools) → text reasoning → emitted as sub_event
      Phase 2: llm_with_tools (tool_choice=any) → structured tool call

    Each sub_event has full debug data (system_prompt, prompt_messages,
    bound_tools, llm_response) so the UI can inspect every call.
    """
```

This replaces the hardcoded two-phase logic in `executor_node` and can be
attached to any node that has tools bound.

### P0c: Each Micro-Reasoning as Separate Event

Currently the serializer emits ONE micro_reasoning event per executor_node
invocation. With the tool loop, each Phase 1 call should be a SEPARATE event:

```
# Current: one micro_reasoning per executor invocation
micro_reasoning (contains Phase 1 reasoning + Phase 2 tool call summary)

# Target: separate events per phase
micro_reasoning_1 (Phase 1 text reasoning, with debug: system_prompt, messages, bound_tools=0)
tool_call_1 (Phase 2 structured call, with debug: system_prompt, messages, bound_tools=7)
tool_result_1 (from tools node)
micro_reasoning_2 (Phase 1 text reasoning for next iteration)
tool_call_2 (Phase 2 structured call)
...
```

Each micro_reasoning event must include:
- `system_prompt`: what the LLM saw
- `prompt_messages`: the message list sent
- `bound_tools`: tool schemas (0 for Phase 1 bare LLM, N for Phase 2)
- `llm_response`: the actual response (text for Phase 1, tool_calls for Phase 2)
- `reasoning`: the text content

### Fix for bound_tools Not Appearing in UI

**Root cause found**: The loopBuilder constructs `MicroReasoning` objects manually
and wasn't copying `bound_tools` from the event data. Fixed in commit 8e7ea5c5
but needs UI rebuild to verify.

Also: the `_extract_prompt_data` in the serializer reads `value.get("_bound_tools")`
from the node result dict. This works when `capture.debug_fields()` is spread into
the result. Verify by checking the serialized JSON for `"bound_tools":` field.

## Other Issues

### SSE Persistence (Backend → Agent Connection)

**Status:** httpx `read=None` timeout deployed. `INCR_PERSIST` logging added.
Backend receives first 4 events then SSE connection may drop. BG persist in
finally block writes all events at session end.

**Verification needed:** Check `INCR_PERSIST` logs after a session to see if
ALL events trigger incremental persist, or if the connection drops after the
first burst.

### Budget Proxy Routing

**Status:** Fixed. `SANDBOX_LLM_API_BASE` env var on backend deployment set to
`http://llm-budget-proxy.{namespace}.svc:8080/v1`. Wizard-deployed agents now
route through budget proxy. Verified: 148 calls / 517K tokens tracked for V1.

**Note:** The Helm chart sets `SANDBOX_LLM_API_BASE` on the backend deployment.
We overrode it via `kubectl set env`. For permanent fix, update the Helm values.

### Token Counting Mismatch

Agent inline counter (23K) vs budget proxy (517K). The inline counter uses
`response.usage_metadata` which may not be populated correctly by the litellm
proxy response when going through the budget proxy. The budget proxy counts
actual upstream tokens. Trust the proxy number.

### Redeploy Test

Test deploys agent, sends message, redeploys with new limits (1537Mi/507m),
verifies limits applied via kubectl. Redeploy works but test times out at
Pod tab assertion. Fix: adjust assertion or increase timeout.

### Welcome Card

Fixed: only shows in empty session state. No more bot icon + agent name header
above messages. Commit ff95a573.

## Commits This Session

### Agent (agent-examples repo)

| Commit | Description |
|--------|-------------|
| 9b54b97 | Remove all legacy event types (plan, plan_step, reflection) |
| 580184c | Phase 1 uses bare LLM (no tools) for text reasoning |
| 29f2d2f | Two-phase executor (reasoning + tool call) |
| 67043a5 | Revert to tool_choice="any" after auto experiments |
| a5cc813 | Capture bound tools in invoke_llm debug |
| 7600399 | Read SANDBOX_FORCE_TOOL_CHOICE env var |
| 03dfa37 | Preserve actual LLM response on no-tool-count failure |

### UI + Backend (kagenti repo)

| Commit | Description |
|--------|-------------|
| 0b53bb40 | Don't auto-enable text parsing, use wizard defaults |
| 593915d7 | Bump egress proxy defaults to 256Mi/200m |
| 5cba0515 | Patch existing deployments on redeploy (was skip on 409) |
| 18cf70b5 | Route agent LLM calls through budget proxy |
| dc434628 | Remove global httpx read timeout for SSE streaming |
| ab43253e | Remove legacy event type handling from UI + backend |
| 1abbda15 | Filter unknown event types in loopBuilder (KNOWN_TYPES) |
| 8e7ea5c5 | Pass bound_tools from micro_reasoning events to inspector |
| ff95a573 | Hide welcome card when messages exist |
| 3a3beebc | Agent redeploy E2E test |
| Multiple | RCA test wizard toggle fixes (step order, label click, .first()) |

## How to Continue

```bash
# Setup
export KUBECONFIG=/tmp/kagenti/sbox42-kubeconfig
export LOG_DIR=/tmp/kagenti/tdd/ui-sbox42
mkdir -p $LOG_DIR

# P0: Wire reflector + reporter through invoke_llm
# File: .worktrees/agent-examples/a2a/sandbox_agent/src/sandbox_agent/reasoning.py
# Lines to change:
#   reflector_node ~1222: replace llm.ainvoke() with invoke_llm()
#   reporter_node ~1486: replace llm.ainvoke() with invoke_llm()
#   Remove all manual _DEBUG_PROMPTS conditionals from these nodes

# P0b: Extract tool loop function
# File: .worktrees/agent-examples/a2a/sandbox_agent/src/sandbox_agent/context_builders.py
# Add: invoke_with_tool_loop() that wraps invoke_llm with two-phase logic
# Then refactor executor_node to use it

# Run unit tests
cd .worktrees/agent-examples/a2a/sandbox_agent
uv run pytest tests/test_context_isolation.py tests/test_executor_loop.py \
  tests/test_node_visit_indexing.py tests/test_event_serializer.py -v

# Build + deploy
cd .worktrees/agent-examples
git add -u && git commit -s -m "fix(agent): ..." && git push
oc -n team1 start-build sandbox-agent

cd .worktrees/sandbox-agent
git add -u && git commit -s -m "fix(ui): ..." && git push
oc -n kagenti-system start-build kagenti-ui
oc -n kagenti-system start-build kagenti-backend

# 3-phase clean per tdd:ui-hypershift
kubectl exec -n team1 postgres-sessions-0 -- psql -U kagenti -d sessions -c \
  "DELETE FROM checkpoint_writes; DELETE FROM checkpoint_blobs; DELETE FROM checkpoints; DELETE FROM tasks"
oc -n team1 rollout restart deploy/rca-agent-emptydir
oc -n kagenti-system rollout restart deploy/kagenti-backend
sleep 30
kubectl exec -n team1 postgres-sessions-0 -- psql -U kagenti -d sessions -c \
  "DELETE FROM checkpoint_writes; DELETE FROM checkpoint_blobs; DELETE FROM checkpoints; DELETE FROM tasks"

# Run both RCA test variants (wizard deploy)
RCA_FORCE_TOOL_CHOICE=1 RCA_AGENT_NAME=rca-agent-emptydir \
  npx playwright test e2e/agent-rca-workflow.spec.ts --timeout=600000

RCA_FORCE_TOOL_CHOICE=0 RCA_AGENT_NAME=rca-auto \
  npx playwright test e2e/agent-rca-workflow.spec.ts --timeout=600000

# Verify bound_tools in prompt inspector
# Open a session → expand a step → click Prompt → check "Bound Tools" section
# Should show tool names (shell, file_read, grep, etc.) not "0 tools"

# Verify budget proxy tracking
kubectl exec -n team1 postgres-sessions-0 -- psql -U kagenti -d llm_budget -c \
  "SELECT session_id, count(*) as calls, sum(prompt_tokens+completion_tokens) as tokens \
   FROM llm_calls GROUP BY session_id ORDER BY calls DESC LIMIT 5"
```

## Key File Locations

```
Agent code:
  .worktrees/agent-examples/a2a/sandbox_agent/src/sandbox_agent/
  ├── context_builders.py    # invoke_llm, build_*_context, LLMCallCapture
  ├── reasoning.py           # planner, executor, reflector, reporter nodes
  ├── event_serializer.py    # LangGraphSerializer (JSON event emission)
  ├── graph.py               # LangGraph graph construction, tool binding
  ├── prompts.py             # System prompt templates + WORKSPACE_PREAMBLE
  └── agent.py               # A2A server, astream() loop, workspace_path in input_state

UI code:
  .worktrees/sandbox-agent/kagenti/ui-v2/src/
  ├── utils/loopBuilder.ts   # applyLoopEvent reducer (groups by node_visit)
  ├── components/LoopDetail.tsx        # CollapsibleStepSection, ToolResultBlock
  ├── components/AgentLoopCard.tsx     # Plan always visible, badges
  ├── components/PromptInspector.tsx   # Bound Tools section
  └── pages/SandboxPage.tsx           # SSE handler, history loading

Backend code:
  .worktrees/sandbox-agent/kagenti/backend/app/routers/
  ├── sandbox.py             # SSE streaming, incremental persist, BG persist
  └── sandbox_deploy.py      # Wizard deploy (LLM_API_BASE, proxy limits, 409 patch)
```

## Architecture Reference

### invoke_llm Contract
```python
response, capture = await invoke_llm(
    llm, messages,
    node="reflector",
    session_id=state.get("context_id", ""),
    workspace_path=state.get("workspace_path", "/workspace"),
)
# capture.debug_fields() → {_system_prompt, _prompt_messages, _llm_response, _bound_tools}
# capture.token_fields() → {model, prompt_tokens, completion_tokens}
# capture.messages → exact list sent to LLM (with workspace preamble)
# capture.bound_tools → tool schemas extracted from llm.kwargs["tools"]
```

### Node Visit Model
```
node_visit increments on node TYPE transitions only:
  router(1) → planner(2) → step_selector(3) → executor(4) → reflector(5)
                                                    ↑ ↓
                                              tools (stays 4)
  executor→tools→executor tool loop = same node_visit
```

### Context Windows
```
Planner:   SystemMessage + user HumanMessage + recent ToolMessages (no own AIMessages)
Executor:  SystemMessage + step brief + this step's tool pairs + reflection HumanMessages
Reflector: SystemMessage + last 3 AI→Tool pairs (no planner/reflector text AIMessages)
Reporter:  SystemMessage + full history (intentional for summarization)
```

### Two-Phase Executor (when SANDBOX_FORCE_TOOL_CHOICE=1)
```
Phase 1: bare LLM (no tools) → text reasoning
Phase 2: llm_with_tools (tool_choice="any") → structured tool call
Reasoning merged into response.content for micro_reasoning event
```

### tool_choice Experiment Results
```
tool_choice="any" (required):    100% structured calls, no text reasoning
tool_choice="auto" (explicit):   0% structured on vLLM Llama 4 Scout
implicit auto (omitted):         0% structured on vLLM Llama 4 Scout
bare LLM (no tools):             100% text (forced, no tools to call)
```

## Research: A2A Message Queuing & Task Cancellation

### Current A2A Task Lifecycle
```
Client → POST /tasks/sendSubscribe (SSE) → Agent processes → streams events → final status
```
Each `tasks/send` or `tasks/sendSubscribe` is independent. A2A has NO built-in
message queuing that blocks until a previous task completes.

### Task Cancellation (A2A spec)
The A2A protocol defines `POST /tasks/cancel` with `{"id": "<task_id>"}`.
The agent SHOULD set `task.status.state = "canceled"` and stop work.

Our sandbox agent uses LangGraph's `astream()` — cancellation requires:
1. Backend receives cancel request
2. Backend signals the agent (e.g., sets a flag in the task store or cancels the SSE connection)
3. Agent checks for cancellation between LLM calls / tool executions
4. Agent emits a final `status_update` with `state: "canceled"`

### Pattern 1: Cancel + New (Recommended First)
```
User clicks cancel → UI sends POST /api/sandbox/tasks/{id}/cancel
→ Backend cancels SSE connection to agent
→ Agent detects broken pipe, cleans up
→ UI sends new message via POST /api/sandbox/tasks/sendSubscribe
```
**Pros:** Simple, matches ChatGPT/Claude UX, no queuing needed.
**Cons:** Loses in-progress work. Agent must handle abrupt cancellation gracefully.

### Pattern 2: Message Queuing (Future)
```
User sends message while task running → queued in backend
→ Current task finishes → backend sends queued message
→ Agent processes next message with full context
```
**Pros:** No lost work, natural conversation flow.
**Cons:** More complex, needs queue persistence, user may wait a long time.

### Implementation Plan
1. **Cancel button (P1):** Add cancel button to running agent loop card.
   - UI: button with confirmation popup
   - Backend: `POST /api/sandbox/tasks/{task_id}/cancel` endpoint
   - Agent: graceful cancellation (check flag between tool calls)

2. **Message queuing (P2):** Queue messages when task is running.
   - Backend holds pending messages in session state
   - Auto-send after current task completes or is canceled
   - UI shows "queued" indicator on pending messages
