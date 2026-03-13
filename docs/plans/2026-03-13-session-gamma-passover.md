# Session Gamma (2026-03-13) Passover — Context Isolation + Node Visit Model

> **Date:** 2026-03-13
> **Cluster:** sbox42 (KUBECONFIG=/tmp/kagenti/sbox42-kubeconfig)
> **Worktrees:** `.worktrees/sandbox-agent` (kagenti), `.worktrees/agent-examples` (agent code)
> **Branch:** `feat/sandbox-agent` (both repos)
> **RCA Test:** Passing (1.6m, quality 5/5)
> **Unit Tests:** 134 passing (context_isolation=36, event_serializer=89, node_visit=9)

## Session Summary

Major architectural improvements to the sandbox agent reasoning loop:

1. **Context builders** — Pure functions for each node's LLM message construction
2. **invoke_llm wrapper** — Captures exact LLM input/output, injects workspace preamble
3. **Node visit indexing** — Each graph node visit gets a sequential ID for UI grouping
4. **Workspace preamble** — Universal workspace path rule injected into all LLM calls
5. **Tool result status** — Based on EXIT_CODE, not keyword matching
6. **UI improvements** — Collapsible sections, file preview badges, plan always visible

## What Was Committed

### Agent (agent-examples repo, branch feat/sandbox-agent)

| Commit | Description |
|--------|-------------|
| 6349b5c | P0-P2: workspace path, SystemMessage boundary, tool call ID pairing |
| 9f9b259 | Context builders: planner replan fix, reflector plan leak fix |
| f84f3b2 | Unique event_index, exit-code-based tool status |
| a384a96 | invoke_llm wrapper with debug capture |
| 30afa6c | Universal workspace preamble via invoke_llm |
| e7f9f77 | Serializer: hardcoded index removal, stale step fix |
| 054e83b | Planner uses invoke_llm for workspace preamble |
| 21c6d6d | Node visit model + workspace_path in graph input state |

### UI (kagenti repo, branch feat/sandbox-agent)

| Commit | Description |
|--------|-------------|
| a065c394 | Node visits badge, file preview links, event ordering |
| eac38328 | Step visit badge in PatternFly |
| 4851a0c1 | Uniform badge layout for all step headers |
| 4dd4b3fc | Dark mode badge theming |
| be1b257f | File preview badges with FilePreviewModal, plan always visible |
| 44a57f3c | Remove duplicate PlanSection |
| b6d088ea | Collapsible step sections with tool call summary |
| 8edac287 | Step badge in collapsible header, hide redundant inner header |

## New Files

| File | Purpose |
|------|---------|
| `context_builders.py` | Pure functions: build_planner/executor/reflector_context, invoke_llm, LLMCallCapture |
| `tests/test_context_isolation.py` | 36 tests for context isolation, full RCA flow simulation |
| `tests/test_node_visit_indexing.py` | 9 TDD tests for node_visit, sub_index, micro_step |

## Architecture: Current State

### Context Flow (Approach B)

```
build_planner_context(state, system_prompt) → [SystemMessage, HumanMessage, ToolMessages]
build_executor_context(state, system_prompt) → [SystemMessage, HumanMessage, step tool pairs]
build_reflector_context(state, system_prompt) → [SystemMessage, last 3 AI→Tool pairs]

invoke_llm(llm, messages, workspace_path=...) → (response, LLMCallCapture)
  ├─ Injects WORKSPACE_PREAMBLE into first SystemMessage
  ├─ Captures exact messages sent + response received
  ├─ Extracts token usage and model name
  └─ Returns debug_fields() and token_fields() for node result
```

### Node Visit Model

```
node_visit: Sequential counter per graph node visit (main UI sections)
sub_index:  Position within a node visit (0, 1, 2...)
event_index: Global unique sequence number (for total ordering)
step:       Plan step being executed (1-based)
micro_step: Micro-reasoning counter within a step (resets on step_selector)

Tool nodes ("tools", "planner_tools", "reflector_tools") inherit the
preceding node's node_visit and continue its sub_index.
```

## Remaining Issues (Next Session)

### P0: Orphaned tool_call/tool_result pairing

**Symptom:** Some tool_result events appear without matching tool_call events.
This happens when the executor's dedup logic skips tool calls (`_dedup: True`)
but the tools node still executes and returns a result.

**Fix:** When dedup skips a tool call, it should also prevent the tools node
from executing. Currently, the dedup path returns an AIMessage without
tool_calls, which routes to reflector — but if the previous AIMessage had
tool_calls, LangGraph's ToolNode may still process them.

### P1: Executor exits tool loop too early

**Symptom:** Executor produces micro_reasoning without tool_calls on visits
5-8, then stops. The `_no_tool_count` counter triggers step failure after
2 consecutive no-tool responses.

