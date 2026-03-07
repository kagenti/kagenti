# Tabbed Session View Design

> **Date:** 2026-03-05
> **Session:** L+1
> **Status:** Approved

## Overview

Redesign the SandboxPage session detail from a single chat view to a tabbed
interface. Each session gets tabs for Chat, Graph, Statistics, Files, and more.
The WelcomeCard becomes a permanent first message in the chat flow.

## Decisions

| Decision | Choice |
|----------|--------|
| WelcomeCard | Permanent first message (always visible, scrolls with chat) |
| Tab system | PatternFly Tabs with lazy panel rendering |
| Tab persistence | URL search param `&tab=graph` |
| Stats data | Collected from SSE events + backend API for history |
| Agent image | All sandbox variants use reasoning loop image with `loop_id` events |

## Tab Layout

```
┌──────────────────────────────────────────────────────────────┐
│ [Sessions sidebar]  │  Agent: sandbox-legion  Namespace: team1
│                     ├────────────────────────────────────────┤
│  ● Session A        │ [Chat] [Graph] [Stats] [Files]        │
│  ● Session B        ├────────────────────────────────────────┤
│  [New Session]      │           Tab content                  │
└─────────────────────┴────────────────────────────────────────┘
```

### Tab: Chat (default)

- WelcomeCard as first message (agent name, model, tools, example prompts)
- User/agent message bubbles
- Collapsed AgentLoopCards (final answer + "Reasoning" toggle)
- Streaming indicator
- Input area at bottom

### Tab: Graph

- Session DAG visualization (React Flow + dagre)
- Reuses `SessionGraphPage` from Session E
- Shows delegation tree, sub-agent relationships
- Embedded as panel, not separate page

### Tab: Stats

Four stat sections:

**Token Usage**
- Per-turn table: turn #, prompt tokens, completion tokens, total
- Cumulative totals at bottom
- Data from AgentLoop `budget.tokensUsed`

**Context Window**
- Progress bar showing % consumed vs model context limit
- Model limit from agent card (e.g., 128K for llama4-scout)

**Timing**
- Per-turn: TTFT, response time, total duration
- Session total duration
- Data from AgentLoop `budget.wallClockS`

**Tool Calls**
- Summary table: tool name, call count, success count, fail count
- Data from AgentLoop `steps[].toolCalls` and `steps[].toolResults`

### Tab: Files

- Reuses `FileBrowser` component (Session H)
- Scoped to session's contextId via `/workspace/{contextId}/`
- Tree view + file preview + breadcrumbs

### Extensibility

PatternFly Tabs supports dynamic tab addition. Future tabs:
- Logs (agent container logs)
- Traces (OpenTelemetry spans from Phoenix)
- HITL History (approve/deny decisions)

## WelcomeCard as Permanent First Message

Currently: WelcomeCard shows only when `messages.length === 0`.

Change: WelcomeCard renders as the first element in the messages container,
before all messages. It's always visible and scrolls with the chat.

```tsx
{/* Welcome card — permanent first message */}
<WelcomeCard agent={selectedAgent} model={agentCard?.model} ... />

{/* Messages */}
{messages.map(msg => <ChatBubble ... />)}
```

## Data Flow for Stats

**During streaming:**
- SSE events with `loop_id` → `updateLoop()` updates AgentLoop objects
- AgentLoop contains: `budget.tokensUsed`, `budget.wallClockS`, `steps[].toolCalls`
- Stats tab reads from the `agentLoops` Map state

**For historical sessions:**
- Backend endpoint: `GET /chat/{ns}/sessions/{contextId}/stats`
- Returns aggregated token/timing/tool data from stored task metadata
- Falls back to "Stats unavailable" if no metadata stored

## Components

| Component | Change |
|-----------|--------|
| `SandboxPage.tsx` | Add PatternFly Tabs wrapper, move chat to tab panel |
| `SessionStatsPanel.tsx` | **NEW** — token, context, timing, tool tables |
| `WelcomeCard` | Move from conditional empty state to permanent first message |
| `AgentLoopCard.tsx` | Already done — collapsed turns with reasoning toggle |
| `SessionGraphPage.tsx` | Embed as tab panel (remove standalone page route) |
| `FileBrowser.tsx` | Already supports contextId — embed as tab panel |

## Implementation Tasks

1. Add PatternFly Tabs to SandboxPage (Chat tab wraps existing content)
2. Make WelcomeCard permanent first message
3. Create SessionStatsPanel with 4 stat sections
4. Embed SessionGraphPage as Graph tab
5. Embed FileBrowser as Files tab with contextId
6. Add `&tab=` URL param persistence
7. Update tests for tabbed layout
