# Quick Start

Deploy a sandbox agent on a local Kind cluster in 5 minutes.

---

## Prerequisites

- Docker Desktop running
- `kubectl`, `helm`, `uv` installed
- Clone the kagenti repo

## 1. Deploy the Platform

```bash
# Full platform deployment (creates Kind cluster, installs all components)
./.github/scripts/local-setup/kind-full-test.sh --skip-cluster-destroy
```

This deploys: Keycloak, Istio Ambient, SPIRE, AuthBridge webhook, LiteLLM,
Phoenix, OTEL Collector, MCP Gateway, and the Kagenti backend + UI.

## 2. Enable Feature Flags

Feature flags are disabled by default. To enable the Agentic Runtime:

```bash
# Edit the Helm values to enable sandbox features
# In charts/kagenti/values.yaml:
#   featureFlags:
#     sandbox: true
#     integrations: true
#     triggers: true

# Or pass at install time:
helm upgrade kagenti charts/kagenti \
  --set featureFlags.sandbox=true \
  --set featureFlags.integrations=true \
  --set featureFlags.triggers=true
```

## 3. Deploy a Sandbox Agent

```bash
# Deploy sandbox agents with PostgreSQL, budget proxy, and egress proxy
./.github/scripts/kagenti-operator/76-deploy-sandbox-agents.sh
```

This creates in the `team1` namespace:
- `postgres-sessions` StatefulSet (sessions + llm_budget databases)
- `llm-budget-proxy` Deployment (token enforcement)
- Sandbox agent Deployment(s) with selected security profile

## 4. Access the UI

```bash
# Show all service URLs
./.github/scripts/local-setup/show-services.sh
```

Open http://kagenti-ui.localtest.me:8080 and log in with `admin/admin`.

Navigate to the **Sandboxes** page to see deployed agents, then open a
session to start chatting.

## 5. Send a Message

In the sandbox session view:
1. Select an agent from the catalog
2. Type a message (e.g. "Analyze the file structure of this workspace")
3. Watch the reasoning loop in real-time:
   - Planner creates a numbered plan
   - Executor runs tools (shell commands, file reads)
   - Reflector decides whether to continue or finish
   - Reporter synthesizes the final answer

The Graph View tab shows the agent's processing graph with live animations.

## Next Steps

- [Configuration](./configuration.md) -- feature flags, Helm values, env vars
- [Security](./security.md) -- composable security layers, Landlock
- [Writing Agents](./agents.md) -- create your own sandbox agent
- [Deployment](./deployment.md) -- production deployment, database setup
