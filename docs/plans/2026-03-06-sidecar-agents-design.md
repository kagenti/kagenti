# Sidecar Agents Design

> **Date:** 2026-03-06
> **Session:** P (Sidecar Agents)
> **Status:** Backend + UI implemented, Playwright tests need tuning
> **Cluster:** sandbox42 (sandbox44 destroyed)
> **Worktree:** `.worktrees/sidecar-agents` on `feat/sidecar-agents` (rebased onto `feat/sandbox-agent`)
> **Deploy from:** The sidecar-agents worktree
> **Integration:** Cherry-pick commits to `.worktrees/sandbox-agent/` for integration testing
>
> ## Implementation Status (Session P — 2026-03-08)
>
> **What works:**
> - Backend SidecarManager: enable/disable/config/list/approve/deny APIs all functional
> - SSE fan-out from sandbox.py and chat.py to SidecarManager event queue
> - Looper, Hallucination Observer, Context Guardian analyzers run as asyncio tasks
> - UI SidecarTab component: enable/disable switch, auto-approve toggle, SSE observation stream
> - UI tab bar: dynamic sidecar tabs appear/disappear, badge counts, HITL badges
> - Playwright tests: auth works, API calls succeed, tabs appear — tested on sandbox42
>
> **What needs work (L+1):**
> - Looper observation emission: currently only emits on detected loops (3+ repeated tool calls).
>   Needs a "heartbeat" observation ("Monitoring... N tool calls seen, no loops detected") so tests
>   can verify the sidecar is active without requiring the agent to actually loop.
> - Playwright test timeout: 45s wait for first observation is too short if agent task hasn't
>   generated enough tool calls. Either increase timeout or add heartbeat observations.
> - Image rebuild: sandbox42 used pre-rebase image (functionally identical). Next deploy should
>   rebuild from the rebased `feat/sidecar-agents` branch.
> - A2A message injection: the "inject corrective message into parent session" path is stubbed
>   (TODO in sidecar_manager.py). Needs implementation to complete the HITL intervention flow.
>
> **Commits on `feat/sidecar-agents` (rebased onto `feat/sandbox-agent`):**
> ```
> 84c109bb feat(sidecar): implement sidecar agents framework
> 1f42e1a1 feat(ui): add sidecar agent tabs, SidecarTab component, and sidecar API service
> a35a942e fix(ui): use size="sm" instead of isSmall for PatternFly v5 Button
> bd338001 fix(test): add auth headers to sidecar API calls in Playwright tests
> ```

## Goal

Design and implement sidecar agents that run alongside sandbox sessions. Sidecars
observe session activity, detect problems (stuck loops, hallucinations, context bloat),
and intervene with corrective messages gated by HITL or auto-approve toggles.

## Core Concepts

**Sidecar agents** are system sub-agents that run alongside a parent sandbox session.
Each sidecar:

- Is a **LangGraph agent** with its own `context_id`, checkpointed state, and message history
- Has `session_type: "sidecar"` and a `parent_context_id` linking to the root session
- Can **read** the parent session's SSE event stream and workspace files
- Can **write** corrective messages into the parent session (gated by HITL or auto-approve toggle)
- Runs **in-process** in the FastAPI backend as an `asyncio.Task`
- Survives backend restarts via LangGraph checkpoint (loads latest state on re-enable)
- Can be **enabled/disabled** instantly -- disable cancels the asyncio task, enable resumes from checkpoint

## Initial Sidecar Agents

| Name | Trigger | Purpose |
|------|---------|---------|
| **Looper** | Event-driven (watches turn completion) | Auto-continue kicker: when agent finishes a turn, sends "continue" to keep it going. Configurable iteration limit -- stops and invokes HITL when reached. Pauses when session is waiting on HITL. Counter is resettable. |
| **Hallucination Observer** | SSE event-driven | Monitors for fabricated file paths, APIs, or imports. Validates against workspace. Comments with corrections. |
| **Context Budget Guardian** | SSE event-driven | Tracks token usage trajectory. Warns on sharp growth. Suggests what to stop doing. |

## Architecture

