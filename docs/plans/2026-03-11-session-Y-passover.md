# Session Y Passover — Event Pipeline, Budget Wizard, Visualizations

> **Date:** 2026-03-11
> **Previous Session:** X (passover at docs/plans/2026-03-10-session-X-passover.md)
> **Cluster:** sbox42 (Llama 4 Scout via LiteLLM proxy)
> **Worktrees:** `.worktrees/sandbox-agent` (kagenti), `.worktrees/agent-examples` (agent code)

## HOW TO REBUILD AND TEST

### Quick rebuild + test (Level 5 from tdd:ui-hypershift skill)

```bash
export KUBECONFIG=~/clusters/hcp/kagenti-team-sbox42/auth/kubeconfig

# 1. Push both worktrees
cd .worktrees/sandbox-agent && git push origin feat/sandbox-agent && cd -
cd .worktrees/agent-examples && git push origin feat/sandbox-agent && cd -

# 2. Trigger all 3 builds
oc start-build kagenti-ui -n kagenti-system
oc start-build kagenti-backend -n kagenti-system
oc start-build sandbox-agent -n team1

# 3. Wait for builds (~2 min)
for ns_build in "kagenti-system/kagenti-ui" "kagenti-system/kagenti-backend" "team1/sandbox-agent"; do
  ns=${ns_build%/*}; bc=${ns_build#*/}
  ver=$(oc -n $ns get bc $bc -o jsonpath='{.status.lastVersion}')
  while ! oc -n $ns get build ${bc}-${ver} -o jsonpath='{.status.phase}' 2>/dev/null | grep -qE 'Complete|Failed'; do sleep 10; done
  echo "  $bc: $(oc -n $ns get build ${bc}-${ver} -o jsonpath='{.status.phase}')"
done

# 4. Rollout + clean
oc rollout restart deploy/kagenti-ui deploy/kagenti-backend -n kagenti-system
# Clear stale skill cache
kubectl exec deploy/rca-agent -n team1 -c agent -- rm -rf /workspace/.claude/skills /workspace/.skill-repos
kubectl exec deploy/rca-agent-emptydir -n team1 -c agent -- rm -rf /workspace/.claude/skills /workspace/.skill-repos
oc rollout restart deploy/rca-agent deploy/rca-agent-emptydir -n team1
# Clean DB
kubectl exec -n team1 postgres-sessions-0 -- psql -U kagenti -d sessions -c "DELETE FROM tasks"
sleep 45

# 5. Run both RCA tests
cd .worktrees/sandbox-agent/kagenti/ui-v2
export KEYCLOAK_PASSWORD=$(kubectl get secret kagenti-test-users -n keycloak -o jsonpath='{.data.admin-password}' | base64 -d)
export KAGENTI_UI_URL=https://kagenti-ui-kagenti-system.apps.kagenti-team-sbox42.octo-emerging.redhataicoe.com
export KEYCLOAK_USER=admin CI=true
LOG_DIR=/tmp/kagenti-tdd-sbox42 && mkdir -p "$LOG_DIR"

# PVC variant (deploys via wizard)
npx playwright test e2e/agent-rca-workflow.spec.ts --reporter=list --timeout=600000 > "$LOG_DIR/rca-pvc.log" 2>&1; echo "PVC: $?"

# emptydir variant (pre-deployed, skip wizard)
RCA_AGENT_NAME=rca-agent-emptydir RCA_SKIP_DEPLOY=1 \
npx playwright test e2e/agent-rca-workflow.spec.ts --reporter=list --timeout=600000 > "$LOG_DIR/rca-emptydir.log" 2>&1; echo "EMPTYDIR: $?"
```

### Skills loading

Skills are loaded from `SANDBOX_SKILL_REPOS` env var on kagenti-backend:
```
SANDBOX_SKILL_REPOS="https://github.com/Ladas/kagenti.git@feat/sandbox-agent#.claude/skills"
```
This is forwarded to new agent deployments. To change, set on backend:
```bash
kubectl set env deploy/kagenti-backend -n kagenti-system \
  SANDBOX_SKILL_REPOS="https://github.com/Ladas/kagenti.git@feat/sandbox-agent#.claude/skills"
```

### Pre-deployed emptydir agent

