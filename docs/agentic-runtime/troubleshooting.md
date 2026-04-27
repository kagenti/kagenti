# Troubleshooting

---

## Agent Pod Not Starting

### Landlock probe failure

**Symptom:** Pod fails with `Landlock not supported by kernel`.

**Cause:** `SANDBOX_LANDLOCK=true` but the node kernel doesn't support Landlock
(requires Linux 5.13+). The startup probe is assertive -- it fails the pod
rather than silently degrading.

**Fix:** Either upgrade the node kernel or set `SANDBOX_LANDLOCK=false` in the
agent deployment.

### PostgreSQL connection refused

**Symptom:** Agent logs show `connection refused` to `postgres-sessions`.

**Cause:** The `postgres-sessions` StatefulSet hasn't started yet, or the
secret `postgres-sessions-secret` doesn't exist.

**Check:**
```bash
kubectl get statefulset postgres-sessions -n team1
kubectl get secret postgres-sessions-secret -n team1
```

**Fix:** Run `76-deploy-sandbox-agents.sh` which creates the StatefulSet and
secrets.

---

## SSE Streaming Issues

### Events not appearing in UI

**Symptom:** Agent is processing but the UI shows no events.

**Check:**
1. Verify the background event consumer is running:
   ```bash
   kubectl logs deploy/kagenti-backend -n kagenti-system | grep "consumer"
   ```
2. Check the events table:
   ```bash
   kubectl exec -n team1 statefulset/postgres-sessions -- \
     psql -U kagenti sessions -c "SELECT COUNT(*) FROM events"
   ```

**Common causes:**
- Backend can't reach the agent pod (check Istio mTLS, NetworkPolicy)
- Agent pod is not emitting SSE events (check agent logs)
- Feature flag `SANDBOX` is not enabled

### Gap in event history

**Symptom:** Some events are missing when loading session history.

**Cause:** The gap-fill mechanism fetches events from `?from_index=N` but
the events table may have index gaps if the background consumer was
temporarily unavailable.

**Fix:** The UI automatically falls back to the `loop_events` blob in
task metadata, then to raw history. If events are permanently lost,
the session history may be incomplete but functional.

---

## Budget Proxy Issues

### Agent stops with "Budget Exceeded"

**Symptom:** Agent gracefully stops mid-task with a budget exceeded message.

**This is expected behavior.** The LLM Budget Proxy returned HTTP 402.

**Check current usage:**
```bash
kubectl exec -n team1 statefulset/postgres-sessions -- \
  psql -U kagenti llm_budget -c \
  "SELECT session_id, SUM(total_tokens) FROM llm_calls GROUP BY session_id"
```

**Increase limit:**
```bash
kubectl exec -n team1 statefulset/postgres-sessions -- \
  psql -U kagenti llm_budget -c \
  "UPDATE budget_limits SET max_tokens = 2000000 WHERE scope = 'session'"
```

### Budget proxy not recording calls

**Symptom:** `llm_calls` table is empty but agent is making LLM calls.

**Cause:** Agent's `LLM_API_BASE` is pointing directly to LiteLLM instead
of the budget proxy.

**Check:** Verify the agent deployment has:
```yaml
env:
  - name: LLM_API_BASE
    value: http://llm-budget-proxy:8080
```

---

## File Browser Issues

### "Failed to browse files"

**Symptom:** File browser shows an error.

**Cause:** Backend needs `pods/exec` permission to browse agent pod files.
This permission is only granted when `KAGENTI_FEATURE_FLAG_SANDBOX` is `true`.

**Check:**
```bash
kubectl auth can-i create pods/exec -n team1 \
  --as system:serviceaccount:kagenti-system:kagenti-backend
```

---

## Sidecar Issues

### Sidecar not starting

**Symptom:** Sidecar deployment exists but pod isn't running.

**Check:**
```bash
kubectl describe pod -n team1 -l app=looper-sidecar
kubectl logs -n team1 -l app=looper-sidecar
```

---

## Database Issues

### "relation does not exist"

**Symptom:** Backend logs show `relation "sessions" does not exist`.

**Cause:** Auto-migration hasn't run yet. It runs on backend startup.

**Fix:** Restart the backend:
```bash
kubectl rollout restart deploy/kagenti-backend -n kagenti-system
```

### Stale connection pool

**Symptom:** Agent intermittently fails with connection errors to PostgreSQL.

**Cause:** The asyncpg connection pool went stale (e.g. after PostgreSQL
pod restart).

**Fix:** The agent has `_ensure_checkpointer()` which auto-reconnects.
If it persists, restart the agent pod.

---

## Log Locations

| Component | How to Access |
|-----------|--------------|
| Backend | `kubectl logs deploy/kagenti-backend -n kagenti-system` |
| Agent | `kubectl logs deploy/<agent-name> -n team1` |
| Budget Proxy | `kubectl logs deploy/llm-budget-proxy -n team1` |
| Egress Proxy | `kubectl logs deploy/<agent>-egress-proxy -n team1` |
| PostgreSQL | `kubectl logs statefulset/postgres-sessions -n team1` |
| LiteLLM | `kubectl logs deploy/litellm-proxy -n kagenti-system` |

### Useful Filters

```bash
# Agent reasoning events
kubectl logs deploy/sandbox-legion -n team1 | grep "event_type"

# Budget proxy decisions
kubectl logs deploy/llm-budget-proxy -n team1 | grep "budget"

# Backend SSE proxy errors
kubectl logs deploy/kagenti-backend -n kagenti-system | grep "SSE\|consumer"
```
