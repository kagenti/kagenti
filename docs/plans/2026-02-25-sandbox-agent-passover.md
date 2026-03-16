# Agent Sandbox — Session Passover (2026-02-25)

> **For next session:** Continue implementing the agent sandbox. Address pdettori's review comments on agent-examples PR #126, implement the two new capabilities (C19: multi-conversation isolation, C20: sub-agent spawning), deploy a fresh cluster for full E2E validation.

## What Was Done This Session

### Phase 1-9 Implementation (All Complete)

| Phase | Capabilities | Status | What Was Verified |
|-------|-------------|--------|-------------------|
| 1 | C1, C16 | **Done** | CRDs installed, controller built on-cluster via `oc start-build`, SandboxTemplate deployed, Sandbox + SandboxClaim working, headless Service + DNS verified, hardening verified (read-only root, caps dropped, non-root UID 1000770000, seccomp RuntimeDefault, SELinux enforced via restricted-v2 SCC, no SA token) |
| 2 | C5, C6 | **Done** | Squid proxy sidecar built on-cluster (UBI9 + Squid), domain allowlist working (github.com=200, pypi.org=200, evil.com=403, google.com=403), NetworkPolicy fixed for OVN-Kubernetes DNS (requires explicit namespaceSelector for openshift-dns namespace) |
| 3 | C3 | **Done** | nono-py installed from PyPI via proxy, Landlock ABI v5 confirmed on RHCOS 5.14 kernel, filesystem restrictions verified (/workspace=writable, /tmp=writable, /etc=blocked by Landlock) |
| 4 | C9, C10, C11 | **Done** | SkillsLoader parses CLAUDE.md + .claude/skills/ into system prompt (tested with mock workspace: 3 skills loaded, 378-char prompt generated), litellm imported and functional (completion/acompletion available), init container pattern for git clone designed (alpine/git image), full SandboxTemplate created |
| 5 | C9 dynamic | **Done** | RepoManager with sources.json policy verified (kagenti/*=allowed, kubernetes-sigs/agent-sandbox=allowed, evil-org/*=denied, random/other=denied) |
| 6 | C4, C15 | **Done** | TOFU hash verification logic tested (SHA-256, detects CLAUDE.md tampering, ConfigMap storage for hash persistence) |
| 7 | C17 | **Done** | SandboxTrigger module (cron/webhook/alert → SandboxClaim), FastAPI endpoint design |
| 8 | C14, C18 | **Done** | HITLManager with ContextRegistry + channel adapters (GitHub/Slack/KagentiUI), ApprovalRequest/Decision data model, FastAPI integration design |
| 9 | C13 | **Done** | OTEL verification scaffolding (checks MLflow accessibility, trace existence, GenAI attributes, span hierarchy) |

### Infrastructure Scripts

| Script | What It Does | Tested |
|--------|-------------|--------|
| `35-deploy-agent-sandbox.sh` | Deploys CRDs, RBAC, controller (on-cluster build), SandboxTemplate. Auto-detects gVisor RuntimeClass. | Yes — ran on sbox cluster, controller deployed, template applied to team1+team2 |
| `hypershift-full-test.sh` Phase 2.5 | `--include-agent-sandbox` / `--skip-agent-sandbox` flags | Yes — ran full pipeline on sbox, Phase 2.5 completed successfully |
| `create-cluster.sh` ENABLE_GVISOR | Installs gVisor via MachineConfig on NodePool, creates RuntimeClass | Partially — MachineConfig applied, RuntimeClass created, but gVisor + SELinux incompatibility prevents container creation (deferred) |

### Test Results on sbox Cluster

**Run 1 (initial deploy):** 47 passed, 0 failed, 30 errors, 3 skipped
- All 30 errors: Keycloak `Invalid user credentials` (RHBK operator auto-generates `temp-admin` with random password)

**Run 2 (after Keycloak fix):** 47 passed, 1 failed, 29 errors, 3 skipped
- Keycloak admin login: **FIXED** (created permanent `admin/admin` user via kcadm)
- 29 remaining errors: MLflow OAuth — Keycloak DB was wiped, OAuth clients lost
- 1 failure: `test_mlflow_otel_metrics_received` — OTEL metrics issue (pre-existing)

**Root cause of Keycloak issue:** RHBK operator creates `keycloak-initial-admin` secret with `temp-admin` + random password. The bootstrap admin is temporary and gets consumed/deleted. Fix: created permanent admin user via `kcadm.sh`. The real fix is ensuring the installer creates a persistent admin after the RHBK operator initializes Keycloak.

### gVisor + SELinux (Deferred)

gVisor (runsc) rejects ALL SELinux labels. CRI-O on RHCOS always applies labels. A wrapper script approach was prototyped (strips SELinux from OCI spec before calling runsc) but needs node rollout to test. Custom SCC (`gvisor-sandbox`, priority 20) was created to bypass SELinux for sandbox-agent SA.

**Decision:** Deferred. Sandbox works with runc + SecurityContext hardening (C16) + nono Landlock (C3). Plan doc updated with detailed security analysis comparing gVisor, SELinux, and Kata. Kata marked as "later" (requires VM per sandbox).

### PRs and Repos

| Repo | Branch | PR | Status |
|------|--------|----|----|
| Ladas/kagenti | `feat/sandbox-agent` | [#1](https://github.com/Ladas/kagenti/pull/1) | Draft, 22 files, +2601 lines |
| Ladas/agent-examples | `feat/sandbox-agent` | [kagenti/agent-examples#126](https://github.com/kagenti/agent-examples/pull/126) | Draft, rebased on upstream/main, 4 security review comments from pdettori |
| kagenti/kagenti-extensions | — | — | No changes needed (AuthBridge already built) |

### Review Comments to Address (agent-examples #126)

| # | Issue | Severity | Infra Mitigation (Phases 1-9) | App Fix Needed |
|---|-------|----------|------|------|
| 1 | Shell interpreter bypass (`bash -c "curl ..."`) | Critical | Squid proxy blocks at network level + nono Landlock blocks filesystem | Add recursive argument inspection for interpreter commands |
| 2 | HITL has no `interrupt()` call | Critical | Phase 8 HITL module provides proper approval backend | Replace `except HitlRequired` with LangGraph `interrupt()` |
| 3 | No TTL / workspace cleanup | Medium | SandboxClaim has `shutdownTime` + `Delete` policy | Add `cleanup_expired()` method or document as advisory |
| 4 | Package/remote blocking not wired | Medium | Phase 5 RepoManager enforces sources.json | Wire `is_package_blocked()` into executor pre-hooks |

## New Capabilities to Design

### C19: Multi-Conversation Isolation

**Problem:** A single sandbox agent pod may handle multiple concurrent conversations (e.g., different users or different A2A requests). Each conversation must be isolated — one conversation's workspace, context, and state must not leak to another.

**Current POC approach:** `WorkspaceManager` creates per-context directories under a shared PVC:
```
/workspace/
├── ctx-abc123/    # Conversation 1's workspace
│   ├── .context.json
│   └── repo/
├── ctx-def456/    # Conversation 2's workspace
│   ├── .context.json
│   └── repo/
```

**Design questions for next session:**
1. **Process-level isolation:** Should each conversation run in a separate process (fork/exec) with its own nono Landlock sandbox? This would prevent one conversation's compromised process from accessing another's workspace.
2. **Pod-per-conversation vs shared pod:** The agent-sandbox controller creates one pod per Sandbox. Should we create one Sandbox per conversation (strongest isolation, higher resource cost) or multiplex conversations on one pod (lower cost, weaker isolation)?
3. **Memory isolation:** LangGraph's `MemorySaver` is in-process. Multi-conversation needs either separate checkpointers per conversation or a shared store with strict key isolation.
4. **Credential isolation:** Each conversation may need different scoped tokens (e.g., one user's GitHub token vs another's). AuthBridge handles this at the request level, but the agent process needs to track which credentials belong to which conversation.

**Recommended approach:** One Sandbox pod per conversation for security-critical workloads (autonomous mode). Shared pod with per-context workspace isolation for interactive mode (lower cost, acceptable risk since the human is watching).

### C20: Sub-Agent Spawning via LangGraph

**Problem:** A sandbox agent needs to spawn sub-agents for parallel work — similar to how Claude Code uses the `Task` tool with `subagent_type=Explore` to delegate research. The sandbox should support:
1. Spawning sub-agents within the same LangGraph graph (asyncio tasks)
2. Spawning sub-agents in separate sandbox pods (A2A delegation)
3. Loading different skills for different sub-agents

**Current patterns:**
- **Claude Code Explore agent:** Spawns a sub-process with limited tools (Grep, Read, Glob) for codebase research. Returns a summary.
- **LangGraph sub-graphs:** A parent graph can invoke child graphs as tools. Each sub-graph runs as an asyncio task in the same process.
- **A2A delegation:** A planning agent sends an A2A message to spawn a separate sandbox agent with its own task.

**Design for next session:**
1. **In-process sub-agents (fast, same pod):** Use LangGraph's `StateGraph` composition — parent graph has tool nodes that invoke child graphs. Child graphs run as asyncio tasks sharing the same Python process. Good for research/analysis tasks.
   ```python
   # Parent graph tool that spawns a sub-agent
   @tool
   async def explore(query: str) -> str:
       """Spawn an explore sub-agent for codebase research."""
       sub_graph = create_explore_graph(workspace="/workspace/repo")
       result = await sub_graph.ainvoke({"query": query})
       return result["summary"]
   ```

2. **Out-of-process sub-agents (isolated, separate pods):** Create a new SandboxClaim with the sub-task. The parent agent polls the sub-agent's A2A endpoint until it returns results. Good for untrusted or long-running tasks.
   ```python
   @tool
   async def delegate(task: str, skill: str) -> str:
       """Spawn a sandbox sub-agent for a delegated task."""
       trigger = SandboxTrigger(namespace="team1")
       claim_name = trigger.create_from_webhook(
           event_type="a2a_delegation",
           repo="kagenti/kagenti",
           branch="main",
       )
       # Poll A2A endpoint until task completes
       return await poll_sandbox_result(claim_name, timeout=300)
   ```

3. **Skill-driven sub-agent selection:** The parent agent reads the skills index and selects which skill to invoke via a sub-agent:
   ```python
   skills = loader.list_skills()  # ["k8s:health", "tdd:kind", "rca:ci"]
   # LLM decides which skill to use based on the task
   # Sub-agent is spawned with that skill's full content as system prompt
   ```

**Recommended approach:** Start with in-process sub-agents (LangGraph asyncio, same pod) for fast tasks like explore/research. Add A2A delegation for heavy tasks that need their own sandbox. Skills determine which sub-agent type to use.

## Cluster & Environment

| Item | Value |
|------|-------|
| Cluster (sbox) | `kagenti-team-sbox` (2 workers, v1.33.6, Ready) |
| Kubeconfig (sbox) | `~/clusters/hcp/kagenti-team-sbox/auth/kubeconfig` |
| Cluster (lpvc) | `kagenti-hypershift-custom-lpvc` (2 workers, v1.33.6, Ready) |
| Kubeconfig (lpvc) | `~/clusters/hcp/kagenti-hypershift-custom-lpvc/auth/kubeconfig` |
| Mgmt kubeconfig | `~/.kube/kagenti-team-mgmt.kubeconfig` (kagenti-team mgmt accessible) |
| Worktree (kagenti) | `.worktrees/sandbox-agent` (branch `feat/sandbox-agent`) |
| Worktree (agent-examples) | `.worktrees/agent-examples` (branch `feat/sandbox-agent`, rebased on upstream/main) |
| Helm | `/opt/homebrew/opt/helm@3/bin/helm` v3.20.0 (brew, required — Rancher Desktop ships v4) |

## File Map

```
kagenti/kagenti (.worktrees/sandbox-agent):
├── .github/scripts/
│   ├── kagenti-operator/35-deploy-agent-sandbox.sh    # NEW — controller deployment
│   ├── hypershift/create-cluster.sh                   # MODIFIED — ENABLE_GVISOR
│   └── local-setup/hypershift-full-test.sh            # MODIFIED — Phase 2.5
├── deployments/sandbox/
│   ├── proxy/{Dockerfile,squid.conf,entrypoint.sh}    # NEW — Squid sidecar
│   ├── sandbox-template.yaml                          # NEW — Phase 1 basic
│   ├── sandbox-template-with-proxy.yaml               # NEW — Phase 2 with proxy
│   ├── sandbox-template-full.yaml                     # NEW — Phase 4 full (init container + litellm)
│   ├── test-sandbox.yaml                              # NEW — direct Sandbox test
│   ├── test-sandbox-claim.yaml                        # NEW — SandboxClaim test
│   ├── skills_loader.py                               # NEW — Phase 4 (C10)
│   ├── agent_server.py                                # NEW — Phase 4 (C11)
│   ├── nono-launcher.py                               # NEW — Phase 3 (C3)
│   ├── repo_manager.py                                # NEW — Phase 5 (C9)
│   ├── sources.json                                   # NEW — Phase 5
│   ├── tofu.py                                        # NEW — Phase 6 (C4)
│   ├── triggers.py                                    # NEW — Phase 7 (C17)
│   ├── hitl.py                                        # NEW — Phase 8 (C18)
│   └── otel_verification.py                           # NEW — Phase 9 (C13)
├── docs/plans/
│   ├── 2026-02-24-sandbox-agent-implementation-passover.md  # MODIFIED — gVisor/SELinux note
│   └── 2026-02-25-sandbox-agent-passover.md                 # NEW — this file
└── kagenti/tests/e2e/common/test_sandbox_agent.py           # MODIFIED

agent-examples (.worktrees/agent-examples):
└── a2a/sandbox_agent/                                 # POC code (has 4 review comments)
```

## Next Session Tasks (Priority Order)

1. **Address pdettori's 4 review comments** on agent-examples PR #126 (security fixes)
2. **Design C19 (multi-conversation isolation)** — decide pod-per-conversation vs shared pod
3. **Design C20 (sub-agent spawning)** — implement in-process LangGraph sub-agents + A2A delegation
4. **Deploy fresh cluster** — run full E2E with all phases, verify all tests pass
5. **Phase 5-9 integration tests** — write E2E tests for proxy, nono, skills loading
6. **Keycloak fix** — ensure installer creates persistent admin (not temp bootstrap)

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

> Read docs/plans/2026-02-25-sandbox-agent-passover.md. Continue implementing: (1) address pdettori's 4 review comments on agent-examples PR #126, (2) design and implement C19 (multi-conversation isolation) and C20 (sub-agent spawning via LangGraph), (3) deploy fresh cluster for full E2E validation. Use /tdd:hypershift for cluster work.
