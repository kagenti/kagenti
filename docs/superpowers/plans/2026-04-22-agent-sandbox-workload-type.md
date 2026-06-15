# Agent-Sandbox Workload Type Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `Sandbox` (from kubernetes-sigs/agent-sandbox) as a fourth workload type alongside Deployment, StatefulSet, and Job, gated behind a new feature flag.

**Architecture:** The backend creates `Sandbox` CRs via the Kubernetes CustomObjects API (same imperative pattern as the existing three workload types). A startup CRD detection check gracefully disables the feature if the agent-sandbox controller is not installed. The UI conditionally shows the Sandbox option based on the `agentSandbox` feature flag.

**Tech Stack:** Python 3.11+ / FastAPI / Pydantic (backend), React / PatternFly (frontend), Helm 3 (charts), pytest (E2E)

---

## File Structure

| File | Responsibility |
|------|---------------|
| `kagenti/backend/app/core/config.py` | Feature flag declaration |
| `kagenti/backend/app/core/constants.py` | `WORKLOAD_TYPE_SANDBOX` constant + CRD coordinates |
| `kagenti/backend/app/services/kubernetes.py` | Sandbox CRUD methods (create/get/list/delete/patch) |
| `kagenti/backend/app/routers/agents.py` | Manifest builder + all dispatch points (create/list/get/delete/finalize) |
| `kagenti/backend/app/routers/config.py` | Expose `agentSandbox` in feature flags response |
| `kagenti/backend/app/services/reconciliation.py` | Add Sandbox to `_workload_exists` |
| `kagenti/backend/app/main.py` | CRD detection at startup |
| `charts/kagenti/values.yaml` | `featureFlags.agentSandbox` value |
| `charts/kagenti/templates/ui.yaml` | Wire env var for feature flag |
| `kagenti/ui-v2/src/types/index.ts` | Add `'sandbox'` to `WorkloadType` union |
| `kagenti/ui-v2/src/hooks/useFeatureFlags.ts` | Add `agentSandbox` boolean |
| `kagenti/ui-v2/src/pages/ImportAgentPage.tsx` | Sandbox option in workload dropdown |
| `kagenti/ui-v2/src/pages/AgentCatalogPage.tsx` | Sandbox badge rendering |
| `kagenti/ui-v2/src/pages/AgentDetailPage.tsx` | Sandbox status display |
| `kagenti/ui-v2/src/services/api.ts` | Add `'sandbox'` to API type unions |
| `kagenti/tests/e2e/test_agent_sandbox.py` | E2E tests for Sandbox workload type |

---

### Task 1: Feature flag + constants (epic 1.1)

**Files:**
- Modify: `kagenti/backend/app/core/config.py:69-71`
- Modify: `kagenti/backend/app/core/constants.py:56-66`

- [ ] **Step 1: Add feature flag to config.py**

In `kagenti/backend/app/core/config.py`, add after line 71 (`kagenti_feature_flag_triggers`):

```python
    kagenti_feature_flag_agent_sandbox: bool = False
```

- [ ] **Step 2: Add constants to constants.py**

In `kagenti/backend/app/core/constants.py`, add after line 59 (`WORKLOAD_TYPE_JOB = "job"`):

```python
WORKLOAD_TYPE_SANDBOX = "sandbox"

# agent-sandbox CRD coordinates (kubernetes-sigs/agent-sandbox)
AGENT_SANDBOX_CRD_GROUP = "agents.x-k8s.io"
AGENT_SANDBOX_CRD_VERSION = "v1alpha1"
AGENT_SANDBOX_PLURAL = "sandboxes"
```

- [ ] **Step 3: Make SUPPORTED_WORKLOAD_TYPES conditional**

Replace lines 62-66 in `constants.py`:

```python
# Supported workload types
SUPPORTED_WORKLOAD_TYPES = [
    WORKLOAD_TYPE_DEPLOYMENT,
    WORKLOAD_TYPE_STATEFULSET,
    WORKLOAD_TYPE_JOB,
]
```

with:

```python
# Supported workload types (sandbox added conditionally at startup)
SUPPORTED_WORKLOAD_TYPES = [
    WORKLOAD_TYPE_DEPLOYMENT,
    WORKLOAD_TYPE_STATEFULSET,
    WORKLOAD_TYPE_JOB,
]
if settings.kagenti_feature_flag_agent_sandbox:
    SUPPORTED_WORKLOAD_TYPES.append(WORKLOAD_TYPE_SANDBOX)
```

- [ ] **Step 4: Add agentSandbox to feature flags response**

In `kagenti/backend/app/routers/config.py`, update the `FeatureFlagsResponse` class (line 16-19):

