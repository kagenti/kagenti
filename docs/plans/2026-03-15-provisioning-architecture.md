# Provisioning Architecture Brainstorm

> **Date:** 2026-03-15
> **Goal:** Simplify kagenti provisioning into clean layers, fix litellm-proxy-secret gap

## Current State (Broken)

### The Problem

`hypershift-full-test.sh` calls these phases:
1. Create cluster
2. Install kagenti (ansible) → deploys platform + team namespaces
3. Build platform images (37)
4. Deploy agent-sandbox controller (35)
5. Deploy test agents (71-76) → weather-tool, weather-agent, sandbox-agents
6. Run E2E tests

**Missing:** `38-deploy-litellm.sh` is **never called**. So:
- No litellm-proxy in kagenti-system
- No litellm-proxy-secret (master key)
- No litellm-virtual-keys in team1
- Sandbox agents crash: `Error: secret "litellm-proxy-secret" not found`

### The Mismatch

The sandbox agent deployment YAMLs hardcode `litellm-proxy-secret` as the LLM key
secret name, but that secret is only created by `38-deploy-litellm.sh` (in
kagenti-system, not team1) or by the wizard (which creates a per-agent secret).

The 38 script creates `litellm-virtual-keys` in team1 (with key `api-key`), but
the deployment references `litellm-proxy-secret` with key `apikey`. Name AND key
mismatch.

### Current Provisioning Layers

```
┌────────────────────────────────────────────────────────────┐
│ L1: CLUSTER (create-cluster.sh)                            │
│     HyperShift/Kind cluster, kubeconfig                    │
├────────────────────────────────────────────────────────────┤
│ L2: PLATFORM (30-run-installer.sh → ansible)               │
│     kagenti-system: UI, backend, gateway, keycloak,        │
│     istio, SPIRE, tekton, phoenix, postgres-otel           │
│     team1/team2: namespaces, secrets (github, openai, etc) │
│     *** MISSING: litellm-proxy ***                         │
├────────────────────────────────────────────────────────────┤
│ L2.5: LITELLM (38-deploy-litellm.sh — NEVER CALLED)       │
│     kagenti-system: litellm-proxy deploy, master key,      │
│     model config from .env.maas                            │
│     team1: litellm-virtual-keys                            │
├────────────────────────────────────────────────────────────┤
│ L3: AGENTS (71-76 scripts)                                 │
│     Build images, deploy agents, create routes             │
│     *** NO virtual key per agent ***                       │
├────────────────────────────────────────────────────────────┤
│ L4: WIZARD (sandbox_deploy.py create_sandbox)              │
│     Creates agent + secret + egress proxy + PVC            │
│     CAN create per-agent LLM secret (llm_key_source=new)  │
│     But defaults to "existing" → litellm-proxy-secret      │
│     which doesn't exist in team1!                          │
└────────────────────────────────────────────────────────────┘
```

## Proposed Architecture

### Design Principles

1. **Each layer provisions its own resources.** No layer depends on manual steps.
2. **Secrets flow down:** kagenti-system holds master keys → team namespaces get
   virtual keys → agents reference namespace-scoped keys.
3. **One secret name for agents:** All agents in a namespace use the same
   `litellm-virtual-keys` secret (not `litellm-proxy-secret`).
4. **Script agents use the same backend API as the wizard.** No duplicated logic.

### Proposed Layers

```
┌────────────────────────────────────────────────────────────┐
│ L1: CLUSTER                                                │
│     create-cluster.sh (unchanged)                          │
├────────────────────────────────────────────────────────────┤
│ L2: PLATFORM INSTALL (ansible + 38-deploy-litellm)         │
│     kagenti-system:                                        │
│       - UI, backend, gateway, keycloak, istio, etc.        │
│       - litellm-proxy (with master key + model config)     │
│       - llm-budget-proxy                                   │
│     team1/team2:                                           │
│       - namespaces + standard secrets                      │
│       - litellm-virtual-keys (per-namespace virtual key)   │
├────────────────────────────────────────────────────────────┤
│ L3: AGENT DEPLOY (via backend API, not kubectl)            │
│     Script does port-forward to kagenti-backend, then      │
│     POST /api/sandbox/{ns}/create — same as wizard         │
│     Backend creates: deployment, service, egress proxy,    │
│     workspace, references litellm-virtual-keys secret      │
├────────────────────────────────────────────────────────────┤
│ L4: E2E TESTS                                              │
│     Tests run against deployed agents                      │
└────────────────────────────────────────────────────────────┘
```

