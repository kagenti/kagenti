---
draft: true       # excluded from https://www.rossoctl.dev/
---

# Agent-Sandbox as Fourth Workload Type — Design Spec

**Epic:** [#1155](https://github.com/rossoctl/rossoctl/issues/1155)
**Scope:** Phase 1 only (Sandbox CRD as a workload type, imperative creation)
**Feature flag:** `rossoctl_feature_flag_agent_sandbox` (new, separate from existing `sandbox` flag)

## Problem

Rossoctl supports three workload types (Deployment, StatefulSet, Job) for agent deployment. The kubernetes-sigs/agent-sandbox project provides a Kubernetes-native abstraction purpose-built for AI agent runtimes — offering stable identity, persistent storage, lifecycle management (pause/resume/expire), and optional VM-level isolation. Adding Sandbox as a fourth workload type gives users access to these capabilities through the existing Rossoctl UI.

## Architecture

The backend creates `Sandbox` CRs directly via the Kubernetes API (same imperative pattern as Deployment/StatefulSet/Job). The agent-sandbox controller is an **external prerequisite** — not bundled in the Rossoctl Helm chart. The feature flag gates all Sandbox-related code paths so clusters without agent-sandbox installed continue to work unchanged.

The rossoctl-webhook already injects AuthBridge sidecars at Pod CREATE time based on `rossoctl.io/type: agent` labels. Since the Sandbox controller creates Pods from the Sandbox `podTemplate`, webhook injection works automatically — no webhook changes needed.

### CRD coordinates

- **Group:** `agents.x-k8s.io`
- **Version:** `v1alpha1`
- **Plural:** `sandboxes`
- **Kind:** `Sandbox`

## Components Changed

### 1. Feature flag + constants

**`rossoctl/backend/app/core/config.py`**
- Add `rossoctl_feature_flag_agent_sandbox: bool = False`

**`rossoctl/backend/app/core/constants.py`**
- Add `WORKLOAD_TYPE_SANDBOX = "sandbox"`
- Add to `SUPPORTED_WORKLOAD_TYPES` list (conditionally, when flag is enabled)
- Add agent-sandbox CRD constants: `AGENT_SANDBOX_CRD_GROUP`, `AGENT_SANDBOX_CRD_VERSION`, `AGENT_SANDBOX_PLURAL`

**`rossoctl/backend/app/routers/config.py`**
- Add `agentSandbox: bool` to `FeatureFlagsResponse`

### 2. KubernetesService — Sandbox CRUD

**`rossoctl/backend/app/services/kubernetes.py`**
- Add `create_sandbox(namespace, body)` — uses `custom_api.create_namespaced_custom_object`
- Add `get_sandbox(namespace, name)` — uses `custom_api.get_namespaced_custom_object`
- Add `list_sandboxes(namespace, label_selector)` — uses `custom_api.list_namespaced_custom_object`
- Add `delete_sandbox(namespace, name)` — uses `custom_api.delete_namespaced_custom_object`
- Add `patch_sandbox(namespace, name, body)` — uses `custom_api.patch_namespaced_custom_object`

All methods use the existing `custom_api` property (no new API client needed).

### 3. Manifest builder

**`rossoctl/backend/app/routers/agents.py`**

New function `_build_sandbox_manifest(request, image)` returns a Sandbox CR dict:

```yaml
apiVersion: agents.x-k8s.io/v1alpha1
kind: Sandbox
metadata:
  name: <request.name>
  namespace: <request.namespace>
  labels:
    rossoctl.io/type: agent          # triggers webhook injection
    rossoctl.io/workload-type: sandbox
    app.kubernetes.io/name: <name>
    app.kubernetes.io/managed-by: rossoctl-ui
    # ... standard rossoctl labels
spec:
  podTemplate:
    metadata:
      labels:
        rossoctl.io/type: agent      # required for webhook pod matching
    spec:
      serviceAccountName: <name>
      containers:
      - name: agent
        image: <image>
        ports:
        - containerPort: 8000
        env: [...]                  # same env vars as Deployment
        resources: {limits, requests}
        securityContext:
          runAsNonRoot: true
          allowPrivilegeEscalation: false
```

Optional fields (when provided in request):
- `runtimeClassName` for Kata/gVisor isolation
- `volumeClaimTemplates` for persistent `/workspace`

### 4. Router integration (agents.py)

12 switch points in `agents.py` need Sandbox branches, all guarded by feature flag check:

| Endpoint | Change |
|----------|--------|
| `CreateAgentRequest.validate_workload_type` | Accept "sandbox" when flag enabled |
| `list_agents` | Add fourth query: `kube.list_sandboxes()` |
| `get_agent` | Add fourth try: `kube.get_sandbox()` |
| `create_agent` (image deploy) | Add `elif WORKLOAD_TYPE_SANDBOX` branch |
| `create_agent` (source deploy) | Add Sandbox path in `finalize_shipwright_build` |
| `delete_agent` | Add Sandbox deletion |
| Service creation | Sandbox manages its own headless Service — skip `_build_service_manifest` |
| HTTPRoute | Support creating routes for Sandbox agents |

**Validation gating:** The `validate_workload_type` validator on `CreateAgentRequest` checks against `SUPPORTED_WORKLOAD_TYPES`. The Sandbox type must only be accepted when the feature flag is enabled. Options:
- **Option A:** Make `SUPPORTED_WORKLOAD_TYPES` dynamic (read flag at import time) — simple but requires restart to change
- **Option B:** Override validation in the endpoint to check the flag — more explicit

**Choice:** Option A. Feature flags already require restart to change (they're read from env vars at startup). `SUPPORTED_WORKLOAD_TYPES` will conditionally include `"sandbox"` based on `settings.rossoctl_feature_flag_agent_sandbox`.

### 5. Status extraction

Sandbox status differs from Deployment/StatefulSet/Job. The Sandbox CR has:
- `.status.conditions` — array of conditions (Ready, PodReady, etc.)
- `.status.serviceFQDN` — auto-created headless Service FQDN

New helper functions:
- `_get_sandbox_description(sandbox)` — extract description from annotations
- `_is_sandbox_ready(sandbox)` — check conditions for Ready=True
- `_get_sandbox_status(sandbox)` — return status string

### 6. Reconciliation

**`rossoctl/backend/app/services/reconciliation.py`**
- Update `_workload_exists()` to check Sandbox CRs (fourth try after Job)

### 7. CRD detection + graceful degradation

At startup (in `main.py` lifespan), check if the `sandboxes.agents.x-k8s.io` CRD is installed:
- If flag enabled AND CRD exists: enable Sandbox workload type
- If flag enabled AND CRD missing: log warning, set `SUPPORTED_WORKLOAD_TYPES` to exclude sandbox
- If flag disabled: no detection needed

### 8. UI changes

**`rossoctl/ui-v2/src/types/index.ts`**
- Add `'sandbox'` to `WorkloadType` union

**`rossoctl/ui-v2/src/hooks/useFeatureFlags.ts`**
- Add `agentSandbox: boolean` to `FeatureFlags` interface

**`rossoctl/ui-v2/src/pages/ImportAgentPage.tsx`**
- Add "Sandbox" option to workload type dropdown (shown when `agentSandbox` flag is true)
- Description: "For agents requiring stable identity, persistent storage, and lifecycle management (pause/resume). Requires agent-sandbox controller."

**`rossoctl/ui-v2/src/pages/AgentDetailPage.tsx`**
- Handle `workloadType === 'sandbox'` in status display
- Show Sandbox-specific fields (serviceFQDN, conditions)

**`rossoctl/ui-v2/src/pages/AgentCatalogPage.tsx`**
- Render sandbox workload type badge (purple label)

**`rossoctl/ui-v2/src/services/api.ts`**
- Add `'sandbox'` to workload type unions in API interfaces

### 9. Helm chart

**`charts/rossoctl/values.yaml`**
- Add `featureFlags.agentSandbox: false`

**`charts/rossoctl/templates/backend-deployment.yaml`** (or equivalent)
- Wire `ROSSOCTL_FEATURE_FLAG_AGENT_SANDBOX` env var from values

### 10. E2E tests

**`rossoctl/tests/e2e/test_agent_sandbox.py`**
- Marker: `@pytest.mark.requires_features(["agent_sandbox"])`
- Tests: create, list, get, delete agent with `workloadType=sandbox`
- Verify: pod running, rossoctl labels present, AuthBridge sidecars injected (if webhook installed)

CI installs agent-sandbox controller in Kind cluster before running these tests.

## What is NOT in scope (Phase 2)

- SandboxTemplate / SandboxClaim / WarmPool management
- Template/Claim separation (admin vs user)
- Warm pool pre-warming and utilization metrics
- AgentRuntime CR alignment (#862)

## Key decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Feature flag | New `agent_sandbox`, not reusing `sandbox` | Existing `sandbox` controls interactive session UI |
| CRD detection | Startup check | Fail-fast with clear log message |
| Service creation | Skip for Sandbox | Sandbox controller auto-creates headless Service |
| Workload type validation | Conditional at import time | Matches existing startup-time flag pattern |
| Deployment model | External prerequisite | Loose coupling; admin controls agent-sandbox version |
