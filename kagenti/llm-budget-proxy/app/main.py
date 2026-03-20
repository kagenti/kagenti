"""LLM Budget Proxy — per-session and per-agent token budget enforcement.

A small FastAPI proxy that sits between agents and LiteLLM. It:
1. Checks per-session token budget before forwarding requests
2. Forwards to LiteLLM (streaming or non-streaming)
3. Records token usage in PostgreSQL after each call
4. Returns 402 when budget is exceeded
"""

from __future__ import annotations

import json
import logging
import os
import time
from contextlib import asynccontextmanager
from uuid import uuid4

import asyncpg
import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse

logger = logging.getLogger("llm-budget-proxy")
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s"
)

LITELLM_URL = os.environ.get(
    "LITELLM_URL", "http://litellm-proxy.kagenti-system.svc.cluster.local:4000"
)
DATABASE_URL = os.environ.get("DATABASE_URL", "")
DEFAULT_SESSION_MAX_TOKENS = int(
    os.environ.get("DEFAULT_SESSION_MAX_TOKENS", "1000000")
)
CACHE_TTL = float(os.environ.get("CACHE_TTL", "5.0"))

# In-memory session token cache: session_id -> (tokens, monotonic_timestamp)
_session_cache: dict[str, tuple[int, float]] = {}

db: asyncpg.Pool | None = None

CREATE_TABLES_SQL = """
CREATE TABLE IF NOT EXISTS llm_calls (
    id              BIGSERIAL PRIMARY KEY,
    request_id      UUID NOT NULL DEFAULT gen_random_uuid(),
    session_id      TEXT NOT NULL,
    user_id         TEXT NOT NULL DEFAULT '',
    agent_name      TEXT NOT NULL DEFAULT '',
    namespace       TEXT NOT NULL DEFAULT '',
    model           TEXT NOT NULL DEFAULT '',
    prompt_tokens   INTEGER NOT NULL DEFAULT 0,
    completion_tokens INTEGER NOT NULL DEFAULT 0,
    total_tokens    INTEGER NOT NULL DEFAULT 0,
    cost_usd        REAL NOT NULL DEFAULT 0.0,
    latency_ms      INTEGER NOT NULL DEFAULT 0,
    status          TEXT NOT NULL DEFAULT 'ok',
    error_message   TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    metadata        JSONB DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS budget_limits (
    id              SERIAL PRIMARY KEY,
    scope           TEXT NOT NULL,
    scope_key       TEXT NOT NULL,
    namespace       TEXT NOT NULL DEFAULT '',
    max_tokens      BIGINT NOT NULL,
    max_cost_usd    REAL,
    window_seconds  INTEGER,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(scope, scope_key, namespace)
);
"""

CREATE_INDEXES_SQL = """
CREATE INDEX IF NOT EXISTS idx_llm_calls_session
    ON llm_calls (session_id, created_at);
CREATE INDEX IF NOT EXISTS idx_llm_calls_agent
    ON llm_calls (agent_name, namespace, created_at);
CREATE INDEX IF NOT EXISTS idx_llm_calls_user
    ON llm_calls (user_id, created_at);
"""

INSERT_DEFAULT_BUDGETS_SQL = """
INSERT INTO budget_limits (scope, scope_key, max_tokens, window_seconds)
VALUES
    ('session', '*', 1000000, NULL),
    ('agent_daily', '*', 5000000, 86400),
    ('agent_monthly', '*', 50000000, 2592000)
ON CONFLICT (scope, scope_key, namespace) DO NOTHING;
"""


@asynccontextmanager
async def lifespan(app: FastAPI):
    global db
    if not DATABASE_URL:
        logger.error("DATABASE_URL not set — running without persistence")
    else:
        db = await asyncpg.create_pool(DATABASE_URL, min_size=2, max_size=10)
        async with db.acquire() as conn:
            await conn.execute(CREATE_TABLES_SQL)
            await conn.execute(CREATE_INDEXES_SQL)
            await conn.execute(INSERT_DEFAULT_BUDGETS_SQL)
        logger.info("DB migrated — tables ready")
    logger.info("LLM Budget Proxy ready — LITELLM_URL=%s", LITELLM_URL)
    yield
    if db:
        await db.close()


app = FastAPI(title="LLM Budget Proxy", lifespan=lifespan)


def _extract_metadata(body: dict) -> dict:
    """Extract budget metadata from the request body.

    The OpenAI SDK merges ``extra_body`` keys into the top-level request
    body, so ``metadata`` appears at root level (not nested under extra_body).
    We check both locations for robustness.
    """
    meta = body.get("metadata") or {}
    if not meta:
        extra = body.get("extra_body") or {}
        meta = extra.get("metadata") or {}
    return {
        "session_id": meta.get("session_id", ""),
        "agent_name": meta.get("agent_name", ""),
        "user_id": meta.get("user_id", ""),
        "namespace": meta.get("namespace", ""),
        "max_session_tokens": int(meta.get("max_session_tokens", 0)),
    }


