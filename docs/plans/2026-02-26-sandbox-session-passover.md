# Sandbox Legion — Session Passover (2026-02-26)

> **For next session:** Continue iterating on Playwright walkthrough test, fix the flaky session persistence test, build the sandbox agent import wizard UI, add Playwright tests to the fulltest pipeline. Both clusters (sbox, sbox2) have sandbox-legion deployed with all 8 Playwright UI tests passing.

## What Was Done This Session

### Infrastructure & Backend
| Item | Status |
|------|--------|
| Rename sandbox-agent → sandbox-legion | Done (both repos) |
| PostgreSQL persistence (TaskStore + Checkpointer) | Done, verified on both clusters |
| Backend sandbox API (CRUD on tasks table) | Done, 7 tests passing |
| Backend sandbox chat proxy (`/api/v1/sandbox/{ns}/chat`) | Done, non-streaming A2A proxy on port 8000 |
| Deploy pipeline `37-build-platform-images.sh` | Done, builds backend+UI from source on-cluster |
| Deploy pipeline `76-deploy-sandbox-agents.sh` | Done, deploys all sandbox variants (shared image) |
| Multi-turn test fix (fresh connections per turn) | Done |
| contextId VARCHAR(36) fix | Done |

### UI Components
| Component | Status |
|-----------|--------|
| SandboxPage (chat + sidebar) | Done, uses sandbox chat proxy |
| SessionSidebar (TreeView, parent→child) | Done |
| SessionsTablePage (search, pagination, kill/delete) | Done |
| AdvancedConfig (model/repo/branch) | Done |
| Sandbox nav item | Done |
| Types + API service | Done |

### Tests
| Suite | Result | Notes |
|-------|--------|-------|
| Backend agent tests (11) | 11/11 pass | Non-streaming + streaming multi-turn |
| Backend session API tests (7) | 6/7 pass | 1 flaky: session persistence polling race |
| Playwright sandbox.spec.ts (8) | 8/8 pass | Login, nav, sidebar, table, search, config |
| Playwright walkthrough (1) | 0/1 | Chat assertion fix committed, untested |

### Design Documents Created
| Document | Content |
|----------|---------|
| `2026-02-26-sandbox-legion-status.md` | Full status + remaining work + HITL provisioning + RBAC |
| `2026-02-26-sandbox-wizard-design.md` | Import wizard (6 steps), SandboxTokenPolicy CRD, SPIRE + GitHub App + Slack |
| `2026-02-26-vault-research.md` | HashiCorp Vault on OpenShift: deploy recipe, SPIRE integration, rotation patterns |

### Rebased
Both worktrees rebased onto upstream/main (clean, no conflicts):
- kagenti: `feat/sandbox-agent` (48 commits ahead)
- agent-examples: `feat/sandbox-agent` (19 commits ahead)

---

## Known Issues

### 1. Flaky `test_session_persists_in_db`
The A2A SDK's DatabaseTaskStore commits asynchronously. The test polls for 12s but sometimes the task isn't saved in time. May need to investigate if the TaskStore save callback fires reliably.

### 2. Walkthrough chat response assertion
Fixed but untested — scoped the Playwright locator to `.pf-v5-c-card__body` and waits for "Legion:" label. The chat proxy returns raw graph streaming events in the content — may need to clean up the response rendering in SandboxPage.

### 3. SandboxPage response rendering
The sandbox chat proxy returns the final text from artifacts, but the SandboxPage also shows intermediate graph events (AIMessage, ToolMessage) as separate "Legion:" blocks. Should only show the final response.

### 4. Playwright not in fulltest pipeline
The `hypershift-full-test.sh` Phase 4 runs pytest E2E tests but NOT Playwright UI tests. Need to add a Phase 4.1 or integrate into the existing test runner.

---

## Remaining Work (Priority Order)

### High Priority
1. **Fix SandboxPage response rendering** — show only final content, not raw graph events
2. **Fix walkthrough test** — re-run after response rendering fix
3. **Add Playwright to fulltest pipeline** — Phase 4.1 after pytest
4. **Fix flaky session persistence test** — investigate TaskStore async commit timing

### Medium Priority
5. **Sandbox agent import wizard** — PatternFly Wizard with 6 steps (design doc ready)
6. **UI transport adapters** — detect agent's preferredTransport, switch between SSE and non-streaming
7. **Expand tdd:hypershift skill** — add UI TDD cycle (build → deploy → Playwright → iterate)

### Lower Priority
8. **Vault integration** — deploy standalone Vault + VSO for secret rotation (research done)
9. **SandboxTokenPolicy CRD** — declarative credential scoping for AuthBridge
10. **HITL provisioning** — one-click OpenShift sandbox cluster provisioning via HITL
11. **HTTP streaming transport** — switch agent from JSONRPC (SSE) to HTTP streaming
12. **web_fetch retry** — handle GitHub API 429 rate limits
13. **Phoenix timing fix** — trace ingestion race condition

---

## Clusters

| Cluster | KUBECONFIG | Backend | UI | Sandbox | Tests |
|---------|-----------|---------|-----|---------|-------|
| sbox | `~/clusters/hcp/kagenti-team-sbox/auth/kubeconfig` | Rebuilt from source | Rebuilt from source | sandbox-agent + sandbox-legion | 17/18 backend, 8/8 Playwright |
| sbox2 | `~/clusters/hcp/kagenti-team-sbox2/auth/kubeconfig` | Rebuilt from source | Rebuilt from source | sandbox-agent + sandbox-legion | 18/18 backend |

## Worktrees

| Repo | Worktree | Branch | Remote |
|------|----------|--------|--------|
| kagenti | `.worktrees/sandbox-agent` | `feat/sandbox-agent` | `Ladas/kagenti` |
| agent-examples | `.worktrees/agent-examples` | `feat/sandbox-agent` | `Ladas/agent-examples` |

## PRs

| Repo | PR | Status |
|------|----|--------|
| kagenti/kagenti | [#758](https://github.com/kagenti/kagenti/pull/758) | Draft, needs CI re-check after rebase |
| kagenti/agent-examples | [#126](https://github.com/kagenti/agent-examples/pull/126) | Draft, needs CI re-check after rebase |

---

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

> Read docs/plans/2026-02-26-sandbox-session-passover.md. Continue: (1) fix SandboxPage response rendering to show only final text, (2) re-run and fix walkthrough Playwright test, (3) add Playwright to fulltest pipeline, (4) fix flaky session persistence test, (5) start sandbox import wizard UI. Use /tdd:hypershift on sbox and sbox2.
