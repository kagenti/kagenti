# Agent Sandbox — Session Passover (2026-02-26, Final)

> **For next session:** Focus on (1) multi-persona Keycloak setup with random passwords, (2) per-context Landlock isolation, (3) SSE streaming verification on live cluster, (4) Keycloak redirect_uri fix. See "Next Session Tasks" below.

## Session Stats

- **Duration:** ~4.5 hours wall time
- **Code:** 4,809 lines added, 593 removed across kagenti + agent-examples
- **Commits:** 16 on feat/sandbox-agent (kagenti), 3 on feat/sandbox-agent (agent-examples)
- **Tests:** 16/16 Playwright UI tests passing on sbox, 9/9 on sbox1
- **Subagents:** 4 parallel Opus 4.6 subagents for infrastructure (A2A concurrency, wizard backend, SSE streaming, HITL + security modules)

## What Was Built

### Core Infrastructure (via 4 parallel subagents)

| Feature | Files | Status |
|---------|-------|--------|
| A2A per-context_id concurrency locks | agent.py | Deployed — prevents stuck submitted tasks |
| TTL cleanup endpoint `POST /sandbox/{ns}/cleanup` | sandbox.py | Deployed — marks stale tasks as failed |
| HPA for sandbox-legion autoscaling | sandbox-legion-hpa.yaml | Created — 1-5 replicas, 70% CPU |
| Wizard backend `POST /sandbox/{ns}/create` | sandbox_deploy.py, main.py | Deployed — K8s Deployment + Service + Route |
| SSE streaming `POST /sandbox/{ns}/chat/stream` | sandbox.py, SandboxPage.tsx, nginx.conf | Deployed — proxies A2A message/stream events |
| Shell interpreter bypass detection | executor.py | Committed — catches `bash -c "curl evil.com"` |
| TOFU verification on startup | agent.py | Committed — hashes CLAUDE.md/sources.json |
| Sources policy in interpreter bypass | executor.py | Committed — blocks `bash -c "git clone evil.com"` |
| HITL interrupt() design | graph.py | Documented — 7-step implementation roadmap |

### UI Components

| Component | What | Status |
|-----------|------|--------|
| SessionSidebar | Compact display (agent name, time, session name/PR ref), root-only toggle, tooltip, 5s polling | Deployed |
| SessionsTablePage | Root-only toggle, sub-session count, agent/time columns | Deployed |
| SandboxPage chat | Message bubbles with avatars, timestamps, markdown styling, SSE streaming, infinite scroll | Deployed |
| SandboxCreatePage | 6-step wizard: Source, Security, Identity, Persistence, Observability, Review | Deployed |
| Nav rename | "Sandbox" → "Sessions" | Deployed |

### Backend APIs

| Endpoint | Purpose | Status |
|----------|---------|--------|
| `GET /sandbox/{ns}/sessions/{ctx}/history` | Paginated history with artifact-paired responses | Deployed |
| `PUT /sandbox/{ns}/sessions/{ctx}/rename` | Set/clear custom session title | Deployed |
| `POST /sandbox/{ns}/cleanup` | TTL cleanup for stuck submitted tasks | Deployed |
| `POST /sandbox/{ns}/create` | Deploy sandbox agent via K8s API | Deployed |
| `POST /sandbox/{ns}/chat/stream` | SSE streaming proxy for A2A message/stream | Deployed |

### Playwright Tests (16 total)

| Suite | Tests | What |
|-------|-------|------|
| sandbox.spec.ts | 8 | Navigation, chat, sidebar, sessions table, config |
| sandbox-walkthrough.spec.ts | 1 | Full user journey with timing markers |
| sandbox-debug.spec.ts | 1 | Session switching, history loading, visual debug |
| sandbox-create-walkthrough.spec.ts | 6 | Basic/Hardened/Enterprise agent import + navigation |

### Bug Fixes

| Bug | Root Cause | Fix |
|-----|-----------|-----|
| Stuck "submitted" tasks | A2A SDK allows concurrent graph execution per context_id | Per-context_id asyncio.Lock |
| History showing only user messages | Backend returned first task record (submitted), not latest (completed) | `ORDER BY id DESC LIMIT 1` |
| Graph event dumps in history | Agent status updates stored as history entries | Server-side filtering + artifact pairing |
| Popover flickering | PatternFly Popover hover trigger unreliable | Replaced with Tooltip |
| Session not restored on reload | Keycloak SSO redirect loses SPA path | localStorage persistence (partial fix) |
| Walkthrough test ESM error | `require('fs')` in ESM context | Dynamic `import('fs')` |
| nginx proxy timeout | 60s too short for tool calls | Increased to 300s |

## Known Issues

| Issue | Severity | Notes |
|-------|----------|-------|
| Page reload → home page | Medium | Keycloak SSO redirect_uri doesn't preserve `/sandbox?session=xxx`. Needs Keycloak init config fix. |
| Duplicate context_id in sidebar | Low | Multiple task records per context_id from retries. Need dedup view. |
| "Created: Unknown" in tooltip | Low | A2A SDK doesn't populate status.timestamp consistently. |
| Fixed admin/admin credentials | High | Kind deployment hardcodes `admin/admin`. Need random password generation. |
| No multi-user isolation in shared pod | Medium | Sessions share PVC; one session can read another's files. Need per-context Landlock. |
| Backend tests need in-cluster access | Medium | Pytest tests call agent via internal DNS. Need refactoring to use authenticated public API. |

