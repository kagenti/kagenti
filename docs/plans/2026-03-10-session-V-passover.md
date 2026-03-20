# Session V Passover — Loop Event Pipeline, Rendering Parity, Agent Reasoning

> **Date:** 2026-03-10
> **Previous Session:** U (passover at docs/plans/2026-03-09-session-U-passover.md)
> **Cluster:** sbox42 (Llama 4 Scout via LiteLLM proxy)
> **Worktrees:** `.worktrees/sandbox-agent` (kagenti), `.worktrees/agent-examples` (agent code)
> **Test baseline:** 169-171 passed, 0 failed (consistent across v6-v8 runs, ~21 min)
> **Cost:** ~$600, ~16h wall time

## CRITICAL FOR SESSION W — START HERE

### 1. GitHub PAT Token Not Available to Agents

The sandbox agents have no `GH_TOKEN` or `GITHUB_TOKEN` env var. We patched it manually:

```bash
kubectl set env deployment/sandbox-legion deployment/sandbox-basic deployment/sandbox-hardened deployment/sandbox-restricted deployment/sandbox-agent \
  -n team1 --from=secret/github-token-secret --prefix=GITHUB_PAT_
```

But the secret has **placeholder values** (`ghp_REPLACE_WITH_GITHUB_TOKEN`). Need:
1. Update `github-token-secret` in team1 with real PAT
2. Add `GITHUB_PAT_TOKEN` env var to agent deployment template in Helm chart (`charts/kagenti/`)
3. Add GitHub token field to the import wizard so users can configure it per agent
4. The planner prompt tells executor to `export GH_TOKEN=$GITHUB_PAT_TOKEN` — verify this works

### 2. Agent Loop UI Rendering — Mostly Working, Needs Polish

The loop event pipeline is working end-to-end. Sessions show AgentLoopCards with plan/executor/reflector/reporter steps. Remaining UI issues:

- **Plan shows "Respond to the user"** for some tasks — fixed planner prompt (build 53), but Llama 4 Scout still sometimes ignores instructions
- **Replans show as separate entries** but the plan block should show original plan and highlight which steps changed
- **Step input/output not clearly visible** — each step should show what was asked (from plan) and what happened (tool calls + results) as expandable blocks
- **"Step completed" message** from executor dedup leaks into final answer sometimes

### 3. History Fallback Extraction — Critical Fix Found

The history endpoint's fallback extraction (recovering loop events from agent message text when metadata has 0 loop_events) had a bug: `persisted_loop_events` was assigned AFTER the metadata loop but BEFORE the history extraction loop. **Fixed in build 77** (commit `ff1f3925`). This was the root cause of RCA sessions showing "old format."

### 4. `stream_task_id` Persistence — Still Fragile

Even with A2A taskId capture from the first SSE event, the `finally` block sometimes fails to persist loop_events silently. Diagnostic logging added (build 75) but the root cause isn't fully understood. The history extraction fallback covers this gap.

---

## What Session V Delivered

### Pipeline Parity (Design Doc + Implementation)

| Change | Files |
|--------|-------|
| **Design doc**: 5-stage pipeline with exact JSON structures at each boundary | `docs/plans/2026-03-09-loop-event-pipeline-design.md` |
| **Shared `loopBuilder.ts`**: single `applyLoopEvent()` used by both SSE streaming and history | `ui-v2/src/utils/loopBuilder.ts`, `SandboxPage.tsx` |
| **Backend legacy filtering**: `plan`, `plan_step`, `reflection`, `llm_response` no longer forwarded | `sandbox.py` |
| **Pipeline logging**: SERIALIZE, A2A_EMIT, LOOP_FWD, FLAT_FWD, HISTORY at all 5 stages | `sandbox.py`, `event_serializer.py`, `agent.py` |
| **History fallback extraction**: recover loop events from agent message text | `sandbox.py` |

### Backend Fixes (12 changes)

