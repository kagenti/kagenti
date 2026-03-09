# Session U Passover — Loop Event Pipeline, Tool Calling, Budget

> **Date:** 2026-03-09
> **Previous Session:** T (passover at docs/plans/2026-03-09-session-T-passover.md)
> **Cluster:** sbox42 (Llama 4 Scout via LiteLLM proxy)
> **Worktrees:** `.worktrees/sandbox-agent` (kagenti), `.worktrees/agent-examples` (agent code)
> **Cost:** ~$326, ~10.5h wall time
> **Test baseline:** 12/13 tests pass (sidecar auto-continue known failure)

---

## What Session U Delivered

| Category | Changes |
|----------|---------|
| **P0-1: Historical View** | 14 differences fixed in `loadInitialHistory` — status transitions, index-based step lookup, tool_call batch support, budget events, step statuses |
| **P0-2: Looper Sidecar** | SSE auth via fetch+ReadableStream, [DONE] fanout, `should_continue()` fix, child session creation, DB polling every interval |
| **P0-3: "continue" Final Answer** | Reporter detects bare decision keywords, falls through to LLM summary |
| **P0-4: Empty Blocks** | Guard against replacing executor steps with empty descriptions |
| **Event Pipeline** | text-parsed tool_call events, reasoning field (2000 chars), tool_choice="any" forcing tool API usage |
| **UI Rendering** | Interleaved loop cards with messages, expandable planner/reflector/reporter, plan spinner stops on done, model badges, token display |
| **Metadata Persistence** | Write to latest task only (not all rows), exclude loop_events from cross-task merge, full-JSON dedup |
| **Stats** | data-testid attributes, assertive token/message count tests, LlmUsagePanel blip fix, loop answer counting |
| **Agent Budget** | 100 iterations, 10 tools/step, 1M tokens, HITL at 50 |
| **Naming** | "kick" → "auto-continue" everywhere |
| **Tests** | Sidecar lifecycle + auto-continue, walkthrough stats, RCA stats, consistency, backend pipeline test |
| **Logging** | SSE event logging, graph event logging, CancelledError handling |

---

## Test Results (T17 — best run)

| Test | Status | Time |
|------|--------|------|
| Sessions isolation | ✅ | 1.9m |
| Sessions no-leak | ✅ | 14s |
| Sessions persist | ✅ | 22s |
| Delegation | ✅ | 49s |
| Variants (4) | ✅ | ~21s each |
| Sidecar lifecycle | ✅ | 45s |
| Consistency | ✅ | 31s |
| Walkthrough + stats | ✅ | 17s |
| RCA workflow | ✅ (flaky ~50%) | 1.8m |
| **Sidecar auto-continue** | ❌ | 3.3m |

---

## Remaining Issues (P0 for Session V)

### 1. RCA Agent — Flaky (A2A SDK CancelledError) — ROOT CAUSE FOUND

**Problem:** The A2A SDK's event queue gets `CancelledError` during long-running multi-iteration agents, dropping SSE events. The agent continues processing (our fix) but the backend receives fewer events → incomplete loop_events → old format in UI.

**Root cause chain:**
1. Nginx proxy has `proxy_read_timeout 300s` (5 min)
2. Backend streams SSE to browser but doesn't send keepalive pings to nginx
3. For slow agents (RCA with Llama 4 Scout), nginx drops the backend→browser connection after 5 min
4. Browser disconnects → backend's httpx stream to agent closes
5. Agent's A2A SDK event consumer gets `CancelledError`
6. Events produced after CancelledError are dropped from SSE (but agent continues processing)

**Evidence:**
```
nginx.conf: proxy_read_timeout 300s;
Agent logs: CancelledError in span a2a.server.events.event_queue.EventQueue.dequeue_event
Backend logs: only 2 SSE data lines received for RCA (should be 10+)
```

**Fix (Session V):**
1. **Backend SSE keepalive**: Send `data: {"ping": true}` every 15s to nginx to prevent timeout
2. **Increase nginx timeout**: `proxy_read_timeout 600s` or more
3. **Backend fallback**: After SSE stream ends with incomplete events, read task history from agent's A2A task store via `message/send` and extract loop_events from the final task
4. **Agent-side**: Already fixed — catches CancelledError and continues processing

