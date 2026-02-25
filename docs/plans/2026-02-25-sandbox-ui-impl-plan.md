# Sandbox Agent Management UI — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add session-persisted sandbox agent management to Kagenti with sidebar tree, chat-first UX, searchable table, and per-namespace PostgreSQL.

**Architecture:** FastAPI backend gets a new `sandbox` router with dynamic per-namespace Postgres pool discovery. React UI adds a SandboxPage with session sidebar tree (last 20, collapsible parent→child), chat panel with expandable advanced config, and full sessions table. LangGraph agents use AsyncPostgresSaver for checkpoint persistence.

**Tech Stack:** FastAPI + asyncpg (backend), React + PatternFly + TanStack Query (UI), PostgreSQL 16 (sessions DB), LangGraph AsyncPostgresSaver (checkpointer), Playwright (E2E tests)

**Design doc:** `docs/plans/2026-02-25-sandbox-ui-design.md`

---

## Task 1: Deploy PostgreSQL for Sessions (team1 namespace)

**Files:**
- Create: `deployments/sandbox/postgres-sessions.yaml`

**Step 1: Write the Kubernetes manifests**

```yaml
# deployments/sandbox/postgres-sessions.yaml
apiVersion: v1
kind: Secret
metadata:
  name: postgres-sessions-secret
  namespace: team1
stringData:
  host: postgres-sessions.team1
  port: "5432"
  database: sessions
  username: kagenti
  password: kagenti-sessions-dev
---
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: postgres-sessions
  namespace: team1
  labels:
    app.kubernetes.io/name: postgres-sessions
spec:
  replicas: 1
  serviceName: postgres-sessions
  selector:
    matchLabels:
      app.kubernetes.io/name: postgres-sessions
  template:
    metadata:
      labels:
        app.kubernetes.io/name: postgres-sessions
    spec:
      containers:
      - name: postgres
        image: postgres:16-alpine
        env:
        - name: POSTGRES_DB
          value: sessions
        - name: POSTGRES_USER
          value: kagenti
        - name: POSTGRES_PASSWORD
          valueFrom:
            secretKeyRef:
              name: postgres-sessions-secret
              key: password
        - name: PGDATA
          value: /var/lib/postgresql/data/pgdata
        ports:
        - containerPort: 5432
        resources:
          requests:
            cpu: 100m
            memory: 256Mi
          limits:
            cpu: 500m
            memory: 512Mi
        volumeMounts:
        - name: data
          mountPath: /var/lib/postgresql/data
  volumeClaimTemplates:
  - metadata:
      name: data
    spec:
      accessModes: [ReadWriteOnce]
      resources:
        requests:
          storage: 5Gi
---
apiVersion: v1
kind: Service
metadata:
  name: postgres-sessions
  namespace: team1
spec:
  selector:
    app.kubernetes.io/name: postgres-sessions
  ports:
  - port: 5432
    targetPort: 5432
```

**Step 2: Deploy and verify**

```bash
kubectl apply -f deployments/sandbox/postgres-sessions.yaml
kubectl rollout status statefulset/postgres-sessions -n team1 --timeout=120s
kubectl exec -n team1 postgres-sessions-0 -- psql -U kagenti -d sessions -c '\dt'
```

**Step 3: Commit**

```bash
git add deployments/sandbox/postgres-sessions.yaml
git commit -s -m "feat: add postgres-sessions StatefulSet for sandbox session persistence"
```

---

## Task 2: Backend — Session DB Pool Manager

**Files:**
- Create: `kagenti/backend/app/services/session_db.py`
- Modify: `kagenti/backend/app/main.py` (add startup/shutdown hooks)

**Step 1: Write the pool manager**

