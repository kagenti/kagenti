# Session Beta Passover — LLM Budget Proxy + DB Multi-Tenancy

> **Date:** 2026-03-12
> **From:** Session Alpha
> **Cluster:** sbox42 (alive, all agents deployed with latest code)
> **Worktrees:** `.worktrees/sandbox-agent` (kagenti), `.worktrees/agent-examples` (agent code)
> **Branch:** `feat/sandbox-agent` (both repos)

## What Session Alpha Completed

### Code Changes (all committed + pushed + deployed on sbox42)

**Agent code (`.worktrees/agent-examples/a2a/sandbox_agent/`):**

| Change | File | Impact |
|--------|------|--------|
| `_budget_summary` + `_no_tool_count` in SandboxState | `graph.py` | budget_update events now emitted by LangGraph |
| Reporter always runs LLM | `reasoning.py` | No more leaked reflector text as final answer |
| Prompt context on early-termination | `reasoning.py` | UI shows why steps ended without LLM call |
| gh CLI debugging hints | `reasoning.py` | Better micro-reasoning for tool flags |
| Stall detector removed entirely | `reasoning.py` | Reflector LLM decides, not hardcoded guards |
| Tool-limit return includes budget data | `reasoning.py` | Budget visible for tool-limited steps |
| LiteLLM refresh (partial, not working) | `budget.py` | Needs replacement by proxy — revert or remove |

**UI code (`.worktrees/sandbox-agent/kagenti/ui-v2/`):**

| Change | File | Impact |
|--------|------|--------|
| Polling fix — task_state terminal detection | `SandboxPage.tsx` | Stops infinite polling, fixes token/tool inflation |
| `budget_update` event type match | `loopBuilder.ts` | Budget data populates loop state |
| Micro-reasoning tokens in totals | `LoopSummaryBar.tsx` | Token count matches LiteLLM |
| Sidecar/looper tests → sandbox-hardened | `sandbox-sidecars.spec.ts` | Isolates from sandbox-legion tests |
| Resilience test → sandbox-hardened | `agent-resilience.spec.ts` | Stops scale-down breaking other tests |
| Budget enforcement + persistence tests | `sandbox-budget.spec.ts` | Tests exist but need proxy to pass |

**Backend (`.worktrees/sandbox-agent/kagenti/backend/`):**

| Change | File | Impact |
|--------|------|--------|
| `task_state` + `last_updated` in HistoryPage | `sandbox.py` | UI detects terminal sessions |

### Test Results (last run: full-test-v3)

- **173 passed, 22 failed, 1 skipped** (9.2 min)
- Resilience test on sandbox-hardened: **PASSED**
- Budget tests: **FAILING** (need the LLM proxy to enforce budget)
- RCA test: **PASSED**
- Pre-existing failures: HITL (5), wizard (3), skill-whisperer (5), sidecars (1), others (6)

### Design Docs Written (review + implement)

1. **`docs/plans/2026-03-12-llm-budget-proxy-design.md`** — LLM budget proxy service
   - Per-session token budget via small FastAPI proxy
   - Per-agent daily/monthly budgets
   - `llm_calls` + `budget_limits` tables in team postgres
   - Agent handles 402 → visible failure in UI

2. **`docs/plans/2026-03-12-db-multi-tenancy-design.md`** — Schema-per-agent isolation
   - Team schema (shared): sessions, llm_calls
   - Agent schema (isolated): LangGraph checkpoints
   - Wizard creates schema+user on deploy, drops on delete
   - Namespace-prefixed identifiers with hash (≤63 chars)

## What Session Beta Should Do

### Priority 1: Implement LLM Budget Proxy (Phase 1)

1. **Create the proxy service** (`charts/kagenti/images/llm-budget-proxy/` or similar)
   - ~300 line FastAPI app
   - `POST /v1/chat/completions` — budget check + forward to LiteLLM
   - Streaming support (SSE pass-through)
   - PostgreSQL for `llm_calls` tracking
   - Auto-migration on startup (`CREATE TABLE IF NOT EXISTS`)

2. **Deploy to sbox42** for testing
   - Build image via Shipwright/BuildConfig
   - Deploy in team1 namespace
   - Service: `llm-budget-proxy.team1.svc:8080`

3. **Update agent to use proxy**
   - Change `LLM_API_BASE` from litellm to proxy
   - Handle 402 budget exceeded errors
   - Remove `budget.add_tokens()` calls and `refresh_from_litellm()`

4. **Run budget tests** — should now pass

### Priority 2: DB Schema Isolation

1. Update deploy scripts to create schemas + per-agent users
2. Update wizard to create agent schema on deploy, drop on delete
3. Update agent `CHECKPOINT_DB_URL` to use per-agent credentials

### Priority 3: Remaining Fixes

