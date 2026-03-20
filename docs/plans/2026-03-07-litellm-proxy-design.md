# LiteLLM Proxy Gateway — Design & Implementation Plan

> **Date:** 2026-03-07
> **Session:** Q (LiteLLM Proxy)
> **Cluster:** sandbox44 (to be created)
> **Status:** Approved by Coordinator brainstorm

## Problem

Agents currently talk directly to MAAS/OpenAI endpoints. Each agent has its own `LLM_API_BASE` + `LLM_API_KEY` env vars. To switch models, we patch every deployment individually. No centralized token tracking, no per-session spend visibility, no quick model switching.

## Solution

Deploy LiteLLM as a centralized proxy in `kagenti-system`. All agents point to it. LiteLLM handles model routing, API key management, and spend tracking.

## Architecture

```
┌─────────────────┐
│  Kagenti UI     │──── GET /api/v1/sessions/{id}/tokens ────┐
└─────────────────┘                                          │
                                                             ▼
┌─────────────────┐     ┌───────────────────┐     ┌──────────────────┐
│ sandbox-legion  │────▶│  litellm-proxy    │────▶│ MAAS Llama Scout  │
│ sandbox-basic   │     │  (kagenti-system) │     │ MAAS Mistral      │
│ sandbox-hardened│────▶│                   │────▶│ MAAS DeepSeek     │
│ rca-agent       │     │  :4000/v1/chat/   │     │ OpenAI (optional) │
│ weather-service │────▶│  completions      │     │ vLLM (optional)   │
└─────────────────┘     │                   │     └──────────────────┘
                        │  ┌─────────────┐  │
                        │  │ PostgreSQL  │  │ ◀── spend/logs, tags
                        │  │ (spend DB)  │  │
                        │  └─────────────┘  │
                        └───────────────────┘
```

### Agent Change (minimal)

```yaml
# Before (direct to MAAS):
- name: LLM_API_BASE
  value: "https://llama-4-scout-...apps.prod.rhoai.../v1"
- name: LLM_API_KEY
  value: "51cd949e..."
- name: LLM_MODEL
  value: "llama-4-scout-17b-16e-w4a16"

# After (via LiteLLM proxy):
- name: LLM_API_BASE
  value: "http://litellm-proxy.kagenti-system.svc:4000/v1"
- name: LLM_API_KEY
  valueFrom:
    secretKeyRef:
      name: litellm-proxy-secret
      key: virtual-key
- name: LLM_MODEL
  value: "llama-4-scout"  # friendly alias
```

No agent code changes needed — LiteLLM exposes OpenAI-compatible `/v1/chat/completions`.

## Metadata Tagging (per-session token tracking)

Every LLM call must include metadata for spend attribution:

```python
response = litellm.completion(
    model=self.model,
    messages=messages,
    metadata={
        "session_id": context_id,           # this session
        "parent_session": parent_context_id, # who spawned this session (if sub-agent)
        "root_session": root_context_id,     # top-level user session
        "agent_name": agent_name,            # e.g. "sandbox-legion"
        "namespace": namespace,              # e.g. "team1"
    }
)
```

### Session Hierarchy

```
root_session: "user-abc-123"          ← user starts chat
  ├── session_id: "user-abc-123"      ← main session tokens
  ├── parent_session: null
  │
  ├── session_id: "sub-research-456"  ← sub-agent spawned by legion
  │   ├── parent_session: "user-abc-123"
  │   └── root_session: "user-abc-123"
  │
  └── session_id: "sub-verify-789"    ← another sub-agent
      ├── parent_session: "user-abc-123"
      └── root_session: "user-abc-123"
```

Query patterns:
- **Session total:** `GET /spend/tags?tags=session_id:user-abc-123`
- **Full tree total:** `GET /spend/tags?tags=root_session:user-abc-123`
- **Sub-agents only:** full tree minus root session's own tokens

## Implementation Tasks

### Task 1: Deploy LiteLLM Proxy

**Files:**
- `charts/kagenti/templates/litellm-deployment.yaml`
- `charts/kagenti/templates/litellm-service.yaml`
- `charts/kagenti/templates/litellm-configmap.yaml`

**Deployment spec:**
```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: litellm-proxy
  namespace: kagenti-system
spec:
  replicas: 1
  selector:
    matchLabels:
      app: litellm-proxy
  template:
    spec:
      containers:
      - name: litellm
        image: ghcr.io/berriai/litellm:main-latest
        ports:
        - containerPort: 4000
        env:
        - name: DATABASE_URL
          value: "postgresql://kagenti:kagenti@postgres-otel-0.postgres-otel.kagenti-system:5432/litellm"
        - name: LITELLM_MASTER_KEY
          valueFrom:
            secretKeyRef:
              name: litellm-proxy-secret
              key: master-key
        volumeMounts:
        - name: config
          mountPath: /app/config.yaml
          subPath: config.yaml
      volumes:
      - name: config
        configMap:
          name: litellm-config
```

