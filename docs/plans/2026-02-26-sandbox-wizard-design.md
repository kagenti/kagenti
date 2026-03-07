# Sandbox Agent Import Wizard — Design Document

> **Date:** 2026-02-26 | **Status:** Draft

## Overview

A step-by-step wizard at `/sandbox/create` for deploying security-hardened sandbox agents. Guides users through source configuration, security layers, identity/credentials, persistence, and LLM setup. Supports two credential modes: quick (PAT) and enterprise (GitHub App).

## Wizard Steps

### Step 1: Source

| Field | Type | Required | Default |
|-------|------|----------|---------|
| Agent name | text | yes | — |
| Git repository URL | text | yes | — |
| Branch | text | yes | `main` |
| Context directory | text | no | `/` |
| Dockerfile path | text | no | `Dockerfile` |
| Agent variant | select | yes | `sandbox-legion` |

Agent variant options: `sandbox-legion` (multi-agent, persistent), `sandbox-agent` (basic, stateless), or custom name.

### Step 2: Security Hardening

| Field | Type | Default | Capability |
|-------|------|---------|------------|
| Isolation mode | radio | Shared pod | C19 |
| Read-only root filesystem | toggle | on | C16 |
| Drop all capabilities | toggle | on | C16 |
| Non-root user | toggle | on | C16 |
| Landlock filesystem rules | textarea | `/workspace:rw, /tmp:rw` | C3 |
| Network proxy allowlist | textarea | `github.com, api.openai.com` | C5 |
| Workspace size | select | `5Gi` | — |
| Session TTL | select | `7 days` | C19 |

Isolation modes:
- **Shared pod:** Multiple sessions share one pod (lower cost, acceptable for interactive)
- **Pod-per-session:** Each session gets its own pod (strongest isolation, for autonomous)

### Step 3: Identity & Credentials

Two tabs: **Quick Setup** and **Enterprise Setup**.

#### Quick Setup (PAT)

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| GitHub PAT | password | no | Stored as K8s Secret, injected by AuthBridge |
| PAT scope description | text | auto | Read from GitHub API after paste |
| Slack bot token | password | no | Stored as Secret, channel-scoped by policy |
| Allowed Slack channels | multi-select | if Slack | Channels the agent can post to |
| LLM API key | password | yes | OpenAI/Anthropic key |

Flow: User pastes PAT → wizard validates it against GitHub API → shows scope summary → stores as Secret → AuthBridge injects on matching outbound requests.

#### Enterprise Setup (GitHub App)

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| GitHub App | select | yes | Lists installed GitHub Apps from org |
| Allowed repos | multi-select | yes | Repos the app has access to |
| Permissions | checkboxes | yes | `contents:write`, `pull_requests:write`, etc. |
| SPIRE identity | toggle | yes (default on) | Enables SVID for AuthBridge token exchange |
| Namespace | select | yes | From Keycloak groups |
| Service account | text | auto | `sandbox-{name}` |

Flow: Wizard creates a `SandboxTokenPolicy` CRD → AuthBridge reads it → exchanges SPIFFE SVID for GitHub App installation token scoped to selected repos/permissions.

```yaml
apiVersion: kagenti.io/v1alpha1
kind: SandboxTokenPolicy
metadata:
  name: my-agent
  namespace: team1
spec:
  spiffeId: spiffe://kagenti/ns/team1/sa/sandbox-my-agent
  github:
    appInstallationId: "12345678"
    repos: ["org/repo1", "org/repo2"]
    permissions:
      contents: write
      pull_requests: write
      issues: read
  slack:
    # Bot token stored as Secret, channel-restricted by policy
    secretRef: slack-bot-secret
    allowedChannels: ["#agent-results", "#ci-notifications"]
    permissions: ["chat:write", "files:write"]
  llm:
    secretRef: openai-secret
    allowedModels: ["gpt-4o-mini", "gpt-4o"]
```

**Slack channel scoping:** AuthBridge intercepts Slack API calls (`api.slack.com/chat.postMessage`) and checks the `channel` parameter against `allowedChannels`. If the agent tries to post to a channel not in the list, the request is blocked before reaching Slack. This is defense-in-depth on top of Slack's own bot permissions.

### Step 4: Persistence

| Field | Type | Default | Notes |
|-------|------|---------|-------|
| Enable session persistence | toggle | on | A2A SDK DatabaseTaskStore |
| PostgreSQL source | radio | In-cluster | In-cluster StatefulSet vs external URL |
| External DB URL | text | — | Only if "External" selected |
| Enable graph checkpointing | toggle | on | LangGraph AsyncPostgresSaver |

In-cluster: wizard deploys `postgres-sessions` StatefulSet + Secret automatically.
External: user provides connection string (RDS, Cloud SQL, etc.).

### Step 5: Observability

