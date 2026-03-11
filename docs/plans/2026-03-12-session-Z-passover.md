# Session Z Passover — Budget, Steps, Reflector, Token Efficiency

> **Date:** 2026-03-12
> **Previous Session:** Y
> **Cluster:** sbox42 (KUBECONFIG=~/clusters/hcp/kagenti-team-sbox42/auth/kubeconfig)
> **Worktrees:** `.worktrees/sandbox-agent` (kagenti), `.worktrees/agent-examples` (agent code)

## What's Working Now (Session Z achievements)

### UI Fixes
- Subscribe handler processes events via `applyLoopEvent` (was silently dropping)
- Subscribe reconnection on page reload
- Session navigation cancels old subscribe stream (AbortController)
- Failed loops stay expanded (don't auto-collapse)
- Stats count includes loops with steps (fixes assistant-msg-count=0)
- Cancel button for streaming chat
- Wizard budget step with sections + verbose descriptions
- Dark mode fixes (switches, helper text, stepper)
- Recursion limit amber warning (not red error)
- Timestamps on loop steps (hover for created/updated)
- Rich console logging for debugging
- Removed gvisor from wizard/backend/API
- Istio ambient labels on Squid proxy + LiteLLM
- Budget section in Stats tab with progress bars
- Toggle shows plan step count + node visit counter

### Agent Fixes
- Shell output truncated to 10KB (prevents context explosion)
- Token-based executor windowing (30K token cap, not message count)
- Reflector sees complete tool call pairs (args + result)
- Reflector prompt shows remaining steps + "X of N" format
- Workspace layout in executor prompt (repos/, output/)
- Prompt preview includes tool call arguments
- Subagent tool filtering (no delegate/explore in children)
- recursion_limit bumped to 2000 (was 50)
- max_iterations kept at 100 (looper concept)

### Tests
- 5+ consecutive green RCA E2E runs
- Budget < 200K assertion
- Step label duplication check
- PVC test needs extra Next click for Budget wizard step

## IMMEDIATE: Next Session Must Fix

### 1. Step numbering format: `Step X [N]` → `Step 2a [5]`

When a plan step is retried (replan), use letter suffix:
- Step 1 [1] → first attempt
- Step 1 [2] → still on step 1, second node visit
- Step 2 [3] → moved to step 2
- Step 2a [5] → step 2 failed, replanned, retry as 2a
- Step 2b [7] → second retry as 2b

**Files:**
- `loopBuilder.ts` — track replan count per plan step, assign letter suffix
- `LoopDetail.tsx` — render the suffix

### 2. Reflector still decides "done" too early

Even with "remaining steps" in the prompt, Llama 4 Scout sometimes says "done" after step 1. The reflector prompt needs to be even more explicit:

```
DECISION PROCESS:
1. Did the current step (1 of 9) succeed?
2. Remaining: 2. cd repos, 3. list failures, 4. identify run, ...
3. Since 8 steps remain → you MUST choose "continue", NOT "done".
4. Only choose "done" when remaining = NONE.
```

**File:** `reasoning.py` reflector system prompt

### 3. System prompts need clarity on the loop model

The executor, reflector, and planner prompts should all reference the same concepts:
- **Plan step** — numbered item in the plan (Step 1, Step 2, ...)
- **Node visit** — global counter of graph traversals [1], [2], [3], ...
- **Reasoning cycle** — one planner→executor→reflector round

Executor should know: "You are executing Step {X} of {N}. Your node visit is [{V}]."
Reflector should know: "Step {X} of {N} just completed. {R} steps remain."

### 4. Executor steps after reporter (ordering bug)

During streaming, events can arrive out of order. A late executor event arriving after the reporter causes it to appear below "Final answer". Fix: `applyLoopEvent` should ignore executor/tool events after a reporter_output has been received.

**File:** `loopBuilder.ts` — add guard: `if (loop.status === 'done') return loop;` for executor/tool events

### 5. Page load jankiness

Current flow causes blank flash + content popping in:
- `handleSelectSession` clears state → blank
- API loads → content appears piece by piece
- Polling races with initial load

Fix: show loading overlay over current content (don't clear), gate polling until initial load complete.

**File:** `SandboxPage.tsx`

## Design Doc

See `docs/plans/2026-03-12-budget-limits-design.md` for the full budget/limits naming proposal.

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

# Rollout
kubectl exec deploy/rca-agent-emptydir -n team1 -c agent -- rm -rf /workspace/.claude/skills /workspace/.skill-repos 2>/dev/null
oc -n kagenti-system rollout restart deploy/kagenti-backend deploy/kagenti-ui
oc -n team1 rollout restart deploy/rca-agent-emptydir
sleep 30

# Test
cd .worktrees/sandbox-agent/kagenti/ui-v2
export KEYCLOAK_PASSWORD=$(kubectl -n keycloak get secret kagenti-test-users -o jsonpath='{.data.admin-password}' | base64 -d)
export KAGENTI_UI_URL="https://$(kubectl get route kagenti-ui -n kagenti-system -o jsonpath='{.spec.host}')"
export KEYCLOAK_USER=admin CI=true

RCA_AGENT_NAME=rca-agent-emptydir RCA_SKIP_DEPLOY=1 \
npx playwright test e2e/agent-rca-workflow.spec.ts --reporter=list --timeout=600000 > "$LOG_DIR/rca.log" 2>&1; echo "EXIT:$?"
```