### Key Changes

#### 1. Integrate litellm into platform install

Add `38-deploy-litellm.sh` to `hypershift-full-test.sh` Phase 2, after ansible
completes and postgres-otel is ready:

```bash
# In hypershift-full-test.sh, Phase 2 (after 30-run-installer.sh):
./.github/scripts/kagenti-operator/38-deploy-litellm.sh
```

This creates litellm-proxy + master key + virtual keys for team namespaces.

#### 2. Fix secret name consistency

All sandbox agent deployments should reference `litellm-virtual-keys` with
key `api-key` (the secret created by `38-deploy-litellm.sh`), NOT
`litellm-proxy-secret` with key `apikey`.

Update deployment YAMLs in `kagenti/examples/agents/`:
```yaml
# BEFORE (broken):
- name: LLM_API_KEY
  valueFrom:
    secretKeyRef:
      name: litellm-proxy-secret   # doesn't exist in team1
      key: apikey

# AFTER:
- name: LLM_API_KEY
  valueFrom:
    secretKeyRef:
      name: litellm-virtual-keys   # created by 38-deploy-litellm.sh
      key: api-key
```

Also update `DEFAULT_LLM_SECRET` in `sandbox_deploy.py`:
```python
# BEFORE:
DEFAULT_LLM_SECRET = "litellm-proxy-secret"

# AFTER:
DEFAULT_LLM_SECRET = "litellm-virtual-keys"
DEFAULT_LLM_SECRET_KEY = "api-key"
```

#### 3. Deploy agents via backend API (not raw kubectl)

Replace `76-deploy-sandbox-agents.sh` with a script that port-forwards to the
kagenti backend and calls the wizard API:

```bash
#!/usr/bin/env bash
# 76-deploy-sandbox-agents.sh (new version)

# Port-forward to backend
kubectl port-forward -n kagenti-system svc/kagenti-backend 18080:8080 &
PF_PID=$!
trap "kill $PF_PID" EXIT
sleep 5

# Get auth token
TOKEN=$(curl -s http://localhost:18080/api/auth/token \
  -d "username=admin&password=${KEYCLOAK_PASSWORD}" | jq -r .access_token)

# Deploy each variant via the wizard API
for variant in sandbox-agent sandbox-legion; do
  curl -X POST "http://localhost:18080/api/sandbox/team1/create" \
    -H "Authorization: Bearer $TOKEN" \
    -H "Content-Type: application/json" \
    -d "{
      \"name\": \"$variant\",
      \"base_agent\": \"$variant\",
      \"model\": \"llama-4-scout\",
      \"llm_key_source\": \"existing\",
      \"llm_secret_name\": \"litellm-virtual-keys\"
    }"
done
```

**Benefits:**
- Single source of truth for agent deployment logic (backend)
- Wizard and scripts produce identical deployments
- New features (budget proxy, egress proxy, PVC) automatically available
- No drift between wizard-deployed and script-deployed agents

**Risks:**
- Backend must be running before agents can deploy (ordering dependency)
- Need auth token flow in scripts
- Backend API may not support all deployment patterns (e.g., weather-tool
  is an MCP tool, not a sandbox agent)

**Mitigation:** Keep weather-tool/weather-agent as kubectl-deployed (they're
simple MCP tools, not sandbox agents). Only sandbox agents go through the API.

#### 4. Budget proxy per namespace (already exists in wizard)

The wizard already deploys `llm-budget-proxy` per agent. For script-deployed
agents, ensure the budget proxy is deployed once per namespace:

Option A: Deploy as part of team namespace provisioning (38-deploy-litellm.sh)
Option B: Backend auto-deploys on first agent create (current wizard behavior)

