# Session Beta-2 — Unified Turn Rendering, Multi-Turn Tests, Graph Feedback

> **Date:** 2026-03-16
> **Cluster:** sandbox42 (KUBECONFIG=~/clusters/hcp/kagenti-team-sandbox42/auth/kubeconfig)
> **Worktrees:** `.worktrees/sandbox-agent` (kagenti), `.worktrees/agent-examples` (agent code)
> **Branch:** `feat/sandbox-agent` (both repos)
> **MANAGED_BY_TAG:** kagenti-team
> **Previous:** Session Beta (2026-03-15) — AgentGraphCard, useSessionLoader, OTel, test fixes

## What Session Beta Delivered

- AgentGraphCard: 12 event types, 10 nodes, A2A extension endpoint
- useSessionLoader: state machine replacing polling (-364 lines, 6 race conditions eliminated)
- Graph view: topology DAG with edge counters + multi-message sidebar
- OTel observability module (middleware removed, auto-instrumentation kept)
- 35+ E2E test fixes, 12 bug fixes (RBAC, secrets, proxy, wizard)
- RCA wizard deploy tests: emptydir + PVC both PASSING (5/5 quality)
- 73 broad UI tests passing, 2 rendering tests fixed

## What Beta-2 Must Do

### P0: Unified Turn Block Rendering

**Problem:** Messages and agent loops are rendered separately. The
`groupMessagesIntoTurns` function groups messages into "turns", and loop
cards are interleaved by position. This causes:
- Loops not visually associated with their user message
- Multi-turn renders are fragile (position-based pairing)
- Session isolation test fails because rendering order breaks

**Fix:** Each "turn" should be ONE visual block:
```
Turn 1:
  [User bubble] "Analyze CI failures for #860"
  [AgentLoopCard] Plan: 5 steps, tools, final answer
Turn 2:
  [User bubble] "Also fix the flaky test"
  [AgentLoopCard] Streaming... step 2/3
```

**Pairing logic:** Match user message to AgentLoop by:
1. `loop.userMessage` text match (set during streaming)
2. Temporal ordering (user message order → next unpaired loop)
3. The existing `pairMessagesWithLoops` utility in `historyPairing.ts`

**Files to modify:**
- `SandboxPage.tsx` — the rendering section at lines ~1825-1900 (the IIFE with `groupMessagesIntoTurns`)
- `utils/loopBuilder.ts` — may need to store user message reference in AgentLoop
- `e2e/sandbox-sessions.spec.ts:185` — session isolation test must assertively verify:
  - Each turn shows user message + loop card in correct order
  - Session A messages don't appear in Session B
  - Agent badge shows correct agent name per session

### P0: Session Isolation Test Fix

**Current failure:** `sandbox-sessions.spec.ts:185` — after creating Session B,
the `startNewSession` function can't find the welcome card because the UI
still shows Session A's content.

**Root cause:** `handleNewSession` dispatches `SESSION_CLEARED` and resets
contextId, but the UI may not re-render fast enough before the test checks.

**Fix approach:**
1. `startNewSession` should wait for the welcome card OR empty chat state
2. The test should verify agent badge switches to the correct agent
3. Each turn should assertively check that messages belong to the right session

### P1: Graph View Feedback

**From user:** The graph view needs:
1. Two subtabs: "Multi-message graph" (accumulated across messages) and
   "Current message graph" (single message detail)
2. Collapsible session list on the left in graph view
3. Inline mode: messages with summary + link to fullscreen per message
4. The graph nodes should show better progress indicators

**Implementation:** The `GraphLoopView.tsx` was enhanced in Beta with topology
DAG, edge counters, and multi-message sidebar. Beta-2 should:
- Add the subtab toggle (All Messages / Selected Message)
- Polish the sidebar (show agent name, step progress, token count)
- Add a "Fullscreen" button per message that expands to full graph view

### P1: File Browser Scroll Bug

**From user:** "When I am on the files page, don't reload it. When I scroll
down, it reloads and scrolls up immediately."

**Root cause:** The 30s session status poll or sidecar poll triggers a
React state update that causes the FileBrowser component to re-render,
resetting scroll position.

**Fix:** Either:
- Use `React.memo` on FileBrowser to prevent re-render when parent state changes
- Or use `shouldComponentUpdate` / `useMemo` to stabilize the file tree data

### P1: loopBuilder Category-Based Reducer

**Design done in Beta:** Switch `applyLoopEvent` from `switch(event.type)`
(14+ cases) to `switch(eventDef.category)` (7 stable values). Uses the
graph card's `event_catalog` to look up category.

**Files:**
- `utils/loopBuilder.ts` — refactor `applyLoopEvent`
- `types/graphCard.ts` — already created in Beta
- `services/api.ts` — `graphCardService.fetchGraphCard` already created

### P2: Backend E2E Tests

Sessions API tests failed on SSL cert verification. Need to:
- Set `verify=False` or use OpenShift CA in `_get_ssl_context()`
- Run full backend E2E suite and fix remaining failures

## Also Planned for Beta-2+ Sessions

### Beta-3: Per-Session Landlock Isolation
- Design doc: `docs/plans/2026-03-16-session-beta3-per-session-isolation.md`
- Landlock LSM for per-session file access isolation
- securityContext.fsGroup per session
- PVC subdirectory permissions

