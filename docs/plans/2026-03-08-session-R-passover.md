# Session R Passover — Tool Calling Stability + Agent Selection + LiteLLM Analytics

> **Date:** 2026-03-08
> **Session:** R (Opus 4.6, 1M context)
> **Cluster:** sbox42 (Llama 4 Scout via LiteLLM proxy)
> **Worktree:** `.worktrees/sandbox-agent` (kagenti repo), `.worktrees/agent-examples` (agent code)
> **RCA Test:** 11 runs, final: 5/5 quality, agent=rca-agent correct, tools executing

---

## What Session R Delivered

### Agent Selection Fix (P0 — DONE)

The agent switching bug was a multi-layer race condition:

| Layer | Problem | Fix |
|-------|---------|-----|
| Frontend state | `selectedAgentRef.current` stale in async closures | Sync ref immediately in useEffect |
| URL params | `setSearchParams` overwrote agent param with stale value | Use updater function to preserve existing params |
| Backend routing | Trusted frontend's `agent_name` field (race-prone) | `_resolve_agent_name()` reads from DB for existing sessions |
| Test selectors | `getByText('/rca:ci')` matched sidebar + chat | Scoped to `getByTestId('chat-messages')` |
| Test agent pick | Dead `SandboxAgentsPanel` click | URL param + badge assertion |

**Commits (kagenti repo):**
```
e1494b11 fix(test): scope RCA test selectors + fix agent selection
63c8c232 fix(ui): sync selectedAgent from URL param + no-retry RCA test
142fac6e chore: remove accidentally tracked worktree from index
a1610689 chore: gitignore .claude/worktrees/
71773306 fix(test): update RCA test to use PR #860
a533dca4 fix(ui): update selectedAgentRef immediately on URL param change
faeafd96 fix(backend): resolve agent from DB for existing sessions
39c2dffa fix(ui): read agent from URL instead of stale closure ref
190460a7 fix(ui): preserve URL agent param on session creation
0a1296e3 feat(test+docs): variants timeout fix + delegation test + analytics design
```

### Tool Calling Stability (P0 — DONE)

| Issue | Root Cause | Fix |
|-------|-----------|-----|
| `gh api \| jq` blocked by HITL | Permission checker didn't split compound commands | Split on `&&/\|\|/\|/;`, check each segment |
| `git remote` blocked | Not in allow list | Added git remote/fetch/pull/show/rev-parse |
| `cd` blocked | Not in allow list | Added `shell(cd:*)` |
| Rate limit errors | No retry in shell tool | Exponential backoff (2s/4s/8s, 3 retries) |
| Llama 4 tool format not parsed | Model generates `[label, tool]{json}` not `tool(args)` | New regex `_LABEL_TOOL_JSON_RE` + JSON parser |
| Reflection skipped for single-step | Missing tool call on first pass → done immediately | Removed single-step reflection skip |
| Duplicate tool calls | `tools→executor` loop re-generates same calls | Executor-level dedup matching on (name, args) |

**Commits (agent-examples repo):**
```
377da2c fix(sandbox): compound command permissions + rate-limit retry
d2cda9c fix(sandbox): tools→reflector edge (reverted in f1b6a38)
1762cab fix(sandbox): add missing git subcommands to allow list
f1b6a38 fix(sandbox): revert tools→reflector, restore tools→executor edge
f8d1d9b feat(sandbox): fast-path planner + tool dedup + LiteLLM metadata
40e84ad fix(sandbox): parse Llama 4 tool format + never skip reflection
```

### LiteLLM Session Analytics (P2 — Layer 1 DONE, Layers 2-4 DESIGNED)

**Done:** Agent-side metadata tagging — every `ChatOpenAI` call now includes `extra_body.metadata` with `session_id`, `agent_name`, `namespace` for LiteLLM spend tracking.

**Design doc:** `docs/plans/2026-03-08-litellm-analytics-design.md`

**Remaining (for next session):**
- Layer 2: Backend `token_usage.py` router proxying LiteLLM `/spend/logs`
- Layer 3: UI API client TypeScript types + fetch methods
- Layer 4: `SessionStatsPanel` LLM Usage card with per-model breakdown table

### Other Deliverables

- **Fast-path planner**: `_is_trivial_text_request()` skips planner LLM call for "say exactly" / "what was the marker" patterns
- **Budget reduction**: max_iterations 10→6, hitl_interval 5→4
- **Variants timeout**: test timeout 300s→420s
- **Delegation test**: `sandbox-delegation.spec.ts` created (not yet run)
- **Gitignore**: `.claude/worktrees/` added

---

## Test Results

### RCA Test (agent-rca-workflow.spec.ts)

