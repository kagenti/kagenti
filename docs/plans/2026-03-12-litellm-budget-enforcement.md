# LiteLLM-Based Budget Enforcement

> **Date:** 2026-03-12
> **Status:** Implementing

## Problem

Budget tracking is fragmented across multiple in-memory counters:
- `AgentBudget.tokens_used` resets on each message (no cross-turn accumulation)
- `AgentBudget.tokens_used` resets on pod restart (no persistence)
- Explore/delegate sub-agent LLM calls are not tracked in the parent budget
- `budget_update` events in the UI show per-message usage, not total session usage

## Solution

Use LiteLLM as the **single source of truth** for token budget enforcement.

The agent already passes `session_id` (context_id) in metadata to every LLM call.
LiteLLM already tracks per-session usage and exposes it via the backend's
`/api/v1/token-usage/sessions/{context_id}` endpoint (used by the LLM Usage tab).

### Architecture

```
Before each LLM call:
  query_litellm_usage(session_id) → { total_tokens: N }
  if N >= SANDBOX_MAX_TOKENS → raise BudgetExceeded (no LLM call)
  else → proceed with LLM call → LiteLLM tracks it automatically
```

### What changes

| Component | Before | After |
|-----------|--------|-------|
| Budget check | `budget.exceeded` (in-memory counter) | Query LiteLLM for actual session usage |
| Budget tracking | `budget.add_tokens()` per node | Removed — LiteLLM tracks automatically |
| Budget persistence | Lost on restart | LiteLLM DB persists |
| Sub-agent tracking | Not tracked | Tracked (same session_id) |
| budget_update events | From in-memory counter | From LiteLLM query |

### Implementation

1. **`budget.py`**: Add `async check_litellm(session_id, backend_url)` method that queries
   the token-usage API and updates `tokens_used` from the response's `total_tokens`.

2. **`reasoning.py`**: Before each LLM call in planner/executor/reflector/reporter,
   call `await budget.check_litellm(context_id, backend_url)` instead of just
   checking `budget.exceeded`.

3. **`graph.py`**: Pass `backend_url` (derived from `KAGENTI_BACKEND_URL` or
   inferred from service discovery) to the budget checker.

4. **Remove `budget.add_tokens()`** calls — LiteLLM is the source of truth.

5. **`budget_update` events**: Emit with `tokens_used` from LiteLLM query result
   (accurate across restarts and sub-agents).

### Configuration

- `SANDBOX_MAX_TOKENS` — unchanged, still the budget limit (default 1,000,000)
- `KAGENTI_BACKEND_URL` — backend URL for token-usage API (default: auto-discover
  via `kagenti-backend.kagenti-system.svc.cluster.local:8000`)
- `SANDBOX_BUDGET_CHECK_INTERVAL` — minimum seconds between LiteLLM queries
  to avoid hammering the API (default: 5s, cached)

### Fallback

If the token-usage API is unavailable (backend down, network error), fall back
to the in-memory counter (current behavior). Log a warning but don't block execution.
