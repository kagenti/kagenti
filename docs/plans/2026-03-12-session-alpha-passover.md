# Session Alpha Passover — From Session Z

> **Date:** 2026-03-12
> **Previous Session:** Z (massive — 60+ commits, 18 test runs)
> **Cluster:** sbox42 (KUBECONFIG=~/clusters/hcp/kagenti-team-sbox42/auth/kubeconfig)
> **Worktrees:** `.worktrees/sandbox-agent` (kagenti), `.worktrees/agent-examples` (agent code)
> **Branch:** feat/sandbox-agent (both repos)

## What's Working Now

### Agent Architecture
- **step_selector node** — LLM node between planner→executor and reflector→executor. Reviews plan progress, writes focused brief for executor.
- **Reflector "done" override** — programmatically overrides "done" when plan steps remain
- **Token-based executor windowing** — 30K token cap (chars/4 estimate)
- **Shell output truncation** — 10KB cap prevents context blowout
- **Reflector sees tool call pairs** — last 3 AI→Tool message pairs
- **Prompt echo stripping** — reflector assessment no longer echoes system prompt
- **current_step in all executor return paths** — fixes plan_step=0 in events
- **Configurable tool_choice** — `SANDBOX_FORCE_TOOL_CHOICE` env var (default: on)
- **Text tool parsing** — `SANDBOX_TEXT_TOOL_PARSING` env var (default: on)
- **Debug prompts** — `SANDBOX_DEBUG_PROMPTS` env var (default: on)
- **Subagent tool filtering** — explore/delegate excluded from child agents
- **recursion_limit=300** (was 50)

