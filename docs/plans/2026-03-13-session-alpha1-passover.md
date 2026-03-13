# Session Alpha-1 (2026-03-13) Passover — Per-Node Tools + Agent Debugging

> **Date:** 2026-03-13
> **Cluster:** sbox42 (KUBECONFIG=/tmp/kagenti/sbox42-kubeconfig)
> **Worktrees:** `.worktrees/sandbox-agent` (kagenti), `.worktrees/agent-examples` (agent code)
> **Branch:** `feat/sandbox-agent` (both repos)
> **Tests:** 191/196 passing (97.4%)

## Session Summary

This session (continuation of Alpha) focused on:
1. Design doc v2 rewrite + 6 new design docs
2. Agent fixes: GH_TOKEN, jq, reporter force-done, budget proxy routing
3. UI fixes: wizard defaults, pod tab, micro-reasoning order, loading spinner
4. Per-node tool subsets (graph wired, hit Llama 4 Scout `tool_choice=auto` wall)
5. Executor context window fix (5K for new steps, 30K for continuing)
6. Full debugging analysis infrastructure

## Test Progress

| Metric | Start | End |
|--------|-------|-----|
| Passed | 173 | 191 |
| Failed | 22 | 4 |
| Pass rate | 88.3% | 97.4% |

Remaining 4 failures: budget persistence (flaky), session isolation (flaky),
delegation (not built), looper (not built).

---

## Critical Finding: Llama 4 Scout Cannot Use tool_choice=auto

From `docs/plans/2026-03-13-sandbox-agent-tool-calling-guide.md`:

**Llama 4 Scout ALWAYS calls tools when tools are present**, regardless of
`tool_choice` setting. With `auto`, it acts like `required` — it never
produces text-only responses. This means:

- **Executor:** MUST use `tool_choice="any"` (working correctly)
- **Planner with tools:** Calls glob/file_read infinitely, never produces plan text
- **Reflector with tools:** Calls verification tools infinitely, never produces decision

**The per-node tool architecture is correct** but requires a `respond_to_user`
escape tool for Llama 4 Scout. Without it, planner/reflector must stay on
bare `llm` (no tools bound).

### Escape Tool Pattern (from research doc)

```python
@tool
def respond_to_user(response: str) -> str:
    """Return a text response to the user. Use this when you have enough
    information to answer and don't need to call any more tools."""
    return response
```

With this tool, the planner can: glob → file_read → respond_to_user(plan text).
The LLM always calls a tool, but one of the tools IS "produce text output".

### Current State of Graph (committed)

```
router -> planner <-> planner_tools -> step_selector -> executor <-> tools -> reflector <-> reflector_tools
                                                                                    |
                                                                              reflector_route
                                                                              |       |       |
                                                                           reporter  step_sel  planner
```

All nodes have tool subsets wired in graph.py. But `llm_planner` and
`llm_reflector` use `bind_tools()` with default `auto`, which causes
infinite tool loops with Llama 4 Scout.

**Next session must:** Add `respond_to_user` escape tool to planner_tools
and read_only_tools, then test the full flow.

---

## What Was Committed

### Agent (agent-examples repo)

| Commit | Change |
|--------|--------|
| `jq` in Dockerfile | Base image has jq for skills |
| Reporter `partial` status | Force-done shows real summary, not "The task has been completed" |
| Token budget removed from `exceeded` | Proxy is authoritative, agent just tracks for UI display |
| Debug: `bound_tools` in events | Executor events show tool schemas |
| Debug: `llm_response` in all nodes | Full OpenAI-format response (content, tool_calls, finish_reason) |
| Debug: step_selector prompts | Shows why a step was selected |
| Per-node tool subsets (graph.py) | Planner/reflector/executor each get own tools + ToolNode |
| Planner/reflector tool_call passthrough | reasoning.py handles tool_calls by returning for graph execution |
| Executor context window | 5K tokens for new steps, 30K for continuing |
| Executor `tool_choice="any"` | Must call tools, not produce text |

### UI (kagenti repo)

