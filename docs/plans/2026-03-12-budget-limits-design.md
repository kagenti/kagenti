# Budget & Limits Design — Naming, Tracking, UI Exposure

> **Date:** 2026-03-12
> **Status:** Draft — needs review

## Problem

We have 3 different limiting mechanisms that are conflated in naming, UI display, and configuration:

1. **LangGraph recursion limit** — counts every graph node visit
2. **Budget iterations** — counts planner→executor→reflector cycles
3. **Plan steps** — items in the plan created by the planner

The UI shows "28 steps" (node visits), the wizard says "Max Iterations: 200", and the recursion limit silently kills the graph at 50. Users can't tell what's actually limiting their agent.

## Terminology

| Term | What it counts | Who increments | Where checked | Current default |
|------|---------------|----------------|---------------|-----------------|
| **Plan steps** | Items in the plan array | Planner node | UI only (display) | N/A (depends on task) |
| **Reasoning cycles** | planner→executor→reflector rounds | `budget.tick_iteration()` in reflector | Reflector: `if iteration >= max_iterations` | 200 |
| **Tool calls per step** | Tool invocations within one executor step | Executor tool loop counter | Executor: `if tool_call_count >= max` | 10 (env: 20) |
| **Graph node visits** | Every node entry (planner, executor, tools, reflector, reporter) | LangGraph runtime | LangGraph: `GraphRecursionError` | 50 → **should be 2000** |
| **Total tokens** | prompt + completion across all LLM calls | `budget.add_tokens()` after each LLM call | Reflector + Executor: `budget.exceeded` | 1,000,000 |
| **Wall clock** | Real time since message received | `budget._start_time` monotonic clock | Reflector + Executor: `budget.exceeded` | 600s |

## Proposal: Rename for Clarity

### Agent-side (budget.py + env vars)

| Current name | Proposed name | Env var | Default |
|-------------|--------------|---------|---------|
| `max_iterations` | `max_reasoning_cycles` | `SANDBOX_MAX_REASONING_CYCLES` | 200 |
| `max_tool_calls_per_step` | `max_tool_calls_per_step` | `SANDBOX_MAX_TOOL_CALLS_PER_STEP` | 20 |
| `max_tokens` | `max_tokens` | `SANDBOX_MAX_TOKENS` | 1,000,000 |
| `max_wall_clock_s` | `max_wall_clock_s` | `SANDBOX_MAX_WALL_CLOCK_S` | 600 |
| `recursion_limit` | `graph_node_limit` | `SANDBOX_GRAPH_NODE_LIMIT` | 2000 |
| `hitl_interval` | `hitl_interval` | `SANDBOX_HITL_INTERVAL` | 50 |

### UI Wizard sections

**Session Limits** (total budget for one user message):
- Max Tokens: 1,000,000 — "Total prompt + completion tokens across all LLM calls"
- Max Wall Clock: 600s — "Maximum real-time seconds per message"

**Reasoning Limits** (the planner→executor→reflector loop):
- Max Reasoning Cycles: 200 — "Maximum planner→executor→reflector rounds"
- HITL Check-in: 50 — "Pause for human approval after this many cycles"
- Graph Node Limit: 2000 — "Internal graph traversal limit (advanced)"

**Step Limits** (per plan step execution):
- Tool Calls Per Step: 20 — "Maximum tool invocations within a single plan step"

## What the UI Should Show

### AgentLoopCard toggle
```
▼ 8 plan steps · 3 cycles · 12 tool calls · 9.9K tokens
```
- **8 plan steps** = `loop.plan.length` or `loop.totalSteps`
- **3 cycles** = `loop.iteration` (reasoning cycles completed)
- **12 tool calls** = sum of `step.toolCalls.length` across all steps
- **9.9K tokens** = sum of prompt + completion tokens

### LoopSummaryBar
Same info in compact form.

### StepSection labels
- Planner: `"Plan (8 steps)"` or `"Replan (iteration 2): 5 steps"`
- Executor: `"Step 3/8: List CI failures"` (plan step number / total)
- Reflector: `"Reflection [continue]"` or `"Reflection [replan]"`
- Reporter: `"Final answer"`

### Stats tab — Budget section
```
Budget
  Tokens:     45,230 / 1,000,000  [====----] 4.5%
  Wall Clock: 45s / 600s          [=-------] 7.5%
  Cycles:     3 / 200             [--------] 1.5%
  Tool Calls: 12 (across 8 plan steps)
```

## Event Data Requirements

### executor_step event MUST include:
```json
{
  "type": "executor_step",
  "plan_step": 2,        // 0-based index into plan array
  "iteration": 3,        // current reasoning cycle
  "step": 15,            // global node visit counter (internal)
  "total_steps": 8,      // plan length
  "description": "List CI failures"
}
```

### reflector_decision event MUST include:
```json
{
  "type": "reflector_decision",
  "plan_step": 2,
  "iteration": 3,
  "decision": "continue"
}
```

### budget_update event:
```json
{
  "type": "budget_update",
  "tokens_used": 45230,
  "tokens_budget": 1000000,
  "wall_clock_s": 45,
  "max_wall_clock_s": 600,
  "iterations_used": 3,
  "max_iterations": 200,
  "plan_steps_completed": 2,
  "plan_steps_total": 8
}
```

## Relationship: recursion_limit vs max_reasoning_cycles

```
One reasoning cycle ≈ 5-15 graph node visits:
  planner(1) + [executor(1) + tools(1)] × N_tool_calls + reflector(1)

For max_reasoning_cycles = 200:
  graph_node_limit should be ≥ 200 × 10 = 2000

Rule of thumb: graph_node_limit = max_reasoning_cycles × 10
```

The graph_node_limit is a safety net, not a user-facing limit. Users think in reasoning cycles (how many times can the agent plan/execute/reflect). The graph_node_limit prevents infinite loops if something goes wrong.

## Migration

1. Keep old env var names as aliases (backward compat)
2. New names take precedence
3. Wizard shows new names
4. Agent logs use new names

## Files to Change

| File | Change |
|------|--------|
| `budget.py` | Rename fields, add aliases, bump defaults |
| `event_serializer.py` | Ensure plan_step + iteration in all events |
| `reasoning.py` | Use new field names |
| `SandboxWizard.tsx` | Rename sections, update descriptions |
| `sandbox_deploy.py` | New env var names (keep aliases) |
| `loopBuilder.ts` | Read plan_step, iteration consistently |
| `LoopDetail.tsx` | Step labels use plan step + iteration |
| `AgentLoopCard.tsx` | Toggle shows plan steps + cycles + tools |
| `LoopSummaryBar.tsx` | Compact summary |
| `SessionStatsPanel.tsx` | Budget section with cycles |
| `agentLoop.ts` | Add iteration to AgentLoop type |
