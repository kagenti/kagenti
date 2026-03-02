# Multi-Session Coordination — 2026-03-01

> This document coordinates work across multiple Claude Code sessions working
> on the Kagenti sandbox platform. Each session updates its section when
> starting and completing work.

## Architecture Reference

See [2026-03-01-sandbox-platform-design.md](2026-03-01-sandbox-platform-design.md) for the full
system design with C4 diagrams.

Previous research (reference only): [2026-02-23-sandbox-agent-research.md](2026-02-23-sandbox-agent-research.md)

## Session Overview

| Session | Claude Session ID | Cluster | Focus | Status |
|---------|------------------|---------|-------|--------|
| **Session A** | `9468f782` | sbox | Identity, HITL, sessions, test fixes | Active |
| **Session D** | `eb18a410` | sbox | Keycloak users, multi-user tests | 10/10 pass |
| **Session O** | `25db5acf` | sbox42 | Orchestrator — spawns sub-sessions for builds, fixes, tests | Active |

Other active sessions (spawned by O or standalone):
- `0281a77c` — tofu.py unit tests (sbox42)
- `487d5f15` — test verification (sbox42, completed)
- `411cade4` — sandbox.spec.ts fixes (sbox, completed)
- `fab47f37` — IntegrationDetailPage routing (sbox, completed)
- `1d8e455f` — Shipwright builds (sbox, active)
- `19fda572` — sandbox agent setup (sbox42, active)

**WARNING:** Multiple sessions deploying to sbox concurrently → test instability (60/140 pass).
sbox42 is the stable baseline (112/140 pass).

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

| File | Tests | Pass | Fail | Owner | Root Cause |
|------|-------|------|------|-------|------------|
| integrations.spec.ts | 24 | 24 | 0 | Session C | — |
| sessions-table.spec.ts | 20 | 20 | 0 | Session C | — |
| agent-chat-identity.spec.ts | 10 | 6 | 4 | **Session D** | dev-user/ns-admin not in Keycloak |
| sandbox-create-walkthrough.spec.ts | 6 | 5 | 1 | Session B | Wizard test |
| home.spec.ts | 6 | 6 | 0 | Fixed | Auth added |
| sandbox.spec.ts | 14 | 4 | 10 | **Session A** | Timeouts, needs investigation |
| sandbox-variants.spec.ts | 4 | 4 | 0 | Session A | — |
| sandbox-chat-identity.spec.ts | 3 | 3 | 0 | Session C | — |
| agent-chat.spec.ts | 3 | 3 | 0 | Shared | — |
| sandbox-sessions.spec.ts | 6 | 5 | 1 | **Session A** | Title in sidebar test |
| agent-catalog.spec.ts | 12 | ? | ? | Fixed | Auth added (rerun needed) |
| tool-catalog.spec.ts | 9 | ? | ? | Fixed | Auth added (rerun needed) |
| session-ownership.spec.ts | 4 | ? | ? | Fixed | Creates session first now |
| sandbox-rendering.spec.ts | 4 | 0 | 1+3skip | **Session B** | Serializer not in agent image |
| sandbox-walkthrough.spec.ts | 1 | 0 | 1 | Session B | Auth/nav issue |
| sandbox-debug.spec.ts | 1 | 0 | 1 | Debug | — |
| test-sse-debug.spec.ts | 1 | 1 | 0 | Debug | — |

---

## Session Fix Instructions

### Session A: Fix sandbox.spec.ts timeouts (10 failures)
Tests have `loginIfNeeded()` but still timeout. Investigate:
- Health check: "should have no error alerts" — timeout 1m
- Navigation: "should have Sessions in nav" — timeout 1m
- Chat: "should send a chat message" — timeout 2m
- Sessions table: "should display/search" — timeout 23s
Likely cause: tests wait for elements that load slowly or have changed selectors.

### Session B: Fix rendering tests (1+3 failures)
Root cause: `event_serializer.py` not in agent image → agent emits Python repr, not JSON.
Fix: Include serializer in pyproject.toml or Dockerfile, rebuild agent image.
Once fixed, tool call steps will render and all 4 rendering tests should pass.

### Session D: Fix multi-user tests (4 failures)
Root cause: `dev-user` and `ns-admin` not provisioned in Keycloak.
Fix: Ensure `create-test-users.sh` runs during cluster setup, or add realm-init job.
Tests: `agent-chat-identity.spec.ts` lines 394, 433, 469, 508.

---

## Priority Order

1. **Session B**: Fix agent image (serializer) → unblocks 4 rendering tests
2. **Session A**: Fix sandbox.spec.ts timeouts (10 tests)
3. **Session D**: Provision Keycloak test users → unblocks 4 multi-user tests
4. **Session A**: Session title in sidebar (1 test)
5. **Session C**: Already all passing (44/44)
