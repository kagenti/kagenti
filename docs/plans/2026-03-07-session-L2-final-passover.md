# Session L+2 Final Passover

> **Date:** 2026-03-07
> **Session:** L+2 (Claude Code, Opus 4.6)
> **Cost:** $929 / 6h47m API / 3d wall / 6553 lines added
> **Test Score:** 193/195 (99.0%), up from 182/194 (93.8%)
> **Cluster:** sbox42 (Llama 4 Scout)
> **Repos:** `feat/sandbox-agent` branch in both kagenti + agent-examples

## What L+2 Delivered

### UI Features
- Embedded FileBrowser in Files tab (props-based, contextId-scoped, breadcrumb nav)
- FilePathCard rendering (backtick-aware regex, custom ReactMarkdown code component)
- SessionStatsPanel rewrite (message-based stats extraction, not just agentLoops)
- SkillWhisperer merges agent card skills + built-in tools
- Agent badge restores from session metadata on load/switch
- Session polling (5s idle polling for cross-tab/multi-user updates)
- Duplicate message fix (content-based dedup in polling)
- Loop finalization (mark active loops "done" on stream end)
- Agent card fallback (try `/chat/` then `/sandbox/` endpoint)

### Backend
- `/sandbox/{ns}/agent-card/{name}` endpoint (bypasses AuthBridge 8080 retry)
- Removed auth from `/chat/{ns}/{name}/agent-card`
- Tuple parts guard (`isinstance(p, dict)`) in session history parsing
- File browser double-prefix fix (paths already absolute → use as-is)
- Skill forwarding in non-streaming `chat_send` endpoint
- Simplified deployment (removed init container/ConfigMap approach)
- RBAC: ConfigMap permissions for backend SA in team1/team2
- `create_configmap` method on KubernetesService

### Agent (agent-examples repo)
- **Dynamic skill loading**: clones kagenti repo at startup, scans `.claude/skills/`
- **Agent card with 100+ skills**: dynamically populated from scanned SKILL.md files
- **Skill invocation**: `/rca:ci` prefix → loads skill content into planner/executor prompts
- **Skill search paths**: per-session workspace + shared root `/workspace/.claude/skills/`
- **Child session DB records**: `_register_child_session()` + `_complete_child_session()` with `parent_context_id`
- SKILL.md convention support (directory-based skills with colon names)

### Auth/Keycloak
- Created `kagenti-operator` and `kagenti-admin` roles
- Assigned roles: admin (all), dev-user (viewer+operator), ns-admin (all)
- Synced passwords, emailVerified=true, temporary=false
- `create-test-users.sh` now creates roles
- TODO for master→demo realm migration

### Tests
- Deterministic file browser tests (kubectl file write, not LLM-dependent)
- RCA test uses `/rca:ci` skill invocation
- Files tab + Stats tab checks in RCA test
- Walkthrough search clear fix (PatternFly SearchInput focus bug)
- Skill whisperer mock updated for merged skills
- All timeouts bumped (identity 60s, file browser 30s, walkthrough 30min)
- WebSocket session updates design doc

### Docs
- `docs/plans/2026-03-06-websocket-session-updates-design.md`
- `docs/plans/2026-03-07-session-L2-final-passover.md` (this file)

---

## P0 — Must Fix Next Session

### 1. Agent/sandbox switching bug (CRITICAL)

**Problem:** When a user starts a session with rca-agent, the UI may send messages to sandbox-legion instead. The `selectedAgent` state defaults to `sandbox-legion` and isn't reliably updated from session metadata.

**Evidence:** Session `76754165a36747e2b0c9aff09d0ff1eb` has 2 task records — first with `agent_name: sandbox-legion` (wrong), second with empty agent_name.

**Root cause chain:**
1. User clicks rca-agent session → `handleSelectSession(id, 'rca-agent')` sets selectedAgent
2. `loadInitialHistory` fires → fetches session metadata → if metadata has no `agent_name`, selectedAgent stays correct
3. BUT: if the user navigates away and back, or page reloads, selectedAgent resets to default `'sandbox-legion'`
4. `loadInitialHistory` does fetch metadata and restore agent, but there's a race between the metadata fetch and the user sending a message

**Fix approach:**
- Add `sessionAgent` state (distinct from `selectedAgent` for new sessions)
- When `contextId` is set, lock agent to `sessionAgent` from DB metadata
- Block agent change during active session (show warning)
- Backend: reject messages where `agent_name` doesn't match the session's stored agent

**Files:**
- `kagenti/ui-v2/src/pages/SandboxPage.tsx` — state management
- `kagenti/backend/app/routers/sandbox.py` — validation in chat endpoints

### 2. Agent loop box stuck in "reasoning" + duplicate final message

