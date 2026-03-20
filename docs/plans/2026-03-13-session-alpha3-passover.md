# Session Alpha-3 Passover — Streaming Architecture: WebSocket Hub + gRPC A2A

> **Date:** 2026-03-13
> **Cluster:** sbox42 (KUBECONFIG=/tmp/kagenti/sbox42-kubeconfig)
> **Worktrees:** `.worktrees/sandbox-agent` (kagenti), `.worktrees/agent-examples` (agent code)
> **Branch:** `feat/sandbox-agent` (both repos)
> **Previous:** session-alpha2-passover.md (executor isolation + step scoping)
> **Depends on:** Alpha-2 P1 (SystemMessage step boundary) should be done first

## Goal

Replace the fragile SSE-based event pipeline with a durable, multi-user
streaming architecture. Three phases, each independently deployable.

---

## Phase 1: DB-Backed Event Store

### Problem

Events are accumulated in memory during the SSE stream. If the stream
disconnects (browser navigates, proxy timeout, pod restart), events after
the disconnect are permanently lost. Recovery via `tasks/resubscribe` only
gets future events — already-emitted events are gone.

Evidence from this session: sessions consistently lost 80-95% of events
(9 of 188, 13 of ~200) until we fixed the Playwright test to wait.

### Architecture

```
                    BEFORE                              AFTER
                    ──────                              ─────

Browser ◄── SSE ── Backend ◄── SSE ── Agent    Browser ◄── SSE ── Backend ◄── SSE ── Agent
                      │                                       │         │
                 finally block                           per-event     │
                      │                                   write       │
                   DB write                                │         │
                  (on disconnect)                    ┌─────▼─────┐   │
                                                     │  events    │   │
                                                     │  table     │◄──┘
                                                     │  (append)  │
                                                     └───────────┘
                                                          │
                                                     page reload
                                                     reads from DB
```

### New `loop_events` Table

Instead of storing events in `tasks.metadata::jsonb->'loop_events'` (which
requires rewriting the entire JSON blob on each update), create a dedicated
append-only events table:

```sql
CREATE TABLE loop_events (
    id BIGSERIAL PRIMARY KEY,
    context_id TEXT NOT NULL,         -- session ID
    loop_id TEXT NOT NULL,            -- reasoning loop ID
    event_index INT NOT NULL,         -- chronological counter
    step INT,                         -- plan step (1-based)
    event_type TEXT NOT NULL,         -- router, planner_output, tool_call, etc.
    event_data JSONB NOT NULL,        -- full event payload
    created_at TIMESTAMPTZ DEFAULT NOW(),

    -- Fast lookup by session
    CONSTRAINT idx_loop_events_ctx UNIQUE (context_id, event_index)
);

CREATE INDEX idx_loop_events_ctx_type ON loop_events(context_id, event_type);
```

### Backend Changes

**`sandbox.py` — SSE streaming handler:**

```python
# Current: accumulate in list, write on disconnect
loop_events.append(parsed)
# ... finally: write all to tasks.metadata

# New: write each event immediately
loop_events.append(parsed)
await _insert_loop_event(pool, session_id, parsed)
# ... finally: no-op (events already in DB)
```

```python
async def _insert_loop_event(pool, session_id: str, event: dict):
    """Append a single event to the loop_events table."""
    async with pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO loop_events (context_id, loop_id, event_index, step, event_type, event_data)
            VALUES ($1, $2, $3, $4, $5, $6::jsonb)
            ON CONFLICT (context_id, event_index) DO NOTHING
        """, session_id, event.get("loop_id", ""),
             event.get("event_index", 0), event.get("step"),
             event.get("type", "unknown"), json.dumps(event))
```

**`sandbox.py` — History endpoint:**

```python
# Current: read from tasks.metadata->'loop_events'
# New: read from loop_events table

@router.get("/{namespace}/sessions/{session_id}/history")
async def get_session_history(session_id: str, ...):
    pool = await get_session_pool(namespace)
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT event_data FROM loop_events
            WHERE context_id = $1
            ORDER BY event_index
        """, session_id)
    events = [json.loads(r["event_data"]) for r in rows]
    # ... return events
```

