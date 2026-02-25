# Sandbox Legion — Session Passover (2026-02-25)

> **For next session:** Implement Sandbox Legion rename, wire A2A TaskStore to Postgres, build the UI (sidebar, chat, table), run Playwright tests. Two HyperShift clusters are running with Sandbox Legion deployed and all tests passing.

## What Was Done This Session

### Security Fixes (PR #126, agent-examples)

4 critical/medium fixes from pdettori's code review + 4 hardening fixes from automated code review:

| # | Fix | File | What Changed |
|---|-----|------|-------------|
| 1 | Shell interpreter bypass | `permissions.py` | `check_interpreter_bypass()` detects `-c`/`-e` flags in bash/sh/python, extracts embedded commands, checks against deny rules. Also parses `&&`, `\|\|`, `;`, `\|` chains. |
| 2 | HITL no interrupt() | `graph.py` | Replaced `except HitlRequired` string return with LangGraph `interrupt()` that pauses graph. Agent resumes only after explicit human approval. |
| 3 | No TTL enforcement | `workspace.py` | Added `cleanup_expired()` — reads `created_at + ttl_days`, deletes expired workspace dirs. Wired into agent startup. |
| 4 | sources.json not wired | `executor.py` | Added `_check_sources()` pre-hook — checks pip/npm blocked packages and git allowed_remotes before execution. |
| 5 | HITL-on-unknown | `permissions.py` | Interpreter-wrapped unknown commands route to HITL (not auto-allow via `shell(bash:*)` rule). |
| 6 | Path traversal | `graph.py`, `subagents.py` | Replaced `str().startswith()` with `Path.is_relative_to()` to prevent `/workspace` vs `/workspace-evil` prefix collision. |
| 7 | Approval guard | `graph.py` | `isinstance(approval, dict)` check before `.get("approved")` to handle None. |
| 8 | `&&`/`;` parsing | `permissions.py` | Split embedded commands on `&&`, `\|\|`, `;`, `\|` metacharacters. |

### CI Fixes (PR #758, kagenti)