- Looper test still failing (0 observations) — investigate
- Missing prompts for some steps — verify with new builds
- Multi-turn message ordering issue reported but not investigated

## How to Run Things

### Environment Setup

```bash
# Cluster access (kubeconfig was extracted from mgmt cluster)
export KUBECONFIG=/tmp/kagenti/sbox42-kubeconfig

# If kubeconfig is stale, re-extract:
export MGMT_KUBECONFIG=/tmp/kagenti-team-mgmt.kubeconfig
# Decode from .env.kagenti-team:
echo "$HYPERSHIFT_MGMT_KUBECONFIG_BASE64" | base64 -d > $MGMT_KUBECONFIG
KUBECONFIG=$MGMT_KUBECONFIG kubectl get secret kagenti-team-sbox42-admin-kubeconfig \
  -n clusters -o jsonpath='{.data.kubeconfig}' | base64 -d > /tmp/kagenti/sbox42-kubeconfig

# Verify cluster access
kubectl get nodes

# Log directory
export LOG_DIR=/tmp/kagenti/tdd/ui-sbox42
mkdir -p $LOG_DIR

# UI URL
export KAGENTI_UI_URL="https://kagenti-ui-kagenti-system.apps.kagenti-team-sbox42.octo-emerging.redhataicoe.com"

# Keycloak password (from K8s secret)
export KEYCLOAK_PASSWORD=$(kubectl -n keycloak get secret kagenti-test-users \
  -o jsonpath='{.data.admin-password}' | base64 -d)
export KEYCLOAK_USER=admin
```

### TDD Iteration Flow (from /tdd:ui-hypershift)

#### Level 1: UI-only change (~2min)

```bash
# Working dir for UI
cd .worktrees/sandbox-agent/kagenti/ui-v2

# 1. Commit + push
git add -u && git commit -s -m "fix(ui): <description>" && git push

# 2. Build UI (~90s)
oc -n kagenti-system start-build kagenti-ui
# Wait:
VER=$(oc -n kagenti-system get bc kagenti-ui -o jsonpath='{.status.lastVersion}')
while ! oc -n kagenti-system get build kagenti-ui-$VER -o jsonpath='{.status.phase}' | grep -qE '^Complete$|^Failed$'; do sleep 10; done
echo "Build: $(oc -n kagenti-system get build kagenti-ui-$VER -o jsonpath='{.status.phase}')"

# 3. Rollout (~15s)
oc -n kagenti-system rollout restart deploy/kagenti-ui
oc -n kagenti-system rollout status deploy/kagenti-ui --timeout=60s

# 4. Test
npx playwright test e2e/<spec>.spec.ts --reporter=list --timeout=600000 \
  > $LOG_DIR/test.log 2>&1; echo "EXIT:$?"
```

#### Level 2: Backend-only change (~90s)

```bash
cd .worktrees/sandbox-agent

# 1. Commit + push
git add -u && git commit -s -m "fix(backend): <description>" && git push

# 2. Build backend
oc -n kagenti-system start-build kagenti-backend
# Wait same pattern as UI

# 3. Rollout
oc -n kagenti-system rollout restart deploy/kagenti-backend
oc -n kagenti-system rollout status deploy/kagenti-backend --timeout=90s
```

#### Level 3: Agent code change (~3min)

```bash
cd .worktrees/agent-examples

# 1. Commit + push
git add -u && git commit -s -m "fix(agent): <description>" && git push

# 2. Build agent
oc -n team1 start-build sandbox-agent
VER=$(oc -n team1 get bc sandbox-agent -o jsonpath='{.status.lastVersion}')
while ! oc -n team1 get build sandbox-agent-$VER -o jsonpath='{.status.phase}' | grep -qE '^Complete$|^Failed$'; do sleep 10; done
echo "Build: $(oc -n team1 get build sandbox-agent-$VER -o jsonpath='{.status.phase}')"

# 3. Rollout ALL agents (they share the same image)
oc -n team1 rollout restart deploy/sandbox-legion deploy/sandbox-hardened \
  deploy/sandbox-restricted deploy/rca-agent-emptydir
sleep 15
for d in sandbox-legion sandbox-hardened sandbox-restricted rca-agent-emptydir; do
  oc -n team1 rollout status deploy/$d --timeout=90s 2>&1 | tail -1
done
```

#### Level 4: LLM Budget Proxy (new service)

```bash
# First time: create BuildConfig + Deployment + Service
# (see deployment manifests in design doc)

# Subsequent iterations:
oc -n team1 start-build llm-budget-proxy
VER=$(oc -n team1 get bc llm-budget-proxy -o jsonpath='{.status.lastVersion}')
while ! oc -n team1 get build llm-budget-proxy-$VER -o jsonpath='{.status.phase}' | grep -qE '^Complete$|^Failed$'; do sleep 10; done

oc -n team1 rollout restart deploy/llm-budget-proxy
oc -n team1 rollout status deploy/llm-budget-proxy --timeout=60s
```

