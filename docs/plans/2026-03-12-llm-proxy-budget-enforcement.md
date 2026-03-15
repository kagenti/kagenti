# LLM Proxy with Budget Enforcement

> **Date:** 2026-03-12
> **Status:** Design review
> **Replaces:** 2026-03-12-litellm-budget-enforcement.md (direct LiteLLM query approach)

## Problem

Token budget enforcement is fragmented:
- Agent tracks tokens in-memory (resets on restart, misses sub-agents)
- Agent can't query LiteLLM directly (no HTTP libraries, auth issues)
- Budget is per-message, not per-session

## Solution

The kagenti-backend becomes an **OpenAI-compatible LLM proxy** that enforces
token budgets. The agent routes ALL LLM calls through the backend instead of
directly to LiteLLM.

## Architecture

```
Agent (ChatOpenAI)
  base_url: http://kagenti-backend.kagenti-system.svc:8000/internal/llm/v1
  Authorization: Bearer sk-kagenti-... (agent's LiteLLM key)
  metadata.session_id: context_id

  POST /v1/chat/completions
    ↓
Backend (/internal/llm — no Keycloak auth, mTLS only)
  1. Extract session_id from request body → extra_body.metadata.session_id
  2. Extract api_key from Authorization header
  3. Query LiteLLM: GET /spend/logs with agent's api_key
     → sum total_tokens where metadata.session_id matches
  4. Compare against budget (from env var or session metadata)
  5a. If over budget → return HTTP 402:
      {"error": {"message": "Budget exceeded: 45000/50000 tokens", "type": "budget_exceeded", "code": "budget_exceeded"}}
  5b. If within budget → forward request to LiteLLM, stream response back
    ↓
LiteLLM (litellm-proxy.kagenti-system.svc:4000)
  → processes LLM call
  → tracks spend per request_id + session_id automatically
```

## Agent Changes

### graph.py
- Change `ChatOpenAI(base_url=config.llm_api_base)` to point to backend proxy
- Add env var `LLM_PROXY_URL` (default: `http://kagenti-backend.kagenti-system.svc:8000/internal/llm/v1`)
- Pass `LLM_API_KEY` as the auth header (unchanged — just different target)

### budget.py
- Remove `refresh_from_litellm()` — no more agent-side token queries
- Remove `add_tokens()` calls — LiteLLM tracks automatically
- Keep: `iterations_exceeded`, `wall_clock_exceeded`, `step_tools_exceeded`
- Keep: `summary()` for budget_update events (uses in-memory counters for iterations/wall-clock)

### reasoning.py
- Remove all `budget.add_tokens(prompt_tokens + completion_tokens)` calls
- Remove `await budget.refresh_from_litellm()` calls
- Keep `budget.exceeded` checks for iterations and wall clock only
- Add try/except around `llm.ainvoke()` to catch budget exceeded errors:
  ```python
  try:
      response = await llm.ainvoke(messages)
  except Exception as e:
      if "budget_exceeded" in str(e).lower() or "402" in str(e):
          return {
              "messages": [AIMessage(content=f"Budget exceeded: {e}")],
              "done": True,
              "_system_prompt": f"[Budget exceeded — proxy rejected call]\n{e}",
              "_budget_summary": budget.summary(),
          }
      raise
  ```

## Backend Changes

### New router: app/routers/llm_proxy.py

