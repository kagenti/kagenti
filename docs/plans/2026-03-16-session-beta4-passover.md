# Session Beta-4 — Unified Turn Rendering, Multi-Turn Tests, Graph Feedback

> **Date:** 2026-03-16
> **Cluster:** sandbox42 (KUBECONFIG=~/clusters/hcp/kagenti-team-sandbox42/auth/kubeconfig)
> **Worktrees:** `.worktrees/sandbox-agent` (kagenti), `.worktrees/agent-examples` (agent code)
> **Branch:** `feat/sandbox-agent` (both repos)
> **MANAGED_BY_TAG:** kagenti-team
> **Previous:** Session Beta (2026-03-15) — AgentGraphCard, useSessionLoader, OTel, test fixes

## What Session Beta Delivered (continued through 2026-03-16)

### Architecture & Foundation
- AgentGraphCard: 12 event types, 10 nodes, A2A extension endpoint
- useSessionLoader: state machine replacing polling (-364 lines, 6 race conditions eliminated)
- OTel observability module (middleware removed — broke SSE, auto-instrumentation kept)
- Sessions DB: `public.sessions` table auto-migrated on backend startup
  - Composite indexes: (namespace, updated_at DESC), (agent_name, namespace), (owner)
  - Atomic upsert on every /chat/stream with COALESCE for safe overwrites
  - Prepared fields: owner_email, owner_sub, model_override, budget_max_tokens
  - list_sessions queries sessions table (indexed) instead of tasks JSON parsing

### Graph Views
- Dual graph views: StepGraphView (old per-step DAG) + TopologyGraphView (graph card topology)
- GraphLoopView wrapper with subtab toggle: [Step Graph | Topology] [Event Types | Subtypes] [Fullscreen]
- Both views accept `allLoops` for multi-message rendering
- Edge labels show description + traversal count from graph card
- Fullscreen button uses native requestFullscreen API

### Test Fixes & Infrastructure
- 35+ E2E test fixes (DNS variants, auth headers, OpenAI skips, assertive assertions)
- Playwright pinned to ^1.50.1, removed test.describe.configure from 7 files
- loopBuilder refactored: category-based reducer (7 categories via EVENT_CATALOG)
- FileBrowser: React.memo wrapper prevents scroll reset on parent re-render
- Streaming race fix: deferred setContextId + sendInProgressRef
- RCA wizard deploy tests: emptydir + PVC both PASSING (5/5 quality)
- 185 UI tests passing (full suite), 20 core tests green

### Bug Fixes
- RBAC: pods/exec, configmaps, secrets, PVCs in backend ClusterRole
- Wizard: proxy=True default (both backend + UI INITIAL_STATE)
- LLM secret key resolution (api-key vs apikey for default vs per-agent)
- OTel HTTP middleware removed (BaseHTTPMiddleware broke SSE streaming)
- Session title backfill from first user message (atomic DB update)
- Reporter respond_to_user fix (in progress — serializer extraction)
- 35+ E2E test fixes, 12 bug fixes (RBAC, secrets, proxy, wizard)
- RCA wizard deploy tests: emptydir + PVC both PASSING (5/5 quality)
- 73 broad UI tests passing, 2 rendering tests fixed

## What Beta-4 Must Do

### P0: Custom A2A Event Persistor + Seamless History Loading

**Problem:** User message blocks load AFTER the agent loop card instead of
before. History loading is all-or-nothing. The A2A SDK's task store persists
events as a blob in task metadata — no per-event granularity.

**Solution: Custom persistor that stores events individually:**

1. **New `events` table** (in sessions DB):
   ```sql
   CREATE TABLE events (
     id BIGSERIAL PRIMARY KEY,
     context_id TEXT NOT NULL,
     task_id TEXT NOT NULL,
     event_index INT NOT NULL,
     event_type TEXT NOT NULL,
     langgraph_node TEXT,
     payload JSONB NOT NULL,
     created_at TIMESTAMPTZ DEFAULT NOW()
   );
   CREATE INDEX idx_events_ctx ON events(context_id, event_index);
   ```

2. **Backend persistor**: stores each event separately as it arrives from
   the agent SSE stream. Also stores a summary record per task (updated
   periodically) with: step count, status, token totals, last event index.

3. **UI loading model**:
   - Load tasks (messages) in batches of 5 from sessions table
   - For each OPENED task: batch-load its events from events table
   - For LIVE streaming task: connect to SSE + collect gap events
   - "Load more" rectangle at top for older messages
   - Closed blocks show summary (from task summary record)
   - Opened blocks show full events (lazy-loaded)

4. **User message rendering**: user message stored in sessions/tasks table
   with `created_at` timestamp. ALWAYS renders BEFORE its agent loop.
   No position-based or content-based pairing needed — just by task_id.

### P0: Graph Streaming Animations

**Problem:** All 4 graph views are static — no animation when events stream in.
The user can't see the agent's progress in real time through the graph.

**What it should look like:**
- As each event arrives via SSE, the corresponding node PULSES (brief glow)
- Edge from previous node to current node ANIMATES (particle/dash flow)
- Animation seamlessly transitions to next edge as new events arrive
- Active node has persistent highlight, previous nodes dim
- In Topology view: edges light up as they're traversed
- In Step Graph: new nodes APPEAR with fade-in, edges draw progressively
- In Events flow: new event type nodes appear, edges animate between them