The emptydir variant is deployed via API (not wizard):
```bash
curl -sk -X POST https://kagenti-api-.../api/v1/sandbox/team1/create -H 'Content-Type: application/json' -d '{
  "name":"rca-agent-emptydir", "repo":"https://github.com/Ladas/agent-examples",
  "branch":"feat/sandbox-agent", "context_dir":"/a2a/sandbox_agent",
  "base_agent":"sandbox-legion", "model":"llama-4-scout", "namespace":"team1",
  "enable_persistence":true, "workspace_storage":"emptydir",
  "secctx":true, "proxy":true,
  "proxy_domains":"github.com, api.github.com, pypi.org, files.pythonhosted.org"
}'
```

---

## P0: loop_events Persistence — Debugging in Progress

### Root cause (from Session X)
Backend logs show only 1 `LOOP_FWD` per session (type=router). Planner/executor/reflector events are not being forwarded. Added `SSE_PARSE` logging to trace the event pipeline.

### What to check in logs after redeploy
```bash
kubectl logs deploy/kagenti-backend -n kagenti-system -c backend --tail=200 | grep -E "SSE_PARSE|LOOP_FWD|Agent SSE"
```

Expected: multiple `SSE_PARSE` and `LOOP_FWD` lines per session (one per graph node event).
If only 1: the A2A event structure is not carrying the serialized JSON lines through to the backend's SSE stream.

### Confirmed diagnosis (Session X debugging)
The backend SSE connection to the agent closes after receiving only the `router` event. The agent's LLM calls take 30+ seconds (Llama 4 Scout via LiteLLM), and during that time only keepalive pings are sent. The planner/executor/reflector events are produced after the LLM responds but by then the backend's SSE stream may have ended (client navigated, nginx timeout, or test progression).

**The `_recover_loop_events_from_agent` fallback function exists** (sandbox.py line 1984) but the logs show it's NOT running. Check:
1. Is `session_has_loops` True? (Should be — router event has loop_id)
2. Is `has_reporter` False? (Should be — no reporter event in 1 loop_event)
3. Is `loop_events_persisted` False? (Should be — never set to True)

Add logging to the finally block to diagnose why recovery isn't triggering:
```python
logger.info("Recovery check: session_has_loops=%s has_reporter=%s persisted=%s events=%d",
    session_has_loops, has_reporter, loop_events_persisted, len(loop_events))
```

### Agent-side fix deployed (build 74)
Background event drain + re-persist via `task_updater.update_status()`. But this doesn't work because the A2A response stream is closed — `update_status` has nowhere to push events.

### The real fix needed
After the SSE stream ends, the backend should **poll the agent's A2A task endpoint** with retries (up to 10, exponential backoff) until the task reaches COMPLETED/FAILED. Then extract loop_events from the task history. The `_recover_loop_events_from_agent` function does this but isn't being called.

---

## Session Y Progress (2026-03-11)

### FIXED in this session

| Fix | Commits |
|-----|---------|
| **loop_events persistence** | GeneratorExit killed `await conn.execute()` in finally block. Moved ALL persistence to background task `_persist_and_recover()` — immune to GeneratorExit. |
| **Recovery polling** | `_recover_loop_events_from_agent` now polls with exponential backoff (5s→60s, 10 retries) waiting for task COMPLETED/FAILED state. |
| **micro_reasoning events** | New event type emitted between executor tool calls. Each executor micro-step captures reasoning, prompt, tokens. |
| **PromptInspector overlay** | Fullscreen overlay (ESC/X to close) showing system prompt, input messages, LLM response, tokens for any node. |
| **Full prompt data** | Increased truncation: system_prompt 3K→10K, messages 500→5000 chars, 30→100 entries. Model name now populated. |
| **Token display** | micro-reasoning blocks show token usage and model name inline. |

### NEW P0: Token Budget Not Enforced

**CRITICAL**: `budget.add_tokens()` is NEVER called — token tracking is dead code.
- `AgentBudget.max_tokens = 1_000_000` exists but `tokens_used` is never incremented
- `tokens_exceeded` is never checked by any node
- Only `max_iterations` is enforced (in reflector only)
- Session `10f9e8471d034583a09f900c9c589617` consumed 1.49M tokens without stopping

**Fix needed in `reasoning.py`:**
1. After each LLM call, call `budget.add_tokens(prompt_tokens + completion_tokens)`
2. In reflector AND executor, check `budget.tokens_exceeded` and force done
3. Emit a `budget_update` event after each node with current usage

### NEW P0: Context Window Management

**Problem**: LangGraph message history grows unbounded. Each LLM call includes ALL previous messages. When history exceeds the model's context window (131K for Llama 4 Scout), calls either fail or get truncated silently.

