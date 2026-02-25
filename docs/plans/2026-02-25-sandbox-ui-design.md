# Sandbox Agent Management UI — Design Document

> **Date:** 2026-02-25 | **Status:** Approved for implementation

## Overview

Add a sandbox agent management UI to Kagenti that lets users spawn, chat with, and manage sandbox agents. The UI supports both a chat-first default experience and an advanced wizard for power users. Sessions are persisted in per-namespace PostgreSQL, tracked in a collapsible sidebar tree, and shared across user groups via Keycloak RBAC.

## Architecture

```
┌─── Kagenti UI (React + PatternFly) ──────────────────────────────────┐
│                                                                       │
│  [Sidebar: Session Tree]     [Main Panel: Chat / Table / Wizard]      │
│  Last 20 sessions            Chat-first default + Advanced config     │
│  Collapsible parent→child    Session table at /sandbox/sessions       │
│                                                                       │
└───────────────────────────────────┬───────────────────────────────────┘
                                    │
              ┌─────────────────────▼─────────────────────────┐
              │  Kagenti Backend (FastAPI)                      │
              │                                                │
              │  New router: /api/v1/sandbox/{namespace}/...   │
              │  - GET  /sessions (list, search, paginate)     │
              │  - GET  /sessions/{id} (detail + messages)     │
              │  - POST /create (spawn sandbox)                │
              │  - POST /chat/{id}/send (send message)         │
              │  - POST /chat/{id}/stream (SSE stream)         │
              │  - DELETE /sessions/{id} (cleanup)             │
              │  - POST /sessions/{id}/kill (force stop)       │
              │                                                │
              │  Connection pool: asyncpg per namespace         │
              │  Pool: min=2, max=10, idle_timeout=300s        │
              │  DB URL: configurable (in-cluster or external) │
              └────────────────────┬──────────────────────────┘
                                   │
         ┌─────────────────────────▼──────────────────────────┐
         │  PostgreSQL (per agent namespace)                    │
         │                                                     │
         │  Configurable: in-cluster StatefulSet OR external   │
         │  (RDS, Cloud SQL, any Postgres-compatible)          │
         │  Connection string via ConfigMap/Secret per NS      │
         │                                                     │
         │  Tables:                                            │
         │  - checkpoints (LangGraph AsyncPostgresSaver)       │
         │  - sessions (metadata, owner, status, config)       │
         │  - session_messages (chat history, actor tracking)  │
         └────────────────────────────────────────────────────┘
```

## Data Model

### sessions table

| Column | Type | Description |
|--------|------|-------------|
| `context_id` | TEXT PK | A2A context ID |
| `parent_id` | TEXT FK → sessions | Parent session (for sub-agents) |
| `owner_user` | TEXT | Keycloak username who created the session |
| `owner_group` | TEXT | Keycloak group (maps to namespace) |
| `title` | TEXT | Auto-generated from first message |
| `status` | TEXT | `active`, `completed`, `failed`, `killed` |
| `agent_name` | TEXT | e.g. `sandbox-agent` |
| `config` | JSONB | `{model, repo, branch, skills, workspace_size}` |
| `created_at` | TIMESTAMPTZ | Creation time |
| `updated_at` | TIMESTAMPTZ | Last activity |
| `completed_at` | TIMESTAMPTZ | When session ended |

### session_messages table

| Column | Type | Description |
|--------|------|-------------|
| `id` | SERIAL PK | Auto-increment |
| `context_id` | TEXT FK → sessions | Session reference |
| `role` | TEXT | `user` or `assistant` |
| `content` | TEXT | Message content |
| `actor_user` | TEXT | Who sent this (for shared sessions) |
| `created_at` | TIMESTAMPTZ | Message time |

### Indexes

```sql
CREATE INDEX idx_sessions_owner ON sessions(owner_user);
CREATE INDEX idx_sessions_group ON sessions(owner_group);
CREATE INDEX idx_sessions_parent ON sessions(parent_id);
CREATE INDEX idx_sessions_status ON sessions(status);
CREATE INDEX idx_messages_context ON session_messages(context_id);
```

## UI Components

### A. Session Sidebar (always visible, left side)

- Shows last 20 sessions (configurable)
- Collapsible tree: parent sessions with nested children (sub-agent sessions)
- Status indicators: 🟢 active, 🟡 working, ⚪ completed, 🔴 failed
- Click session → opens chat view with that contextId
- Search box at top for quick filtering
- "View All →" link navigates to full table view
- "+ New Session" button at bottom

```
┌─────────────────────┐
│ 🔍 Search sessions  │
├─────────────────────┤
│ Sandbox Sessions    │
│                     │
│ ▼ ctx-abc [RCA]  🟢 │
│   ├─ ctx-def     🟡 │
│   └─ ctx-xyz     ⚪ │
│ ▶ ctx-ghi [PR]   ⚪ │
│ ▶ ctx-jkl [test] 🟢 │
│                     │
│ [+ New Session]     │
│ [View All →]        │
└─────────────────────┘
```

### B. Chat View (main panel, default)

