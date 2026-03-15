# Session Beta (2026-03-13) Passover — Streaming Architecture + Fixes

> **Date:** 2026-03-13
> **Cluster:** sbox42 (KUBECONFIG=/tmp/kagenti/sbox42-kubeconfig)
> **Worktrees:** `.worktrees/sandbox-agent` (kagenti), `.worktrees/agent-examples` (agent code)
> **Branch:** `feat/sandbox-agent` (both repos)
> **Previous:** session-alpha1-passover.md

## Session Summary

This session (continuation of Alpha-1) implemented:
1. `respond_to_user` escape tool for Llama 4 Scout planner/reflector
2. STDERR false positive fix (exit_code check, not STDERR prefix)
3. Prompt extraction to `prompts.py` (-190 lines from reasoning.py)
4. Step counter fix (tracks plan step, not auto-increment)
5. Structured OTel logging (26 logger calls with `extra={}`)
6. Incremental persist threshold (5→2)
7. Deep analysis of SSE streaming disconnect + recovery failure

## What Was Committed

### Agent (agent-examples repo)

| Commit | Change |
|--------|--------|
| b9cefa2 | respond_to_user escape tool + STDERR false positive fix |
| d80b6b4 | Step counter from plan state + structured OTel logging |

### Backend (kagenti repo, sandbox-agent worktree)

| Commit | Change |
|--------|--------|
| (pending push) | `_INCREMENTAL_PERSIST_THRESHOLD` from 5 to 2 |

## Key Finding: SSE Stream Disconnect Pattern

### The Problem

```
Timeline for EVERY session:
11:01:30 — Backend receives tool_call event
11:01:33 — Backend receives tool_result event
11:01:33 — Stream finally block fires (0ms later!)
           → 9 events persisted, agent still running
           → Recovery polls agent, agent stuck in "working"
           → Events 10-188 LOST
```

### Root Cause Chain

```
Playwright test reads SSE events
→ Gets enough data (tool_call + tool_result)
→ Navigates to next test step (page.goto or pushState)
→ Browser aborts the fetch() SSE connection
→ Backend's async generator receives GeneratorExit
→ finally block fires, persists accumulated events
→ Agent continues running independently (no listener)
→ Agent emits events 10-188 to dead SSE pipe
→ subscribe/resubscribe only gets FUTURE events (empty)
→ Recovery polls tasks/get but task is still "working"
→ Recovery gives up after 10 attempts (5 min)
→ Events are permanently lost
```

### Why Subscribe Doesn't Get Events

The A2A `tasks/resubscribe` sends only **new** status-update messages going forward.
Events already emitted during the original stream are gone. The agent's event queue
is drained — resubscribe connects to an empty pipe.

---

## Streaming Architecture Brainstorm

### Current Architecture (broken)

```
┌─────────┐    SSE     ┌─────────┐    SSE    ┌─────────┐
│ Browser │◄──────────│ Backend │◄──────────│  Agent  │
│  (UI)   │  fetch()  │(FastAPI)│ httpx.get │(LangGrp)│
└─────────┘           └────┬────┘           └─────────┘
                           │
                     finally block
                           │
                    ┌──────▼──────┐
                    │  PostgreSQL  │
                    │ tasks.meta   │
                    │ {loop_events}│
                    └─────────────┘

Problems:
1. SSE is fire-and-forget — missed events are gone
2. Backend accumulates events in memory, writes on disconnect
3. Recovery via tasks/get only has message-level history
4. No event replay mechanism
5. Single listener (browser) — no multi-user visibility
```

### Option A: Agent-Side Event Persistence (recommended short-term)