```python
class FeatureFlagsResponse(BaseModel):
    sandbox: bool
    integrations: bool
    triggers: bool
    agentSandbox: bool
```

And update the endpoint (line 32-36):

```python
    return FeatureFlagsResponse(
        sandbox=settings.kagenti_feature_flag_sandbox,
        integrations=settings.kagenti_feature_flag_integrations,
        triggers=settings.kagenti_feature_flag_triggers,
        agentSandbox=settings.kagenti_feature_flag_agent_sandbox,
    )
```

- [ ] **Step 5: Commit**

```bash
git add kagenti/backend/app/core/config.py kagenti/backend/app/core/constants.py kagenti/backend/app/routers/config.py
git commit -s -m "feat: add agent_sandbox feature flag and constants (epic 1155 step 1.1)"
```

---

### Task 2: KubernetesService Sandbox CRUD (epic 1.2)

**Files:**
- Modify: `kagenti/backend/app/services/kubernetes.py:492-498`

- [ ] **Step 1: Add Sandbox CRUD methods**

In `kagenti/backend/app/services/kubernetes.py`, add a new section before the `@lru_cache` line (line 495), after the Job Operations section:

```python
    # -------------------------------------------------------------------------
    # Sandbox Operations (agent-sandbox CRD: agents.x-k8s.io/v1alpha1)
    # -------------------------------------------------------------------------

    def create_sandbox(self, namespace: str, body: dict) -> dict:
        """Create a Sandbox CR in the specified namespace."""
        from app.core.constants import (
            AGENT_SANDBOX_CRD_GROUP,
            AGENT_SANDBOX_CRD_VERSION,
            AGENT_SANDBOX_PLURAL,
        )

        try:
            return self.custom_api.create_namespaced_custom_object(
                group=AGENT_SANDBOX_CRD_GROUP,
                version=AGENT_SANDBOX_CRD_VERSION,
                namespace=namespace,
                plural=AGENT_SANDBOX_PLURAL,
                body=body,
            )
        except ApiException as e:
            logger.error(f"Error creating Sandbox in {namespace}: {e}")
            raise

    def get_sandbox(self, namespace: str, name: str) -> dict:
        """Get a Sandbox CR by name."""
        from app.core.constants import (
            AGENT_SANDBOX_CRD_GROUP,
            AGENT_SANDBOX_CRD_VERSION,
            AGENT_SANDBOX_PLURAL,
        )

        try:
            return self.custom_api.get_namespaced_custom_object(
                group=AGENT_SANDBOX_CRD_GROUP,
                version=AGENT_SANDBOX_CRD_VERSION,
                namespace=namespace,
                plural=AGENT_SANDBOX_PLURAL,
                name=name,
            )
        except ApiException as e:
            logger.error(f"Error getting Sandbox {name} in {namespace}: {e}")
            raise

    def list_sandboxes(
        self, namespace: str, label_selector: Optional[str] = None
    ) -> List[dict]:
        """List Sandbox CRs in a namespace with optional label selector."""
        from app.core.constants import (
            AGENT_SANDBOX_CRD_GROUP,
            AGENT_SANDBOX_CRD_VERSION,
            AGENT_SANDBOX_PLURAL,
        )

        try:
            response = self.custom_api.list_namespaced_custom_object(
                group=AGENT_SANDBOX_CRD_GROUP,
                version=AGENT_SANDBOX_CRD_VERSION,
                namespace=namespace,
                plural=AGENT_SANDBOX_PLURAL,
                label_selector=label_selector,
            )
            return response.get("items", [])
        except ApiException as e:
            logger.error(f"Error listing Sandboxes in {namespace}: {e}")
            raise

    def delete_sandbox(self, namespace: str, name: str) -> None:
        """Delete a Sandbox CR by name."""
        from app.core.constants import (
            AGENT_SANDBOX_CRD_GROUP,
            AGENT_SANDBOX_CRD_VERSION,
            AGENT_SANDBOX_PLURAL,
        )

        try:
            self.custom_api.delete_namespaced_custom_object(
                group=AGENT_SANDBOX_CRD_GROUP,
                version=AGENT_SANDBOX_CRD_VERSION,
                namespace=namespace,
                plural=AGENT_SANDBOX_PLURAL,
                name=name,
            )
        except ApiException as e:
            logger.error(f"Error deleting Sandbox {name} in {namespace}: {e}")
            raise

    def patch_sandbox(self, namespace: str, name: str, body: dict) -> dict:
        """Patch a Sandbox CR with the provided body."""
        from app.core.constants import (
            AGENT_SANDBOX_CRD_GROUP,
            AGENT_SANDBOX_CRD_VERSION,
            AGENT_SANDBOX_PLURAL,
        )

        try:
            return self.custom_api.patch_namespaced_custom_object(
                group=AGENT_SANDBOX_CRD_GROUP,
                version=AGENT_SANDBOX_CRD_VERSION,
                namespace=namespace,
                plural=AGENT_SANDBOX_PLURAL,
                name=name,
                body=body,
            )
        except ApiException as e:
            logger.error(f"Error patching Sandbox {name} in {namespace}: {e}")
            raise
```