```python
# kagenti/backend/app/services/session_db.py
"""Dynamic per-namespace PostgreSQL connection pool manager.

Discovers DB connection from postgres-sessions-secret in each namespace.
Pools are created lazily on first access and cached.
"""
import asyncpg
import base64
import logging
from kubernetes import client as k8s_client, config as k8s_config

logger = logging.getLogger(__name__)

_pool_cache: dict[str, asyncpg.Pool] = {}

# Pool limits
POOL_MIN_SIZE = 2
POOL_MAX_SIZE = 10
POOL_MAX_INACTIVE_LIFETIME = 300  # seconds


async def get_session_pool(namespace: str) -> asyncpg.Pool:
    """Get or create a connection pool for a namespace's session DB."""
    if namespace in _pool_cache:
        return _pool_cache[namespace]

    dsn = _discover_dsn(namespace)
    pool = await asyncpg.create_pool(
        dsn,
        min_size=POOL_MIN_SIZE,
        max_size=POOL_MAX_SIZE,
        max_inactive_connection_lifetime=POOL_MAX_INACTIVE_LIFETIME,
    )
    _pool_cache[namespace] = pool
    logger.info("Created session DB pool for namespace %s", namespace)
    return pool


def _discover_dsn(namespace: str) -> str:
    """Read DB connection from postgres-sessions-secret in namespace."""
    try:
        k8s_config.load_incluster_config()
    except k8s_config.ConfigException:
        k8s_config.load_kube_config()

    v1 = k8s_client.CoreV1Api()
    try:
        secret = v1.read_namespaced_secret("postgres-sessions-secret", namespace)
        data = secret.data or {}
        host = base64.b64decode(data.get("host", "")).decode()
        port = base64.b64decode(data.get("port", "")).decode() or "5432"
        database = base64.b64decode(data.get("database", "")).decode()
        username = base64.b64decode(data.get("username", "")).decode()
        password = base64.b64decode(data.get("password", "")).decode()
        return f"postgresql://{username}:{password}@{host}:{port}/{database}"
    except Exception:
        # Fallback: convention-based
        logger.warning("No postgres-sessions-secret in %s, using convention", namespace)
        return f"postgresql://kagenti:kagenti@postgres-sessions.{namespace}:5432/sessions"


async def close_all_pools():
    """Close all cached pools (call on shutdown)."""
    for ns, pool in _pool_cache.items():
        await pool.close()
        logger.info("Closed session DB pool for namespace %s", ns)
    _pool_cache.clear()


async def ensure_schema(namespace: str):
    """Create session tables if they don't exist."""
    pool = await get_session_pool(namespace)
    async with pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                context_id    TEXT PRIMARY KEY,
                parent_id     TEXT REFERENCES sessions(context_id),
                owner_user    TEXT NOT NULL,
                owner_group   TEXT NOT NULL,
                title         TEXT,
                status        TEXT DEFAULT 'active',
                agent_name    TEXT NOT NULL,
                config        JSONB,
                created_at    TIMESTAMPTZ DEFAULT NOW(),
                updated_at    TIMESTAMPTZ DEFAULT NOW(),
                completed_at  TIMESTAMPTZ
            );
            CREATE TABLE IF NOT EXISTS session_messages (
                id            SERIAL PRIMARY KEY,
                context_id    TEXT REFERENCES sessions(context_id) ON DELETE CASCADE,
                role          TEXT NOT NULL,
                content       TEXT NOT NULL,
                actor_user    TEXT,
                created_at    TIMESTAMPTZ DEFAULT NOW()
            );
            CREATE INDEX IF NOT EXISTS idx_sessions_owner ON sessions(owner_user);
            CREATE INDEX IF NOT EXISTS idx_sessions_group ON sessions(owner_group);
            CREATE INDEX IF NOT EXISTS idx_sessions_parent ON sessions(parent_id);
            CREATE INDEX IF NOT EXISTS idx_sessions_status ON sessions(status);
            CREATE INDEX IF NOT EXISTS idx_messages_context ON session_messages(context_id);
        """)
```

**Step 2: Wire into FastAPI lifecycle**

Add to `kagenti/backend/app/main.py`:
```python
from app.services.session_db import close_all_pools

@app.on_event("shutdown")
async def shutdown():
    await close_all_pools()
```