### Gamma: Graph Feedback + File Browser Plan
- Design doc: `docs/plans/2026-03-15-session-gamma-plan.md`
- Graph view subtabs and polish
- File browser scroll fix
- Plan file rendering with badges

### Theta: Squid Proxy Domain Counters
- Design doc: `docs/plans/2026-03-15-session-theta-squid-proxy-counters.md`
- Per-agent DB schema isolation
- Proxy counter sidecar
- Network activity API + UI panel

### Extended Planning
- Design in `docs/plans/2026-03-15-agent-graph-card-design.md` Section 13
- Simple mode: JSON plan with append-only mutations
- Extended mode: thinking/tool loop with plan-specific tools
- Plan files as multi-turn source of truth

## How to Start Beta-2

```bash
# 1. Setup
export CLUSTER=sandbox42
export MANAGED_BY_TAG=kagenti-team
export KUBECONFIG=~/clusters/hcp/${MANAGED_BY_TAG}-${CLUSTER}/auth/kubeconfig
export LOG_DIR=/tmp/kagenti/tdd/ui-${CLUSTER}
mkdir -p $LOG_DIR

# 2. Verify cluster
kubectl get nodes
kubectl get deploy -n team1
kubectl get deploy -n kagenti-system | grep -E "backend|ui"

# 3. Get credentials
export KEYCLOAK_PASSWORD=$(kubectl -n keycloak get secret keycloak-initial-admin \
  -o jsonpath='{.data.password}' | base64 -d)
export KAGENTI_UI_URL="https://$(kubectl get route kagenti-ui -n kagenti-system \
  -o jsonpath='{.spec.host}')"

# 4. Working directory
cd .worktrees/sandbox-agent

# 5. Run the failing session isolation test to see current state
cd kagenti/ui-v2
KUBECONFIG=$KUBECONFIG KAGENTI_UI_URL=$KAGENTI_UI_URL \
  KEYCLOAK_USER=admin KEYCLOAK_PASSWORD=$KEYCLOAK_PASSWORD \
  KEYCLOAK_VERIFY_SSL=false \
  npx playwright test e2e/sandbox-sessions.spec.ts:185 \
  --reporter=list --timeout=120000

# 6. Fix the unified turn rendering in SandboxPage.tsx
# Key section: lines ~1825-1900 (the IIFE with groupMessagesIntoTurns)
# Pair each user message with its AgentLoop, render as one block

# 7. Build + deploy
git add -u && git commit -s -m "fix(ui): unified turn rendering" && git push
# Follow /tdd:ui-hypershift for build → rollout → test cycle

# 8. Run broad test suite
npx playwright test e2e/home.spec.ts e2e/sandbox.spec.ts \
  e2e/sessions-table.spec.ts e2e/agent-catalog.spec.ts \
  e2e/sandbox-rendering.spec.ts e2e/sandbox-graph.spec.ts \
  e2e/skill-whisperer.spec.ts e2e/sandbox-sessions.spec.ts \
  --reporter=list --timeout=120000

# 9. Run RCA wizard deploy test
RCA_AGENT_NAME=rca-agent-emptydir LLM_SECRET_NAME=litellm-virtual-keys \
  npx playwright test e2e/agent-rca-workflow.spec.ts \
  --reporter=list --timeout=600000
```

## Key Files to Read First

```
# Turn rendering (P0)
kagenti/ui-v2/src/pages/SandboxPage.tsx          # Lines 1825-1900: turn rendering
kagenti/ui-v2/src/utils/loopBuilder.ts           # applyLoopEvent, buildAgentLoops
kagenti/ui-v2/src/utils/historyPairing.ts        # pairMessagesWithLoops

# Graph view (P1)
kagenti/ui-v2/src/components/GraphLoopView.tsx   # Enhanced in Beta with topology DAG
kagenti/ui-v2/src/types/graphCard.ts             # GraphCard types
kagenti/ui-v2/src/services/api.ts                # graphCardService

# State machine hook
kagenti/ui-v2/src/hooks/useSessionLoader.ts      # Session lifecycle state machine

# Design docs
docs/plans/2026-03-15-agent-graph-card-design.md # Full architecture + extended planning
docs/plans/2026-03-15-session-beta-passover.md   # This session's passover
docs/plans/2026-03-16-session-beta2-passover.md  # Next session plan
```

## Test Baseline (from Beta)

| Suite | Result |
|-------|--------|
| UI broad (73 tests) | 73 passed |
| RCA emptydir wizard | 1 passed (5/5 quality) |
| RCA PVC wizard | 1 passed (5/5 quality) |
| Rendering tests | 2 passed (were failing, fixed in Beta) |
| Session isolation | 1 FAILING (P0 for Beta-2) |
| Agent unit tests | 416 passed, 18 pre-existing failures |

## Pre-Existing Issues (NOT caused by Beta)

- `a2a.utils.telemetry:CancelledError` — A2A SDK internal tracing, not our code
- 18 agent unit test failures — budget defaults, permissions, reasoning changes
- Backend sessions API tests — SSL cert verification on HyperShift routes
- OTel HTTP middleware removed — need per-node span emission from graph card