| Fix | What |
|-----|------|
| Dockerfile pinning | `FROM ubi9:9.5`, `squid-5.5` (was `:latest` / unversioned) — fixed Hadolint DL3007/DL3041 + Trivy DS-0001 |
| Test skip → fail | Removed `pytestmark skipif` — sandbox agent tests now fail (not skip) when agent is unavailable |
| StatefulSet→Deployment | Updated `35-deploy-agent-sandbox.sh` for upstream agent-sandbox migration (PR #191) |
| Route auto-discovery | `hypershift-full-test.sh` auto-discovers `sandbox-agent` route for `SANDBOX_AGENT_URL` |

### Capabilities Implemented

| Capability | What Was Built |
|-----------|---------------|
| **C19** (multi-conversation) | `cleanup_expired()` on startup, TTL from Configuration, per-context workspace dirs |
| **C20** (sub-agent spawning) | `subagents.py` — `explore` tool (in-process LangGraph sub-graph, read-only, 15 iter limit, 120s timeout) + `delegate` tool (SandboxClaim stub for out-of-process) |
| **C21** (A2A session persistence) | `a2a-sdk[postgresql]` `DatabaseTaskStore` replaces `InMemoryTaskStore`. Framework-agnostic — works for any A2A agent. `TASK_STORE_DB_URL` env var. |

### Infrastructure

| Item | Status |
|------|--------|
| `36-fix-keycloak-admin.sh` | Created + wired into Phase 2. Fixes RHBK operator temp-admin issue. Creates permanent admin/admin + demo realm. |
| `postgres-sessions` StatefulSet | Deployed to team1 on sbox + sbox1. Postgres 16 Alpine, 5Gi PVC. |
| Sandbox Legion deployment | Running on both clusters. Image built via Shipwright from `ladas/agent-examples:feat/sandbox-agent`. Uses OpenAI `gpt-4o-mini` via `openai-secret`. Route created for external access. |
| MLflow OAuth | Fixed on both clusters. `helm upgrade --reuse-values` re-triggered OAuth hook after demo realm was created. |

### E2E Test Results

| Cluster | Passed | Failed | Skipped | Notes |
|---------|--------|--------|---------|-------|
| **sbox** | 88 | 0 | 3 | 3 skips = UI agent discovery (pre-existing backend 404) |
| **sbox1** | 87 | 0 | 4 | 4 skips = 3 UI discovery + 1 Phoenix trace timing (race condition on fresh cluster) |

**Sandbox agent tests (11 total, all passing on sbox):**
- 3 deployment tests: deployment ready, service exists, agent card
- 2 shell tests: `ls` workspace, file write+read
- 2 multi-turn tests: file persistence across turns, conversational memory (Bob Beep)
- 4 real-task tests: GitHub issue #751 analysis, PR #753 analysis, RCA on mock CI failure log, workspace exploration

### Architecture Pivot: A2A-Generic Persistence

**Key decision:** Session persistence at the A2A protocol level, not LangGraph-specific.

```
A2A TaskStore (ALL agents)        LangGraph Checkpointer (Sandbox Legion only)
├── tasks, messages, artifacts    ├── Graph state, node outputs
├── Framework-agnostic            ├── Internal to agent
├── Read by Kagenti backend → UI  ├── Not read by UI
└── a2a-sdk[postgresql]           └── AsyncPostgresSaver (optional)
```

**Why:** The previous approach (AsyncPostgresSaver) only worked for LangGraph agents. The A2A SDK's `DatabaseTaskStore` persists at the protocol level — any agent framework can use it. The backend reads from the same tables to power the UI.

### Naming

**Sandbox Legion** = the flagship LangGraph-based multi-sub-agent orchestrator. Uses both A2A TaskStore (session persistence) and AsyncPostgresSaver (graph state for HITL pause/resume). Future sandbox agents (CrewAI, AG2) use only the A2A TaskStore.

### Documentation Created/Updated

| Document | What |
|----------|------|
| `docs/plans/2026-02-23-sandbox-agent-research.md` | Added C19, C20, C21 to capability matrix with deep-dives. Updated Section 4 (implementation status), gVisor deferral, security review findings. |
| `docs/auth/scoped-tokens-guide.md` | Full AuthBridge token flow for all services (GitHub, LLM, MLflow, Slack, A2A, MCP). |
| `docs/plans/2026-02-25-sandbox-ui-design.md` | Sandbox Legion management UI design — sidebar tree, chat-first UX, session table, RBAC, dynamic Postgres discovery. |
| `docs/plans/2026-02-25-sandbox-ui-impl-plan.md` | 10-task TDD implementation plan. Tasks 1-4 done (Postgres, pool manager, API router, agent wiring). |

---

## PRs

| Repo | PR | Branch | CI | Commits |
|------|----|--------|----|---------|
| kagenti/kagenti | [#758](https://github.com/kagenti/kagenti/pull/758) | `Ladas:feat/sandbox-agent` → `main` | All 15 checks green | ~15 commits |
| kagenti/agent-examples | [#126](https://github.com/kagenti/agent-examples/pull/126) | `feat/sandbox-agent` → `main` | All 2 checks green | ~12 commits |

---

## Clusters

| Cluster | Kubeconfig | Workers | Sandbox Legion | Postgres | Tests |
|---------|-----------|---------|----------------|----------|-------|
| sbox | `~/clusters/hcp/kagenti-team-sbox/auth/kubeconfig` | 2x v1.33.6 | Deployed + route | Deployed | 88 pass |
| sbox1 | `~/clusters/hcp/kagenti-team-sbox1/auth/kubeconfig` | 2x v1.33.6 | Deployed + route | Deployed | 87 pass |

---

## File Map

```
kagenti/kagenti (.worktrees/sandbox-agent):
├── .github/scripts/
│   ├── kagenti-operator/35-deploy-agent-sandbox.sh    # UPDATED — StatefulSet→Deployment
│   ├── kagenti-operator/36-fix-keycloak-admin.sh      # NEW — RHBK workaround
│   ├── hypershift/create-cluster.sh                   # MODIFIED — ENABLE_GVISOR
│   └── local-setup/hypershift-full-test.sh            # MODIFIED — Phase 2 Keycloak fix, sandbox route
├── deployments/sandbox/
│   ├── proxy/{Dockerfile,squid.conf,entrypoint.sh}    # UPDATED — pinned versions
│   ├── postgres-sessions.yaml                         # NEW — StatefulSet + Service + Secret
│   └── [sandbox templates, Python modules]             # Phases 1-9
├── kagenti/backend/app/
│   ├── services/session_db.py                         # NEW — dynamic per-NS pool manager
│   ├── routers/sandbox.py                             # NEW — session CRUD API
│   └── main.py                                        # MODIFIED — shutdown hook + router
├── kagenti/examples/agents/
│   ├── sandbox_agent_deployment.yaml                  # UPDATED — OpenAI config
│   ├── sandbox_agent_shipwright_build_ocp.yaml        # UPDATED — feat/sandbox-agent branch
│   └── sandbox_agent_service.yaml                     # EXISTING
├── kagenti/tests/e2e/common/
│   ├── test_sandbox_agent.py                          # UPDATED — route discovery, no skipif
│   └── test_sandbox_agent_tasks.py                    # NEW — GitHub/PR/RCA tests
├── docs/plans/
│   ├── 2026-02-23-sandbox-agent-research.md           # UPDATED — C19/C20/C21
│   ├── 2026-02-25-sandbox-ui-design.md                # NEW — Sandbox Legion UI design
│   ├── 2026-02-25-sandbox-ui-impl-plan.md             # NEW — 10-task impl plan
│   └── 2026-02-25-sandbox-session-passover.md         # NEW — this file
└── docs/auth/scoped-tokens-guide.md                   # NEW — token flow guide

agent-examples (.worktrees/agent-examples):
└── a2a/sandbox_agent/
    ├── src/sandbox_agent/
    │   ├── permissions.py    # UPDATED — interpreter bypass, HITL-on-unknown
    │   ├── graph.py          # UPDATED — interrupt(), explore/delegate tools, is_relative_to
    │   ├── executor.py       # UPDATED — _check_sources() pre-hook
    │   ├── workspace.py      # UPDATED — cleanup_expired()
    │   ├── subagents.py      # NEW — explore + delegate tools (C20)
    │   └── agent.py          # UPDATED — cleanup on startup, DatabaseTaskStore, AsyncPostgresSaver
    └── pyproject.toml        # UPDATED — a2a-sdk[postgresql], asyncpg, langgraph-checkpoint-postgres
```

---

## Next Session Tasks (Priority Order)

1. **Rename sandbox-agent → sandbox-legion** throughout both repos (deployment, service, route, build, settings, tests, docs)
2. **Wire `TASK_STORE_DB_URL`** in deployment manifest → `postgresql+asyncpg://kagenti:kagenti-sessions-dev@postgres-sessions.team1:5432/sessions`
3. **Verify TaskStore persistence** — send A2A message, restart pod, confirm session survives in DB
4. **Investigate A2A SDK TaskStore schema** — check exact table names/columns the SDK creates, adjust backend `sandbox.py` queries to match
5. **UI Task 5: SessionSidebar** — PatternFly TreeView, last 20 sessions, collapsible parent→child
6. **UI Task 6: SandboxPage** — chat panel + sidebar, route `/sandbox`
7. **UI Task 7: SessionsTable** — searchable table at `/sandbox/sessions`
8. **UI Task 8: AdvancedConfig** — expandable config panel (model, repo, skills)
9. **Playwright E2E tests** — login → sandbox → chat → verify session in sidebar
10. **Fix 1-test Phoenix timing difference** between sbox and sbox1 (trace ingestion race)

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

> Read docs/plans/2026-02-25-sandbox-session-passover.md. Continue: (1) rename sandbox-agent to sandbox-legion, (2) wire TaskStore to Postgres and verify persistence, (3) build the UI (Tasks 5-8), (4) run Playwright tests. Use /tdd:hypershift on both sbox and sbox1 clusters.