**ConfigMap (generated from `.env.maas`):**
```yaml
model_list:
  - model_name: llama-4-scout
    litellm_params:
      model: openai/llama-4-scout-17b-16e-w4a16
      api_base: https://llama-4-scout-...apps.prod.rhoai.../v1
      api_key: os.environ/MAAS_LLAMA4_API_KEY

  - model_name: mistral-small
    litellm_params:
      model: openai/mistral-small-24b-w8a8
      api_base: https://mistral-small-...apps.prod.rhoai.../v1
      api_key: os.environ/MAAS_MISTRAL_API_KEY

  - model_name: deepseek-r1
    litellm_params:
      model: openai/r1-qwen-14b-w4a16
      api_base: https://deepseek-r1-...apps.prod.rhoai.../v1
      api_key: os.environ/MAAS_DEEPSEEK_API_KEY

general_settings:
  master_key: os.environ/LITELLM_MASTER_KEY
  database_url: os.environ/DATABASE_URL
```

### Task 2: Create Deploy Script

**File:** `.github/scripts/kagenti-operator/38-deploy-litellm.sh`

Steps:
1. Read model credentials from `.env.maas`
2. Generate ConfigMap with model aliases
3. Create `litellm-proxy-secret` with master key + virtual keys
4. Apply deployment + service
5. Wait for rollout
6. Create DB schema (LiteLLM auto-migrates on startup)
7. Create virtual API keys per namespace via LiteLLM API

### Task 3: Wire Agents to Proxy

Update `76-deploy-sandbox-agents.sh` and `74-deploy-weather-agent.sh`:
- Set `LLM_API_BASE=http://litellm-proxy.kagenti-system.svc:4000/v1`
- Set `LLM_API_KEY` from `litellm-proxy-secret` virtual key
- Set `LLM_MODEL` to friendly alias (e.g., `llama-4-scout`)

### Task 4: Add Metadata Tagging

**File:** `deployments/sandbox/agent_server.py` (modify existing `litellm.completion()` call)

Add `metadata` dict with:
- `session_id` — current context_id
- `parent_session` — from task metadata `parent_context_id` (if sub-agent)
- `root_session` — walk up parent chain to find root, or from task metadata `root_context_id`
- `agent_name` — from env var or agent card
- `namespace` — from env var

Also update `graph.py` if it calls LLM directly via LangChain — pass metadata through `ChatLiteLLM` or `ChatOpenAI` kwargs.

### Task 5: Expose Stats API in Backend

**File:** `kagenti/backend/app/routers/token_usage.py` (NEW)

Endpoints:
```
GET /api/v1/sessions/{context_id}/tokens
  → proxy to LiteLLM: GET /spend/tags?tags=session_id:{context_id}
  → returns: { total_tokens, prompt_tokens, completion_tokens, model, cost_usd }

GET /api/v1/sessions/{context_id}/tokens/tree
  → proxy to LiteLLM: GET /spend/tags?tags=root_session:{context_id}
  → returns: { total, breakdown: [{session_id, agent_name, tokens, model}] }
```

### Task 6: Wire into Deploy Pipeline

**File:** `.github/scripts/local-setup/hypershift-full-test.sh`

Add after `36-fix-keycloak-admin.sh`, before `76-deploy-sandbox-agents.sh`:
```bash
log_step "Deploying LiteLLM proxy..."
./.github/scripts/kagenti-operator/38-deploy-litellm.sh
```

### Task 7: Model Management API

**File:** `kagenti/backend/app/routers/models.py` (NEW)

Proxy LiteLLM's model management:
```
GET  /api/v1/models          → LiteLLM GET /model/info
POST /api/v1/models          → LiteLLM POST /model/new
DELETE /api/v1/models/{name} → LiteLLM POST /model/delete
```

UI model picker reads from this instead of hardcoded list.

## Testing

- `kagenti/ui-v2/e2e/litellm-proxy.spec.ts` — verify proxy health, model listing, agent chat works through proxy
- Backend unit tests for `token_usage.py` and `models.py` routers
- Integration: run full Playwright suite — all 192+ tests should still pass with agents going through proxy

## Model Compatibility

| Model | tool_choice=auto | Via LiteLLM Proxy | Recommended |
|-------|-----------------|-------------------|-------------|
| Llama 4 Scout 17B-16E | ✅ 10/10 | ✅ | Default |
| Mistral Small 3.1 24B | ❌ 0/10 | ✅ (text only) | No — no tool calling |
| DeepSeek R1 Qwen 14B | ❌ no tools | ✅ (text only) | No |

## Security

- **Istio Ambient mTLS**: agent → proxy is pod-to-pod, auto-encrypted
- **Virtual API keys**: each namespace gets its own key, spend tracked separately
- **Master key**: only for admin API (model management, key creation). Stored in K8s secret.
- **Real API keys**: stored in LiteLLM config, never exposed to agents
