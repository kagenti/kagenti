# Session Eta (η) — Chat View Modes: Simple / Advanced / Graph

> **Date:** 2026-03-14
> **Cluster:** sbox42
> **Worktrees:** `.worktrees/sandbox-agent` (kagenti), `.worktrees/agent-examples` (agent code)
> **Branch:** `feat/sandbox-agent`
> **Prior Art:** `2026-03-05-tabbed-session-view-design.md` (Graph tab spec with React Flow)
> **Depends On:** session-alpha4 (thinking iterations, PlanStore, cancel button)

## Goal

Add a **floating view mode bar** to the chat area that switches between three
rendering modes — Simple, Advanced, and Graph — all driven from the same
`AgentLoop` data source. No data changes needed — this is purely a rendering
adapter layer.

## View Modes

### 1. Simple View (new)

A clean, user-friendly view that hides the reasoning internals. Shows:
- User message
- Final answer (markdown)
- Collapsed "Agent worked for X seconds · N steps · M tool calls" summary bar
- Click summary → expands to show plan steps as a numbered checklist with ✓/✗

**Does NOT show:** thinking iterations, micro-reasoning, tool call/result details,
prompt inspector, node visit badges, token counts, budget bar.

**Target audience:** End users who just want the answer, not the reasoning trace.

### 2. Advanced View (current — default)

The current `AgentLoopCard` + `LoopDetail` rendering with:
- Collapsible step sections (node visit badges, tool calls, results)
- Thinking iterations (purple `ThinkingBlock`)
- Micro-reasoning (blue, with "N thinking" badge)
- Prompt inspector buttons
- Budget bar
- Plan with step status

This is the existing rendering — no changes needed except wiring to the view switcher.

### 3. Graph View (new)

Visual DAG of the agent's execution flow using React Flow + dagre layout:
- **Nodes:** planner, executor (per step), reflector, reporter, tools
- **Edges:** directed arrows showing the execution flow
- **Node content:** step description, status badge (done/running/failed), token count
- **Thinking sub-nodes:** small nodes inside executor showing thinking iterations
- **Tool call nodes:** connected to executor, showing tool name + status icon
- **Replan edges:** dotted lines from reflector back to planner (with "replan" label)
- **Live updates:** nodes animate (pulse) while executing, edges draw as events arrive

**Prior art:** `SessionGraphPage` component (from tabbed-session-view-design.md) used
React Flow with dagre. This view reuses that approach but scoped to a single
`AgentLoop` instead of the full session.

## Architecture

### Data Flow (Rendering Adapter Pattern)

```
AgentLoop (Map<string, AgentLoop>)
  │
  ├── SimpleRenderer  → <SimpleLoopCard loop={loop} />
  ├── AdvancedRenderer → <AgentLoopCard loop={loop} />  (existing)
  └── GraphRenderer   → <GraphLoopView loop={loop} />
```

All three renderers consume the same `AgentLoop` data structure. The view mode
is a simple state variable that selects which renderer to use. No data
transformation needed — each renderer picks what it needs from the AgentLoop.

### Floating View Mode Bar

```
┌──────────────────────────────────────────────┐
│  [Simple]  [Advanced]  [Graph]     float: right, top of chat area
└──────────────────────────────────────────────┘
```

- PatternFly `ToggleGroup` with `ToggleGroupItem` for each mode
- Positioned as a floating bar in the top-right of the chat area
- Persisted via URL search param `&view=simple|advanced|graph`
- Default: `advanced` (current behavior, no regression)

### Component Structure

```
SandboxPage.tsx
  ├── FloatingViewBar (ToggleGroup)
  │     state: viewMode: 'simple' | 'advanced' | 'graph'
  │
  ├── {viewMode === 'simple' && <SimpleLoopCard loop={loop} />}
  ├── {viewMode === 'advanced' && <AgentLoopCard loop={loop} />}
  └── {viewMode === 'graph' && <GraphLoopView loop={loop} />}
```

### New Files

| File | Purpose |
|------|---------|
| `components/SimpleLoopCard.tsx` | Simple view renderer |
| `components/GraphLoopView.tsx` | Graph view renderer (React Flow) |
| `components/FloatingViewBar.tsx` | View mode toggle bar |

### Existing Files to Modify

| File | Change |
|------|--------|
| `pages/SandboxPage.tsx` | Add FloatingViewBar, conditional rendering |
| `package.json` | Add `reactflow` dependency (if not already present) |

## SimpleLoopCard Design

```tsx
const SimpleLoopCard: React.FC<{ loop: AgentLoop }> = ({ loop }) => {
  const [expanded, setExpanded] = useState(false);
  const totalSteps = loop.plan.length;
  const doneSteps = loop.steps.filter(s => s.status === 'done').length;
  const totalTokens = loop.steps.reduce((sum, s) => sum + s.tokens.prompt + s.tokens.completion, 0);
  const totalTools = loop.steps.reduce((sum, s) => sum + s.toolCalls.length, 0);

  return (
    <div className="simple-loop-card">
      {/* User message */}
      {loop.userMessage && <div className="user-msg">{loop.userMessage}</div>}

      {/* Final answer (full markdown) */}
      {loop.finalAnswer && <ReactMarkdown>{loop.finalAnswer}</ReactMarkdown>}

      {/* Summary bar (always visible) */}
      <div className="summary-bar" onClick={() => setExpanded(!expanded)}>
        {expanded ? '▼' : '▶'}
        Agent completed in {doneSteps}/{totalSteps} steps
        · {totalTools} tool calls
        · {totalTokens.toLocaleString()} tokens
      </div>

      {/* Expanded: plan checklist */}
      {expanded && (
        <ol className="plan-checklist">
          {loop.plan.map((step, i) => (
            <li key={i} className={stepStatus(loop, i)}>
              {stepIcon(loop, i)} {step}
            </li>
          ))}
        </ol>
      )}
    </div>
  );
};
```