```
+---------------------------------------------------------------------+
| UI (SandboxPage.tsx)                                                |
|                                                                     |
|  +----------+---------+--------------------+----------------------+ |
|  |  Chat    | Looper  | Hallucination Obs. | Context Guardian     | |
|  |  (tab)   | (tab)   | (tab)              | (tab)                | |
|  +----------+---------+--------------------+----------------------+ |
|  Each tab: toggle [Auto/HITL] + badge count + observation stream    |
|  HITL badge on parent Chat tab when intervention pending            |
+---------------+-----------------------------------------------------+
                | SSE (per sidecar sub-session) + REST API
                |
+---------------v-----------------------------------------------------+
| Backend (FastAPI)                                                    |
|                                                                      |
|  SSE Proxy --> asyncio.Queue (per session)                           |
|                    |                                                 |
|  SidecarManager    |                                                 |
|  +-- registry: Dict[session_id, Dict[sidecar_type, SidecarHandle]]  |
|  |                                                                   |
|  +-- Looper (asyncio.Task)                                           |
|  |   +-- periodic timer -> read parent state -> detect loops         |
|  |       +-- LangGraph agent, own checkpointer                      |
|  |                                                                   |
|  +-- HallucinationObserver (asyncio.Task)                            |
|  |   +-- consumes SSE queue -> validate paths/APIs                   |
|  |       +-- LangGraph agent, own checkpointer                      |
|  |                                                                   |
|  +-- ContextBudgetGuardian (asyncio.Task)                            |
|      +-- consumes SSE queue -> track token trajectory                |
|          +-- LangGraph agent, own checkpointer                      |
|                                                                      |
|  Intervention path:                                                  |
|  sidecar observation -> [auto-approve?] -> inject A2A msg to parent  |
|                         [HITL?] -> pending approval -> UI badge      |
+---------------+-----------------------------------------------------+
                | A2A JSON-RPC 2.0
                |
+---------------v-----------------------------------------------------+
| Agent Pod (sandbox-legion)                                           |
|  +-- Receives corrective messages as regular user-role A2A input     |
+---------------------------------------------------------------------+
```

## Key Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Event source | SSE stream subscription | Decoupled, sidecars see what flows through the backend |
| Where they run | In-process asyncio.Tasks in FastAPI backend | Lightweight, no new pods, zero network overhead |
| Session model | System sub-sessions with own LangGraph identity | Own context_id, checkpointed state, own message history |
| Message flow | Own tab for observations; HITL-gated injection into parent chat | Observations don't pollute main chat; interventions require approval |
| UI layout | Tabs above chat area | Simple, PatternFly tabs, full-height view per sidecar |
| Per-sidecar control | Toggle: Auto-approve / HITL | Each sidecar independently configurable |
| State persistence | LangGraph checkpointer (option B) | No extra tables; LangGraph auto-loads latest compacted state on restart |
| Trigger model | Per-sidecar: periodic (Looper) or SSE-driven (others) | Different sidecars need different observation patterns |

## Data Model

### SidecarHandle (in-memory, per active sidecar)

```python
@dataclass
class SidecarHandle:
    task: asyncio.Task
    context_id: str            # e.g. "sidecar-looper-{parent_context_id[:12]}"
    sidecar_type: str          # "looper" | "hallucination_observer" | "context_guardian"
    parent_context_id: str
    enabled: bool
    auto_approve: bool
    config: dict               # type-specific settings
```

### Sidecar config per type

| Sidecar | Config Keys | Defaults |
|---------|------------|----------|
| Looper | `interval_seconds`, `counter_limit` | 30, 3 |
| Hallucination Observer | (none yet) | -- |
| Context Budget Guardian | `warn_threshold_pct`, `critical_threshold_pct` | 60, 80 |

### Session metadata (stored in LangGraph checkpoint)

```json
{
  "session_type": "sidecar",
  "sidecar_type": "looper",
  "parent_context_id": "abc123...",
  "auto_approve": false,
  "config": {"interval_seconds": 30, "counter_limit": 3}
}
```

## API Endpoints

```
GET  /api/v1/sandbox/{ns}/sessions/{ctxId}/sidecars
     -> List all sidecars for session, their status, config

POST /api/v1/sandbox/{ns}/sessions/{ctxId}/sidecars/{type}/enable
     -> Spawn asyncio task, load from checkpoint if exists

POST /api/v1/sandbox/{ns}/sessions/{ctxId}/sidecars/{type}/disable
     -> Cancel asyncio task (CancelledError handler flushes checkpoint)

PUT  /api/v1/sandbox/{ns}/sessions/{ctxId}/sidecars/{type}/config
     -> Update config (interval, counter_limit, auto_approve, etc.)
     -> Hot-reloads into running task

POST /api/v1/sandbox/{ns}/sessions/{ctxId}/sidecars/{type}/reset
     -> Looper-specific: reset loop counter

GET  /api/v1/sandbox/{ns}/sessions/{ctxId}/sidecars/{type}/observations
     -> SSE stream of sidecar's observation messages

POST /api/v1/sandbox/{ns}/sessions/{ctxId}/sidecars/{type}/approve/{msgId}
POST /api/v1/sandbox/{ns}/sessions/{ctxId}/sidecars/{type}/deny/{msgId}
     -> HITL approval/denial for pending interventions
```

## Enable/Disable Lifecycle

### On disable:
1. `handle.task.cancel()` -- asyncio sends `CancelledError` to the task
2. Task's `except CancelledError` handler flushes pending state to LangGraph checkpoint
3. Remove from active registry
4. LangGraph state persists in DB -- nothing lost

### On enable:
1. Create new `asyncio.Task` for the sidecar
2. LangGraph loads from last checkpoint (if exists) -- resumes where it left off
3. Register in active registry
4. Looper: start periodic timer. SSE-driven: subscribe to queue.