async def _get_session_tokens(session_id: str) -> int:
    """Get total tokens used for a session, with in-memory cache."""
    if not db or not session_id:
        return 0
    cached = _session_cache.get(session_id)
    if cached and time.monotonic() - cached[1] < CACHE_TTL:
        return cached[0]
    tokens = await db.fetchval(
        "SELECT COALESCE(SUM(total_tokens), 0) FROM llm_calls WHERE session_id = $1",
        session_id,
    )
    _session_cache[session_id] = (tokens, time.monotonic())
    return tokens


async def _record_call(
    *,
    session_id: str,
    user_id: str,
    agent_name: str,
    namespace: str,
    model: str,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    total_tokens: int = 0,
    latency_ms: int = 0,
    status: str = "ok",
    error_message: str | None = None,
) -> None:
    """Insert a record into llm_calls."""
    if not db:
        return
    await db.execute(
        "INSERT INTO llm_calls "
        "(session_id, user_id, agent_name, namespace, model, "
        "prompt_tokens, completion_tokens, total_tokens, latency_ms, status, error_message) "
        "VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)",
        session_id,
        user_id,
        agent_name,
        namespace,
        model,
        prompt_tokens,
        completion_tokens,
        total_tokens,
        latency_ms,
        status,
        error_message,
    )
    # Invalidate cache so next check sees updated tokens
    _session_cache.pop(session_id, None)
    if total_tokens > 0:
        logger.info(
            "Recorded: session=%s agent=%s tokens=%d status=%s",
            session_id[:12] if session_id else "none",
            agent_name or "unknown",
            total_tokens,
            status,
        )


async def _check_budget(
    session_id: str, max_tokens: int, meta: dict, model: str
) -> JSONResponse | None:
    """Check session budget. Returns 402 response if exceeded, None if OK."""
    if not session_id or max_tokens <= 0:
        return None
    used = await _get_session_tokens(session_id)
    if used >= max_tokens:
        msg = f"Session budget exceeded: {used:,}/{max_tokens:,} tokens"
        await _record_call(
            session_id=session_id,
            user_id=meta.get("user_id", ""),
            agent_name=meta.get("agent_name", ""),
            namespace=meta.get("namespace", ""),
            model=model,
            status="budget_exceeded",
            error_message=msg,
        )
        logger.warning(
            "Budget exceeded for session %s: %d/%d", session_id[:12], used, max_tokens
        )
        return JSONResponse(
            status_code=402,
            content={
                "error": {
                    "message": msg,
                    "type": "budget_exceeded",
                    "code": "budget_exceeded",
                    "tokens_used": used,
                    "tokens_budget": max_tokens,
                }
            },
        )
    return None


@app.post("/v1/chat/completions")
async def chat_completions(request: Request):
    body = await request.json()
    api_key = request.headers.get("authorization", "").removeprefix("Bearer ").strip()
    model = body.get("model", "")

    meta = _extract_metadata(body)
    session_id = meta["session_id"]
    max_tokens = meta["max_session_tokens"] or DEFAULT_SESSION_MAX_TOKENS

    logger.info(
        "LLM request: session=%s agent=%s model=%s stream=%s max_tokens=%d",
        session_id[:12] if session_id else "none",
        meta["agent_name"] or "unknown",
        model,
        body.get("stream", False),
        max_tokens,
    )

    # Budget check
    budget_resp = await _check_budget(session_id, max_tokens, meta, model)
    if budget_resp:
        return budget_resp

    start_time = time.monotonic()

    if body.get("stream"):
        return StreamingResponse(
            _stream_and_track(body, api_key, meta, start_time),
            media_type="text/event-stream",
            headers={"X-Accel-Buffering": "no", "Cache-Control": "no-cache"},
        )

    # Non-streaming: forward and record
    async with httpx.AsyncClient(timeout=httpx.Timeout(300.0)) as client:
        resp = await client.post(
            f"{LITELLM_URL}/v1/chat/completions",
            json=body,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
        )

    latency_ms = int((time.monotonic() - start_time) * 1000)

    if resp.status_code != 200:
        await _record_call(
            session_id=session_id,
            user_id=meta["user_id"],
            agent_name=meta["agent_name"],
            namespace=meta["namespace"],
            model=model,
            latency_ms=latency_ms,
            status="error",
            error_message=f"LiteLLM returned {resp.status_code}",
        )
        return JSONResponse(status_code=resp.status_code, content=resp.json())

    result = resp.json()
    usage = result.get("usage", {})
    await _record_call(
        session_id=session_id,
        user_id=meta["user_id"],
        agent_name=meta["agent_name"],
        namespace=meta["namespace"],
        model=model,
        prompt_tokens=usage.get("prompt_tokens", 0),
        completion_tokens=usage.get("completion_tokens", 0),
        total_tokens=usage.get("total_tokens", 0),
        latency_ms=latency_ms,
    )
    return result