**Subscribe endpoint — replay + live:**

```python
@router.get("/{namespace}/sessions/{session_id}/subscribe")
async def subscribe(session_id: str, ...):
    # 1. Send all existing events from DB (replay)
    rows = await conn.fetch("SELECT event_data FROM loop_events WHERE context_id = $1 ORDER BY event_index", session_id)
    for r in rows:
        yield f"data: {r['event_data']}\n\n"

    # 2. If session still running, connect to live stream
    if session_state == "working":
        async for event in _proxy_agent_sse(agent_url, session_id):
            await _insert_loop_event(pool, session_id, event)
            yield f"data: {json.dumps(event)}\n\n"
```

### Migration

1. Create `loop_events` table via Alembic migration
2. Keep backward compat: still write to `tasks.metadata->'loop_events'` for old UI
3. New history endpoint reads from `loop_events` table first, falls back to metadata
4. Remove metadata writes after migration period

### Testing

- Kill SSE mid-stream → page reload shows ALL events from DB
- Multiple page reloads → same event set (idempotent)
- Concurrent sessions → no event cross-contamination

---

## Phase 2: WebSocket Hub for Multi-User

### Problem

Only one browser can see a session's live events. If admin sends a message
and a viewer opens the same session, the viewer sees only historical events,
not the live stream. There's no way for multiple users to watch the same
agent session in real-time.

### Architecture

```
┌──────────┐                    ┌──────────────────────┐
│ Browser 1│◄─── WebSocket ────►│                      │
│  (admin) │                    │    Backend           │
│          │                    │    WebSocket Hub     │
│ Browser 2│◄─── WebSocket ────►│                      │◄── SSE ── Agent
│ (viewer) │                    │  ┌────────────────┐  │
│          │                    │  │  Room: ctx_123  │  │
│ Browser 3│◄─── WebSocket ────►│  │  - conn_1 (rw) │  │
│ (viewer) │                    │  │  - conn_2 (ro) │  │
└──────────┘                    │  │  - conn_3 (ro) │  │
                                │  └────────────────┘  │
                                │           │          │
                                │     ┌─────▼──────┐   │
                                │     │ loop_events │   │
                                │     │   table     │   │
                                │     └────────────┘   │
                                └──────────────────────┘
```

### WebSocket Protocol

```typescript
// Client → Server
{ type: "join", session_id: "ctx_123" }           // join a session room
{ type: "leave", session_id: "ctx_123" }           // leave a room
{ type: "message", session_id: "ctx_123", text: "..." }  // send message (admin only)
{ type: "hitl_approve", session_id: "ctx_123", ... }     // HITL approval

// Server → Client
{ type: "event", session_id: "ctx_123", event: {...} }   // live event
{ type: "history", session_id: "ctx_123", events: [...] } // replay on join
{ type: "joined", session_id: "ctx_123", viewers: 3 }    // room status
{ type: "error", message: "..." }                         // error
```

### Backend Implementation

```python
# New file: app/services/ws_hub.py

class SessionRoom:
    """A WebSocket room for a single agent session."""
    def __init__(self, session_id: str):
        self.session_id = session_id
        self.connections: dict[str, WebSocket] = {}  # conn_id → ws
        self.owner: str | None = None  # admin who started the session

    async def broadcast(self, event: dict):
        """Send event to all connected clients."""
        msg = json.dumps({"type": "event", "session_id": self.session_id, "event": event})
        for ws in self.connections.values():
            await ws.send_text(msg)

class WebSocketHub:
    """Manages session rooms and WebSocket connections."""
    def __init__(self):
        self.rooms: dict[str, SessionRoom] = {}

    async def join(self, session_id: str, ws: WebSocket, user: str):
        if session_id not in self.rooms:
            self.rooms[session_id] = SessionRoom(session_id)
        room = self.rooms[session_id]
        conn_id = str(uuid4())
        room.connections[conn_id] = ws
        # Send history replay
        events = await _load_events_from_db(session_id)
        await ws.send_text(json.dumps({
            "type": "history",
            "session_id": session_id,
            "events": events,
        }))
        return conn_id

    async def on_agent_event(self, session_id: str, event: dict):
        """Called when backend receives an event from agent SSE."""
        # 1. Persist to DB
        await _insert_loop_event(pool, session_id, event)
        # 2. Broadcast to all connected clients
        if session_id in self.rooms:
            await self.rooms[session_id].broadcast(event)
```

