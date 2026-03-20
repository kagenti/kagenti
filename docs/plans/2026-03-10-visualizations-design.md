# Agent Loop Visualizations — Design

> **Date:** 2026-03-10
> **Status:** Draft
> **Linked from:** [Session X Passover](2026-03-10-session-X-passover.md) item #12

## Overview

New "Visualizations" tab in session detail showing multiple visualization examples for agent loops. Phase 1 is about exploring visualization types — not optimized, just API-streamed computation from DB returning data for the client to render.

## Data Source

All visualizations read from the same data:
- **Session history** (messages, tool calls, tool results)
- **Loop events** (planner_output, executor_step, tool_call, tool_result, reflector_decision, reporter_output)
- **Token usage** (prompt_tokens, completion_tokens per step)
- **Timing** (event timestamps, step durations)

Backend endpoint: `GET /sandbox/{ns}/sessions/{contextId}/visualizations`
Returns pre-computed visualization data from the DB. Client renders with lightweight chart libraries.

## Visualization Examples (stacked vertically in tab)

### 1. Graph Flow Diagram
Interactive Mermaid/D3 graph showing the actual execution path:

```
router → planner → executor → shell("gh workflow list") → executor → reflector → executor → shell("gh run view") → reflector → reporter
```

- Nodes colored by type (planner=blue, executor=orange, tools=grey, reflector=purple)
- Edges labeled with decision (execute/replan/done)
- Failed tool calls highlighted in red
- Click a node to see its input/output

### 2. Timeline / Gantt Chart
Horizontal timeline showing:
- Each step as a bar (width = duration)
- Tool calls as sub-bars within executor steps
- Reflector decisions as markers
- Token usage overlaid as area chart
- Wall clock time on X axis

### 3. Token Usage Waterfall
Stacked bar chart per step:
- Prompt tokens (blue) vs completion tokens (orange)
- Cumulative line showing budget consumption
- Budget limit shown as horizontal line
- Helps identify which steps are expensive

### 4. Plan Evolution View
Shows how the plan changed across replans:
- Original plan as a column of steps
- Each replan as a new column
- Lines connecting steps that stayed the same
- Deleted steps crossed out, new steps highlighted
- Step status (done/failed/skipped) color-coded

### 5. Multi-Agent Delegation Tree
For sessions with `delegate` tool calls:
- Tree diagram: parent session → child sessions
- Each node shows: agent name, status, duration
- Expand to see the child's own loop visualization
- Helps understand orchestration patterns

### 6. Tool Call Heatmap
Grid showing tool usage patterns:
- Rows = plan steps, Columns = tool types (shell, file_read, grep, etc.)
- Cell color = call count (white→blue scale)
- Red cells = failed calls
- Shows which tools are used most and where failures cluster

## API Shape

```typescript
// GET /sandbox/{ns}/sessions/{contextId}/visualizations
interface VisualizationData {
  graph: {
    nodes: Array<{ id: string; type: string; label: string; status: string }>;
    edges: Array<{ from: string; to: string; label?: string }>;
  };
  timeline: Array<{
    step: number;
    node: string;
    startMs: number;
    durationMs: number;
    toolCalls: Array<{ name: string; startMs: number; durationMs: number; status: string }>;
  }>;
  tokens: Array<{
    step: number;
    prompt: number;
    completion: number;
    cumulative: number;
    budgetLimit: number;
  }>;
  planEvolution: Array<{
    iteration: number;
    steps: Array<{ text: string; status: string }>;
  }>;
  delegations: Array<{
    contextId: string;
    agentName: string;
    status: string;
    durationMs: number;
    children: Array</* recursive */>;
  }>;
  toolHeatmap: {
    steps: string[];
    tools: string[];
    counts: number[][];  // steps x tools
    failures: number[][]; // steps x tools
  };
}
```

## Frontend Rendering

Use lightweight libraries:
- **Graph**: Mermaid.js (already in project for markdown) or react-flow
- **Timeline**: Simple HTML/CSS bars (no library needed for MVP)
- **Charts**: recharts (already a common React choice) or plain SVG
- **Heatmap**: CSS grid with color interpolation

## Phase 1 Scope

- Backend computes all data from DB on request (not optimized)
- Client renders all 6 visualizations stacked vertically
- No interactivity beyond expand/collapse
- No real-time streaming (snapshot of completed session)
- No caching

## Phase 2 (Future)

- Real-time visualization during streaming (SSE updates)
- Interactive graph (click to inspect)
- Comparison view (two sessions side by side)
- Aggregated views across sessions (average token usage, common failure patterns)
