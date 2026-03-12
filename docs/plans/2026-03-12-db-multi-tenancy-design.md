# Database Multi-Tenancy — Schema-Per-Agent Isolation

> **Date:** 2026-03-12
> **Status:** Design review

## Problem

1. All agents share the same `checkpoints` table — no isolation between agents
2. Agent cleanup/delete doesn't clean up DB state (checkpoints, sessions linger)
3. No per-agent DB user — can't enforce access control at DB level
4. Need clean separation: sessions (backend-owned, shared) vs checkpoints (agent-owned, isolated)

## Architecture Overview

```mermaid
graph TB
    subgraph "Team Namespace (team1)"
        A1[sandbox-legion pod]
        A2[sandbox-hardened pod]
        A3[rca-agent pod]
        PROXY[llm-budget-proxy]
        PG[(postgres-sessions<br/>database: kagenti)]
    end

    subgraph "kagenti-system"
        BE[kagenti-backend]
        LLM[litellm-proxy]
    end

    A1 -->|"user: team1_agent_legion_user<br/>schema: team1_agent_legion"| PG
    A2 -->|"user: team1_agent_hardened_user<br/>schema: team1_agent_hardened"| PG
    A3 -->|"user: team1_agent_rca_agent_user<br/>schema: team1_agent_rca_agent"| PG
    BE -->|"user: team1_sessions_user<br/>schema: team1"| PG
    PROXY -->|"user: team1_llm_budget_user<br/>schema: team1"| PG
    A1 --> PROXY
    A2 --> PROXY
    A3 --> PROXY
    PROXY --> LLM
```

## Database Layout

```mermaid
erDiagram
    KAGENTI_DB {
        string "database: kagenti"
    }

    TEAM1_SCHEMA {
        string "schema: team1 (shared, backend-owned)"
    }
    TEAM1_SCHEMA ||--o{ TASKS : contains
    TEAM1_SCHEMA ||--o{ LLM_CALLS : contains
    TEAM1_SCHEMA ||--o{ BUDGET_LIMITS : contains

    AGENT_LEGION_SCHEMA {
        string "schema: agent_legion (per-agent, agent-owned)"
    }
    AGENT_LEGION_SCHEMA ||--o{ CHECKPOINTS : contains
    AGENT_LEGION_SCHEMA ||--o{ CHECKPOINT_BLOBS : contains
    AGENT_LEGION_SCHEMA ||--o{ CHECKPOINT_WRITES : contains
    AGENT_LEGION_SCHEMA ||--o{ CHECKPOINT_MIGRATIONS : contains

    AGENT_HARDENED_SCHEMA {
        string "schema: agent_hardened (per-agent)"
    }
    AGENT_HARDENED_SCHEMA ||--o{ CHECKPOINTS : contains
    AGENT_HARDENED_SCHEMA ||--o{ CHECKPOINT_BLOBS : contains
    AGENT_HARDENED_SCHEMA ||--o{ CHECKPOINT_WRITES : contains
    AGENT_HARDENED_SCHEMA ||--o{ CHECKPOINT_MIGRATIONS : contains
```

## Schema Ownership

| Schema | Owner | Created by | Accessed by | Contains |
|--------|-------|-----------|-------------|----------|
| `team1` | `team1_sessions_user` | Deploy scripts | kagenti-backend, llm-budget-proxy | tasks, llm_calls, budget_limits |
| `team1_agent_legion` | `team1_agent_legion_user` | Wizard (on agent deploy) | sandbox-legion pod | checkpoints, checkpoint_blobs, checkpoint_writes |
| `team1_agent_hardened` | `team1_agent_hardened_user` | Wizard (on agent deploy) | sandbox-hardened pod | checkpoints, ... |
| `team1_agent_rca_agent` | `team1_agent_rca_agent_user` | Wizard (on agent deploy) | rca-agent pod | checkpoints, ... |

## Lifecycle Flows

### Team Namespace Provisioning (deploy scripts)

```mermaid
sequenceDiagram
    participant Scripts as Deploy Scripts
    participant PG as PostgreSQL
    participant K8s as Kubernetes

    Scripts->>PG: CREATE DATABASE kagenti
    Scripts->>PG: CREATE USER team1_sessions_user WITH PASSWORD '...'
    Scripts->>PG: CREATE SCHEMA team1 AUTHORIZATION team1_sessions_user
    Scripts->>PG: ALTER USER team1_sessions_user SET search_path = team1
    Scripts->>PG: CREATE USER team1_llm_budget_user WITH PASSWORD '...'
    Scripts->>PG: GRANT USAGE ON SCHEMA team1 TO team1_llm_budget_user
    Scripts->>PG: GRANT CREATE ON SCHEMA team1 TO team1_llm_budget_user
    Scripts->>PG: ALTER USER team1_llm_budget_user SET search_path = team1
    Scripts->>K8s: Create Secret sessions-db-secret (team1_sessions_user creds)
    Scripts->>K8s: Create Secret llm-budget-db-secret (team1_llm_budget_user creds)
    Note over Scripts: kagenti-backend and llm-budget-proxy<br/>run their own table migrations on startup
```