### Frontend Implementation

```typescript
// New: useSessionWebSocket hook
function useSessionWebSocket(sessionId: string) {
  const ws = useRef<WebSocket | null>(null);
  const [events, setEvents] = useState<LoopEvent[]>([]);

  useEffect(() => {
    const url = `wss://${window.location.host}/api/v1/sandbox/ws`;
    ws.current = new WebSocket(url);

    ws.current.onopen = () => {
      ws.current?.send(JSON.stringify({ type: "join", session_id: sessionId }));
    };

    ws.current.onmessage = (msg) => {
      const data = JSON.parse(msg.data);
      if (data.type === "history") {
        setEvents(data.events);
      } else if (data.type === "event") {
        setEvents(prev => [...prev, data.event]);
      }
    };

    // Auto-reconnect
    ws.current.onclose = () => {
      setTimeout(() => { /* reconnect */ }, 1000);
    };

    return () => ws.current?.close();
  }, [sessionId]);

  return events;
}
```

### Nginx/Route Config

```
# OpenShift route needs WebSocket support
oc annotate route kagenti-ui \
  haproxy.router.openshift.io/timeout=3600s \
  --overwrite

# Nginx config for WS upgrade
location /api/v1/sandbox/ws {
    proxy_pass http://kagenti-backend:8000;
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
    proxy_read_timeout 3600s;
}
```

---

## Phase 3: gRPC A2A Between Backend and Agent

### Problem

SSE (Server-Sent Events) between backend and agent is:
- **Unidirectional** — agent→backend only, can't send commands back
- **Text-based** — JSON parsing on every event
- **No backpressure** — agent can flood backend with events
- **No health monitoring** — connection silently dies
- **Large payloads** — JSON events are 500-2000 bytes each

### Architecture

```
┌──────────┐            ┌──────────────┐            ┌──────────┐
│ Browser  │◄── WS ────►│   Backend    │◄── gRPC ──►│  Agent   │
│          │   JSON     │              │  protobuf  │          │
└──────────┘            └──────┬───────┘            └──────────┘
                               │
                         ┌─────▼──────┐
                         │ loop_events│
                         │   table    │
                         └────────────┘
```

### Protobuf Schema

```protobuf
syntax = "proto3";
package kagenti.agent.v1;

// Event types emitted by the agent during reasoning loop
message LoopEvent {
  string loop_id = 1;
  int32 event_index = 2;
  int32 step = 3;

  oneof event {
    RouterEvent router = 10;
    PlannerEvent planner = 11;
    StepSelectorEvent step_selector = 12;
    ExecutorEvent executor = 13;
    ToolCallEvent tool_call = 14;
    ToolResultEvent tool_result = 15;
    MicroReasoningEvent micro_reasoning = 16;
    ReflectorEvent reflector = 17;
    ReporterEvent reporter = 18;
    BudgetUpdateEvent budget_update = 19;
  }
}

message RouterEvent {
  string route = 1;  // "new", "resume", "replan"
  string plan_status = 2;
}

message PlannerEvent {
  repeated string steps = 1;
  int32 iteration = 2;
  string content = 3;
  int32 prompt_tokens = 4;
  int32 completion_tokens = 5;
}

message ToolCallEvent {
  string call_id = 1;
  repeated ToolInvocation tools = 2;
}