```
┌─────────┐    SSE     ┌─────────┐    SSE    ┌─────────┐
│ Browser │◄──────────│ Backend │◄──────────│  Agent  │
│  (UI)   │           │         │           │         │
└─────────┘           └────┬────┘           └────┬────┘
                           │                     │
                           │               ┌─────▼─────┐
                    ┌──────▼──────┐        │ Agent DB   │
                    │  PostgreSQL  │◄───────│ events tbl │
                    │ tasks.meta   │ poll   │ (append)   │
                    └─────────────┘        └───────────┘

Agent writes each event to its own DB table as it emits.
Backend recovery reads events from agent DB instead of SSE.
Subscribe replays from agent DB + live stream.

Pros:
- Events never lost (written before emitted)
- Recovery reads complete event history
- Simple — agent already has DB access (checkpointer)
- No protocol changes needed

Cons:
- Agent needs schema migration for events table
- Dual-write (DB + SSE) adds latency per event
- Still SSE-based (fragile connections)
```

### Option B: WebSocket for Multi-User Communication

```
┌─────────┐           ┌─────────┐           ┌─────────┐
│Browser 1│◄──WS──────│         │    SSE    │         │
│ (admin) │           │ Backend │◄──────────│  Agent  │
│Browser 2│◄──WS──────│  + WS   │           │         │
│ (viewer)│           │  Hub    │           │         │
└─────────┘           └────┬────┘           └─────────┘
                           │
                    ┌──────▼──────┐
                    │  PostgreSQL  │
                    │ events tbl   │
                    └─────────────┘

Backend receives SSE from agent.
Backend writes each event to DB immediately.
Backend broadcasts each event to all connected WebSocket clients.
Page reload: fetch events from DB (history), then connect WS for live.

Pros:
- Multi-user: admin sends message, viewers see live progress
- Bidirectional: viewers can send input (HITL approval)
- WebSocket auto-reconnects (built into browser API)
- Events in DB are the source of truth (never lost)
- History on reload = DB query, live = WS subscription

Cons:
- WebSocket server adds complexity (connection management, rooms)
- Need session-scoped rooms (one per context_id)
- WS connection lifecycle management in React
- Still SSE between backend and agent (could be fragile)
```

### Option C: gRPC A2A Between Backend and Agent

```
┌─────────┐           ┌─────────┐           ┌─────────┐
│Browser 1│◄──WS──────│         │   gRPC    │         │
│Browser 2│◄──WS──────│ Backend │◄──────────│  Agent  │
│         │           │  + WS   │  stream   │ + gRPC  │
└─────────┘           └────┬────┘           └─────────┘
                           │
                    ┌──────▼──────┐
                    │  PostgreSQL  │
                    │ events tbl   │
                    └─────────────┘

Backend ↔ Agent uses gRPC bidirectional streaming.
Backend ↔ Browser uses WebSocket.

gRPC advantages over SSE:
- Binary protocol (protobuf) — smaller payloads (~30-50% vs JSON)
- HTTP/2 multiplexing — multiple streams on single connection
- Built-in flow control + backpressure
- Connection health monitoring (keepalive, max idle)
- Automatic reconnection with exponential backoff
- Typed schemas (protobuf) — no JSON parsing errors

Could we send protobuf to UI directly?
- YES via grpc-web: browser can speak gRPC via grpc-web proxy
- BUT: protobuf in browser needs codegen (protoc → TypeScript)
- Trade-off: smaller payloads vs build complexity
- Recommendation: gRPC between backend↔agent, WS+JSON to browser

Protobuf message sizes vs JSON:
- A tool_call event: JSON ~500 bytes, protobuf ~150 bytes (70% smaller)
- A tool_result event: JSON ~2KB, protobuf ~700 bytes (65% smaller)
- Per session (200 events): JSON ~100KB, protobuf ~30KB
- The savings are significant for high-volume sessions

gRPC streaming types:
- Server streaming (agent→backend): like SSE but with backpressure
- Bidirectional (agent↔backend): enables backend→agent commands
  (e.g., "cancel task", "provide HITL input", "adjust budget")

A2A protocol compatibility:
- A2A spec is JSON-RPC over HTTP/SSE — gRPC would be a custom transport
- Could implement A2A-over-gRPC as a transport layer under the A2A interface
- Agents still expose HTTP A2A for external callers, gRPC for internal

Cons:
- gRPC server + client in both backend and agent
- Protobuf schema maintenance
- A2A protocol deviation (custom transport)
- Debugging harder (binary wire format vs readable JSON/SSE)
```

