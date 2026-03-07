# Session L+2 Passover — Open Items for Next Session

> **Date:** 2026-03-06
> **Session:** L+2 (Claude Code)
> **Test Score:** 193/195 (98.9%), up from 182/194 (93.8%)
> **Cluster:** sbox42 (Llama 4 Scout)

## What L+2 Delivered (14 commits)

- Embedded FileBrowser in Files tab (props-based, contextId-scoped)
- FilePathCard rendering (backtick-aware, custom ReactMarkdown code component)
- SessionStatsPanel rewrite (message-based stats, not just agentLoops)
- SkillWhisperer fix (fallback skills + sandbox agent-card endpoint)
- Agent card auth fix (`/sandbox/{ns}/agent-card/{name}` endpoint)
- Agent badge restore from session metadata on load/switch
- Tuple parts guard in session history parsing
- Keycloak: created kagenti-operator/admin roles, synced passwords
- Session polling (5s idle polling for cross-tab updates)
- Skill forwarding fix (non-streaming `chat_send` now forwards `skill` field)
- Duplicate message fix (content-based dedup in polling)
- Loop finalization (mark active loops "done" on stream end)
- Deterministic file browser tests (kubectl file write, not LLM-dependent)
- WebSocket session updates design doc

## P0 — Must Fix (Skill Loading + RCA Test)

### 1. Wire skill_pack_loader.py as init container (Session M Task 4)

**Problem:** `skill_pack_loader.py` exists at `deployments/sandbox/skill_pack_loader.py` with 11 unit tests passing, but is **never added as an init container** to agent deployments. The workspace `/workspace/.claude/skills/` stays empty.

**What to do:**
- Modify `kagenti/backend/app/routers/sandbox_deploy.py` → `_build_deployment_manifest()`
- Add init container `skill-loader` that runs `skill_pack_loader.py`
- Create ConfigMaps for the script and `skill-packs.yaml` manifest
- Add `skill_packs: list[str]` field to `SandboxCreateRequest`
- See `docs/plans/2026-03-04-skill-packs-impl.md` Task 4 for full spec

**Files:**
- `kagenti/backend/app/routers/sandbox_deploy.py` — add init container
- `skill-packs.yaml` — manifest already exists at repo root
- `deployments/sandbox/skill_pack_loader.py` — script already exists

### 2. Backend: pass skill content to agent system prompt

**Problem:** Even when skills are loaded to `/workspace/.claude/skills/`, the agent's system prompt doesn't include them. When `skill: "rca:ci"` is in the A2A message metadata, the agent needs to:
1. Read the skill file from `/workspace/.claude/skills/rca/ci.md` (or `rca:ci.md`)
2. Include the skill content in the executor's system prompt
3. Follow the skill's instructions

**What to do:**
- Modify agent's `graph.py` or `reasoning.py` to check for `skill` in message metadata
- If skill is present, read the corresponding `.md` file from the workspace
- Inject skill content into the planner/executor system prompt

**Files:**
- `.repos/agent-examples/.../sandbox_agent/graph.py`
- `.repos/agent-examples/.../sandbox_agent/reasoning.py`

### 3. RCA test: use `/rca:ci` skill invocation

**Problem:** The RCA agent test sends a plain text message instead of `/rca:ci PR #809`.

**What to do:**
- Update `e2e/agent-rca-workflow.spec.ts` line ~130 to send `/rca:ci Analyze CI for PR #809`
- Verify the skill prefix is parsed and forwarded (frontend already handles this)
- Add assertion that the agent's response follows the RCA skill template

## P1 — Should Fix

### 4. Delegation: child sessions not visible in sidebar

**Problem:** In-process delegation (`_run_in_process`) runs as a local LangGraph subgraph. No task record is created in the A2A database, so child sessions don't appear in the sidebar.

**Root cause:** `parent_context_id` is passed to `make_delegate_tool` but only logged, never stored. The subgraph uses `thread_id: child_context_id` but doesn't create a DB record.

**Fix:** Before running the subgraph, create a task record via the A2A TaskStore:
```python
task = Task(id=uuid(), contextId=child_context_id,
            status=TaskStatus(state=TaskState.working),
            metadata={"agent_name": variant, "parent_context_id": parent_context_id})
await task_store.save(task)
```
Then update to `completed` when done.

**Files:**
- `.repos/agent-examples/.../sandbox_agent/subagents.py`
- `.repos/agent-examples/.../sandbox_agent/agent.py` (pass task_store to make_delegate_tool)

### 5. Backend: `GET /api/v1/sandbox/skill-packs` endpoint (Session M Task 3)

**Problem:** No API endpoint to list available skill packs. The wizard UI needs this to show checkboxes.

**Files:**
- `kagenti/backend/app/routers/sandbox.py` — add endpoint
- `skill-packs.yaml` — read and return

### 6. UI: Wizard "Skills" step (Session M Task 5)

**Problem:** The create-agent wizard has no step for selecting skill packs.

**Files:**
- `kagenti/ui-v2/src/pages/SandboxCreatePage.tsx` — add Skills step

### 7. Cross-tab SSE / WebSocket

**Problem:** 5s polling works but is coarse. Design doc at `docs/plans/2026-03-06-websocket-session-updates-design.md`.

**Recommendation:** Medium-term, add long-lived SSE endpoint. Long-term, WebSocket.

## P2 — Nice to Have

### 8. Keycloak realm migration (master → demo)

TODO added in `kagenti/auth/create-test-users.sh`.

### 9. Agent card from K8s labels

Agent card is served by running pod. Could also be constructed from K8s labels for catalog view.

### 10. Walkthrough test timeout

22.9 min on Llama 4 Scout, exceeds 20-min timeout. Model-dependent.

## Startup

```bash
cd /Users/ladas/Projects/OCTO/kagenti/kagenti
export KUBECONFIG=~/clusters/hcp/kagenti-team-sbox42/auth/kubeconfig

# Read this passover doc
# Priority: wire skill_pack_loader init container (P0 #1),
# then fix agent skill loading (P0 #2), then RCA test (P0 #3)
```