message ToolInvocation {
  string name = 1;
  string args_json = 2;  // JSON-encoded args (keeps flexibility)
}

message ToolResultEvent {
  string call_id = 1;
  string name = 2;
  string output = 3;
  string status = 4;  // "success" or "error"
}

message MicroReasoningEvent {
  int32 micro_step = 1;
  string after_call_id = 2;
  string reasoning = 3;
  string next_action = 4;
  ToolResultSummary previous_tool = 5;
  int32 prompt_tokens = 6;
  int32 completion_tokens = 7;
}

message ToolResultSummary {
  string name = 1;
  string output = 2;  // truncated to 500 chars
  string status = 3;
}

message ReflectorEvent {
  string decision = 1;    // continue, retry, replan, done, hitl
  string assessment = 2;
  int32 prompt_tokens = 3;
  int32 completion_tokens = 4;
}

message ReporterEvent {
  string content = 1;
  int32 prompt_tokens = 2;
  int32 completion_tokens = 3;
}

message BudgetUpdateEvent {
  int32 tokens_used = 1;
  int32 tokens_budget = 2;
  int32 iterations_used = 3;
  int32 iterations_budget = 4;
  float wall_clock_s = 5;
  float max_wall_clock_s = 6;
}

// Size comparison (typical tool_call event):
//   JSON:     ~500 bytes  {"type":"tool_call","loop_id":"abc","step":3,"call_id":"xyz",...}
//   Protobuf: ~150 bytes  (binary, no field names, varint encoding)
//   Savings:  ~70%

// gRPC service definition
service AgentService {
  // Bidirectional streaming — agent sends events, backend sends commands
  rpc ExecuteTask(stream AgentCommand) returns (stream LoopEvent);

  // Unary — get task status
  rpc GetTask(GetTaskRequest) returns (TaskStatus);
}

message AgentCommand {
  oneof command {
    StartTaskCommand start = 1;
    CancelTaskCommand cancel = 2;
    HitlApproveCommand hitl_approve = 3;
    AdjustBudgetCommand adjust_budget = 4;
  }
}

message StartTaskCommand {
  string context_id = 1;
  string message = 2;
  map<string, string> metadata = 3;
}
```

### Payload Size Comparison

| Event Type | JSON (bytes) | Protobuf (bytes) | Savings |
|-----------|-------------|------------------|---------|
| tool_call | ~500 | ~150 | 70% |
| tool_result | ~2,000 | ~700 | 65% |
| micro_reasoning | ~1,500 | ~500 | 67% |
| budget_update | ~300 | ~50 | 83% |
| **Per session (200 events)** | **~100 KB** | **~30 KB** | **70%** |

### gRPC vs SSE Feature Comparison

| Feature | SSE | gRPC |
|---------|-----|------|
| Direction | Server → Client | Bidirectional |
| Protocol | HTTP/1.1 text | HTTP/2 binary |
| Multiplexing | 1 stream per connection | N streams per connection |
| Backpressure | None | Built-in flow control |
| Health check | None (silent disconnect) | Keepalive pings |
| Reconnection | Manual | Built-in with backoff |
| Schema | Freeform JSON | Typed protobuf |
| Debugging | curl + readable | grpcurl + binary |
| Browser support | Native EventSource | grpc-web proxy needed |

### A2A Protocol Compatibility

The A2A spec uses JSON-RPC over HTTP/SSE. gRPC would be a **custom transport**
under the A2A interface:

```
External callers → HTTP/JSON-RPC (standard A2A)
Internal backend → gRPC/protobuf (fast transport)
```

The agent exposes both:
- Port 8000: HTTP A2A (for external callers, agent cards, health checks)
- Port 8001: gRPC (for backend-to-agent streaming)

### Implementation Steps

1. Define protobuf schema in `proto/agent.proto`
2. Generate Python server (agent) + client (backend) stubs
3. Add gRPC server to agent alongside HTTP server
4. Backend uses gRPC client instead of httpx SSE
5. Keep HTTP A2A for external compatibility

### Can We Send Protobuf Directly to UI?

**Yes, via grpc-web:**
- Browser speaks gRPC via Envoy grpc-web proxy
- Requires protoc → TypeScript codegen
- Trade-off: smaller payloads vs build complexity

**Recommendation:** Keep WS+JSON for browser, gRPC for backend↔agent.
The 70% size reduction matters for the backend↔agent path (100s of events
per session, multiple concurrent sessions). The browser↔backend path
has fewer events (just the current session) and JSON is easier to debug.

---

## Implementation Order

```
Session Alpha-2:  P0-P2 (workspace paths, step boundary, tool ID mapping)
                  ↓
