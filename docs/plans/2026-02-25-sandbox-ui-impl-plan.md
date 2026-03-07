# Sandbox Legion Management UI — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

> **Naming:** "Sandbox Legion" is the agent name for the flagship multi-sub-agent LangGraph orchestrator. Use `sandbox-legion` (not `sandbox-agent`) in code, configs, and agent_name fields.

**Goal:** Add session-persisted Sandbox Legion management to Kagenti with sidebar tree, chat-first UX, searchable table, and per-namespace PostgreSQL.

**Architecture:** FastAPI backend gets a new `sandbox` router with dynamic per-namespace Postgres pool discovery. React UI adds a SandboxPage with session sidebar tree (last 20, collapsible parent→child), chat panel with expandable advanced config, and full sessions table. Session persistence is handled by the **A2A SDK's DatabaseTaskStore** (framework-agnostic). Sandbox Legion additionally uses LangGraph AsyncPostgresSaver for internal graph state (HITL pause/resume).

**Tech Stack:** FastAPI + asyncpg (backend), React + PatternFly + TanStack Query (UI), PostgreSQL 16 (shared by A2A SDK DatabaseTaskStore + LangGraph AsyncPostgresSaver), Playwright (E2E tests)

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

> **IMPORTANT:** The custom `sessions` and `session_messages` tables are **REPLACED** by the A2A SDK's `DatabaseTaskStore` schema. The SDK creates and manages its own tables (`tasks`, `task_messages`, `task_artifacts`, etc.) automatically. The pool manager should provide connections for reading from these SDK-managed tables. Do NOT create custom session tables — the SDK handles schema creation.

**Files:**
- Create: `kagenti/backend/app/services/session_db.py`
- Modify: `kagenti/backend/app/main.py` (add startup/shutdown hooks)

**Step 1: Write the pool manager**

```python
# kagenti/backend/app/services/session_db.py
"""Dynamic per-namespace PostgreSQL connection pool manager.

Discovers DB connection from postgres-sessions-secret in each namespace.
Pools are created lazily on first access and cached.

NOTE: This pool is used to READ from the A2A SDK's DatabaseTaskStore tables.
The SDK manages schema creation — do NOT create custom session tables here.
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
    """Get or create a connection pool for a namespace's session DB.

    Used by the backend to read from A2A SDK DatabaseTaskStore tables.
    """
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


# NOTE: ensure_schema() is NOT needed — the A2A SDK's DatabaseTaskStore
# handles table creation automatically when the agent starts up.
# The backend only reads from these SDK-managed tables.
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

> **IMPORTANT:** The router queries the **A2A SDK's DatabaseTaskStore tables** (`tasks`, etc.) — NOT custom `sessions` / `session_messages` tables. The SDK manages the schema; the backend is a read-only consumer for UI purposes.

**Files:**
- Create: `kagenti/backend/app/routers/sandbox.py`
- Modify: `kagenti/backend/app/main.py` (register router)

**Step 1: Write the router**

```python
# kagenti/backend/app/routers/sandbox.py
"""Sandbox Legion session management API.

Endpoints for listing, creating, and managing Sandbox Legion sessions.
Session data is read from the A2A SDK's DatabaseTaskStore tables
(tasks, task_messages, etc.) in per-namespace PostgreSQL.
"""
import logging
from datetime import datetime, timezone
from typing import Optional
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from app.services.session_db import get_session_pool

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
    agent_name: str = "sandbox-legion"
    model: str = "gpt-4o-mini"
    repo: Optional[str] = None
    branch: str = "main"
    workspace_size: str = "5Gi"

class SendMessageRequest(BaseModel):
    message: str
    actor_user: Optional[str] = None


# --- Endpoints ---
# NOTE: All queries target the A2A SDK's DatabaseTaskStore tables (e.g., "tasks").
# The exact table/column names depend on the SDK version — adjust as needed.

