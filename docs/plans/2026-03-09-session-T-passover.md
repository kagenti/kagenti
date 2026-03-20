# Session T Passover — Loop Consistency, Looper Fix, Historical View

> **Date:** 2026-03-09
> **Previous Session:** S (Opus 4.6, 1M context, ~$250, 8h wall)
> **Cluster:** sbox42 (Llama 4 Scout via LiteLLM proxy)
> **Worktree:** `.worktrees/sandbox-agent` (kagenti), `.worktrees/agent-examples` (agent code)
> **Test baseline:** 10/10 core tests pass, consistency test fails (by design)

---

## What Session S Delivered (Summary)

| Category | Features |
|----------|----------|
| **Event Pipeline** | Typed event schema (`event_schema.py`), serializer refactor (distinct types per node), backend persistence in `finally` block, frontend reconstruction from `loop_events` |
| **UI Components** | Model switcher cog, graph node badges, HITL approval dialog, sub-sessions tab, compact sidecar panel, file preview fullscreen, token display per step |
| **Backend Fixes** | Atomic metadata write (agent_name + loop_events in one UPDATE), `_resolve_agent_name` never returns empty, metadata merge across task rows, retry with backoff |
| **Agent Changes** | recursion_limit: 50, token emission in SSE events, request_id capture, f-string docstring revert |
| **Test Infrastructure** | Parallel execution (4 workers, 1.5m), `toPass()` retry wrappers, data-testid sidebar selectors, loop consistency test, resilience test |
| **Cleanup** | Deleted stale `deployments/sandbox/agents/legion/*.py`, looper language ("auto-continued"), dark mode colors |

---

## P0 for Session T

### 1. Historical View ≠ Streaming View (CRITICAL)

**The consistency test (`agent-loop-consistency.spec.ts`) fails.** This is the #1 priority.

**Problem:** During live streaming, the UI renders loop cards with badges ([planner], [executor], etc.) and tool calls. After reload, the historical reconstruction from persisted `loop_events` renders differently — missing badges, wrong step order, or flat text instead of loop cards.

**Root cause chain:**
1. Agent serializer emits both new types (`planner_output`) and legacy types (`plan`) as separate JSON lines
2. Backend captures events during streaming — the legacy filter (`_LEGACY` set) skips legacy types for persistence ✓
3. Backend persists events in `finally` block via atomic metadata write ✓
4. History endpoint returns `loop_events` from metadata ✓
5. Frontend `loadInitialHistory` reconstructs loop cards from events ← **THIS IS WHERE IT BREAKS**

**Debug approach:**
```bash
# 1. Send a message, capture streaming view (screenshots)
# 2. Check persisted events in DB
kubectl exec -n team1 postgres-sessions-0 -- psql -U kagenti -d sessions -t -A \
  -c "SELECT metadata::json->'loop_events' FROM tasks WHERE context_id = '<ID>' LIMIT 1"

# 3. Check what history endpoint returns
# (need auth — use the test's kc() helper or curl with token)

# 4. Compare events in DB vs what frontend receives
# Add console.log in loadInitialHistory after receiving loop_events
```

**Key code locations:**
- Frontend reconstruction: `SandboxPage.tsx` ~line 960 (`if (pageAny.loop_events)`)
- History endpoint: `sandbox.py` ~line 440 (`persisted_loop_events`)
- SSE handler (streaming): `SandboxPage.tsx` ~line 1420 (event type handling)

**The fix must make the reconstruction loop produce IDENTICAL AgentLoop objects as the live SSE handler.** The consistency test should pass when this is fixed.

### 2. Looper Not Working (CRITICAL)

**Problem:** The looper sidecar is enabled but doesn't auto-continue the agent.

**Three sub-issues:**

**2a. SSE observations return 401**
The sidecar observation SSE endpoint requires auth, but the `EventSource` in `SidecarTab.tsx` doesn't pass auth headers. EventSource doesn't support custom headers natively — need to use `fetch` + SSE parsing or pass token as query param.

