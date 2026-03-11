# Session Z Passover — Budget Enforcement, Wizard Controls, Looper Retry

> **Date:** 2026-03-11
> **Previous Session:** Y (passover at docs/plans/2026-03-11-session-Y-passover.md)
> **Cluster:** sbox42 (KUBECONFIG=~/clusters/hcp/kagenti-team-sbox42/auth/kubeconfig)
> **Worktrees:** `.worktrees/sandbox-agent` (kagenti), `.worktrees/agent-examples` (agent code)

## HOW TO REBUILD AND TEST

Follow `/tdd:ui-hypershift` skill strictly. NO DB cleanup unless specified.

```bash
export KUBECONFIG=~/clusters/hcp/kagenti-team-sbox42/auth/kubeconfig
export LOG_DIR=/tmp/kagenti-tdd-sbox42 && mkdir -p "$LOG_DIR"
export KEYCLOAK_PASSWORD=$(kubectl -n keycloak get secret kagenti-test-users -o jsonpath='{.data.admin-password}' | base64 -d)
export KAGENTI_UI_URL="https://$(kubectl get route kagenti-ui -n kagenti-system -o jsonpath='{.spec.host}')"
export KEYCLOAK_USER=admin CI=true
cd .worktrees/sandbox-agent/kagenti/ui-v2

# Emptydir test
RCA_AGENT_NAME=rca-agent-emptydir RCA_SKIP_DEPLOY=1 \
npx playwright test e2e/agent-rca-workflow.spec.ts --reporter=list --timeout=600000 > "$LOG_DIR/rca.log" 2>&1; echo "EXIT:$?"
```

## Session Y Achievements (what's already working)

