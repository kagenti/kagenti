# Session Alpha-2 (2026-03-13) Passover — Step Isolation + Streaming Architecture

> **Date:** 2026-03-13
> **Cluster:** sbox42 (KUBECONFIG=/tmp/kagenti/sbox42-kubeconfig)
> **Worktrees:** `.worktrees/sandbox-agent` (kagenti), `.worktrees/agent-examples` (agent code)
> **Branch:** `feat/sandbox-agent` (both repos)
> **Previous:** session-alpha1-passover.md, session-beta-passover.md
> **Tests:** RCA E2E passing (EXIT:0), 126 events, 16/16 tool pairs, 6 steps

## Session Summary

This session (Beta continuation) focused on:
1. P0-P1: respond_to_user escape tool + STDERR false positive fix
2. Step counter refactoring (plan step + event_index chronological counter)
3. Structured OTel logging (26 logger calls with extra={})
4. Incremental event persistence (threshold 5→2)
5. Playwright SSE fix (wait for loop completion)
6. Prompt fixes (relative paths, gh CLI flags, no delegate, no /workspace)
7. **Step boundary marker** — executor context isolation via `[STEP N]` HumanMessage
8. **Retry decision** — reflector can retry current step before full replan
9. **Replan from failure** — preserves done steps, no reset to step 0
10. Dedup sentinel removal from micro_reasoning
11. event_index injection into ALL event types
12. Squid proxy: added blob.core.windows.net
13. Deep session analysis (5daa, c7f4, 8dc6, 724f, 07e9)

## Commits This Session

### Agent (agent-examples repo, branch feat/sandbox-agent)

| Commit | Description |
|--------|-------------|
| b9cefa2 | respond_to_user escape tool + STDERR false positive fix |
| d80b6b4 | Step counter from plan state + structured OTel logging |
| b04d25e | Restore event_index counter, remove dedup sentinel, GH_CACHE_DIR |
| 76279f3 | Relative paths in prompts, disable delegate tool |
| 85e4770 | Remove delegate tool from prompts |
| 86558a4 | Step-scoped executor context + retry + replan from failure |
| 054ac70 | Revert aggressive message isolation, keep 5K/30K window |
| 61bc446 | Step-scoped executor context + error logging |
| f7e2e96 | Fix used_chars scoping error in executor context |
| f014597 | Step boundary marker for executor context isolation |
| 1de7430 | Inject step + event_index into ALL event types |

### Backend (kagenti repo, branch feat/sandbox-agent)

| Commit | Description |
|--------|-------------|
| (pending) | `_INCREMENTAL_PERSIST_THRESHOLD` from 5 to 2 |
| 85c90873 | Wait for agent loop completion before navigating (Playwright) |
| 1616100a | Graph Node Visits reads event_index instead of step |

---

## Architecture: Current State

```
┌─────────────────────────────────────────────────────────────────┐
│  OUTER GRAPH (SandboxState — single MessagesState)              │
│                                                                 │
│  router → planner ⇄ planner_tools → step_selector              │
│                                         │                       │
│                                         ▼                       │
│                              executor ⇄ tools ──→ reflector     │
│                                                      │          │
│                                              reflector_route    │
│                                              │     │     │      │
│                                          reporter step  planner │
│                                              │    sel          │
│                                             END                 │
└─────────────────────────────────────────────────────────────────┘

Step isolation: via [STEP N] HumanMessage boundary marker
- Executor on new step: sees only step_brief HumanMessage
- Executor continuing: walks back to [STEP N] marker, sees own tool results
- Problem: Llama 4 Scout still sees plan in windowed messages on tool_call_count > 0
```

### What Works