| Run | Agent | Tool Calls | Quality | Duration | Issue |
|-----|-------|-----------|---------|----------|-------|
| 1 | sandbox-legion | 0 | N/A | 30s | Selector strict mode violation |
| 2 | sandbox-legion | 6 | 5/5 | 1.7m | Wrong agent (no URL param fix) |
| 3 | rca-agent | 6 | 5/5 | 1.4m | URL param fix working |
| 4 | rca-agent | 2 | 5/5 | 1.5m | Compound permissions + rate-limit retry |
| 5 | rca-agent | 0 | N/A | 10.1m | UI pod restart timeout |
| 6 | rca-agent | 2 | 5/5 | 1.2m | All fixes confirmed |
| 7 | rca-agent | 0 | 2/5 | 1.2m | tools→reflector regression |
| 8 | rca-agent | 6 | 5/5 | 1.5m | tools→executor restored |
| 9 | rca-agent | 0 | 3/5 | ~1m | Llama 4 format not parsed |
| 10 | rca-agent | 1+10 | 5/5 | ~1.5m | Llama 4 parser working |
| 11 | rca-agent | 7 | 5/5 | ~1.5m | URL param preserved, all green |

### Sandbox Variants (sandbox-variants.spec.ts)

- sandbox-legion: TIMEOUT at 5min (killed — model latency via LiteLLM)
- sandbox-hardened: TIMEOUT at 5min
- sandbox-basic: likely passes (local qwen2.5:3b, fast)
- sandbox-restricted: untested

**Root cause:** Llama 4 Scout takes 15-30s per LLM call. 3 turns × multi-step plans = 5+ minutes.
**Mitigation:** Fast-path planner + budget reduction + timeout 420s. Needs re-test.

---

## P0 for Next Session (S)

### 1. Agent loop streaming finalization bug (CRITICAL)

**Problem:** When the agent loop finishes streaming, the UI creates a duplicate/phantom content box that disappears on page reload. The stream end event isn't properly finalizing the AgentLoopCard — it either duplicates the final content or creates an extra empty block.

**Where to look:**
- `SandboxPage.tsx` — SSE stream handler, `updateLoop` callback, stream-end logic (search for `seenLoopId`, `setAgentLoops`, `finalize`)
- `AgentLoopCard.tsx` — rendering logic when loop status transitions to "done"
- The `loop_event` SSE data may send a final event that creates a duplicate message

**How to test:** The delegation test (`sandbox-delegation.spec.ts`) is a good candidate — it forces a multi-step flow with tool calls. Add assertions that:
1. After stream completes, count message blocks — no duplicates
2. Reload the page, count message blocks — same count as before reload
3. No phantom/empty content blocks visible

**Repro:** Start a chat with rca-agent, send `/rca:ci ...`, wait for completion, observe extra block. Reload — block disappears.

### 2. Sandbox-variants test — re-run with fast-path planner

The fast-path + budget reduction should help. Re-run and iterate if still timing out.
Consider: should the test use simpler prompts? Or should we add a "fast mode" config for the agent?

### 3. LiteLLM Stats UI (Layers 2-4)

Implementation plan in `docs/plans/2026-03-08-litellm-analytics-design.md`:
- Backend: `token_usage.py` router proxying LiteLLM `/spend/logs`
- UI: `SessionStatsPanel` LLM Usage card with per-model breakdown table
- Test: verify stats appear after creating traffic
- Agent-side metadata tagging is DONE (Layer 1) — every ChatOpenAI call tagged

### 4. Graph node badges in UI

The user wants `[planner]`, `[executor]`, `[reflector]`, `[reporter]` labels on each step in the expanded agent loop. Check `AgentLoopCard.tsx` and the `loop_event` SSE data for node type info. The passover doc P4 specifies: `[type] [loop_id] [step N]` prefix on rendered events, timestamp on hover.

### 5. Delegate child session visibility

- `sandbox-delegation.spec.ts` is ready but untested
- The delegate tool works (stats show delegate:1) but child sessions may not appear in sidebar
- `_register_child_session` in `subagents.py` writes `parent_context_id` to DB
- `SessionSidebar.tsx` has `rootOnly` filter + `subSessionCount()` — should work if DB records are correct
- Verify TASK_STORE_DB_URL is set, asyncpg connection works, child records appear

### 6. Duplicate tool calls — monitor

The executor-level dedup is in place. Monitor via logs: `Dedup: skipped N already-executed tool call(s)`. If duplicates still occur, the dedup key `(name, repr(sorted(args)))` may need adjustment for commands with varying args.

---

## Architecture Notes

### Agent Selection Flow (after Session R fixes)