## Capability Status (C1-C21)

| Cap | Name | Status | What's Done | What's Missing |
|-----|------|--------|-------------|----------------|
| C1 | Pod lifecycle | **Complete** | CRDs, controller, SandboxTemplate | — |
| C3 | Landlock | **Complete** | nono-launcher module, verified on RHCOS | Per-context isolation |
| C4 | TOFU | **Integrated** | Hash verification on startup, warns on mismatch | ConfigMap storage not tested on cluster |
| C5 | Squid proxy | **Complete** | Domain allowlist, sidecar built, NetworkPolicy | — |
| C6 | AuthBridge | **Designed** | Token exchange pattern documented | End-to-end test pending |
| C9 | Multi-repo | **Integrated** | RepoManager wired into interpreter bypass | Executor pre-hooks not complete |
| C10 | Skills loading | **Complete** | SkillsLoader parses CLAUDE.md + skills | — |
| C11 | Multi-LLM | **Complete** | litellm integration, model selector in UI | — |
| C13 | Observability | **Scaffolding** | Verification module exists | Trace parsing not implemented |
| C14 | HITL backend | **Framework** | Data models, channel adapters (stubs) | Actual API calls in adapters |
| C16 | Hardening | **Complete** | Read-only root, caps dropped, non-root, seccomp | — |
| C17 | Triggers | **Designed** | Cron/webhook/alert module | Backend integration pending |
| C18 | HITL routing | **Designed** | interrupt() design documented | Graph restructuring needed |
| C19 | Multi-conv | **Partial** | WorkspaceManager per-context dirs | Per-context Landlock isolation |
| C20 | Sub-agents | **Mostly** | explore() works, delegate() is stub | delegate creates SandboxClaim |
| C21 | Persistence | **Complete** | PostgreSQL TaskStore + LangGraph checkpointer | — |

## Clusters

| Cluster | KUBECONFIG | Status | Tests |
|---------|-----------|--------|-------|
| sbox | ~/clusters/hcp/kagenti-team-sbox/auth/kubeconfig | Running, latest build | 16/16 pass |
| sbox1 | ~/clusters/hcp/kagenti-team-sbox1/auth/kubeconfig | Running, latest build | 9/9 pass |

## Worktrees

| Repo | Worktree | Branch | Last Commit |
|------|----------|--------|-------------|
| kagenti | .worktrees/sandbox-agent | feat/sandbox-agent | `d5776302` wizard tests |
| agent-examples | .worktrees/agent-examples | feat/sandbox-agent | `ec6fe43` concurrency + security |

## PRs

| Repo | PR | Status |
|------|----|----|
| Ladas/kagenti | [#758](https://github.com/kagenti/kagenti/pull/758) | Draft |
| kagenti/agent-examples | [#126](https://github.com/kagenti/agent-examples/pull/126) | Draft |

## Next Session Tasks (Priority Order)

### 1. Multi-Persona Keycloak Setup
- **Random admin password:** Replace hardcoded `admin/admin` with random password generated at deploy time. Store in `keycloak-initial-admin` secret.
- **Test personas:** Create 3 users with different roles:
  - `dev-user` / random password → `kagenti-viewer` role, `team1-dev` group
  - `ns-admin` / random password → `kagenti-operator` role, `team1-admin` group
  - `platform-admin` / random password → `kagenti-admin` role
- **show-services.sh:** Print credentials using ANSI dim text (e.g., `\033[8m$PASSWORD\033[0m` — hidden until text selected) or print `kubectl get secret` command to reveal.
- **Playwright multi-persona tests:** Test that dev-user can chat but not kill sessions; ns-admin can kill/delete; platform-admin can access admin page.

### 2. Per-Context Landlock Isolation (C19)
- Each session runs in a subprocess with nono Landlock scoped to `/workspace/ctx-{id}/` only
- Other sessions' directories are invisible (not just unwritable)
- Design decision: fork/exec per request vs. persistent worker processes

### 3. SSE Streaming Verification
- Test SSE streaming on live cluster with long-running agent command (`sleep 30`)
- Verify frontend shows real-time status updates
- Test session switching during streaming and reconnection

### 4. Keycloak Redirect Fix
- Fix SPA path preservation through Keycloak SSO redirect
- Options: (a) configure `redirectUri` in Keycloak init, (b) use `post_login_redirect_uri` in keycloak-js, (c) App-level redirect based on localStorage

### 5. Session Deduplication
- Backend: deduplicate session list by context_id (show only latest task per context_id)
- Consider adding a DB view or unique constraint

### 6. Backend Test Refactoring
- Refactor pytest session tests to use Keycloak token + public API
- Remove dependency on in-cluster DNS access
- Pattern: `grant_type=password` → Bearer token → public route

### 7. Address PR Review Comments
- pdettori's 4 comments on agent-examples PR #126
- Shell interpreter bypass (done), HITL interrupt (designed), TTL cleanup (done), RepoManager wiring (done)

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

> Read docs/plans/2026-02-26-sandbox-session-passover.md. Continue: (1) implement random Keycloak admin password + 3 test user personas, (2) add multi-persona Playwright tests, (3) verify SSE streaming with long-running commands, (4) fix Keycloak redirect_uri for page reload, (5) implement per-context Landlock isolation. Use /tdd:hypershift on sbox and sbox1.
