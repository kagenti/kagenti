# Session V Passover — Loop Event Pipeline, Rendering Parity, Agent Reasoning

> **Date:** 2026-03-10
> **Previous Session:** U (passover at docs/plans/2026-03-09-session-U-passover.md)
> **Cluster:** sbox42 (Llama 4 Scout via LiteLLM proxy)
> **Worktrees:** `.worktrees/sandbox-agent` (kagenti), `.worktrees/agent-examples` (agent code)
> **Test baseline:** 170/171 passed, 0 failed (consistent across v6-v8 runs)

## What Session V Delivered

### Pipeline Parity (Design Doc + Implementation)

| Change | Files |
|--------|-------|
| **Design doc**: 5-stage pipeline with exact JSON structures | `docs/plans/2026-03-09-loop-event-pipeline-design.md` |
| **Shared `loopBuilder.ts`**: single `applyLoopEvent()` used by both SSE streaming and history | `ui-v2/src/utils/loopBuilder.ts`, `SandboxPage.tsx` |
| **Backend legacy filtering**: `plan`, `plan_step`, `reflection`, `llm_response` no longer forwarded | `sandbox.py` |
| **Pipeline logging**: SERIALIZE, A2A_EMIT, LOOP_FWD, FLAT_FWD, HISTORY at all 5 stages | `sandbox.py`, `event_serializer.py`, `agent.py` |

### Backend Fixes

| Change | Root Cause |
|--------|-----------|
| **Per-task metadata isolation** | `finally` block was merging metadata across all task rows |
| **SSE keepalive pings** (15s) | Nginx 300s timeout killed slow agent connections |
| **`stream_task_id` from A2A taskId** | `_set_owner_metadata` couldn't find task row (A2A SDK race) |
| **Remove dangerous ORDER BY DESC fallback** | Could target wrong task in multi-turn sessions |
| **Remove user message dedup** | Identical messages across tasks were being collapsed |
| **Recover loop events from history text** | Tasks with 0 loop_events but events in history messages |
| **Incomplete loops shown as failed** | Loops without reporter_output now show red "failed" status |
| **Fix stale "working" status** | Sessions showing "Active" after agent completed |
| **Sidecar state persistence** | Backend restart lost all sidecar handles |
| **None metadata crash in sidecar restore** | `json.loads("null")` returns None, not dict |

### Agent Fixes

| Change | Root Cause |
|--------|-----------|
| **`_safe_format()` for prompts** | `{...}` in executor prompt crashed `.format()` |
| **Shielded graph execution** | Client disconnect cancelled LangGraph via CancelledError |
| **Reflector: no step-count forced done** | `current_step + 1 >= len(plan)` was forcing done prematurely |
| **Reflector: stall detection reset after replan** | Previous "replan" decisions counted as no-tool iterations |
| **Replanner context: original plan with step status** | Replanner didn't know what was already completed |
| **Budget configurable via env vars** | `SANDBOX_*` env vars for all budget parameters |
| **Improved stall detection** | Threshold 3→2, identical-output detection, replan-loop detection |

### Frontend Fixes

| Change | Root Cause |
|--------|-----------|
| **Replan preservation** | Last replan was overwriting `loop.plan` |
| **ReplanSection component** | Replans shown as collapsible entries below original plan |
| **Test isolation** | `sandbox-debug.spec.ts` was reusing sessions from other tests |

## Remaining Issues

### 1. RCA Agent Multi-Iteration Timeout
The RCA agent on Llama 4 Scout takes >3 minutes for complex CI analysis. The test timeout (180s) cuts the stream short. The shielded graph execution helps (agent finishes in background) but the SSE events after disconnect are still lost. The recovery fallback extracts events from history text, so the UI shows the loop card — but it's marked as "failed" if the reporter didn't run before the test ended.

### 2. Plan Quality with Llama 4 Scout
The planner creates single-step "Respond to the user" plans for tasks that need multi-step tool usage. This is an LLM quality issue — the planner prompt is correct but Llama 4 Scout doesn't follow it well. Replans produce the same trivial plan because the model ignores the step-status context.

### 3. Sidecar Auto-Continue
The looper sidecar polls DB but can't track child session context_ids. Needs message queuing (next phase).

## Architecture Reference

### Loop Event Pipeline (5 Stages)

```
Agent (LangGraph) → Serializer (JSON lines) → A2A SDK (TaskStatusUpdate)
    → Backend SSE Proxy (extract loop_id, forward, persist)
        → Frontend (applyLoopEvent → AgentLoop → AgentLoopCard)
```

See `docs/plans/2026-03-09-loop-event-pipeline-design.md` for full details.

### Key Design Principles
1. **Single source of truth**: `loop_events` in task metadata
2. **Idempotent reconstruction**: `applyLoopEvent()` is pure — same events, same output
3. **No legacy types in pipeline**: filtered at backend before forwarding
4. **Per-task isolation**: `stream_task_id` from A2A taskId, no cross-task writes
5. **Observable pipeline**: structured logging at every stage boundary

## Test Commands

```bash
cd .worktrees/sandbox-agent/kagenti/ui-v2
export KUBECONFIG=~/clusters/hcp/kagenti-team-sbox42/auth/kubeconfig
export KEYCLOAK_PASSWORD=$(kubectl get secret kagenti-test-users -n keycloak -o jsonpath='{.data.admin-password}' | base64 -d)
export KAGENTI_UI_URL=https://kagenti-ui-kagenti-system.apps.kagenti-team-sbox42.octo-emerging.redhataicoe.com
export KEYCLOAK_USER=admin CI=true

# Full suite
npx playwright test e2e/ --workers=4 --reporter=list

# Clean DB
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
```

## Key Files

| File | Purpose |
|------|---------|
| `kagenti/ui-v2/src/utils/loopBuilder.ts` | Shared loop event processing (NEW) |
| `kagenti/ui-v2/src/pages/SandboxPage.tsx` | SSE handler + history reconstruction (refactored) |
| `kagenti/ui-v2/src/components/LoopDetail.tsx` | Step/tool/reasoning detail + ReplanSection |
| `kagenti/backend/app/routers/sandbox.py` | SSE proxy, history endpoint, metadata persistence |
| `kagenti/backend/app/services/sidecar_manager.py` | Sidecar state persistence |
| `agent-examples/.../event_serializer.py` | LangGraph → JSON events + SERIALIZE logging |
| `agent-examples/.../reasoning.py` | Plan/execute/reflect/report node logic |
| `agent-examples/.../agent.py` | Shielded graph execution + A2A_EMIT logging |
| `agent-examples/.../budget.py` | Configurable budget via SANDBOX_* env vars |
| `docs/plans/2026-03-09-loop-event-pipeline-design.md` | Pipeline design doc |