async def _stream_and_track(body: dict, api_key: str, meta: dict, start_time: float):
    """Stream response from LiteLLM, accumulate usage, record on completion."""
    prompt_tokens = 0
    completion_tokens = 0
    total_tokens = 0
    model = body.get("model", "")

    # Ensure LiteLLM sends usage in the final chunk
    body.setdefault("stream_options", {})
    body["stream_options"]["include_usage"] = True

    async with httpx.AsyncClient(timeout=httpx.Timeout(300.0)) as client:
        async with client.stream(
            "POST",
            f"{LITELLM_URL}/v1/chat/completions",
            json=body,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
        ) as resp:
            async for line in resp.aiter_lines():
                yield line + "\n"
                if line.startswith("data: ") and line != "data: [DONE]":
                    try:
                        chunk = json.loads(line[6:])
                        usage = chunk.get("usage")
                        if usage:
                            prompt_tokens = usage.get("prompt_tokens", prompt_tokens)
                            completion_tokens = usage.get(
                                "completion_tokens", completion_tokens
                            )
                            total_tokens = usage.get("total_tokens", total_tokens)
                    except (json.JSONDecodeError, KeyError):
                        pass

    latency_ms = int((time.monotonic() - start_time) * 1000)
    await _record_call(
        session_id=meta["session_id"],
        user_id=meta["user_id"],
        agent_name=meta["agent_name"],
        namespace=meta["namespace"],
        model=model,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=total_tokens,
        latency_ms=latency_ms,
    )


@app.post("/v1/completions")
async def completions(request: Request):
    """Forward completions endpoint — same logic as chat/completions."""
    return await chat_completions(request)


@app.post("/v1/embeddings")
async def embeddings(request: Request):
    """Pass-through embeddings — tracked but no budget check."""
    body = await request.json()
    api_key = request.headers.get("authorization", "").removeprefix("Bearer ").strip()
    meta = _extract_metadata(body)

    async with httpx.AsyncClient(timeout=httpx.Timeout(60.0)) as client:
        resp = await client.post(
            f"{LITELLM_URL}/v1/embeddings",
            json=body,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
        )

    if resp.status_code == 200:
        result = resp.json()
        usage = result.get("usage", {})
        await _record_call(
            session_id=meta["session_id"],
            user_id=meta["user_id"],
            agent_name=meta["agent_name"],
            namespace=meta["namespace"],
            model=body.get("model", ""),
            prompt_tokens=usage.get("prompt_tokens", 0),
            total_tokens=usage.get("total_tokens", 0),
        )
        return result
    return JSONResponse(status_code=resp.status_code, content=resp.json())


@app.get("/v1/models")
async def models(request: Request):
    """Forward models list to LiteLLM."""
    api_key = request.headers.get("authorization", "").removeprefix("Bearer ").strip()
    async with httpx.AsyncClient(timeout=httpx.Timeout(10.0)) as client:
        resp = await client.get(
            f"{LITELLM_URL}/v1/models",
            headers={"Authorization": f"Bearer {api_key}"},
        )
    return JSONResponse(status_code=resp.status_code, content=resp.json())


@app.get("/internal/usage/{session_id}")
async def session_usage(session_id: str):
    """Return session usage summary with per-model breakdown.

    Used by kagenti-backend to serve budget stats to the UI.
    """
    if not db:
        return {
            "session_id": session_id,
            "total_tokens": 0,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "call_count": 0,
            "models": [],
        }
    # Totals
    totals = await db.fetchrow(
        "SELECT COALESCE(SUM(total_tokens), 0) as total_tokens, "
        "COALESCE(SUM(prompt_tokens), 0) as prompt_tokens, "
        "COALESCE(SUM(completion_tokens), 0) as completion_tokens, "
        "COUNT(*) as call_count "
        "FROM llm_calls WHERE session_id = $1 AND status = 'ok'",
        session_id,
    )
    # Per-model breakdown
    model_rows = await db.fetch(
        "SELECT model, "
        "COALESCE(SUM(prompt_tokens), 0) as prompt_tokens, "
        "COALESCE(SUM(completion_tokens), 0) as completion_tokens, "
        "COALESCE(SUM(total_tokens), 0) as total_tokens, "
        "COALESCE(SUM(cost_usd), 0) as cost, "
        "COUNT(*) as num_calls "
        "FROM llm_calls WHERE session_id = $1 AND status = 'ok' "
        "GROUP BY model ORDER BY SUM(total_tokens) DESC",
        session_id,
    )
    return {
        "session_id": session_id,
        "total_tokens": totals["total_tokens"],
        "prompt_tokens": totals["prompt_tokens"],
        "completion_tokens": totals["completion_tokens"],
        "call_count": totals["call_count"],
        "models": [
            {
                "model": r["model"] or "unknown",
                "prompt_tokens": r["prompt_tokens"],
                "completion_tokens": r["completion_tokens"],
                "total_tokens": r["total_tokens"],
                "cost": float(r["cost"]),
                "num_calls": r["num_calls"],
            }
            for r in model_rows
        ],
    }


@app.get("/health")
async def health():
    """Readiness/liveness probe."""
    if db:
        try:
            await db.fetchval("SELECT 1")
        except Exception:
            return JSONResponse(
                status_code=503, content={"status": "unhealthy", "db": "unreachable"}
            )
    return {"status": "healthy", "db": "connected" if db else "disabled"}