**UI shows wrong number**: Stats tab shows "1,489,577 / 131,072 tokens (1136.5%)" — this compares CUMULATIVE tokens (all calls summed) to the PER-CALL context window. These are different metrics:
- **Cumulative usage**: total tokens consumed across all LLM calls (budget tracking)
- **Context window usage**: tokens in the CURRENT call vs model's max context

**Needs:**
1. **Message trimming in graph**: Before each LLM call, trim history to fit within context window (e.g., keep system prompt + last N messages within 100K). Use LangGraph's `trim_messages` or custom trimmer.
2. **Per-call context tracking**: Emit `prompt_tokens` per node (already done), show it as "context: X/131K" in the UI.
3. **UI fix**: Don't show cumulative tokens as context window %. Show two separate metrics:
   - "Total usage: 1.49M tokens" (cumulative, budget)
   - "Last call: 45K/131K context" (per-call, window)

### Remaining P0 items (from Session X)

| # | Item | Notes |
|---|------|-------|
| 1 | ~~loop_events persistence~~ | FIXED — background task |
| 2 | **Budget controls in wizard** | Step showing SANDBOX_* defaults, passed as env vars |
| 3 | **RCA quality 3/5** | Reporter prompt formatting for Llama 4 Scout |
| 4 | ~~Agent ends after few steps~~ | Partially fixed — recovery polling fills gaps |
| 5 | **Message queue + cancel button** | Queue messages during loop, cancel button top right |
| 6 | **Visualizations tab** | Design doc at `2026-03-10-visualizations-design.md` |
| 7 | **Kiali ambient mesh** | LiteLLM + Squid need `istio.io/dataplane-mode: ambient` |
| 8 | **Agent redeploy E2E test** | Test reconfigure, session continuation, workspace persistence |
| 9 | **Per-session UID isolation** | fsGroup is stopgap, need per-session UIDs |
| 10 | **LLM usage panel** | OTEL/Phoenix trace export broken |
| 11 | **Subsessions panel** | Show "No sub-sessions" instead of empty |
| 12 | **Reflector prompt says "continue"** | Should say "execute" to match route name |
| 13 | **Loop failure reason not shown** | Failed agent loops should show the error reason next to the failure icon |
| 14 | **Agent writes outside workspace** | `mkdir ../../output` fails — skills/prompts reference paths outside `/workspace` |
| 15 | **Token budget enforcement** | NEW — `add_tokens()` never called, budget is dead code |
| 16 | **Context window management** | NEW — no message trimming, UI shows wrong metric |
| 17 | **DB metadata race condition** | CRITICAL: A2A SDK's `DatabaseTaskStore.save()` overwrites metadata column via `session.merge()`. Backend writes `{owner, agent_name, loop_events}`, A2A SDK replaces with `{}`. **Quick fix**: `ALTER TABLE tasks ADD COLUMN backend_meta jsonb DEFAULT '{}'::jsonb` — SDK won't touch it. Then change all backend reads/writes from `metadata` to `backend_meta`. **Design needed**: long-term storage architecture for sessions, metadata, loop_events, checkpoints. |
| 18 | **SSE stream closes at 30s** | Agent's A2A SSE handler closes after ~30s. With clean checkpointer (81K entries deleted), SSE delivered 12+ events. Dirty checkpointer = slow agent = only router arrives. Recovery now works (correct task ID) but metadata is overwritten by A2A SDK. |
| 19 | **Double-send UI bug** | 3rd session created during tests. Input cleared but message still sent twice. 32s gap suggests retry/fallback mechanism, not double-click. |
| 20 | **Ghost sessions after cleanup** | Recovery background tasks survive pod rollout transition, writing to DB after cleanup. Fix: clean DB AFTER all pods fully restarted. |

## Checking Logs After Tests

```bash
# Agent logs (reasoning, tool calls, errors)
kubectl logs deploy/rca-agent -n team1 --tail=100 | grep -E "Reflector|executor|SERIALIZE|A2A_EMIT|error|warning" | head -20

# Backend SSE pipeline (event forwarding, persistence)
kubectl logs deploy/kagenti-backend -n kagenti-system -c backend --tail=200 | grep -E "SSE_PARSE|LOOP_FWD|Agent SSE|Finally|recover"

# DB state (persisted events)
kubectl exec -n team1 postgres-sessions-0 -- psql -U kagenti -d sessions -c "SELECT context_id, (metadata::json->>'loop_events')::text IS NOT NULL as has_loops, jsonb_array_length(COALESCE((metadata::jsonb->'loop_events'), '[]'::jsonb)) as event_count FROM tasks ORDER BY id DESC LIMIT 5"
```
