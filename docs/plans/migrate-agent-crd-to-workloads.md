# Migration Plan: Agent CRD to Standard Kubernetes Workloads

**Status:** Draft
**Created:** 2026-01-23
**Target:** Kagenti UI v2.x

## Executive Summary

This document outlines the phased migration of the Kagenti UI from managing agents
via the custom `Agent` CRD (processed by kagenti-operator) to directly creating
standard Kubernetes workloads (Deployments, Services, and eventually StatefulSets
and Jobs).

**Goals:**
- Remove dependency on kagenti-operator for agent deployment
- Use standard Kubernetes primitives for better portability
- Maintain backward compatibility during transition
- Enable future support for StatefulSets and Jobs

---

## Table of Contents

1. [Current State Analysis](#1-current-state-analysis)
2. [Target State](#2-target-state)
3. [Label Standards](#3-label-standards)
4. [Migration Phases](#4-migration-phases)
   - [Phase 1: Backend Infrastructure](#phase-1-backend-infrastructure)
   - [Phase 2: Deployment Support](#phase-2-deployment-support)
   - [Phase 3: Frontend Updates](#phase-3-frontend-updates)
   - [Phase 4: Migration Tooling](#phase-4-migration-tooling)
   - [Phase 5: Future Workload Types](#phase-5-future-workload-types-placeholder)
5. [API Changes](#5-api-changes)
6. [RBAC Requirements](#6-rbac-requirements)
7. [Testing Strategy](#7-testing-strategy)
8. [Rollback Plan](#8-rollback-plan)

---

## 1. Current State Analysis

### Current Architecture

```
┌─────────────┐     POST /agents     ┌─────────────────┐
│  Kagenti UI │ ──────────────────▶  │ Backend (FastAPI)│
└─────────────┘                      └────────┬────────┘
                                              │
                                              │ Creates Agent CRD
                                              ▼
                                     ┌─────────────────┐
                                     │  Kubernetes API │
                                     └────────┬────────┘
                                              │
                                              │ Watches Agent CRD
                                              ▼
                                     ┌─────────────────┐
                                     │kagenti-operator │
                                     └────────┬────────┘
                                              │
                                              │ Creates
                                              ▼
                              ┌───────────────┴───────────────┐
                              │                               │
                       ┌──────▼──────┐               ┌───────▼───────┐
                       │  Deployment │               │    Service    │
                       └─────────────┘               └───────────────┘
```

### Current Agent CRD Structure

**File:** `kagenti/backend/app/routers/agents.py` (lines 1006-1136)

```yaml
apiVersion: agent.kagenti.dev/v1alpha1
kind: Agent
metadata:
  name: <agent-name>
  namespace: <namespace>
  labels:
    app.kubernetes.io/created-by: kagenti-ui
    app.kubernetes.io/name: kagenti-operator
    kagenti.io/type: agent
    kagenti.io/protocol: <protocol>
    kagenti.io/framework: <framework>
spec:
  description: "Agent description"
  replicas: 1
  servicePorts:
    - name: http
      port: 8080
      targetPort: 8000
      protocol: TCP
  imageSource:
    image: <image-url>
  podTemplateSpec:
    spec:
      containers:
        - name: agent
          image: <image-url>
          env: [...]
          ports: [...]
          resources: {...}
          volumeMounts: [...]
      volumes: [...]
```

### Key Backend Files

| File | Purpose | Lines of Interest |
|------|---------|-------------------|
| `kagenti/backend/app/routers/agents.py` | Agent API endpoints | 1006-1136 (manifest), 262-299 (list) |
| `kagenti/backend/app/services/kubernetes.py` | K8s API wrapper | 82-103 (list resources) |
| `kagenti/backend/app/core/constants.py` | CRD/label constants | All |

### Key Frontend Files

| File | Purpose |
|------|---------|
| `kagenti/ui-v2/src/pages/AgentCatalogPage.tsx` | Agent listing |
| `kagenti/ui-v2/src/pages/AgentDetailPage.tsx` | Agent details |
| `kagenti/ui-v2/src/pages/ImportAgentPage.tsx` | Agent creation |
| `kagenti/ui-v2/src/services/api.ts` | API client |
| `kagenti/ui-v2/src/types/index.ts` | TypeScript types |

---

## 2. Target State

### Target Architecture

```
┌─────────────┐     POST /agents     ┌─────────────────┐
│  Kagenti UI │ ──────────────────▶  │ Backend (FastAPI)│
└─────────────┘                      └────────┬────────┘
                                              │
                                              │ Creates directly
                                              ▼
                                     ┌─────────────────┐
                                     │  Kubernetes API │
                                     └────────┬────────┘
                                              │
                              ┌───────────────┼───────────────┐
                              │               │               │
                       ┌──────▼──────┐ ┌─────▼─────┐ ┌───────▼───────┐
                       │  Deployment │ │  Service  │ │  HTTPRoute    │
                       └─────────────┘ └───────────┘ └───────────────┘
```

### Benefits

1. **No operator dependency** - Agents work without kagenti-operator running
2. **Standard K8s primitives** - Better tooling support (kubectl, Lens, etc.)
3. **Simpler debugging** - Direct inspection of Deployments/Services
4. **Future flexibility** - Easy to add StatefulSets, Jobs, CronJobs

---

## 3. Label Standards

### Required Labels (All Workloads)

All agent workloads (Deployment, StatefulSet, Job) and their managed Pods MUST have:

| Label | Value | Purpose |
|-------|-------|---------|
| `kagenti.io/type` | `agent` | Identifies resource as a Kagenti agent |
| `app.kubernetes.io/name` | `<agent-name>` | Standard K8s app name label |
| `kagenti.io/protocol` | `a2a` | Protocol type (a2a, mcp, etc.) |

### Recommended Labels

| Label | Value | Purpose |
|-------|-------|---------|
| `app.kubernetes.io/managed-by` | `kagenti-ui` | Resource manager |
| `app.kubernetes.io/component` | `agent` | Component type |
| `kagenti.io/framework` | `<framework>` | Framework (LangGraph, CrewAI, etc.) |
| `kagenti.io/workload-type` | `deployment` | Workload type (deployment/statefulset/job) |

### Label Selector for Agents

To list all agents in a namespace:

```
kagenti.io/type=agent
```

To list all A2A agents:

```
kagenti.io/type=agent,kagenti.io/protocol=a2a
```

---

## 4. Migration Phases

### Phase 1: Backend Infrastructure

**Goal:** Add backend support for creating/managing Deployments and Services directly.

#### 1.1 Add Kubernetes Core API Methods

**File:** `kagenti/backend/app/services/kubernetes.py`

Add new methods for core Kubernetes resources:

```python
# Deployments
def create_deployment(namespace: str, body: dict) -> dict
def get_deployment(namespace: str, name: str) -> dict
def list_deployments(namespace: str, label_selector: str = None) -> list
def delete_deployment(namespace: str, name: str) -> None
def patch_deployment(namespace: str, name: str, body: dict) -> dict

# Services
def create_service(namespace: str, body: dict) -> dict
def get_service(namespace: str, name: str) -> dict
def delete_service(namespace: str, name: str) -> None

# Future: StatefulSets (placeholder)
def create_statefulset(namespace: str, body: dict) -> dict
def get_statefulset(namespace: str, name: str) -> dict
def list_statefulsets(namespace: str, label_selector: str = None) -> list
def delete_statefulset(namespace: str, name: str) -> None

# Future: Jobs (placeholder)
def create_job(namespace: str, body: dict) -> dict
def get_job(namespace: str, name: str) -> dict
def list_jobs(namespace: str, label_selector: str = None) -> list
def delete_job(namespace: str, name: str) -> None
```

#### 1.2 Update Constants

**File:** `kagenti/backend/app/core/constants.py`

```python
# Workload types
WORKLOAD_TYPE_DEPLOYMENT = "deployment"
WORKLOAD_TYPE_STATEFULSET = "statefulset"  # Future
WORKLOAD_TYPE_JOB = "job"  # Future

# Label keys
LABEL_KAGENTI_TYPE = "kagenti.io/type"
LABEL_KAGENTI_PROTOCOL = "kagenti.io/protocol"
LABEL_KAGENTI_FRAMEWORK = "kagenti.io/framework"
LABEL_KAGENTI_WORKLOAD_TYPE = "kagenti.io/workload-type"
LABEL_APP_NAME = "app.kubernetes.io/name"
LABEL_MANAGED_BY = "app.kubernetes.io/managed-by"

# Label values
VALUE_TYPE_AGENT = "agent"
VALUE_MANAGED_BY_UI = "kagenti-ui"
```

#### 1.3 Add Manifest Builders

**File:** `kagenti/backend/app/routers/agents.py` (new functions)

```python
def _build_deployment_manifest(request: CreateAgentRequest, image: str) -> dict:
    """Build Kubernetes Deployment manifest for an agent."""

def _build_service_manifest(request: CreateAgentRequest) -> dict:
    """Build Kubernetes Service manifest for an agent."""

# Future placeholders
def _build_statefulset_manifest(request: CreateAgentRequest, image: str) -> dict:
    """Build Kubernetes StatefulSet manifest for an agent. (Future)"""
    raise NotImplementedError("StatefulSet support coming in future release")

def _build_job_manifest(request: CreateAgentRequest, image: str) -> dict:
    """Build Kubernetes Job manifest for an agent. (Future)"""
    raise NotImplementedError("Job support coming in future release")
```

---

### Phase 2: Deployment Support

**Goal:** Implement full Deployment + Service creation workflow.

#### 2.1 Deployment Manifest Structure

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: <agent-name>
  namespace: <namespace>
  labels:
    kagenti.io/type: agent
    kagenti.io/protocol: a2a
    kagenti.io/framework: <framework>
    kagenti.io/workload-type: deployment
    app.kubernetes.io/name: <agent-name>
    app.kubernetes.io/managed-by: kagenti-ui
  annotations:
    kagenti.io/description: "<description>"
    kagenti.io/shipwright-build: "<build-name>"  # if built from source
spec:
  replicas: 1
  selector:
    matchLabels:
      kagenti.io/type: agent
      app.kubernetes.io/name: <agent-name>
  template:
    metadata:
      labels:
        kagenti.io/type: agent
        kagenti.io/protocol: a2a
        kagenti.io/framework: <framework>
        app.kubernetes.io/name: <agent-name>
    spec:
      containers:
        - name: agent
          image: <image>
          imagePullPolicy: Always
          env:
            - name: PORT
              value: "8000"
            - name: HOST
              value: "0.0.0.0"
            # ... other env vars
          ports:
            - containerPort: 8000
              name: http
              protocol: TCP
          resources:
            requests:
              cpu: 100m
              memory: 256Mi
            limits:
              cpu: 500m
              memory: 1Gi
          volumeMounts:
            - name: cache
              mountPath: /app/.cache
            - name: shared-data
              mountPath: /shared
      volumes:
        - name: cache
          emptyDir: {}
        - name: shared-data
          emptyDir: {}
```

#### 2.2 Service Manifest Structure

```yaml
apiVersion: v1
kind: Service
metadata:
  name: <agent-name>
  namespace: <namespace>
  labels:
    kagenti.io/type: agent
    kagenti.io/protocol: a2a
    app.kubernetes.io/name: <agent-name>
    app.kubernetes.io/managed-by: kagenti-ui
spec:
  type: ClusterIP
  selector:
    kagenti.io/type: agent
    app.kubernetes.io/name: <agent-name>
  ports:
    - name: http
      port: 8080
      targetPort: 8000
      protocol: TCP
```

#### 2.3 Update Agent Creation Endpoint

**File:** `kagenti/backend/app/routers/agents.py`

Modify `create_agent()` endpoint to:

1. Accept new parameter `workload_type` (default: `deployment`)
2. Create Deployment instead of Agent CRD
3. Create Service for the Deployment
4. Create HTTPRoute (unchanged)

```python
@router.post("/agents")
async def create_agent(request: CreateAgentRequest):
    # Validate workload type
    if request.workload_type not in [WORKLOAD_TYPE_DEPLOYMENT]:
        raise HTTPException(400, f"Unsupported workload type: {request.workload_type}")

    # Build and create Deployment
    deployment_manifest = _build_deployment_manifest(request, image)
    k8s.create_deployment(request.namespace, deployment_manifest)

    # Build and create Service
    service_manifest = _build_service_manifest(request)
    k8s.create_service(request.namespace, service_manifest)

    # Create HTTPRoute if requested (unchanged)
    if request.create_route:
        # ... existing HTTPRoute logic
```

#### 2.4 Update Agent List Endpoint

**File:** `kagenti/backend/app/routers/agents.py`

Modify `list_agents()` to query Deployments instead of Agent CRD:

```python
@router.get("/agents")
async def list_agents(namespace: str):
    label_selector = f"{LABEL_KAGENTI_TYPE}={VALUE_TYPE_AGENT}"

    deployments = k8s.list_deployments(namespace, label_selector)
    # Future: Also list StatefulSets and Jobs with same selector

    agents = []
    for deploy in deployments:
        agents.append({
            "name": deploy["metadata"]["name"],
            "namespace": deploy["metadata"]["namespace"],
            "status": _get_deployment_status(deploy),
            "labels": deploy["metadata"].get("labels", {}),
            "workloadType": "deployment",
            # ... other fields
        })

    return agents
```

#### 2.5 Update Agent Get Endpoint

Return Deployment details with associated Service info:

```python
@router.get("/agents/{namespace}/{name}")
async def get_agent(namespace: str, name: str):
    deployment = k8s.get_deployment(namespace, name)
    service = k8s.get_service(namespace, name)

    return {
        "metadata": deployment["metadata"],
        "spec": deployment["spec"],
        "status": _get_deployment_status(deployment),
        "service": service,
        "workloadType": "deployment",
    }
```

#### 2.6 Update Agent Delete Endpoint

Delete Deployment, Service, and associated resources:

```python
@router.delete("/agents/{namespace}/{name}")
async def delete_agent(namespace: str, name: str):
    deleted = []

    # Delete Deployment
    try:
        k8s.delete_deployment(namespace, name)
        deleted.append(f"Deployment/{name}")
    except NotFoundError:
        pass

    # Delete Service
    try:
        k8s.delete_service(namespace, name)
        deleted.append(f"Service/{name}")
    except NotFoundError:
        pass

    # Delete HTTPRoute (unchanged)
    # Delete Shipwright Build/BuildRun (unchanged)

    return {"deleted": deleted}
```

#### 2.7 Update Shipwright Build Finalization

Modify `finalize_shipwright_build()` to create Deployment instead of Agent CRD:

```python
@router.post("/agents/{namespace}/{name}/finalize-shipwright-build")
async def finalize_shipwright_build(namespace: str, name: str, request: FinalizeRequest):
    # ... get build info, validate success ...

    # Create Deployment instead of Agent CRD
    deployment_manifest = _build_deployment_manifest(config, output_image)
    k8s.create_deployment(namespace, deployment_manifest)

    # Create Service
    service_manifest = _build_service_manifest(config)
    k8s.create_service(namespace, service_manifest)

    # Create HTTPRoute if requested
    # ...
```

---

### Phase 3: Frontend Updates

**Goal:** Update frontend to work with new Deployment-based agents.

#### 3.1 Update Type Definitions

**File:** `kagenti/ui-v2/src/types/index.ts`

```typescript
// Workload types
export type WorkloadType = 'deployment' | 'statefulset' | 'job';

export interface Agent {
  name: string;
  namespace: string;
  description?: string;
  status: 'Ready' | 'Not Ready' | 'Progressing' | 'Failed';
  labels: {
    protocol?: string;
    framework?: string;
    type?: string;
  };
  workloadType: WorkloadType;
  createdAt?: string;
}

export interface AgentDetail {
  metadata: {
    name: string;
    namespace: string;
    labels: Record<string, string>;
    annotations?: Record<string, string>;
    creationTimestamp: string;
    uid: string;
  };
  spec: {
    replicas?: number;
    template?: {
      spec: {
        containers: Array<{
          image: string;
          env?: Array<{ name: string; value?: string }>;
        }>;
      };
    };
  };
  status: DeploymentStatus;
  service?: ServiceInfo;
  workloadType: WorkloadType;
}

export interface DeploymentStatus {
  replicas?: number;
  readyReplicas?: number;
  availableReplicas?: number;
  conditions?: Array<{
    type: string;
    status: string;
    reason?: string;
    message?: string;
    lastTransitionTime?: string;
  }>;
}

export interface CreateAgentRequest {
  // ... existing fields ...
  workloadType?: WorkloadType;  // default: 'deployment'
}
```

#### 3.2 Update Agent Catalog Page

**File:** `kagenti/ui-v2/src/pages/AgentCatalogPage.tsx`

- Add workload type indicator (icon or badge)
- Update status logic for Deployment conditions
- No major UI changes needed

#### 3.3 Update Agent Detail Page

**File:** `kagenti/ui-v2/src/pages/AgentDetailPage.tsx`

- Update status tab to show Deployment conditions
- Show replica count and availability
- Show Service information (ClusterIP, ports)
- Update YAML tab to show Deployment YAML

#### 3.4 Update Import Agent Page

**File:** `kagenti/ui-v2/src/pages/ImportAgentPage.tsx`

- Add workload type selector (disabled for now, default to Deployment)
- Update form submission to include `workloadType`

```typescript
// Future: Workload type selector (Phase 5)
<FormGroup label="Workload Type" fieldId="workload-type">
  <FormSelect
    value={workloadType}
    onChange={(_, value) => setWorkloadType(value as WorkloadType)}
    isDisabled={true}  // Enable in Phase 5
  >
    <FormSelectOption value="deployment" label="Deployment (Recommended)" />
    <FormSelectOption value="statefulset" label="StatefulSet" isDisabled />
    <FormSelectOption value="job" label="Job" isDisabled />
  </FormSelect>
  <FormHelperText>
    StatefulSet and Job support coming soon.
  </FormHelperText>
</FormGroup>
```

---

### Phase 4: Migration Tooling

**Goal:** Provide tools to migrate existing Agent CRD resources to Deployments.

**Status:** ✅ Implemented

#### 4.1 CLI Migration Script

**File:** `kagenti/tools/migrate_agents.py`

A command-line tool for migrating Agent CRDs to Kubernetes Deployments.

##### Installation

The script is included in the kagenti package. Ensure you have the kubernetes Python package installed:

```bash
pip install kubernetes
```

##### Usage

```bash
# Basic usage - list agents that can be migrated (dry-run by default)
python -m kagenti.tools.migrate_agents --namespace <namespace>

# Dry-run migration (shows what would happen without making changes)
python -m kagenti.tools.migrate_agents --namespace team1 --dry-run

# Actually perform the migration
python -m kagenti.tools.migrate_agents --namespace team1 --no-dry-run

# Migrate and delete old Agent CRDs after successful migration
python -m kagenti.tools.migrate_agents --namespace team1 --no-dry-run --delete-old

# Migrate a specific agent only
python -m kagenti.tools.migrate_agents --namespace team1 --agent my-agent --no-dry-run

# Output results as JSON (useful for scripting)
python -m kagenti.tools.migrate_agents --namespace team1 --json

# Verbose output for debugging
python -m kagenti.tools.migrate_agents --namespace team1 -v
```

##### Command-Line Options

| Option | Short | Default | Description |
|--------|-------|---------|-------------|
| `--namespace` | `-n` | `default` | Kubernetes namespace to migrate agents from |
| `--agent` | `-a` | (all) | Specific agent name to migrate (migrates all if not specified) |
| `--dry-run` | | `True` | Show what would be done without making changes |
| `--no-dry-run` | | | Actually perform the migration |
| `--delete-old` | | `False` | Delete Agent CRDs after successful migration |
| `--json` | | `False` | Output results as JSON |
| `--verbose` | `-v` | `False` | Enable verbose logging |

##### Migration Logic

1. **List Agent CRDs**: Query all Agent CRDs in the specified namespace
2. **Check for existing Deployments**: Skip agents that already have a Deployment with the same name
3. **Build Deployment manifest**: Extract configuration from Agent CRD and build Deployment spec
4. **Build Service manifest**: Create matching Service for the agent
5. **Create resources**: Apply Deployment and Service to cluster
6. **Cleanup (optional)**: Delete the original Agent CRD if `--delete-old` is specified

##### Migration Annotations

Migrated Deployments include tracking annotations:

```yaml
annotations:
  kagenti.io/migrated-from: "agent-crd"
  kagenti.io/migration-timestamp: "2026-01-23T10:30:00+00:00"
```

##### Example Output

```
============================================================
Kagenti Agent CRD Migration - DRY-RUN
============================================================
Namespace: team1
Delete old CRDs: False
Total Agent CRDs found: 3
============================================================

🔍 weather-agent: dry-run
   - Would create Deployment
   - Would create Service

🔍 chat-agent: dry-run
   - Would create Deployment
   - Service already exists

⏭️ data-processor: skipped
   - Deployment already exists

============================================================
SUMMARY
============================================================
Total: 3
Would migrate: 2
Skipped (already migrated): 1
Failed: 0
============================================================

💡 This was a dry-run. Use --no-dry-run to actually perform the migration.
```

##### JSON Output Format

When using `--json`, the output follows this structure:

```json
{
  "namespace": "team1",
  "dry_run": true,
  "delete_old": false,
  "total": 3,
  "migrated": 0,
  "skipped": 1,
  "failed": 0,
  "dry_run_count": 2,
  "results": [
    {
      "name": "weather-agent",
      "namespace": "team1",
      "status": "dry-run",
      "deployment_created": false,
      "service_created": false,
      "agent_crd_deleted": false,
      "messages": ["Would create Deployment", "Would create Service"],
      "errors": []
    }
  ]
}
```

#### 4.2 Backend Migration Endpoints

**File:** `kagenti/backend/app/routers/agents.py`

Three API endpoints are available for migration:

##### List Migratable Agents

```http
GET /agents/migration/migratable?namespace=team1
```

Returns a list of Agent CRDs that can be migrated, indicating which already have Deployments.

##### Migrate Single Agent

```http
POST /agents/{namespace}/{name}/migrate
Content-Type: application/json

{
  "delete_old": false
}
```

Migrates a single Agent CRD to a Deployment.

##### Batch Migration

```http
POST /agents/migration/migrate-all?namespace=team1&dry_run=true&delete_old=false
```

Migrates all Agent CRDs in a namespace with optional dry-run mode.

#### 4.3 Backward Compatibility Period

**File:** `kagenti/backend/app/core/config.py`

During the migration period, the backend supports both Agent CRDs and Deployments via the `enable_legacy_agent_crd` setting:

```python
# config.py
enable_legacy_agent_crd: bool = True  # Set to False after full migration
```

When enabled, the `list_agents` endpoint will:

1. Query Deployments with `kagenti.io/type=agent` label
2. Query Agent CRDs in the namespace
3. Skip Agent CRDs that already have a corresponding Deployment (already migrated)
4. Return a combined list of both Deployment-based and CRD-based agents

##### Disabling Legacy Support

After migration is complete:

1. Set `ENABLE_LEGACY_AGENT_CRD=false` environment variable
2. Restart the backend service
3. Only Deployment-based agents will be listed
4. Agent CRDs can be cleaned up from the cluster

---

### Phase 5: Future Workload Types (Placeholder)

**Goal:** Add support for StatefulSets and Jobs.

#### 5.1 StatefulSet Support

**Use cases:**
- Agents requiring stable network identities
- Agents requiring persistent storage
- Agents requiring ordered deployment/scaling

**Implementation:**
- Add `_build_statefulset_manifest()` function
- Add StatefulSet CRUD operations to kubernetes.py
- Update list/get/delete endpoints to handle StatefulSets
- Add PVC template support
- Enable StatefulSet option in Import page

#### 5.2 Job Support

**Use cases:**
- One-time agent tasks
- Batch processing agents
- Scheduled agent runs (CronJob)

**Implementation:**
- Add `_build_job_manifest()` function
- Add Job CRUD operations to kubernetes.py
- Different status handling (Succeeded/Failed vs Running)
- Optional CronJob support

#### 5.3 Workload Type Auto-Selection

Consider auto-selecting workload type based on agent requirements:

```python
def _determine_workload_type(request: CreateAgentRequest) -> WorkloadType:
    if request.persistent_storage:
        return WORKLOAD_TYPE_STATEFULSET
    if request.run_once:
        return WORKLOAD_TYPE_JOB
    return WORKLOAD_TYPE_DEPLOYMENT
```

---

## 5. API Changes

### New/Modified Endpoints

| Endpoint | Change | Phase |
|----------|--------|-------|
| `POST /agents` | Add `workload_type` param, create Deployment+Service | 2 |
| `GET /agents` | Query Deployments instead of Agent CRD | 2 |
| `GET /agents/{ns}/{name}` | Return Deployment details | 2 |
| `DELETE /agents/{ns}/{name}` | Delete Deployment+Service | 2 |
| `POST /agents/{ns}/{name}/finalize-shipwright-build` | Create Deployment instead of Agent | 2 |
| `POST /agents/{ns}/{name}/migrate` | New: Migrate Agent CRD to Deployment | 4 |

### Request/Response Schema Changes

**CreateAgentRequest:**
```json
{
  "name": "my-agent",
  "namespace": "team1",
  "workloadType": "deployment",  // NEW: default "deployment"
  // ... other fields unchanged
}
```

**Agent (list response):**
```json
{
  "name": "my-agent",
  "namespace": "team1",
  "status": "Ready",
  "workloadType": "deployment",  // NEW
  "labels": {...}
}
```

**AgentDetail (get response):**
```json
{
  "metadata": {...},
  "spec": {...},  // Deployment spec instead of Agent spec
  "status": {...},  // Deployment status
  "service": {...},  // NEW: Service info
  "workloadType": "deployment"  // NEW
}
```

---

## 6. RBAC Requirements

### New Permissions Required

The Kagenti backend ServiceAccount needs additional permissions:

```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: kagenti-backend
rules:
  # Existing permissions for CRDs...

  # NEW: Deployments
  - apiGroups: ["apps"]
    resources: ["deployments"]
    verbs: ["get", "list", "create", "update", "patch", "delete"]

  # NEW: Services
  - apiGroups: [""]
    resources: ["services"]
    verbs: ["get", "list", "create", "delete"]

  # NEW: Pods (for status/logs)
  - apiGroups: [""]
    resources: ["pods", "pods/log"]
    verbs: ["get", "list"]

  # Future: StatefulSets
  - apiGroups: ["apps"]
    resources: ["statefulsets"]
    verbs: ["get", "list", "create", "update", "patch", "delete"]

  # Future: Jobs
  - apiGroups: ["batch"]
    resources: ["jobs"]
    verbs: ["get", "list", "create", "delete"]
```

### Helm Chart Updates

**File:** `charts/kagenti/templates/ui.yaml`

Update the RBAC rules for the kagenti-backend ServiceAccount.

---

## 7. Testing Strategy

### Unit Tests

- Test manifest builders produce valid YAML
- Test label selectors return correct resources
- Test status mapping logic

### Integration Tests

- Create agent via API, verify Deployment + Service created
- Delete agent, verify cleanup
- Build agent from source, verify finalization creates Deployment
- Test migration endpoint

### E2E Tests

**File:** `kagenti/tests/e2e/`

- Full workflow: Import agent → Build → Deploy → Chat → Delete
- Migration: Create Agent CRD → Migrate → Verify Deployment

### Manual Testing Checklist

- [ ] Import agent from image (Deployment created)
- [ ] Import agent from source (Build → Deployment)
- [ ] Agent appears in catalog with correct status
- [ ] Agent detail page shows Deployment info
- [ ] Chat works with Deployment-based agent
- [ ] Delete agent cleans up all resources
- [ ] HTTPRoute works correctly
- [ ] Migrate existing Agent CRD to Deployment

---

## 8. Rollback Plan

### Feature Flag

Add feature flag to switch between Agent CRD and Deployment modes:

```python
# config.py
USE_DEPLOYMENT_WORKLOADS = os.getenv("USE_DEPLOYMENT_WORKLOADS", "true").lower() == "true"
```

### Rollback Steps

1. Set `USE_DEPLOYMENT_WORKLOADS=false`
2. Restart backend
3. New agents will use Agent CRD
4. Existing Deployment-based agents continue to work
5. Run reverse migration if needed

### Data Preservation

- Deployments can be converted back to Agent CRD if needed
- All configuration stored in Deployment spec/annotations
- Shipwright Build resources unchanged

---

## Implementation Timeline

| Phase | Description | Estimated Effort |
|-------|-------------|------------------|
| 1 | Backend Infrastructure | Medium |
| 2 | Deployment Support | Large |
| 3 | Frontend Updates | Medium |
| 4 | Migration Tooling | Small |
| 5 | Future Workload Types | Future |

---

## Open Questions

1. **Should we support both Agent CRD and Deployments long-term?**
   - Recommendation: Deprecate Agent CRD after migration period

2. **How to handle agents created by kagenti-operator?**
   - They have associated Deployments already
   - Migration may need to transfer ownership

3. **Should the migration be automatic or manual?**
   - Recommendation: Manual with tooling support

4. **What about agents with custom operator features?**
   - Some Agent CRD features may not map 1:1 to Deployment
   - Document any feature gaps

---

## References

- [Kubernetes Deployments](https://kubernetes.io/docs/concepts/workloads/controllers/deployment/)
- [Kubernetes Services](https://kubernetes.io/docs/concepts/services-networking/service/)
- [Kubernetes Labels and Selectors](https://kubernetes.io/docs/concepts/overview/working-with-objects/labels/)
- [Kubernetes Recommended Labels](https://kubernetes.io/docs/concepts/overview/working-with-objects/common-labels/)