| Change | Root Cause |
|--------|-----------|
| **Per-task metadata isolation** | `finally` block was merging metadata across all task rows |
| **SSE keepalive pings** (15s) | Nginx 300s timeout killed slow agent connections |
| **`stream_task_id` from A2A taskId** | `_set_owner_metadata` couldn't find task row (A2A SDK race) |
| **Remove dangerous ORDER BY DESC fallback** | Could target wrong task in multi-turn sessions |
| **Remove user message dedup** | Identical messages across tasks were being collapsed |
| **Recover loop events from history text** | Tasks with 0 loop_events but events in history messages |
| **Fix persisted_loop_events assignment order** | Fallback extraction ran but was never returned to frontend |
| **Incomplete loops shown as failed** | Loops without reporter_output now show red "failed" status |
| **Fix stale "working" status** | Sessions showing "Active" after agent completed |
| **Sidecar state persistence** | Backend restart lost all sidecar handles |
| **None metadata crash in sidecar restore** | `json.loads("null")` returns None, not dict |
| **Diagnostic logging in finally block** | Track row_found, loop_events count, persisted flag |

### Agent Fixes (9 changes)

| Change | Root Cause |
|--------|-----------|
| **`_safe_format()` for prompts** | `{...}` in executor prompt crashed `.format()` |
| **Shielded graph execution** | Client disconnect cancelled LangGraph via CancelledError |
| **Reflector: no step-count forced done** | `current_step + 1 >= len(plan)` was forcing done prematurely |
| **Reflector: stall detection reset after replan** | Previous "replan" decisions counted as no-tool iterations |
| **Replanner context: original plan with step status** | Replanner didn't know what was already completed |
| **Planner prompt: remove "Respond to the user" pattern** | Llama 4 Scout latched onto it for every request |
| **Planner prompt: default to proper multi-step planning** | Removed single-step constraint |
| **Budget configurable via env vars** | `SANDBOX_*` env vars for all budget parameters |
| **Improved stall detection** | Threshold 3->2, identical-output detection, replan-loop detection |

### Frontend Fixes (4 changes)

| Change | Root Cause |
|--------|-----------|
| **Replan preservation** | Last replan was overwriting `loop.plan` |
| **ReplanSection component** | Replans shown as collapsible entries below original plan |
| **Test isolation** | `sandbox-debug.spec.ts` was reusing sessions from other tests |
| **Incomplete loops as "failed"** | Red indicator + "interrupted" message vs showing nothing |

---

## Remaining Issues (P0 for Session W)

### 1. GitHub PAT Token Deployment
See Critical section above. Needs Helm chart + wizard changes.

### 2. Agent Loop UI Polish
The AgentLoopCard shows the flow but needs clearer step-by-step rendering:
- Each step should show: description (from plan) -> tool calls -> tool results -> status
- Replans should show what changed vs original plan
- The "Step completed" dedup message shouldn't leak into final answers

### 3. RCA Test Expects Old Format
`agent-rca-workflow.spec.ts` line 147 waits for `.sandbox-markdown` or `Tool Call:|Result:` text (old format). Should be updated to expect `[data-testid="agent-loop-card"]`.

### 4. Sidecar Auto-Continue (Unchanged)
The looper sidecar polls DB but can't track child session context_ids. Needs message queuing.

### 5. `stream_task_id` Finally Block Persistence
The `finally` block sometimes fails to persist loop_events even when `stream_task_id` is set. The diagnostic logging (build 75) should help diagnose on next occurrence. The history extraction fallback covers this gap.

### 6. Plan Quality with Llama 4 Scout
Even with improved prompts, Llama 4 Scout sometimes produces trivial single-step plans. The fast-path `_is_trivial_text_request()` handles "Say exactly:" patterns in code, but the LLM planner still occasionally outputs "Respond to the user" for tool-requiring tasks.

---

## Architecture Reference

### Loop Event Pipeline (5 Stages)

```
Stage 1: Agent (LangGraph nodes) -> LangGraphSerializer -> JSON lines
         Log: SERIALIZE session=X loop=Y type=Z step=N

Stage 2: Agent agent.py -> A2A SDK TaskUpdater -> EventQueue
         Log: A2A_EMIT session=X lines=N types=[...]

Stage 3: Backend sandbox.py -> SSE proxy -> extract loop_id -> forward + persist
         Log: LOOP_FWD session=X loop=Y type=Z step=N
         Log: FLAT_FWD session=X content_len=N (when no loop events)

Stage 4: Backend sandbox.py -> history endpoint -> read from DB + fallback extraction
         Log: HISTORY session=X tasks=N total_events=N unique=N types=[...]

Stage 5: Frontend SandboxPage.tsx -> applyLoopEvent() -> AgentLoop -> AgentLoopCard
         Log: [sse] LOOP_RECV loop=Y type=Z step=N
         Log: [history] LOOP_REBUILD events=N types=[...]
```

