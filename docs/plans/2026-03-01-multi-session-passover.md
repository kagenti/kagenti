# Multi-Session Sandbox Development Coordination

> **Date:** 2026-03-01
> **Main Coordinator:** `9468f782` — runs cross-cluster tests, monitors all sessions, updates doc
> **Orchestrator:** Session O (spawns sub-sessions)
> **Active Sessions:** A, B, C, D, E, F, O
> **Test Clusters:** sbox (dev), sbox1 (staging), sbox42 (integration)

## CRITICAL: Passwords Changed on ALL Clusters

**ALL Keycloak passwords have been rotated to random values.**
Old `admin/admin` NO LONGER WORKS on any cluster.

**To get new credentials:**
```bash
KUBECONFIG=~/clusters/hcp/kagenti-team-<YOUR_CLUSTER>/auth/kubeconfig \
  .worktrees/sandbox-agent/.github/scripts/local-setup/show-services.sh --reveal
```

**For Playwright tests:** The test runner (92-run-ui-tests.sh) auto-reads from K8s secrets.
For manual runs, set env vars:
```bash
export KEYCLOAK_PASSWORD=$(kubectl -n keycloak get secret kagenti-test-users -o jsonpath='{.data.admin-password}' | base64 -d)
```

**Session assignments remain the same:** A/B/D→sbox, C→sbox42, O→sandbox42

---

## ALERT: OpenAI Budget EXCEEDED

**Confirmed:** `insufficient_quota` — HTTP 429 on chat completions. Key is valid (models endpoint returns 200) but all chat/completion calls fail with:
```json
{"error": {"message": "You exceeded your current quota", "type": "insufficient_quota", "code": "insufficient_quota"}}
```

**Impact:** sandbox-legion, sandbox-hardened, sandbox-restricted ALL fail. sandbox-basic (local qwen2.5:3b) unaffected.

**Action:** Check billing at https://platform.openai.com/account/billing/overview

**TODO for Session B:** Agent must handle 429 `insufficient_quota` gracefully — return clear error message + auto-retry with backoff for transient 429s. Do NOT crash the SSE stream.

## Orchestrator Status (Updated 2026-03-01 15:00)

### Cluster Matrix
| Cluster | Model | Agents | Tests | UI | Password |
|---------|-------|--------|-------|-----|----------|
| **sbox** | DeepSeek R1 14B | 5 running | **12/12 PASS** | Latest | Random (use `show-services.sh --reveal`) |
| **sbox42** | Mistral Small 24B | 5 running | **13/13 PASS** | Latest | Random (use `show-services.sh --reveal`) |
| **sandbox42** | Mistral Small 24B | 1 (legion) | 0/8 (needs UI rebuild) | Old (v0.5.0) | Random (use `show-services.sh --reveal`) |

### Session → Cluster Assignments
| Session | Cluster | Why |
|---------|---------|-----|
| **A** (Core Platform) | **sbox** | Has all 5 variants, DeepSeek, full history |
| **B** (Source Builds) | **sbox** | Shares agents with A, needs Shipwright builds |
| **C** (HITL & Integrations) | **sbox42** | Clean cluster, Mistral, no conflicts with A/B |
| **D** (Keycloak) | **sbox** | Needs Keycloak access in keycloak namespace |
| **O** (Orchestrator) | **sandbox42** | Integration testing after fixing UI build |

### Passwords Changed
All clusters now use **random Keycloak admin passwords** (not admin/admin).
Read credentials: `KUBECONFIG=~/clusters/hcp/kagenti-team-<cluster>/auth/kubeconfig .github/scripts/local-setup/show-services.sh --reveal`

Demo realm users (dev-user, ns-admin) still use username=password (by design for test users).

### Latest Test Results
| Cluster | Suite | Result |
|---------|-------|--------|
| sbox | Full sandbox (12 tests) | **12/12 PASS** |
| sbox | Weather agent (3 tests) | **3/3 PASS** |
| sbox42 | Full sandbox (13 tests) | **13/13 PASS** |
| sandbox42 | Session + identity | **0/8 FAIL** (old UI, no Sessions page) |

### Session Activity (latest)
| Session | Last Commit | What |
|---------|------------|------|
| A | `bb2f73e6` | flush tool call events during streaming |
| B | No commits visible | may be working locally |
| C | `907fac72` + 6 more | Integration CRD + UI pages (7 commits) |
| D | `c34f4c29` | demo realm users + show-services --reveal |

## Architecture Reference

