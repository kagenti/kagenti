# A2A Protocol Integration

The Agentic Runtime uses the [A2A (Agent-to-Agent) protocol](https://google.github.io/A2A/)
as its composability boundary. This document covers how agents communicate,
the two access models (proxied vs direct), and our A2A extensions.

> **A2A SDK:** `a2a-sdk >= 0.2.5` (server-side). Spec: v1.0.0 (2026-03-12).
> We use the SDK on agents only; the backend uses raw JSON-RPC via httpx.
> See [detailed design](../plans/2026-03-17-a2a-integration-design.md) for
> SDK upgrade analysis and extension design.

---

## Communication Models

Agents are A2A-compliant HTTP services. There are two ways to reach them:

### Model 1: Proxied via Backend (Default)

```mermaid
sequenceDiagram
    participant User
    participant UI as Kagenti UI
    participant Backend as FastAPI Backend
    participant AB as AuthBridge Sidecar
    participant Agent as Agent Container

    User->>UI: Send message
    UI->>Backend: POST /api/v1/sandbox/{ns}/chat/stream<br/>Authorization: Bearer {oidc_token}
    Backend->>Backend: Validate JWT, enforce RBAC
    Backend->>Backend: Resolve agent URL<br/>http://{name}.{ns}.svc.cluster.local:8000
    Backend->>AB: POST / (A2A JSON-RPC)<br/>method: message/stream<br/>Authorization: Bearer {token}
    AB->>AB: Validate inbound JWT
    AB->>Agent: Forward (validated)
    Agent-->>Backend: SSE stream (events)
    Backend-->>Backend: Persist events (background consumer)
    Backend-->>Backend: Upsert session metadata
    Backend-->>UI: SSE stream (forwarded events)
```

**What you get:**
- Keycloak JWT validation + RBAC enforcement (`ROLE_OPERATOR`)
- Session persistence (PostgreSQL `sessions` + `events` tables)
- Background event consumer (survives UI disconnect)
- Gap-fill reconnect (events table)
- Session history aggregation
- Sidecar agent fan-out
- Agent card caching and discovery
- Feature flag gating
- File browser (pods/exec)
- Budget tracking UI integration

### Model 2: Direct A2A Access

```mermaid
sequenceDiagram
    participant Client as External A2A Client
    participant AB as AuthBridge Sidecar
    participant Agent as Agent Container

    Client->>AB: POST / (A2A JSON-RPC)<br/>method: message/stream
    AB->>AB: Validate JWT (if configured)
    AB->>Agent: Forward
    Agent-->>Client: SSE stream (events)
```

An external system can call the agent directly using standard A2A protocol,
bypassing the Kagenti backend entirely. This requires network access to the
agent's Kubernetes Service.

**Direct access URL:**
```
http://{agent-name}.{namespace}.svc.cluster.local:8000
```

**What you get:**
- Pure A2A protocol compliance
- Framework-neutral agent invocation
- AuthBridge JWT validation (if sidecar injected)
- Istio Ambient mTLS encryption
- Agent's own task store (in-memory or PostgreSQL)
- Full SSE event stream with EVENT_CATALOG events
- AgentGraphCard at `/.well-known/agent-graph-card.json`
- Agent card at `/.well-known/agent-card.json`

**What you lose:**
- No session persistence in Kagenti's `sessions`/`events` tables
- No RBAC enforcement (backend `ROLE_OPERATOR` check)
- No background event consumer (events lost on disconnect)
- No gap-fill reconnect
- No sidecar agent observation
- No file browser
- No budget tracking UI
- No feature flag gating

### When to Use Each Model

| Use Case | Model | Why |
|----------|-------|-----|
| Kagenti UI user | Proxied | Full platform features, session history, budget UI |
| External A2A client (another agent) | Direct | Standard A2A interop, client manages own state |
| CI/CD pipeline calling agent | Direct | Lightweight, no UI needed, script-friendly |
| Multi-platform agent mesh | Direct | Each platform manages own RBAC and budget |
| Agent-to-agent delegation | Direct | `delegate` tool calls peer agents via A2A |
| Custom dashboard / external UI | Either | Proxied if you want Kagenti sessions, direct for custom state |

---

## A2A Protocol Details

### JSON-RPC Request Format

```json
{
  "jsonrpc": "2.0",
  "id": "request-uuid",
  "method": "message/stream",
  "params": {
    "message": {
      "role": "user",
      "parts": [{"kind": "text", "text": "Analyze this codebase"}],
      "messageId": "msg-uuid",
      "contextId": "session-uuid"
    }
  }
}
```

| Field | Purpose |
|-------|---------|
| `method` | `message/stream` for streaming, `message/send` for non-streaming |
| `contextId` | Groups multiple tasks into a session (A2A core spec, not extension) |
| `messageId` | Unique per message |
| `parts` | Content parts (text, file, data) |

### SSE Response Events

The agent streams A2A events plus our EVENT_CATALOG events:

```
data: {"result":{"id":"task-uuid","contextId":"session-uuid","status":{"state":"working"}}}

data: {"result":{"status":{"state":"working","message":{"parts":[{"kind":"text","text":"{\"type\":\"planner_output\",...}"}]}}}}

data: {"result":{"status":{"state":"completed"}}}

data: [DONE]
```

A2A task lifecycle states:

| State | Meaning |
|-------|---------|
| `submitted` | Task acknowledged |
| `working` | Being processed |
| `completed` | Finished successfully |
| `failed` | Finished with error |
| `input-required` | Needs user input (HITL) |

### Agent Discovery

Agents expose `/.well-known/agent-card.json` per the A2A spec:

```json
{
  "name": "sandbox-legion",
  "description": "LangGraph coding agent with persistent sessions",
  "version": "1.0.0",
  "url": "http://sandbox-legion.team1.svc.cluster.local:8000",
  "capabilities": {
    "streaming": true,
    "extensions": [
      {
        "uri": "urn:kagenti:agent-graph-card:v1",
        "description": "Processing graph topology and event schemas",
        "required": false,
        "params": {"endpoint": "/.well-known/agent-graph-card.json"}
      }
    ]
  },
  "skills": [
    {
      "id": "coding",
      "name": "Coding Agent",
      "description": "Plan-execute-reflect coding with shell, file, and web tools"
    }
  ]
}
```

The backend discovers agents by fetching this endpoint. It tries port 8080
first (AuthBridge sidecar), falls back to 8000 (direct).

---

## A2A Extensions

### Registered Extensions

| Extension | URI | Status | Purpose |
|-----------|-----|--------|---------|
| **AgentGraphCard** | `urn:kagenti:agent-graph-card:v1` | Shipped | Graph topology + event catalog |
| **Session metadata** | -- | Planned | Session persistence, budget, ownership |

### AgentGraphCard Extension

Our primary A2A extension. Agents declare it in their `AgentCard.capabilities.extensions[]`
and expose the endpoint at `/.well-known/agent-graph-card.json`.

```
URI: urn:kagenti:agent-graph-card:v1
Endpoint: /.well-known/agent-graph-card.json
Required: false
```

The graph card contains:
- **event_catalog** -- every event type the agent can emit, with categories and fields
- **topology** -- the agent's processing graph (nodes, edges, entry_node)
- **common_event_fields** -- fields present on every streamed event

This enables framework-neutral UI rendering. See [Concepts](./concepts.md#agentgraphcard).

### Session Context Extension (Planned)

A2A v1.0 has `context_id` as a core field (not an extension) for grouping
tasks into sessions. However, session **metadata** (owner, budget limits,
model override, title) is Kagenti-specific.

Planned extension to expose session metadata via A2A:

```
URI: urn:kagenti:session-metadata:v1 (planned)
Purpose: Session persistence, ownership, budget limits
Storage: Message.metadata["urn:kagenti:session-metadata:v1/session"]
```

This would allow direct A2A clients to read/write session metadata without
going through the Kagenti backend.

---

## SDK Version Analysis

| Component | Version | Notes |
|-----------|---------|-------|
| A2A Spec | v1.0.0 (2026-03-12) | Major rewrite from v0.3 |
| a2a-sdk (PyPI) | 0.3.25 stable / 1.0.0a0 alpha | We use `>=0.2.5` |
| Our pinned | `>=0.2.0` (backend), `>=0.2.5` (tests) | Pre-v1.0 API |

**SDK v0.2 vs v1.0 breaking changes:**
- Enum values: `"completed"` -> `"TASK_STATE_COMPLETED"`
- Part types: separate `TextPart`/`FilePart` -> unified `Part` with `oneof`
- Agent card: restructured `capabilities` and `supportedInterfaces`
- Proto package: `a2a.v1` -> `lf.a2a.v1`

**Upgrade path:** The `1.0.0a0` alpha SDK is available. Upgrade requires
updating all A2A type imports and enum references. See
[detailed design](../plans/2026-03-17-a2a-integration-design.md) for
the migration plan.

---

## Port Discovery

| Port | Used By | When |
|------|---------|------|
| 8080 | AuthBridge sidecar (Envoy) | Agents with `kagenti.io/inject: enabled` |
| 8000 | Direct agent container | Sandbox agents, platform base agents |

The backend tries 8080 first, falls back to 8000 on connection error.
Direct A2A clients should use the agent's Kubernetes Service, which maps
to the correct port.
