# Agent Loop UI — Expandable Reasoning Block Design

> **Date:** 2026-03-03
> **Author:** Session G
> **Status:** Draft
> **Depends on:** sandbox-reasoning-loop-design.md

## Problem

The current chat UI shows agent responses as flat messages — tool calls, results,
and final text are rendered as separate items with no visual grouping. Users can't
see the reasoning structure (plan → execute → reflect) or track resource usage
(tokens, model, duration).

## Design

### Collapsed View (default)

```
┌─ Agent ─────────────────────────────── llama-4-scout ── 12.3s ─┐
│  ⚡ 3 tools · 1.2k tokens · ✓ done                [▼ Details] │
│                                                                 │
│  ## RCA Report                                                  │
│  The CI failures are caused by...                               │
└─────────────────────────────────────────────────────────────────┘
```

Summary bar shows: tool count, total tokens, status, model name, wall time.
Final answer (`.sandbox-markdown`) always visible below summary.

### Expanded View (click Details)

```
┌─ Agent ─────────────────────────────── llama-4-scout ── 12.3s ─┐
│  ⚡ 3 tools · 1.2k tokens · ✓ done                [▲ Details] │
├────────────────────────────────────────────────────────────────┤
│  📋 Plan (iteration 1)                                         │
│    1. Fetch CI logs from PR #758                                │
│    2. Analyze failure patterns                                  │
│    3. Identify root cause                                       │
│                                                                 │
│  ── Step 1/3: Fetch CI logs ─── llama-4-scout ─── 847 tok ──  │
│    ▶ Tool Call: web_fetch(url=github.com/...)                   │
│    ▶ Result: "404 Not Found"                      [▶ expand]   │
│                                                                 │
│  ── Step 2/3: Search repo ──── llama-4-scout ─── 1,203 tok ── │
│    ▶ Tool Call: explore(query="CI failures")                    │
│    ▶ Result: "Found 3 test files..."              [▶ expand]   │
│                                                                 │
│  ── Step 3/3: Analyze ──────── llama-4-scout ─── 956 tok ───  │
│    ▶ Tool Call: shell(grep ERROR...)                             │
│    ▶ Result: "3 errors in auth module"            [▶ expand]   │
│                                                                 │
│  🔍 Reflection: Root cause identified → done                   │
├────────────────────────────────────────────────────────────────┤
│  ## RCA Report                                                  │
│  The CI failures are caused by...                               │
└─────────────────────────────────────────────────────────────────┘
```

Each step shows: step number, description, model used, token count.
Tool call/result blocks are expandable for full args/output.

### Live Streaming View

During execution, the card updates in real-time:

```
┌─ Agent ─────────────────────────── llama-4-scout ── 4.2s... ──┐
│  ⚡ 1 tool · 847 tok · ⏳ step 2/3...             [▼ Details] │
├────────────────────────────────────────────────────────────────┤
│  ── Step 2/3: Search repo ──── llama-4-scout ────────────────  │
│    ⏳ thinking...                                               │
└─────────────────────────────────────────────────────────────────┘
```

## Data Model

### Session Metadata (stored in DB)

```json
{
  "owner": "admin",
  "agent_name": "sandbox-legion",
  "model": "llama-4-scout-17b-16e-w4a16",
  "title": "Analyze CI failures for PR #758",
  "visibility": "private"
}
```

### SSE Event Types

Each event carries `loop_id` to group events from one agent turn:

```typescript
// Plan created/updated
{ type: "plan", loop_id: "L1", iteration: 0,
  steps: ["Fetch CI logs", "Analyze failures", "Identify root cause"] }

// Step started
{ type: "plan_step", loop_id: "L1", step: 0, total_steps: 3,
  description: "Fetching CI logs", model: "llama-4-scout" }

// Tool call (reuses existing format)
{ type: "tool_call", loop_id: "L1", step: 0,
  tools: [{ name: "web_fetch", args: { url: "..." } }],
  model: "llama-4-scout" }

// Tool result (reuses existing format)
{ type: "tool_result", loop_id: "L1", step: 0,
  name: "web_fetch", output: "404 Not Found" }

// Reflection
{ type: "reflection", loop_id: "L1", iteration: 0,
  assessment: "CI logs not accessible via web", decision: "continue",
  model: "llama-4-scout", tokens: { prompt: 1200, completion: 300 } }

// Budget update
{ type: "budget", loop_id: "L1",
  tokens_used: 2450, tokens_budget: 200000,
  iterations: 1, max_iterations: 10,
  wall_clock_s: 12.3, max_wall_clock_s: 3600 }

// Final response
{ type: "llm_response", loop_id: "L1",
  content: "## RCA Report\n...",
  model: "llama-4-scout", tokens: { prompt: 2000, completion: 800 } }
```

