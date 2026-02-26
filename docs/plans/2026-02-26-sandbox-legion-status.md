# Sandbox Legion — Status & Remaining Work (2026-02-26)

## What's Done

### Infrastructure
| Item | Status | Details |
|------|--------|---------|
| Rename sandbox-agent → sandbox-legion | Done | Both repos, all manifests, tests, scripts |
| PostgreSQL session persistence | Done | A2A SDK DatabaseTaskStore + LangGraph AsyncPostgresSaver |
| Backend sandbox API | Done | CRUD on A2A tasks table, dynamic per-NS pool discovery |
| Deploy pipeline (37-build-platform-images) | Done | Builds backend+UI from source on-cluster |
| Deploy pipeline (76-deploy-sandbox-agents) | Done | Shared image, deploys all variants (sandbox-agent + sandbox-legion) |
| Multi-turn streaming fix | Done | Dual approach: non-streaming for single-turn, SSE for multi-turn |

### UI Components
| Component | Status | Details |
|-----------|--------|---------|
| SandboxPage (chat) | Done | Chat-first UX, SSE streaming, namespace selector |
| SessionSidebar | Done | TreeView with parent→child, search, quick-jump |
| SessionsTablePage | Done | Search, pagination, kill/delete, status labels |
| AdvancedConfig | Done | Model dropdown, repo/branch inputs |
| Sandbox nav item | Done | Under "Agentic Workloads" |
| Types + API service | Done | TaskSummary, TaskDetail, sandboxService |

### Tests
| Suite | Status | Results (sbox + sbox2) |
|-------|--------|----------------------|
| Sandbox agent (11) | 9/11 pass, 2 multi-turn timeout | Multi-turn now uses streaming |
| Session API (7) | 7/7 pass | Backend rebuilt from source |
| Playwright UI (written) | Not run on cluster | Need browser access |

---

## What's Remaining

### 1. Sandbox Agent Import Wizard (NEW — not started)

**Route:** `/sandbox/create`

A step-by-step wizard for deploying security-hardened sandbox agents:

| Step | Name | What | Security Layer |
|------|------|------|---------------|
| 1 | Source | Git repo URL, branch, Dockerfile path, contextDir | AuthBridge for git clone |
| 2 | Security | Isolation mode, Landlock rules, proxy allowlist, NetworkPolicy | C3 (nono), C5 (Squid), C16 (hardening) |
| 3 | Identity | SPIRE toggle, namespace, service account, token scoping | C6 (AuthBridge), SPIFFE |
| 4 | Persistence | PostgreSQL toggle, TTL, checkpoint DB | C21 (TaskStore) |
| 5 | LLM Config | Model provider, API key secret, OTEL endpoint | C11 (litellm), C13 (observability) |
| 6 | Review | Summary + Deploy button → triggers pipeline | — |

**Open design questions:**
- How does SPIRE identity map to GitHub scoped tokens? (see below)
- Should the wizard create the Shipwright Build, or use the operator?
- How do we validate security config before deploying?

### 2. SPIRE + Scoped Token Flow (DESIGN NEEDED)

**Problem:** A sandbox agent needs scoped credentials to:
- Create branches on specific forks
- Send PRs to the main repo
- Access GitHub/GitLab APIs with least privilege
- Access LLM APIs (OpenAI, Anthropic, etc.)

**Current pattern (AuthBridge):**
```
Agent pod ──SPIFFE SVID──> AuthBridge ext_proc ──token exchange──> Scoped Token
```

1. Agent pod gets a SPIFFE SVID from SPIRE (`spiffe://kagenti/ns/team1/sa/sandbox-legion`)
2. When agent makes an outbound HTTP request, Istio routes through AuthBridge
3. AuthBridge validates the SVID and exchanges it for a scoped token:
   - GitHub: SVID → GitHub App installation token (scoped to specific repos)
   - LLM: SVID → API key from Kubernetes Secret
   - MLflow: SVID → OAuth2 token (Keycloak client credentials)

**Key question:** How do users configure which repos/permissions an agent gets?

**Proposed flow for the wizard:**
1. User selects "Enable SPIRE identity" in Step 3
2. User specifies allowed GitHub repos: `org/repo1, org/repo2`
3. Wizard creates a `SandboxTokenPolicy` CRD:
   ```yaml
   apiVersion: kagenti.io/v1alpha1
   kind: SandboxTokenPolicy
   metadata:
     name: my-sandbox-agent
     namespace: team1
   spec:
     spiffeId: spiffe://kagenti/ns/team1/sa/my-sandbox-agent
     github:
       app: kagenti-github-app
       repos: ["org/repo1", "org/repo2"]
       permissions: ["contents:write", "pull_requests:write"]
     llm:
       secretRef: openai-secret
       models: ["gpt-4o-mini", "gpt-4o"]
   ```
