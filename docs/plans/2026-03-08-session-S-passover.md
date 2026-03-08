# Session S Passover — Event Pipeline, Model Switcher, Agent Name Architecture

> **Date:** 2026-03-08
> **Session:** S (Opus 4.6, 1M context)
> **Cost:** ~$55, 4h 24m wall time
> **Cluster:** sbox42 (Llama 4 Scout via LiteLLM proxy)
> **Worktree:** `.worktrees/sandbox-agent` (kagenti), `.worktrees/agent-examples` (agent code)

---

## What Session S Delivered

### Test Suite — 10/10 Green (1.3m parallel)
All 5 test files pass with 4 parallel workers:
- sandbox-sessions: 3/3 (1.2m)
- sandbox-walkthrough: 1/1 (8-12s)
- sandbox-variants: 4/4 (17-20s each)
- agent-rca-workflow: 1/1 (1.4-1.7m)
- sandbox-delegation: 1/1 (30-37s)

### Features Implemented
| Feature | Status | Files |
|---------|--------|-------|
| Streaming phantom block fix | Done | SandboxPage.tsx |
| Sidebar agent name overwrite | Done | sandbox.py |
| contextIdRef for reload | Done | SandboxPage.tsx |
| handleSelectSession force reload | Done | SandboxPage.tsx |
| LiteLLM analytics L2-4 | Done | token_usage.py, LlmUsagePanel.tsx, api.ts |
| Helm LITELLM_API_KEY | Done | ui.yaml |
| Model Switcher cog popover | Done | ModelSwitcher.tsx, models.py |
| Graph node badges | Done (live only) | LoopDetail.tsx, agentLoop.ts |
| HITL approval dialog | Done | HitlApprovalCard.tsx |
| Sub-sessions tab | Done | SubSessionsPanel.tsx |
| Token tracking (agent SSE) | Done | reasoning.py, event_serializer.py |
| recursion_limit: 50 | Done | agent.py |
| Typed event schema | Done | event_schema.py, agentLoop.ts |
| Serializer refactor (distinct types) | Done | event_serializer.py |
| Backend loop event persistence | Done (code) | sandbox.py |
| Historical loop reconstruction | Done (code) | SandboxPage.tsx |
| Dark mode color fixes | Done | SessionSidebar.tsx, LoopDetail.tsx |
| Stale agent code cleanup | Done | deployments/sandbox/agents/legion/ |
| Test reliability (variants, walkthrough) | Done | All test files |

### Agent-Examples Commits
```
29850d1 feat: typed event schema + serializer refactor + unit tests
231e857 fix(sandbox): revert f-string docstring on shell tool
1dc08cd fix(sandbox): shell tool docstring includes workspace path
43e567d feat: token emission in SSE events + request_id tracking + recursion limit
```

---

## P0 for Next Session

### 1. Agent Name Vicious Cycle (CRITICAL — RECURRING)

**Problem:** Sessions keep showing `sandbox-legion` instead of the correct agent. The metadata update (`_set_owner_metadata`) sometimes fails silently, leaving `agent_name` empty. The frontend then defaults to `sandbox-legion`, and subsequent messages go to the wrong agent.

**Root cause analysis (deep research):**
- `_set_owner_metadata` has retry + warning logs now, but still fails when task row doesn't exist yet (A2A SDK race)
- The frontend defaults to `sandbox-legion` when agent_name is missing
- Clicking a session with empty agent_name sets `selectedAgent` to the default
- Next message then goes to the default agent, overwriting any correct routing

**Architectural fix needed:**
1. Frontend: never default to `sandbox-legion` — use URL `?agent=` param or localStorage
2. Backend: move metadata update to a background job with aggressive retry (not inline with SSE streaming)
3. Or: the A2A SDK should accept agent_name in the task creation and set it atomically

### 2. Loop Events Not Persisting

**Problem:** `has_loops: no` for all sessions. The backend code to persist loop events was added but loop events aren't being captured.

**Likely cause:** The loop event detection in `_stream_sandbox_response` looks for `loop_id` in the parsed message parts, but the events may be nested differently after the serializer refactor. The backend SSE proxy needs debugging to verify it's actually capturing events.

### 3. Historical Loop Reconstruction

**Problem:** Loop cards only show during live streaming. On reload, they disappear. The code to reconstruct from `loop_events` in history was added but depends on P0#2 (events must be persisted first).

### 4. Streaming Reconnect on Page Reload

**Problem:** If the user reloads during an active stream, the UI loads history but doesn't reconnect to the ongoing stream. Sessions in "working" state should trigger a reconnect attempt.

### 5. Reflector Duplicate Content

**Problem:** When the reflector decides "continue" and the loop iterates, the reflection text appears as a duplicate block. The reflector should show once with a `[continue]` or `[replan]` badge, not duplicate.

---

## Architecture Recommendations

### Event Pipeline Contract
```
Agent node → event_schema.py (typed dataclass) → event_serializer.py → A2A SSE
  → backend proxy (captures + forwards) → frontend SSE handler → loop card state
  → on [DONE]: persist loop_events to task metadata
  → on reload: reconstruct loop cards from persisted events
```

Each layer has clear types. No free-form JSON. Tested independently.

### Agent Name: Single Source of Truth
```
1. Agent name is SET by _resolve_agent_name() at request time
2. Agent name is STORED in task metadata via _set_owner_metadata()
3. Frontend READS agent name from session metadata (never from selectedAgent default)
4. URL ?agent= param is AUTHORITATIVE for new sessions
5. For existing sessions: DB is AUTHORITATIVE
```

### Test Infrastructure
- Run with `--workers=4` for parallel execution (1.3m vs 5.3m)
- Don't delete rca-agent after tests (only before)
- Use `data-testid="session-{contextId}"` for reliable sidebar clicks
- PF TextInput: use `pressSequentially()` + timeout race

---

## How to Run Tests

```bash
export KUBECONFIG=/Users/ladas/clusters/hcp/kagenti-team-sbox42/auth/kubeconfig
export KEYCLOAK_PASSWORD=$(kubectl get secret kagenti-test-users -n keycloak \
  -o jsonpath='{.data.admin-password}' | base64 -d)
export KAGENTI_UI_URL=https://kagenti-ui-kagenti-system.apps.kagenti-team-sbox42.octo-emerging.redhataicoe.com
export KEYCLOAK_USER=admin CI=true

# Clean
kubectl delete deploy rca-agent -n team1 --ignore-not-found
kubectl exec -n team1 postgres-sessions-0 -- psql -U kagenti -d sessions \
  -c "DELETE FROM tasks"

# Run parallel
cd .worktrees/sandbox-agent/kagenti/ui-v2
npx playwright test e2e/ --workers=4 --reporter=list
```
