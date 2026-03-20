# Session Alpha (2026-03-13) Passover

> **Date:** 2026-03-13
> **Cluster:** sbox42 (KUBECONFIG=/tmp/kagenti/sbox42-kubeconfig)
> **Worktrees:** `.worktrees/sandbox-agent` (kagenti), `.worktrees/agent-examples` (agent code)
> **Branch:** `feat/sandbox-agent` (both repos)
> **Tests:** 191/196 passing (97.4%)

## What This Session Completed

### Design Docs
- Design v2 (main architecture doc) — rewritten, posted to issue #820
- Delta/Epsilon/Zeta session passovers
- MCP Gateway in architecture diagram
- Composable sandbox security standalone design doc
- HITL + Pod Events + Resource Wizard design doc
- vLLM tool_choice=auto issue doc analyzed

### Agent Fixes
- `jq` added to agent base image
- `GH_TOKEN` properly set from `github-token-secret`
- Reporter force-done: `partial` status + real summary (not "The task has been completed")
- All agents routed through LLM budget proxy
- Token budget removed from local `exceeded` check (proxy is authoritative)
- Debug mode: `bound_tools` + `llm_response` (full OpenAI format) in all node events
- Debug mode: step_selector includes system_prompt + llm_response
- Per-node tool subsets (WIP): planner gets read+write, reflector gets verify tools

### UI Fixes
- Wizard default `github-token-secret` (was `github-pat-secret`)
- Wizard proxy domains expanded (added `githubusercontent.com`, etc.)
- Wizard resource limits (memory/CPU for agent + proxy pods)
- Pod tab showing all 3 pods (agent, egress proxy, budget proxy)
- User message in loop card header
- Spinner during session load (no flicker)
- Micro-reasoning renders before tool call
- Backend memory 256Mi → 512Mi (Helm chart)

### Test Fixes
- Budget enforcement via proxy (200 token limit, 402 path tested, 3 follow-up messages)
- Variant tests: poll for loop card done state (not just input enabled)
- Session tests: poll for sessionId in URL
- Chat identity: use .first() for user message selector

### Infrastructure
- Squid proxy configs patched with `.githubusercontent.com`
- All egress proxies restarted
- DB cleanup procedures documented

## What's In Progress (WIP)

### Per-Node Tool Subsets (graph.py committed, reasoning.py needs updates)

Graph topology changed to give each node its own tools:

| Node | Tools | Status |
|------|-------|--------|
| Planner | glob, grep, file_read, file_write | Graph wired, planner_tools loop added |
| Executor | all tools | Unchanged |
| Reflector | glob, grep, file_read (inline) | Graph wired, reflector_node needs verify_tools param |
| Step selector | none | Unchanged |
| Reporter | none | Unchanged |

**Remaining work:**

1. **`reflector_node` in reasoning.py** — accept `verify_tools` param:
   ```python
   async def reflector_node(state, llm, budget=None, verify_tools=None):
       # After LLM decides continue/replan/done, optionally verify:
       if verify_tools and decision == "continue":
           # Call glob to verify the step's output exists
           glob_tool = next((t for t in verify_tools if t.name == "glob"), None)
           if glob_tool:
               result = await glob_tool.ainvoke({"pattern": "**/*"})
               # If expected output missing, change decision to "replan"
   ```

2. **`planner_node` in reasoning.py** — update prompt to:
   - Call `glob("**/*")` before planning to see workspace state
   - Save plans to `/workspace/.plans/plan-{timestamp}.md`
   - On replan: create step variants (1b, 1c) not replace whole plan
   - Create `.plans/` directory in workspace manager

3. **Test the planner tool loop** — planner calls glob → planner_tools executes → planner runs again with results → outputs plan

### Key Design Decisions for Next Session

1. **Planner saves plans to files**: `/workspace/.plans/plan-v1.md`, `plan-v2.md` etc.
2. **Step variants on replan**: Step 1 fails → mark as 1-FAILED, create step 1b with different approach
3. **Reflector verifies inline**: Calls tools directly (not via graph tool loop) to keep the graph simpler
4. **tool_choice="auto" for planner/reflector**: They CAN choose not to call tools

## Remaining Test Failures (4)

| Test | Root Cause |
|------|-----------|
| Budget persistence | Flaky — timing of token count after restart |
| Session isolation | Flaky — sessionBId sometimes empty (timing) |
| Delegation | Feature not built |
| Sidecars/looper | Feature not built (0 observations) |

## How to Continue

```bash
# Cluster access
export KUBECONFIG=/tmp/kagenti/sbox42-kubeconfig

# Agent code
cd .worktrees/agent-examples

# Key files to edit:
# - a2a/sandbox_agent/src/sandbox_agent/reasoning.py (reflector_node, planner_node)
# - a2a/sandbox_agent/src/sandbox_agent/graph.py (already updated)

# Build + deploy agent
oc -n team1 start-build sandbox-agent
oc -n team1 rollout restart deploy/sandbox-legion deploy/rca-agent-emptydir

# Run tests
cd .worktrees/sandbox-agent/kagenti/ui-v2
RCA_SKIP_DEPLOY=1 RCA_AGENT_NAME=rca-agent-emptydir \
  npx playwright test --reporter=list --timeout=600000
```
