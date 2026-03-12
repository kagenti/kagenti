# LLM Budget Proxy — Per-Session & Per-Agent Token Budget Enforcement

> **Date:** 2026-03-12
> **Status:** Design review (v2)

## Problem

1. No per-session token budget — agents run until wall-clock or iteration limit
2. No per-agent monthly budget — can't cap an agent's total spend
3. Budget resets on pod restart (in-memory counter)
4. Sub-agent (explore/delegate) LLM calls not tracked in parent budget
5. Local Llama models have $0 cost — LiteLLM's dollar-based `max_budget` needs pricing
6. Agents shouldn't talk to kagenti-backend (security boundary)
7. LiteLLM's `/spend/logs` doesn't store `session_id` in metadata — can't query per-session

## Why not just extend LiteLLM?

LiteLLM's `completion()` function is **2,384 lines** with 152 provider-specific branches.
It handles model routing, streaming, tool calls, vision, fallbacks across 1000+ providers.
Our agents use the **OpenAI-compatible API** exclusively (all models behind LiteLLM).
The proxy doesn't need any of this — it's a pass-through with budget tracking.

LiteLLM's per-key `max_budget` works for monthly agent budgets but:
- Is dollar-based only (useless for local models without pricing config)
- Has no per-session concept — only per-key
- Doesn't store `session_id` in spend logs (can't query per-session)

## Solution: Small Proxy Service with its own DB

```
Agent pod (team1 namespace)
  ChatOpenAI(base_url="http://llm-budget-proxy.kagenti-system.svc:8080/v1")
      │
      ▼
LLM Budget Proxy (kagenti-system) ─── ~300 line FastAPI app + PostgreSQL
  1. Log the request (session_id, user_id, agent_name, model, namespace)
  2. Query own DB: SELECT SUM(total_tokens) WHERE session_id = ?
  3. If over session budget → return 402
  4. Forward to LiteLLM
  5. Read response usage (total_tokens, prompt_tokens, completion_tokens)
  6. INSERT into llm_calls table
  7. Stream response back to agent
      │
      ▼
LiteLLM Proxy (kagenti-system)
  - Per-key monthly budget (max_budget on virtual key)
  - Model routing, provider abstraction
  - Spend tracking for cost analytics
```

## Database Design

### Storage: PostgreSQL

