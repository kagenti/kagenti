# Session Theta (theta) — Squid Proxy Domain Counters + Per-Schema DB Isolation

> **Date:** 2026-03-15
> **Cluster:** sandbox42
> **Worktrees:** `.worktrees/sandbox-agent` (kagenti), `.worktrees/agent-examples` (agent code)
> **Branch:** `feat/sandbox-agent`
> **Depends On:** Session beta (AgentGraphCard, OTel, test fixes)

## Goal

Extend the squid proxy sidecar to count network requests per domain with
approve/deny status, protocol, and HTTP method. Persist counters to the
team namespace postgres instance with per-agent schema isolation.

## Background

### Squid Proxy Sidecar (Current)

The sandbox agent can be deployed with a squid proxy sidecar that enforces
network egress policies (allow/deny domain lists). Currently configured via
the wizard's `proxy: bool` and `proxy_domains` fields in
`sandbox_deploy.py`.

Key files:
- `sandbox_deploy.py` — deploys sidecar container with squid config
- Squid config: domain allowlist/denylist via `proxy_allowlist` field
- Agent sets `HTTP_PROXY` / `HTTPS_PROXY` env vars pointing to sidecar

### Team Namespace Postgres (Current)

Each team namespace has a `postgres-sessions` StatefulSet that stores:
- A2A task state (`tasks` table)
- LangGraph checkpoints (`checkpoints`, `checkpoint_blobs`, `checkpoint_writes`)
- Currently: single `kagenti` user, single schema, shared by all agents

### What's Missing

1. **No visibility** into what domains agents actually access
2. **No per-agent DB isolation** — all agents in a namespace share one schema
3. **No counters/metrics** for network activity

## Design

### 1. Squid Access Log Parser + In-Memory Counter

The squid proxy already logs every request to stdout (`access.log` format).
Instead of a separate counter process, we add a **lightweight sidecar script**
(Python or Go) that:

1. Tails squid's access log (pipe or file)
2. Parses each line: `timestamp duration client action/code size method url`
3. Extracts: domain, status (TCP_DENIED vs TCP_MISS/HIT), method, protocol
4. Maintains in-memory counters:
   ```python
   counters: dict[str, DomainCounter] = {}

   @dataclass
   class DomainCounter:
       domain: str
       approved: int = 0
       denied: int = 0
       methods: dict[str, int] = field(default_factory=dict)  # GET: 5, POST: 2
       protocols: dict[str, int] = field(default_factory=dict)  # https: 7
       first_seen: datetime
       last_seen: datetime
       bytes_total: int = 0
   ```
5. Periodically flushes to postgres (every 30s or when batch size >= 50)

### 2. Per-Agent Schema in Team Postgres

Each agent gets its own postgres schema, with its own DB user that can only
write to its schema. This prevents agents from reading/modifying each other's
data.

```sql
-- Created by team namespace provisioning (agent-namespaces.yaml or deploy script)
CREATE SCHEMA IF NOT EXISTS "sandbox_legion";
CREATE SCHEMA IF NOT EXISTS "rca_agent";
CREATE SCHEMA IF NOT EXISTS "llm_budget_proxy";

-- Per-agent users (can only touch their own schema)
CREATE USER sandbox_legion_rw WITH PASSWORD '...';
GRANT USAGE ON SCHEMA sandbox_legion TO sandbox_legion_rw;
GRANT ALL ON ALL TABLES IN SCHEMA sandbox_legion TO sandbox_legion_rw;
ALTER DEFAULT PRIVILEGES IN SCHEMA sandbox_legion GRANT ALL ON TABLES TO sandbox_legion_rw;

-- Agent's search_path only includes its own schema
ALTER USER sandbox_legion_rw SET search_path TO sandbox_legion;
```

The provisioning script creates schemas + users when deploying agents.
Each agent's `DATABASE_URL` includes the schema-specific user.

### 3. Network Activity Table

```sql
-- In each agent's schema (e.g., sandbox_legion.network_activity)
CREATE TABLE network_activity (
    id BIGSERIAL PRIMARY KEY,
    context_id TEXT,          -- session that made the request
    domain TEXT NOT NULL,
    approved BOOLEAN NOT NULL,
    method TEXT,              -- GET, POST, CONNECT, etc.
    protocol TEXT,            -- http, https, ftp
    request_count INT DEFAULT 1,
    bytes_total BIGINT DEFAULT 0,
    first_seen TIMESTAMPTZ NOT NULL,
    last_seen TIMESTAMPTZ NOT NULL,
    -- Batch upsert key
    UNIQUE (context_id, domain, method, protocol, approved)
);

CREATE INDEX idx_network_activity_domain ON network_activity(domain);
CREATE INDEX idx_network_activity_context ON network_activity(context_id);
```