See `docs/plans/2026-03-09-loop-event-pipeline-design.md` for full JSON structures at each boundary.

### Key Design Principles
1. **Single source of truth**: `loop_events` in task metadata (with history text fallback)
2. **Idempotent reconstruction**: `applyLoopEvent()` is pure — same events, same output
3. **No legacy types in pipeline**: filtered at backend before forwarding
4. **Per-task isolation**: `stream_task_id` from A2A taskId, no cross-task writes
5. **Observable pipeline**: structured logging at every stage boundary

### A2A Protocol Flow
```
Browser -> Backend: POST /sandbox/{ns}/chat/stream {message, session_id, agent_name}
Backend -> Agent:   JSON-RPC message/stream {params: {message: {role, parts, contextId}}}
Agent -> Backend:   SSE data: {result: {kind: "status-update", taskId, status: {message: {parts: [{text: "JSON\nlines"}]}}}}
Backend -> Browser: SSE data: {session_id, loop_id, loop_event: {type, loop_id, ...}}
```

The loop events are JSON-encoded inside `message.parts[0].text` (double JSON encoding).
Backend extracts them by splitting on newlines and parsing each line.

---

## Tips and Tricks

### Build -> Deploy -> Test Cycle
```bash
# Push changes
cd .worktrees/sandbox-agent && git push origin feat/sandbox-agent
cd .worktrees/agent-examples && git push origin feat/sandbox-agent

# Trigger builds (all 3)
KUBECONFIG=~/clusters/hcp/kagenti-team-sbox42/auth/kubeconfig
oc start-build kagenti-ui -n kagenti-system
oc start-build kagenti-backend -n kagenti-system
oc start-build sandbox-agent -n team1

# Wait for builds (~1-3 min each)
oc get build kagenti-ui-NNN kagenti-backend-NNN -n kagenti-system --no-headers
oc get build sandbox-agent-NNN -n team1 --no-headers

# Restart all
oc rollout restart deployment/kagenti-ui deployment/kagenti-backend -n kagenti-system
oc rollout restart deployment/sandbox-agent deployment/sandbox-legion deployment/sandbox-basic deployment/sandbox-hardened deployment/sandbox-restricted -n team1

# Clean DB (MUST wait for backend pod to be ready first)
sleep 30
kubectl exec deployment/kagenti-backend -n kagenti-system -- python3 -c "
import os, sys; sys.path.insert(0, '/app'); os.chdir('/app')
import asyncio
from app.services.session_db import get_session_pool
async def c():
    pool = await get_session_pool('team1')
    async with pool.acquire() as conn:
        n = await conn.fetchval('SELECT count(*) FROM tasks')
        await conn.execute('DELETE FROM tasks')
        print(f'Deleted {n} tasks')
asyncio.run(c())
"

# Run tests
cd .worktrees/sandbox-agent/kagenti/ui-v2
export KEYCLOAK_PASSWORD=$(kubectl get secret kagenti-test-users -n keycloak -o jsonpath='{.data.admin-password}' | base64 -d)
export KAGENTI_UI_URL=https://kagenti-ui-kagenti-system.apps.kagenti-team-sbox42.octo-emerging.redhataicoe.com
export KEYCLOAK_USER=admin CI=true
npx playwright test e2e/ --workers=4 --reporter=list
```

### Debugging Pipeline Issues
```bash
# Correlate events across stages for a session
SESSION=<session_id>

# Stage 1-2: Agent serialized + emitted
kubectl logs deploy/sandbox-legion -n team1 | grep "SERIALIZE session=$SESSION"
kubectl logs deploy/sandbox-legion -n team1 | grep "A2A_EMIT session=$SESSION"

# Stage 3: Backend forwarded
kubectl logs deploy/kagenti-backend -n kagenti-system | grep "LOOP_FWD session=$SESSION"

# Stage 4: History returned
kubectl logs deploy/kagenti-backend -n kagenti-system | grep "HISTORY session=$SESSION"

# Check DB directly
kubectl exec deploy/kagenti-backend -n kagenti-system -- python3 -c "
import os,sys,json;sys.path.insert(0,'/app');os.chdir('/app')
import asyncio
from app.services.session_db import get_session_pool
async def c():
 pool=await get_session_pool('team1')
 async with pool.acquire() as conn:
  rows=await conn.fetch(\"SELECT id,metadata FROM tasks WHERE context_id='$SESSION'\")
  for r in rows:
   meta=json.loads(r['metadata']) if r['metadata'] else {}
   le=meta.get('loop_events',[])
   print(f'task={r[\"id\"][:12]} loop_events={len(le)}')
asyncio.run(c())
"
```