### On session end:
1. Cancel all sidecar tasks for that session
2. Cleanup queue references

## Sidecar Behaviors

### Looper (Auto-Continue Kicker)

1. Watches SSE events for turn completion (COMPLETED/FAILED status)
2. Does NOT kick when session is waiting on HITL (INPUT_REQUIRED)
3. On completion: sends "continue" A2A message to the agent
4. Increments kick counter
5. Emits observation: "Kicked agent to continue. Iteration 2/5."
6. When counter hits `counter_limit`: stops, emits HITL intervention
   - "Iteration limit reached: 5/5. Agent stopped. Reset counter to continue."
7. If auto-approve: resets counter and keeps kicking
8. Reset button: clears counter, Looper resumes kicking on next completion

### Hallucination Observer

1. Receives SSE events from parent queue
2. Filters for tool calls that reference file paths, API endpoints, import statements
3. Validates against workspace (calls sandbox files API: `GET /sandbox/{ns}/files/{agent}?path=...`)
4. On invalid path/import: emits observation
   "File `/workspace/src/nonexistent.py` does not exist. Did you mean `/workspace/src/existing.py`?"
5. If auto-approve: injects correction into parent chat
6. If HITL: shows pending badge, user approves/denies

### Context Budget Guardian

1. Receives SSE events, tracks token counts from status updates
2. Maintains trajectory: tokens per turn, growth rate
3. At `warn_threshold_pct`: emits observation
   "Context at 60%. Consider summarizing or stopping verbose tool output."
4. At `critical_threshold_pct`: emits intervention
   "Context at 80%. Recommend: stop reading large files, compact conversation."
5. If auto-approve at critical: injects warning into parent chat

## UI Components

### Tab bar (above chat area)
- `Chat` tab -- existing sandbox chat (default)
- One tab per enabled sidecar: `Looper`, `Hallucination Observer`, `Context Guardian`
- Each tab shows: name + badge count (unread observations) + HITL pending indicator
- Disabled sidecars don't show tabs

### Sidecar tab content
- Header: toggle [Auto/HITL], config button (opens settings popover), enable/disable switch
- Observation stream: chronological list of sidecar messages (reuse EventsPanel-style rendering)
- Pending interventions: highlighted with Approve/Deny buttons
- Looper-specific: loop counter display, reset button

### Parent Chat tab
- When a sidecar intervention is approved (or auto-approved), the corrective message appears
  inline with a visual indicator: `[Looper]` prefix and distinct left-border color
- HITL badge on Chat tab when any sidecar has pending intervention

## Development & Deployment

| Item | Detail |
|------|--------|
| **Worktree** | New worktree branched from `.worktrees/sandbox-agent` (`feat/sandbox-agent`) -> `feat/sidecar-agents` |
| **Cluster** | sandbox44 (`export KUBECONFIG=~/clusters/hcp/kagenti-team-sandbox44/auth/kubeconfig`) |
| **Deploy** | Deploy sandbox44 from the new sidecar-agents worktree |
| **Testing** | TDD on sandbox44; once tests green, cherry-pick to `.worktrees/sandbox-agent/` for integration testing |
| **Backend changes** | New router `sidecar.py`, new service `sidecar_manager.py`, modifications to `chat.py` SSE proxy for queue fan-out |
| **UI changes** | Tab bar in SandboxPage, SidecarTab component, config popovers |
| **No new CRDs** | Sidecars are in-process, no Kubernetes resources needed |

## Files to Create/Modify

| File | Change |
|------|--------|
| `kagenti/backend/app/routers/sidecar.py` | NEW: Sidecar REST + SSE endpoints |
| `kagenti/backend/app/services/sidecar_manager.py` | NEW: SidecarManager, SidecarHandle, lifecycle |
| `kagenti/backend/app/services/sidecars/looper.py` | NEW: Looper LangGraph agent |
| `kagenti/backend/app/services/sidecars/hallucination_observer.py` | NEW: Hallucination Observer agent |
| `kagenti/backend/app/services/sidecars/context_guardian.py` | NEW: Context Budget Guardian agent |
| `kagenti/backend/app/routers/chat.py` | MODIFY: Add queue fan-out in SSE proxy |
| `kagenti/backend/app/main.py` | MODIFY: Register sidecar router, cleanup on shutdown |
| `kagenti/ui-v2/src/pages/SandboxPage.tsx` | MODIFY: Add tab bar above chat |
| `kagenti/ui-v2/src/components/SidecarTab.tsx` | NEW: Sidecar observation panel + controls |
| `kagenti/ui-v2/src/services/api.ts` | MODIFY: Add sidecar API methods |

## Dependencies

| Dependency | Status |
|-----------|--------|
| SSE streaming in chat.py | Working |
| Sandbox files API | Working |
| LangGraph checkpointer | Working (psycopg driver) |
| HITL approve/deny | Working (Session K wired it) |
| SandboxPage tab rendering | Needs implementation |