```
User navigates to /sandbox?agent=rca-agent
  → SandboxPage useEffect reads ?agent= param
  → Sets selectedAgent state + ref synchronously
  → User sends message
  → Frontend sends POST with agent_name from ref
  → Backend _resolve_agent_name():
     - New session? Use request.agent_name
     - Existing session? Read agent_name from DB (authoritative)
  → Backend proxies to http://{resolved_agent}.team1.svc:8000
  → Session created with correct agent_name in metadata
  → URL updated: setSearchParams preserves existing ?agent= param
```

### Tool Call Flow (after Session R fixes)

```
Planner → [trivial?] → fast-path (1 step) / LLM plan
Executor → LLM with tools bound → response
  → maybe_patch_tool_calls():
     - Has structured tool_calls? Use as-is
     - Try Llama 4 format: [label, tool]{"key": "value"} → parse JSON
     - Try legacy format: tool(key="value") → parse kwargs
  → Dedup: compare (name, args) against executed ToolMessages
     - All duplicates? Return text → routes to reflector
     - New calls? Execute via ToolNode
  → tools_condition → tools or reflector
Tools → _safe_tools (crash-proof) → executor (loop)
Reflector → LLM evaluates → done/continue/replan
Reporter → LLM formats final answer → END
```

### Permission Check Flow (after Session R fixes)

```
Shell command received (e.g. "cd repos && gh api ... | jq ...")
  → _split_compound() → ["cd repos", "gh api ...", "jq ..."]
  → _check_compound():
     - Each segment checked independently
     - All ALLOW → auto-execute
     - Any DENY → reject
     - Any HITL → human approval
  → Rate-limit detection on result
     - "rate limit exceeded" → retry with 2s/4s/8s backoff
```

---

### 7. Session sidebar shows wrong agent name (sandbox-legion instead of rca-agent)

**Problem:** Session `6fc4e43f` shows `agent=rca-agent` in URL and badge, but the left sidebar session list shows it under `sandbox-legion`. The backend `_resolve_agent_name()` routes correctly, but the A2A task store record gets the initial (wrong) `agent_name` from the first request before the backend resolution kicks in.

**Root cause:** The FIRST A2A message creates the task record in the agent's DB. The agent writes `agent_name` from whatever the backend proxy sent. The backend's `_set_owner_metadata()` sets `agent_name` only if it's missing — but the A2A SDK may have already set it from the proxy headers.

**Fix approach:** After `_resolve_agent_name()`, if the resolved agent differs from the request, update the existing task record's `agent_name` in the DB. Or: the backend should always write the resolved agent_name via `_set_owner_metadata()` even if one already exists (overwrite, not just fill-if-missing).

**Key code:**
- `sandbox.py:_set_owner_metadata()` line ~1399: `if agent_name and not meta.get("agent_name")` — change to `if agent_name`
- `sandbox.py:_resolve_agent_name()` line ~1170 — already resolves correctly
- The A2A SDK `DatabaseTaskStore` creates the task with metadata from the message — check if it sets `agent_name`

---

## How to Read This Doc Efficiently (Context Budget)

**DO NOT read this entire file into context.** Use targeted reads:

```bash
# Quick overview — just the section headers
grep '^##\|^###' docs/plans/2026-03-08-session-R-passover.md

# P0 items for next session only (the work to do)
sed -n '/^## P0 for Next Session/,/^## Architecture/p' docs/plans/2026-03-08-session-R-passover.md

# Architecture flows (if debugging agent selection or tool calls)
sed -n '/^## Architecture Notes/,/^## Startup/p' docs/plans/2026-03-08-session-R-passover.md

# Test results table (if comparing with your runs)
sed -n '/^### RCA Test/,/^### Sandbox/p' docs/plans/2026-03-08-session-R-passover.md
```

**Key files to read with subagents (not main context):**
- `SandboxPage.tsx` — 1800+ lines, always use Grep to find specific functions
- `reasoning.py` — 600+ lines, read specific node functions by line range
- `sandbox.py` — 1700+ lines, search for endpoint names

---

## How to Run Tests on sbox42

### Single test (RCA workflow)

```bash
export KUBECONFIG=~/clusters/hcp/kagenti-team-sbox42/auth/kubeconfig
export KEYCLOAK_PASSWORD=$(kubectl get secret kagenti-test-users -n keycloak -o jsonpath='{.data.admin-password}' | base64 -d)
export KAGENTI_UI_URL=https://kagenti-ui-kagenti-system.apps.kagenti-team-sbox42.octo-emerging.redhataicoe.com
export KEYCLOAK_USER=admin
export CI=true

# Clean rca-agent before RCA test (wizard deploys fresh)
kubectl delete deploy rca-agent -n team1 --ignore-not-found
kubectl delete svc rca-agent -n team1 --ignore-not-found

cd .worktrees/sandbox-agent/kagenti/ui-v2
npx playwright test e2e/agent-rca-workflow.spec.ts --reporter=list
```

