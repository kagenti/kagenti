# Agent Sandbox — Session Passover (2026-02-26, Session 2)

> **For next session:** Continue with sandbox UI polish, deploy to sbox1, and start backend API for the import wizard. Consider refactoring backend pytest tests to use authenticated public API.

## What Was Done This Session

### Code Changes (10 files, +1287/-172 lines in kagenti, +12/-2 in agent-examples)

| Change | Files | What |
|--------|-------|------|
| Response rendering fix | `agent.py`, `sandbox.py`, `SandboxPage.tsx` | 3-layer fix: agent extracts only text blocks from tool-calling models, backend parses stringified lists, frontend filters graph event dumps from history |
| Session sidebar redesign | `SessionSidebar.tsx` | Compact display (agent name + time + session name/PR ref), root-only toggle, hover popover with details (creation time, status, sub-session count) |
| Sessions table redesign | `SessionsTablePage.tsx` | Root-only toggle, sub-session count column, agent name and created time columns |
| Chat UX improvements | `SandboxPage.tsx` | Message bubbles with avatars (User/Robot icons), timestamps, markdown styling (code blocks, tables, blockquotes), "Load earlier messages" batch loading |
| Import wizard | `SandboxCreatePage.tsx`, `App.tsx`, `index.ts` | 6-step wizard at `/sandbox/create`: Source, Security, Identity, Persistence, Observability, Review. ProgressStepper navigation. |
| Playwright fixes | `sandbox-walkthrough.spec.ts`, `92-run-ui-tests.sh` | Fixed ESM `require` → dynamic `import()`. Added sandbox tests to fulltest pipeline. |
| Session test fixes | `test_sandbox_sessions_api.py` | Shared `_wait_for_session()` polling helper (10 attempts, 2s intervals). Applied to persist, detail, kill, delete tests. |

### Test Results on sbox Cluster

| Suite | Result | Notes |
|-------|--------|-------|
| Playwright sandbox.spec.ts | 8/8 pass | Navigation, chat, sidebar, table, config |
| Playwright walkthrough | 1/1 pass | Full user journey, 11.2s |
| Backend session API | 7/7 connectivity fail | Expected — tests call in-cluster DNS from laptop. Deferred: refactor to use authenticated public API. |

### Design Decisions

1. **Session hierarchy:** Root sessions shown by default (toggle for all). Sub-sessions linked via `metadata.parent_context_id`. Ready for C20 sub-agent spawning.
2. **History batch loading:** Show last 30 messages initially, "Load earlier" button for older messages. Not true infinite scroll (history comes from single task record, no server-side pagination).
3. **Sub-session visualization:** User chose DAG (ReactFlow) over tree list. Deferred until C20 implementation adds actual sub-sessions.
4. **Backend test approach:** Current tests bypass auth and need in-cluster access. Future: refactor to use Keycloak token + public API endpoints.

## Clusters

| Cluster | KUBECONFIG | Status |
|---------|-----------|--------|
| sbox | ~/clusters/hcp/kagenti-team-sbox/auth/kubeconfig | Running, backend+UI rebuilding from latest push |
| sbox1 | ~/clusters/hcp/kagenti-team-sbox1/auth/kubeconfig | Ready (nodes up), needs kagenti deploy |

## Worktrees

| Repo | Worktree | Branch | Last Commit |
|------|----------|--------|-------------|
| kagenti | .worktrees/sandbox-agent | feat/sandbox-agent | `3dbefc7d` feat: sandbox UI improvements + import wizard + test fixes |
| agent-examples | .worktrees/agent-examples | feat/sandbox-agent | `123d18c` fix: extract only text from tool-calling model responses |

## PRs

| Repo | PR | Status |
|------|----|----|
| Ladas/kagenti | [#758](https://github.com/kagenti/kagenti/pull/758) | Draft, pushed |
| kagenti/agent-examples | [#126](https://github.com/kagenti/agent-examples/pull/126) | Draft, pushed |

## Known Issues (from visual debug test)

| Bug | Status | Notes |
|-----|--------|-------|
| Sidebar empty on initial load | Timing | Sessions load after ~3s polling; namespace selector shows "Loading..." initially |
| Page reload → home page | Keycloak | SSO redirect loses SPA path; localStorage restore only works on actual reload |
| Session ID not captured on fresh nav | Fixed | localStorage no longer restores stale session on fresh navigation |
| nginx 60s proxy timeout | Fixed | Increased to 300s for long-running agent tool calls |
| History shows only user messages | Fixed | History endpoint now pairs user msgs with artifact responses |

## Next Session Tasks (Priority Order)

1. **SSE streaming for live chat updates** — Backend: `POST /sandbox/{ns}/chat/stream` proxying A2A `message/stream`. Frontend: EventSource/ReadableStream for real-time chat updates as agent thinks/executes.
2. **Sidebar live status updates** — SSE subscription per visible session, or reduce polling to 3s. Show status transitions dynamically.
3. **Session switching test with long-running command** — Send `sleep 30`, switch sessions, come back, verify stream reconnects. Needs streaming to be implemented first.
4. **Backend API for wizard** — `POST /api/v1/sandbox/create` that orchestrates deployment
5. **Sub-session DAG visualization** — Add ReactFlow dependency, stub out DAG component
6. **Refactor backend tests** — Use Keycloak token + public API instead of direct in-cluster calls
7. **Fix Keycloak redirect_uri** — Preserve full SPA path through SSO redirect
8. **Address pdettori's review comments** on agent-examples PR #126

## Startup Command for Next Session

```bash
cd /Users/ladas/Projects/OCTO/kagenti/kagenti
export MANAGED_BY_TAG=kagenti-team
source .env.kagenti-team
export KUBECONFIG=~/clusters/hcp/kagenti-team-sbox/auth/kubeconfig
export PATH="/opt/homebrew/opt/helm@3/bin:$PATH"
claude
```

Then say:

> Read docs/plans/2026-02-26-sandbox-session-passover.md. Continue: (1) verify rebuild on sbox, (2) deploy kagenti on sbox1, (3) start backend API for import wizard, (4) add ReactFlow DAG for sub-sessions, (5) refactor backend tests to use authenticated API. Use /tdd:hypershift on sbox and sbox1.