The counter script does batch upserts:
```sql
INSERT INTO network_activity (context_id, domain, approved, method, protocol,
                              request_count, bytes_total, first_seen, last_seen)
VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
ON CONFLICT (context_id, domain, method, protocol, approved)
DO UPDATE SET
    request_count = network_activity.request_count + EXCLUDED.request_count,
    bytes_total = network_activity.bytes_total + EXCLUDED.bytes_total,
    last_seen = GREATEST(network_activity.last_seen, EXCLUDED.last_seen);
```

### 4. Architecture

```
Pod: sandbox-agent
  ├── Container: sandbox-agent (main)
  │   └── Sets HTTP_PROXY=http://localhost:3128
  │
  ├── Container: squid-proxy (sidecar)
  │   ├── Squid on port 3128
  │   ├── Config: allow/deny domains from wizard
  │   └── Access log → stdout (or shared volume)
  │
  └── Container: proxy-counter (new sidecar)
      ├── Tails squid access log
      ├── In-memory DomainCounter aggregation
      ├── Periodic flush to postgres (30s / batch 50)
      └── DATABASE_URL uses schema-specific user
```

### 5. Backend API

New endpoint to query network activity:

```
GET /api/v1/sandbox/{namespace}/sessions/{context_id}/network-activity
  → { domains: [{ domain, approved, denied, methods, protocols, bytes, first_seen, last_seen }] }

GET /api/v1/sandbox/{namespace}/agents/{agent_name}/network-activity
  → { domains: [...] }  (aggregated across all sessions for this agent)
```

### 6. UI Integration

New tab or panel in the sandbox session view showing:
- Domain activity table: domain, approved/denied count, methods, bytes
- Color-coded: green for approved, red for denied
- Sortable by count, domain, last_seen
- Filter by approved/denied

## Implementation Plan

### Phase 1: Per-Agent Schema Isolation
- [ ] Update team namespace provisioning to create schemas per agent
- [ ] Create DB users with schema-specific privileges
- [ ] Update agent deployment to use schema-specific DATABASE_URL
- [ ] Migrate existing tasks/checkpoints tables into agent schemas

### Phase 2: Proxy Counter Sidecar
- [ ] Create proxy-counter container image (Python, ~200 lines)
- [ ] Parse squid access log format
- [ ] In-memory counter with periodic batch flush
- [ ] Add as sidecar in sandbox_deploy.py when `proxy: true`
- [ ] Create network_activity table via schema migration

### Phase 3: Backend + UI
- [ ] Backend endpoint for network activity queries
- [ ] UI panel in session view
- [ ] Aggregated view per agent

## Key Decisions to Make

1. **Counter sidecar vs. squid log plugin?**
   - Sidecar: separate container, clean separation, independent scaling
   - Squid helper: runs in squid container, no extra container overhead
   - Recommendation: sidecar (cleaner, can be disabled independently)

2. **Context ID extraction from squid logs?**
   - Squid can log custom headers (X-Context-Id)
   - Agent would need to set this header on all proxied requests
   - Alternative: parse from referer or just use pod-level context

3. **Schema migration tool?**
   - Use raw SQL in provisioning scripts
   - Or use alembic/liquibase for versioned migrations
   - Recommendation: raw SQL for now (few tables)

4. **How to pass schema-specific DB creds to agents?**
   - K8s Secret per agent (created by provisioning)
   - Or single secret with per-agent keys
   - Recommendation: Secret per agent (matches existing pattern)

## Files to Create/Modify

| File | Change |
|------|--------|
| `proxy_counter.py` | **New**: squid log parser + DB flusher |
| `Dockerfile.proxy-counter` | **New**: lightweight Python image |
| `sandbox_deploy.py` | Add proxy-counter sidecar when proxy=true |
| `agent-namespaces.yaml` | Create per-agent schemas + users |
| `sandbox.py` | New endpoint: /network-activity |
| `NetworkActivityPanel.tsx` | **New**: UI component |

## Related Docs

- `docs/plans/2026-03-15-agent-graph-card-design.md` — AgentGraphCard design
- `docs/plans/2026-03-12-llm-budget-proxy-design.md` — Budget proxy (similar pattern)
- `docs/plans/2026-03-15-provisioning-architecture.md` — Team provisioning