Option B is cleaner — the budget proxy deployment is already in the wizard code.

### Full-Test Script Phase Map (Proposed)

```
Phase 1: Create Cluster
  └─ create-cluster.sh

Phase 2: Install Platform
  ├─ 30-run-installer.sh (ansible: kagenti-system + team namespaces)
  ├─ 41-wait-crds.sh
  ├─ 42-apply-pipeline-template.sh
  ├─ 38-deploy-litellm.sh (NEW: litellm + virtual keys)   ← ADD THIS
  ├─ 37-build-platform-images.sh (UI + backend from source)
  └─ 35-deploy-agent-sandbox.sh (sandbox controller)

Phase 3: Deploy Agents
  ├─ 71-build-weather-tool.sh (MCP tool — stays as kubectl)
  ├─ 72-deploy-weather-tool.sh
  ├─ 74-deploy-weather-agent.sh
  └─ 76-deploy-sandbox-agents.sh (CHANGE: use backend API)

Phase 4: Run Tests
  ├─ 90-run-e2e-tests.sh (backend E2E)
  └─ 92-run-ui-tests.sh (Playwright E2E)

Phase 5: Uninstall (optional)
Phase 6: Destroy Cluster (optional)
```

### Secret Flow Diagram

```
.env.maas (MAAS model keys)
     │
     ▼
38-deploy-litellm.sh
     │
     ├─► kagenti-system/litellm-proxy-secret
     │     master-key: sk-kagenti-{hex}
     │     database-url: postgresql://...
     │
     ├─► kagenti-system/litellm-model-keys
     │     MAAS_LLAMA4_API_KEY, MAAS_MISTRAL_API_KEY, etc.
     │
     ├─► kagenti-system/litellm-config (ConfigMap)
     │     model routing: llama-4-scout → MAAS endpoint
     │
     └─► team1/litellm-virtual-keys
           api-key: sk-{virtual-key}
                │
                ▼
         Agent Deployments (all agents in team1)
           LLM_API_KEY → secretKeyRef: litellm-virtual-keys/api-key
           LLM_API_BASE → http://llm-budget-proxy.team1.svc:8080/v1
                │
                ▼
         llm-budget-proxy (team1)
           Checks budget → forwards to litellm-proxy
                │
                ▼
         litellm-proxy (kagenti-system)
           Routes to MAAS/OpenAI using model config
```

## Immediate Action Plan

### Quick Fix (sandbox42 — unblock now)

1. Run `38-deploy-litellm.sh` manually on sandbox42
2. Fix sandbox-agent deployment to reference `litellm-virtual-keys`/`api-key`
3. Restart sandbox-agent pods

### Proper Fix (sandbox43 — deploy clean)

1. Add `38-deploy-litellm.sh` call to `hypershift-full-test.sh` Phase 2
2. Update all sandbox agent deployment YAMLs to use `litellm-virtual-keys`
3. Update `DEFAULT_LLM_SECRET` in `sandbox_deploy.py`
4. Copy `.env.maas` to worktree (or make 38 script worktree-aware)
5. Deploy sandbox43 with full-test → verify end-to-end

### Future (after tests pass)

1. Convert `76-deploy-sandbox-agents.sh` to use backend API
2. Move litellm into kagenti-deps or kagenti Helm chart
3. Per-agent virtual keys (not per-namespace) for better isolation

## Open Questions

1. **Should litellm be in the Helm chart?** Currently it's a separate script.
   Moving it to kagenti-deps chart would make it declarative and idempotent.
   But it needs `.env.maas` values at install time → Helm values or external secret.

2. **Per-namespace vs per-agent virtual keys?** Currently one key per namespace
   (team1-agents). The wizard can create per-agent keys. Which is default?

3. **Budget proxy: one per namespace or one per agent?** The wizard creates one
   per agent. For simplicity, one per namespace (shared) would be cleaner.
   Per-agent adds isolation but more pods.

4. **Weather-tool/weather-agent via API?** These are MCP tools, not sandbox agents.
   The wizard API is sandbox-specific. Keep as kubectl for now?
