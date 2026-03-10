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

### Possible causes
1. A2A `TaskStatusUpdateEvent` message format changed — `status_message` extraction misses the JSON lines
2. The `parts` extraction in `_extract_text_from_parts` drops the serialized loop events
3. The agent's `task_updater.update_status()` wraps the message differently than expected

---

## Remaining P0 items (from Session X)

| # | Item | Notes |
|---|------|-------|
| 1 | **loop_events persistence** | Root cause investigation above |
| 2 | **Budget controls in wizard** | Step showing SANDBOX_* defaults, passed as env vars |
| 3 | **RCA quality 3/5** | Reporter prompt formatting for Llama 4 Scout |
| 4 | **Agent ends after few steps** | Verify graph topology fix works |
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

## Checking Logs After Tests

```bash
# Agent logs (reasoning, tool calls, errors)
kubectl logs deploy/rca-agent -n team1 --tail=100 | grep -E "Reflector|executor|SERIALIZE|A2A_EMIT|error|warning" | head -20

# Backend SSE pipeline (event forwarding, persistence)
kubectl logs deploy/kagenti-backend -n kagenti-system -c backend --tail=200 | grep -E "SSE_PARSE|LOOP_FWD|Agent SSE|Finally|recover"

# DB state (persisted events)
kubectl exec -n team1 postgres-sessions-0 -- psql -U kagenti -d sessions -c "SELECT context_id, (metadata::json->>'loop_events')::text IS NOT NULL as has_loops, jsonb_array_length(COALESCE((metadata::jsonb->'loop_events'), '[]'::jsonb)) as event_count FROM tasks ORDER BY id DESC LIMIT 5"
```