See [2026-03-01-sandbox-platform-design.md](2026-03-01-sandbox-platform-design.md) for the full
system design with C4 diagrams.

Previous research (reference only): [2026-02-23-sandbox-agent-research.md](2026-02-23-sandbox-agent-research.md)

---

## Session Definitions

### Session O — Orchestrator (sbox42 cluster)

**Role:** Test coordination, integration testing, conflict resolution
**Cluster:** sbox42 (creating — ETA ~10 min)
**Claude Session ID:** `25db5acf`
**Responsibilities:**
- Run full E2E test suite after each session pushes
- Detect conflicts between sessions
- Update this passover doc with test results
- Deploy fresh cluster for integration testing

**Does NOT write code** — only reads, tests, and coordinates

**Startup:**
```bash
cd /Users/ladas/Projects/OCTO/kagenti/kagenti
export MANAGED_BY_TAG=kagenti-team
source .env.kagenti-team
export KUBECONFIG=~/clusters/hcp/kagenti-team-sbox42/auth/kubeconfig
export PATH="/opt/homebrew/opt/helm@3/bin:$PATH"
claude

Read docs/plans/2026-03-01-multi-session-passover.md. You are Session O (Orchestrator).
Deploy sbox42 cluster, run full test suite, report results.
Other sessions (A, B, C, D) are working in parallel — check for conflicts.
```

**To create sbox42 cluster:**
```bash
# From main repo with HyperShift credentials:
source .env.kagenti-team
export CLUSTER_SUFFIX=sbox42
.github/scripts/hypershift/create-cluster.sh
# Wait ~10 min for cluster to be ready
# Then deploy Kagenti:
export KUBECONFIG=~/clusters/hcp/kagenti-team-sbox42/auth/kubeconfig
.worktrees/sandbox-agent/.github/scripts/local-setup/hypershift-full-test.sh --include-agent-sandbox
```

---

### Session A — Core Platform (sbox cluster)

**Claude Session ID:** `411cade4`
**Worktree:** `.worktrees/sandbox-agent`
**Role:** Fix DB connection, tool call rendering, session management, test fixes
**Cluster:** sbox (existing)
**File Ownership:**
- `kagenti/backend/app/routers/sandbox.py` — EXCLUSIVE
- `kagenti/ui-v2/src/pages/SandboxPage.tsx` — EXCLUSIVE
- `kagenti/ui-v2/src/components/SessionSidebar.tsx` — EXCLUSIVE
- `kagenti/ui-v2/src/components/SandboxAgentsPanel.tsx` — EXCLUSIVE
- `kagenti/ui-v2/e2e/sandbox-sessions.spec.ts` — EXCLUSIVE
- `kagenti/ui-v2/e2e/sandbox-rendering.spec.ts` — EXCLUSIVE
- `kagenti/ui-v2/e2e/sandbox-variants.spec.ts` — EXCLUSIVE

**Commits:** `bb2f73e6`, `5f7596d6`, `cf026bb9`, `1bb39522`, `e6eb9b8b`

**Completed Tasks:**
1. ~~P0: DB pool hardening~~ ✅ ssl=False, retry, eviction (5f7596d6)
2. ~~P1: Tool call streaming~~ ✅ regex fallback + flush (bb2f73e6)
3. ~~P1: Session title merge~~ ✅ metadata across task rows (cf026bb9)
4. ~~P1: sandbox.spec.ts 10 failures~~ ✅ selector fixes (e6eb9b8b)
5. ~~P1: sidebar title test~~ ✅ improved assertion (e6eb9b8b)
6. ~~P1: Unit + E2E tests~~ ✅ 23 backend + 1 E2E (1bb39522)

**All Session A tasks complete.** Backend + UI deployed to sbox.

**Startup:**
```bash
cd /Users/ladas/Projects/OCTO/kagenti/kagenti
export MANAGED_BY_TAG=kagenti-team
source .env.kagenti-team
export KUBECONFIG=~/clusters/hcp/kagenti-team-sbox/auth/kubeconfig
export PATH="/opt/homebrew/opt/helm@3/bin:$PATH"
claude

Read docs/plans/2026-03-01-multi-session-passover.md. You are Session A (Core Platform).
Fix the Istio+asyncpg DB connection blocker first, then tool call rendering.
Sessions B, C, D are working in parallel — do NOT touch their files.
Use /tdd:hypershift for iteration. 12/12 Playwright tests must stay green.
```

---