| Commit | Change |
|--------|--------|
| Wizard: `github-token-secret` default | Was `github-pat-secret` |
| Wizard: expanded proxy domains | Added `githubusercontent.com`, `api.github.com`, `files.pythonhosted.org` |
| Wizard: pod resource limits | Memory/CPU for agent + proxy configurable in Budget step |
| Wizard: text tool parsing off by default | `tool_choice="any"` makes it unnecessary |
| Pod tab | Shows all 3 pods (agent, egress proxy, budget proxy) with events |
| User message in loop card | Grey header showing what the user asked |
| Loading spinner | Spinner during session load instead of empty flicker |
| Micro-reasoning before tool call | Correct chronological order |
| Backend memory 512Mi | Helm chart persisted |
| Budget test: proxy enforcement | Tests 402 path with 200 token limit |
| Variant tests: poll for done state | Wait for loop card to finish, not just input enabled |
| Session tests: poll for sessionId | Wait up to 15s for URL parameter |

---

## Key Problems Found (Not Yet Fixed)

### 1. STDERR Marked as Error

Git clone outputs progress to STDERR. The shell tool marks this as `status: "error"`
even though `exit_code: 0`. Fix: check exit_code, not STDERR presence.

**File:** `graph.py` `_format_result()` function

### 2. Reflector Marks Failed Steps as "done"

When reflector says "continue", it marks the current step as "done" (line 1413
in reasoning.py) even if the tool call failed. The step_selector then skips it.

**Fix:** Reflector needs to verify outcomes before marking done. Requires
the escape tool + tool loop to work.

### 3. Step Re-selection Loop

Steps keep going back to step 1 because the reflector/planner cycle resets
`current_step`. The step_selector searches from `current_step` and finds
step 1 still "pending" after a replan.

### 4. Executor "Step completed" Without LLM Call

When `_no_tool_count >= 2` (two consecutive responses with no tool calls),
the executor produces "Step completed" as text with 0 tokens. This fires
even when the step wasn't actually completed — the executor just couldn't
figure out what tool to call.

### 5. "Step completed" Text from Dedup Path

When the executor's tool calls are deduplicated (already executed), it
produces "Step completed" without running the LLM. The UI shows this as
a micro-reasoning event with 0 tokens. This is confusing because it looks
like the step succeeded when it may have been skipped.

---

## Session Debugging Scripts

### Script 1: Get Session Events from DB

```bash
# Usage: ./debug-session-events.sh <context_id>
export KUBECONFIG=/tmp/kagenti/sbox42-kubeconfig
CTX_ID="${1:?Usage: $0 <context_id>}"

kubectl exec -n team1 postgres-sessions-0 -- psql -U kagenti -d sessions -c "
SELECT
  e->>'type' as type,
  (e->>'step')::int as step,
  e->>'decision' as decision,
  e->>'name' as tool,
  e->>'status' as status,
  e->>'prompt_tokens' as p_tok,
  e->>'completion_tokens' as c_tok,
  substring(COALESCE(e->>'content', e->>'description', e->>'reasoning', ''), 1, 120) as detail
FROM tasks, jsonb_array_elements(COALESCE(metadata::jsonb->'loop_events','[]'::jsonb)) e
WHERE context_id = '$CTX_ID'
ORDER BY (e->>'step')::int NULLS FIRST,
  CASE e->>'type'
    WHEN 'router' THEN 0 WHEN 'planner_output' THEN 1 WHEN 'plan' THEN 2
    WHEN 'plan_step' THEN 3 WHEN 'step_selector' THEN 4 WHEN 'executor_step' THEN 5
    WHEN 'tool_call' THEN 6 WHEN 'tool_result' THEN 7 WHEN 'micro_reasoning' THEN 8
    WHEN 'reflector_decision' THEN 9 WHEN 'reflection' THEN 10
    WHEN 'reporter_output' THEN 11 WHEN 'budget_update' THEN 12
    ELSE 13 END
"
```

### Script 2: Get Session Summary