| Feature | Status | Evidence |
|---------|--------|----------|
| Step boundary marker | Working | Step 1 has 1 tool call (was 6-10) |
| Event ordering | Working | event_index on ALL events |
| Retry decision | Working | Reflector can choose "retry" |
| Replan from failure | Working | Preserves done steps |
| STDERR fix | Working | git clone shows status:success |
| respond_to_user escape | Deployed | Not yet triggered by Llama 4 Scout |
| Structured logging | Working | 26 logger calls with extra={} |
| Incremental persist | Working | threshold=2, high-value types immediate |
| Playwright SSE wait | Working | 126 events persisted (was 9-13) |
| Squid proxy | Patched | blob.core.windows.net added |

### What's Broken / Incomplete

| Issue | Root Cause | Fix Needed |
|-------|-----------|------------|
| Executor still sees plan at tool_call_count > 0 | 30K window includes planner AIMessage | Proper subgraph OR aggressive window filtering |
| gh run view --log-failed > output/ci-run.log fails | Shell `>` redirect is relative to CWD (repos/kagenti), not workspace | Use full workspace path in prompt |
| Micro-reasoning shows empty blocks (0 tokens) | Dedup path still emits executor_step events | Check `_dedup` flag in serializer for ALL event types |
| Tool call/result call_id mismatch in UI | Serializer generates new call_id per event, but ToolNode returns results with different IDs | Pass LangGraph's tool_call_id through |
| Historical sessions render in wrong order | Old events have NULL event_index | Can't fix retroactively (DB data) |
| "Step 6 [2]" wrong labels in UI | loopBuilder uses step for grouping but step/event_index are conflated | Fix loopBuilder to use event_index for ordering, step for grouping |

---

## Priority 0: Workspace Path in Executor Prompt

### Problem