### Session B — Source Builds & Agent Image (sbox cluster)

**Claude Session ID:** `1d8e455f`
**Role:** Fix Shipwright builds, agent image packaging, deploy scripts
**Cluster:** sbox (shared with A, different namespace resources)
**Worktree:** `.worktrees/sandbox-agent` (kagenti repo) + `.worktrees/agent-examples` (agent code)
**File Ownership:**
- `.worktrees/agent-examples/` — EXCLUSIVE (all agent code)
- `kagenti/backend/app/routers/sandbox_deploy.py` — EXCLUSIVE
- `kagenti/backend/app/services/kubernetes.py` — EXCLUSIVE
- `.github/scripts/kagenti-operator/35-deploy-agent-sandbox.sh` — EXCLUSIVE
- `deployments/sandbox/` — EXCLUSIVE
- `kagenti/ui-v2/e2e/sandbox-create-walkthrough.spec.ts` — EXCLUSIVE

**Priority Tasks:**
1. ~~P0: Fix event_serializer.py not included in agent image~~ ✅ VERIFIED — serializer IS in image
2. ~~P0: Fix Shipwright build timeouts/failures~~ ✅ RESOLVED — backend-37 + ui-39 completed
3. ~~P0: Fix Istio+asyncpg DB connection~~ ✅ FIXED — switched `asyncpg` to `psycopg` driver
4. ~~P0: Fix postgres-sessions non-root~~ ✅ FIXED — switched to `bitnami/postgresql:16`
5. ~~P1: Create deployment manifests for all variants~~ ✅ DONE — 5 variants with services
6. ~~P1: Graceful 429/quota error handling~~ ✅ DONE — retry + clean error via SSE
7. ~~P0: Fix stale agent code in sandbox-legion~~ ✅ **ROOT CAUSE FOUND** — ConfigMap `agent-code-patch` volume mount was overlaying agent.py + event_serializer.py with old versions. Removed mounts. Builds were correct all along.
8. ~~P1: OpenShift BuildConfig alternative~~ ✅ DONE — created `sandbox_agent_buildconfig_ocp.yaml` with `noCache: true`
9. P1: Wizard deploy triggers Shipwright Build (not just Deployment)
10. P2: Source build from git URL (wizard end-to-end)

**Session Active:** YES (started 2026-03-01T12:04Z)

**Commits:**
```
# agent-examples repo:
2e2590b fix(sandbox): switch TaskStore from asyncpg to psycopg driver
048f0de fix(sandbox): handle LLM 429/quota errors gracefully in SSE stream
e489461 fix(sandbox): add CACHE_BUST arg to Dockerfile
b83a366 debug: add agent.py line count check to Dockerfile build

# kagenti repo:
6d5aee22 fix(deploy): switch sandbox-legion TaskStore URL from asyncpg to psycopg
2417c723 fix(deploy): switch postgres-sessions to bitnami/postgresql for OCP
2bf50b24 feat(deploy): add deployment manifests for all sandbox agent variants
bb196a00 fix(deploy): add CACHE_BUST build-arg to Shipwright Build
```

**Status / Findings:**
- ✅ Serializer in all agent images, produces correct JSON format
- ✅ Backend + UI builds completed, latest code deployed
- ✅ DB connection fixed: `postgresql+psycopg://` works with Istio ztunnel
- ✅ postgres-sessions: bitnami/postgresql:16 (UID 1001) for OCP compatibility
- ✅ All 5 variant manifests created with services
- ✅ 429 handling: quota exhaustion → clean error, transient → retry 3x with backoff
- ✅ **Stale code root cause: ConfigMap volume mount `agent-code-patch`** was overlaying agent.py/event_serializer.py with old versions. Fixed by removing mounts. sandbox-legion now has 536-line agent.py with all fixes.
- ✅ OpenShift BuildConfig created as Shipwright alternative (noCache: true)
- ⚠️ Agents switched to Mistral (mistral-small-24b-w8a8) — OpenAI quota exceeded

**Startup:**
```bash
cd /Users/ladas/Projects/OCTO/kagenti/kagenti
export MANAGED_BY_TAG=kagenti-team
source .env.kagenti-team
export KUBECONFIG=~/clusters/hcp/kagenti-team-sbox/auth/kubeconfig
export PATH="/opt/homebrew/opt/helm@3/bin:$PATH"
claude

Read docs/plans/2026-03-01-multi-session-passover.md. You are Session B (Source Builds).
Fix the agent image to include event_serializer.py, then fix Shipwright builds.
Session A owns sandbox.py and SandboxPage.tsx — do NOT touch those files.
```