```bash
# Usage: ./debug-session-summary.sh <context_id>
export KUBECONFIG=/tmp/kagenti/sbox42-kubeconfig
CTX_ID="${1:?Usage: $0 <context_id>}"

kubectl exec -n team1 postgres-sessions-0 -- psql -U kagenti -d sessions -c "
SELECT
  status::json->>'state' as state,
  metadata::json->>'agent_name' as agent,
  substring(metadata::json->>'title', 1, 80) as title,
  jsonb_array_length(COALESCE(metadata::jsonb->'loop_events','[]'::jsonb)) as events,
  length(history::text) as hist_bytes,
  (SELECT count(*) FROM jsonb_array_elements(COALESCE(metadata::jsonb->'loop_events','[]'::jsonb)) e WHERE e->>'type' = 'tool_call') as tool_calls,
  (SELECT count(*) FROM jsonb_array_elements(COALESCE(metadata::jsonb->'loop_events','[]'::jsonb)) e WHERE e->>'type' = 'tool_result' AND e->>'status' = 'error') as tool_errors,
  (SELECT count(*) FROM jsonb_array_elements(COALESCE(metadata::jsonb->'loop_events','[]'::jsonb)) e WHERE e->>'type' = 'reflector_decision') as reflector_decisions,
  substring((SELECT e->>'content' FROM jsonb_array_elements(COALESCE(metadata::jsonb->'loop_events','[]'::jsonb)) e WHERE e->>'type' = 'reporter_output' LIMIT 1), 1, 200) as final_answer
FROM tasks WHERE context_id = '$CTX_ID'
"
```

### Script 3: Get Agent Logs for Session

```bash
# Usage: ./debug-session-logs.sh <agent_name> <context_id>
export KUBECONFIG=/tmp/kagenti/sbox42-kubeconfig
AGENT="${1:?Usage: $0 <agent_name> <context_id>}"
CTX_ID="${2:?Usage: $0 <agent_name> <context_id>}"

kubectl logs deploy/$AGENT -n team1 --tail=2000 2>/dev/null | grep "$CTX_ID" | head -100
```

### Script 4: Compare DB Events vs Agent Logs

```bash
# Usage: ./debug-session-compare.sh <agent_name> <context_id>
# Compares event count in DB vs log lines mentioning the session
export KUBECONFIG=/tmp/kagenti/sbox42-kubeconfig
AGENT="${1:?Usage: $0 <agent_name> <context_id>}"
CTX_ID="${2:?}"

echo "=== DB Events ==="
kubectl exec -n team1 postgres-sessions-0 -- psql -U kagenti -d sessions -t -c "
SELECT e->>'type' as type, count(*)
FROM tasks, jsonb_array_elements(COALESCE(metadata::jsonb->'loop_events','[]'::jsonb)) e
WHERE context_id = '$CTX_ID' GROUP BY 1 ORDER BY 2 DESC
"

echo ""
echo "=== Agent Log Events ==="
kubectl logs deploy/$AGENT -n team1 --tail=2000 2>/dev/null | grep "$CTX_ID" | grep -oP '"type":\s*"[^"]+"' | sort | uniq -c | sort -rn

echo ""
echo "=== Missing from DB (in logs but not events) ==="
echo "(Compare the two lists above to find gaps)"
```

### Script 5: Get LLM Responses for a Session (debug mode)

```bash
# Usage: ./debug-session-llm-responses.sh <context_id>
export KUBECONFIG=/tmp/kagenti/sbox42-kubeconfig
CTX_ID="${1:?Usage: $0 <context_id>}"

kubectl exec -n team1 postgres-sessions-0 -- psql -U kagenti -d sessions -c "
SELECT
  e->>'type' as node,
  (e->>'step')::int as step,
  e->>'prompt_tokens' as p_tok,
  e->>'completion_tokens' as c_tok,
  e->'llm_response'->'choices'->0->'message'->>'content' as content_preview,
  jsonb_array_length(COALESCE(e->'llm_response'->'choices'->0->'message'->'tool_calls', '[]'::jsonb)) as tc_count,
  e->'llm_response'->'choices'->0->>'finish_reason' as finish_reason
FROM tasks, jsonb_array_elements(COALESCE(metadata::jsonb->'loop_events','[]'::jsonb)) e
WHERE context_id = '$CTX_ID'
  AND e->'llm_response' IS NOT NULL
ORDER BY (e->>'step')::int NULLS FIRST
"
```

