# Session Gamma-2 (2026-03-14) Passover — Tool Loop, Indexing, Persistence

> **Date:** 2026-03-14
> **Cluster:** sbox42 (KUBECONFIG=/tmp/kagenti/sbox42-kubeconfig)
> **Worktrees:** `.worktrees/sandbox-agent` (kagenti), `.worktrees/agent-examples` (agent code)
> **Branch:** `feat/sandbox-agent` (both repos)
> **RCA Test:** Passing (1.8m, quality 5/5, 28K tokens)
> **Unit Tests:** 152+ passing

## Session Summary (continuation of Gamma)

1. Removed dedup (caused orphaned tool_results)
2. Added per-tool-result reflection HumanMessage (fixed 10x repeat loop)
3. Moved gh CLI flags from generic prompt to rca:ci skill
4. `replanner_output` event type (distinct from planner)
5. loopBuilder groups by `node_visit` instead of `step`
6. Executor tool loop shares one `node_visit` (not incrementing per re-entry)
7. Backend persist threshold → 1 (every event persisted)
8. `invoke_llm` captures bound tools in debug output
9. Tested tool_choice: auto (explicit + implicit) vs any
10. Workspace preamble injection via `invoke_llm`

## Commits This Session

### Agent (agent-examples repo)

| Commit | Description |
|--------|-------------|
| 0cc396d | Remove dedup, fix tool loop + 8 TDD tests |
| ec56ca3→0c4e3b1 | Reflection HumanMessage after EACH tool result |
| 8d866d5→cae8818 | Generic debugging guidelines, --help hint |
| b582f31 | replanner_output event type |
| 3349693 | Executor tool loop shares same node_visit |
| 2588933 | Test implicit auto (FAILED: 0 structured calls) |
| 8fb6f0f | Test explicit auto (FAILED: 0 structured calls) |
| 67043a5 | Revert to tool_choice="any" |
| a5cc813 | Capture bound tools in invoke_llm debug |

### UI + Backend (kagenti repo)

| Commit | Description |
|--------|-------------|
| dacc4fdb | gh CLI flag reference in rca:ci skill |
| ffa48c4a | Handle replanner_output, preserve currentStep |
| 711cfcbd | loopBuilder groups by node_visit |
| e412ec69 | Backend: persist every event (threshold=1) |

## tool_choice Experiment Results

| Mode | Structured tool_calls | Text reasoning | Verdict |
|------|----------------------|----------------|---------|
| `"any"` (required) | 100% | Never (empty content) | **USE THIS** |
| `"auto"` (explicit) | 0% | Yes (tools as text) | Broken on vLLM |
| implicit (omitted) | 0% | Yes (tools as text) | Broken on vLLM |

See `docs/plans/2026-03-13-vllm-tool-choice-auto-issue.md` for full analysis.

## Key Architecture Decisions

### Node Visit Model
```
node_visit increments on node TYPE transitions only:
  router(1) → planner(2) → step_selector(3) → executor(4) → reflector(5)
                                                    ↑ ↓
                                              tools (stays 4)
  executor→tools→executor loop = same node_visit
```

### Context Builders (Approach B)
```python
build_planner_context()   → SystemMessage + user HumanMessage + recent ToolMessages
build_executor_context()  → SystemMessage + step brief + tool pairs + reflection HumanMessages
build_reflector_context() → SystemMessage + last 3 AI→Tool pairs (no planner leak)
invoke_llm()              → injects WORKSPACE_PREAMBLE + captures bound_tools
```

### Reflection Prompt Pattern
```
AIMessage(tool_call: shell(gh run list --head ...))
ToolMessage("STDERR: unknown flag --head\nEXIT_CODE: 1")
HumanMessage("Tool 'shell' call 1 FAILED. Error: unknown flag.
  The flag is INVALID. Run the command with --help.
  Goal: 'List CI failures'. Try DIFFERENT approach. NEVER repeat.")
```

## Remaining Issues

### P0: Backend persist not deploying
The persist-every-event fix (commit e412ec69) may not be deployed.
Backend needs rebuild: `oc -n kagenti-system start-build kagenti-backend`
Then rollout: `oc -n kagenti-system rollout restart deploy/kagenti-backend`

### P1: Micro-reasoning text empty with tool_choice="any"
With `any`, Llama 4 Scout always calls a tool with empty `content`.
The micro-reasoning text shows "Decided next action: → shell(...)"
(auto-generated summary) instead of real reasoning. Options:
- Use `respond_to_user` escape tool for reasoning
- Two-phase call: first `auto` for reasoning, then `any` for tool
- Accept the limitation (current approach)

### P2: UI PromptInspector needs "Tools" section
The `_bound_tools` field is now captured by `invoke_llm` but the
PromptInspector component doesn't render it yet. Add a "Tools"
section showing the tool names/descriptions.

### P3: Collapsible sections still show redundant info
Some sub-blocks inside CollapsibleStepSection duplicate the header.

### P4: loopBuilder node_visit gaps
node_visit has gaps (5→7, 9→11) from planner_tools/reflector_tools
nodes that don't set `_last_node_key`. Cosmetic — ordering is correct.

## How to Continue

```bash
export KUBECONFIG=/tmp/kagenti/sbox42-kubeconfig
export LOG_DIR=/tmp/kagenti/tdd/ui-sbox42
mkdir -p $LOG_DIR

# Rebuild backend (persist fix not yet deployed)
oc -n kagenti-system start-build kagenti-backend
# wait...
oc -n kagenti-system rollout restart deploy/kagenti-backend

# Agent changes
cd .worktrees/agent-examples
git add -u && git commit -s -m "fix(agent): ..." && git push
oc -n team1 start-build sandbox-agent
# wait...
oc -n team1 rollout restart deploy/rca-agent-emptydir

# UI changes
cd .worktrees/sandbox-agent/kagenti/ui-v2
git add -u && git commit -s -m "fix(ui): ..." && git push
oc -n kagenti-system start-build kagenti-ui
# wait...
oc -n kagenti-system rollout restart deploy/kagenti-ui

# Test
RCA_AGENT_NAME=rca-agent-emptydir npx playwright test \
  e2e/agent-rca-workflow.spec.ts --reporter=list --timeout=600000
```

## Test Files

| File | Tests | Coverage |
|------|-------|---------|
| `test_context_isolation.py` | 38 | Context builders, full RCA flow, invoke_llm |
| `test_node_visit_indexing.py` | 10 | node_visit, sub_index, micro_step reset |
| `test_executor_loop.py` | 8 | No dedup, tool loop continuation, event pairing |
| `test_event_serializer.py` | 89 | Event types, status detection, index uniqueness |
| `loopBuilder.test.ts` | 6 | Event ordering, nodeVisits, call_id pairing |