Session Alpha-3:   Phase 1 (DB event store + loop_events table)
                  ↓
Session Gamma:    Phase 2 (WebSocket hub)
                  ↓
Session Delta:    Phase 3 (gRPC A2A)
```

### Phase 1 Estimate (DB Event Store)

| Task | Files | Effort |
|------|-------|--------|
| Create loop_events table migration | backend/migrations/ | 15 min |
| _insert_loop_event function | backend/app/routers/sandbox.py | 30 min |
| Replace metadata writes with table inserts | sandbox.py SSE handler | 1 hr |
| History endpoint reads from table | sandbox.py history handler | 30 min |
| Subscribe with replay + live | sandbox.py subscribe handler | 1 hr |
| Remove recovery polling (no longer needed) | sandbox.py _recover_* | 30 min |
| Tests | e2e/agent-rca-workflow.spec.ts | 30 min |

### Phase 2 Estimate (WebSocket Hub)

| Task | Files | Effort |
|------|-------|--------|
| WebSocketHub class | backend/app/services/ws_hub.py | 2 hr |
| WS endpoint + room management | backend/app/routers/sandbox.py | 1 hr |
| Nginx/route WS config | charts/kagenti/templates/ | 30 min |
| useSessionWebSocket hook | ui-v2/src/hooks/ | 1 hr |
| Replace SSE EventSource with WS | ui-v2/src/pages/SandboxPage.tsx | 2 hr |
| Multi-user viewer count badge | ui-v2/src/components/ | 30 min |
| Tests | e2e/ | 1 hr |

### Phase 3 Estimate (gRPC A2A)

| Task | Files | Effort |
|------|-------|--------|
| Proto schema definition | proto/agent.proto | 1 hr |
| Python codegen + server | agent/src/sandbox_agent/grpc_server.py | 2 hr |
| Backend gRPC client | backend/app/services/grpc_client.py | 2 hr |
| Replace SSE proxy with gRPC | backend/app/routers/sandbox.py | 2 hr |
| Dual-port agent (HTTP + gRPC) | agent Dockerfile + K8s service | 1 hr |
| Tests | e2e/ | 1 hr |

---

## How to Start Phase 1

```bash
export KUBECONFIG=/tmp/kagenti/sbox42-kubeconfig
export LOG_DIR=/tmp/kagenti/tdd/ui-sbox42

# 1. Create migration
cd .worktrees/sandbox-agent/kagenti/backend
# Add loop_events table to init SQL or Alembic migration

# 2. Modify SSE handler
# File: app/routers/sandbox.py
# In the LOOP_FWD section, add: await _insert_loop_event(pool, session_id, parsed)
# Remove the finally-block metadata write for loop_events

# 3. Modify history endpoint
# Read from loop_events table instead of tasks.metadata->'loop_events'

# 4. Build + deploy
cd .worktrees/sandbox-agent
git add -u && git commit -s -m "feat(backend): DB-backed event store" && git push
oc -n kagenti-system start-build kagenti-backend

# 5. Test
# Kill SSE mid-stream (navigate away), reload page → all events visible
RCA_SKIP_DEPLOY=1 RCA_AGENT_NAME=rca-agent-emptydir \
  npx playwright test e2e/agent-rca-workflow.spec.ts
```