---

### Session C — HITL & Session Orchestration (sbox1 cluster)

**Claude Session ID:** `487d5f15`
**Role:** Wire HITL approve/deny, implement sub-agent delegation, passover
**Worktree:** `.claude/worktrees/integrations-hub` (code cherry-picked to `.worktrees/sandbox-agent`)
**Cluster:** sbox1
**File Ownership:**
- `kagenti/ui-v2/src/pages/SandboxesPage.tsx` — EXCLUSIVE
- `kagenti/ui-v2/src/pages/SessionsTablePage.tsx` — EXCLUSIVE
- `kagenti/ui-v2/e2e/sandbox-chat-identity.spec.ts` — EXCLUSIVE
- `kagenti/ui-v2/e2e/session-ownership.spec.ts` — EXCLUSIVE
- `kagenti/tests/e2e/common/test_sandbox_variants.py` — EXCLUSIVE
- `kagenti/tests/e2e/common/test_sandbox_legion.py` — EXCLUSIVE
- `docs/plans/2026-02-27-session-orchestration-design.md` — EXCLUSIVE

**Additional File Ownership (Integrations Hub + Sessions):**
- `kagenti/ui-v2/src/pages/IntegrationsPage.tsx` — EXCLUSIVE
- `kagenti/ui-v2/src/pages/AddIntegrationPage.tsx` — EXCLUSIVE
- `kagenti/ui-v2/src/pages/IntegrationDetailPage.tsx` — EXCLUSIVE
- `kagenti/ui-v2/e2e/integrations.spec.ts` — EXCLUSIVE
- `kagenti/ui-v2/e2e/add-integration.spec.ts` — EXCLUSIVE
- `kagenti/ui-v2/e2e/sessions-table.spec.ts` — EXCLUSIVE
- `kagenti/backend/app/routers/integrations.py` — EXCLUSIVE
- `charts/kagenti/templates/integration-crd.yaml` — EXCLUSIVE
- `docs/plans/2026-02-28-integrations-hub-design.md` — EXCLUSIVE
- `docs/plans/2026-03-01-sub-agent-delegation-design.md` — EXCLUSIVE

**Completed Tasks:**
1. ✅ Integrations Hub UI — IntegrationsPage (tabbed), AddIntegrationPage (form), IntegrationDetailPage
2. ✅ Backend Integration router — 7 endpoints (CRUD + webhook + test connection)
3. ✅ Helm Integration CRD + RBAC rules
4. ✅ SessionsTablePage — type filter, parent/child links, status badges
5. ✅ Sub-agent delegation design doc
6. ✅ Webhook receiver endpoint

**Remaining Tasks:**
1. P1: Wire HITL approve/deny (needs sandbox.py — Session A file)
2. P2: Implement delegate tool (needs agent-examples — Session B file)
3. P2: Passover chain API (needs sandbox.py — cross-session TODO posted)
4. P3: Automated passover (context_monitor node)

**Test Results (local):** 58/58 Playwright tests (24 integrations + 14 add-integration + 20 sessions)
**sbox42 Results:** 7/7 passing (sandbox-chat-identity 3/3, session-ownership 4/4)

**Startup:**
```bash
cd /Users/ladas/Projects/OCTO/kagenti/kagenti
export MANAGED_BY_TAG=kagenti-team
source .env.kagenti-team
export KUBECONFIG=~/clusters/hcp/kagenti-team-sbox1/auth/kubeconfig
export PATH="/opt/homebrew/opt/helm@3/bin:$PATH"
claude

Read docs/plans/2026-03-01-multi-session-passover.md. You are Session C (HITL & Orchestration).
Wire HITL approve/deny buttons to actually resume the agent graph.
Session A owns sandbox.py — coordinate with A for any backend changes needed.
Deploy and test on sbox1 cluster.
```

---

### Session D — Keycloak & Multi-User (sbox cluster)

**Claude Session ID:** `eb18a410`
**Role:** Keycloak personas, multi-user tests, RBAC verification
**Cluster:** sbox (Keycloak namespace)
**Worktree:** `.worktrees/sandbox-agent`
**Session Active:** YES (started 2026-03-01)
**File Ownership:**
- `kagenti/ui-v2/src/contexts/AuthContext.tsx` — EXCLUSIVE
- `kagenti/ui-v2/e2e/agent-chat-identity.spec.ts` — EXCLUSIVE
- `kagenti/auth/` — EXCLUSIVE
- `kagenti/examples/identity/` — EXCLUSIVE
- `charts/kagenti-deps/templates/keycloak-*.yaml` — EXCLUSIVE