```python
router = APIRouter(prefix="/internal/llm", tags=["llm-proxy"])

@router.api_route("/v1/{path:path}", methods=["POST", "GET"])
async def proxy_llm_call(path: str, request: Request):
    """OpenAI-compatible proxy with budget enforcement."""

    # 1. Extract auth + session from request
    api_key = request.headers.get("Authorization", "").replace("Bearer ", "")
    body = await request.json()
    session_id = (body.get("extra_body", {}) or {}).get("metadata", {}).get("session_id", "")

    # 2. Check budget
    if session_id:
        total_tokens = await _get_session_tokens(api_key, session_id)
        max_tokens = _get_budget_limit(session_id)  # env var or session metadata
        if total_tokens >= max_tokens:
            return JSONResponse(
                status_code=402,
                content={"error": {
                    "message": f"Budget exceeded: {total_tokens:,}/{max_tokens:,} tokens",
                    "type": "budget_exceeded",
                    "code": "budget_exceeded",
                    "tokens_used": total_tokens,
                    "tokens_budget": max_tokens,
                }}
            )

    # 3. Forward to LiteLLM
    # Stream response if requested
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    if body.get("stream"):
        return StreamingResponse(_stream_litellm(path, body, headers))
    else:
        async with httpx.AsyncClient(timeout=300) as client:
            resp = await client.post(f"{LITELLM_URL}/v1/{path}", json=body, headers=headers)
            return Response(content=resp.content, status_code=resp.status_code, headers=dict(resp.headers))
```

### Budget limit resolution
```python
def _get_budget_limit(session_id: str) -> int:
    """Get budget limit for a session.

    Priority:
    1. Session-level override (future: from DB/CRD)
    2. Agent-level env var SANDBOX_MAX_TOKENS
    3. Default: 1,000,000
    """
    # For now: read from env var passed by the agent in request metadata
    # Future: query session metadata in DB for per-session overrides
    return int(os.environ.get("SANDBOX_MAX_TOKENS", "1000000"))
```

### Spend query (using agent's key)
```python
async def _get_session_tokens(api_key: str, session_id: str) -> int:
    """Query LiteLLM for total tokens used by this session."""
    headers = {"Authorization": f"Bearer {api_key}"}
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(
            f"{LITELLM_URL}/spend/logs",
            headers=headers,
            params={"api_key": api_key},
        )
        if resp.status_code != 200:
            return 0  # Can't check — allow the call
        logs = resp.json()

    # Sum tokens for this session
    total = 0
    for log in logs:
        meta = log.get("metadata") or {}
        if meta.get("session_id") == session_id:
            total += log.get("total_tokens") or 0
    return total
```

## UI Changes

None required — the error propagates through the existing flow:
1. Agent catches 402 → sets `done: True` with budget message
2. Event serializer emits the step with `_system_prompt: "[Budget exceeded...]"`
3. Reporter runs (if it can) and produces a summary
4. Loop card shows the failure reason
5. Stats panel shows budget from budget_update events

## Configuration

| Env Var | Where | Default | Purpose |
|---------|-------|---------|---------|
| `LLM_PROXY_URL` | Agent | `http://kagenti-backend...:8000/internal/llm/v1` | Backend proxy URL |
| `LLM_API_KEY` | Agent | from secret | LiteLLM API key (forwarded to proxy) |
| `SANDBOX_MAX_TOKENS` | Agent | 1,000,000 | Token budget (sent in request metadata) |
| `LITELLM_BASE_URL` | Backend | `http://litellm-proxy...:4000` | LiteLLM URL for spend queries |

## What the agent keeps vs what moves

| Concern | Agent (local) | Backend proxy |
|---------|--------------|---------------|
| Token budget | - | Enforced via LiteLLM spend |
| Iteration limit | Checked per-message | - |
| Wall clock limit | Checked per-message | - |
| Tool calls/step | Checked per-step | - |
| Recursion limit | LangGraph config | - |

## Future: Per-session budget overrides

With RBAC:
1. Wizard sets `max_tokens` per agent deployment (stored in CRD/ConfigMap)
2. Backend reads it when proxying calls
3. Admin can override per-session via API
4. Budget shown in UI with remaining tokens

## Rollout

1. Deploy backend with new `/internal/llm` router
2. Update agent to point `LLM_API_BASE` to backend proxy
3. Remove agent-side token tracking
4. Test: budget enforcement, persistence across restart, sub-agent inclusion