**Step 3: Commit**

```bash
git add kagenti/backend/app/services/session_db.py kagenti/backend/app/main.py
git commit -s -m "feat: add dynamic per-namespace session DB pool manager"
```

---

## Task 3: Backend — Sandbox Sessions Router

**Files:**
- Create: `kagenti/backend/app/routers/sandbox.py`
- Modify: `kagenti/backend/app/main.py` (register router)

**Step 1: Write the router**

```python
# kagenti/backend/app/routers/sandbox.py
"""Sandbox session management API.

Endpoints for listing, creating, and managing sandbox agent sessions.
Session data is stored in per-namespace PostgreSQL.
"""
import logging
from datetime import datetime, timezone
from typing import Optional
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from app.services.session_db import get_session_pool, ensure_schema

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/sandbox", tags=["sandbox"])


# --- Request/Response models ---

class SessionSummary(BaseModel):
    context_id: str
    parent_id: Optional[str] = None
    title: Optional[str] = None
    status: str
    agent_name: str
    owner_user: str
    created_at: datetime
    updated_at: datetime

class SessionDetail(SessionSummary):
    config: Optional[dict] = None
    completed_at: Optional[datetime] = None
    children: list[SessionSummary] = []
    messages: list[dict] = []

class CreateSessionRequest(BaseModel):
    agent_name: str = "sandbox-agent"
    model: str = "gpt-4o-mini"
    repo: Optional[str] = None
    branch: str = "main"
    workspace_size: str = "5Gi"

class SendMessageRequest(BaseModel):
    message: str
    actor_user: Optional[str] = None


# --- Endpoints ---

@router.get("/{namespace}/sessions")
async def list_sessions(
    namespace: str,
    limit: int = Query(20, le=100),
    offset: int = Query(0, ge=0),
    status: Optional[str] = None,
    search: Optional[str] = None,
) -> dict:
    await ensure_schema(namespace)
    pool = await get_session_pool(namespace)

    conditions = ["1=1"]
    params = []
    idx = 1

    if status:
        conditions.append(f"status = ${idx}")
        params.append(status)
        idx += 1
    if search:
        conditions.append(f"(title ILIKE ${idx} OR context_id ILIKE ${idx})")
        params.append(f"%{search}%")
        idx += 1

    where = " AND ".join(conditions)

    async with pool.acquire() as conn:
        total = await conn.fetchval(
            f"SELECT COUNT(*) FROM sessions WHERE {where}", *params
        )
        rows = await conn.fetch(
            f"""SELECT context_id, parent_id, title, status, agent_name,
                       owner_user, created_at, updated_at
                FROM sessions WHERE {where}
                ORDER BY updated_at DESC
                LIMIT ${idx} OFFSET ${idx+1}""",
            *params, limit, offset,
        )

    return {
        "items": [dict(r) for r in rows],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.get("/{namespace}/sessions/{context_id}")
async def get_session(namespace: str, context_id: str) -> SessionDetail:
    await ensure_schema(namespace)
    pool = await get_session_pool(namespace)

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM sessions WHERE context_id = $1", context_id
        )
        if not row:
            raise HTTPException(404, f"Session {context_id} not found")

        children = await conn.fetch(
            """SELECT context_id, parent_id, title, status, agent_name,
                      owner_user, created_at, updated_at
               FROM sessions WHERE parent_id = $1
               ORDER BY created_at""",
            context_id,
        )
        messages = await conn.fetch(
            """SELECT role, content, actor_user, created_at
               FROM session_messages WHERE context_id = $1
               ORDER BY created_at""",
            context_id,
        )

    return SessionDetail(
        **dict(row),
        children=[SessionSummary(**dict(c)) for c in children],
        messages=[dict(m) for m in messages],
    )


@router.delete("/{namespace}/sessions/{context_id}")
async def delete_session(namespace: str, context_id: str) -> dict:
    pool = await get_session_pool(namespace)
    async with pool.acquire() as conn:
        result = await conn.execute(
            "DELETE FROM sessions WHERE context_id = $1", context_id
        )
    if result == "DELETE 0":
        raise HTTPException(404, f"Session {context_id} not found")
    return {"deleted": context_id}


@router.post("/{namespace}/sessions/{context_id}/kill")
async def kill_session(namespace: str, context_id: str) -> dict:
    pool = await get_session_pool(namespace)
    async with pool.acquire() as conn:
        result = await conn.execute(
            """UPDATE sessions SET status = 'killed',
                      completed_at = NOW(), updated_at = NOW()
               WHERE context_id = $1 AND status = 'active'""",
            context_id,
        )
    if result == "UPDATE 0":
        raise HTTPException(404, f"Session {context_id} not found or not active")
    return {"killed": context_id}
```