**Priority Tasks:**
1. ~~P1: Create dev-user and ns-admin Keycloak test users~~ ✅ DONE — Helm realm init + create-test-users.sh
2. ~~P1: Multi-user Playwright test (admin + dev-user)~~ ✅ DONE — JWT-based identity assertions
3. ~~P2: Random admin password (not hardcoded admin/admin)~~ ✅ DONE — randAlphaNum(16) with lookup preservation
4. ~~P2: Session visibility RBAC verification test~~ ✅ DONE — browser session isolation verified
5. P3: SPIRE identity toggle integration

**Test Results:** 10/10 Playwright tests passing on sbox (24.9s)

**Commits (on `feat/sandbox-agent`):**
```
88f3f1fc feat(auth): add Keycloak test users, random admin password, and multi-user E2E tests
c34f4c29 feat(auth): add demo realm users and --reveal flag to show-services
56dd5bd6 fix(e2e): use JWT-based assertions for multi-user identity tests
529b9155 feat(auth): add create-test-users.sh for master realm user provisioning
c127036a fix(auth): store test user passwords in kagenti-test-users secret
```

**Key finding:** UI authenticates against **master** realm (not demo). Test users must exist in master realm for UI login. `create-test-users.sh` handles this. Helm realm init creates demo realm users (for future migration).

**To provision users on a new cluster:**
```bash
KUBECONFIG=~/clusters/hcp/kagenti-team-<cluster>/auth/kubeconfig \
  ./kagenti/auth/create-test-users.sh
```

**Startup:**
```bash
cd /Users/ladas/Projects/OCTO/kagenti/kagenti
export MANAGED_BY_TAG=kagenti-team
source .env.kagenti-team
export KUBECONFIG=~/clusters/hcp/kagenti-team-sbox/auth/kubeconfig
export PATH="/opt/homebrew/opt/helm@3/bin:$PATH"
claude

Read docs/plans/2026-03-01-multi-session-passover.md. You are Session D (Keycloak & Multi-User).
Create dev-user in Keycloak, then write multi-user Playwright tests.
Do NOT touch sandbox.py, SandboxPage.tsx, or deploy files — those belong to Sessions A and B.
```

---

## Shared Resources (READ-ONLY for all sessions)

- `CLAUDE.md` — project config
- `docs/plans/2026-03-01-multi-session-passover.md` — THIS DOC (Session O updates)
- `docs/plans/2026-03-01-sandbox-platform-design.md` — design reference
- `kagenti/ui-v2/playwright.config.ts` — test config
- `kagenti/tests/conftest.py` — test fixtures

## Conflict Prevention Rules

1. Each session has EXCLUSIVE file ownership — do NOT edit other sessions' files
2. If you need a change in another session's file, add a TODO comment in this doc
3. All sessions push to `feat/sandbox-agent` branch — pull before push
4. Session O runs integration tests after each push
5. If tests fail after your push, YOU fix it before moving on

---

## Test Commands

```bash
# Session A tests (core):
KAGENTI_UI_URL=https://kagenti-ui-kagenti-system.apps.kagenti-team-sbox.octo-emerging.redhataicoe.com \
  npx playwright test sandbox-sessions.spec.ts sandbox-variants.spec.ts sandbox-rendering.spec.ts

# Session C tests (HITL):
KAGENTI_UI_URL=https://kagenti-ui-kagenti-system.apps.kagenti-team-sbox1.octo-emerging.redhataicoe.com \
  npx playwright test sandbox-chat-identity.spec.ts session-ownership.spec.ts

# Session D tests (multi-user):
KAGENTI_UI_URL=https://kagenti-ui-kagenti-system.apps.kagenti-team-sbox.octo-emerging.redhataicoe.com \
  npx playwright test agent-chat-identity.spec.ts

# Full suite (Session O):
KAGENTI_UI_URL=https://kagenti-ui-kagenti-system.apps.kagenti-team-sbox42.octo-emerging.redhataicoe.com \
  npx playwright test sandbox-*.spec.ts session-*.spec.ts agent-chat-identity.spec.ts
```

---

## Current Test Results (Session O updates this)