- Chat-first experience — user starts typing immediately
- Messages rendered with react-markdown (same as existing AgentChat)
- Agent card details in expandable header
- ⚙ "Advanced" toggle expands configuration panel
- Sub-agent activity shown inline (e.g., "Spawned explore sub-agent ctx-def")

### C. Advanced Configuration (expandable panel)

Only shown when user clicks ⚙ Advanced:

| Field | Type | Default |
|-------|------|---------|
| Repository | text input | (none — agent uses its built-in skills) |
| Branch | text input | `main` |
| Model | dropdown | `gpt-4o-mini` |
| Skills | multi-select checkboxes | All available |
| Workspace Size | dropdown | `5Gi` |
| TTL | dropdown | `7 days` |
| Namespace | dropdown | User's namespaces from Keycloak groups |

### D. Sessions Table (full page, `/sandbox/sessions`)

PatternFly Table with:
- Columns: ID, Task/Title, Owner, Status, Started, Parent, Actions
- Searchable by title, owner
- Filterable by status, date range
- Sortable by any column
- Pagination (20 per page)
- Bulk actions: kill selected, cleanup expired
- Row click → opens chat view
- Delete button visible only to session owner or namespace admin

## RBAC Model

| Role | Access |
|------|--------|
| Namespace member (Keycloak group = namespace) | Read all sessions in namespace, chat in own sessions |
| Session owner | Full control (delete, kill, share) |
| Namespace admin | Full control over all sessions in namespace |
| Platform admin | Full control everywhere |

- `actor_user` field in `session_messages` tracks who is talking in shared sessions
- Sub-sessions inherit parent's namespace access
- Backend validates JWT group claims on every request

## Backend Connection Pooling (Dynamic Discovery)

DB connections are **not hardcoded** — the backend discovers Postgres per namespace dynamically:

1. User authenticates → JWT groups = namespaces they can access
2. For each namespace, backend looks for `postgres-sessions-secret` Secret
3. Secret contains: `host`, `port`, `database`, `username`, `password`
4. Connection pools created lazily on first access, cached per namespace
5. Falls back to convention: `postgres-sessions.{namespace}:5432/sessions`

```python
# Dynamic per-namespace pool discovery
_pool_cache: dict[str, asyncpg.Pool] = {}

async def get_session_pool(namespace: str) -> asyncpg.Pool:
    """Get or create a connection pool for a namespace's session DB."""
    if namespace in _pool_cache:
        return _pool_cache[namespace]

    # Read DB connection from namespace Secret
    try:
        secret = k8s_client.read_namespaced_secret(
            "postgres-sessions-secret", namespace
        )
        dsn = _build_dsn_from_secret(secret)
    except ApiException:
        # Fallback: convention-based in-cluster Postgres
        dsn = f"postgresql://kagenti:kagenti@postgres-sessions.{namespace}:5432/sessions"

    pool = await asyncpg.create_pool(
        dsn,
        min_size=2,       # keep 2 warm connections
        max_size=10,      # max 10 concurrent per namespace
        max_inactive_connection_lifetime=300,  # close idle after 5 min
    )
    _pool_cache[namespace] = pool
    return pool
```

**External Postgres:** Users point to RDS, Cloud SQL, or any managed Postgres by creating a `postgres-sessions-secret` in their namespace:

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: postgres-sessions-secret
  namespace: team2
stringData:
  host: my-rds-instance.us-east-1.rds.amazonaws.com
  port: "5432"
  database: team2_sessions
  username: kagenti_team2
  password: <password>
```

## PostgreSQL Deployment (in-cluster option)

For dev/test, deploy a small Postgres StatefulSet per namespace:

```yaml
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: postgres-sessions
  namespace: team1
spec:
  replicas: 1
  template:
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
```

## Testing Strategy

### Backend E2E Tests
- Session CRUD via API (create, list, get, delete, kill)
- Message persistence across turns
- Sub-session parent-child relationships
- RBAC enforcement (user can only see own namespace)
- Connection pool behavior under load

### Playwright UI Tests
- Login → navigate to sandbox → start chat → verify response
- Session appears in sidebar after creation
- Click session in sidebar → loads chat history
- Advanced config panel toggle
- Session table: search, filter, pagination
- Kill session from table → verify status change
- Sub-session tree collapse/expand
- Shared session: second user sees messages with actor_user attribution

### Sandbox Agent Functional Tests
- Existing: shell, file_read, file_write, multi-turn, memory
- New: GitHub analysis, PR analysis, RCA on mock CI log
- All tests use route URL (auto-discovered, no skipif)

## Implementation Phases

1. **Postgres + Backend API** — Deploy postgres-sessions, add session router to backend, connection pooling
2. **Agent Integration** — Wire AsyncPostgresSaver into sandbox agent, write session metadata on each message
3. **UI: Chat + Sidebar** — New SandboxPage with chat view, session sidebar tree
4. **UI: Advanced Config** — Expandable config panel, sandbox creation API
5. **UI: Session Table** — Full page table with search/filter/pagination/bulk actions
6. **RBAC** — Keycloak group validation, actor_user tracking
7. **Playwright Tests** — Full test suite following existing patterns
8. **Update Research Doc** — Add C21 (session persistence) to main research document