Use the existing `postgres.kagenti-system.svc:5432` (LiteLLM's postgres).
Create a new database `llm_budget` (or schema `budget` in the `litellm` database).

Auto-migration on startup via SQLAlchemy/asyncpg `CREATE TABLE IF NOT EXISTS`.

### Table: `llm_calls`

Stores every LLM call with full metadata for flexible aggregation.

```sql
CREATE TABLE IF NOT EXISTS llm_calls (
    id              BIGSERIAL PRIMARY KEY,
    request_id      UUID NOT NULL DEFAULT gen_random_uuid(),

    -- Dimensions (indexed for fast aggregation)
    session_id      TEXT NOT NULL,
    user_id         TEXT NOT NULL DEFAULT '',
    agent_name      TEXT NOT NULL DEFAULT '',
    namespace       TEXT NOT NULL DEFAULT '',
    model           TEXT NOT NULL DEFAULT '',

    -- Metrics
    prompt_tokens   INTEGER NOT NULL DEFAULT 0,
    completion_tokens INTEGER NOT NULL DEFAULT 0,
    total_tokens    INTEGER NOT NULL DEFAULT 0,
    cost_usd        REAL NOT NULL DEFAULT 0.0,
    latency_ms      INTEGER NOT NULL DEFAULT 0,

    -- Status
    status          TEXT NOT NULL DEFAULT 'ok',  -- ok, error, budget_exceeded
    error_message   TEXT,

    -- Timestamps
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- Raw metadata (for future flexibility)
    metadata        JSONB DEFAULT '{}'
);

-- Composite indexes for fast budget queries
CREATE INDEX IF NOT EXISTS idx_llm_calls_session
    ON llm_calls (session_id, created_at);
CREATE INDEX IF NOT EXISTS idx_llm_calls_agent
    ON llm_calls (agent_name, namespace, created_at);
CREATE INDEX IF NOT EXISTS idx_llm_calls_user
    ON llm_calls (user_id, created_at);

-- Partitioning by month (for efficient cleanup of old data)
-- Phase 2: convert to partitioned table
```

### Budget queries (all O(index scan))

```sql
-- Per-session token total
SELECT COALESCE(SUM(total_tokens), 0)
FROM llm_calls WHERE session_id = $1;

-- Per-agent daily tokens (floating 24h window)
SELECT COALESCE(SUM(total_tokens), 0)
FROM llm_calls WHERE agent_name = $1 AND namespace = $2
AND created_at > NOW() - INTERVAL '24 hours';

-- Per-agent monthly tokens (floating 30d window)
SELECT COALESCE(SUM(total_tokens), 0)
FROM llm_calls WHERE agent_name = $1 AND namespace = $2
AND created_at > NOW() - INTERVAL '30 days';

-- Per-user daily tokens
SELECT COALESCE(SUM(total_tokens), 0)
FROM llm_calls WHERE user_id = $1
AND created_at > NOW() - INTERVAL '24 hours';

-- DAU (distinct users today)
SELECT COUNT(DISTINCT user_id) FROM llm_calls
WHERE created_at > CURRENT_DATE;

-- MAU (distinct users last 30 days)
SELECT COUNT(DISTINCT user_id) FROM llm_calls
WHERE created_at > NOW() - INTERVAL '30 days';
```

### Budget configuration table

```sql
CREATE TABLE IF NOT EXISTS budget_limits (
    id              SERIAL PRIMARY KEY,
    scope           TEXT NOT NULL,   -- 'session', 'agent_daily', 'agent_monthly', 'user_daily'
    scope_key       TEXT NOT NULL,   -- session_id, agent_name, user_id
    namespace       TEXT NOT NULL DEFAULT '',
    max_tokens      BIGINT NOT NULL,
    max_cost_usd    REAL,            -- optional dollar limit
    window_seconds  INTEGER,         -- NULL for session (lifetime), 86400 for daily, etc.
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    UNIQUE(scope, scope_key, namespace)
);

-- Defaults inserted on startup
-- INSERT INTO budget_limits (scope, scope_key, max_tokens, window_seconds)
-- VALUES ('session', '*', 1000000, NULL),           -- 1M tokens per session (default)
--        ('agent_daily', '*', 5000000, 86400),      -- 5M tokens/day per agent
--        ('agent_monthly', '*', 50000000, 2592000); -- 50M tokens/month per agent
```

## Proxy Service Design

### Tech stack
- **FastAPI** (async, streaming support, auto-docs)
- **asyncpg** (async PostgreSQL, fast)
- **httpx** (async HTTP client for LiteLLM forwarding)
- **uvicorn** (ASGI server)

### Endpoints

```
POST /v1/chat/completions     — Budget-checked proxy (OpenAI-compatible)
POST /v1/completions          — Same
POST /v1/embeddings           — Pass-through (tracked but no budget check)
GET  /v1/models               — Forward to LiteLLM
GET  /internal/usage/{session_id}  — Session usage summary (for UI)
GET  /health                  — Readiness probe
```

### Request flow

```python
@app.post("/v1/chat/completions")
async def chat_completions(request: Request):
    body = await request.json()
    api_key = extract_api_key(request)
    metadata = (body.get("extra_body") or {}).get("metadata", {})
    session_id = metadata.get("session_id", "")
    agent_name = metadata.get("agent_name", "")
    user_id = metadata.get("user_id", "")
    namespace = metadata.get("namespace", "")
    max_session_tokens = int(metadata.get("max_session_tokens", 0))

    # 1. Check session budget
    if session_id and max_session_tokens > 0:
        used = await db.fetchval(
            "SELECT COALESCE(SUM(total_tokens), 0) FROM llm_calls WHERE session_id = $1",
            session_id,
        )
        if used >= max_session_tokens:
            # Log the rejected call
            await db.execute(
                "INSERT INTO llm_calls (session_id, user_id, agent_name, namespace, model, status, error_message) "
                "VALUES ($1, $2, $3, $4, $5, 'budget_exceeded', $6)",
                session_id, user_id, agent_name, namespace, body.get("model", ""),
                f"Session budget exceeded: {used:,}/{max_session_tokens:,} tokens",
            )
            return JSONResponse(status_code=402, content={
                "error": {
                    "message": f"Session budget exceeded: {used:,}/{max_session_tokens:,} tokens",
                    "type": "budget_exceeded",
                    "code": "budget_exceeded",
                    "tokens_used": used,
                    "tokens_budget": max_session_tokens,
                }
            })

    # 2. Check agent daily/monthly budget (from budget_limits table)
    # ... similar query with time window

    # 3. Forward to LiteLLM
    start_time = time.monotonic()
    if body.get("stream"):
        return StreamingResponse(
            stream_and_track(body, api_key, session_id, agent_name, user_id, namespace, start_time),
            media_type="text/event-stream",
        )
    else:
        resp = await forward_to_litellm(body, api_key)
        usage = resp.get("usage", {})
        latency = int((time.monotonic() - start_time) * 1000)

        # 4. Record the call
        await db.execute(
            "INSERT INTO llm_calls (session_id, user_id, agent_name, namespace, model, "
            "prompt_tokens, completion_tokens, total_tokens, latency_ms) "
            "VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)",
            session_id, user_id, agent_name, namespace, body.get("model", ""),
            usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0),
            usage.get("total_tokens", 0), latency,
        )
        return resp


async def stream_and_track(body, api_key, session_id, agent_name, user_id, namespace, start_time):
    """Stream response from LiteLLM, accumulate usage, record on completion."""
    total_tokens = 0
    prompt_tokens = 0
    completion_tokens = 0
    model = body.get("model", "")

    async with httpx.AsyncClient(timeout=300) as client:
        async with client.stream(
            "POST", f"{LITELLM_URL}/v1/chat/completions",
            json=body,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        ) as resp:
            async for line in resp.aiter_lines():
                yield line + "\n"
                # Parse SSE data for usage in final chunk
                if line.startswith("data: ") and line != "data: [DONE]":
                    try:
                        chunk = json.loads(line[6:])
                        usage = chunk.get("usage")
                        if usage:
                            prompt_tokens = usage.get("prompt_tokens", prompt_tokens)
                            completion_tokens = usage.get("completion_tokens", completion_tokens)
                            total_tokens = usage.get("total_tokens", total_tokens)
                    except json.JSONDecodeError:
                        pass

    # Record after stream completes
    latency = int((time.monotonic() - start_time) * 1000)
    await db.execute(
        "INSERT INTO llm_calls (session_id, user_id, agent_name, namespace, model, "
        "prompt_tokens, completion_tokens, total_tokens, latency_ms) "
        "VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)",
        session_id, user_id, agent_name, namespace, model,
        prompt_tokens, completion_tokens, total_tokens, latency,
    )
```

### In-memory cache

Cache session token sums for 5 seconds to avoid hitting the DB on every call:

```python
_session_cache: dict[str, tuple[int, float]] = {}  # session_id → (tokens, timestamp)

async def get_session_tokens(session_id: str) -> int:
    cached = _session_cache.get(session_id)
    if cached and time.monotonic() - cached[1] < 5.0:
        return cached[0]
    tokens = await db.fetchval(
        "SELECT COALESCE(SUM(total_tokens), 0) FROM llm_calls WHERE session_id = $1",
        session_id,
    )
    _session_cache[session_id] = (tokens, time.monotonic())
    return tokens
```

## Deployment

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: llm-budget-proxy
  namespace: kagenti-system
spec:
  replicas: 1
  template:
    spec:
      containers:
      - name: proxy
        image: <charts/kagenti/images/llm-budget-proxy>
        ports:
        - containerPort: 8080
        env:
        - name: LITELLM_URL
          value: "http://litellm-proxy.kagenti-system.svc:4000"
        - name: DATABASE_URL
          value: "postgresql://budget:password@postgres.kagenti-system.svc:5432/llm_budget"
        - name: DEFAULT_SESSION_MAX_TOKENS
          value: "1000000"
---
apiVersion: v1
kind: Service
metadata:
  name: llm-budget-proxy
  namespace: kagenti-system
spec:
  ports:
  - port: 8080
  # No Route — internal only, accessible from agent namespaces via Istio mTLS
```

### Auto-migration on startup

```python
@app.on_event("startup")
async def startup():
    global db
    db = await asyncpg.create_pool(DATABASE_URL)
    async with db.acquire() as conn:
        await conn.execute(CREATE_TABLES_SQL)
        await conn.execute(CREATE_INDEXES_SQL)
        await conn.execute(INSERT_DEFAULT_BUDGETS_SQL)
    logger.info("LLM Budget Proxy ready — DB migrated")
```

## Agent Changes

Minimal — just change the LLM base URL and handle 402:

```python
# graph.py — point to proxy instead of LiteLLM
llm = ChatOpenAI(
    base_url=os.environ.get("LLM_API_BASE", "http://llm-budget-proxy.kagenti-system.svc:8080/v1"),
    ...
)

# reasoning.py — handle budget exceeded
try:
    response = await llm.ainvoke(messages)
except Exception as e:
    if "budget_exceeded" in str(e).lower() or "402" in str(e):
        return {"messages": [AIMessage(content=str(e))], "done": True, ...}
    raise
```

## Wizard Integration (Phase 2)

When deploying an agent, the wizard:
1. Creates a LiteLLM virtual key with `max_budget` (monthly dollar limit)
2. Inserts `budget_limits` rows for the agent (daily/monthly token limits)
3. Stores the virtual key in the agent's K8s secret
4. Sets `LLM_API_BASE` to the proxy URL

## Floating Window Limits

The `created_at` timestamp + `window_seconds` in `budget_limits` enables:

```sql
-- Floating 24h window
SELECT COALESCE(SUM(total_tokens), 0) FROM llm_calls
WHERE agent_name = $1 AND created_at > NOW() - make_interval(secs => $2);
```

This naturally handles:
- **Session budget**: `window_seconds = NULL` → sum all time for session
- **Daily limit**: `window_seconds = 86400` → sliding 24h window
- **Monthly limit**: `window_seconds = 2592000` → sliding 30d window
- **Hourly rate limit**: `window_seconds = 3600` → sliding 1h window

## Analytics Queries (future UI dashboard)

The `llm_calls` table enables rich analytics:

```sql
-- Top agents by token usage (last 7 days)
SELECT agent_name, namespace, SUM(total_tokens) as tokens, COUNT(*) as calls
FROM llm_calls WHERE created_at > NOW() - INTERVAL '7 days'
GROUP BY agent_name, namespace ORDER BY tokens DESC;

-- Per-model usage breakdown
SELECT model, SUM(total_tokens), COUNT(*), AVG(latency_ms)
FROM llm_calls GROUP BY model;

-- DAU/MAU
SELECT COUNT(DISTINCT user_id) as dau FROM llm_calls WHERE created_at > CURRENT_DATE;
SELECT COUNT(DISTINCT user_id) as mau FROM llm_calls WHERE created_at > NOW() - INTERVAL '30 days';

-- Session cost ranking
SELECT session_id, agent_name, SUM(total_tokens), SUM(cost_usd)
FROM llm_calls GROUP BY session_id, agent_name ORDER BY SUM(total_tokens) DESC LIMIT 20;
```

## Security

- **No external route** — service only accessible within the cluster via mTLS
- **Agents cannot reach kagenti-backend** — only the proxy
- **API key pass-through** — proxy forwards the agent's key to LiteLLM, doesn't store it
- **DB access** — proxy has its own DB user, separate from LiteLLM's tables

## Phased Rollout

### Phase 1: Proxy + Session Budget
- Deploy llm-budget-proxy with PostgreSQL
- Agent points `LLM_API_BASE` to proxy
- Session budget from `SANDBOX_MAX_TOKENS` in request metadata
- Track all calls in `llm_calls` table
- Agent handles 402 error → visible failure in UI

### Phase 2: Wizard + Virtual Keys + Agent Budget
- Wizard creates per-agent LiteLLM key + budget_limits rows
- Daily/monthly agent budgets enforced by proxy
- Model pricing configured in LiteLLM
- Budget visible in wizard and session UI

### Phase 3: UI Key/Budget Management
- Kagenti UI section for LLM keys and budgets
- Import new models, associate to keys
- Usage dashboards (DAU/MAU, per-agent, per-model)
- Per-session budget override via UI

### Phase 4: Advanced Limits
- Floating window rate limits (tokens/minute, requests/hour)
- Per-user budgets
- Table partitioning for old data cleanup
- Cost alerting

## Database Ownership Model

Each team namespace has a PostgreSQL server (`postgres-sessions`) that hosts
databases for different services. Each service owns its DB and migrations.

```
postgres-sessions.team1.svc:5432
  ├── sessions        (owned by kagenti-backend, migrations in backend code)
  │   └── tasks       — A2A task store, session history, loop events
  │   └── checkpoints — LangGraph checkpoint tables
  │
  └── llm_budget      (owned by llm-budget-proxy, migrations in proxy code)
      └── llm_calls   — per-call token tracking
      └── budget_limits — configurable budget rules
```

### Who manages what

| Concern | Owner | Where |
|---------|-------|-------|
| PostgreSQL server | Deploy scripts | `.github/scripts/` or Ansible |
| `sessions` DB + user | Deploy scripts (create) | Provisioning step |
| `sessions` tables | kagenti-backend (migrate) | `backend/app/services/session_db.py` |
| `llm_budget` DB + user | Deploy scripts (create) | Provisioning step |
| `llm_budget` tables | llm-budget-proxy (migrate) | Proxy startup |
| DB credentials → secrets | Deploy scripts | K8s Secrets |

### Provisioning flow

```
Deploy scripts (runs once per team namespace):

1. Deploy postgres StatefulSet
   kubectl apply -f postgres-sessions.yaml -n team1

2. Create databases and users (via psql init script or Job)
   CREATE USER sessions_user WITH PASSWORD '...';
   CREATE DATABASE sessions OWNER sessions_user;

   CREATE USER llm_budget_user WITH PASSWORD '...';
   CREATE DATABASE llm_budget OWNER llm_budget_user;

3. Store credentials in K8s secrets
   # For kagenti-backend (in kagenti-system, reads team1 DB)
   kubectl create secret generic sessions-db-team1 \
     -n kagenti-system \
     --from-literal=url=postgresql://sessions_user:pass@postgres-sessions.team1.svc:5432/sessions

   # For llm-budget-proxy (in team1 or kagenti-system)
   kubectl create secret generic llm-budget-db \
     -n team1 \
     --from-literal=url=postgresql://llm_budget_user:pass@postgres-sessions.team1.svc:5432/llm_budget
```

**Services never create databases or users.** They only run table-level
migrations (`CREATE TABLE IF NOT EXISTS`) using the credentials they receive.

### Proxy DB connection

```python
# Credentials come from K8s secret, mounted as env var
DATABASE_URL = os.environ["DATABASE_URL"]
# e.g. postgresql://llm_budget_user:pass@postgres-sessions.team1.svc:5432/llm_budget

@app.on_event("startup")
async def startup():
    global db
    db = await asyncpg.create_pool(DATABASE_URL)
    # Table-level migrations only — DB and user already exist
    async with db.acquire() as conn:
        await conn.execute(CREATE_TABLES_SQL)
        await conn.execute(CREATE_INDEXES_SQL)
        await conn.execute(INSERT_DEFAULT_BUDGETS_SQL)
    logger.info("LLM Budget Proxy ready — tables migrated")
```

### Deploy script changes (Phase 1)

The existing deploy scripts (e.g. `.github/scripts/local-setup/`) already:
- Deploy `postgres-sessions` StatefulSet in team namespaces
- Create `sessions` DB + user
- Store credentials in K8s Secrets

**Add to the same scripts:**
```bash
# After creating sessions DB, also create llm_budget DB + user
kubectl exec -n $NAMESPACE postgres-sessions-0 -- psql -U postgres -c \
  "CREATE USER llm_budget_user WITH PASSWORD '$LLM_BUDGET_DB_PASSWORD';"
kubectl exec -n $NAMESPACE postgres-sessions-0 -- psql -U postgres -c \
  "CREATE DATABASE llm_budget OWNER llm_budget_user;"

# Create secret for llm-budget-proxy
kubectl create secret generic llm-budget-db-secret -n $NAMESPACE \
  --from-literal=host=postgres-sessions.$NAMESPACE.svc \
  --from-literal=port=5432 \
  --from-literal=database=llm_budget \
  --from-literal=username=llm_budget_user \
  --from-literal=password=$LLM_BUDGET_DB_PASSWORD
```

### Wizard: no DB changes needed

The wizard (`sandbox_deploy.py`) does NOT create databases — it only creates
K8s Deployments, Services, Secrets, and PVCs. DB provisioning is handled
by the deploy scripts. No wizard changes needed for the proxy DB.

The wizard will need changes in **Phase 2** to:
- Select existing LiteLLM models for the agent
- Set session token budget (passed as `SANDBOX_MAX_TOKENS` env var)
- Create LiteLLM virtual key for the agent (monthly budget)

### Future: team provisioning operator

When a new team namespace is created by the operator:
1. Deploy `postgres-sessions` StatefulSet
2. Run DB/user provisioning Job (creates `sessions` + `llm_budget` DBs + users)
3. Create K8s Secrets with credentials
4. Deploy llm-budget-proxy with secret reference
5. Configure network policies (agent → proxy, proxy → postgres, proxy → litellm)

### Multi-namespace support

The proxy is deployed once in `kagenti-system` but needs to access postgres
in each team namespace. Options:

**A) One proxy per namespace** — simplest, proxy deployed alongside agents.
Each connects to its own namespace's postgres.

**B) Single proxy, multiple DB connections** — proxy in kagenti-system
maintains connection pools to each team's postgres. Namespace extracted
from request metadata.

Recommendation: **A for now** (one proxy per namespace, deployed by the
agent provisioning scripts). Simpler, matches the existing pattern where
each namespace has its own services.

## Open Questions

1. **Streaming token counting**: LiteLLM includes `usage` in the final SSE chunk
   (`stream_options.include_usage = true`). Need to verify this works with our
   LiteLLM version.

2. **Multi-replica proxy**: Session token cache is per-process. With 2+ replicas,
   queries may see stale counts. Acceptable with 5s cache TTL + DB as source of truth.

3. **Proxy placement**: One per namespace (option A) or single in kagenti-system
   (option B)? Start with A, consolidate later if needed.
