# Next Session Passover — Step Naming, Prompt Context, Test Fixes

> **Date:** 2026-03-12
> **Cluster:** sbox42 (KUBECONFIG=~/clusters/hcp/kagenti-team-sbox42/auth/kubeconfig)
> **Worktrees:** `.worktrees/sandbox-agent` (kagenti), `.worktrees/agent-examples` (agent code)

## What's Working Now

All the foundational infrastructure is solid:
- Budget enforcement (add_tokens, exceeded checks in executor+reflector)
- budget_update events emitted after every node
- MergingDatabaseTaskStore preserves backend metadata
- Recovery with correct A2A task ID + merge (not replace)
- tasks/resubscribe SSE reconnection
- Subscribe endpoint for page reload reconnection
- micro_reasoning after every tool call with call_id pairing
- PromptInspector (portal, fullscreen, ESC close, inline expand + Fullscreen button)
- Prompt data in all node types (50KB limit)
- Unique step index per node invocation
- Tool result status icons (success/error)
- Streaming indicator ("Agent is working...")
- Smooth loading (parallel fetch, skeleton, batch state)
- Wizard budget controls + clickable step navigation
- Recursion limit HITL warning (amber, not red failure)

## P0: Step Naming / Numbering

### Problem
Plan says "7 steps" but UI shows "Step 29". Each node invocation increments `_step_index` globally, so after 29 graph node calls we're at step 29. The step number is meaningless — it's an internal counter, not the plan step.

### Fix needed
The step NUMBER should reflect the PLAN step (1-7). The executor should use `current_step` from graph state (which tracks which plan step is executing) instead of the global `_step_index`. Other nodes (planner, reflector, reporter) can use the global counter for ordering but should NOT label their steps as "Step 29".

The UI's `StepSection` header should show:
- Planner: "Plan (iteration N)"
- Executor: "Step N: {plan_step_description}"
- Reflector: "Reflection [continue/replan/done]"
- Reporter: "Final answer"

NOT "Step 29: ..." for everything.

### Files
- Agent: `event_serializer.py` — use `current_step` for executor events
- UI: `LoopDetail.tsx` StepSection — render step label based on nodeType

## P0: Reflector Gets No Conversation Context

### Problem
The reflector's prompt shows `system_prompt` (5000 chars) but `prompt_messages: 0`. It reflects without seeing ANY conversation history — no executor results, no tool outputs, no plan state. This is why it makes wrong decisions ("continue" when tools fail).

### Root cause
The `_prompt_messages` in reasoning.py comes from `_summarize_messages(messages)` where `messages` is the LangGraph state messages list. The reflector might be receiving a filtered/empty messages list. Check `reflector_node()` — what messages does it pass to `_summarize_messages()`?

### Files
- Agent: `reasoning.py` reflector_node — check what messages it summarizes

## P0: Stats Counter Assertion

### Problem
Test fails at line 333: `stats-user-msg-count` shows "0". The stats panel reads from a different data source than the chat messages.

### Files
- UI: SandboxPage.tsx stats panel
- Backend: token_usage or stats endpoint

## P1: PVC Test Timeout

The wizard deploy takes longer (agent build + rollout). The test timeout for agent card verification needs increasing.

### Files
- Test: `agent-rca-workflow.spec.ts` — increase timeout for wizard deploy variant

## P1: Micro-Reasoning System Prompt

The micro-reasoning shares the executor's system prompt. It should have its own hints:
- "If path not accessible, run echo $PWD"
- "If command fails with unknown flag, run --help"
- "Check error output before retrying same command"

### Files
- Agent: `reasoning.py` executor system prompt

## Rebuild + Test

```bash
export KUBECONFIG=~/clusters/hcp/kagenti-team-sbox42/auth/kubeconfig
# Follow /tdd:ui-hypershift skill
# NO DB cleanup unless specified
```
