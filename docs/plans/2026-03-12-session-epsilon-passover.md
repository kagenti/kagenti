# Session Epsilon Passover — Advanced Features

> **Date:** 2026-03-12
> **From:** Session Delta
> **Cluster:** sbox42
> **Worktrees:** `.worktrees/sandbox-agent` (kagenti), `.worktrees/agent-examples` (agent code)
> **Branch:** `feat/sandbox-agent` (both repos)

## Prerequisites

Beta, Gamma, and Delta should be complete before starting Epsilon:
- Beta: LLM budget proxy + DB schemas
- Gamma: UI polish (step naming, event ordering, page load)
- Delta: Infrastructure (mesh labels, OTEL, ghost sessions, crash recovery)

## What Session Epsilon Should Do

### Priority 0: Visualizations Tab (#22)

Session graph DAG visualization using React Flow:

- Implement `SessionGraphPage.tsx` at `/sandbox/graph`
- Backend endpoint: `GET /api/v1/sandbox/{namespace}/sessions/{context_id}/graph`
- Dagre layout (top-to-bottom), custom nodes with status badges
- Edge styles per delegation mode (in-process, shared-pvc, isolated, sidecar)
- Live updates via SSE (session_created, session_status_changed)

See [Visualizations Design](./2026-03-10-visualizations-design.md) for full spec.

### Priority 1: Message Queue + Cancel (#21)

Queue user messages while the agent is in a reasoning loop:

- Messages sent during a loop should be queued and delivered after loop completes
- Cancel button: sends interrupt signal to stop the current loop
- UI shows queued message count and cancel affordance
- Backend needs an endpoint to cancel/interrupt a running task

### Priority 2: Per-Session UID Isolation (#25)

Each session should run with a unique UID to prevent filesystem cross-contamination:

- Current stopgap: `fsGroup` on the pod
- Target: per-session UID mapping (requires user namespace support or init container chown)
- Evaluate feasibility on OpenShift (restricted SCC constraints)

### Priority 3: Context Window Management UI (#30)

Token-based context windowing (30K cap) is implemented but the UI is confusing:

- Show clear context window usage indicator (used / max tokens)
- Explain when messages are being trimmed
- Consider showing a "context pressure" indicator
- Align UI metric with actual token count (currently shows wrong number)

### Priority 4: Agent Redeploy E2E Test (#24)

Test the full reconfigure + redeploy flow:

- Wizard reconfigure (change security tier, model, etc.)
- Verify sessions survive agent redeploy
- Test that new config takes effect on next session
- Playwright test covering the full flow

## Items from Master Tracking

| # | Item | Origin | Notes |
|---|------|--------|-------|
| 22 | Visualizations tab | Y | Design doc at `2026-03-10-visualizations-design.md` |
| 21 | Message queue + cancel button | Y | Queue messages during loop |
| 25 | Per-session UID isolation | Y | fsGroup is stopgap |
| 30 | Context window management | Y | 30K cap works, UI confusing |
| 24 | Agent redeploy E2E test | Y | Test reconfigure, session continuation |