| Field | Type | Default | Notes |
|-------|------|---------|-------|
| OTEL endpoint | text | auto | `otel-collector.kagenti-system:8335` |
| MLflow tracking | toggle | on | Traces flow to MLflow via OTEL |
| LLM model | select | `gpt-4o-mini` | From available models |

### Step 6: Review & Deploy

Summary card showing all configuration. Deploy button triggers:
1. Creates K8s Secret (PAT or GitHub App config)
2. Creates SandboxTokenPolicy CRD (enterprise mode)
3. Creates postgres-sessions StatefulSet (if persistence enabled)
4. Creates Shipwright Build + triggers BuildRun
5. Creates Deployment + Service
6. Creates Route with 300s streaming timeout
7. Waits for agent to be ready (polls agent card)
8. Redirects to `/sandbox` chat page

## Token Exchange Flow

```
User in Wizard                    Kubernetes                      Runtime
─────────────                    ──────────                      ───────

[Quick: paste PAT]────────────> Secret
                                  github-pat-{name}
                                  namespace: team1

[Enterprise: select App+repos]─> SandboxTokenPolicy CR
                                  spiffeId, repos, perms

                                 SPIRE registers workload
                                  spiffe://kagenti/ns/team1/
                                  sa/sandbox-{name}

                                                                 Agent starts
                                                                 Gets SVID from SPIRE

                                                                 Agent: git clone org/repo1
                                                                   │
                                                                   ▼
                                                                 Istio → AuthBridge ext_proc
                                                                   │
                                                                 AuthBridge checks:
                                                                 ├─ Quick mode: inject PAT from Secret
                                                                 └─ Enterprise: validate SVID
                                                                    → lookup SandboxTokenPolicy
                                                                    → exchange for GitHub App token
                                                                    → scope to repos + permissions
                                                                    → inject Authorization header
                                                                   │
                                                                   ▼
                                                                 github.com receives scoped token
                                                                 Agent can push to org/repo1 ✓
                                                                 Agent cannot access org/repo3 ✗
```

## Agent Workflow: Create Branch + Send PR

Once deployed, a sandbox agent with proper credentials can:

```python
# Agent has scoped GitHub credentials via AuthBridge
# 1. Clone the repo (AuthBridge injects token for git clone)
shell("git clone https://github.com/org/repo1 /workspace/repo1")

# 2. Create a branch
shell("cd /workspace/repo1 && git checkout -b fix/issue-123")

# 3. Make changes
file_write("/workspace/repo1/src/fix.py", "...")

# 4. Commit and push (AuthBridge injects token for git push)
shell("cd /workspace/repo1 && git add -A && git commit -m 'Fix #123' && git push origin fix/issue-123")

# 5. Create PR via GitHub API (AuthBridge injects token for api.github.com)
web_fetch("POST https://api.github.com/repos/org/repo1/pulls", {
    "title": "Fix #123",
    "head": "fix/issue-123",
    "base": "main"
})
```

The agent never sees the token — AuthBridge transparently injects it.

## UI Components

| Component | File | PatternFly |
|-----------|------|-----------|
| SandboxCreatePage | `pages/SandboxCreatePage.tsx` | Wizard |
| SourceStep | `components/wizard/SourceStep.tsx` | Form |
| SecurityStep | `components/wizard/SecurityStep.tsx` | Form + Toggles |
| IdentityStep | `components/wizard/IdentityStep.tsx` | Tabs + Form |
| PersistenceStep | `components/wizard/PersistenceStep.tsx` | Form + Radio |
| ObservabilityStep | `components/wizard/ObservabilityStep.tsx` | Form |
| ReviewStep | `components/wizard/ReviewStep.tsx` | DescriptionList |

## Playwright Walkthrough Test

`sandbox-create-walkthrough.spec.ts`:
1. `intro` → login
2. `navigate_create` → click "+ New Agent" or navigate to `/sandbox/create`
3. `source_step` → fill repo URL, branch, name
4. `security_step` → configure isolation, allowlist
5. `identity_step` → paste PAT (quick tab) or select GitHub App (enterprise tab)
6. `persistence_step` → enable postgres, verify defaults
7. `observability_step` → verify OTEL endpoint
8. `review_deploy` → click Deploy, wait for build + deployment
9. `verify_agent` → redirect to /sandbox, verify agent responds
10. `end`

## Implementation Priority

1. **Wizard shell** — PatternFly Wizard with 6 steps, navigation, validation
2. **Source + Review steps** — Minimum viable: name, repo, deploy
3. **Security step** — Toggles for C16 hardening defaults
4. **Identity step** — Quick tab (PAT) first, Enterprise tab (GitHub App) later
5. **Persistence + Observability** — Use defaults, let user override
6. **Backend API** — `POST /api/v1/sandbox/create` that orchestrates the deployment
7. **SandboxTokenPolicy CRD** — AuthBridge reads it for scoped token exchange
8. **Playwright walkthrough** — Test the full wizard flow
