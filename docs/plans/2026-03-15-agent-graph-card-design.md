# AgentGraphCard Design

> **Date:** 2026-03-15
> **Status:** Brainstorm / RFC
> **Branch:** `next_phase_agents`

## Problem Statement

The sandbox agent's LangGraph graph topology is **implicitly duplicated** across
5 files in 2 repos:

| File | Repo | Hardcoded knowledge |
|------|------|---------------------|
| `graph.py` | agent-examples | Node names, edges, tools per node |
| `event_serializer.py` | agent-examples | `if key == "planner":` per-node methods |
| `event_schema.py` | agent-examples | One dataclass per event type |
| `sandbox.py` | kagenti | `if "loop_id" in parsed:` event routing |
| `loopBuilder.ts` | kagenti | `switch (event.type)` per-type reducer |

Adding a node or changing topology requires all 5 files. The backend and UI have
**implicit contracts** with the agent about event shapes. Different agent types
(sandbox, RCA, code-review) cannot reuse the same backend/UI code without
duplicating this contract.

Additionally, the UI's session/message loading is over-engineered:
- 5-second polling loop for new messages (even when idle)
- Complex de-duplication between polled and streamed data
- Race conditions between polling, history loading, and SSE streaming
- Flickering when polling and streaming overlap

## Solution Overview

Three interrelated changes:

1. **AgentGraphCard** — self-describing graph manifest with event catalog + topology
2. **Simplified message loading** — subscribe-based, no periodic polling
3. **Debug payloads per node** — every event carries LLM debug data or logic description

---

## 1. A2A Extension Mechanism

### How A2A Extensions Work