| Session | Tests | Passing | Last Run |
|---------|-------|---------|----------|
| A (Core) | 12 | 12/12 | 2026-02-28 |
| B (Builds) | 3 | 0/3 (wizard walkthrough) | Not run |
| C (HITL+Integrations) | 7+44 | 7/7 sbox42 + 44/44 local | 2026-03-01 — integrations 24/24, sessions 20/20, webhook endpoint, delegation design |
| D (Multi-user) | 10 | **10/10** | 2026-03-02 — JWT identity + session isolation, sbox |
| O (Integration) | 31 | **23/31** (5 fail, 3 skip) | 2026-03-01 14:45 — sbox42 full suite |

### Session O — Integration Test Detail (sbox42, 2026-03-01 14:45)

| Spec file | Total | Pass | Fail | Skip | Owner |
|---|---|---|---|---|---|
| `sandbox-sessions.spec.ts` | 6 | 6 | 0 | 0 | A |
| `sandbox-variants.spec.ts` | 4 | 4 | 0 | 0 | A |
| `sandbox-chat-identity.spec.ts` | 3 | 3 | 0 | 0 | C |
| `session-ownership.spec.ts` | 4 | 4 | 0 | 0 | C |
| `agent-chat-identity.spec.ts` | 10 | 6 | **4** | 0 | D |
| `sandbox-rendering.spec.ts` | 4 | 0 | **1** | 3 | A |

**Failure root causes:**
- **agent-chat-identity (4 failures):** Multi-user login timeout — `loginAs(dev-user/ns-admin)` hangs on Keycloak redirect >30s. Admin single-context login works (6/10 pass). Likely Keycloak users not created on sbox42 — Session D needs to create `dev-user` and `ns-admin` users here.
- **sandbox-rendering (1 fail + 3 skip):** Tool call steps not rendered (`Tool Call steps found: 0`). UI rendering bug — streaming response arrives but ToolCallStep components produce no DOM. Serial mode skips remaining 3 tests. Session A / B coordination needed.

**Deploy workarounds applied on sbox42 (NOT in repo):**
1. `postgres-sessions`: replaced `bitnami/postgresql:16` (tag not found) with `registry.redhat.io/rhel9/postgresql-16:latest` (non-root, OpenShift-compatible)
2. All sandbox agent deployments: patched `securityContext.runAsUser: 1001` to fix TOFU `PermissionError` on OpenShift-assigned UID

---

## Cross-Session TODOs

> Sessions add requests here when they need changes in another session's files.

| Requester | Target Session | File | Change Needed | Status |
|-----------|---------------|------|---------------|--------|
| O (conflict scan) | ALL | `api.ts`, `App.tsx`, `main.py` | **UNOWNED** — these shared files will cause merge conflicts. Assign ownership or use merge-order rules. | NEW — Session C added integrations to all 3 files (cherry-picked + conflict resolved into sandbox-agent) |
| O (conflict scan) | A, B | `SandboxCreatePage.tsx` | **UNOWNED** — sits at Session A/B boundary. Assign to one session. | NEW |
| A | O | `deployments/sandbox/postgres-sessions.yaml` | Re-apply on sbox42: image fixed from `postgres:16-alpine` to `bitnami/postgresql:16` (non-root) in 886a3cf4. Run: `kubectl apply -f .worktrees/sandbox-agent/deployments/sandbox/postgres-sessions.yaml` then `kubectl rollout restart sts/postgres-sessions -n team1` | READY |
| O (conflict scan) | B | `kubernetes.py` | Multi-author (Smola + Dettori). Session A HITL work touched this B-exclusive file in commit ae3e26fa. | WATCH |
| O (conflict scan) | D | `kagenti/auth/` | 3 authors (Dettori, Rubambiza, Smola). Session D should coordinate before modifying. | WATCH |
| O (sbox42 deploy) | B | `postgres-sessions.yaml` | ~~**P0 BLOCKER**: postgres:16-alpine runs as root~~ ✅ FIXED — switched to `bitnami/postgresql:16` (UID 1001). Commit `2417c723`. | DONE |
| B | A | `sandbox.py` | FYI: asyncpg fix is `TASK_STORE_DB_URL` driver scheme (`postgresql+psycopg://`), not ssl or retry. Checkpointer already uses psycopg via `AsyncPostgresSaver`. | INFO |
| C | A | `sandbox.py` | Add `GET /sessions/{context_id}/chain` endpoint — traverse `parent_context_id` and `passover_from`/`passover_to` in metadata to return full session lineage. See `docs/plans/2026-03-01-sub-agent-delegation-design.md` Phase 2. | NEW |
| O (sbox42 test) | B | `postgres-sessions.yaml` | **P0**: `bitnami/postgresql:16` tag does NOT exist on Docker Hub (manifest unknown). sbox42 workaround: `registry.redhat.io/rhel9/postgresql-16:latest`. Fix: use valid tag (e.g. `bitnami/postgresql:16.6.0`) or switch to RHEL image. | NEW |
| O (sbox42 test) | B | agent Dockerfile / `agent.py` | **P0**: TOFU hash write `PermissionError: /app/.tofu-hashes.json` on OCP with arbitrary UID. `/app` owned by 1001 but OCP assigns different UID. Fix: `chmod g+w /app` in Dockerfile OR write to `/tmp`. sbox42 workaround: `runAsUser: 1001` patch. | NEW |
| O (sbox42 test) | D | `agent-chat-identity.spec.ts` | 4 multi-user tests fail on sbox42 — Keycloak `dev-user`/`ns-admin` not created. Session D must run user creation on sbox42 or tests need cluster-agnostic setup. | NEW |
| O (sbox42 test) | A | `sandbox-rendering.spec.ts` | Tool call steps not rendered (`found: 0`). Agent streams response but ToolCallStep components produce no DOM elements. Frontend rendering bug. | NEW |