### Recommended Path

```
Phase 1 (now):     Fix Playwright test SSE disconnect
                   Backend persists events to DB on receipt (not finally)
                   → Events never lost, history loads from DB

Phase 2 (next):    WebSocket hub for multi-user live view
                   DB-backed event store with cursor-based replay
                   → Multiple users see same session live

Phase 3 (future):  gRPC between backend and agent
                   Protobuf events with typed schemas
                   → Reliable streaming, smaller payloads, backpressure
```

---

## Playwright Test Fix

The Playwright test disconnects SSE because it navigates away while the stream is
still open. Fix: wait for the agent loop to complete (look for `reporter_output`
or the loop card's "done" state) before navigating.

```typescript
// BEFORE (disconnects SSE):
await expect(agentOutput.first()).toBeVisible({ timeout: 180000 });
// ... immediately navigates away

// AFTER (waits for completion):
// Wait for loop to finish — reporter_output or done state
const doneIndicator = page.locator('[data-testid="agent-loop-card"] [data-status="done"]')
  .or(page.locator('.sandbox-markdown'))  // final answer renders as markdown
  .or(page.locator('textarea[aria-label="Message input"]:not([disabled])'));  // input re-enabled
await expect(doneIndicator.first()).toBeVisible({ timeout: 300000 }); // 5 min
await page.waitForTimeout(5000); // let final events flush
```

---

## Agent Behavior Issues (from session c7f4f3e9)

### 1. gh CLI flag hallucination

Agent used `gh run list --head-ref` which doesn't exist. The correct flag is `--branch`.

**Fix:** Add `gh run list` valid flags to the executor prompt in `prompts.py`:
```
## gh run list valid flags
- `--branch <branch>` — filter by branch name
- `--status <status>` — filter by status (queued, in_progress, completed, failure, etc.)
- `--event <event>` — filter by event type (push, pull_request, etc.)
- `--limit <n>` — max results
- Do NOT use `--head-ref` (invalid), use `--branch` instead.
```

### 2. Wasted steps (pwd, cd, ls)

The executor wastes tool calls on navigation commands that have no effect
(bare `cd`) or produce no useful information (`pwd`). The step_selector
produces briefs that encourage this.

**Fix:** Add to executor prompt:
```
NEVER waste tool calls on:
- `pwd` — you already know you're in /workspace
- `cd <dir>` alone — has no effect, chain with &&
- `ls` without a purpose — only ls if you need to verify something
```

### 3. Reflector marks steps "done" prematurely

Reflector said "done" after `pwd` succeeded, even though the step's goal
(list CI failures) wasn't achieved. The reflector needs to verify the step's
stated goal, not just check if the tool call succeeded.

---

## How to Continue

```bash
# Cluster
export KUBECONFIG=/tmp/kagenti/sbox42-kubeconfig
export LOG_DIR=/tmp/kagenti/tdd/ui-sbox42
mkdir -p $LOG_DIR

# Fix 1: Update executor prompt in prompts.py (gh CLI flags + no wasted calls)
# Fix 2: Fix Playwright test to wait for loop completion before navigating
# Fix 3: Implement DB-backed event persistence in backend SSE handler

# Build + deploy
cd .worktrees/agent-examples
# edit prompts.py
git add -u && git commit -s -m "fix(agent): executor prompt — correct gh flags" && git push
oc -n team1 start-build sandbox-agent

# Test
cd .worktrees/sandbox-agent/kagenti/ui-v2
RCA_SKIP_DEPLOY=1 RCA_AGENT_NAME=rca-agent-emptydir \
  npx playwright test e2e/agent-rca-workflow.spec.ts --reporter=list --timeout=600000
```