## GraphLoopView Design

```tsx
import ReactFlow, { type Node, type Edge } from 'reactflow';
import dagre from 'dagre';

const GraphLoopView: React.FC<{ loop: AgentLoop }> = ({ loop }) => {
  // Build nodes from loop.steps (grouped by eventType)
  const nodes: Node[] = [];
  const edges: Edge[] = [];

  // Planner node
  nodes.push({ id: 'planner', data: { label: 'Planner', plan: loop.plan }, ... });

  // Executor nodes (one per plan step)
  loop.steps.filter(s => inferNodeType(s) === 'executor').forEach((step, i) => {
    const stepId = `executor-${i}`;
    nodes.push({
      id: stepId,
      data: {
        label: `Step ${i+1}`,
        description: step.description,
        status: step.status,
        thinkingCount: (step.thinkings || []).length,
        toolCount: step.toolCalls.length,
      },
    });
    // Edge: planner → executor (or previous reflector → executor)
    edges.push({ id: `e-to-${stepId}`, source: i === 0 ? 'planner' : `reflector-${i-1}`, target: stepId });

    // Tool nodes (children of executor)
    step.toolCalls.forEach((tc, j) => {
      const toolId = `tool-${i}-${j}`;
      nodes.push({ id: toolId, data: { label: tc.name, status: step.toolResults[j]?.status } });
      edges.push({ id: `e-${stepId}-${toolId}`, source: stepId, target: toolId });
    });

    // Thinking sub-nodes
    (step.thinkings || []).forEach((t, j) => {
      const thinkId = `think-${i}-${j}`;
      nodes.push({ id: thinkId, data: { label: `Think ${j+1}`, reasoning: t.reasoning?.substring(0, 50) } });
    });

    // Reflector node after each step
    const refId = `reflector-${i}`;
    nodes.push({ id: refId, data: { label: 'Reflector', decision: loop.reflectorDecision } });
    edges.push({ id: `e-${stepId}-${refId}`, source: stepId, target: refId });
  });

  // Reporter node
  nodes.push({ id: 'reporter', data: { label: 'Reporter' } });

  // Layout with dagre
  const { nodes: layoutNodes, edges: layoutEdges } = applyDagreLayout(nodes, edges);

  return <ReactFlow nodes={layoutNodes} edges={layoutEdges} fitView />;
};
```

## Data Source: AgentLoop

All three views consume the same `AgentLoop` from `agentLoops` state in SandboxPage.
Key fields each view uses:

| Field | Simple | Advanced | Graph |
|-------|--------|----------|-------|
| `loop.userMessage` | ✓ | ✓ | — |
| `loop.finalAnswer` | ✓ | ✓ | — |
| `loop.plan` | ✓ checklist | ✓ numbered | ✓ planner node |
| `loop.steps` | count only | full detail | DAG nodes |
| `loop.steps[].thinkings` | — | ThinkingBlock | sub-nodes |
| `loop.steps[].microReasonings` | — | full render | — |
| `loop.steps[].toolCalls` | count | full render | tool nodes |
| `loop.steps[].toolResults` | — | full render | status icons |
| `loop.budget` | — | budget bar | — |
| `loop.status` | icon | border color | node animation |
| `loop.replans` | — | replan section | dotted edges |

## Implementation Plan

### Phase 1: FloatingViewBar + SimpleLoopCard (~1 hour)
1. Create `FloatingViewBar.tsx` — ToggleGroup with 3 modes
2. Create `SimpleLoopCard.tsx` — clean summary view
3. Wire into `SandboxPage.tsx` — conditional rendering
4. URL param persistence (`&view=simple|advanced|graph`)

### Phase 2: GraphLoopView (~2 hours)
1. Add `reactflow` + `dagre` dependencies
2. Create `GraphLoopView.tsx` — DAG from AgentLoop
3. Custom node components (executor, planner, tool, thinking)
4. Live updates: re-layout on new events
5. Node click → opens detail panel (reuses LoopDetail)

### Phase 3: Polish (~30 min)
1. Keyboard shortcuts (1/2/3 for view modes)
2. Smooth transitions between views
3. View mode remembered per session

## Key Decisions

1. **No data transformation** — renderers read AgentLoop directly
2. **Default: advanced** — no regression for existing users
3. **Graph view is read-only** — no drag/edit of the DAG (display only)
4. **React Flow** reused from prior SessionGraphPage work
5. **Floating bar, not tab** — stays visible above the chat, not part of the tab bar

## Dependencies

```json
{
  "reactflow": "^11.x",
  "@dagrejs/dagre": "^1.x"
}
```

Check if already in `package.json` — the tabbed-session-view design may have added them.

## Files to Read Before Starting

```
# Current rendering (Advanced view)
kagenti/ui-v2/src/components/AgentLoopCard.tsx     # Card wrapper, border color, status
kagenti/ui-v2/src/components/LoopDetail.tsx        # Step sections, tool calls, thinking blocks
kagenti/ui-v2/src/types/agentLoop.ts               # AgentLoop, AgentLoopStep types
kagenti/ui-v2/src/utils/loopBuilder.ts             # applyLoopEvent, buildAgentLoops
kagenti/ui-v2/src/pages/SandboxPage.tsx            # agentLoops state, streaming, rendering

# Prior graph work
docs/plans/2026-03-05-tabbed-session-view-design.md  # Graph tab spec
```