- [ ] **Step 2: Commit**

```bash
git add kagenti/backend/app/services/kubernetes.py
git commit -s -m "feat: add Sandbox CRUD methods to KubernetesService (epic 1155 step 1.2)"
```

---

### Task 3: Manifest builder (epic 1.3)

**Files:**
- Modify: `kagenti/backend/app/routers/agents.py`

- [ ] **Step 1: Add WORKLOAD_TYPE_SANDBOX to imports**

In `kagenti/backend/app/routers/agents.py`, add to the imports from `app.core.constants` (around line 57-59):

```python
    WORKLOAD_TYPE_SANDBOX,
    AGENT_SANDBOX_CRD_GROUP,
    AGENT_SANDBOX_CRD_VERSION,
    AGENT_SANDBOX_PLURAL,
```

- [ ] **Step 2: Add _build_sandbox_manifest function**

Add after `_build_job_manifest` (after line ~2400, before `create_agent`). Find the exact location by searching for the line after the closing of `_build_job_manifest`:

```python
def _build_sandbox_manifest(
    request: "CreateAgentRequest",
    image: str,
    shipwright_build_name: Optional[str] = None,
) -> dict:
    """Build a Sandbox CR manifest for an agent (agents.x-k8s.io/v1alpha1)."""
    env_vars = _build_env_vars(request)
    labels = _build_common_labels(request, WORKLOAD_TYPE_SANDBOX)

    annotations: Dict[str, str] = {
        KAGENTI_DESCRIPTION_ANNOTATION: f"Agent '{request.name}' deployed from UI.",
    }
    if shipwright_build_name:
        annotations["kagenti.io/shipwright-build"] = shipwright_build_name

    container_port = DEFAULT_IN_CLUSTER_PORT
    if request.servicePorts and len(request.servicePorts) > 0:
        container_port = request.servicePorts[0].targetPort

    manifest = {
        "apiVersion": f"{AGENT_SANDBOX_CRD_GROUP}/{AGENT_SANDBOX_CRD_VERSION}",
        "kind": "Sandbox",
        "metadata": {
            "name": request.name,
            "namespace": request.namespace,
            "labels": labels,
            "annotations": annotations,
        },
        "spec": {
            "podTemplate": {
                "metadata": {
                    "labels": {
                        **labels,
                    },
                },
                "spec": {
                    "serviceAccountName": request.name,
                    "containers": [
                        {
                            "name": "agent",
                            "image": image,
                            "imagePullPolicy": DEFAULT_IMAGE_POLICY,
                            "resources": {
                                "limits": DEFAULT_RESOURCE_LIMITS,
                                "requests": DEFAULT_RESOURCE_REQUESTS,
                            },
                            "env": env_vars,
                            "ports": [
                                {
                                    "name": "http",
                                    "containerPort": container_port,
                                    "protocol": "TCP",
                                },
                            ],
                            "volumeMounts": [
                                {"name": "cache", "mountPath": "/app/.cache"},
                                {"name": "marvin", "mountPath": "/.marvin"},
                                {"name": "shared-data", "mountPath": "/shared"},
                            ],
                        }
                    ],
                    "volumes": [
                        {"name": "cache", "emptyDir": {}},
                        {"name": "marvin", "emptyDir": {}},
                        {"name": "shared-data", "emptyDir": {}},
                    ],
                },
            },
        },
    }

    if request.imagePullSecret:
        manifest["spec"]["podTemplate"]["spec"]["imagePullSecrets"] = [
            {"name": request.imagePullSecret}
        ]

    return manifest
```

- [ ] **Step 3: Add Sandbox status helper functions**

Add near the other status helper functions (near `_is_deployment_ready`, `_is_statefulset_ready`, `_get_job_status`):

```python
def _is_sandbox_ready(sandbox: dict) -> str:
    """Check if a Sandbox CR is ready by examining its status conditions."""
    status = sandbox.get("status", {})
    conditions = status.get("conditions", [])
    for cond in conditions:
        if cond.get("type") == "Ready":
            if cond.get("status") == "True":
                return "Ready"
            return "Not Ready"
    return "Pending"


def _get_sandbox_description(sandbox: dict) -> str:
    """Extract description from a Sandbox CR."""
    metadata = sandbox.get("metadata", {})
    annotations = metadata.get("annotations", {})
    return annotations.get(KAGENTI_DESCRIPTION_ANNOTATION, "No description")
```