**How to implement backend keepalive:**
In `_stream_sandbox_response()`, run a background task that sends ping data to the SSE response every 15s:
```python
async def _keepalive():
    while True:
        await asyncio.sleep(15)
        yield "data: {\"ping\": true}\n\n"
```

**How to implement fallback:**
After `finally` block, if `loop_events` is empty but session is completed:
```python
# Read final task from agent's task store
resp = await client.post(agent_url, json={"method": "tasks/get", "params": {"id": task_id}})
task = resp.json()["result"]
# Extract loop_events from task history
for msg in task["history"]:
    for part in msg["parts"]:
        parsed = json.loads(part["text"])
        if parsed.get("loop_id"):
            loop_events.append(parsed)
```

### 2. Sidecar Auto-Continue — Design Issue

**Problem:** Looper polls DB for parent session state. After first auto-continue creates a child session, the parent's state stays COMPLETED. Looper needs to track and poll child context_ids.

**Design:** Message queuing (next phase) — looper queues "continue" messages, picks them up when current loop finishes.

### 3. File Browser 404 for Some Agents

**Problem:** `/files/{agent_name}/{context_id}` returns 404 for sandbox-basic but works for rca-agent. May be a workspace path resolution issue per agent deployment.

### 4. Reflector Loops Without Progress — Needs Stall Detection

**Problem:** Session `8a6d778a` shows 52 messages — the agent called tools in iterations 1-2, then looped 25+ times (planner→executor→reflector) without any tool calls or new output. The reflector keeps saying "replan" without detecting that nothing changed.

**Evidence:** 52 history messages, only 2 tool_results at messages 3 and 8, then 40+ planner/executor/reflector cycles with zero tool calls.

**Fix:** Add stall detection to the reflector:
- Track tool_call count per iteration
- If last 3 iterations had 0 tool calls → force `done`
- Or: compare executor output across iterations — if identical, force `done`
- Consider reducing default budget back to a reasonable number (20?) with stall detection

**Code location:** `reasoning.py` reflector_node — needs access to iteration history

### 5. Executor Still Writes Text Instead of Tool Calls (Sometimes)

**Problem:** Despite `tool_choice="any"`, Llama 4 Scout occasionally writes text descriptions instead of using function calling API. The `parse_text_tool_calls()` catches some patterns (Llama format, legacy format) but not all.

**Fix:** Proper skill unpacking — when executor output contains a slash command, load the skill, extract commands, re-feed to planner. Don't hack the parser.

### 5. Budget Not Configurable Per Session

**Problem:** Budget (100 iter, 10 tools/step, 1M tokens) is hardcoded as defaults. Should be configurable per agent (env vars) and overridable per session (UI/API).

### 6. Sidecar State Not Persisted

**Problem:** Sidecar handles (enabled/disabled, config, observations) are stored in-memory in `SidecarManager._handles`. Backend restart loses all state. UI shows no sidecars after restart.

**Fix:** Persist sidecar state in session metadata or a separate DB table. On startup, restore handles for active sessions.

### 7. Multi-Turn Loop Events — Per-Task Isolation

**Problem:** The metadata merge in `finally` block was copying loop_events across tasks. Fixed by excluding `loop_events` from merge, but older sessions still have duplicated data.

**Status:** Fixed for new sessions. Old sessions show deduplicated events (may lose some turns).

---

## Architecture Reference

### Event Pipeline (Working)
```
Agent graph node
  → event_serializer.py (typed JSON with type + loop_id)
  → A2A SSE stream (status-update with message parts)
  → Backend _stream_sandbox_response:
      - Parses JSON lines from status_message
      - Detects loop_id → forwards as loop_event to frontend
      - Captures new-type events (filters legacy)
      - Persists in finally block (latest task row only)
  → Frontend SSE handler:
      - Creates AgentLoop steps with nodeType badges
      - Merges tool data when steps replaced at same index
      - Filters JSON events from flat messages (isGraphDump)
  → On reload:
      - History endpoint aggregates loop_events from all task rows (full-JSON dedup)
      - loadInitialHistory reconstructs AgentLoop from events
      - Loop cards interleaved with user messages by position
```