### UI
- Subscribe handler processes events via `applyLoopEvent`
- Subscribe reconnection on page reload
- Session navigation cancels old subscribe stream (AbortController)
- Failed loops stay expanded (don't auto-collapse)
- Step labels: `Step X/N [V]` format (plan step / total [node visit])
- Plan step counter from `plan_step` field (normalized from `current_step`)
- Replan updates active plan + step count + resets currentStep
- Stats count includes loops with steps
- Budget section in Stats tab with progress bars
- Cancel button for streaming chat
- Wizard: budget sections, force tool calling, text parsing, debug prompts toggles
- Dark mode fixes, timestamps on steps, recursion limit amber warning
- Toggle shows plan step count + node visit counter
- New session button clears state properly
- Loading overlay on session switch (no blank flash)
- Removed gvisor

### Backend
- SQL-based event extraction from history (prevents OOM)
- Write-back: events extracted from history saved to metadata for fast future loads
- Istio ambient labels on Squid proxy + LiteLLM
- Budget params (SANDBOX_*) passed as env vars on wizard deploy

### Tests
- RCA E2E test passes (10+ green runs)
- Budget < 200K assertion
- Step label duplication check
- PVC test has extra Next click for Budget wizard step

## P0: Must Fix in Session Alpha

### 1. Polling doesn't update loop events (ROOT CAUSE of stale UI)

**Impact:** After streaming ends, the 5-second polling fetches history but only updates `messages`, ignoring `loop_events`. Reflector nodes, step progression, and final answers never appear after initial load.

**Fix:** In the polling `useEffect` (SandboxPage.tsx ~line 1183), also check `histPage.loop_events` and merge new events into `agentLoops` using `applyLoopEvent`. Don't rebuild from scratch — only apply events not already in the loop.

**File:** `kagenti/ui-v2/src/pages/SandboxPage.tsx` (polling useEffect)

### 2. Active streaming session pulls user back when navigating away

**Impact:** If you're viewing a streaming session and navigate to another page/session, the subscribe stream's state updates pull you back.

**Fix:** The subscribe AbortController should also abort when the user navigates away from the sandbox page entirely (not just session switch). Add cleanup in the component unmount / route change.

**File:** `kagenti/ui-v2/src/pages/SandboxPage.tsx` (_subscribeToSession, useEffect cleanup)

### 3. Executor still runs multiple plan steps in one burst

**Impact:** With `tool_choice="any"`, the executor MUST call a tool every response. It can never produce text-only to signal "step done". So it keeps calling tools across plan steps without returning to the reflector. The `max_tool_calls_per_step=20` is the only boundary.

**Options:**
a. Lower `max_tool_calls_per_step` to 5 (simple but blunt)
b. Add a programmatic check in executor: after each tool result, check if the current plan step's description was achieved (heuristic)
c. The step_selector already sets `current_step` — the executor should check if its assigned step matches what it's actually doing

**File:** `reasoning.py` executor_node, `graph.py` step_selector

### 4. Step numbering gaps in UI

**Impact:** Node visit counter shows [3], [4], [7], [9] — gaps where router/planner/reflector visits consume numbers but aren't shown as executor steps. The user expects sequential [1], [2], [3].

**Fix:** Use a separate counter for executor-only steps, or renumber steps in the UI based on render order rather than the raw node visit index.

**File:** `loopBuilder.ts` (track executor step count separately)

### 5. PVC test still fails (extra Next click might not be enough)

**Impact:** The wizard deploy test times out or fails. May need more robust wizard navigation (click step labels instead of Next buttons).

**File:** `e2e/agent-rca-workflow.spec.ts`

## P1: Should Fix

### 6. Page load jankiness (partially fixed)

Loading overlay added but polling still causes re-renders. The polling should be gated until initial load completes.

### 7. Backend OOM on large histories

SQL-based extraction added but untested under load. The write-back mechanism should prevent repeated extraction. Monitor backend restarts.

### 8. Planner prompt block not showing in UI

Debug logging added but root cause not found. The data reaches the loopBuilder (`system_prompt` and `prompt_messages` present in events) but PromptBlock may not render for planner steps. Check browser console for `[PromptBlock]` logs.

### 9. Context window management

Executor windowing at 30K tokens helps but is approximate (chars/4). For Llama 4 Scout (131K context), a more precise tokenizer would be better. Also, the planner and reporter still send full history.

### 10. Step 2a/2b retry naming

When a plan step fails and is replanned, the new attempt should be labeled `Step 2a`, `Step 2b`, etc. Currently all retries show as `Step 2`.

**File:** `loopBuilder.ts` (track replan count per plan step)

### 11. Micro-reasoning context bloat

Micro-reasoning (executor between tool calls) still sends growing context. After a `gh api` returns 10KB (truncated), every subsequent micro-reasoning includes it. The windowing helps but doesn't specifically target micro-reasoning.

### 12. Agent uses `cd` as separate command

The agent keeps trying `shell("cd repos/kagenti")` as a standalone command (which doesn't persist). Despite the prompt saying "chain commands with &&", Llama 4 Scout doesn't always follow. Consider:
- Intercepting `cd` commands and converting to `cwd` parameter
- Prepending `cd X &&` to subsequent commands automatically

## P2: Nice to Have

### 13. Budget display real-time (budget_update events)

Budget section shows data from loop state but the agent's `budget_update` events aren't flowing to the UI (event_serializer emits them but the UI doesn't process the `budget` event type from SSE). The loopBuilder handles `budget` type — the issue is in the SSE streaming path.

### 14. Visualizations tab

Design doc exists at `docs/plans/2026-03-10-visualizations-design.md`. Not implemented.

### 15. Agent redeploy E2E test

Test for reconfiguring/redeploying an existing agent via wizard.

### 16. Per-session UID isolation (done but verify)

fsGroup + runAsNonRoot implemented. Needs verification on HyperShift.

## Design Docs

- `docs/plans/2026-03-12-budget-limits-design.md` — naming proposal for budget/limits
- `docs/plans/2026-03-12-session-Z-passover.md` — Session Z passover (superseded by this doc)

## HOW TO REBUILD AND TEST

```bash
export KUBECONFIG=~/clusters/hcp/kagenti-team-sbox42/auth/kubeconfig
export LOG_DIR=/tmp/kagenti-tdd-sbox42 && mkdir -p "$LOG_DIR"

# Push both worktrees
cd .worktrees/sandbox-agent && git push origin feat/sandbox-agent && cd -
cd .worktrees/agent-examples && git push origin feat/sandbox-agent && cd -

# Build all 3
oc -n kagenti-system start-build kagenti-ui
oc -n kagenti-system start-build kagenti-backend
oc -n team1 start-build sandbox-agent

# Wait for builds
for ns_build in "kagenti-system/kagenti-ui" "kagenti-system/kagenti-backend" "team1/sandbox-agent"; do
  ns=${ns_build%/*}; bc=${ns_build#*/}
  ver=$(oc -n $ns get bc $bc -o jsonpath='{.status.lastVersion}')
  while ! oc -n $ns get build ${bc}-${ver} -o jsonpath='{.status.phase}' 2>/dev/null | grep -qE '^Complete$|^Failed$'; do sleep 10; done
  echo "  $bc-$ver: $(oc -n $ns get build ${bc}-${ver} -o jsonpath='{.status.phase}')"
done

# Rollout (clear skill cache first)
kubectl exec deploy/rca-agent-emptydir -n team1 -c agent -- rm -rf /workspace/.claude/skills /workspace/.skill-repos 2>/dev/null
oc -n kagenti-system rollout restart deploy/kagenti-backend deploy/kagenti-ui
oc -n team1 rollout restart deploy/rca-agent-emptydir
sleep 30

# Test
cd .worktrees/sandbox-agent/kagenti/ui-v2
export KEYCLOAK_PASSWORD=$(kubectl -n keycloak get secret kagenti-test-users -o jsonpath='{.data.admin-password}' | base64 -d)
export KAGENTI_UI_URL="https://$(kubectl get route kagenti-ui -n kagenti-system -o jsonpath='{.spec.host}')"
export KEYCLOAK_USER=admin CI=true

# Emptydir (pre-deployed, fast)
RCA_AGENT_NAME=rca-agent-emptydir RCA_SKIP_DEPLOY=1 \
npx playwright test e2e/agent-rca-workflow.spec.ts --reporter=list --timeout=600000 > "$LOG_DIR/rca.log" 2>&1; echo "EXIT:$?"

# PVC (wizard deploy, slower)
RCA_AGENT_NAME=rca-agent-pvc \
npx playwright test e2e/agent-rca-workflow.spec.ts --reporter=list --timeout=600000 > "$LOG_DIR/rca-pvc.log" 2>&1; echo "EXIT:$?"
```

## Checking Logs

```bash
# Backend
kubectl logs deploy/kagenti-backend -n kagenti-system -c backend --tail=200 > $LOG_DIR/backend.log 2>&1

# Agent
kubectl logs deploy/rca-agent-emptydir -n team1 --tail=200 > $LOG_DIR/agent.log 2>&1

# DB state
kubectl exec -n team1 postgres-sessions-0 -- psql -U kagenti -d sessions -c \
  "SELECT context_id, status::json->>'state' as state, \
   CASE WHEN (metadata::jsonb->'loop_events') IS NOT NULL \
   THEN jsonb_array_length(metadata::jsonb->'loop_events') ELSE 0 END as events \
   FROM tasks ORDER BY id DESC LIMIT 10"

# Step progression for a session
kubectl exec -n team1 postgres-sessions-0 -- psql -U kagenti -d sessions -c \
  "SELECT DISTINCT e->>'plan_step' as plan, count(*) as visits \
   FROM tasks, jsonb_array_elements(metadata::jsonb->'loop_events') as e \
   WHERE context_id='SESSION_ID' AND e->>'type' = 'executor_step' \
   GROUP BY e->>'plan_step' ORDER BY plan"
```