**Step 2: Register router in main.py**

```python
from app.routers import sandbox
app.include_router(sandbox.router)
```

**Step 3: Commit**

```bash
git add kagenti/backend/app/routers/sandbox.py kagenti/backend/app/main.py
git commit -s -m "feat: add sandbox sessions API router"
```

---

## Task 4: Agent — Wire AsyncPostgresSaver + Session Metadata

**Files:**
- Modify: `a2a/sandbox_agent/src/sandbox_agent/agent.py` (agent-examples repo)
- Modify: `a2a/sandbox_agent/pyproject.toml` (add asyncpg, langgraph-checkpoint-postgres)

**Step 1: Add dependencies**

In `pyproject.toml`, add:
```toml
dependencies = [
    # ... existing ...
    "langgraph-checkpoint-postgres>=2.0.0",
    "asyncpg>=0.30.0",
]
```

**Step 2: Replace MemorySaver with AsyncPostgresSaver**

In `agent.py`, update `SandboxAgentExecutor.__init__()`:
```python
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

class SandboxAgentExecutor(AgentExecutor):
    def __init__(self) -> None:
        # ... existing setup ...
        config = Configuration()

        # Use PostgreSQL checkpointer if configured, else MemorySaver
        if config.checkpoint_db_url and config.checkpoint_db_url != "memory":
            import asyncpg
            self._checkpointer = AsyncPostgresSaver.from_conn_string(
                config.checkpoint_db_url
            )
        else:
            self._checkpointer = MemorySaver()
```

**Step 3: Write session metadata on each message**

In the `execute()` method, after resolving workspace, insert session row:
```python
# Record session in DB
if hasattr(self._checkpointer, 'conn'):  # PostgreSQL mode
    await self._record_session(context_id, context)
```

**Step 4: Commit**

```bash
git add a2a/sandbox_agent/src/sandbox_agent/agent.py a2a/sandbox_agent/pyproject.toml
git commit -s -m "feat: wire AsyncPostgresSaver for session persistence"
```

---

## Task 5: UI — Session Sidebar Component

**Files:**
- Create: `kagenti/ui-v2/src/components/SessionSidebar.tsx`
- Create: `kagenti/ui-v2/src/services/sandbox.ts`
- Create: `kagenti/ui-v2/src/types/sandbox.ts`

**Step 1: Add types**

```typescript
// kagenti/ui-v2/src/types/sandbox.ts
export interface SessionSummary {
  context_id: string;
  parent_id: string | null;
  title: string | null;
  status: 'active' | 'completed' | 'failed' | 'killed';
  agent_name: string;
  owner_user: string;
  created_at: string;
  updated_at: string;
}

export interface SessionDetail extends SessionSummary {
  config: Record<string, unknown> | null;
  completed_at: string | null;
  children: SessionSummary[];
  messages: SessionMessage[];
}

export interface SessionMessage {
  role: 'user' | 'assistant';
  content: string;
  actor_user: string | null;
  created_at: string;
}

export interface SessionListResponse {
  items: SessionSummary[];
  total: number;
  limit: number;
  offset: number;
}
```

**Step 2: Add sandbox API service**