### Budget
```
max_iterations: 100 (outer plan-execute-reflect cycles)
max_tool_calls_per_step: 10 (per plan step)
max_tokens: 1,000,000 (prompt + completion)
hitl_interval: 50 (pause for human approval)
recursion_limit: 50 (LangGraph hard stop)
tool_choice: "any" (force function calling API)
```

### Key Commits (kagenti worktree)
```
c125118b  P0 fixes — history consistency, looper sidecar, empty blocks
7bca4fac  Stats tests and data-testid attributes
e1b8c123  Interleave loop cards, modal handling, looper dedup
9f49b15e  Metadata write to latest task only, full-JSON dedup
8ea9af23  Reasoning block, model badges, walkthrough fix
095fb4f2  Filter JSON loop events from history (isGraphDump)
58c64415  Merge tool data on step replace, fix ordering
fb84f393  Plan spinner, expandable all step types
419d6155  Exclude loop_events from metadata merge
b9ad147a  Log all SSE data lines for diagnosis
```

### Key Commits (agent-examples worktree)
```
38eed6a   Reporter bare keyword detection (P0-3)
add2f90   Text-parsed tool_call events + reasoning field
d8cbe0c   Executor prompt enforces tool calling
78c5ca2   Agent continues on client disconnect
4ea981b   Revert parser hack (keep prompt only)
d015770   tool_choice="any" — force tool calling
1ddf88b   Budget: 100 iter, 10 tools/step, 1M tokens
```

---

## How to Run Tests

```bash
cd .worktrees/sandbox-agent/kagenti/ui-v2
export KUBECONFIG=~/clusters/hcp/kagenti-team-sbox42/auth/kubeconfig
export KEYCLOAK_PASSWORD=$(kubectl get secret kagenti-test-users -n keycloak -o jsonpath='{.data.admin-password}' | base64 -d)
export KAGENTI_UI_URL=https://kagenti-ui-kagenti-system.apps.kagenti-team-sbox42.octo-emerging.redhataicoe.com
export KEYCLOAK_USER=admin CI=true

# Full suite
npx playwright test e2e/ --workers=4 --reporter=list

# Backend pipeline test (from backend dir)
cd ../backend
python3 -m pytest tests/test_loop_event_pipeline.py -v
```

### Build → Deploy
```bash
# Push changes
cd .worktrees/sandbox-agent && git push origin feat/sandbox-agent
cd .worktrees/agent-examples && git push origin feat/sandbox-agent

# Trigger builds
oc start-build kagenti-ui -n kagenti-system
oc start-build kagenti-backend -n kagenti-system
oc start-build sandbox-agent -n team1

# Restart
oc rollout restart deployment/kagenti-ui deployment/kagenti-backend -n kagenti-system
oc rollout restart deployment/sandbox-legion deployment/sandbox-basic deployment/sandbox-hardened deployment/sandbox-restricted -n team1
```

---

## Key Files

| File | Purpose |
|------|---------|
| `kagenti/ui-v2/src/pages/SandboxPage.tsx` | SSE handler, history reconstruction, rendering |
| `kagenti/ui-v2/src/components/AgentLoopCard.tsx` | Loop card with toggle |
| `kagenti/ui-v2/src/components/LoopDetail.tsx` | Steps, tool calls, reasoning blocks |
| `kagenti/ui-v2/src/components/LoopSummaryBar.tsx` | Status icon, token count, duration |
| `kagenti/ui-v2/src/components/SessionStatsPanel.tsx` | Message/token/tool stats |
| `kagenti/ui-v2/src/types/agentLoop.ts` | AgentLoop + AgentLoopStep types |
| `kagenti/backend/app/routers/sandbox.py` | SSE proxy, metadata, history endpoint |
| `kagenti/backend/app/services/sidecar_manager.py` | Looper DB polling, _send_continue |
| `kagenti/backend/app/services/sidecars/looper.py` | LooperAnalyzer state machine |
| `agent-examples/a2a/sandbox_agent/src/sandbox_agent/reasoning.py` | Planner/executor/reflector/reporter |
| `agent-examples/a2a/sandbox_agent/src/sandbox_agent/event_serializer.py` | Graph → JSON events |
| `agent-examples/a2a/sandbox_agent/src/sandbox_agent/budget.py` | Iteration/token/tool limits |
| `agent-examples/a2a/sandbox_agent/src/sandbox_agent/graph.py` | LangGraph build, tool binding |