### Common Gotchas
- **Backend namespace mismatch**: `oc rollout restart` needs `-n kagenti-system` for backend/UI, `-n team1` for agents. Can't mix in one command.
- **DB cleanup kills loop_events but not A2A task history**: The A2A SDK stores messages in the same DB. After cleanup, sessions appear empty in the sidebar but if the agent pod wasn't restarted, its in-memory state may still serve old data.
- **TypeScript needs `cd` to ui-v2**: `npx tsc --noEmit` must run from `kagenti/ui-v2/`, not the repo root.
- **ruff format modifies files**: Pre-commit hook runs ruff-format which may modify Python files. If commit fails, re-stage and commit again.
- **Agent builds are in team1 namespace**: `oc start-build sandbox-agent -n team1`, not kagenti-system.
- **Keycloak realm is "demo"**: Token URL is `https://keycloak.../realms/demo/protocol/openid-connect/token`, not "kagenti".

---

## Key Files

| File | Purpose |
|------|---------|
| `kagenti/ui-v2/src/utils/loopBuilder.ts` | Shared loop event processing (NEW in V) |
| `kagenti/ui-v2/src/pages/SandboxPage.tsx` | SSE handler + history reconstruction (refactored in V) |
| `kagenti/ui-v2/src/components/LoopDetail.tsx` | Step/tool/reasoning detail + ReplanSection |
| `kagenti/ui-v2/src/components/AgentLoopCard.tsx` | Loop card with failed/done/active status |
| `kagenti/ui-v2/src/types/agentLoop.ts` | AgentLoop + AgentLoopStep types |
| `kagenti/backend/app/routers/sandbox.py` | SSE proxy, history endpoint, metadata persistence |
| `kagenti/backend/app/services/sidecar_manager.py` | Sidecar state persistence |
| `kagenti/backend/app/services/session_db.py` | Per-namespace PostgreSQL pool manager |
| `agent-examples/.../event_serializer.py` | LangGraph -> JSON events + SERIALIZE logging |
| `agent-examples/.../reasoning.py` | Plan/execute/reflect/report node logic |
| `agent-examples/.../agent.py` | Shielded graph execution + A2A_EMIT logging |
| `agent-examples/.../budget.py` | Configurable budget via SANDBOX_* env vars |
| `agent-examples/.../graph.py` | LangGraph build, tool binding, routing |
| `docs/plans/2026-03-09-loop-event-pipeline-design.md` | Pipeline design doc |

## Commits (kagenti worktree)

```
8f72c40e  Per-task metadata isolation, SSE keepalive, sidecar persistence, replan UI
7ca29fa7  Handle None metadata in sidecar restore
645df162  Capture stream_task_id from A2A taskId
a92c56fe  Remove user message dedup
68f3bbcb  Capture stream_task_id from first A2A event
1d402d09  Recover loop events when stream cut short
5726bbbb  Test isolation: sandbox-debug navigates directly
c9fb8e61  Show incomplete loops as failed, recover events from history
607accd2  Correct stale 'working' status for completed sessions
a4e4fbb3  Remove dangerous ORDER BY DESC fallback
379893d8  Diagnostic logging in finally block
ff1f3925  Fix history fallback extraction assignment order (ROOT CAUSE of old format)
2a5039dd  Shared loopBuilder, backend legacy filtering, pipeline logging
3ef1b344  Session V passover doc
```

## Commits (agent-examples worktree)

```
622ab48   safe_format, stall detection, budget env vars
40bee51   SERIALIZE and A2A_EMIT pipeline logging
2cc4031   Shielded graph execution from client disconnect
4926c33   Original plan with step status in replan context
558d98f   Stall detection reset after replan boundary
e7b344d   Reflector no longer forces done based on step count
891c8c3   Planner prompt: proper multi-step planning, GH_TOKEN example
```