---

### Session F — Composable Sandbox Security (no cluster)

**Claude Session ID:** `0281a77c`
**Role:** Design + implement composable sandbox security model, Landlock wiring, SandboxClaim integration
**Worktree:** `.worktrees/sandbox-agent` (feat/sandbox-agent) — also committed to fix/hypershift-ci-deploy (to be cherry-picked)
**Cluster:** None (unit tests only — no cluster needed)
**Session Active:** YES (started 2026-03-01)
**File Ownership:**
- `deployments/sandbox/sandbox_profile.py` — EXCLUSIVE (NEW, created by F)
- `deployments/sandbox/tests/` — EXCLUSIVE (NEW, created by F)
- `kagenti/backend/app/routers/sandbox_trigger.py` — EXCLUSIVE (NEW, created by F)
- `kagenti/backend/tests/test_sandbox_trigger.py` — EXCLUSIVE (NEW, created by F)
- `docs/plans/2026-03-01-sandbox-platform-design.md` Section 3 — EXCLUSIVE (Session F additions)
- `docs/plans/2026-03-01-composable-sandbox-impl.md` — EXCLUSIVE
- `deployments/sandbox/*.py` (nono_launcher, tofu, repo_manager, triggers) — SHARED with Session B (copied from worktree, B owns originals in `.worktrees/`)

**Completed Tasks:**
1. ✅ Design: Composable 5-tier sandbox model (T0-T4) with self-documenting names
2. ✅ Design: Wizard flow with independent layer toggles + warnings for unusual combos
3. ✅ Design: SandboxClaim vs Deployment toggle (user chooses in wizard)
4. ✅ Updated design doc Section 2 (Container Diagram) + Section 3 (new) + Section 6 (Layer×Tier matrix)
5. ✅ Copied sandbox modules from worktree to `deployments/sandbox/`
6. ✅ Created `sandbox_profile.py` — composable name builder + K8s manifest generator (20 tests)
7. ✅ Unit tests for all modules: nono_launcher (10), tofu (11), repo_manager (10), triggers (7), agent_server (5)
8. ✅ Created `sandbox_trigger.py` FastAPI router — `POST /api/v1/sandbox/trigger` (9 tests)
9. ✅ Registered router in `main.py`
10. ✅ Wired TOFU verification into `nono_launcher.py` (runs before Landlock, `TOFU_ENFORCE=true` blocks)
11. ✅ Wired `nono_launcher.py` into `sandbox-template-full.yaml` entrypoint (replaces `sleep 36000`)
12. ✅ Wired `repo_manager.py` into `agent_server.py` (loads sources.json, `/repos` endpoint)
13. ✅ Updated design doc: Layer×Tier matrix (T2/T3 now ✅), Built section, Partial section
14. ✅ **63 sandbox module tests passing** in worktree
15. ✅ Wired `sandbox_profile.py` into `sandbox_deploy.py` — composable name + warnings in deploy response
16. ✅ Added composable security fields to `SandboxCreateRequest` (secctx, landlock, proxy, gvisor toggles)