**Fix:** The context builder for executor on continuing step should include
the tool_result from the "tools" node. Currently, the executor may not see
the latest ToolMessage because the windowing logic walks back to
[STEP_BOUNDARY] but the ToolMessage is appended AFTER the executor's
AIMessage in state["messages"].

### P2: sub_index gap in tools node

**Symptom:** tool_result at nv=7 has sub_index=4 but nv=7 only has
micro_reasoning at sub_index=0. Gap of 1-3.

**Fix:** The tools node inherits the executor's sub_index, but when multiple
executor visits happen between tools visits, the sub_index from the last
executor is stale. Reset sub_index tracking when tools node runs.

### P3: Micro-reasoning not showing after tool results

**Symptom:** In the UI, micro_reasoning blocks appear before tool_call but
not after tool_result. The user expects:
  micro_reasoning → tool_call → tool_result → micro_reasoning → tool_call → ...

**Root cause:** Each executor→tools→executor cycle is a separate graph
traversal. The first executor produces micro_reasoning + tool_call. The
tools node produces tool_result. The second executor invocation SHOULD
produce micro_reasoning (reflecting on tool result) + next tool_call. But
Llama 4 Scout sometimes produces text-only responses without tool_calls,
which the serializer emits as micro_reasoning without tool_call.

### P4: UI loopBuilder needs node_visit grouping

**Status:** Data model is ready (node_visit field in events). The UI's
loopBuilder still groups by `step` (plan step number). Need to refactor
`applyLoopEvent` to group by `node_visit` and render each visit as a
collapsible section.

### P5: File preview for directories

The FilePreviewModal currently only handles files. When a workspace path
points to a directory (e.g., `/workspace/<ctx>/repos/kagenti/`), it should
show the FileBrowser component instead.

### P6: Legacy event types removal

`plan`, `plan_step`, `reflection` are backward-compat aliases. Once the UI
uses only `planner_output`, `executor_step`, `reflector_decision`, remove
the legacy types from the serializer.

### P7: Pre-existing test failures

18 pre-existing test failures in test_budget.py (default values changed),
test_executor.py (permission changes), test_reasoning.py (reflector/reporter
API changes). Not from this session's work.

## How to Continue

```bash
# Cluster
export KUBECONFIG=/tmp/kagenti/sbox42-kubeconfig
export LOG_DIR=/tmp/kagenti/tdd/ui-sbox42
mkdir -p $LOG_DIR

# Build + deploy cycle
cd .worktrees/agent-examples
# make changes...
git add -u && git commit -s -m "fix(agent): ..." && git push
oc -n team1 start-build sandbox-agent
# wait for build...
oc -n team1 rollout restart deploy/rca-agent-emptydir

# For UI changes
cd .worktrees/sandbox-agent/kagenti/ui-v2
# make changes...
git add -u && git commit -s -m "fix(ui): ..." && git push
oc -n kagenti-system start-build kagenti-ui
# wait for build...
oc -n kagenti-system rollout restart deploy/kagenti-ui

# Test
RCA_AGENT_NAME=rca-agent-emptydir npx playwright test e2e/agent-rca-workflow.spec.ts \
  --reporter=list --timeout=600000

# Analyze session
CTX_ID=$(kubectl exec -n team1 postgres-sessions-0 -- psql -U kagenti -d sessions -t -c \
  "SELECT context_id FROM tasks WHERE metadata::json->>'agent_name' = 'rca-agent-emptydir' \
   ORDER BY id DESC LIMIT 1" | tr -d ' ')

# Show node_visit structure
kubectl exec -n team1 postgres-sessions-0 -- psql -U kagenti -d sessions -c "
SELECT (e->>'node_visit')::int as nv, (e->>'sub_index')::int as si,
  (e->>'event_index')::int as ei, (e->>'step')::int as step,
  e->>'type' as type, substring(COALESCE(e->>'name',e->>'description',''),1,40) as detail
FROM tasks, jsonb_array_elements(COALESCE(metadata::jsonb->'loop_events','[]'::jsonb)) e
WHERE context_id = '$CTX_ID' ORDER BY (e->>'event_index')::int"
```

## Key Test Files

| File | Tests | What it covers |
|------|-------|----------------|
| `test_context_isolation.py` | 36 | Per-node context isolation, full RCA flow, replan duplication |
| `test_node_visit_indexing.py` | 9 | node_visit, sub_index, event_index uniqueness, micro_step reset |
| `test_event_serializer.py` | 89 | Event types, tool call ID pairing, status detection, index uniqueness |
| `loopBuilder.test.ts` | 6 | Event ordering, nodeVisits tracking, call_id pairing |
