# Deployment

---

## Components per Namespace

Each agent namespace (e.g. `team1`) gets these components:

| Component | Type | Purpose |
|-----------|------|---------|
| `postgres-sessions` | StatefulSet | Sessions DB + LLM budget DB |
| `llm-budget-proxy` | Deployment | Per-session token enforcement |
| Sandbox agent(s) | Deployment | Agent pods (one per variant) |
| Egress proxy | Deployment | Squid domain allowlist (optional, per agent) |

Platform-wide components in `kagenti-system`:

| Component | Purpose |
|-----------|---------|
| `kagenti-backend` | FastAPI backend with sandbox routes |
| `kagenti-ui` | React frontend |
| `litellm-proxy` | Model routing and spend tracking |
| `keycloak` | OIDC provider |
| `kagenti-webhook` (in `kagenti-webhook-system`) | Mutating webhook that injects AuthBridge sidecars into agent pods |
| `spire-server` / `spire-agent` | Workload identity |
| `otel-collector` | Trace collection |
| `phoenix` | LLM observability |

---

## Deploy Scripts

| Script | Purpose |
|--------|---------|
| `kind-full-test.sh` | Full platform on Kind (all components) |
| `38-deploy-litellm.sh` | LiteLLM proxy to kagenti-system |
| `76-deploy-sandbox-agents.sh` | Sandbox agents, PostgreSQL, budget proxy |
| `35-deploy-agent-sandbox.sh` | Agent-sandbox CRDs (SandboxTemplate, SandboxClaim) |

### 76-deploy-sandbox-agents.sh

This is the main sandbox deployment script. It:

1. Creates the `postgres-sessions` StatefulSet with two databases:
   - `sessions` -- session metadata, events, tasks, checkpoints
   - `llm_budget` -- LLM call tracking, budget limits
2. Builds the LLM budget proxy image (OpenShift BuildConfig or local build)
3. Deploys sandbox agent variant(s) with selected security profile
4. Creates egress proxy if the profile includes L7

---

## Database Setup

### PostgreSQL StatefulSet

Each namespace gets a `postgres-sessions` StatefulSet deployed from
`deployments/sandbox/postgres-sessions.yaml`:

- User: `kagenti`
- Password: from `postgres-sessions-secret` (default: `kagenti-sessions-dev`)
- Databases: `sessions`, `llm_budget`
- Storage: PVC (production) or emptyDir (dev)

### Auto-Migration

Tables are created automatically:

| Tables | Created By | When |
|--------|-----------|------|
| `sessions`, `events` | Backend auto-migration | On backend startup |
| `tasks` | A2A SDK `DatabaseTaskStore` | On first task creation |
| `checkpoints`, `checkpoint_writes`, `checkpoint_blobs` | LangGraph `AsyncPostgresSaver.setup()` | On agent startup |
| `llm_calls`, `budget_limits` | LLM Budget Proxy | On proxy startup |

No manual schema setup is needed.

### Connection Strings

| Client | DSN |
|--------|-----|
| Backend | `postgresql://kagenti:<pw>@postgres-sessions.<ns>:5432/sessions` |
| Agent | `postgresql://kagenti:<pw>@postgres-sessions.<ns>:5432/sessions` |
| Budget Proxy | `postgresql://kagenti:<pw>@postgres-sessions.<ns>:5432/llm_budget` |

SSL is disabled at the application level -- Istio Ambient ztunnel provides mTLS.

---

## LLM Budget Proxy

Deployed from `deployments/sandbox/llm-budget-proxy.yaml`:

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: llm-budget-proxy
  namespace: team1
spec:
  containers:
    - name: proxy
      image: llm-budget-proxy:latest
      env:
        - name: LITELLM_URL
          value: http://litellm-proxy.kagenti-system.svc.cluster.local:4000
        - name: DATABASE_URL
          valueFrom:
            secretKeyRef:
              name: postgres-sessions-secret
              key: llm-budget-db-url
      ports:
        - containerPort: 8080
      resources:
        requests: { cpu: 50m, memory: 128Mi }
        limits: { cpu: 200m, memory: 256Mi }
---
apiVersion: v1
kind: Service
metadata:
  name: llm-budget-proxy
  namespace: team1
spec:
  ports:
    - port: 8080
      targetPort: 8080
```

Agents set `LLM_API_BASE=http://llm-budget-proxy:8080` to route all LLM
calls through the proxy.

---

## Platform Base Image

The platform base image (`deployments/sandbox/platform_base/`) provides
common infrastructure for all framework adapters:

```
platform_base/
├── entrypoint.py      # Plugin loader + A2A server bootstrap
├── permissions.py     # Three-tier permission checker
├── sources.py         # Capability declarations
├── workspace.py       # Per-context workspace isolation
└── requirements.txt   # Platform dependencies
```

Build the base image:

```bash
docker build -f deployments/sandbox/Dockerfile.base \
  -t kagenti-agent-base:latest \
  deployments/sandbox/
```

Framework adapters extend this image (see [Writing Agents](./agents.md)).

---

## Agent Manifests

### Directory Structure

```
deployments/sandbox/
├── agents/
│   ├── legion/           # LangGraph persistent agent
│   │   ├── Dockerfile
│   │   ├── deployment.yaml
│   │   └── ...
│   └── opencode/         # OpenCode adapter (WIP)
│       ├── Dockerfile
│       ├── plugin.py
│       └── deployment.yaml
├── platform_base/        # Shared base image
├── proxy/                # Squid egress proxy
│   ├── Dockerfile
│   ├── squid.conf
│   └── entrypoint.sh
├── llm-budget-proxy.yaml
├── postgres-sessions.yaml
├── sandbox_profile.py    # Security profile builder
└── agent_server.py       # A2A server utilities
```

### Agent Container Resources

| Container | CPU Request | CPU Limit | Memory Request | Memory Limit |
|-----------|------------|-----------|---------------|-------------|
| Agent | 250m | 2 | 512Mi | 4Gi |
| Egress Proxy | 50m | 200m | 128Mi | 256Mi |
| Budget Proxy | 50m | 200m | 128Mi | 256Mi |

---

## Helm Chart

The main Helm chart (`charts/kagenti/`) manages:

- Feature flag env vars on backend and UI deployments
- Agent namespace creation with Istio Ambient labels
- PostgreSQL secrets in agent namespaces
- RBAC roles scoped by feature flags

Key template: `charts/kagenti/templates/agent-namespaces.yaml` creates
per-namespace resources when `featureFlags.sandbox` is `true`.