- [ ] **Step 4: Commit**

```bash
git add kagenti/backend/app/routers/agents.py
git commit -s -m "feat: add Sandbox manifest builder and status helpers (epic 1155 step 1.3)"
```

---

### Task 4: Router integration — list, get, delete (epic 1.4a)

**Files:**
- Modify: `kagenti/backend/app/routers/agents.py`

- [ ] **Step 1: Add Sandbox to list_agents**

In `list_agents` (around line 566, after the Jobs query block ending at line 597), add before the legacy Agent CRD block:

```python
        # Query Sandbox CRs with agent label (when feature flag enabled)
        if settings.kagenti_feature_flag_agent_sandbox:
            try:
                sandboxes = kube.list_sandboxes(
                    namespace=namespace,
                    label_selector=label_selector,
                )

                for sandbox in sandboxes:
                    metadata = sandbox.get("metadata", {})
                    name = metadata.get("name", "")
                    if name in agent_names:
                        logger.warning(
                            f"Duplicate agent name '{name}' detected: Sandbox skipped because "
                            f"another workload with the same name already exists in namespace '{namespace}'."
                        )
                        continue
                    agent_names.add(name)
                    labels = metadata.get("labels", {})

                    agents.append(
                        AgentSummary(
                            name=name,
                            namespace=metadata.get("namespace", namespace),
                            description=_get_sandbox_description(sandbox),
                            status=_is_sandbox_ready(sandbox),
                            labels=_extract_labels(labels),
                            workloadType=WORKLOAD_TYPE_SANDBOX,
                            createdAt=_format_timestamp(
                                metadata.get("creation_timestamp")
                                or metadata.get("creationTimestamp")
                            ),
                        )
                    )
            except ApiException as e:
                if e.status == 404:
                    logger.debug("Sandbox CRD not installed, skipping Sandbox query")
                elif e.status != 403:
                    logger.warning(f"Failed to list Sandboxes in {namespace}: {e.reason}")
```

- [ ] **Step 2: Add Sandbox to get_agent**

In `get_agent` (around line 692, after the Job try block), add before the 404 raise:

```python
    # If still not found, try Sandbox (when feature flag enabled)
    if workload is None and settings.kagenti_feature_flag_agent_sandbox:
        try:
            workload = kube.get_sandbox(namespace=namespace, name=name)
            workload_type = WORKLOAD_TYPE_SANDBOX
        except ApiException as e:
            if e.status != 404:
                raise HTTPException(status_code=e.status, detail=str(e.reason))
```

- [ ] **Step 3: Add Sandbox status to get_agent response**

In `get_agent` (around line 720-727, the ready_status if/elif chain), add before `else`:

```python
    elif workload_type == WORKLOAD_TYPE_SANDBOX:
        ready_status = _is_sandbox_ready(workload)
```

- [ ] **Step 4: Handle Service lookup for Sandbox**

In `get_agent` (around line 707), the existing code skips Service lookup for Jobs. The Sandbox controller creates its own headless Service, so we should also skip creating one but still try to look up the auto-created one. The existing logic `if workload_type != WORKLOAD_TYPE_JOB` already handles this correctly — Sandbox will look up the Service, and if the Sandbox controller hasn't created one yet, the 404 is silently ignored.

No code change needed here.

- [ ] **Step 5: Add Sandbox to delete_agent**

In `delete_agent` (around line 818, after the Job delete block), add:

```python
    # Delete the Sandbox (if exists)
    if settings.kagenti_feature_flag_agent_sandbox:
        try:
            kube.delete_sandbox(namespace=namespace, name=name)
            messages.append(f"Sandbox '{name}' deleted")
        except ApiException as e:
            if e.status == 404:
                logger.debug(f"Sandbox '{name}' not found")
            else:
                logger.warning(f"Failed to delete Sandbox '{name}': {e.reason}")
```

- [ ] **Step 6: Commit**

```bash
git add kagenti/backend/app/routers/agents.py
git commit -s -m "feat: add Sandbox to list/get/delete agent endpoints (epic 1155 step 1.4a)"
```

---

### Task 5: Router integration — create + finalize (epic 1.4b)

**Files:**
- Modify: `kagenti/backend/app/routers/agents.py`

- [ ] **Step 1: Add Sandbox branch to create_agent (image deploy)**

In `create_agent` (around line 2466-2475, the workload type dispatch), add after the Job elif:

```python
            elif request.workloadType == WORKLOAD_TYPE_SANDBOX:
                workload_manifest = _build_sandbox_manifest(
                    request=request,
                    image=request.containerImage,
                )
                kube.create_sandbox(
                    namespace=request.namespace,
                    body=workload_manifest,
                )
                logger.info(
                    f"Created Sandbox '{request.name}' in namespace '{request.namespace}'"
                )
```