### Script 6: Checkpoint State

```bash
# Usage: ./debug-session-checkpoints.sh <context_id>
export KUBECONFIG=/tmp/kagenti/sbox42-kubeconfig
CTX_ID="${1:?Usage: $0 <context_id>}"

kubectl exec -n team1 postgres-sessions-0 -- psql -U kagenti -d sessions -c "
SELECT thread_id, checkpoint_ns, length(checkpoint::text) as cp_bytes,
  length(metadata::text) as meta_bytes
FROM checkpoints WHERE thread_id = '$CTX_ID'
ORDER BY checkpoint_ns
"
```

---

## Analysis Process for Next Session

When analyzing a session, follow this order:

1. **Session summary** (Script 2) — state, events, tool calls, errors, final answer
2. **Event timeline** (Script 1) — chronological flow of all graph events
3. **LLM responses** (Script 5) — what each LLM call returned (debug mode only)
4. **Agent logs** (Script 3) — raw logs with full request/response data
5. **Compare DB vs logs** (Script 4) — find events in logs not persisted to DB
6. **UI verification** — open the session URL, check if all events render

Key things to check:
- Steps with `prompt_tokens=0` — no LLM call, deterministic decision
- Tool results with `status=error` but `exit_code=0` — STDERR false positive
- `step_selector` going back to step 1 — step not marked "done" properly
- `reflector_decision` with `done` when steps remain — premature termination
- Tool calls in planner/reflector nodes — verify they appear in UI

---

## Architecture Decisions for Next Session

### 1. Escape Tool (must implement)

```python
@tool
def respond_to_user(response: str) -> str:
    """Return your final text response. Call this when you have enough
    information and don't need any more tools."""
    return response
```

Add to planner_tools and read_only_tools. Then planner can:
glob → file_read → respond_to_user("1. Clone repo\n2. List failures\n...")

### 2. STDERR Fix (simple)

In `_format_result()` in graph.py, set status based on exit_code:
```python
status = "error" if result.exit_code != 0 else "success"
```
Not based on STDERR presence.

### 3. Reflector Step Marking

After adding escape tool + verification, reflector should:
- Call `glob("repos/kagenti/*")` to verify clone happened
- If files exist → mark step "done", decision "continue"
- If empty → mark step "failed", decision "replan"

### 4. Context Window

Keep the 5K/30K split:
- New step (tool_call_count == 0): 5K tokens — focus on step brief
- Continuing step (tool_call_count > 0): 30K tokens — see own tool results

---

## How to Continue

```bash
# Cluster
export KUBECONFIG=/tmp/kagenti/sbox42-kubeconfig
export LOG_DIR=/tmp/kagenti/tdd/ui-sbox42
mkdir -p $LOG_DIR

# Clean DB before testing
kubectl exec -n team1 postgres-sessions-0 -- psql -U kagenti -d sessions -c \
  "DELETE FROM checkpoint_writes; DELETE FROM checkpoint_blobs; DELETE FROM checkpoints; DELETE FROM tasks"

# Agent code
cd .worktrees/agent-examples
# Key file: a2a/sandbox_agent/src/sandbox_agent/graph.py (tool subsets)
# Key file: a2a/sandbox_agent/src/sandbox_agent/reasoning.py (planner/reflector)

# Build + deploy
oc -n team1 start-build sandbox-agent
oc -n team1 rollout restart deploy/sandbox-legion deploy/rca-agent-emptydir

# Run RCA test
cd .worktrees/sandbox-agent/kagenti/ui-v2
RCA_SKIP_DEPLOY=1 RCA_AGENT_NAME=rca-agent-emptydir \
  npx playwright test e2e/agent-rca-workflow.spec.ts --reporter=list --timeout=600000

# Analyze session
CTX_ID=$(kubectl exec -n team1 postgres-sessions-0 -- psql -U kagenti -d sessions -t -c \
  "SELECT context_id FROM tasks WHERE metadata::json->>'agent_name' = 'rca-agent-emptydir' ORDER BY id DESC LIMIT 1" | tr -d ' ')
# Then run Scripts 1-6 above with $CTX_ID
```
