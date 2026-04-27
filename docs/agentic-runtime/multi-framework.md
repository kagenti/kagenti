# Multi-Framework Runtime

> **Status: WIP** -- LangGraph is shipped. OpenCode adapter in progress.
> Claude Agent SDK, OpenHands, CrewAI, AG2 are designed.

The Agentic Runtime is framework-neutral. The platform owns infrastructure
while agents provide business logic. This guide covers how different
frameworks integrate via the instrumentation contract.

---

## Overview

Every framework adapter bridges two contracts:

1. **Plugin Contract** -- `get_agent_card()` + `build_executor()` -- makes the
   agent an A2A service (see [Writing Agents](./agents.md))
2. **Instrumentation Contract** -- `FrameworkEventSerializer` +
   `AgentGraphCardBuilder` -- enables graph views, event persistence, and
   debugging in the UI (see [Concepts](./concepts.md#agentgraphcard))

```
+---------------------------------------------------------------+
|  Platform Layer (always present)                               |
+---------------------------------------------------------------+
|  Instrumentation Contract                                      |
|  FrameworkEventSerializer     AgentGraphCardBuilder            |
+---------------------------------------------------------------+
|  Framework Adapters                                            |
|  LangGraph   OpenCode   Claude SDK   CrewAI   AG2   OpenHands |
+---------------------------------------------------------------+
|  Agent Business Logic                                          |
+---------------------------------------------------------------+
```

---

## Framework Status

| Framework | Language | Plugin | Serializer | Graph Card | Status |
|-----------|----------|--------|------------|------------|--------|
| **LangGraph** | Python | Native | `LangGraphSerializer` | Introspects compiled graph | **Shipped** |
| **OpenCode** | Go | `opencode/plugin.py` | Polling only (no events yet) | Static ReAct topology | **WIP** |
| **Claude Agent SDK** | Python | Designed | Async iterator + hooks | Static ReAct topology | **Designed** |
| **OpenHands** | Python | Designed | EventStream subscriber | Multi-node topology | **Designed** |
| **CrewAI** | Python | Designed | BaseEventListener | Agent-per-node | **Designed** |
| **AG2** | Python | Designed | AG-UI SSE or OTel spans | Multi-agent dynamic | **Designed** |

---

## LangGraph (Shipped)

The reference implementation. LangGraph agents run natively in the platform
base image with full instrumentation.

**Interception:** `stream_mode='updates'` yields `(node_name, state_dict)` tuples.
The `LangGraphSerializer` (697 lines) translates these into EVENT_CATALOG events.

**Graph card:** `build_graph_card()` introspects `compiled_graph.get_graph()`
to extract nodes and edges programmatically. Conditional edges appear as
multiple edges from the same source.

**Key files:**
- `event_serializer.py` -- LangGraph -> EVENT_CATALOG translation
- `graph_card.py` -- Graph introspection + event catalog
- `event_schema.py` -- Event type dataclasses

---

## OpenCode (WIP)

[OpenCode](https://opencode.ai/) is a Go-based coding agent CLI. It runs as
a subprocess (`opencode serve`) with an HTTP API.

**Current state:** `OpenCodeExecutor` starts OpenCode, creates sessions via
REST, and polls for responses every 5 seconds. Emits only basic A2A task
status updates -- no EVENT_CATALOG events.

**WIP plan:**

1. Replace polling with SSE client consuming OpenCode's `/event` stream
2. Create `OpenCodeSerializer` mapping `entity.action` events:

| OpenCode Event | EVENT_CATALOG Type | Category |
|---------------|-------------------|----------|
| `message.part.updated` | `thinking` | reasoning |
| `tool.execute.before` | `tool_call` | execution |
| `tool.execute.after` | `tool_result` | tool_output |
| `session.idle` | `reporter_output` | terminal |
| `session.error` | `error` | terminal |
| `permission.asked` | `hitl_request` | interaction |

3. Static topology (simple ReAct loop):
```json
{
  "nodes": {
    "assistant": "LLM reasoning and tool selection",
    "tools": "Tool execution (shell, file, browser)"
  },
  "edges": [
    {"source": "__start__", "target": "assistant"},
    {"source": "assistant", "target": "tools"},
    {"source": "tools", "target": "assistant"},
    {"source": "assistant", "target": "__end__"}
  ]
}
```

**Key challenge:** OpenCode's SSE stream is session-scoped (all events on one
stream). Must filter by `sessionID` to isolate events for the current A2A
context.

---

## Claude Agent SDK (Designed)

The [Claude Agent SDK](https://github.com/anthropics/claude-agent-sdk-python)
wraps Claude Code's agent loop. `query()` returns an async iterator of
typed messages.

**Interception:** Async iterator yields 5 message types + 19 hook events.

| Claude SDK Type | EVENT_CATALOG Type | Category |
|----------------|-------------------|----------|
| `AssistantMessage` (text) | `thinking` | reasoning |
| `AssistantMessage` (tool_use) | `tool_call` | execution |
| `UserMessage` (tool_result) | `tool_result` | tool_output |
| `StreamEvent` (text delta) | `thinking` | reasoning |
| `ResultMessage(success)` | `reporter_output` | terminal |
| `ResultMessage(error_*)` | `error` | terminal |
| `Notification(permission_prompt)` | `hitl_request` | interaction |

**Hooks:** `PreToolUse` and `PostToolUse` fire out-of-band (not in context
window). Can enrich tool_call/tool_result events with metadata.

**Topology:** Static ReAct loop (same as OpenCode).

---

## CrewAI (Designed)

[CrewAI](https://crewai.com/) uses a task-oriented multi-agent model with
`BaseEventListener` for observation.

**Interception:** `@bus.on(EventType)` decorators. Richest event taxonomy
(40+ event types).

| CrewAI Event | EVENT_CATALOG Type | Category |
|-------------|-------------------|----------|
| `LLMCallCompletedEvent` | `thinking` | reasoning |
| `AgentExecutionStartedEvent` | `executor_step` | reasoning |
| `TaskStartedEvent` | `planner_output` | reasoning |
| `ToolUsageStartedEvent` | `tool_call` | execution |
| `ToolUsageFinishedEvent` | `tool_result` | tool_output |
| `TaskEvaluationEvent` | `reflector_decision` | decision |
| `TaskCompletedEvent` | `reporter_output` | terminal |
| `CrewKickoffFailedEvent` | `error` | terminal |

**Topology:** Constructed from `Crew(agents, tasks, process)` definition.
Each agent becomes a node; edges follow the process type (sequential or
hierarchical).

---

## AG2 / AutoGen (Designed)

[AG2](https://ag2.ai/) supports multi-agent conversations with native
OpenTelemetry instrumentation.

**Interception:** Three options:
1. `AGUIStream` SSE events (AG-UI protocol) -- best for streaming
2. `instrument_agent()` OTel spans -- best for observability
3. Python logger (`ag2.event.processor`) -- most complete

| AG-UI Event | EVENT_CATALOG Type | Category |
|------------|-------------------|----------|
| `TEXT_MESSAGE_CONTENT` | `thinking` | reasoning |
| `TOOL_CALL_START` | `tool_call` | execution |
| `TOOL_CALL_RESULT` | `tool_result` | tool_output |
| `RUN_FINISHED` | `reporter_output` | terminal |
| `RUN_ERROR` | `error` | terminal |
| `STATE_SNAPSHOT` | `budget_update` | meta |

**Topology:** Multi-agent with dynamic speaker selection. The graph card
captures the declared topology; runtime deviations appear as
`node_transition` events.

**Key advantage:** AG2 has native OTel with GenAI semantic conventions.
The adapter could consume OTel spans via a SpanProcessor rather than
re-instrumenting.

---

## OpenHands (Designed)

[OpenHands](https://openhands.dev/) (formerly OpenDevin) uses an
event-sourced model with Action/Observation pairs.

**Interception:** V0: `EventStreamSubscriber` callback. V1 SDK (target):
WebSocket `ConversationStateUpdateEvent`.

| OpenHands Event | EVENT_CATALOG Type | Category |
|----------------|-------------------|----------|
| `AgentThinkAction` | `thinking` | reasoning |
| `CmdRunAction` | `tool_call` | execution |
| `FileEditAction` | `tool_call` | execution |
| `CmdOutputObservation` | `tool_result` | tool_output |
| `AgentFinishAction` | `reporter_output` | terminal |
| `ErrorObservation` | `error` | terminal |
| `AgentDelegateAction` | `reflector_decision` | decision |
| `UserRejectObservation` | `hitl_request` | interaction |

**Topology:** Multi-node: controller, runtime, browser, delegate.

---

## Graph Card Generation

Each framework has a different way to determine the topology:

| Framework | Source | Method |
|-----------|--------|--------|
| LangGraph | `compiled_graph.get_graph()` | Programmatic introspection |
| OpenCode | Static | Hardcoded ReAct topology |
| Claude Agent SDK | Static | Hardcoded ReAct topology |
| OpenHands | Agent class structure | Introspect action handlers |
| CrewAI | `Crew(agents, tasks)` | Introspect crew definition |
| AG2 | `GroupChat(agents)` | Introspect speaker transitions |

**Static vs dynamic:**
- **Static:** OpenCode, Claude SDK -- simple ReAct loops
- **Semi-static:** LangGraph, CrewAI -- defined at build time
- **Dynamic:** AG2, OpenHands -- may change during execution

For dynamic topologies, the graph card captures the initial/declared
structure. Runtime deviations appear as `node_transition` meta-events.

---

## Adding a New Framework

1. Create `agents/my_framework/plugin.py` with `get_agent_card()` and
   `build_executor()` (see [Writing Agents](./agents.md))
2. Create `agents/my_framework/serializer.py` implementing
   `FrameworkEventSerializer`
3. Create `agents/my_framework/graph_card.py` implementing
   `AgentGraphCardBuilder`
4. Create `agents/my_framework/Dockerfile` extending `kagenti-agent-base`
5. Set `AGENT_MODULE=my_framework.plugin` in the deployment
6. Write parity tests verifying EVENT_CATALOG output