### Agent Deploy (wizard)

```mermaid
sequenceDiagram
    participant User as User (Wizard UI)
    participant BE as kagenti-backend
    participant PG as PostgreSQL
    participant K8s as Kubernetes

    User->>BE: POST /sandbox/team1/create {name: "sandbox-legion", ...}
    BE->>PG: CREATE USER team1_agent_legion_user WITH PASSWORD '...'
    BE->>PG: CREATE SCHEMA team1_agent_legion AUTHORIZATION team1_agent_legion_user
    BE->>PG: ALTER USER team1_agent_legion_user SET search_path = team1_agent_legion
    BE->>PG: REVOKE ALL ON SCHEMA team1 FROM team1_agent_legion_user
    BE->>K8s: Create Secret agent-legion-db-secret<br/>(team1_agent_legion_user creds)
    BE->>K8s: Create Deployment sandbox-legion<br/>(mounts agent-legion-db-secret as CHECKPOINT_DB_URL)
    BE->>K8s: Create Service, Route, etc.
    Note over K8s: Agent pod starts, connects to DB<br/>LangGraph creates checkpoint tables<br/>in agent_legion schema automatically
```

### Agent Delete (cleanup)

```mermaid
sequenceDiagram
    participant User as User (UI)
    participant BE as kagenti-backend
    participant PG as PostgreSQL
    participant K8s as Kubernetes

    User->>BE: DELETE /sandbox/team1/sandbox-legion
    BE->>K8s: Delete Deployment sandbox-legion
    BE->>K8s: Delete Service, Route, PVC, Secrets
    BE->>PG: DROP SCHEMA agent_legion CASCADE
    BE->>PG: DROP USER agent_legion_user
    BE->>PG: DELETE FROM team1.tasks<br/>WHERE metadata->>'agent_name' = 'sandbox-legion'
    Note over BE: All agent state is fully cleaned up:<br/>checkpoints, sessions, K8s resources
```

## Connection Strings

### Agent pod (checkpoints)

```
# Mounted from agent-legion-db-secret
CHECKPOINT_DB_URL=postgresql://agent_legion_user:pass@postgres-sessions.team1.svc:5432/kagenti
# search_path = agent_legion (set on user, transparent to app)
```

LangGraph's `AsyncPostgresSaver` connects, runs `CREATE TABLE IF NOT EXISTS checkpoints`
— tables land in `agent_legion` schema automatically.

### kagenti-backend (sessions)

```
# Mounted from sessions-db-secret
DATABASE_URL=postgresql://sessions_user:pass@postgres-sessions.team1.svc:5432/kagenti
# search_path = team1
```

Backend creates/queries `tasks` table — lands in `team1` schema.

### llm-budget-proxy (llm tracking)

```
# Mounted from llm-budget-db-secret
DATABASE_URL=postgresql://llm_budget_user:pass@postgres-sessions.team1.svc:5432/kagenti
# search_path = team1
```

Proxy creates/queries `llm_calls`, `budget_limits` — lands in `team1` schema.

## Security Model

```mermaid
graph LR
    subgraph "PostgreSQL: kagenti database"
        T1["team1 schema<br/>(tasks, llm_calls)"]
        AL["agent_legion schema<br/>(checkpoints)"]
        AH["agent_hardened schema<br/>(checkpoints)"]
    end

    SU[team1_sessions_user] -->|"OWNER, full access"| T1
    LBU[team1_llm_budget_user] -->|"USAGE + CREATE"| T1
    ALU[team1_agent_legion_user] -->|"OWNER, full access"| AL
    ALU -.->|"NO ACCESS"| T1
    ALU -.->|"NO ACCESS"| AH
    AHU[team1_agent_hardened_user] -->|"OWNER, full access"| AH
    AHU -.->|"NO ACCESS"| T1
    AHU -.->|"NO ACCESS"| AL
```

- Agent users **cannot** access the team schema (sessions, llm_calls)
- Agent users **cannot** access other agent schemas
- Only `sessions_user` and `llm_budget_user` access the team schema
- Agent user can only see its own checkpoint tables

## Identifier Generation

PostgreSQL limits identifiers to 63 characters. With long namespace + agent
names this can be exceeded. Use a deterministic format:

```
{team:20}_{agent:20}_{hash:16}_{suffix}
```

