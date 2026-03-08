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

### 1. Sandbox-variants test — re-run with fast-path planner

The fast-path + budget reduction should help. Re-run and iterate if still timing out.
Consider: should the test use simpler prompts? Or should we add a "fast mode" config for the agent?

### 2. LiteLLM Stats UI (Layers 2-4)

Implementation plan in `docs/plans/2026-03-08-litellm-analytics-design.md`:
- Backend: `token_usage.py` router
- UI: `SessionStatsPanel` LLM Usage card
- Test: verify stats appear after creating traffic

### 3. Graph node badges in UI

The user wants `[planner]`, `[executor]`, `[reflector]`, `[reporter]` labels on each step in the expanded agent loop. Check `AgentLoopCard.tsx` and the `loop_event` SSE data for node type info.

### 4. Delegate child session visibility

- `sandbox-delegation.spec.ts` is ready but untested
- The delegate tool works (stats show delegate:1) but child sessions may not appear in sidebar
- Check `_register_child_session` DB writes and `SessionSidebar` rootOnly filtering

### 5. Duplicate tool calls — monitor

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

## Startup for Next Session

```bash
cd /Users/ladas/Projects/OCTO/kagenti/kagenti
export KUBECONFIG=~/clusters/hcp/kagenti-team-sbox42/auth/kubeconfig

# You are the continuation of Session R.
# Agent code: .worktrees/agent-examples/a2a/sandbox_agent/
# UI/backend: .worktrees/sandbox-agent/kagenti/
# Read this passover doc for full context.
```