**Problem:** During SSE streaming:
- The AgentLoopCard stays in "reasoning" or "executing" state and doesn't transition to "done" properly when the stream ends
- A duplicate final message box appears (gone on reload)

**Root cause:**
- The `setAgentLoops` finalization in the `finally` block marks loops as "done" but the SSE stream may send both a loop `llm_response` event AND a flat `content` event for the same final answer
- The flat content creates a separate message, and the loop card also shows the final answer → duplicate
- On reload, `loadInitialHistory` reconstructs from DB where only one copy exists

**Fix approach:**
- In the SSE handler, when `accumulatedContent` is set AND `agentLoops` has entries, skip adding the flat final message (the loop card already shows it)
- Add a `status` field to the SSE done event so the UI can mark loops as completed from the event, not just from the finally block
- Deduplicate: if the last loop's `finalAnswer` matches `accumulatedContent`, don't add a separate message

**Files:**
- `kagenti/ui-v2/src/pages/SandboxPage.tsx` — SSE handler finalization logic
- `kagenti/backend/app/routers/sandbox.py` — SSE event emission

### 3. Skill invocation UX — preserve `/rca:ci` in message display

**Problem:** When user sends `/rca:ci Analyze CI failures`, the UI strips the skill prefix and shows just the message text. On reload, the `/rca:ci` prefix is gone from the displayed message.

**Fix:** The user message should display the full text including `/rca:ci` prefix. The skill extraction should happen server-side, not client-side.

**Files:**
- `kagenti/ui-v2/src/pages/SandboxPage.tsx` — `handleSendMessage` skill parsing

---

## P1 — Should Fix

### 4. Delegation child sessions not visible in sidebar

**Status:** `_register_child_session` code exists but may not be working (no child sessions found with `parent_context_id` in DB). Need to verify asyncpg connectivity and fix if needed.

### 5. Skill loading into prompt vs system prompt

**Current:** Skill content is injected into `skill_instructions` state field → prepended to planner/executor system prompts.

**Question:** Should skill content be expanded into the user message instead? This would make it visible in history and preserve the context.

### 6. WebSocket / SSE for real-time session updates

**Design doc:** `docs/plans/2026-03-06-websocket-session-updates-design.md`
**Current:** 5s polling. Next: long-lived SSE endpoint.

### 7. Agent card from K8s labels (AgentCardSync controller)

**Finding:** The `AgentCardSync` controller exists in `kagenti-operator` (`agentcardsync_controller.go`) but may not be deployed. It watches Services and creates AgentCard CRDs. Need to verify it's running on sbox42.

---

## P2 — Nice to Have

### 8. Keycloak realm migration (master → demo)
TODO in `kagenti/auth/create-test-users.sh`.

### 9. Walkthrough test timeout
30min timeout, still hits it occasionally. Model-dependent.

### 10. Skill pack verification (Session M Tasks 3, 5, 7)
- `GET /api/v1/sandbox/skill-packs` endpoint
- Wizard "Skills" step
- Live CI skill invocation test

---

## Startup Instructions

```bash
cd /Users/ladas/Projects/OCTO/kagenti/kagenti
export KUBECONFIG=~/clusters/hcp/kagenti-team-sbox42/auth/kubeconfig

# Both repos are on feat/sandbox-agent branch:
# - .worktrees/sandbox-agent/ (kagenti repo)
# - .worktrees/agent-examples/ (agent code)

# Show services + credentials:
KUBECONFIG=$KUBECONFIG .worktrees/sandbox-agent/.github/scripts/local-setup/show-services.sh --reveal

# Run tests:
cd .worktrees/sandbox-agent/kagenti/ui-v2
KUBECONFIG=$KUBECONFIG \
  KAGENTI_UI_URL=https://kagenti-ui-kagenti-system.apps.kagenti-team-sbox42.octo-emerging.redhataicoe.com \
  KEYCLOAK_USER=admin \
  KEYCLOAK_PASSWORD=$(kubectl -n keycloak get secret kagenti-test-users -o jsonpath='{.data.admin-password}' | base64 -d) \
  npx playwright test e2e/ --reporter=list

# Build + deploy:
oc -n kagenti-system start-build kagenti-backend  # Backend
oc -n kagenti-system start-build kagenti-ui       # UI
oc -n team1 start-build sandbox-agent             # Agent

# Rollout:
kubectl -n kagenti-system rollout restart deploy/kagenti-backend deploy/kagenti-ui
kubectl -n team1 rollout restart deploy/sandbox-legion deploy/rca-agent deploy/sandbox-basic deploy/sandbox-hardened

# Priority: Fix P0 #1 (agent switching), then P0 #2 (loop box), then P0 #3 (skill UX)
```