From the [A2A v1.0 spec](https://a2a-protocol.org/latest/specification/):

```python
class AgentExtension(A2ABaseModel):
    uri: str                        # Unique URI identifying the extension
    description: str | None         # Human-readable description
    required: bool | None           # Client MUST support to interact
    params: dict[str, Any] | None   # Extension-specific config
```

- Agent declares extensions in `AgentCard.capabilities.extensions[]`
- Client indicates support via `A2A-Extensions` HTTP header (comma-separated URIs)
- Extensions can add data to `metadata` fields on Messages, Artifacts, Tasks
- Extensions can add new JSON-RPC methods
- Each extension is identified by a globally unique URI

### GraphCard as A2A Extension

```python
AgentExtension(
    uri="urn:kagenti:agent-graph-card:v1",
    description="Processing graph topology, event catalog, and debug schemas",
    required=False,
    params={"endpoint": "/.well-known/agent-graph-card.json"}
)
```

**Separate endpoint** (`/.well-known/agent-graph-card.json`) because:
- Graph card can be large (event schemas, debug field declarations)
- Agents without graphs (simple A2A) don't pay the cost
- Clean separation: agent card = identity, graph card = execution model
- Cacheable independently (graph card changes less often than skills)

---

## 2. Two-Layer Architecture: Topology vs Event Catalog

### Key Insight

The graph card has **two conceptually distinct layers**:

1. **Topology** — LangGraph nodes and edges (for graph visualization)
2. **Event Catalog** — semantic event types the agent streams (for rendering)

These are **not 1:1**. A single LangGraph node (e.g., `executor`) emits multiple
semantic event types (`tool_call`, `micro_reasoning`, `thinking`). And a single
event type (`tool_result`) can come from multiple LangGraph nodes (`tools`,
`planner_tools`, `reflector_tools`).

The event catalog is the **streaming data model** — it defines what consumers
(backend, UI) receive. The topology is informational for visualization. Every
streamed event carries a `langgraph_node` field so consumers can always trace
back to the source.

---

## 3. AgentGraphCard Schema

```json
{
  "id": "sandbox-legion-v1",
  "description": "Plan-Execute-Reflect loop with tool execution",
  "framework": "langgraph",
  "version": "1.0.0",

  "event_catalog": {

    "planner_output": {
      "category": "reasoning",
      "description": "Plan created or updated with numbered steps",
      "langgraph_nodes": ["planner"],
      "has_llm_call": true,
      "fields": {
        "steps": {
          "type": "array",
          "items": {
            "index": { "type": "int" },
            "description": { "type": "string" },
            "status": { "type": "string", "enum": ["pending", "running", "done", "failed"] }
          }
        },
        "iteration": { "type": "int", "description": "Plan iteration (increments on replan)" }
      },
      "debug_fields": {
        "system_prompt": { "type": "string", "max_length": 50000 },
        "bound_tools": { "type": "array", "items": { "name": "string", "description": "string" }, "max_items": 50 },
        "prompt_messages": { "type": "array", "items": { "role": "string", "preview": "string" }, "max_items": 100 },
        "llm_response": { "type": "object", "description": "OpenAI-style response with choices, tool_calls, usage" }
      }
    },

    "executor_step": {
      "category": "reasoning",
      "description": "A plan step selected for execution with focused brief",
      "langgraph_nodes": ["step_selector"],
      "has_llm_call": true,
      "fields": {
        "step": { "type": "int" },
        "total_steps": { "type": "int" },
        "description": { "type": "string" },
        "reasoning": { "type": "string", "description": "Why this step was selected" }
      },
      "debug_fields": {
        "system_prompt": { "type": "string", "max_length": 50000 },
        "bound_tools": { "type": "array" },
        "prompt_messages": { "type": "array" },
        "llm_response": { "type": "object" }
      }
    },

    "thinking": {
      "category": "reasoning",
      "description": "LLM reasoning/thinking text emitted during node execution",
      "langgraph_nodes": ["planner", "executor", "reflector"],
      "has_llm_call": true,
      "fields": {
        "content": { "type": "string", "description": "Thinking/reasoning text" }
      },
      "debug_fields": {
        "system_prompt": { "type": "string" },
        "bound_tools": { "type": "array" },
        "prompt_messages": { "type": "array" },
        "llm_response": { "type": "object" }
      }
    },

    "tool_call": {
      "category": "execution",
      "description": "Tool invocation by executor or planner",
      "langgraph_nodes": ["executor", "planner"],
      "has_llm_call": false,
      "fields": {
        "step": { "type": "int" },
        "name": { "type": "string", "description": "Tool name" },
        "args": { "type": "object", "description": "Tool arguments" },
        "call_id": { "type": "string", "description": "Unique ID for pairing with tool_result" }
      },
      "debug_fields": {}
    },

    "tool_result": {
      "category": "tool_output",
      "description": "Tool execution output",
      "langgraph_nodes": ["tools", "planner_tools", "reflector_tools"],
      "has_llm_call": false,
      "fields": {
        "step": { "type": "int" },
        "name": { "type": "string" },
        "output": { "type": "string" },
        "call_id": { "type": "string", "description": "Pairs with tool_call" },
        "status": { "type": "string", "enum": ["success", "error", "rate_limited"] }
      },
      "debug_fields": {
        "logic": { "type": "string", "value": "Execute tool call via SandboxExecutor, apply permission checks" }
      }
    },

    "micro_reasoning": {
      "category": "reasoning",
      "description": "Brief reasoning between tool calls within a step",
      "langgraph_nodes": ["executor"],
      "has_llm_call": true,
      "fields": {
        "content": { "type": "string", "description": "Reasoning text" },
        "previous_tool": { "type": "string", "description": "Tool that triggered this reasoning" }
      },
      "debug_fields": {
        "system_prompt": { "type": "string" },
        "bound_tools": { "type": "array" },
        "prompt_messages": { "type": "array" },
        "llm_response": { "type": "object" }
      }
    },

    "reflector_decision": {
      "category": "decision",
      "description": "Reflection outcome determining next graph transition",
      "langgraph_nodes": ["reflector"],
      "has_llm_call": true,
      "fields": {
        "decision": {
          "type": "string",
          "enum": ["continue", "replan", "done", "retry"],
          "description": "What to do next"
        },
        "assessment": { "type": "string" },
        "iteration": { "type": "int" }
      },
      "debug_fields": {
        "system_prompt": { "type": "string" },
        "bound_tools": { "type": "array" },
        "prompt_messages": { "type": "array" },
        "llm_response": { "type": "object" }
      }
    },

    "reporter_output": {
      "category": "terminal",
      "description": "Final answer to the user (markdown)",
      "langgraph_nodes": ["reporter"],
      "has_llm_call": true,
      "terminal": true,
      "fields": {
        "content": { "type": "string" }
      },
      "debug_fields": {
        "system_prompt": { "type": "string" },
        "bound_tools": { "type": "array" },
        "prompt_messages": { "type": "array" },
        "llm_response": { "type": "object" }
      }
    },

    "router_decision": {
      "category": "decision",
      "description": "Entry routing: new plan vs resume",
      "langgraph_nodes": ["router"],
      "has_llm_call": false,
      "fields": {
        "route": { "type": "string", "enum": ["plan", "resume", "replan"] },
        "reason": { "type": "string" }
      },
      "debug_fields": {
        "logic": { "type": "string", "value": "Check plan_status and existing plan_steps to decide resume vs new plan" }
      }
    },

    "budget_update": {
      "category": "meta",
      "description": "Token/time budget status (emitted periodically)",
      "langgraph_nodes": [],
      "has_llm_call": false,
      "fields": {
        "tokens_used": { "type": "int" },
        "tokens_budget": { "type": "int" },
        "wall_clock_s": { "type": "float" },
        "max_wall_clock_s": { "type": "float" }
      },
      "debug_fields": {}
    },

    "node_transition": {
      "category": "meta",
      "description": "Emitted when graph traverses an edge (for graph visualization)",
      "langgraph_nodes": [],
      "has_llm_call": false,
      "fields": {
        "from_node": { "type": "string" },
        "to_node": { "type": "string" },
        "condition": { "type": "string", "description": "Edge condition that matched" }
      },
      "debug_fields": {}
    },

    "hitl_request": {
      "category": "interaction",
      "description": "Human-in-the-loop approval request",
      "langgraph_nodes": ["executor"],
      "has_llm_call": false,
      "fields": {
        "tool_name": { "type": "string" },
        "args": { "type": "object" },
        "reason": { "type": "string" },
        "call_id": { "type": "string" }
      },
      "debug_fields": {
        "logic": { "type": "string", "value": "PermissionChecker evaluated tool call against policy, requires user approval" }
      }
    }
  },

  "common_event_fields": {
    "type": {
      "type": "string",
      "description": "Event type discriminator (key into event_catalog)"
    },
    "loop_id": {
      "type": "string",
      "description": "Groups all events from a single agent invocation"
    },
    "langgraph_node": {
      "type": "string",
      "description": "The actual LangGraph node name that produced this event"
    },
    "node_visit": {
      "type": "int",
      "description": "Monotonic counter of graph node entries within this loop"
    },
    "event_index": {
      "type": "int",
      "description": "Chronological sequence number within this loop"
    },
    "model": {
      "type": "string",
      "description": "LLM model used (only for has_llm_call events)"
    },
    "prompt_tokens": { "type": "int" },
    "completion_tokens": { "type": "int" }
  },

  "topology": {
    "description": "LangGraph graph structure, auto-extracted via compiled.get_graph()",
    "entry_node": "router",
    "terminal_nodes": ["__end__"],

    "nodes": {
      "router": { "description": "Routes to planning or resume based on session state" },
      "planner": { "description": "Creates numbered execution plan" },
      "planner_tools": { "description": "Executes planner tool calls" },
      "step_selector": { "description": "Selects next step, writes focused brief" },
      "executor": { "description": "Executes current step using tools" },
      "tools": { "description": "Executes executor tool calls" },
      "reflector": { "description": "Evaluates results, decides next action" },
      "reflector_tools": { "description": "Executes reflector verification reads" },
      "reflector_route": { "description": "Pass-through for reflector routing" },
      "reporter": { "description": "Generates final summary report" }
    },

    "edges": [
      { "from": "__start__", "to": "router", "condition": null },
      { "from": "router", "to": "planner", "condition": "plan", "description": "New session or replan" },
      { "from": "router", "to": "step_selector", "condition": "resume", "description": "Resume existing plan" },
      { "from": "planner", "to": "planner_tools", "condition": "has_tool_calls" },
      { "from": "planner", "to": "step_selector", "condition": "no_tool_calls", "description": "Plan complete" },
      { "from": "planner_tools", "to": "planner", "condition": null },
      { "from": "step_selector", "to": "executor", "condition": null },
      { "from": "executor", "to": "tools", "condition": "has_tool_calls" },
      { "from": "executor", "to": "reflector", "condition": "no_tool_calls", "description": "Step done" },
      { "from": "tools", "to": "executor", "condition": null },
      { "from": "reflector", "to": "reflector_tools", "condition": "has_tool_calls" },
      { "from": "reflector", "to": "reflector_route", "condition": "no_tool_calls" },
      { "from": "reflector_tools", "to": "reflector", "condition": null },
      { "from": "reflector_route", "to": "step_selector", "condition": "execute", "description": "Continue/retry" },
      { "from": "reflector_route", "to": "planner", "condition": "replan" },
      { "from": "reflector_route", "to": "reporter", "condition": "done" },
      { "from": "reporter", "to": "__end__", "condition": null }
    ]
  }
}
```

### Design Decisions

**Two-layer separation:** `event_catalog` is the streaming contract (what the
UI/backend process). `topology` is the LangGraph structure (what the graph view
renders). They're linked by `langgraph_nodes` in each event type and
`langgraph_node` on every streamed event.

**Event categories:** 6 stable categories the UI switches on:
- `reasoning` — LLM thinking/planning (planner_output, executor_step, thinking, micro_reasoning)
- `execution` — tool invocations (tool_call)
- `tool_output` — tool results (tool_result)
- `decision` — routing decisions (reflector_decision, router_decision)
- `terminal` — final answer (reporter_output)
- `meta` — non-node events (budget_update, node_transition)
- `interaction` — HITL requests (hitl_request)

**`langgraph_node` on every event:** Even though `thinking` can come from
planner, executor, or reflector, the actual `langgraph_node` field tells the UI
which node produced it. This enables: "show me all events from the reflector"
as a filter, and the graph view highlighting the correct node.

**`has_llm_call` + `debug_fields`:** Events from LLM nodes carry:
- `system_prompt` — exact system prompt sent
- `bound_tools` — `[{name, description}]` of tools mounted for this call
- `prompt_messages` — `[{role, preview}]` summarized messages sent to LLM
- `llm_response` — OpenAI-style response object

Events from non-LLM nodes carry:
- `logic` — description of what the node does ("Execute tool call via
  SandboxExecutor, apply permission checks")

This maps directly to the existing `PromptInspector` component and
`LLMCallCapture.debug_fields()` in `context_builders.py`.

**`terminal: true`** on `reporter_output` tells backend/UI this event signals
loop completion without hardcoded name checks.

---

## 4. Auto-Generation from LangGraph

### LangGraph Introspection API

```python
compiled = graph.compile(checkpointer=checkpointer)
lg = compiled.get_graph()

# lg.nodes: Dict[str, Node]   — Node = NamedTuple(id, name, data, metadata)
# lg.edges: List[Edge]        — Edge = NamedTuple(source, target, data, conditional)
# lg.first_node() → Node      — entry point
# lg.last_node()  → Node      — terminal
```

### Generation Code

```python
# graph_card.py — new file in sandbox_agent/

# EVENT_CATALOG: declares the streaming data model.
# This is the source of truth for what the agent emits.
# It does NOT need to mirror LangGraph's node structure 1:1.
EVENT_CATALOG: dict[str, dict] = {
    "planner_output": {
        "category": "reasoning",
        "description": "Plan created or updated with numbered steps",
        "langgraph_nodes": ["planner"],
        "has_llm_call": True,
        "fields": {
            "steps": {"type": "array", "items": {...}},
            "iteration": {"type": "int"},
        },
        "debug_fields": {
            "system_prompt": {"type": "string", "max_length": 50000},
            "bound_tools": {"type": "array", "max_items": 50},
            "prompt_messages": {"type": "array", "max_items": 100},
            "llm_response": {"type": "object"},
        },
    },
    "thinking": {
        "category": "reasoning",
        "langgraph_nodes": ["planner", "executor", "reflector"],
        "has_llm_call": True,
        "fields": {"content": {"type": "string"}},
        "debug_fields": {...},
    },
    # ... all other event types ...
}


def build_graph_card(compiled: CompiledStateGraph, agent_id: str) -> dict:
    """Generate AgentGraphCard from compiled LangGraph + event catalog."""
    lg = compiled.get_graph()

    # --- Topology: fully extracted from LangGraph ---
    topo_nodes = {}
    for node_id, node in lg.nodes.items():
        if node_id in ("__start__", "__end__"):
            continue
        topo_nodes[node.name] = {
            "description": node.name,  # can be enriched from metadata
        }

    topo_edges = []
    for edge in lg.edges:
        topo_edges.append({
            "from": edge.source,
            "to": edge.target,
            "condition": str(edge.data) if edge.data else None,
            "conditional": edge.conditional,
        })

    entry = lg.first_node()
    terminal = lg.last_node()

    return {
        "id": agent_id,
        "framework": "langgraph",
        "version": "1.0.0",
        "event_catalog": EVENT_CATALOG,
        "common_event_fields": {...},
        "topology": {
            "entry_node": entry.name if entry else None,
            "terminal_nodes": [terminal.name] if terminal else [],
            "nodes": topo_nodes,
            "edges": topo_edges,
        },
    }
```

**What comes from LangGraph automatically:**
- All topology nodes and their IDs
- All edges (source → target), including conditional flag
- Entry/terminal nodes

**What is manually declared (EVENT_CATALOG):**
- Event types with their field schemas
- Which LangGraph nodes produce which events
- Whether the event involves an LLM call
- Debug field declarations
- Category for UI rendering

This is intentional. The event catalog is the **streaming contract** — it must
be explicit. LangGraph can't know what JSON the serializer will emit. But the
topology is fully mechanical.

### Serving the Endpoint

```python
# In agent.py:
graph_card = build_graph_card(compiled_graph, "sandbox-legion-v1")

@app.get("/.well-known/agent-graph-card.json")
async def get_graph_card():
    return JSONResponse(graph_card)

# Declare in AgentCard.capabilities.extensions:
AgentExtension(
    uri="urn:kagenti:agent-graph-card:v1",
    description="Processing graph topology and event schemas",
    required=False,
    params={"endpoint": "/.well-known/agent-graph-card.json"},
)
```

---

## 5. Simplified Message Loading

### Current State (broken)

```
SandboxPage.tsx has THREE concurrent data paths:

1. loadInitialHistory()   — fetch all messages + loop_events on session open
2. 5-second poll interval — lightweight fetch for new messages (skip_events)
3. SSE subscribe          — live events from active agent loop

These RACE with each other:
- Poll adds a message → subscribe delivers same message → duplicate
- History load + subscribe fire simultaneously → stale state
- De-duplication by _index + content prefix (first 100 chars) — fragile
- justFinishedStreamingRef flag prevents reload but adds complexity
```

### New Model: Subscribe-Driven, No Polling

```
State Machine:

  IDLE ─────→ LOADING ─────→ LOADED ─────→ SUBSCRIBING
   ↑               ↑             │              │
   │               │             │    stream     │
   │               │             │    ends       │
   │               │             ↓              ↓
   │          SIGNAL_QUEUED   (all done)   RECOVERING
   │               │              │              │
   │               │              ↓              ↓
   └───────────────┴──────── IDLE ◄──── (retries exhausted)
```

#### Step 1: Session Open → Load History

```typescript
async function loadSession(ns: string, contextId: string) {
  state = 'LOADING';

  const [session, history] = await Promise.all([
    sandboxService.getSession(ns, contextId),
    sandboxService.getHistory(ns, contextId, { limit: 50 }),
  ]);

  // Reconstruct loops from persisted loop_events
  const loops = buildAgentLoops(history.loop_events, graphCard);
  setMessages(history.messages);
  setAgentLoops(loops);

  state = 'LOADED';

  // Check: is the latest loop still running?
  const latestLoop = loops[loops.length - 1];
  if (latestLoop && !latestLoop.finalAnswer && latestLoop.status !== 'failed') {
    subscribeToLoop(ns, contextId);
  }
}
```

#### Step 2: Subscribe to Active Loop (Event-Driven)

```typescript
async function subscribeToLoop(ns: string, contextId: string) {
  state = 'SUBSCRIBING';

  const stream = await fetch(`/api/v1/sandbox/${ns}/sessions/${contextId}/subscribe`);
  const reader = stream.body.getReader();

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    const event = parseSSE(value);

    if (event.done) {
      // Terminal: loop finished normally
      finalizeLoops();
      state = 'IDLE';
      return;
    }

    if (event.loop_event) {
      applyLoopEvent(event.loop_event, graphCard);
    }
  }

  // Stream ended without explicit [DONE] → disconnection or cancellation
  recoverFromDisconnect(ns, contextId);
}
```

#### Step 3: Recovery on Disconnect/Cancel

```typescript
async function recoverFromDisconnect(ns: string, contextId: string) {
  state = 'RECOVERING';
  const MAX_RETRIES = 5;
  const RETRY_DELAYS = [1000, 2000, 4000, 8000, 15000]; // exponential backoff

  for (let i = 0; i < MAX_RETRIES; i++) {
    await sleep(RETRY_DELAYS[i]);

    // Check if a new task exists for this session
    const history = await sandboxService.getHistory(ns, contextId, {
      limit: 5,
      skip_events: false, // need loop_events to check status
    });

    const latestTaskState = history.task_state;

    if (latestTaskState === 'working' || latestTaskState === 'submitted') {
      // Agent still running or new task started → resubscribe
      subscribeToLoop(ns, contextId);
      return;
    }

    if (TERMINAL_STATES.has(latestTaskState)) {
      // Agent finished while we were disconnected → load final state
      const loops = buildAgentLoops(history.loop_events, graphCard);
      setAgentLoops(loops);
      state = 'IDLE';
      return;
    }
  }

  // Retries exhausted, no new activity
  state = 'IDLE';
}
```

#### Step 4: Session Status Polling (Activity Detection Only)

This replaces the 5-second message poll. It's low-frequency and only detects
whether a NEW agent loop has started (e.g., another user sent a message).

```typescript
useEffect(() => {
  if (state === 'SUBSCRIBING' || state === 'RECOVERING') return; // no-op while streaming

  const interval = setInterval(async () => {
    const session = await sandboxService.getSession(ns, contextId);

    if (session.task_state === 'working' && state === 'IDLE') {
      // New activity detected, we're not streaming → reload
      loadSession(ns, contextId);
    }

    if (session.task_state === 'working' && state === 'SUBSCRIBING') {
      // Already streaming — queue the signal, don't interrupt
      // The signal will be processed when current stream ends
      pendingReloadSignal.current = true;
    }
  }, 30_000); // 30 seconds, not 5

  return () => clearInterval(interval);
}, [state, ns, contextId]);
```

#### Signal Gating: Anti-Flicker

The core anti-flicker mechanism is a **signal gate**:

```typescript
const pendingReloadSignal = useRef(false);

// After any stream ends (subscribe or chat/stream):
function onStreamEnd() {
  state = 'IDLE';

  if (pendingReloadSignal.current) {
    pendingReloadSignal.current = false;
    loadSession(ns, contextId); // deferred reload
  }
}
```

**Rules:**
1. While `state === 'SUBSCRIBING'`: reject reload signals, set `pendingReloadSignal`
2. While `state === 'LOADING'`: reject all signals (already loading)
3. While `state === 'IDLE'`: accept reload signals immediately
4. On stream end: check `pendingReloadSignal`, reload if set

This eliminates:
- The 5-second polling interval (replaced by 30s session status check)
- Message de-duplication logic (no concurrent polling + streaming)
- `justFinishedStreamingRef` flag (replaced by state machine)
- Content-prefix de-dup heuristics (no overlapping data sources)

### What Gets Deleted

| Current code | Lines | Replaced by |
|--------------|-------|-------------|
| 5s `setInterval` polling loop | SandboxPage.tsx:1267-1365 | 30s session status poll |
| De-dup by `_index` + content prefix | SandboxPage.tsx:1326-1357 | No concurrent sources |
| `justFinishedStreamingRef` | SandboxPage.tsx:1245-1247 | State machine |
| `allLoopsDone` polling guard | SandboxPage.tsx:1267-1270 | State machine |
| `skip_events` lightweight poll | sandbox.py history endpoint | Not needed |

---

## 6. Debug Payloads Per Node

### Current State

Already implemented in `context_builders.py` → `event_serializer.py` → UI:

- `LLMCallCapture` captures system_prompt, bound_tools, prompt_messages, llm_response
- `_extract_prompt_data()` in serializer extracts these fields
- Gated by `SANDBOX_DEBUG_PROMPTS` env var (default: on)
- `PromptInspector.tsx` renders them in a modal

### What Changes

The graph card **declares** which debug fields each event type supports. This
replaces the current implicit contract where the UI checks for `systemPrompt`
on every step and shows the inspector if present.

**Every streamed event** includes a `_debug` field (when debug is enabled):

```json
// LLM node event (has_llm_call: true):
{
  "type": "planner_output",
  "langgraph_node": "planner",
  "loop_id": "abc123",
  "steps": [...],
  "_debug": {
    "system_prompt": "You are a planning agent...",
    "bound_tools": [
      { "name": "file_read", "description": "Read file contents" },
      { "name": "grep", "description": "Search file contents" }
    ],
    "prompt_messages": [
      { "role": "system", "preview": "You are a planning agent..." },
      { "role": "user", "preview": "Fix the login bug in auth.py" }
    ],
    "llm_response": {
      "choices": [{ "message": { "content": "Plan:\n1. ..." } }],
      "usage": { "prompt_tokens": 1200, "completion_tokens": 450 }
    }
  }
}

// Non-LLM node event (has_llm_call: false):
{
  "type": "tool_result",
  "langgraph_node": "tools",
  "loop_id": "abc123",
  "name": "shell",
  "output": "...",
  "_debug": {
    "logic": "Execute tool call via SandboxExecutor. Permission check: ALLOWED (shell in permitted_tools). Timeout: 120s.",
    "input": { "tool": "shell", "args": { "command": "grep -r 'login' src/" } },
    "output_meta": { "exit_code": 0, "stdout_bytes": 1234, "truncated": false }
  }
}

// Decision node event (no LLM, deterministic logic):
{
  "type": "router_decision",
  "langgraph_node": "router",
  "loop_id": "abc123",
  "route": "resume",
  "_debug": {
    "logic": "Check plan_status='executing' and plan_steps=[5 items, 3 done] → resume at step 3",
    "input": { "plan_status": "executing", "plan_steps_count": 5, "done_count": 3 },
    "output": { "route": "resume", "resume_step": 3 }
  }
}
```

### UI Changes for Debug

The `PromptInspector` component becomes graph-card-aware:

```typescript
function openInspector(event: LoopEvent, graphCard: AgentGraphCard) {
  const eventDef = graphCard.event_catalog[event.type];
  if (!eventDef) return;

  if (eventDef.has_llm_call) {
    // Show LLM debug: system prompt, bound tools, messages, response
    setInspectorData({
      mode: 'llm',
      title: `${eventDef.description} (${event.langgraph_node})`,
      systemPrompt: event._debug?.system_prompt,
      boundTools: event._debug?.bound_tools,
      promptMessages: event._debug?.prompt_messages,
      llmResponse: event._debug?.llm_response,
      model: event.model,
      promptTokens: event.prompt_tokens,
      completionTokens: event.completion_tokens,
    });
  } else {
    // Show logic debug: what the node did and why
    setInspectorData({
      mode: 'logic',
      title: `${eventDef.description} (${event.langgraph_node})`,
      logic: event._debug?.logic,
      input: event._debug?.input,
      output: event._debug?.output_meta,
    });
  }
}
```

---

## 7. UI Rendering Modes

The graph card provides **data structure and topology**. The UI renders it in
multiple modes using different grouping keys.

### Mode 1: Inline Message View (default)

Messages in chat list. Each message shows a collapsed **summary card** with
a link to fullscreen.

- **Grouping key:** `loop_id` (one card per agent invocation)
- **Sub-grouping:** `node_visit` (sections within the card)
- Events rendered as: plan steps, tool calls, reflections inline
- Collapsed by default, expandable
- **Summary line:** "Planned 5 steps, executed 14 tool calls, done in 2m"

### Mode 2: Fullscreen Loop View

Detailed view of a single agent loop — accessed via [Fullscreen] link on
each inline message.

- **Grouping key:** `loop_id`
- **Sub-grouping:** `event_index` (chronological) or `step` (by plan step)
- Toggle between chronological and step-grouped views
- Full tool output visible, debug inspector available on every event
- Shows all thinking/micro_reasoning that inline mode hides

### Mode 3: Graph Topology View

Visual DAG rendered from `topology.edges[]`, connected to live event stream.

- **Data source:** `topology.edges` for DAG layout
- **Live state:** `node_transition` events highlight active node + animate edge
- **Edge annotations:** Traversal count badge with popup details
  - Click edge → table: timestamp, condition, duration per traversal
- **Multi-message:** Graph persists across messages in the session
  - Last node of message N connects via dashed arrow to first node of message N+1
  - If message N was cancelled → arrow from last reached node
  - Accumulated edge counts show total across all messages

### Multi-Message Navigation (All Modes)

Collapsible sidebar on the left:

```
▼ Message 1: "Fix the login bug"         [Graph] [Detail]
   Loop: 3a8f — 5 steps, 14 tools, done ✓
▼ Message 2: "Also update the tests"     [Graph] [Detail]
   Loop: 7c2d — 3 steps, 8 tools, done ✓
▶ Message 3: "Deploy to staging"         [Graph] [Detail]  ← active
   Loop: e1b5 — step 3/5, running...
```

Each message row shows: user prompt summary, loop status, step progress.
Click [Graph] or [Detail] to switch rendering mode for that message.
Click the message to expand it in the main panel.

### Graph Card → UI Type Mapping

```typescript
// types/graphCard.ts

interface AgentGraphCard {
  id: string;
  description: string;
  framework: string;
  version: string;
  event_catalog: Record<string, EventTypeDef>;
  common_event_fields: Record<string, FieldSchema>;
  topology: GraphTopology;
}

interface EventTypeDef {
  category: EventCategory;
  description: string;
  langgraph_nodes: string[];
  has_llm_call: boolean;
  terminal?: boolean;
  fields: Record<string, FieldSchema>;
  debug_fields: Record<string, FieldSchema>;
}

type EventCategory =
  | 'reasoning'     // planner_output, executor_step, thinking, micro_reasoning
  | 'execution'     // tool_call
  | 'tool_output'   // tool_result
  | 'decision'      // reflector_decision, router_decision
  | 'terminal'      // reporter_output
  | 'meta'          // budget_update, node_transition
  | 'interaction';  // hitl_request

interface GraphTopology {
  entry_node: string;
  terminal_nodes: string[];
  nodes: Record<string, { description: string }>;
  edges: GraphEdge[];
}

interface GraphEdge {
  from: string;
  to: string;
  condition: string | null;
  conditional?: boolean;
  description?: string;
}

interface FieldSchema {
  type: string;
  description?: string;
  enum?: string[];
  items?: Record<string, FieldSchema>;
  max_length?: number;
  max_items?: number;
  value?: string;  // static value for logic descriptions
}
```

### loopBuilder.ts Refactoring

Current: `switch (event.type)` with 14+ cases.
New: `switch (eventDef.category)` with 7 stable values.

```typescript
function applyLoopEvent(
  loop: AgentLoop,
  event: LoopEvent,
  graphCard: AgentGraphCard
): AgentLoop {
  const eventDef = graphCard.event_catalog[event.type];
  if (!eventDef) return loop; // Unknown event type — skip

  switch (eventDef.category) {
    case 'reasoning':
      return applyReasoningEvent(loop, event, eventDef);
    case 'execution':
      return applyExecutionEvent(loop, event, eventDef);
    case 'tool_output':
      return applyToolOutputEvent(loop, event, eventDef);
    case 'decision':
      return applyDecisionEvent(loop, event, eventDef);
    case 'terminal':
      return applyTerminalEvent(loop, event, eventDef);
    case 'meta':
      return applyMetaEvent(loop, event, eventDef);
    case 'interaction':
      return applyInteractionEvent(loop, event, eventDef);
  }
}
```

Within each handler, the `event.langgraph_node` field distinguishes subtypes:

```typescript
function applyReasoningEvent(loop, event, eventDef) {
  // All reasoning events get added to the thinking/reasoning section
  // The langgraph_node tells us context (planner vs executor vs reflector)
  // The event.type tells us the specific subtype (planner_output vs thinking vs micro_reasoning)

  const section = findOrCreateSection(loop, event.node_visit);
  section.langgraph_node = event.langgraph_node;
  section.type = event.type; // e.g., 'planner_output', 'thinking', 'micro_reasoning'

  if (event.type === 'planner_output') {
    loop.plan = event.steps;
    loop.iteration = event.iteration;
  }

  if (event.type === 'executor_step') {
    section.stepIndex = event.step;
    section.description = event.description;
  }

  if (event._debug && eventDef.has_llm_call) {
    section.debug = event._debug; // system_prompt, bound_tools, etc.
  }

  return { ...loop };
}
```

---

## 8. Cross-Message Continuity in Graph View

Each message is a separate agent invocation (separate `loop_id`). The graph
view connects them:

```
Message 1: router → planner → step_selector → executor ⇄ tools → reflector → reporter → __end__
                                                                                    ┊
Message 2: router → step_selector → executor ⇄ tools → reflector → reporter → __end__
                    (resume path)     └── dashed arrow from Message 1's reporter
```

For cancelled messages:
```
Message 3: router → planner → step_selector → executor → [CANCELLED at tools]
                                                               ┊
Message 4: router → step_selector → executor → ...
                    └── dashed arrow from Message 3's tools (last reached)
```

**Implementation:** Store `lastNodeReached` per loop. Source it from the last
`node_transition` event's `to_node` field, or from the last event's
`langgraph_node` if no transition events exist.

---

## 9. Backend Changes

### Graph Card Fetch + Cache

```python
# chat.py — new endpoint:
@router.get("/{namespace}/{name}/graph-card")
async def get_graph_card(namespace: str, name: str):
    agent_card = await fetch_agent_card(namespace, name)
    ext = next(
        (e for e in (agent_card.capabilities.extensions or [])
         if e.uri == "urn:kagenti:agent-graph-card:v1"),
        None,
    )
    if not ext:
        return JSONResponse(None, status_code=404)

    endpoint = ext.params["endpoint"]
    agent_url = build_agent_url(namespace, name)
    card = await httpx.AsyncClient().get(f"{agent_url}{endpoint}")
    return card.json()
```

### Generic Event Routing in sandbox.py

```python
# Build terminal set from graph card (once per agent):
terminal_types = {
    et for et, edef in graph_card["event_catalog"].items()
    if edef.get("terminal")
}

# In streaming loop — generic forwarding:
async for event in agent_sse_stream:
    parsed = json.loads(event)
    if "loop_id" in parsed:
        yield sse_event(parsed)
        loop_events.append(parsed)
        if parsed.get("type") in terminal_types:
            # loop done
            ...
```

---

## 10. Implementation Phases

### Phase 1: Graph Card Foundation
- [ ] `graph_card.py` in agent-examples: EVENT_CATALOG + `build_graph_card()`
- [ ] Serve at `/.well-known/agent-graph-card.json`
- [ ] Declare A2A extension in AgentCard
- [ ] Backend: fetch + cache graph card
- [ ] Backend: pass graph card to UI via new endpoint

### Phase 2: Event Catalog Integration
- [ ] Add `langgraph_node` to every streamed event (serializer change)
- [ ] Standardize `_debug` payload on all events (LLM and non-LLM)
- [ ] Backend: generic event routing from graph card (replace hardcoded logic)
- [ ] Add `node_transition` meta-events to serializer

### Phase 3: Simplified Message Loading
- [ ] Remove 5s polling interval from SandboxPage.tsx
- [ ] Implement subscribe-driven state machine (IDLE→LOADING→SUBSCRIBING→RECOVERING)
- [ ] Add signal gating (`pendingReloadSignal`) for anti-flicker
- [ ] Replace 30s session status poll (activity detection only)
- [ ] Delete de-duplication logic, `justFinishedStreamingRef`, `allLoopsDone` guard

### Phase 4: UI Event Catalog Types + Reducer
- [ ] TypeScript types for GraphCard, EventTypeDef, GraphTopology
- [ ] Refactor loopBuilder.ts: `switch(category)` instead of `switch(event.type)`
- [ ] PromptInspector: graph-card-aware (LLM mode vs logic mode)
- [ ] Fetch graph card on agent selection

### Phase 5: Multi-Message Navigation
- [ ] Collapsible message sidebar
- [ ] Inline mode: summary card + fullscreen link
- [ ] Fullscreen loop detail view

### Phase 6: Graph Topology Visualization
- [ ] DAG rendering from `topology.edges`
- [ ] Live node highlighting via `node_transition` events
- [ ] Edge traversal counters + popup detail table
- [ ] Cross-message dashed arrow connections (lastNodeReached)

---

## 11. Files Affected

### Agent (agent-examples repo)

| File | Change |
|------|--------|
| `graph_card.py` | **New**: EVENT_CATALOG, build_graph_card() |
| `agent.py` | Serve /.well-known/agent-graph-card.json, declare extension |
| `event_serializer.py` | Add `langgraph_node` to events, `node_transition` meta-events, standardize `_debug` |
| `event_schema.py` | Add NodeTransition, RouterDecision dataclasses |
| `context_builders.py` | Add non-LLM debug payload (logic, input, output_meta) |

### Backend (kagenti repo)

| File | Change |
|------|--------|
| `routers/chat.py` | New endpoint: fetch graph card via A2A extension |
| `routers/sandbox.py` | Generic event routing; simplify subscribe/resubscribe logic |
| `models/graph_card.py` | **New**: AgentGraphCard Pydantic model (optional) |

### UI (kagenti repo)

| File | Change |
|------|--------|
| `types/graphCard.ts` | **New**: AgentGraphCard, EventTypeDef, GraphTopology types |
| `services/api.ts` | Fetch graph card |
| `utils/loopBuilder.ts` | Refactor: category-based reducer + graph card lookup |
| `pages/SandboxPage.tsx` | Replace polling with subscribe state machine |
| `components/PromptInspector.tsx` | Graph-card-aware: LLM mode + logic mode |
| `components/GraphView.tsx` | **New**: DAG topology visualization |
| `components/MessageSidebar.tsx` | **New**: multi-message navigation |

---

## 12. GenAI OTel Auto-Instrumentation

### Integration with AgentGraphCard

The graph card's event processing pipeline should emit OTel spans — each node
visit becomes a child span under the root `invoke_agent` span. This gives
MLflow/Phoenix visibility into the agent's reasoning graph.

### Architecture

```
User Request → A2A JSON-RPC
  ↓
Root Span Middleware (observability.py)
  ├─ Span: "invoke_agent sandbox-legion"
  ├─ Attributes: gen_ai.*, mlflow.*, openinference.*
  │
  ├─ LangGraph Graph Execution
  │  ├─ node_transition: router → planner
  │  ├─ Planning Node → [Auto-instrumented LLM child span]
  │  ├─ node_transition: planner → step_selector
  │  ├─ Executor Node → [Auto-instrumented LLM + Tool child spans]
  │  ├─ node_transition: executor → reflector
  │  └─ Reflector Node → [Auto-instrumented LLM child span]
  │
  └─ Response (root span status = OK)
  ↓
OTLP Exporter (port 8335)
  ↓
OTel Collector → MLflow + Phoenix
```

### Wizard Toggle

The wizard `SandboxCreateRequest` has `enable_tracing: bool = True`. When
enabled, the deployment sets `OTEL_EXPORTER_OTLP_ENDPOINT`. The agent's
`observability.py` checks for this env var at startup:
- **Set** → configure TracerProvider, auto-instrument LangChain/OpenAI
- **Not set** → skip tracing entirely (zero overhead)

### Implementation

**Agent side:** `observability.py` (copied from weather_service pattern):
- `setup_observability()` — TracerProvider + auto-instrumentation
- `create_tracing_middleware()` — root span with GenAI attributes
- Called from `agent.py:run()` before app initialization

**Key attributes per event_catalog category:**

| Category | Span Name | Attributes |
|----------|-----------|------------|
| reasoning | `{langgraph_node}` | gen_ai.request.model, prompt_tokens, completion_tokens |
| execution | `tool_call {name}` | tool.name, tool.args |
| tool_output | `tool_result {name}` | tool.name, status |
| decision | `{langgraph_node}_decision` | decision, assessment |
| terminal | `reporter_output` | content length, total tokens |

### Files

| File | Change |
|------|--------|
| `observability.py` | **New**: setup_observability(), root span middleware |
| `agent.py` | Wire observability into startup + middleware |
| `sandbox_deploy.py` | `enable_tracing` wizard field, conditional OTEL endpoint |
| `pyproject.toml` | Add openinference-instrumentation-langchain |

---

## Sources

- [A2A Protocol Specification](https://a2a-protocol.org/latest/specification/)
- [A2A Extensions: Empowering Custom Agent Functionality](https://developers.googleblog.com/en/a2a-extensions-empowering-custom-agent-functionality/)
- [LangGraph Graph API Reference](https://reference.langchain.com/python/langgraph/graphs)
- [LangGraph Visualization with get_graph](https://kitemetric.com/blogs/visualizing-langgraph-workflows-with-get-graph)
- [langchain_core.runnables.graph.Graph](https://python.langchain.com/api_reference/core/runnables/langchain_core.runnables.graph.Graph.html)