### Frontend State

```typescript
interface AgentLoop {
  id: string;                    // loop_id
  status: 'planning' | 'executing' | 'reflecting' | 'done' | 'failed';
  model: string;                 // primary model used
  plan: string[];                // plan steps
  currentStep: number;
  totalSteps: number;
  iteration: number;             // outer loop iteration
  steps: AgentLoopStep[];        // completed steps
  reflection?: string;           // latest reflection
  finalAnswer?: string;          // markdown response
  budget: {
    tokensUsed: number;
    tokensBudget: number;
    wallClockS: number;
    maxWallClockS: number;
  };
}

interface AgentLoopStep {
  index: number;
  description: string;
  model: string;                 // model used for this step
  tokens: { prompt: number; completion: number };
  toolCalls: ToolCallData[];     // existing type
  toolResults: ToolResultData[]; // existing type
  durationMs: number;
  status: 'pending' | 'running' | 'done' | 'failed';
}
```

## Component Hierarchy

```
AgentLoopCard (replaces ChatBubble for agent loop responses)
├── LoopSummaryBar
│   ├── StatusIcon (⏳/✓/✗)
│   ├── ToolCount ("3 tools")
│   ├── TokenCount ("1.2k tokens")
│   ├── ModelBadge ("llama-4-scout")
│   ├── Duration ("12.3s")
│   └── ExpandToggle (▼/▲ Details)
├── LoopDetail (only when expanded)
│   ├── PlanSection
│   │   └── PlanStep[] (numbered list)
│   ├── StepSection[] (per completed step)
│   │   ├── StepHeader (step N/M, model, tokens)
│   │   ├── ToolCallStep (existing, reused)
│   │   └── ToolResultStep (existing, reused)
│   └── ReflectionSection
│       └── ReflectionCard (assessment + decision)
└── FinalAnswer (.sandbox-markdown, always visible)
```

## Model Tracking

### Per-Session
- `metadata.model` stores the primary model used when session was created
- Visible in session sidebar and session detail header

### Per-LLM Call
- Each SSE event carries `model` field
- If user switches model mid-session, new events show the new model
- Step headers show which model executed that step
- Summary bar shows the most recent model

### Model Badge Colors
| Model | Color | Label |
|-------|-------|-------|
| llama-4-scout | Blue | "Llama 4" |
| mistral-small | Purple | "Mistral" |
| gpt-4o | Green | "GPT-4o" |
| claude-sonnet | Orange | "Claude" |

## Implementation Files

```
kagenti/ui-v2/src/
├── components/
│   ├── AgentLoopCard.tsx     # NEW — main wrapper
│   ├── LoopSummaryBar.tsx    # NEW — summary row
│   ├── LoopDetail.tsx        # NEW — expandable detail
│   └── ModelBadge.tsx        # NEW — colored model label
├── pages/
│   └── SandboxPage.tsx       # MODIFY — parse loop events, render AgentLoopCard
└── types/
    └── sandbox.ts            # MODIFY — add AgentLoop types
```

## Migration Path

1. **Phase 1** (current): Flat tool_call/tool_result messages (existing ToolCallStep)
2. **Phase 2**: Group events by `loop_id` into AgentLoopCard (backward compatible — old events without loop_id render as flat)
3. **Phase 3**: Full plan/reflect rendering with live budget counter

Old sessions (without loop_id) continue to render as flat messages.
New sessions (with loop_id) get the grouped expandable view.