- [ ] **Step 2: Handle Service creation for Sandbox**

The existing code at line 2478 creates a Service when `request.workloadType != WORKLOAD_TYPE_JOB`. The Sandbox controller auto-creates a headless Service, so skip Service creation for Sandbox too. Update the condition:

```python
            if request.workloadType not in (WORKLOAD_TYPE_JOB, WORKLOAD_TYPE_SANDBOX):
```

- [ ] **Step 3: Handle HTTPRoute for Sandbox**

The existing code at line 2489 checks `request.workloadType != WORKLOAD_TYPE_JOB` before creating an HTTPRoute. Sandbox agents can have routes. Leave this as-is — Sandbox is not excluded from HTTPRoute creation.

No code change needed here.

- [ ] **Step 4: Add Sandbox branch to finalize_shipwright_build**

In `finalize_shipwright_build` (around line 2691-2714, the workload existence check), add a Sandbox try block after the Job check:

```python
        if not workload_exists and settings.kagenti_feature_flag_agent_sandbox:
            try:
                kube.get_sandbox(namespace=namespace, name=name)
                workload_exists = True
                existing_workload_type = WORKLOAD_TYPE_SANDBOX
            except ApiException as e:
                if e.status != 404:
                    raise
```

Then in the workload creation dispatch (around line 2838-2893), add the Sandbox branch after the Job elif:

```python
        elif final_workload_type == WORKLOAD_TYPE_SANDBOX:
            workload_manifest = _build_sandbox_manifest(
                request=agent_request,
                image=container_image,
                shipwright_build_name=name,
            )
            kube.create_sandbox(
                namespace=namespace,
                body=workload_manifest,
            )
            logger.info(
                f"Created Sandbox '{name}' in namespace '{namespace}' from build"
            )
```

And update the Service skip condition (around line 2894):

```python
        if final_workload_type not in (WORKLOAD_TYPE_JOB, WORKLOAD_TYPE_SANDBOX):
```

- [ ] **Step 5: Commit**

```bash
git add kagenti/backend/app/routers/agents.py
git commit -s -m "feat: add Sandbox to create_agent and finalize_shipwright_build (epic 1155 step 1.4b)"
```

---

### Task 6: Reconciliation (epic 1.5)

**Files:**
- Modify: `kagenti/backend/app/services/reconciliation.py:38-47`

- [ ] **Step 1: Add Sandbox to _workload_exists**

Replace the `_workload_exists` function:

```python
def _workload_exists(kube: KubernetesService, namespace: str, name: str) -> bool:
    """Check if any workload (Deployment, StatefulSet, Job, or Sandbox) exists for the given name."""
    for getter in (kube.get_deployment, kube.get_statefulset, kube.get_job):
        try:
            getter(namespace=namespace, name=name)
            return True
        except ApiException as e:
            if e.status != 404:
                raise

    if settings.kagenti_feature_flag_agent_sandbox:
        try:
            kube.get_sandbox(namespace=namespace, name=name)
            return True
        except ApiException as e:
            if e.status != 404:
                raise

    return False
```

- [ ] **Step 2: Add settings import**

At the top of `reconciliation.py`, add:

```python
from app.core.config import settings
```

- [ ] **Step 3: Commit**

```bash
git add kagenti/backend/app/services/reconciliation.py
git commit -s -m "feat: add Sandbox to reconciliation workload check (epic 1155 step 1.5)"
```

---

### Task 7: CRD detection at startup (epic 1.7)

**Files:**
- Modify: `kagenti/backend/app/main.py:96-117`

- [ ] **Step 1: Add CRD detection in lifespan**

In `main.py`, add the CRD detection inside the `lifespan` function, after the startup log lines (around line 103) and before the reconciliation block:

```python
    # Detect agent-sandbox CRD availability (when flag is enabled)
    if settings.kagenti_feature_flag_agent_sandbox:
        from app.core.constants import (
            AGENT_SANDBOX_CRD_GROUP,
            AGENT_SANDBOX_CRD_VERSION,
            AGENT_SANDBOX_PLURAL,
            SUPPORTED_WORKLOAD_TYPES,
            WORKLOAD_TYPE_SANDBOX,
        )
        from app.services.kubernetes import get_kubernetes_service

        try:
            kube = get_kubernetes_service()
            kube.custom_api.list_namespaced_custom_object(
                group=AGENT_SANDBOX_CRD_GROUP,
                version=AGENT_SANDBOX_CRD_VERSION,
                namespace="default",
                plural=AGENT_SANDBOX_PLURAL,
                limit=1,
            )
            logger.info("agent-sandbox CRD detected — Sandbox workload type enabled")
        except Exception:
            logger.warning(
                "Feature flag AGENT_SANDBOX enabled but Sandbox CRD not found "
                "(agents.x-k8s.io/v1alpha1/sandboxes). Disabling Sandbox workload type. "
                "Install agent-sandbox controller to enable: "
                "https://github.com/kubernetes-sigs/agent-sandbox"
            )
            if WORKLOAD_TYPE_SANDBOX in SUPPORTED_WORKLOAD_TYPES:
                SUPPORTED_WORKLOAD_TYPES.remove(WORKLOAD_TYPE_SANDBOX)
```