**2b. fan_out_event not triggering auto-continue**
The `fan_out_event` call in `_stream_sandbox_response` (line ~1484) forwards SSE events to the sidecar manager. But the looper's `ingest()` method may not be detecting the `COMPLETED` state from the forwarded events. Check:
- Is `fan_out_event` being called? (add logging)
- Is the event format correct for `LooperAnalyzer.ingest()`?
- Is `should_kick()` returning `True`?
- Is the kick actually sending a "continue" message?

**2c. Looper should create sub-sessions**
Currently the looper sends "continue" to the same session. It should:
- Create a child session (with `parent_context_id`)
- Share the parent's workspace
- Be visible in the sub-sessions tab

**Key code locations:**
- Sidecar manager: `kagenti/backend/app/services/sidecar_manager.py`
- Looper analyzer: `kagenti/backend/app/services/sidecars/looper.py`
- fan_out_event: `sandbox.py` ~line 1484
- SidecarTab SSE: `kagenti/ui-v2/src/components/SidecarTab.tsx`

### 3. "continue" as Final Answer

**Problem:** When the agent's budget is exhausted (6/6 iterations), the reflector forces `done=True` but its text output is just "continue". The reporter receives this as input and outputs "continue" as the final answer.

**Fix approaches:**
- **Agent-side (preferred):** In `reporter_node` (`reasoning.py`), detect when input is a bare decision keyword and generate a summary from `step_results` instead
- **Frontend-side (band-aid, already applied):** Filter `reporter_output` content matching `/^(continue|replan|done|hitl)\s*$/` → set `finalAnswer = ''`

**Key code:** `reasoning.py` ~line 604 (`reporter_node`)

### 4. Empty Blocks in Agent Loop

**Problem:** Some `executor_step` events have empty `description` — the executor emits a step event before the LLM responds, then another after. The first one creates an empty block.

**Fix:** In the frontend SSE handler, when an `executor_step` arrives with the same step index as an existing step, UPDATE the existing step instead of creating a new one. Currently:
```typescript
steps: [
  ...l.steps.filter((s) => s.index !== le.step),  // Already filters!
  { index: le.step, description: le.description || '', ... }
]
```
The filter removes the old step — but if `description` is empty, the replacement is also empty. The fix: only update if the new description is non-empty.

---

## Test Suite

### Core 5 (must pass):
```bash
npx playwright test e2e/sandbox-sessions.spec.ts e2e/sandbox-walkthrough.spec.ts \
  e2e/sandbox-variants.spec.ts e2e/agent-rca-workflow.spec.ts \
  e2e/sandbox-delegation.spec.ts --workers=4
```

### Consistency test (currently fails — fix it):
```bash
npx playwright test e2e/agent-loop-consistency.spec.ts
```

### Sidecar test (needs looper fix):
```bash
npx playwright test e2e/sandbox-sidecars.spec.ts
```

### Full suite:
```bash
npx playwright test e2e/ --workers=4
```

---

## Architecture Reference

### Event Pipeline
```
Agent graph node
  → event_schema.py (typed dataclass: PlannerOutput, ExecutorStep, etc.)
  → event_serializer.py (emits JSON with type + loop_id)
  → A2A SSE (message parts contain JSON lines)
  → Backend _stream_sandbox_response:
      - Parses JSON lines, detects loop_id
      - Forwards to frontend as loop_event
      - Captures new-type events only (filters legacy)
      - fan_out_event to sidecar manager
  → finally block:
      - Atomic metadata write: agent_name + title + owner + loop_events
  → Frontend SSE handler:
      - Skips legacy types (plan, plan_step, reflection, llm_response)
      - Creates AgentLoop steps with nodeType badges
      - Filters "continue" from reporter_output
  → On reload:
      - History endpoint returns loop_events from metadata
      - loadInitialHistory reconstructs AgentLoop from events
```

### Agent Name Resolution
```
1. Frontend: selectedAgentRef.current || 'sandbox-legion' (never empty)
2. Backend: _resolve_agent_name(namespace, session_id, request_agent)
   - New session: return request_agent || 'sandbox-legion'
   - Existing session: read from DB (authoritative)
3. _set_owner_metadata: always overwrites agent_name with resolved value
4. finally block: atomic write merges agent_name + loop_events
```