### All main UI tests (loop)

```bash
export KUBECONFIG=~/clusters/hcp/kagenti-team-sbox42/auth/kubeconfig
export KEYCLOAK_PASSWORD=$(kubectl get secret kagenti-test-users -n keycloak -o jsonpath='{.data.admin-password}' | base64 -d)
export KAGENTI_UI_URL=https://kagenti-ui-kagenti-system.apps.kagenti-team-sbox42.octo-emerging.redhataicoe.com
export KEYCLOAK_USER=admin
export CI=true
LOG_DIR=/tmp/kagenti/session-s
mkdir -p $LOG_DIR

cd .worktrees/sandbox-agent/kagenti/ui-v2

# Clean rca-agent before full suite
kubectl delete deploy rca-agent -n team1 --ignore-not-found
kubectl delete svc rca-agent -n team1 --ignore-not-found

# Run all sandbox E2E tests sequentially, log each
for spec in \
  e2e/sandbox-sessions.spec.ts \
  e2e/sandbox-walkthrough.spec.ts \
  e2e/sandbox-variants.spec.ts \
  e2e/agent-rca-workflow.spec.ts \
  e2e/sandbox-delegation.spec.ts \
; do
  name=$(basename "$spec" .spec.ts)
  echo "=== Running $name ==="
  npx playwright test "$spec" --reporter=list > "$LOG_DIR/$name.log" 2>&1
  rc=$?
  echo "$name: EXIT=$rc"
  # Clean rca-agent between tests that deploy it
  if [[ "$name" == "agent-rca-workflow" ]]; then
    kubectl delete deploy rca-agent -n team1 --ignore-not-found
    kubectl delete svc rca-agent -n team1 --ignore-not-found
  fi
done

echo "=== Results ==="
for f in $LOG_DIR/*.log; do
  name=$(basename "$f" .log)
  result=$(tail -3 "$f" | grep -oE '[0-9]+ passed|[0-9]+ failed' | head -1)
  echo "  $name: $result"
done
```

### Analyze test failures (subagent pattern)

```
# Never read full test logs in main context. Use subagents:
Agent(subagent_type='Explore'):
  "Grep $LOG_DIR/<test-name>.log for FAIL|Error|timeout.
   Return: which step failed, exact error, 2-3 lines context."
```

### Build → Deploy → Test cycle

```bash
# 1. Push changes
cd .worktrees/agent-examples && git push origin feat/sandbox-agent  # agent code
cd .worktrees/sandbox-agent && git push origin feat/sandbox-agent   # UI/backend

# 2. Trigger builds
oc start-build sandbox-agent -n team1        # agent image
oc start-build kagenti-ui -n kagenti-system  # UI image
oc start-build kagenti-backend -n kagenti-system  # backend image

# 3. Follow builds (redirect to log files!)
oc logs -f build/sandbox-agent-NN -n team1 > $LOG_DIR/build-agent.log 2>&1; echo "EXIT:$?"
oc logs -f build/kagenti-ui-NN -n kagenti-system > $LOG_DIR/build-ui.log 2>&1; echo "EXIT:$?"

# 4. Restart deployments (builds don't auto-restart)
kubectl rollout restart deployment/sandbox-legion deployment/sandbox-agent \
  deployment/sandbox-basic deployment/sandbox-hardened deployment/sandbox-restricted -n team1
kubectl rollout restart deployment/kagenti-ui deployment/kagenti-backend -n kagenti-system

# 5. Wait for rollout
kubectl rollout status deployment/sandbox-legion -n team1 --timeout=120s
kubectl rollout status deployment/kagenti-ui -n kagenti-system --timeout=120s
```

---

## Startup for Next Session

```bash
cd /Users/ladas/Projects/OCTO/kagenti/kagenti
export KUBECONFIG=~/clusters/hcp/kagenti-team-sbox42/auth/kubeconfig

# You are Session S. Read P0 section of the passover:
# sed -n '/^## P0 for Next Session/,/^## How to Read/p' \
#   .worktrees/sandbox-agent/docs/plans/2026-03-08-session-R-passover.md

# Agent code: .worktrees/agent-examples/a2a/sandbox_agent/
# UI/backend: .worktrees/sandbox-agent/kagenti/
# Iterate on RCA test and sandbox-delegation test first.
```