```typescript
// kagenti/ui-v2/src/services/sandbox.ts
import { apiClient } from './api';
import { SessionListResponse, SessionDetail } from '../types/sandbox';

export const sandboxService = {
  listSessions: (namespace: string, params?: { limit?: number; status?: string; search?: string }) =>
    apiClient.get<SessionListResponse>(`/api/v1/sandbox/${namespace}/sessions`, { params }),

  getSession: (namespace: string, contextId: string) =>
    apiClient.get<SessionDetail>(`/api/v1/sandbox/${namespace}/sessions/${contextId}`),

  deleteSession: (namespace: string, contextId: string) =>
    apiClient.delete(`/api/v1/sandbox/${namespace}/sessions/${contextId}`),

  killSession: (namespace: string, contextId: string) =>
    apiClient.post(`/api/v1/sandbox/${namespace}/sessions/${contextId}/kill`),
};
```

**Step 3: Write SessionSidebar component**

```typescript
// kagenti/ui-v2/src/components/SessionSidebar.tsx
// PatternFly TreeView with status indicators
// Shows last 20 sessions, collapsible parent→child
// Search box, + New Session, View All link
```

**Step 4: Commit**

---

## Task 6: UI — Sandbox Page with Chat

**Files:**
- Create: `kagenti/ui-v2/src/pages/SandboxPage.tsx`
- Modify: `kagenti/ui-v2/src/App.tsx` (add route)
- Modify: `kagenti/ui-v2/src/components/AppLayout.tsx` (add nav item)

**Step 1: Create SandboxPage**

Layout: SessionSidebar on left, chat panel on right. Reuses AgentChat patterns but targets sandbox agent.

**Step 2: Add route**

In `App.tsx`: `/sandbox` → `SandboxPage`, `/sandbox/sessions` → `SessionsTablePage`

**Step 3: Add nav item**

In `AppLayout.tsx`, add "Sandbox" under "Agentic Workloads" nav group.

**Step 4: Commit**

---

## Task 7: UI — Sessions Table Page

**Files:**
- Create: `kagenti/ui-v2/src/pages/SessionsTablePage.tsx`

PatternFly Table with search, filter, pagination, bulk actions (kill, delete). Row click → navigates to `/sandbox?session={contextId}`.

---

## Task 8: UI — Advanced Config Panel

**Files:**
- Create: `kagenti/ui-v2/src/components/SandboxConfig.tsx`

Expandable panel with model dropdown, repo/branch inputs, skills multi-select, workspace size, TTL, namespace selector.

---

## Task 9: Playwright E2E Tests

**Files:**
- Create: `kagenti/ui-v2/e2e/sandbox.spec.ts`
- Create: `kagenti/tests/e2e/common/test_sandbox_sessions_api.py`

**UI Tests:**
- Login → navigate to Sandbox → start chat → verify response
- Session appears in sidebar
- Click sidebar session → loads history
- Advanced config toggle
- Sessions table search/filter
- Kill session → verify status change

**Backend API Tests:**
- Create session via API → verify in list
- Send messages → verify persistence
- Delete session → verify gone
- Sub-session parent→child relationship
- RBAC: user only sees own namespace

---

## Task 10: Update Research Doc + Passover

**Files:**
- Modify: `docs/plans/2026-02-23-sandbox-agent-research.md` (add C21: Session Persistence)
- Create: `docs/plans/2026-02-25-sandbox-ui-passover.md`

Add C21 to capability matrix, update implementation status, write passover for next session.

---

## Execution Order

Tasks 1-3 (infra + backend) can run in parallel.
Task 4 (agent integration) depends on Task 1.
Tasks 5-8 (UI) depend on Task 3.
Task 9 (tests) depends on Tasks 5-8.
Task 10 (docs) runs last.

```
Task 1 (Postgres) ──┬── Task 4 (Agent checkpointer)
                    │
Task 2 (Pool mgr) ─┤
                    │
Task 3 (API router) ┴── Tasks 5-8 (UI) ── Task 9 (Tests) ── Task 10 (Docs)
```