- [ ] **Step 2: Commit**

```bash
git add kagenti/backend/app/main.py
git commit -s -m "feat: detect agent-sandbox CRD at startup with graceful degradation (epic 1155 step 1.7)"
```

---

### Task 8: Helm chart (epic 1.1 continued)

**Files:**
- Modify: `charts/kagenti/values.yaml:7-10`
- Modify: `charts/kagenti/templates/ui.yaml:122-123`

- [ ] **Step 1: Add agentSandbox to values.yaml**

In `charts/kagenti/values.yaml`, add after line 10 (`triggers: false`):

```yaml
  agentSandbox: false
```

- [ ] **Step 2: Wire env var in ui.yaml**

In `charts/kagenti/templates/ui.yaml`, add after line 123 (the `KAGENTI_FEATURE_FLAG_TRIGGERS` block):

```yaml
            - name: KAGENTI_FEATURE_FLAG_AGENT_SANDBOX
              value: "{{ .Values.featureFlags.agentSandbox }}"
```

- [ ] **Step 3: Commit**

```bash
git add charts/kagenti/values.yaml charts/kagenti/templates/ui.yaml
git commit -s -m "feat: add agentSandbox feature flag to Helm chart (epic 1155 step 1.1)"
```

---

### Task 9: UI — types + feature flags (epic 1.8a)

**Files:**
- Modify: `kagenti/ui-v2/src/types/index.ts:9`
- Modify: `kagenti/ui-v2/src/hooks/useFeatureFlags.ts`
- Modify: `kagenti/ui-v2/src/services/api.ts:204`

- [ ] **Step 1: Add sandbox to WorkloadType**

In `kagenti/ui-v2/src/types/index.ts`, change line 9:

```typescript
export type WorkloadType = 'deployment' | 'statefulset' | 'job' | 'sandbox';
```

- [ ] **Step 2: Add agentSandbox to FeatureFlags**

In `kagenti/ui-v2/src/hooks/useFeatureFlags.ts`, update the interface (line 7-11):

```typescript
export interface FeatureFlags {
  sandbox: boolean;
  integrations: boolean;
  triggers: boolean;
  agentSandbox: boolean;
}
```

Update `DEFAULT_FLAGS` (line 13-17):

```typescript
const DEFAULT_FLAGS: FeatureFlags = {
  sandbox: false,
  integrations: false,
  triggers: false,
  agentSandbox: false,
};
```

Update the validated block inside the `useEffect` (line 34-38):

```typescript
        const validated: FeatureFlags = {
          sandbox: data.sandbox === true,
          integrations: data.integrations === true,
          triggers: data.triggers === true,
          agentSandbox: data.agentSandbox === true,
        };
```

- [ ] **Step 3: Add sandbox to API type unions**

In `kagenti/ui-v2/src/services/api.ts`, find line 204:

```typescript
    workloadType?: 'deployment' | 'statefulset' | 'job';
```

Change to:

```typescript
    workloadType?: 'deployment' | 'statefulset' | 'job' | 'sandbox';
```

Search for any other workloadType type annotations in `api.ts` and add `'sandbox'` to each one.

- [ ] **Step 4: Commit**

```bash
git add kagenti/ui-v2/src/types/index.ts kagenti/ui-v2/src/hooks/useFeatureFlags.ts kagenti/ui-v2/src/services/api.ts
git commit -s -m "feat: add sandbox to UI types and feature flags (epic 1155 step 1.8a)"
```

---

### Task 10: UI — ImportAgentPage dropdown (epic 1.8b)

**Files:**
- Modify: `kagenti/ui-v2/src/pages/ImportAgentPage.tsx`

- [ ] **Step 1: Import useFeatureFlags**

At the top of `ImportAgentPage.tsx`, add the import (if not already present):

```typescript
import { useFeatureFlags } from '@/hooks/useFeatureFlags';
```

- [ ] **Step 2: Get feature flags in component**

Inside the component function, add:

```typescript
  const featureFlags = useFeatureFlags();
```