#### Running Tests

```bash
cd .worktrees/sandbox-agent/kagenti/ui-v2

# Single test
npx playwright test e2e/sandbox-budget.spec.ts --reporter=list --timeout=600000 \
  > $LOG_DIR/budget-test.log 2>&1; echo "EXIT:$?"

# Full suite
RCA_SKIP_DEPLOY=1 RCA_AGENT_NAME=rca-agent-emptydir \
  npx playwright test --reporter=list --timeout=600000 \
  > $LOG_DIR/full-test.log 2>&1; echo "EXIT:$?"

# Analyze results (use subagent to avoid context pollution)
# Grep for: passed, failed, "[budget", error
```

#### Checking Logs

```bash
# Agent logs
kubectl logs deploy/sandbox-legion -n team1 --tail=50

# Backend logs
kubectl logs deploy/kagenti-backend -n kagenti-system -c backend --tail=50

# DB state
kubectl exec -n team1 postgres-sessions-0 -- psql -U kagenti -d sessions -c \
  "SELECT context_id, status::json->>'state', metadata::json->>'agent_name' \
   FROM tasks ORDER BY id DESC LIMIT 5"

# Budget events in session
kubectl exec -n team1 postgres-sessions-0 -- psql -U kagenti -d sessions -c \
  "SELECT e->>'type', count(*) FROM tasks, \
   jsonb_array_elements(metadata::jsonb->'loop_events') e \
   WHERE context_id = '<SESSION_ID>' GROUP BY e->>'type'"

# Mark stuck sessions as failed
kubectl exec -n team1 postgres-sessions-0 -- psql -U kagenti -d sessions -c \
  "UPDATE tasks SET status = jsonb_set(status::jsonb, '{state}', '\"failed\"') \
   WHERE status::json->>'state' = 'working' \
   AND status::json->>'timestamp' < NOW() - INTERVAL '10 minutes'"
```

### Key File Locations

| What | Path |
|------|------|
| Agent reasoning | `.worktrees/agent-examples/a2a/sandbox_agent/src/sandbox_agent/reasoning.py` |
| Agent graph | `.worktrees/agent-examples/a2a/sandbox_agent/src/sandbox_agent/graph.py` |
| Agent budget | `.worktrees/agent-examples/a2a/sandbox_agent/src/sandbox_agent/budget.py` |
| Agent event serializer | `.worktrees/agent-examples/a2a/sandbox_agent/src/sandbox_agent/event_serializer.py` |
| UI SandboxPage | `.worktrees/sandbox-agent/kagenti/ui-v2/src/pages/SandboxPage.tsx` |
| UI loopBuilder | `.worktrees/sandbox-agent/kagenti/ui-v2/src/utils/loopBuilder.ts` |
| UI LoopSummaryBar | `.worktrees/sandbox-agent/kagenti/ui-v2/src/components/LoopSummaryBar.tsx` |
| UI SessionStatsPanel | `.worktrees/sandbox-agent/kagenti/ui-v2/src/components/SessionStatsPanel.tsx` |
| Backend sandbox router | `.worktrees/sandbox-agent/kagenti/backend/app/routers/sandbox.py` |
| Backend token usage | `.worktrees/sandbox-agent/kagenti/backend/app/routers/token_usage.py` |
| E2E tests | `.worktrees/sandbox-agent/kagenti/ui-v2/e2e/*.spec.ts` |
| LLM proxy design | `.worktrees/sandbox-agent/docs/plans/2026-03-12-llm-budget-proxy-design.md` |
| DB design | `.worktrees/sandbox-agent/docs/plans/2026-03-12-db-multi-tenancy-design.md` |

### LiteLLM API (verified working on sbox42)

```bash
# From agent pod (using agent's LLM_API_KEY):
# Key management (MIT licensed, NOT enterprise)
POST /key/generate  — create virtual key with max_budget + duration
POST /key/delete    — delete key
GET  /key/info      — get key spend/budget info
GET  /spend/logs    — all spend logs (12K+ entries, no session filter)
GET  /user/info     — user/key info
GET  /global/spend  — global spend summary

# Key has max_budget (dollars) + duration (TTL) + budget_duration (reset interval)
# spend tracking works but shows $0 for local models (need pricing config)
```

### Things to NOT do

- **Don't clean DB** unless explicitly asked (sessions from other test runs)
- **Don't use enterprise LiteLLM features** (tags, enforced_params, temp_budget_increase)
- **Don't let agents talk to kagenti-backend** (security boundary)
- **Don't create DBs from services** (deploy scripts create DBs, services only migrate tables)
