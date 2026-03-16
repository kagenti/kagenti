# Virtual Key Management — Backend-Driven Design

> **Date:** 2026-03-15
> **Context:** litellm-proxy-secret missing on fresh deploys, no key management API
> **Goal:** Backend owns all virtual key lifecycle; scripts and tests call backend API

## Current State

### What Exists

| Component | Status | Location |
|-----------|--------|----------|
| LiteLLM proxy deployment | Script only (`38-deploy-litellm.sh`) | Not in full-test pipeline |
| Master key generation | In 38 script | `sk-kagenti-{hex}` |
| Team-level virtual key | In 38 script (one for team1) | `litellm-virtual-keys` secret |
| Per-agent virtual key | **Not implemented** | Wizard just wraps raw keys |
| Backend key management API | **Missing** | No endpoints |
| Backend model listing | Exists | `GET /api/v1/models` (proxies litellm) |
| Token usage tracking | Exists | `GET /api/v1/token-usage/sessions/{id}` |

### What's Broken

1. `38-deploy-litellm.sh` is never called by `hypershift-full-test.sh`
2. Sandbox agent deployments reference `litellm-proxy-secret` (doesn't exist in team1)
3. Wizard creates raw k8s secrets, not litellm virtual keys
4. No per-agent key isolation — all agents in a namespace share one key or use raw keys
5. No way to set model restrictions or budgets per agent via litellm

## Proposed Design

### Key Hierarchy

```
Master Key (kagenti-system, never exposed to agents)
  │
  ├─► Team "team1" (litellm team)
  │     max_budget: $500/30d
  │     models: [llama-4-scout, mistral-small, deepseek-r1]
  │     │
  │     ├─► team1-default key (namespace-wide fallback)
  │     │     stored in: team1/litellm-virtual-keys
  │     │     max_budget: inherits from team
  │     │     models: inherits from team
  │     │
  │     ├─► rca-agent key (per-agent)
  │     │     stored in: team1/rca-agent-llm-key
  │     │     max_budget: $50/30d
  │     │     models: [llama-4-scout]
  │     │
  │     └─► sandbox-agent key (per-agent)
  │           stored in: team1/sandbox-agent-llm-key
  │           max_budget: $100/30d
  │           models: [llama-4-scout, mistral-small]
  │
  └─► Team "team2"
        max_budget: $200/30d
        models: [mistral-small]
```

LiteLLM enforces the hierarchy:
- Agent key budget can't exceed team budget
- Agent key models must be subset of team models
- Team budget is the aggregate cap for all agents in that namespace

### Backend API Endpoints (New)

All key management goes through the kagenti backend. The backend holds the
litellm master key and proxies to litellm's admin API.

```
# ─── Team (Namespace) Key Management ───────────────────────────

POST   /api/v1/llm/teams
       Create a litellm team for a namespace
       Body: { namespace, max_budget?, budget_duration?, models? }
       Returns: { team_id, namespace }

GET    /api/v1/llm/teams
       List all litellm teams
       Returns: [{ team_id, namespace, max_budget, models }]

GET    /api/v1/llm/teams/{namespace}
       Get team details for a namespace
       Returns: { team_id, namespace, max_budget, budget_used, models, keys[] }

# ─── Agent Key Management ──────────────────────────────────────

POST   /api/v1/llm/keys
       Create a virtual key for an agent (under its namespace's team)
       Body: { namespace, agent_name, max_budget?, models?, budget_duration? }
       Returns: { key_alias, secret_name }
       Side effect: creates k8s secret {agent_name}-llm-key in namespace

GET    /api/v1/llm/keys?namespace={ns}
       List all virtual keys in a namespace
       Returns: [{ key_alias, agent_name, max_budget, budget_used, models }]

DELETE /api/v1/llm/keys/{namespace}/{agent_name}
       Revoke an agent's virtual key
       Side effect: deletes k8s secret

# ─── Models ────────────────────────────────────────────────────

GET    /api/v1/models                          (already exists)
       List available models from litellm
```

### Backend Implementation

The backend needs access to litellm's master key. It already has `LITELLM_BASE_URL`
configured. Add `LITELLM_MASTER_KEY` env var (from `litellm-proxy-secret` in
kagenti-system).

```python
# kagenti/backend/app/routers/llm_keys.py

LITELLM_URL = os.environ.get("LITELLM_BASE_URL", "http://litellm-proxy.kagenti-system.svc:4000")
LITELLM_MASTER_KEY = os.environ.get("LITELLM_MASTER_KEY", "")

async def create_team(namespace: str, max_budget: float = 500, models: list[str] | None = None):
    """Create a litellm team for a namespace."""
    resp = httpx.post(f"{LITELLM_URL}/team/new", headers=master_headers(), json={
        "team_alias": namespace,
        "max_budget": max_budget,
        "budget_duration": "30d",
    })
    team_id = resp.json()["team_id"]

    # Create default namespace key under team
    key_resp = httpx.post(f"{LITELLM_URL}/key/generate", headers=master_headers(), json={
        "team_id": team_id,
        "key_alias": f"{namespace}-default",
        "metadata": {"namespace": namespace, "type": "namespace-default"},
    })
    virtual_key = key_resp.json()["token"]

    # Store as k8s secret
    kube.create_secret(namespace, "litellm-virtual-keys",
                       string_data={"api-key": virtual_key})

    return {"team_id": team_id, "namespace": namespace}


async def create_agent_key(namespace: str, agent_name: str,
                           max_budget: float = 100, models: list[str] | None = None):
    """Create a per-agent virtual key under the namespace's team."""
    # Look up team_id for this namespace
    team_id = await _get_team_id(namespace)

    resp = httpx.post(f"{LITELLM_URL}/key/generate", headers=master_headers(), json={
        "team_id": team_id,
        "key_alias": agent_name,
        "max_budget": max_budget,
        "budget_duration": "30d",
        **({"models": models} if models else {}),
        "metadata": {"namespace": namespace, "agent": agent_name},
    })
    virtual_key = resp.json()["token"]

    # Store as k8s secret
    secret_name = f"{agent_name}-llm-key"
    kube.create_secret(namespace, secret_name,
                       string_data={"apikey": virtual_key},
                       labels={"kagenti.io/agent": agent_name})

    return {"key_alias": agent_name, "secret_name": secret_name}
```

### Wizard Integration

Update `sandbox_deploy.py` to call the new key management API:

```python
# When llm_key_source="new" — instead of wrapping raw key:
if request.llm_key_source == "new":
    # Create per-agent virtual key via litellm
    result = await create_agent_key(
        namespace=namespace,
        agent_name=request.name,
        max_budget=request.max_budget or 100,
        models=[request.model] if request.model else None,
    )
    llm_secret = result["secret_name"]

# When llm_key_source="existing" — use namespace default key:
else:
    llm_secret = request.llm_secret_name or "litellm-virtual-keys"
```

### Provisioning Flow (Full-Test Script)

```
Phase 2: Platform Install
  ├─ 30-run-installer.sh (ansible)
  ├─ 38-deploy-litellm.sh             ← deploys litellm-proxy + master key
  ├─ 37-build-platform-images.sh      ← builds backend (with new key mgmt code)
  │
  │  Backend is now running with LITELLM_MASTER_KEY
  │
  ├─ POST /api/v1/llm/teams           ← creates team for team1 + default key
  │     { namespace: "team1" }           stored in team1/litellm-virtual-keys
  │
  └─ POST /api/v1/llm/teams           ← creates team for team2 + default key
        { namespace: "team2" }

Phase 3: Deploy Agents
  ├─ 76-deploy-sandbox-agents.sh
  │   For each agent variant:
  │     POST /api/v1/llm/keys         ← creates per-agent key
  │       { namespace: "team1", agent_name: "sandbox-agent" }
  │     Then kubectl apply deployment (referencing the new secret)
  │
  └─ Wizard-deployed agents also go through same API
```

### Test Integration

Tests call the backend API to set up LLM infrastructure before running:

```typescript
// e2e/fixtures/llm-setup.ts

export async function ensureLlmTeam(api: APIRequestContext, namespace: string) {
  // Create team if not exists
  const teams = await api.get('/api/v1/llm/teams');
  const existing = (await teams.json()).find(t => t.namespace === namespace);
  if (!existing) {
    await api.post('/api/v1/llm/teams', {
      data: { namespace, max_budget: 500 }
    });
  }
}

export async function ensureAgentKey(
  api: APIRequestContext, namespace: string, agentName: string
) {
  // Create per-agent key if not exists
  const keys = await api.get(`/api/v1/llm/keys?namespace=${namespace}`);
  const existing = (await keys.json()).find(k => k.key_alias === agentName);
  if (!existing) {
    await api.post('/api/v1/llm/keys', {
      data: { namespace, agent_name: agentName, max_budget: 100 }
    });
  }
}
```

```typescript
// e2e/sandbox.spec.ts

test.beforeAll(async ({ request }) => {
  // Ensure LLM infrastructure exists
  await ensureLlmTeam(request, 'team1');
  await ensureAgentKey(request, 'team1', 'sandbox-agent');
});
```

Backend E2E tests (pytest) do the same:

```python
# tests/e2e/conftest.py

@pytest.fixture(scope="session")
def llm_team(backend_client):
    """Ensure litellm team exists for team1."""
    resp = backend_client.post("/api/v1/llm/teams",
                                json={"namespace": "team1"})
    assert resp.status_code in (200, 409)  # 409 = already exists
    return resp.json()

@pytest.fixture(scope="session")
def agent_llm_key(backend_client, llm_team):
    """Ensure per-agent virtual key exists."""
    resp = backend_client.post("/api/v1/llm/keys",
                                json={"namespace": "team1",
                                      "agent_name": "sandbox-agent"})
    assert resp.status_code in (200, 409)
    return resp.json()
```

### Script Integration (38-deploy-litellm.sh Simplification)

The 38 script shrinks to just deploying litellm itself. Key creation moves to
backend API calls:

```bash
# 38-deploy-litellm.sh — SIMPLIFIED
# Only: deploy litellm-proxy + create master key + model config
# NO virtual key creation (backend handles that)

# After platform is running:
# 39-setup-llm-teams.sh (new, tiny script)
BACKEND_URL="http://localhost:18080"
kubectl port-forward -n kagenti-system svc/kagenti-backend 18080:8080 &
PF_PID=$!; sleep 5

TOKEN=$(curl -s "$BACKEND_URL/api/auth/token" \
  -d "username=admin&password=${KEYCLOAK_PASSWORD}" | jq -r .access_token)

for ns in team1 team2; do
  curl -X POST "$BACKEND_URL/api/v1/llm/teams" \
    -H "Authorization: Bearer $TOKEN" \
    -H "Content-Type: application/json" \
    -d "{\"namespace\": \"$ns\", \"max_budget\": 500}"
done

kill $PF_PID
```

### Secret Naming Convention

| Secret | Namespace | Key | Created By | Purpose |
|--------|-----------|-----|-----------|---------|
| `litellm-proxy-secret` | kagenti-system | `master-key` | 38 script | Admin ops only |
| `litellm-model-keys` | kagenti-system | `MAAS_*_API_KEY` | 38 script | Model auth |
| `litellm-virtual-keys` | team1 | `api-key` | Backend API | Namespace default |
| `{agent}-llm-key` | team1 | `apikey` | Backend API | Per-agent key |

### Helm Chart Changes

Backend deployment needs `LITELLM_MASTER_KEY` from kagenti-system secret:

```yaml
# charts/kagenti/templates/backend.yaml
- name: LITELLM_MASTER_KEY
  valueFrom:
    secretKeyRef:
      name: litellm-proxy-secret
      key: master-key
      optional: true  # graceful degradation if litellm not deployed
```

### Migration Path

**Phase 1 (quick fix — unblock deploys):**
- Add `38-deploy-litellm.sh` to `hypershift-full-test.sh`
- Fix deployment YAMLs to use `litellm-virtual-keys`/`api-key`
- Update `DEFAULT_LLM_SECRET` to `litellm-virtual-keys` and key to `api-key`
- Team1 shares one virtual key (current 38 script behavior)

**Phase 2 (backend key API):**
- New router: `llm_keys.py` with team + key endpoints
- Wire `LITELLM_MASTER_KEY` env var to backend
- Update wizard to create per-agent virtual keys
- Add `39-setup-llm-teams.sh` that calls backend API
- E2E test fixtures call backend API for LLM setup

**Phase 3 (full feature):**
- UI for key management (list keys, budgets, model access)
- Key rotation endpoint
- Team admin can configure model visibility
- Budget alerts and dashboards

## Open Questions

1. **Key name: `apikey` vs `api-key`?** Currently `litellm-virtual-keys` uses
   `api-key` (38 script) but wizard creates secrets with `apikey`. Pick one
   and standardize. Recommendation: `apikey` (matches OpenAI convention).

2. **Budget proxy: pre-deployed or auto-deployed?** Currently the budget proxy
   is expected to exist. Should the backend deploy it when creating the first
   agent in a namespace? Or should it be part of team provisioning?

3. **What if litellm isn't deployed?** The backend should gracefully degrade —
   if `LITELLM_MASTER_KEY` is empty, key management endpoints return 503 and
   the wizard falls back to raw key secrets (current behavior).

4. **Team_id storage?** After creating a litellm team, where do we store the
   team_id for later lookups? Options:
   - Namespace annotation: `kagenti.io/litellm-team-id: <id>`
   - ConfigMap in namespace: `litellm-team-config`
   - Query litellm by team_alias on each request (simplest)