When the executor runs `cd repos/kagenti && gh run view ... > output/ci-run.log`, the
shell redirect `>` is relative to CWD which is `repos/kagenti/`, NOT the workspace root.
So `output/ci-run.log` creates `repos/kagenti/output/ci-run.log` (or fails if `output/`
doesn't exist inside the cloned repo).

### Fix

The agent already knows its workspace path: `state["workspace_path"]` = `/workspace/<context_id>/`.
Inject this into the executor system prompt:

```python
# In executor_node, when building system_content:
workspace_path = state.get("workspace_path", "/workspace")
system_content = _safe_format(
    _EXECUTOR_SYSTEM,
    current_step=current_step + 1,
    step_text=step_text,
    tool_call_count=tool_call_count,
    max_tool_calls=MAX_TOOL_CALLS_PER_STEP,
    workspace_path=workspace_path,  # NEW
)
```

Update `EXECUTOR_SYSTEM` in prompts.py:

```
Your workspace absolute path is: {workspace_path}
When redirecting output from inside a cloned repo, use the FULL path:
  cd repos/kagenti && gh run view <id> --log-failed > {workspace_path}/output/ci-run.log

For file_read, file_write, grep, glob: use RELATIVE paths (e.g. output/report.md).
For shell redirects inside cd'd directories: use FULL {workspace_path}/output/ path.
```

### UI File Preview

In the UI, recognize paths matching `/workspace/<context_id>/...` in tool results
and render them as clickable file preview links. The file preview API already exists:
`GET /api/v1/sandbox/{ns}/files/{agent}/{session}?path=<relative_path>`

---

## Priority 1: LangGraph Subgraph for Executor Isolation

### Problem

The executor shares `MessagesState` with the outer graph. Even with the [STEP N]
boundary marker, at `tool_call_count > 0` the 30K token window can include the
planner's AIMessage (with the numbered plan). Llama 4 Scout sees the plan and
tries to execute all steps.

### Current Workaround (step boundary marker)

```python
# executor_node — new step (tool_call_count == 0):
first_msg = [HM(content=step_brief)]
windowed = []
# Returns [STEP N] HumanMessage + AIMessage in messages

# executor_node — continuing step (tool_call_count > 0):
first_msg = [HM(content=step_brief)]
# Walk backwards to [STEP N] marker
for m in reversed(all_msgs):
    if content.startswith(f"[STEP {current_step + 1}]"):
        break
    windowed.insert(0, m)
```

This works for step 1 (1 tool call) but can leak plan context on later steps
if the window extends past the marker.

### Proper Fix: Executor Subgraph

```
OUTER GRAPH (SessionState)
├── router → planner → step_selector ──→ step_executor_wrapper ──→ reflector
│                                              │
│                                    ┌─────────▼──────────┐
│                                    │ INNER SUBGRAPH      │
│                                    │ (StepExecutorState) │
│                                    │                     │
│                                    │ executor ⇄ tools    │
│                                    │                     │
│                                    │ Returns: summary    │
│                                    └─────────────────────┘
```

**Implementation approach** (preserves event streaming):

The inner graph CANNOT be a compiled subgraph added via `graph.add_node()` because
LangGraph subgraphs share the parent state. Instead, use a **wrapper node** that:

1. Creates a fresh `StepExecutorState` with only the step brief
2. Runs the inner graph via `astream(stream_mode="updates")`
3. Yields events through the wrapper (problem: LangGraph nodes can't yield)

**Alternative: Message boundary approach (recommended)**

Instead of a true subgraph, keep executor + tools in the outer graph but:

1. The step_selector injects a `[STEP N]` SystemMessage (not HumanMessage)
   into `state["messages"]` as a step boundary
2. The executor ALWAYS builds its messages from the boundary forward:
   `[SystemMessage(executor_prompt), HM(step_brief), ...messages_after_boundary...]`
3. The tools_condition and ToolNode work normally (they read the last message)
4. The reflector receives the step summary, not the full tool history

Key code change in executor_node:
```python
# Find the step boundary in state messages
boundary_idx = len(all_msgs)
for i in range(len(all_msgs) - 1, -1, -1):
    if isinstance(all_msgs[i], SystemMessage) and \
       all_msgs[i].content.startswith(f"[STEP_BOUNDARY {current_step}]"):
        boundary_idx = i + 1
        break

# Only include messages AFTER the boundary
step_msgs = all_msgs[boundary_idx:]
messages = [SystemMessage(content=system_content), HM(content=step_brief)] + step_msgs
```

And in step_selector, inject the boundary:
```python
return {
    "messages": [SystemMessage(content=f"[STEP_BOUNDARY {next_step}]")],
    ...
}
```

**Why SystemMessage not HumanMessage**: HumanMessage would be passed to the LLM as
user input. SystemMessage is invisible to the LLM context but stays in state for
boundary detection.

---

## Priority 2: Fix Tool Call/Result ID Mapping

### Problem

The serializer generates a new `call_id` (UUID) for each tool_call event. But
LangGraph's ToolNode returns ToolMessages with `tool_call_id` matching the
AIMessage's `tool_calls[].id`. The serializer ignores this and generates its own ID,
so tool_calls and tool_results have different call_ids.

### Fix

In `_serialize_executor`, use the AIMessage's `tool_calls[].id` as the call_id
instead of generating a new UUID:

```python
if tool_calls:
    # Use LangGraph's tool_call_id for proper pairing
    call_id = tool_calls[0].get("id", str(uuid.uuid4())[:8])
    self._last_call_id = call_id
```

And in `_serialize_tool_result`, use the ToolMessage's `tool_call_id`:
```python
call_id = getattr(msg, "tool_call_id", self._last_call_id)
```

---

## Priority 3: Streaming Architecture (Design Only)

### Current: SSE fire-and-forget

```
Browser ←─ SSE ─── Backend ←─ SSE ─── Agent
                      │
                 finally block
                      │
                   DB write
```

Problems: SSE disconnect = event loss, no multi-user, no replay.

### Phase 1: DB-backed event store (next session)

```
Browser ←─ SSE ─── Backend ←─ SSE ─── Agent
               │       │
               │  DB write per event
               │       │
               └── history from DB on reconnect
```

Changes:
- Backend writes each event to DB as it receives it (threshold=1 for critical events)
- On page reload, UI loads ALL events from DB (not just what was streamed)
- Subscribe endpoint reads from DB + live stream

### Phase 2: WebSocket hub (future)

```
Browser 1 ←─ WS ──┐
Browser 2 ←─ WS ──┤─── Backend ←─ SSE ─── Agent
Browser 3 ←─ WS ──┘       │
                        DB write
                           │
                      event store
```

- WebSocket for browser↔backend (multi-user, auto-reconnect)
- SSE for backend↔agent (A2A protocol compat)
- DB is source of truth for events

### Phase 3: gRPC A2A (future)

```
Browser ←─ WS ─── Backend ←─ gRPC ─── Agent
                      │
                   DB write
```

- gRPC bidirectional streaming (binary, backpressure, reliable)
- Protobuf schemas for events (~65% smaller than JSON)
- Browser still uses WebSocket + JSON

---

## Priority 4: UI Fixes

### Counter Badge

Show `event_index` as a badge on each node instead of `[N]` text.
The `loopBuilder.ts` already reads `event_index` for `nodeVisits`.
The `AgentLoopCard.tsx` shows `[${loop.nodeVisits}]` — change to a
PatternFly badge component.

### File Preview Links

Recognize `/workspace/<context_id>/...` paths in tool_result output.
Render as clickable links that open the file preview popup.
The file preview API exists: `GET /api/v1/sandbox/{ns}/files/{agent}/{session}?path=<rel>`

### Event Ordering in loopBuilder

The `loopBuilder` groups events by `step` field. With the new step-scoped
events, events within the same step should be ordered by `event_index`.
Currently they may render out of order if `event_index` values are not sequential
within a step (gaps from events lost to SSE disconnect).

---

## How to Continue

```bash
# Cluster
export KUBECONFIG=/tmp/kagenti/sbox42-kubeconfig
export LOG_DIR=/tmp/kagenti/tdd/ui-sbox42
mkdir -p $LOG_DIR

# Priority 0: Workspace path in prompt
# File: .worktrees/agent-examples/a2a/sandbox_agent/src/sandbox_agent/prompts.py
# Add {workspace_path} to EXECUTOR_SYSTEM template
# File: .worktrees/agent-examples/a2a/sandbox_agent/src/sandbox_agent/reasoning.py
# Pass workspace_path to _safe_format in executor_node

# Priority 1: Step boundary as SystemMessage
# File: .worktrees/agent-examples/a2a/sandbox_agent/src/sandbox_agent/graph.py
# In step_selector, inject SystemMessage("[STEP_BOUNDARY N]") into messages
# File: .worktrees/agent-examples/a2a/sandbox_agent/src/sandbox_agent/reasoning.py
# In executor_node, find boundary and scope messages

# Priority 2: Tool call ID mapping
# File: .worktrees/agent-examples/a2a/sandbox_agent/src/sandbox_agent/event_serializer.py
# Use tool_calls[0].id instead of uuid4() for call_id

# Build + deploy
cd .worktrees/agent-examples
git add -u && git commit -s -m "fix(agent): ..." && git push
oc -n team1 start-build sandbox-agent

# Test
cd .worktrees/sandbox-agent/kagenti/ui-v2
RCA_SKIP_DEPLOY=1 RCA_AGENT_NAME=rca-agent-emptydir \
  npx playwright test e2e/agent-rca-workflow.spec.ts --reporter=list --timeout=600000

# Analyze
CTX_ID=$(kubectl exec -n team1 postgres-sessions-0 -- psql -U kagenti -d sessions -t -c \
  "SELECT context_id FROM tasks WHERE metadata::json->>'agent_name' = 'rca-agent-emptydir' \
   ORDER BY id DESC LIMIT 1" | tr -d ' ')
# Then run Scripts 1-6 from alpha1 passover with $CTX_ID
```

---

## Key Debugging Scripts (from this session)

### Dump all session data to local files

```bash
CTX_ID="<context_id>"
LOG_DIR="/tmp/kagenti/tdd/ui-sbox42/session-${CTX_ID:0:4}"
mkdir -p $LOG_DIR

# 1. Full timeline
kubectl exec -n team1 postgres-sessions-0 -- psql -U kagenti -d sessions -c "
SELECT (e->>'event_index')::int as ei, (e->>'step')::int as step, e->>'type' as type,
  e->>'decision' as decision, e->>'name' as tool, e->>'status' as status,
  (e->>'prompt_tokens')::int as p_tok, (e->>'completion_tokens')::int as c_tok,
  substring(COALESCE(e->>'output', e->>'content', e->>'description', e->>'reasoning', ''), 1, 150) as detail
FROM tasks, jsonb_array_elements(COALESCE(metadata::jsonb->'loop_events','[]'::jsonb)) e
WHERE context_id = '$CTX_ID'
ORDER BY (e->>'event_index')::int NULLS FIRST
" > $LOG_DIR/01-timeline.txt

# 2. Tool calls per step (step isolation check)
kubectl exec -n team1 postgres-sessions-0 -- psql -U kagenti -d sessions -c "
SELECT (e->>'step')::int as step,
  count(*) FILTER (WHERE e->>'type' = 'tool_call') as tool_calls,
  count(*) FILTER (WHERE e->>'type' = 'tool_result') as tool_results,
  count(*) FILTER (WHERE e->>'type' = 'micro_reasoning') as micro_reasons
FROM tasks, jsonb_array_elements(COALESCE(metadata::jsonb->'loop_events','[]'::jsonb)) e
WHERE context_id = '$CTX_ID' GROUP BY 1 ORDER BY 1
" > $LOG_DIR/02-step-isolation.txt

# 3. Executor prompts (check for plan leakage)
kubectl exec -n team1 postgres-sessions-0 -- psql -U kagenti -d sessions -t -A -c "
SELECT (e->>'event_index')::int, (e->>'step')::int, e->>'type',
  CASE WHEN e->>'system_prompt' LIKE '%1. Clone%2. List%' THEN 'HAS_PLAN' ELSE 'NO_PLAN' END,
  substring(e->>'system_prompt', 1, 200)
FROM tasks, jsonb_array_elements(COALESCE(metadata::jsonb->'loop_events','[]'::jsonb)) e
WHERE context_id = '$CTX_ID' AND e->>'type' IN ('executor_step', 'micro_reasoning')
  AND e->>'system_prompt' IS NOT NULL
ORDER BY (e->>'event_index')::int
" > $LOG_DIR/03-executor-prompts.txt

# 4. Agent logs
kubectl logs deploy/rca-agent-emptydir -n team1 --tail=2000 | grep "$CTX_ID" > $LOG_DIR/04-agent.log

# 5. Backend logs
kubectl logs deploy/kagenti-backend -n kagenti-system -c backend --tail=2000 | \
  grep "$CTX_ID" | grep -v sidecars > $LOG_DIR/05-backend.log
```

### Test PAT permissions

```bash
TOKEN=$(kubectl get secret github-token-secret -n team1 -o jsonpath='{.data.token}' | base64 -d)
curl -s -H "Authorization: token $TOKEN" "https://api.github.com/repos/kagenti/kagenti/actions/runs?per_page=1&status=failure" | \
  python3 -c "import json,sys; d=json.load(sys.stdin); r=d['workflow_runs'][0]; print(f'run={r[\"id\"]} name={r[\"name\"]}')"
curl -s -w "HTTP:%{http_code}" -o /dev/null -L -H "Authorization: token $TOKEN" \
  "https://api.github.com/repos/kagenti/kagenti/actions/runs/<run_id>/logs"
```
