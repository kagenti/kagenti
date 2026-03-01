# Multi-Session Coordination — 2026-03-01

> This document coordinates work across multiple Claude Code sessions working
> on the Kagenti sandbox platform. Each session updates its section when
> starting and completing work.

## Architecture Reference

See [2026-03-01-sandbox-platform-design.md](2026-03-01-sandbox-platform-design.md) for the full
system design with C4 diagrams.

Previous research (reference only): [2026-02-23-sandbox-agent-research.md](2026-02-23-sandbox-agent-research.md)

## Session Overview

| Session | Role | Branch | Cluster | Focus |
|---------|------|--------|---------|-------|
| **Session A** (this) | Coordinator | `feat/sandbox-agent` | sbox | Identity, HITL, sessions, ownership, test suite |
| **Session B** | Builder | TBD | sbox | Source builds (Shipwright) for UI + backend from worktree |
| **Session C** | Feature | TBD | sbox | Integrations hub pages in UI |

## Shared Resources

- **Cluster**: `kagenti-team-sbox` (HyperShift on AWS)
- **Kubeconfig**: `~/clusters/hcp/kagenti-team-sbox/auth/kubeconfig`
- **Git remote**: `origin` = `git@github.com:Ladas/kagenti.git`
- **Branch**: `feat/sandbox-agent` (all sessions push here)
- **PR**: [#758](https://github.com/kagenti/kagenti/pull/758)
- **Namespaces**: `kagenti-system` (platform), `team1` (agents), `keycloak` (identity)
- **Design doc**: `docs/plans/2026-03-01-sandbox-platform-design.md`

## Session Startup

All sessions should run:
```bash
cd /Users/ladas/Projects/OCTO/kagenti/kagenti
export KUBECONFIG=~/clusters/hcp/kagenti-team-sbox/auth/kubeconfig
# If using worktree:
cd .worktrees/sandbox-agent
```

---

## Session A: Coordinator (Identity, HITL, Sessions)

### Completed
- Multi-user message identity: `admin (you)` labels on chat bubbles (AgentChat + SandboxPage)
- HITL approval cards: Approve/Deny buttons, auto-approve for safe tools
- Session ownership: owner in metadata, role-based filtering, visibility toggle
- Session history fix: query picks most complete history record
- HITL event detection in sandbox streaming
- 16 Playwright tests (20 pass from worktree, 4 fail due to tool call rendering)

### Commits (on `feat/sandbox-agent`)
```
18140dc2 feat: add HITL event handling to sandbox streaming
c6c1bff1 fix: show most complete session history instead of latest record
e24ff3c6 test: add Playwright tests for sandbox chat identity and HITL
300c7557 feat: add username labels and HITL detection to Sessions page
bbe856b0 test: add Playwright tests for session ownership and visibility
48b6fcde feat: add clickable visibility toggle on sessions table
335834d0 feat: add Owner and Visibility columns to sessions table
a0c2a706 feat: add role-based session ownership and visibility
1a1d05e4 fix: auto-approve test expands events panel, remove debug log
c6ac29bf feat: add multi-user identity and HITL approval cards
```

### Session A Progress (2026-03-01)
1. ~~**Fix tool call step rendering**~~ ✅ `bb2f73e6` — parseGraphEvent regex fallback + immediate flush during streaming
2. ~~**Fix Istio+asyncpg DB connection**~~ ✅ `5f7596d6` — ssl=False, retry with backoff, pool eviction
3. ~~**Session name matching content**~~ ✅ `cf026bb9` — metadata merge across task rows for title/owner propagation
4. **Wire HITL approve/deny to LangGraph `graph.resume()`** — moved to Session C
5. **Multi-user E2E test** — moved to Session D

### Files Modified
- `kagenti/backend/app/routers/chat.py` — username in SSE, HITL detection
- `kagenti/backend/app/routers/sandbox.py` — auth, ownership, visibility, history fix, HITL
- `kagenti/ui-v2/src/components/AgentChat.tsx` — username labels, HITL cards, auto-approve
- `kagenti/ui-v2/src/components/EventsPanel.tsx` — hitl_request type, approval buttons
- `kagenti/ui-v2/src/pages/SandboxPage.tsx` — username labels, HITL streaming
- `kagenti/ui-v2/src/pages/SessionsTablePage.tsx` — Owner/Visibility columns, toggle
- `kagenti/ui-v2/src/services/api.ts` — setVisibility API method
- `kagenti/ui-v2/e2e/agent-chat-identity.spec.ts` — identity + HITL tests
- `kagenti/ui-v2/e2e/session-ownership.spec.ts` — ownership tests
- `kagenti/ui-v2/e2e/sandbox-chat-identity.spec.ts` — sandbox identity tests

---

## Session B: Source Builds (UI + Backend from Worktree)

### Problem
Shipwright/OpenShift builds pull from the `feat/sandbox-agent` branch on GitHub.
Builds have been failing intermittently (DNS resolution, registry timeouts).
Need reliable source-to-image pipeline for the worktree code.

### Task
- Fix Shipwright BuildConfig for `kagenti-backend` and `kagenti-ui`
- Ensure builds use the correct git ref and succeed consistently
- Deploy `LangGraphSerializer` in the agent image (currently missing — causes tool call rendering failures)

### Key Commands
```bash
# Trigger builds
KUBECONFIG=~/clusters/hcp/kagenti-team-sbox/auth/kubeconfig oc start-build kagenti-backend -n kagenti-system
KUBECONFIG=~/clusters/hcp/kagenti-team-sbox/auth/kubeconfig oc start-build kagenti-ui -n kagenti-system

# Check build status
KUBECONFIG=~/clusters/hcp/kagenti-team-sbox/auth/kubeconfig kubectl get builds -n kagenti-system --no-headers | tail -5

# Roll out after build
KUBECONFIG=~/clusters/hcp/kagenti-team-sbox/auth/kubeconfig kubectl rollout restart deployment/kagenti-backend deployment/kagenti-ui -n kagenti-system
```

### Status
- [ ] Backend builds reliably
- [ ] UI builds reliably
- [ ] LangGraphSerializer deployed in agent image
- [ ] Tool call rendering verified after serializer deploy

---

## Session C: Integrations Hub Pages

### Task
Build the UI pages for the Integrations Hub feature:
- Integration list page (table of configured integrations)
- Integration detail page (webhook URL, cron schedule, event history)
- Integration create/edit form

### Design Reference
- `docs/plans/2026-02-28-integrations-hub-design.md`
- `docs/plans/2026-02-28-integrations-hub-plan.md`

### Key Files
- `kagenti/ui-v2/src/pages/IntegrationsPage.tsx` (new)
- `kagenti/ui-v2/src/pages/IntegrationDetailPage.tsx` (new)
- `kagenti/ui-v2/src/services/api.ts` (add integration service methods)

### Status
- [ ] Integration list page
- [ ] Integration detail page
- [ ] Integration create/edit form
- [ ] Route added to App.tsx
- [ ] Sidebar navigation link

---

## Test Suite Status

Run from worktree: `.worktrees/sandbox-agent/kagenti/ui-v2/`

```bash
KAGENTI_UI_URL=https://kagenti-ui-kagenti-system.apps.kagenti-team-sbox.octo-emerging.redhataicoe.com \
KEYCLOAK_USER=admin KEYCLOAK_PASSWORD=admin \
npx playwright test e2e/agent-chat.spec.ts e2e/agent-chat-identity.spec.ts \
  e2e/session-ownership.spec.ts e2e/sandbox-chat-identity.spec.ts \
  e2e/sandbox-sessions.spec.ts e2e/sandbox-rendering.spec.ts \
  --reporter=list
```

| Category | Passing | Failing | Root Cause |
|----------|---------|---------|------------|
| Agent chat (identity, HITL) | 9 | 0 | — |
| Session ownership | 4 | 0 | — |
| Sandbox chat identity | 3 | 0 | — |
| Sandbox sessions (multi-turn) | 4 | 1 | Session ID not in URL after reload |
| Sandbox rendering (tool calls) | 0 | 3 | Tool call steps not flushed during streaming |
| **Total** | **20** | **4** | |

---

## Priority Order

1. **Session B**: Fix source builds → deploy serializer → unblocks tool call rendering
2. **Session A**: Fix tool call step flushing → fix 3 rendering test failures
3. **Session A**: Wire HITL approve/deny to graph.resume()
4. **Session C**: Integrations hub UI pages
5. **Session A**: Multi-user E2E test + second Keycloak user