- First 20 chars of team name (truncated, sanitized)
- First 20 chars of agent name (truncated, sanitized)
- 16 char SHA-256 hash of the full `{namespace}/{agent_name}` (guarantees uniqueness)
- Suffix: `u` for user, `s` for schema

Examples:
```
team1_sandbox_legion_a3f8c1e9b2d4f7a0_u     = 45 chars (user)
team1_sandbox_legion_a3f8c1e9b2d4f7a0_s     = 45 chars (schema)
production_work_my_very_long_age_8b2c4d6e1f3a5b70_u = 52 chars (truncated + hash)
```

Always ≤ 63 chars. Always unique (hash covers full names). Human-readable
prefix for debugging.

```python
import hashlib

def db_identifier(namespace: str, agent_name: str, suffix: str = "u") -> str:
    """Build a PostgreSQL identifier (≤63 chars) for a namespace/agent pair.

    Format: {team:20}_{agent:20}_{hash:16}_{suffix}
    """
    ns = namespace.replace('-', '_')[:20]
    agent = agent_name.replace('-', '_')[:20]
    full = f"{namespace}/{agent_name}"
    h = hashlib.sha256(full.encode()).hexdigest()[:16]
    return f"{ns}_{agent}_{h}_{suffix}"
```

## Backend Changes for Agent Lifecycle

### sandbox_deploy.py — create agent schema on deploy

```python
async def _create_agent_db_schema(namespace: str, agent_name: str) -> dict:
    """Create a PostgreSQL schema + user for the agent's checkpoints.

    Returns dict with connection details for the agent's K8s secret.
    """
    schema_name = db_identifier(namespace, agent_name, "s")
    db_user = db_identifier(namespace, agent_name, "u")
    db_password = secrets.token_urlsafe(24)

    pool = await get_admin_pool(namespace)  # connects as postgres superuser
    async with pool.acquire() as conn:
        # Create user + schema
        await conn.execute(f"CREATE USER {db_user} WITH PASSWORD '{db_password}'")
        await conn.execute(f"CREATE SCHEMA {schema_name} AUTHORIZATION {db_user}")
        await conn.execute(f"ALTER USER {db_user} SET search_path = {schema_name}")
        # Deny access to other schemas
        await conn.execute(f"REVOKE ALL ON SCHEMA team1 FROM {db_user}")
        await conn.execute(f"REVOKE ALL ON SCHEMA public FROM {db_user}")

    return {
        "host": f"postgres-sessions.{namespace}.svc",
        "port": "5432",
        "database": "kagenti",
        "username": db_user,
        "password": db_password,
        "schema": schema_name,
    }
```

### sandbox_deploy.py — cleanup on agent delete

```python
async def _delete_agent_db_schema(namespace: str, agent_name: str):
    """Drop the agent's PostgreSQL schema and user. Removes all checkpoints."""
    schema_name = db_identifier(namespace, agent_name, "s")
    db_user = db_identifier(namespace, agent_name, "u")

    pool = await get_admin_pool(namespace)
    async with pool.acquire() as conn:
        await conn.execute(f"DROP SCHEMA IF EXISTS {schema_name} CASCADE")
        await conn.execute(f"DROP USER IF EXISTS {db_user}")

    # Also clean up sessions for this agent
    session_pool = await get_session_pool(namespace)
    async with session_pool.acquire() as conn:
        await conn.execute(
            "DELETE FROM tasks WHERE metadata::json->>'agent_name' = $1",
            agent_name,
        )
```

## Admin Pool

The backend needs a superuser connection to create schemas/users.
This is separate from the `sessions_user` connection used for normal operations.

```python
# Admin connection for DDL operations (schema/user management)
ADMIN_DB_URL = os.environ.get(
    "ADMIN_DATABASE_URL",
    "postgresql://postgres:password@postgres-sessions.{namespace}.svc:5432/kagenti"
)
```

The admin password comes from a K8s secret created by the deploy scripts.

## Migration from Current Setup

1. Deploy scripts create `kagenti` database with `team1` schema
2. Move existing `sessions` DB tables into `team1` schema
3. For each existing agent, create `agent_*` schema and move checkpoints
4. Or simply: wipe all DBs, redeploy fresh (acceptable for dev clusters)

## Phased Rollout

### Phase 1: Schema isolation (this PR)
- Deploy scripts create kagenti DB + team schema
- Wizard creates agent schema + user on agent deploy
- Wizard drops schema + user on agent delete
- Agent connects with per-agent credentials
- Backend connects with shared team credentials

### Phase 2: LLM budget proxy
- llm-budget-proxy uses team schema for llm_calls/budget_limits
- Per-session and per-agent budget enforcement

### Phase 3: UI management
- Show per-agent DB usage in admin UI
- Schema cleanup dashboard
- Cross-namespace analytics (admin only)
