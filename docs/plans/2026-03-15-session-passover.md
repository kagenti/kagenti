# Session Passover — 2026-03-15 — LLM Key Management + Provisioning

> **Cluster:** kagenti-team-sandbox42 (HyperShift, deployed this session)
> **Worktree:** `.worktrees/sandbox-agent` (kagenti), `.worktrees/agent-examples` (agent code)
> **Branch:** `feat/sandbox-agent` (kagenti: `fa941ce3`, agent-examples: `0b72ff7`)
> **sbox42:** untouched (kagenti-team-sbox42, separate cluster)

## What Was Done

### Infrastructure
- Fresh HyperShift cluster `kagenti-team-sandbox42` created and deployed
- Installed all macOS prerequisites: `oc`, `aws`, `helm@3`, `ansible-core`, `boto3`, `certifi`, ansible collections
- LiteLLM proxy deployed to sandbox42 with virtual key for team1
- Sandbox-agent deployment fixed (was crash-looping on missing `litellm-proxy-secret`)

### Code Changes (commit `9e83dc1a`)

| File | Change |
|------|--------|
| `kagenti/backend/app/routers/llm_keys.py` | **NEW** — LLM virtual key management API (teams, keys, agent-models) |
| `kagenti/backend/tests/test_llm_keys.py` | **NEW** — 13 unit tests |
| `kagenti/backend/app/main.py` | Register llm_keys router |
| `kagenti/backend/app/routers/sandbox_deploy.py` | DEFAULT_LLM_SECRET → `litellm-virtual-keys`, added DEFAULT_LLM_SECRET_KEY |
| `charts/kagenti/templates/ui.yaml` | Wire `LITELLM_MASTER_KEY` to backend (optional) |
| `kagenti/examples/agents/sandbox_agent_deployment.yaml` | `litellm-proxy-secret/apikey` → `litellm-virtual-keys/api-key` |
| `kagenti/examples/agents/sandbox_{basic,hardened,legion,restricted}_deployment.yaml` | Same fix |
| `.github/scripts/local-setup/hypershift-full-test.sh` | Add `38-deploy-litellm.sh` to Phase 2 |

### Documentation Created

| Doc | Purpose |
|-----|---------|
| `docs/plans/2026-03-15-hypershift-prerequisites-audit.md` | Actual vs documented prerequisites |
| `docs/plans/2026-03-15-sandbox-bugfix-passover.md` | 4 bugs: prompt data, workspace_path, UI rendering, history loading |
| `docs/plans/2026-03-15-provisioning-architecture.md` | 3-layer provisioning design |
| `docs/plans/2026-03-15-virtual-key-management.md` | Virtual key hierarchy design |

### Unit Tests
- 13/13 passing for `test_llm_keys.py`

## What Works on sandbox42

- Cluster healthy (2 nodes)
- Platform deployed (UI, backend, keycloak, istio, etc.)
- LiteLLM proxy running with 4 models (llama-4-scout, mistral-small, deepseek-r1, gpt-4o-mini)
- Virtual key created for team1 (`litellm-virtual-keys` secret)
- Sandbox-agent pod running (1/1 Ready)
- Weather-service agent running
- Backend rebuilt with new `llm_keys.py` router (commit 9e83dc1a)

## What's Not Done Yet

### E2E Auth Flow
The backend endpoints require `kagenti-viewer`/`kagenti-admin` roles. The Keycloak
`admin-cli` client token doesn't carry these roles. Need to use the proper
Keycloak client (likely the one the UI uses). The Playwright tests handle this
via browser login flow.

**To debug:**
```bash
# Check what Keycloak clients exist
KUBECONFIG=~/clusters/hcp/kagenti-team-sandbox42/auth/kubeconfig \
  kubectl get keycloakclients -n keycloak

# Check what realm roles exist
curl -sk "https://keycloak.../admin/realms/master/roles" \
  -H "Authorization: Bearer $ADMIN_TOKEN"
```

### Bugs from Bugfix Passover (P0-P2)

| Bug | Priority | Status |
|-----|----------|--------|
| Bug 2: workspace_path="" in invoke_with_tool_loop | P0 | Not fixed (in agent-examples repo) |
| Bug 1: Missing prompt fields in loopBuilder | P1 | Not fixed (UI code) |
| Bug 3: Generic prompt rendering | P1 | Depends on Bug 1 |
| Bug 4a: Positional message-loop pairing | P1 | Not fixed |

### Model Selector in Chat
The `/api/v1/llm/agent-models/{ns}/{agent}` endpoint exists in backend but needs:
- UI component wiring in SandboxPage (dropdown next to input)
- Query agent's allowed models on session load
- Pass selected model in the chat request to the agent

### Remaining Provisioning Work
- Convert `76-deploy-sandbox-agents.sh` to use backend API (Phase 2)
- Per-agent virtual keys from wizard (Phase 2)
- Test fixtures that call backend API for LLM setup

## How to Continue

### Setup
```bash
export KUBECONFIG=~/clusters/hcp/kagenti-team-sandbox42/auth/kubeconfig
export LOG_DIR=/tmp/kagenti/tdd/sandbox42 && mkdir -p $LOG_DIR
export KEYCLOAK_PASSWORD=$(kubectl -n keycloak get secret kagenti-test-users -o jsonpath='{.data.admin-password}' | base64 -d)
export KAGENTI_UI_URL="https://$(kubectl get route kagenti-ui -n kagenti-system -o jsonpath='{.spec.host}')"

# For HyperShift tools
export PATH="/opt/homebrew/opt/helm@3/bin:/Library/Frameworks/Python.framework/Versions/3.13/bin:$PATH"
```

### Priority Order
1. **Fix Bug 2** (workspace_path) — 3 lines in agent-examples context_builders.py
2. **Debug E2E auth** — figure out proper Keycloak token flow for API tests
3. **Fix Bug 1** (prompt fields in loopBuilder) — ~30 lines in UI
4. **Wire model selector** in SandboxPage
5. **E2E tests** for key management

### Key File Locations
```
Backend:
  .worktrees/sandbox-agent/kagenti/backend/app/routers/llm_keys.py    # NEW
  .worktrees/sandbox-agent/kagenti/backend/app/routers/sandbox_deploy.py
  .worktrees/sandbox-agent/kagenti/backend/tests/test_llm_keys.py     # NEW

Agent (workspace_path bug):
  .worktrees/agent-examples/a2a/sandbox_agent/src/sandbox_agent/context_builders.py
  Lines 574, 611, 622 — change workspace_path="" to workspace_path=workspace_path

UI (prompt fields bug):
  .worktrees/sandbox-agent/kagenti/ui-v2/src/utils/loopBuilder.ts
  .worktrees/sandbox-agent/kagenti/ui-v2/src/types/agentLoop.ts
  .worktrees/sandbox-agent/kagenti/ui-v2/src/components/LoopDetail.tsx

Helm:
  charts/kagenti/templates/ui.yaml                    # LITELLM_MASTER_KEY wired
  .github/scripts/local-setup/hypershift-full-test.sh # 38-deploy-litellm.sh added
```

### Cluster Inventory
| Cluster | Status | Purpose |
|---------|--------|---------|
| kagenti-team-sbox42 | Alive (13+ days) | Previous alpha work, DO NOT TOUCH |
| kagenti-team-sandbox42 | Alive (new, this session) | Fresh deploy with litellm |