| Feature | Status |
|---------|--------|
| Metadata persistence (MergingDatabaseTaskStore) | WORKING |
| Recovery with correct A2A task ID | WORKING |
| tasks/resubscribe SSE reconnection | WORKING |
| Subscribe endpoint for page reload | WORKING |
| micro_reasoning after every tool call | WORKING |
| PromptInspector (portal, fullscreen, ESC close) | WORKING |
| PromptBlock (inline expand + Fullscreen button) | WORKING |
| Prompt data in all node types (planner, executor, reflector, reporter) | WORKING |
| Unique step index per node invocation | WORKING |
| Tool result status icons (success/error) | WORKING |
| call_id pairing for tool call/result | WORKING |
| No double-send (stream error doesn't trigger fallback) | WORKING |
| Smooth loading (parallel fetch, skeleton, batch state) | WORKING |
| History preserves micro-reasoning (in-place step update) | WORKING |
| Recovery merges events (doesn't replace) | WORKING |
| Background persistence (immune to GeneratorExit) | WORKING |

## P0: Budget Enforcement (IN PROGRESS — Session Y started, Session Z continues)

### What exists in budget.py (updated in Session Y):
- `AgentBudget` dataclass with all limits + wall clock time
- `exceeded` property checks iterations, tokens, AND wall clock
- `exceeded_reason` returns human-readable string
- `summary()` returns dict for event serialization
- `add_tokens()`, `tick_iteration()`, `tick_tool_call()` helpers

### What's NOT wired yet (Session Z must complete):

1. **Call `budget.add_tokens()` after every LLM invocation** in reasoning.py:
   - `planner_node` — after `llm.ainvoke()`
   - `executor_node` — after `llm.ainvoke()`
   - `reflector_node` — after `llm.ainvoke()`
   - `reporter_node` — after `llm.ainvoke()`
   - Extract from `response.usage_metadata` → `prompt_tokens + completion_tokens`

2. **Check `budget.exceeded` in reflector AND executor**:
   - In `reflector_node`: if `budget.exceeded`, force `done` with `budget.exceeded_reason`
   - In `executor_node`: if `budget.exceeded`, return early without LLM call
   - Emit `budget_update` event with `budget.summary()` after each check

3. **Emit `budget_update` events** via event serializer:
   - After each node, emit `{"type": "budget_update", "loop_id": ..., ...budget.summary()}`
   - UI already has handler for `budget` event type in loopBuilder.ts

4. **Pass budget to ALL nodes** (currently only reflector gets it):
   - In graph.py, pass `budget=budget` to planner_node, executor_node, reporter_node

### Key files:
- Agent: `reasoning.py` — wire `budget.add_tokens()` after each LLM call
- Agent: `graph.py` — pass budget to all nodes
- Agent: `event_serializer.py` — emit budget_update events
- Agent: `budget.py` — already updated with wall clock, summary()

## P0: Wizard Budget Controls

### What to build:
1. **New wizard step** (or section in existing step) with budget fields:
   - Max Iterations (default 100)
   - Max Tokens (default 1,000,000)
   - Max Tool Calls Per Step (default 10)
   - Max Wall Clock Time (default 600s)
   - Recursion Limit (default 50)
   - HITL Interval (default 50)

2. **Pass as env vars** on agent deployment:
   ```
   SANDBOX_MAX_ITERATIONS=100
   SANDBOX_MAX_TOKENS=1000000
   SANDBOX_MAX_TOOL_CALLS_PER_STEP=10
   SANDBOX_MAX_WALL_CLOCK_S=600
   SANDBOX_RECURSION_LIMIT=50
   ```

3. **Wizard reconfigure** — allow clicking any step in the top stepper to jump directly (not just next/prev)

### Key files:
- UI: Wizard component (find with `Glob **/*wizard*` or `**/*Wizard*`)
- Backend: deploy endpoint that creates agent deployment with env vars

## P0: Recursion Limit → HITL Warning (not failure)

Currently LangGraph's recursion limit (50) kills the graph with an error artifact. This should:
1. Show as a **warning** (amber), not failure (red)
2. Offer the user a "Continue" button
3. The looper (if enabled) auto-continues by sending a "continue" message
4. Each continuation is a NEW A2A message within the same session
5. Total budget (session-level) caps the overall token usage

### Key files:
- Agent: `graph.py` — increase recursion_limit to budget.recursion_limit
- UI: `AgentLoopCard.tsx` — show recursion limit as warning, not error
- Backend: looper mechanism (existing sidecar_manager or new)

## P1: Other Items

| # | Item | Notes |
|---|------|-------|
| 1 | Stats counter assertion | `stats-user-msg-count=0` after SPA nav — test fails |
| 2 | Context window management | No message trimming for 131K Llama 4 Scout |
| 3 | Agent prompt — correct `gh` syntax | Agent hallucinates `--head-ref` flag |
| 4 | Timestamps/duration on blocks | Show time per block, hover for exact timestamps |
| 5 | Squid proxy domains | Add `*.redhataicoe.com` for internal URLs |
| 6 | Reflector prompt says "continue" | Should say "execute" to match route name |
| 7 | Loop failure reason not shown | Failed loops need clear error display |
| 8 | Agent writes outside workspace | `mkdir ../../output` fails |

## Checking Logs

```bash
# Backend — SSE pipeline, persistence, recovery, resubscribe
kubectl logs deploy/kagenti-backend -n kagenti-system -c backend --tail=200 > $LOG_DIR/backend.log 2>&1

# Agent
kubectl logs deploy/rca-agent-emptydir -n team1 --tail=200 > $LOG_DIR/agent.log 2>&1

# DB state
kubectl exec -n team1 postgres-sessions-0 -- psql -U kagenti -d sessions -c \
  "SELECT id, context_id, metadata::json->>'agent_name' as agent, \
   length(metadata::text) as meta_len, \
   CASE WHEN (metadata::jsonb->'loop_events') IS NOT NULL \
   THEN jsonb_array_length(metadata::jsonb->'loop_events') ELSE 0 END as events, \
   status::json->>'state' as state FROM tasks ORDER BY id DESC LIMIT 10"

# Event breakdown per session
kubectl exec -n team1 postgres-sessions-0 -- psql -U kagenti -d sessions -c \
  "SELECT e->>'type' as type, e->>'step' as step, count(*) FROM tasks, \
   jsonb_array_elements(metadata::jsonb->'loop_events') as e \
   WHERE context_id='SESSION_ID' GROUP BY e->>'type', e->>'step' ORDER BY step, count DESC"
```