**Commits (on `fix/hypershift-ci-deploy`, need cherry-pick to feat/sandbox-agent):**
```
18640cd9 feat(sandbox): composable security model + modules + trigger API (Session F)
ceb51a5b feat(sandbox): wire TOFU + Landlock + repo_manager, register Session F
2718b42a docs: update Session F status — all security layers wired, 322 tests passing
```

**Commits (on `feat/sandbox-agent` worktree):**
```
5a7f557c docs: Session F status — all implementation complete, 322 tests passing
<pending> feat(sandbox): wire sandbox_profile into deploy endpoint + copy modules
```

**Status: CORE IMPLEMENTATION COMPLETE.** All security layers wired and tested. Deploy endpoint uses composable profile.

**Remaining Tasks:**
- P1: Update wizard UI (ImportAgentPage.tsx) with composable security layer toggles (needs Session A/B coordination — ImportAgentPage is currently unowned)
- P1: Deploy wired templates to cluster and run E2E test (needs cluster access — coordinate with Session O)
- P2: Add auth middleware to `/api/v1/sandbox/trigger` endpoint (currently unauthenticated)
- P3: UI for trigger management (cron schedule editor, webhook config, alert mapping)

**Note:** Session B has `deployments/sandbox/` as EXCLUSIVE. Session F added NEW files there (sandbox_profile.py, tests/) and copied modules from the worktree. No existing Session B files were modified. Coordinate with Session B if conflicts arise.

---

### Session E — Legion Sub-Agent Spawning (no cluster required for in-process mode)

**Claude Session ID:** `fab47f37`
**Role:** Legion multi-mode delegation, session graph DAG visualization, delegation E2E tests
**Cluster:** kagenti-hypershift-custom-otel (for cluster-mode tests), local for in-process mode
**Session Active:** YES (started 2026-03-02)
**File Ownership:**
- `kagenti/ui-v2/src/pages/SessionGraphPage.tsx` — EXCLUSIVE (NEW, created by E)
- `kagenti/ui-v2/e2e/sandbox-graph.spec.ts` — EXCLUSIVE (NEW, created by E)
- `kagenti/ui-v2/e2e/sandbox-delegation.spec.ts` — EXCLUSIVE (NEW, created by E)
- `kagenti/backend/app/routers/chat.py` — graph endpoint only (lines 544-612, `get_session_graph`)
- `deployments/sandbox/subagents.py` — EXCLUSIVE (NEW, planned)
- `kagenti/tests/e2e/common/test_sandbox_delegation.py` — EXCLUSIVE (NEW, planned)
- `docs/plans/2026-03-01-sandbox-platform-design.md` Sections 9-10 — EXCLUSIVE (Session E additions)

**Completed Tasks:**
1. ✅ Design: 4-mode delegation model (in-process, shared-pvc, isolated, sidecar) — Section 9
2. ✅ Design: Session Graph DAG page with React Flow + dagre — Section 10
3. ✅ Playwright tests: 10 graph tests (sandbox-graph.spec.ts), 6 delegation tests (sandbox-delegation.spec.ts)
4. ✅ SessionGraphPage.tsx — React Flow + dagre layout, custom nodes/edges, legend
5. ✅ Backend: `GET /chat/{ns}/sessions/{ctx}/graph` endpoint with mock data
6. ✅ Route: `/sandbox/graph` in App.tsx, "Session Graph" nav item in AppLayout.tsx
7. ✅ Dependencies: @xyflow/react@12.10.1, dagre@0.8.5 installed

**Test Results:** 9/10 graph tests passing locally (1 edge visibility flake), 0/6 delegation tests (need SandboxPage delegation event handler)

**Remaining Tasks:**
- P1: Fix remaining graph test flake (edge count assertion)
- P1: Add delegation event types to SandboxPage streaming parser
- P1: Implement `in-process` delegation in agent code (subagents.py)
- P2: Backend: wire graph endpoint to real task metadata
- P2: `shared-pvc` delegation pod spawning
- P3: `isolated` delegation via SandboxClaim
- P3: `sidecar` delegation

---

## Priority Order

1. ~~**Session B**: Fix source builds -> deploy serializer~~ ✅ ALL P0s DONE
2. **Session A**: Tool call rendering (streaming flush), session name propagation
3. **Session C**: Wire HITL approve/deny to graph.resume()
4. **Session D**: Create Keycloak test users, multi-user Playwright tests
5. **Session O**: Pull latest (`2417c723`), re-deploy sbox42 with bitnami postgres, run integration suite
6. **Session B**: Create deployment manifests for hardened/basic/restricted variants
