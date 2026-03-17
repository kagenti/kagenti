# Configuration

---

## Feature Flags

The Agentic Runtime is gated behind three feature flags that flow from Helm
values through backend environment variables to the UI config endpoint.

```
Helm values.yaml          Backend env var                    UI config endpoint
-----------------          ---------------                   ------------------
featureFlags:              KAGENTI_FEATURE_FLAG_SANDBOX      GET /api/v1/config/features
  sandbox: false    -->    KAGENTI_FEATURE_FLAG_INTEGRATIONS -->  { sandbox: bool,
  integrations: false      KAGENTI_FEATURE_FLAG_TRIGGERS           integrations: bool,
  triggers: false                                                  triggers: bool }
```

| Flag | What It Gates | Default | OCP |
|------|--------------|---------|-----|
| `SANDBOX` | All sandbox routes, sessions, sidecars, RBAC, deploy API | `false` | `true` |
| `INTEGRATIONS` | Integrations page (external service connections) | `false` | `true` |
| `TRIGGERS` | Trigger management (cron, webhook, alert -> agent) | `false` | `true` |

### Backend Behavior

When a flag is `false`, the backend skips importing the corresponding router
modules. The routes simply don't exist -- no 403, no error, just not registered.

Each feature-flagged module uses `try/except ImportError` so that missing
dependencies (only installed when the feature is enabled) don't crash the
backend.

### RBAC Scoping

When `SANDBOX` is `false`, the backend ClusterRole does NOT include
pods/exec, secrets, or configmaps permissions. These are only added when the
flag is enabled, preventing cluster-wide privilege escalation when sandbox
is off.

---

## Helm Values

Key values in `charts/kagenti/values.yaml`:

### Feature Flags

```yaml
featureFlags:
  sandbox: false
  integrations: false
  triggers: false
```

### Agent Namespaces

```yaml
agentNamespaces:
  - team1
  - team2
```

Each namespace gets:
- Istio Ambient mesh enrollment
- PostgreSQL `postgres-sessions` StatefulSet (when sandbox enabled)
- RBAC roles for the backend service account

---

## Environment Variables

### Backend (FastAPI)

| Variable | Description | Default |
|----------|-------------|---------|
| `KAGENTI_FEATURE_FLAG_SANDBOX` | Enable sandbox routes | `false` |
| `KAGENTI_FEATURE_FLAG_INTEGRATIONS` | Enable integrations routes | `false` |
| `KAGENTI_FEATURE_FLAG_TRIGGERS` | Enable trigger routes | `false` |
| `KEYCLOAK_URL` | Keycloak OIDC provider URL | -- |
| `KEYCLOAK_REALM` | Keycloak realm name | `kagenti` |

### Sandbox Agent

| Variable | Description | Default |
|----------|-------------|---------|
| `AGENT_MODULE` | Python module implementing plugin contract | -- |
| `LLM_API_BASE` | LLM endpoint (usually budget proxy) | `http://llm-budget-proxy:8080` |
| `LLM_MODEL` | Default LLM model | `llama-4-scout-17b` |
| `SANDBOX_LANDLOCK` | Enable Landlock filesystem isolation | `false` |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | OpenTelemetry collector endpoint | -- |
| `TASK_STORE_DB_URL` | PostgreSQL connection for A2A task store | -- |
| `WORKSPACE_ROOT` | Root directory for per-session workspaces | `/workspace` |
| `SKILL_REPOS` | Comma-separated git URLs for skill loading | -- |

### LLM Budget Proxy

| Variable | Description | Default |
|----------|-------------|---------|
| `LITELLM_URL` | LiteLLM proxy endpoint | `http://litellm-proxy.kagenti-system:4000` |
| `DATABASE_URL` | PostgreSQL connection for budget tracking | -- |

### Egress Proxy (Squid)

| Variable | Description | Default |
|----------|-------------|---------|
| `ALLOWED_DOMAINS` | Space-separated domain allowlist | -- |

---

## Budget Limits

Default budget limits inserted by the LLM Budget Proxy on startup:

| Scope | Default | Window |
|-------|---------|--------|
| Per-session | 1,000,000 tokens | None (session-scoped) |
| Per-agent daily | 5,000,000 tokens | 24h rolling |
| Per-agent monthly | 50,000,000 tokens | 30d rolling |

These can be overridden by inserting rows into the `budget_limits` table
in the `llm_budget` database.

---

## Permission Rules

Agent permissions are configured in `settings.json` using the three-tier
system (ALLOW / DENY / HITL):

```json
{
  "permissions": {
    "allow": [
      "shell(grep:*)",
      "shell(find:*)",
      "shell(cat:*)",
      "file(read:/workspace/**)",
      "file(write:/workspace/**)"
    ],
    "deny": [
      "shell(rm:-rf *)",
      "shell(curl:*)",
      "network(outbound:*)"
    ]
  }
}
```

Rules use `type(prefix:glob)` format. Commands not matching allow or deny
rules default to HITL (human-in-the-loop approval).

## Source Capabilities

Agent capabilities are declared in `sources.json`:

```json
{
  "package_managers": {
    "pip": { "enabled": true, "blocked_packages": ["os", "subprocess"] }
  },
  "git": {
    "enabled": true,
    "allowed_remotes": ["github.com/kagenti/*"]
  },
  "web": {
    "enabled": true,
    "allowed_domains": ["api.github.com", "pypi.org"],
    "blocked_domains": ["malware.example.com"]
  },
  "runtime": {
    "max_execution_time_seconds": 300,
    "max_memory_mb": 4096
  }
}
```