- [ ] **Step 3: Update workloadType state type**

Change line 158:

```typescript
  const [workloadType, setWorkloadType] = useState<'deployment' | 'statefulset' | 'job'>('deployment');
```

to:

```typescript
  const [workloadType, setWorkloadType] = useState<'deployment' | 'statefulset' | 'job' | 'sandbox'>('deployment');
```

- [ ] **Step 4: Update onChange handler type**

Change line 944:

```typescript
                  onChange={(_e, value) => setWorkloadType(value as 'deployment' | 'statefulset' | 'job')}
```

to:

```typescript
                  onChange={(_e, value) => setWorkloadType(value as 'deployment' | 'statefulset' | 'job' | 'sandbox')}
```

- [ ] **Step 5: Add Sandbox option to dropdown**

After line 949 (`<FormSelectOption value="job" label="Job" />`), add:

```tsx
                  {featureFlags.agentSandbox && (
                    <FormSelectOption value="sandbox" label="Sandbox (agent-sandbox)" />
                  )}
```

- [ ] **Step 6: Add Sandbox helper text**

After line 956 (the job helper text), add:

```tsx
                      {workloadType === 'sandbox' && 'For agents requiring stable identity, persistent storage, and lifecycle management (pause/resume). Requires agent-sandbox controller.'}
```

- [ ] **Step 7: Commit**

```bash
git add kagenti/ui-v2/src/pages/ImportAgentPage.tsx
git commit -s -m "feat: add Sandbox option to agent workload type dropdown (epic 1155 step 1.8b)"
```

---

### Task 11: UI — AgentCatalogPage + AgentDetailPage (epic 1.8c)

**Files:**
- Modify: `kagenti/ui-v2/src/pages/AgentCatalogPage.tsx:121-131`
- Modify: `kagenti/ui-v2/src/pages/AgentDetailPage.tsx`

- [ ] **Step 1: Add sandbox badge color to AgentCatalogPage**

In `AgentCatalogPage.tsx`, update `renderWorkloadType` (line 121-131):

```typescript
  const renderWorkloadType = (workloadType: string | undefined) => {
    const type = workloadType || 'deployment';
    const label = type.charAt(0).toUpperCase() + type.slice(1);
    let color: 'grey' | 'orange' | 'gold' | 'purple' = 'grey';
    if (type === 'job') {
      color = 'orange';
    } else if (type === 'statefulset') {
      color = 'gold';
    } else if (type === 'sandbox') {
      color = 'purple';
    }
    return <Label color={color} isCompact>{label}</Label>;
  };
```

- [ ] **Step 2: Add sandbox to AgentDetailPage status badge**

In `AgentDetailPage.tsx`, find the workloadType label rendering (line 428):

```tsx
                          <Label color={workloadType === 'job' ? 'orange' : workloadType === 'statefulset' ? 'gold' : 'grey'} isCompact>
```

Change to:

```tsx
                          <Label color={workloadType === 'job' ? 'orange' : workloadType === 'statefulset' ? 'gold' : workloadType === 'sandbox' ? 'purple' : 'grey'} isCompact>
```

- [ ] **Step 3: Add sandbox to AgentDetailPage kind mapping**

In `AgentDetailPage.tsx`, find the apiVersion/kind mapping (line 999-1000):

```typescript
                      apiVersion: agent.workloadType === 'statefulset' ? 'apps/v1' : agent.workloadType === 'job' ? 'batch/v1' : 'apps/v1',
                      kind: agent.workloadType === 'statefulset' ? 'StatefulSet' : agent.workloadType === 'job' ? 'Job' : 'Deployment',
```

Change to:

```typescript
                      apiVersion: agent.workloadType === 'sandbox' ? 'agents.x-k8s.io/v1alpha1' : agent.workloadType === 'statefulset' ? 'apps/v1' : agent.workloadType === 'job' ? 'batch/v1' : 'apps/v1',
                      kind: agent.workloadType === 'sandbox' ? 'Sandbox' : agent.workloadType === 'statefulset' ? 'StatefulSet' : agent.workloadType === 'job' ? 'Job' : 'Deployment',
```

- [ ] **Step 4: Commit**

```bash
git add kagenti/ui-v2/src/pages/AgentCatalogPage.tsx kagenti/ui-v2/src/pages/AgentDetailPage.tsx
git commit -s -m "feat: add Sandbox display to agent catalog and detail pages (epic 1155 step 1.8c)"
```

---

### Task 12: E2E tests (epic 1.9)

**Files:**
- Create: `kagenti/tests/e2e/test_agent_sandbox.py`

- [ ] **Step 1: Create E2E test file**

Create `kagenti/tests/e2e/test_agent_sandbox.py`:

```python
"""
E2E tests for agent-sandbox (Sandbox) workload type.

Requires:
- agent-sandbox controller installed in the cluster
- KAGENTI_FEATURE_FLAG_AGENT_SANDBOX=true
- Feature: agent_sandbox enabled in test config
"""

import logging

import httpx
import pytest
from kubernetes.client import ApiException

logger = logging.getLogger(__name__)

SANDBOX_GROUP = "agents.x-k8s.io"
SANDBOX_VERSION = "v1alpha1"
SANDBOX_PLURAL = "sandboxes"
TEST_NAMESPACE = "team1"
TEST_AGENT_NAME = "sandbox-e2e-test"
TEST_IMAGE = "ghcr.io/kagenti/examples/echo-agent:v0.0.1"


@pytest.mark.requires_features(["agent_sandbox"])
class TestAgentSandboxWorkloadType:
    """Test Sandbox as a fourth workload type in Kagenti."""

    @pytest.fixture(autouse=True)
    def setup(self, http_client):
        self.client = http_client

    async def _get_auth_token(self) -> str:
        """Get auth token from Keycloak (reuses existing conftest patterns)."""
        # This will be populated based on the cluster's auth setup
        # For Kind clusters without auth, return empty string
        return ""

    async def _api_headers(self) -> dict:
        """Build API request headers."""
        token = await self._get_auth_token()
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        return headers

    @pytest.mark.asyncio
    async def test_feature_flag_exposed(self):
        """Verify agentSandbox flag is returned by /api/v1/config/features."""
        headers = await self._api_headers()
        resp = await self.client.get(
            "http://localhost:8080/api/v1/config/features",
            headers=headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "agentSandbox" in data

    @pytest.mark.asyncio
    async def test_create_sandbox_agent(self):
        """Create an agent with workloadType=sandbox."""
        headers = await self._api_headers()
        payload = {
            "name": TEST_AGENT_NAME,
            "namespace": TEST_NAMESPACE,
            "protocol": "a2a",
            "framework": "LangGraph",
            "workloadType": "sandbox",
            "deploymentMethod": "image",
            "containerImage": TEST_IMAGE,
            "authBridgeEnabled": True,
        }
        resp = await self.client.post(
            "http://localhost:8080/api/v1/agents/create",
            json=payload,
            headers=headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True

    @pytest.mark.asyncio
    async def test_list_includes_sandbox_agent(self):
        """Verify the sandbox agent appears in the agent list."""
        headers = await self._api_headers()
        resp = await self.client.get(
            f"http://localhost:8080/api/v1/agents/{TEST_NAMESPACE}",
            headers=headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        names = [a["name"] for a in data["items"]]
        assert TEST_AGENT_NAME in names
        sandbox_agent = next(a for a in data["items"] if a["name"] == TEST_AGENT_NAME)
        assert sandbox_agent["workloadType"] == "sandbox"

    @pytest.mark.asyncio
    async def test_get_sandbox_agent_detail(self):
        """Verify get agent returns Sandbox details."""
        headers = await self._api_headers()
        resp = await self.client.get(
            f"http://localhost:8080/api/v1/agents/{TEST_NAMESPACE}/{TEST_AGENT_NAME}",
            headers=headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["workloadType"] == "sandbox"
        assert data["metadata"]["labels"]["kagenti.io/type"] == "agent"

    @pytest.mark.asyncio
    async def test_delete_sandbox_agent(self):
        """Delete the sandbox agent and verify cleanup."""
        headers = await self._api_headers()
        resp = await self.client.delete(
            f"http://localhost:8080/api/v1/agents/{TEST_NAMESPACE}/{TEST_AGENT_NAME}",
            headers=headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert "Sandbox" in data["message"]
```

- [ ] **Step 2: Commit**

```bash
git add kagenti/tests/e2e/test_agent_sandbox.py
git commit -s -m "feat: add E2E tests for Sandbox workload type (epic 1155 step 1.9)"
```

---

## Epic coverage matrix

| Epic step | Task | Status |
|-----------|------|--------|
| 1.1 Feature flag + constants | Task 1, Task 8 | Covered |
| 1.2 KubernetesService CRUD | Task 2 | Covered |
| 1.3 Manifest builder | Task 3 | Covered |
| 1.4 Router integration | Task 4, Task 5 | Covered |
| 1.5 Reconciliation | Task 6 | Covered |
| 1.6 Operator compatibility | N/A (verification only, no code changes — webhook injection works via labels) | Covered by design |
| 1.7 CRD detection | Task 7 | Covered |
| 1.8 UI changes | Task 9, Task 10, Task 11 | Covered |
| 1.9 E2E tests | Task 12 | Covered |