4. AuthBridge reads the policy and scopes tokens accordingly
5. Agent can only access the repos and models specified

**Alternative: User provides a PAT (Personal Access Token)**
- Simpler: user pastes a GitHub PAT with specific scopes
- Stored as a Kubernetes Secret
- AuthBridge injects it for matching outbound requests
- Less secure (PAT has user's full permissions, not repo-scoped)

### 3. Playwright Walkthrough Tests (IN PROGRESS)

Two walkthrough tests needed:

**A. Sandbox Deep-Dive (`sandbox-walkthrough.spec.ts`)**
- Login → Sandbox → chat → sidebar → sessions table → kill → history
- 12 markStep sections, ~3 min
- Mirrors all backend test scenarios

**B. Agent Import Wizard (`sandbox-create-walkthrough.spec.ts`)**
- Login → /sandbox/create → step through wizard → deploy → verify in catalog
- Tests the full onboarding flow with security layers
- Blocked on: wizard UI implementation

### 4. Minor Items
| Item | Priority | Status |
|------|----------|--------|
| web_fetch retry (429 rate limit) | Low | Not started |
| Phoenix timing fix | Low | Not started |
| Expand tdd:hypershift skill for UI TDD | Medium | Not started |
| Update research doc with C21 | Low | Not started |

---

## Architecture: How Agents Get Scoped Credentials

```
┌─── User (via Wizard) ────────────────────────────────────────────┐
│  1. Selects repos: org/repo1, org/repo2                          │
│  2. Selects permissions: contents:write, pull_requests:write     │
│  3. Wizard creates SandboxTokenPolicy CRD                        │
└──────────────────────────────────────┬───────────────────────────┘
                                       │
┌─── Kubernetes ───────────────────────▼───────────────────────────┐
│  SandboxTokenPolicy CR                                            │
│  ├── spiffeId: spiffe://kagenti/ns/team1/sa/my-agent             │
│  ├── github.repos: [org/repo1, org/repo2]                        │
│  ├── github.permissions: [contents:write, pull_requests:write]   │
│  └── llm.secretRef: openai-secret                                │
└──────────────────────────────────────┬───────────────────────────┘
                                       │
┌─── Runtime (Agent makes request) ────▼───────────────────────────┐
│                                                                    │
│  Agent pod (SPIFFE SVID from SPIRE)                                │
│       │                                                            │
│       ▼ outbound HTTP (e.g. api.github.com)                       │
│  Istio proxy → AuthBridge ext_proc                                │
│       │                                                            │
│       ▼ AuthBridge:                                                │
│       1. Validates SVID against SPIRE trust bundle                │
│       2. Looks up SandboxTokenPolicy for this spiffeId            │
│       3. Exchanges SVID for scoped GitHub App installation token  │
│       4. Injects Authorization header                             │
│       5. Squid proxy enforces domain allowlist                    │
│                                                                    │
│  Result: Agent can create branches on org/repo1 only              │
│          Agent cannot access org/repo3 (not in policy)            │
└────────────────────────────────────────────────────────────────────┘
```

## Clusters

| Cluster | KUBECONFIG | Backend | UI | Sandbox | Tests |
|---------|-----------|---------|-----|---------|-------|
| sbox | ~/clusters/hcp/kagenti-team-sbox/auth/kubeconfig | Rebuilt from source | Rebuilt from source | sandbox-agent + sandbox-legion | 16/18 pass |
| sbox2 | ~/clusters/hcp/kagenti-team-sbox2/auth/kubeconfig | Rebuilt from source | Rebuilt from source | sandbox-agent + sandbox-legion | 16/18 pass |

## Worktrees

| Repo | Worktree | Branch | Status |
|------|----------|--------|--------|
| kagenti | .worktrees/sandbox-agent | feat/sandbox-agent | Active, pushed |
| agent-examples | .worktrees/agent-examples | feat/sandbox-agent | Active, pushed |

## PRs

| Repo | PR | CI |
|------|----|----|
| Ladas/kagenti | [#758](https://github.com/kagenti/kagenti/pull/758) | Needs re-check |
| kagenti/agent-examples | [#126](https://github.com/kagenti/agent-examples/pull/126) | Needs re-check |