**Implementation approach:**
- Track `lastProcessedEventIndex` in the graph component state
- When `agentLoops` updates with new events, compare indices to find new ones
- For each new event: trigger CSS animation on the corresponding node/edge
- Use ReactFlow's `animated: true` on active edges (already partially done)
- Add CSS keyframes for node pulse (`@keyframes pulse { 0% { box-shadow: ... } }`)
- Transition between animations: keep previous edge animated briefly, then
  switch to new edge (overlap by 500ms for seamless flow)

### P0: Reporter Node — Must Be Terminal, Clean Final Answer

**Progress in Beta:** Serializer fix DONE — `_serialize_reporter()` now extracts
`respond_to_user` tool call response as clean `reporter_output` content (5 tests).
File badges in final answer DONE — collapsible "Files (N)" section with badges.

**Still TODO:**
- Reporter step still shows raw `[STEP_BOUNDARY]` text in some cases
- UI should filter `budget_update` and `node_transition` from step rendering
- Verify reporter is always the LAST rendered step in all graph views

### P0: Unified Turn Block Rendering

**Progress in Beta:** Content-based pairing DONE — `SandboxPage.tsx` pairs user
messages with loops by content match instead of position. User message no longer
disappears (removed stale `MESSAGES_SET` dispatch).

**Still TODO:**
- User message still renders AFTER loop card in some timing scenarios
  (needs the custom A2A persistor with per-event storage to fix properly)
- Session isolation test still fails (multi-session timing)
- The pairing is fragile — depends on `loop.userMessage` being set correctly

### P0: Session Isolation Test Fix

**Progress in Beta:** Test updated with `toPass()` retry pattern, longer
timeouts, sidebar verification. `startNewSession` now handles React batching.

**Still TODO:**
- Test still fails intermittently (1 of ~200 UI tests)

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
DAG, edge counters, and multi-message sidebar. Beta-4 should:
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

### P1: loopBuilder Category-Based Reducer — DONE in Beta

**Completed:** `applyLoopEvent` refactored to 7 category handlers via
`EVENT_CATALOG` lookup. 15 event types mapped. All 22 unit tests pass.
Added `node_transition` + `hitl_request` to catalog.

### P1: Wizard Defaults from Backend API

**Problem:** UI wizard `INITIAL_STATE` hardcodes defaults (wallclock, budget,
proxy, etc.) that must be kept in sync with backend `SandboxCreateRequest`.
When backend changes a default, the UI sends the old value.

**Fix:** Add `GET /api/v1/sandbox/defaults` endpoint that returns the backend's
default `SandboxCreateRequest` values. Wizard loads these on mount instead of
using hardcoded `INITIAL_STATE`. Reconfigure mode already loads from
`GET /config/{agent}` — new deployments should load from `/defaults`.

### P1: StepGraphView Nodes Mode — Group by LangGraph Node — DONE in Beta

**Completed:** Nodes mode now groups by `step.nodeType` (langgraph node name)
instead of EVENT_CATALOG category. Shows: planner, executor, reflector,
reporter as separate merged groups. Colors by category for visual distinction.

### P1: Graph View Unit Tests

**Problem:** Zero unit tests for graph view components. No tests for
`parseNodeId`, `buildLoopGraph`, `stepToTopoNode`, mode switching.

**Fix:** Create `StepGraphView.test.ts` and `TopologyGraphView.test.ts`
with tests for all node ID formats, both modes, multi-message connections.

### P2: Backend E2E Tests

**Progress in Beta:** SSL cert fix DONE (`KEYCLOAK_VERIFY_SSL=false` fallback).
Import order fix DONE. Auth headers added to all 9 call sites.

**Still TODO:** Sessions API tests fail on HTTP 401 — Keycloak token acquisition
needs `KEYCLOAK_URL` auto-detected from cluster. 8 passed, 8 failed.

## Also Planned for Beta-4+ Sessions

### Beta-3: Per-Session Landlock Isolation
- Design doc: `docs/plans/2026-03-16-session-beta3-per-session-isolation.md`
- Landlock LSM for per-session file access isolation
- securityContext.fsGroup per session
- PVC subdirectory permissions

### Gamma: Graph Feedback + File Browser Plan
- Design doc: `docs/plans/2026-03-15-session-gamma-plan.md`
- Graph view subtabs: DONE (Step Graph / Topology + Nodes / Events)
- Graph view topology events flow: DONE (event types as nodes)
- File browser scroll fix: DONE (React.memo)
- File badges in final answer: DONE (collapsible section)
- **Still TODO:** File browser integration with plan files, file preview badges

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

## How to Start Beta-4

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
docs/plans/2026-03-16-session-beta4-passover.md  # Next session plan
```

## Test Baseline (from Beta)

| Suite | Result |
|-------|--------|
| UI broad (73 tests) | 73 passed |
| RCA emptydir wizard | 1 passed (5/5 quality) |
| RCA PVC wizard | 1 passed (5/5 quality) |
| Rendering tests | 2 passed (were failing, fixed in Beta) |
| Session isolation | 1 FAILING (P0 for Beta-4) |
| Agent unit tests | 416 passed, 18 pre-existing failures |

## Pre-Existing Issues (NOT caused by Beta)

- `a2a.utils.telemetry:CancelledError` — A2A SDK internal tracing, not our code
- 18 agent unit test failures — budget defaults, permissions, reasoning changes
- Backend sessions API tests — SSL cert verification on HyperShift routes
- OTel HTTP middleware removed — need per-node span emission from graph card