@router.get("/{namespace}/sessions")
async def list_sessions(
    namespace: str,
    limit: int = Query(20, le=100),
    offset: int = Query(0, ge=0),
    status: Optional[str] = None,
    search: Optional[str] = None,
) -> dict:
    pool = await get_session_pool(namespace)

    conditions = ["1=1"]
    params = []
    idx = 1

    if status:
        conditions.append(f"status = ${idx}")
        params.append(status)
        idx += 1
    if search:
        conditions.append(f"(context_id ILIKE ${idx})")
        params.append(f"%{search}%")
        idx += 1

    where = " AND ".join(conditions)

    async with pool.acquire() as conn:
        # Query the A2A SDK's tasks table
        total = await conn.fetchval(
            f"SELECT COUNT(*) FROM tasks WHERE {where}", *params
        )
        rows = await conn.fetch(
            f"""SELECT id, context_id, status, created_at, updated_at
                FROM tasks WHERE {where}
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
async def get_session(namespace: str, context_id: str) -> dict:
    pool = await get_session_pool(namespace)

    async with pool.acquire() as conn:
        # Query the A2A SDK's tasks table by context_id
        row = await conn.fetchrow(
            "SELECT * FROM tasks WHERE context_id = $1", context_id
        )
        if not row:
            raise HTTPException(404, f"Session {context_id} not found")

        # Get messages from the SDK's message storage
        messages = await conn.fetch(
            """SELECT role, content, created_at
               FROM task_messages WHERE task_id = $1
               ORDER BY created_at""",
            row["id"],
        )

    return {
        "task": dict(row),
        "messages": [dict(m) for m in messages],
    }


@router.delete("/{namespace}/sessions/{context_id}")
async def delete_session(namespace: str, context_id: str) -> dict:
    pool = await get_session_pool(namespace)
    async with pool.acquire() as conn:
        result = await conn.execute(
            "DELETE FROM tasks WHERE context_id = $1", context_id
        )
    if result == "DELETE 0":
        raise HTTPException(404, f"Session {context_id} not found")
    return {"deleted": context_id}


@router.post("/{namespace}/sessions/{context_id}/kill")
async def kill_session(namespace: str, context_id: str) -> dict:
    pool = await get_session_pool(namespace)
    async with pool.acquire() as conn:
        result = await conn.execute(
            """UPDATE tasks SET status = 'canceled',
                      updated_at = NOW()
               WHERE context_id = $1 AND status IN ('submitted', 'working')""",
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

## Task 4: Agent — Wire AsyncPostgresSaver + A2A DatabaseTaskStore (Sandbox Legion)

> **Dual persistence:** Sandbox Legion uses BOTH persistence layers on the same Postgres instance (different tables):
> 1. **A2A SDK DatabaseTaskStore** — Tasks, messages, artifacts. Read by the Kagenti backend for UI. Framework-agnostic (all A2A agents use this).
> 2. **LangGraph AsyncPostgresSaver** — Graph state, checkpoints. Internal to Sandbox Legion for HITL pause/resume. NOT read by the UI.
>
> Both can share the same PostgreSQL instance with different tables. The A2A SDK manages its tables; LangGraph manages `checkpoints`.

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
    "a2a-sdk[postgresql]",
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

        # LangGraph checkpointer (graph state only — NOT session persistence)
        # Use PostgreSQL checkpointer if configured, else MemorySaver
        if config.checkpoint_db_url and config.checkpoint_db_url != "memory":
            import asyncpg
            self._checkpointer = AsyncPostgresSaver.from_conn_string(
                config.checkpoint_db_url
            )
        else:
            self._checkpointer = MemorySaver()
```

**Step 3: A2A SDK DatabaseTaskStore handles session/message persistence**

The A2A SDK's `DatabaseTaskStore` is configured at the A2A server level (not in the agent). It automatically persists tasks and messages to Postgres. No custom `_record_session()` code is needed — the SDK does this.

```python
# In the A2A server setup (NOT in the agent):
from a2a.server.tasks import DatabaseTaskStore

task_store = DatabaseTaskStore(db_url=config.task_store_db_url)
# The SDK creates and manages its own tables automatically
```

**Step 4: Commit**

```bash
git add a2a/sandbox_agent/src/sandbox_agent/agent.py a2a/sandbox_agent/pyproject.toml
git commit -s -m "feat: wire AsyncPostgresSaver + DatabaseTaskStore for Sandbox Legion"
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
