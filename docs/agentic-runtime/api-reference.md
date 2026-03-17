# API Reference

All routes are gated behind feature flags. When `KAGENTI_FEATURE_FLAG_SANDBOX`
is `false`, these routes do not exist.

---

## Sandbox Sessions

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/v1/sandbox/{namespace}/sessions` | List sessions with pagination and search |
| GET | `/api/v1/sandbox/{namespace}/sessions/{context_id}` | Get session with full history and artifacts |
| GET | `/api/v1/sandbox/{namespace}/sessions/{context_id}/chain` | Get session lineage chain (parent/child) |
| GET | `/api/v1/sandbox/{namespace}/sessions/{context_id}/history` | Paginated session history |
| DELETE | `/api/v1/sandbox/{namespace}/sessions/{context_id}` | Delete session (owner or admin only) |
| POST | `/api/v1/sandbox/{namespace}/sessions/{context_id}/kill` | Cancel running session |
| POST | `/api/v1/sandbox/{namespace}/cleanup` | Mark stale tasks as failed (TTL-based) |

## Sandbox Chat & Streaming

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/v1/sandbox/{namespace}/chat` | Send message to agent via A2A JSON-RPC |
| POST | `/api/v1/sandbox/{namespace}/chat/stream` | Stream agent response via SSE |
| GET | `/api/v1/sandbox/{namespace}/sessions/{session_id}/subscribe` | Subscribe to running session event stream |

## Sandbox Events

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/v1/sandbox/{namespace}/events` | Get paginated events for a session/task |
| GET | `/api/v1/sandbox/{namespace}/tasks/paginated` | Get paginated task summaries |

## Sandbox Agents

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/v1/sandbox/{namespace}/agents` | List agent deployments with session counts |
| GET | `/api/v1/sandbox/{namespace}/agent-card/{agent_name}` | Proxy A2A agent card from agent pod |
| GET | `/api/v1/sandbox/{namespace}/agents/{agent_name}/pod-status` | Get pod status, events, resources |
| GET | `/api/v1/sandbox/{namespace}/pods/{agent_name}/metrics` | Get CPU/memory metrics |
| GET | `/api/v1/sandbox/{namespace}/pods/{agent_name}/events` | Get Kubernetes events for agent pods |

## Sandbox Deployment

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/v1/sandbox/defaults` | Get backend default sandbox creation values |
| POST | `/api/v1/sandbox/{namespace}/create` | Deploy new sandbox agent |
| DELETE | `/api/v1/sandbox/{namespace}/{name}` | Delete sandbox agent and resources |
| GET | `/api/v1/sandbox/{namespace}/{name}/config` | Get wizard config from deployment annotations |
| PUT | `/api/v1/sandbox/{namespace}/{name}` | Update sandbox configuration |

## File Browser

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/v1/sandbox/{namespace}/files/{agent_name}` | Browse files in agent pod |
| GET | `/api/v1/sandbox/{namespace}/files/{agent_name}/list` | List directory contents |
| GET | `/api/v1/sandbox/{namespace}/files/{agent_name}/content` | Read file content |
| GET | `/api/v1/sandbox/{namespace}/files/{agent_name}/{context_id}` | Browse session workspace |
| GET | `/api/v1/sandbox/{namespace}/stats/{agent_name}` | Get storage statistics |

## Sidecar Management

Gated behind `KAGENTI_FEATURE_FLAG_SANDBOX`.

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/v1/sidecar/{namespace}` | Deploy sidecar to namespace |
| GET | `/api/v1/sidecar/{namespace}/{pod_name}/logs` | Get sidecar logs |
| POST | `/api/v1/sidecar/{namespace}/{pod_name}/health` | Check sidecar health |
| POST | `/api/v1/sidecar/{namespace}/{pod_name}/restart` | Restart sidecar pod |
| PUT | `/api/v1/sidecar/{namespace}/{pod_name}/config` | Update sidecar config |
| GET | `/api/v1/sidecar/{namespace}/{pod_name}/ready` | Check sidecar readiness |

## Token Usage & LLM Keys

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/v1/token-usage/{namespace}` | Get token usage stats |
| GET | `/api/v1/token-usage/{namespace}/{agent_name}` | Get usage for specific agent |
| GET | `/api/v1/llm/{namespace}` | Get namespace LLM keys |
| POST | `/api/v1/llm/teams/{namespace}` | Create LLM key team |
| POST | `/api/v1/llm/keys/{namespace}` | Create new LLM key |
| GET | `/api/v1/llm/{namespace}/{key_name}` | Get key details |
| DELETE | `/api/v1/llm/{namespace}/{key_name}` | Delete LLM key |
| GET | `/api/v1/llm/{namespace}/agent-models` | Get per-agent model overrides |
| GET | `/api/v1/models` | List available LLM models |

## Triggers

Gated behind `KAGENTI_FEATURE_FLAG_TRIGGERS`.

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/v1/sandbox/trigger` | Create sandbox from trigger event |

## Configuration

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/v1/config/features` | Get enabled feature flags |

---

## SSE Event Format

When streaming via `/chat/stream` or `/subscribe`, events are sent as
Server-Sent Events with JSON payloads:

```
event: message
data: {"type": "planner_output", "loop_id": "abc123", "langgraph_node": "planner", ...}

event: message
data: {"type": "tool_call", "loop_id": "abc123", "langgraph_node": "executor", ...}

event: message
data: {"type": "reporter_output", "loop_id": "abc123", "langgraph_node": "reporter", ...}
```

Each event includes the common fields defined in
[Concepts](./concepts.md#event-categories).

## Error Responses

Standard error format:

```json
{
  "detail": "Session not found",
  "status_code": 404
}
```

Budget exceeded (from LLM Budget Proxy):

```json
{
  "error": {
    "type": "budget_exceeded",
    "tokens_used": 1050000,
    "tokens_budget": 1000000
  }
}
```