### Sidecar Architecture
```
Sidecars run in-process as asyncio tasks in the backend.
- SidecarManager: manages lifecycle, event queues
- fan_out_event(): forwards SSE events to sidecar analyzers
- LooperAnalyzer: detects COMPLETED → sends "continue"
- HallucinationObserver: detects fake file paths
- ContextGuardian: monitors token usage

SSE observations: /sidecars/{type}/observations (needs auth fix)
Config: hot-reload via PUT /sidecars/{type}/config
```

---

## How to Run Tests on sbox42

```bash
cd /Users/ladas/Projects/OCTO/kagenti/kagenti
export KUBECONFIG=~/clusters/hcp/kagenti-team-sbox42/auth/kubeconfig
export KEYCLOAK_PASSWORD=$(kubectl get secret kagenti-test-users -n keycloak \
  -o jsonpath='{.data.admin-password}' | base64 -d)
export KAGENTI_UI_URL=https://kagenti-ui-kagenti-system.apps.kagenti-team-sbox42.octo-emerging.redhataicoe.com
export KEYCLOAK_USER=admin CI=true

# Clean (only delete rca-agent — tests clean it in beforeAll)
kubectl delete deploy rca-agent -n team1 --ignore-not-found

# Run core 5 + consistency test
cd .worktrees/sandbox-agent/kagenti/ui-v2
npx playwright test e2e/sandbox-sessions.spec.ts e2e/sandbox-walkthrough.spec.ts \
  e2e/sandbox-variants.spec.ts e2e/agent-rca-workflow.spec.ts \
  e2e/sandbox-delegation.spec.ts e2e/agent-loop-consistency.spec.ts \
  --workers=4 --reporter=list

# Analyze sessions after test
kubectl exec -n team1 postgres-sessions-0 -- psql -U kagenti -d sessions \
  -c "SELECT context_id, max(metadata::json->>'agent_name') as agent,
      CASE WHEN max(metadata::text) LIKE '%loop_events%' THEN 'YES' ELSE 'no' END as loops
      FROM tasks WHERE metadata IS NOT NULL
      GROUP BY context_id ORDER BY max(status::json->>'timestamp') DESC"
```

### Build → Deploy cycle
```bash
# Push changes
cd .worktrees/sandbox-agent && git push origin feat/sandbox-agent
cd .worktrees/agent-examples && git push origin feat/sandbox-agent

# Trigger builds
oc start-build kagenti-ui -n kagenti-system
oc start-build kagenti-backend -n kagenti-system
oc start-build sandbox-agent -n team1

# Wait + restart
kubectl rollout restart deployment/kagenti-ui deployment/kagenti-backend -n kagenti-system
kubectl rollout restart deployment/sandbox-legion -n team1
```

---

## Key Files

| File | Purpose |
|------|---------|
| `kagenti/ui-v2/src/pages/SandboxPage.tsx` | Main page — SSE handler, history reconstruction, state management |
| `kagenti/ui-v2/src/components/AgentLoopCard.tsx` | Loop card rendering |
| `kagenti/ui-v2/src/components/LoopDetail.tsx` | Step detail with badges + tokens |
| `kagenti/ui-v2/src/components/SidecarTab.tsx` | Compact sidecar panel |
| `kagenti/ui-v2/src/components/SubSessionsPanel.tsx` | Child sessions tab |
| `kagenti/ui-v2/src/types/agentLoop.ts` | AgentLoop + NodeEventType types |
| `kagenti/backend/app/routers/sandbox.py` | SSE proxy, metadata, history endpoint |
| `kagenti/backend/app/services/sidecar_manager.py` | Sidecar lifecycle |
| `kagenti/backend/app/services/sidecars/looper.py` | Auto-continue logic |
| `agent-examples/.../event_serializer.py` | Graph node → JSON event |
| `agent-examples/.../event_schema.py` | Typed event dataclasses |
| `agent-examples/.../reasoning.py` | Planner/executor/reflector/reporter nodes |
