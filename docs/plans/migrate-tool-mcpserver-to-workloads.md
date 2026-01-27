# Migration Plan: MCPServer CRD to Standard Kubernetes Workloads

**Status:** Draft
**Created:** 2026-01-26
**Target:** Kagenti UI v2.x

## Executive Summary

This document outlines the phased migration of the Kagenti UI from managing MCP tools
via the Toolhive `MCPServer` CRD to directly creating standard Kubernetes workloads
(Deployments and StatefulSets). This migration removes the dependency on the Toolhive
operator while maintaining full MCP tool functionality.

**Goals:**
- Remove dependency on Toolhive operator for tool deployment
- Use standard Kubernetes primitives for better portability
- Maintain backward compatibility during transition
- Support both Deployments and StatefulSets for tools

**Scope:**
- Deployments (primary workload type)
- StatefulSets (for tools requiring persistent state)
- Services (must be created by UI - previously handled by Toolhive operator)

---

## Table of Contents

1. [Current State Analysis](#1-current-state-analysis)
2. [Target State](#2-target-state)
3. [Label Standards](#3-label-standards)
4. [Migration Phases](#4-migration-phases)
   - [Phase 1: Backend Infrastructure](#phase-1-backend-infrastructure)
   - [Phase 2: Deployment Support](#phase-2-deployment-support)
   - [Phase 3: StatefulSet Support](#phase-3-statefulset-support)
   - [Phase 4: Frontend Updates](#phase-4-frontend-updates)
   - [Phase 5: Migration Tooling](#phase-5-migration-tooling)
   - [Phase 6: CI/E2E Test Updates](#phase-6-cie2e-test-updates)
5. [API Changes](#5-api-changes)
6. [MCP Connection Updates](#6-mcp-connection-updates)
7. [RBAC Requirements](#7-rbac-requirements)
8. [Testing Strategy](#8-testing-strategy)
9. [Rollback Plan](#9-rollback-plan)

---

## 1. Current State Analysis

### Current Architecture

```
┌─────────────┐     POST /tools      ┌─────────────────┐
│  Kagenti UI │ ──────────────────▶  │ Backend (FastAPI)│
└─────────────┘                      └────────┬────────┘
                                              │
                                              │ Creates MCPServer CRD
                                              ▼
                                     ┌─────────────────┐
                                     │  Kubernetes API │
                                     └────────┬────────┘
                                              │
                                              │ Watches MCPServer CRD
                                              ▼
                                     ┌─────────────────┐
                                     │Toolhive Operator│
                                     └────────┬────────┘
                                              │
                                              │ Creates
                                              ▼
                              ┌───────────────┴───────────────┐
                              │                               │
                       ┌──────▼──────┐               ┌───────▼───────┐
                       │     Pod     │               │    Service    │
                       └─────────────┘               │mcp-{name}-proxy│
                                                     └───────────────┘
```

### Current MCPServer CRD Structure

**API Version:** `toolhive.stacklok.dev/v1alpha1`
**Kind:** `MCPServer`

**File:** `kagenti/backend/app/routers/tools.py` (lines 458-538)

```yaml
apiVersion: toolhive.stacklok.dev/v1alpha1
kind: MCPServer
metadata:
  name: <tool-name>
  namespace: <namespace>
  labels:
    app.kubernetes.io/created-by: kagenti-ui
    kagenti.io/type: tool
    kagenti.io/protocol: streamable_http|sse
    kagenti.io/framework: <framework>
spec:
  image: <image-url>
  transport: streamable-http
  port: 8000
  targetPort: 8000
  proxyPort: 8000
  podTemplateSpec:
    spec:
      serviceAccountName: <tool-name>
      securityContext:
        runAsNonRoot: true
        seccompProfile:
          type: RuntimeDefault
      containers:
        - name: mcp
          image: <image-url>
          env:
            - name: PORT
              value: "8000"
            - name: HOST
              value: "0.0.0.0"
            # ... other env vars
          resources:
            limits:
              cpu: 500m
              memory: 1Gi
            requests:
              cpu: 100m
              memory: 256Mi
          volumeMounts:
            - name: cache
              mountPath: /app/.cache
            - name: tmp
              mountPath: /tmp
      volumes:
        - name: cache
          emptyDir: {}
        - name: tmp
          emptyDir: {}
```

### What Toolhive Operator Creates

When an MCPServer CRD is created, the Toolhive operator automatically provisions:

1. **Pod** - Running the MCP tool container
2. **Service** - Named `mcp-{name}-proxy` on port 8000
3. **MCP Endpoint** - Available at `http://mcp-{name}-proxy.{namespace}.svc.cluster.local:8000/mcp`

### Key Backend Files

| File | Purpose | Lines of Interest |
|------|---------|-------------------|
| `kagenti/backend/app/routers/tools.py` | Tool API endpoints | 458-538 (manifest), 185-244 (list) |
| `kagenti/backend/app/services/kubernetes.py` | K8s API wrapper | 82-103 (list resources) |
| `kagenti/backend/app/core/constants.py` | CRD/label constants | All |

### Key Frontend Files

| File | Purpose |
|------|---------|
| `kagenti/ui-v2/src/pages/ToolCatalogPage.tsx` | Tool listing |
| `kagenti/ui-v2/src/pages/ToolDetailPage.tsx` | Tool details, MCP invocation |
| `kagenti/ui-v2/src/pages/ImportToolPage.tsx` | Tool creation |
| `kagenti/ui-v2/src/pages/ToolBuildProgressPage.tsx` | Build monitoring |
| `kagenti/ui-v2/src/services/api.ts` | API client |

### Current MCP Tool Discovery & Invocation Flow

```
ToolDetailPage → "Connect & List Tools" Button
              → toolService.connect({namespace}, {name})
              → Backend: POST /tools/{ns}/{name}/connect
              → Connect to mcp-{name}-proxy.{ns}.svc.cluster.local:8000/mcp
              → MCP ClientSession.list_tools()
              → Return MCPToolSchema[] (name, description, input_schema)
              → Display tools
              → User invokes tool
              → MCP ClientSession.call_tool(tool_name, args)
              → Display result
```

---

## 2. Target State

### Target Architecture

```
┌─────────────┐     POST /tools      ┌─────────────────┐
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
                       │ Deployment  │ │  Service  │ │  HTTPRoute    │
                       │     or      │ │ {name}-mcp│ │  (optional)   │
                       │ StatefulSet │ └───────────┘ └───────────────┘
                       └─────────────┘
```

### Benefits

1. **No operator dependency** - Tools work without Toolhive operator running
2. **Standard K8s primitives** - Better tooling support (kubectl, Lens, etc.)
3. **Simpler debugging** - Direct inspection of Deployments/Services
4. **StatefulSet support** - Enable tools requiring persistent storage
5. **Consistent with agents** - Same patterns as agent migration

### Service Naming Convention

**Old (Toolhive):** `mcp-{name}-proxy`
**New (Direct):** `{name}-mcp`

This maintains a clear naming convention while indicating MCP protocol.

---

## 3. Label Standards

### Required Labels (All Tool Workloads)

All tool workloads (Deployment, StatefulSet) and their managed Pods **MUST** have:

| Label | Value | Purpose |
|-------|-------|---------|
| `kagenti.io/type` | `tool` | Identifies resource as a Kagenti tool |
| `app.kubernetes.io/name` | `<tool-name>` | Standard K8s app name label |
| `kagenti.io/protocol` | `mcp` | Protocol type |

### Recommended Labels

| Label | Value | Purpose |
|-------|-------|---------|
| `kagenti.io/transport` | `streamable_http` | MCP transport type |
| `app.kubernetes.io/managed-by` | `kagenti-ui` | Resource manager |
| `app.kubernetes.io/component` | `tool` | Component type |
| `kagenti.io/framework` | `<framework>` | Framework (Python, etc.) |
| `kagenti.io/workload-type` | `deployment` or `statefulset` | Workload type |

### Label Selector for Tools

To list all tools in a namespace:

```
kagenti.io/type=tool
```

To list all MCP tools:

```
kagenti.io/type=tool,kagenti.io/protocol=mcp
```

---

## 4. Migration Phases

### Phase 1: Backend Infrastructure

**Goal:** Add backend support for creating/managing Deployments, StatefulSets, and Services for tools.

#### 1.1 Update Constants

**File:** `kagenti/backend/app/core/constants.py`

```python
# Workload types for tools
TOOL_WORKLOAD_TYPE_DEPLOYMENT = "deployment"
TOOL_WORKLOAD_TYPE_STATEFULSET = "statefulset"

# Tool label keys
LABEL_KAGENTI_TYPE = "kagenti.io/type"
LABEL_KAGENTI_PROTOCOL = "kagenti.io/protocol"
LABEL_KAGENTI_TRANSPORT = "kagenti.io/transport"
LABEL_KAGENTI_FRAMEWORK = "kagenti.io/framework"
LABEL_KAGENTI_WORKLOAD_TYPE = "kagenti.io/workload-type"
LABEL_APP_NAME = "app.kubernetes.io/name"
LABEL_MANAGED_BY = "app.kubernetes.io/managed-by"

# Tool label values
VALUE_TYPE_TOOL = "tool"
VALUE_PROTOCOL_MCP = "mcp"
VALUE_TRANSPORT_STREAMABLE_HTTP = "streamable_http"
VALUE_MANAGED_BY_UI = "kagenti-ui"

# Service naming
TOOL_SERVICE_SUFFIX = "-mcp"  # Results in: {name}-mcp
```

#### 1.2 Add Kubernetes Core API Methods

**File:** `kagenti/backend/app/services/kubernetes.py`

Reuse methods from agent migration (Deployments and Services) and add StatefulSet support:

```python
# StatefulSets
def create_statefulset(namespace: str, body: dict) -> dict
def get_statefulset(namespace: str, name: str) -> dict
def list_statefulsets(namespace: str, label_selector: str = None) -> list
def delete_statefulset(namespace: str, name: str) -> None
def patch_statefulset(namespace: str, name: str, body: dict) -> dict
```

#### 1.3 Add Manifest Builders for Tools

**File:** `kagenti/backend/app/routers/tools.py` (new functions)

```python
def _build_tool_deployment_manifest(request: CreateToolRequest, image: str) -> dict:
    """Build Kubernetes Deployment manifest for an MCP tool."""

def _build_tool_statefulset_manifest(request: CreateToolRequest, image: str) -> dict:
    """Build Kubernetes StatefulSet manifest for an MCP tool."""

def _build_tool_service_manifest(request: CreateToolRequest) -> dict:
    """Build Kubernetes Service manifest for an MCP tool."""
```

---

### Phase 2: Deployment Support

**Goal:** Implement full Deployment + Service creation workflow for tools.

#### 2.1 Deployment Manifest Structure

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: <tool-name>
  namespace: <namespace>
  labels:
    kagenti.io/type: tool
    kagenti.io/protocol: mcp
    kagenti.io/transport: streamable_http
    kagenti.io/framework: <framework>
    kagenti.io/workload-type: deployment
    app.kubernetes.io/name: <tool-name>
    app.kubernetes.io/managed-by: kagenti-ui
  annotations:
    kagenti.io/description: "<description>"
    kagenti.io/shipwright-build: "<build-name>"  # if built from source
spec:
  replicas: 1
  selector:
    matchLabels:
      kagenti.io/type: tool
      app.kubernetes.io/name: <tool-name>
  template:
    metadata:
      labels:
        kagenti.io/type: tool
        kagenti.io/protocol: mcp
        kagenti.io/transport: streamable_http
        kagenti.io/framework: <framework>
        app.kubernetes.io/name: <tool-name>
    spec:
      serviceAccountName: <tool-name>
      securityContext:
        runAsNonRoot: true
        seccompProfile:
          type: RuntimeDefault
      containers:
        - name: mcp
          image: <image>
          imagePullPolicy: Always
          env:
            - name: PORT
              value: "8000"
            - name: HOST
              value: "0.0.0.0"
            - name: OTEL_EXPORTER_OTLP_ENDPOINT
              value: "http://..."
            - name: KEYCLOAK_URL
              value: "http://..."
            - name: UV_CACHE_DIR
              value: "/app/.cache"
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
            - name: tmp
              mountPath: /tmp
      volumes:
        - name: cache
          emptyDir: {}
        - name: tmp
          emptyDir: {}
      imagePullSecrets:
        - name: <registry-secret>  # if provided
```

#### 2.2 Service Manifest Structure

```yaml
apiVersion: v1
kind: Service
metadata:
  name: <tool-name>-mcp
  namespace: <namespace>
  labels:
    kagenti.io/type: tool
    kagenti.io/protocol: mcp
    app.kubernetes.io/name: <tool-name>
    app.kubernetes.io/managed-by: kagenti-ui
spec:
  type: ClusterIP
  selector:
    kagenti.io/type: tool
    app.kubernetes.io/name: <tool-name>
  ports:
    - name: http
      port: 8000
      targetPort: 8000
      protocol: TCP
```

#### 2.3 Update Tool Creation Endpoint

**File:** `kagenti/backend/app/routers/tools.py`

Modify `create_tool()` endpoint to:

1. Accept new parameter `workloadType` (default: `deployment`)
2. Create Deployment instead of MCPServer CRD
3. Create Service for the Deployment
4. Create HTTPRoute (unchanged)

```python
@router.post("/tools")
async def create_tool(request: CreateToolRequest):
    # Validate workload type
    if request.workload_type not in [TOOL_WORKLOAD_TYPE_DEPLOYMENT]:
        raise HTTPException(400, f"Unsupported workload type: {request.workload_type}")

    # Build and create Deployment
    deployment_manifest = _build_tool_deployment_manifest(request, image)
    k8s.create_deployment(request.namespace, deployment_manifest)

    # Build and create Service
    service_manifest = _build_tool_service_manifest(request)
    k8s.create_service(request.namespace, service_manifest)

    # Create HTTPRoute if requested (unchanged)
    if request.create_http_route:
        # ... existing HTTPRoute logic
```

#### 2.4 Update Tool List Endpoint

**File:** `kagenti/backend/app/routers/tools.py`

Modify `list_tools()` to query Deployments instead of MCPServer CRD:

```python
@router.get("/tools")
async def list_tools(namespace: str):
    label_selector = f"{LABEL_KAGENTI_TYPE}={VALUE_TYPE_TOOL}"

    # Query Deployments
    deployments = k8s.list_deployments(namespace, label_selector)

    # Future: Also query StatefulSets
    # statefulsets = k8s.list_statefulsets(namespace, label_selector)

    tools = []
    for deploy in deployments:
        tools.append({
            "name": deploy["metadata"]["name"],
            "namespace": deploy["metadata"]["namespace"],
            "status": _get_deployment_status(deploy),
            "labels": deploy["metadata"].get("labels", {}),
            "workloadType": "deployment",
            "createdAt": deploy["metadata"].get("creationTimestamp"),
        })

    return {"items": tools}
```

#### 2.5 Update Tool Get Endpoint

Return Deployment details with associated Service info:

```python
@router.get("/tools/{namespace}/{name}")
async def get_tool(namespace: str, name: str):
    deployment = k8s.get_deployment(namespace, name)
    service_name = f"{name}{TOOL_SERVICE_SUFFIX}"
    service = k8s.get_service(namespace, service_name)

    return {
        "metadata": deployment["metadata"],
        "spec": deployment["spec"],
        "status": _get_deployment_status(deployment),
        "service": service,
        "workloadType": "deployment",
    }
```

#### 2.6 Update Tool Delete Endpoint

Delete Deployment, Service, and associated resources:

```python
@router.delete("/tools/{namespace}/{name}")
async def delete_tool(namespace: str, name: str):
    deleted = []

    # Delete Deployment
    try:
        k8s.delete_deployment(namespace, name)
        deleted.append(f"Deployment/{name}")
    except NotFoundError:
        pass

    # Delete Service
    service_name = f"{name}{TOOL_SERVICE_SUFFIX}"
    try:
        k8s.delete_service(namespace, service_name)
        deleted.append(f"Service/{service_name}")
    except NotFoundError:
        pass

    # Delete HTTPRoute (unchanged)
    # Delete Shipwright Build/BuildRun (unchanged)

    return {"deleted": deleted}
```

#### 2.7 Update Shipwright Build Finalization

Modify `finalize_shipwright_build()` to create Deployment instead of MCPServer:

```python
@router.post("/tools/{namespace}/{name}/finalize-shipwright-build")
async def finalize_shipwright_build(namespace: str, name: str, request: FinalizeRequest):
    # ... get build info, validate success ...

    # Create Deployment instead of MCPServer CRD
    deployment_manifest = _build_tool_deployment_manifest(config, output_image)
    k8s.create_deployment(namespace, deployment_manifest)

    # Create Service
    service_manifest = _build_tool_service_manifest(config)
    k8s.create_service(namespace, service_manifest)

    # Create HTTPRoute if requested
    # ...
```

---

### Phase 3: StatefulSet Support

**Goal:** Add support for MCP tools that require persistent storage.

#### 3.1 Use Cases for StatefulSet

- Tools requiring persistent cache (large model files)
- Tools maintaining state across restarts
- Tools requiring stable network identities

#### 3.2 StatefulSet Manifest Structure

```yaml
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: <tool-name>
  namespace: <namespace>
  labels:
    kagenti.io/type: tool
    kagenti.io/protocol: mcp
    kagenti.io/transport: streamable_http
    kagenti.io/framework: <framework>
    kagenti.io/workload-type: statefulset
    app.kubernetes.io/name: <tool-name>
    app.kubernetes.io/managed-by: kagenti-ui
spec:
  serviceName: <tool-name>-mcp
  replicas: 1
  selector:
    matchLabels:
      kagenti.io/type: tool
      app.kubernetes.io/name: <tool-name>
  template:
    metadata:
      labels:
        kagenti.io/type: tool
        kagenti.io/protocol: mcp
        kagenti.io/transport: streamable_http
        kagenti.io/framework: <framework>
        app.kubernetes.io/name: <tool-name>
    spec:
      serviceAccountName: <tool-name>
      securityContext:
        runAsNonRoot: true
        seccompProfile:
          type: RuntimeDefault
      containers:
        - name: mcp
          image: <image>
          imagePullPolicy: Always
          env:
            # ... same as Deployment
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
            - name: data
              mountPath: /data
            - name: cache
              mountPath: /app/.cache
  volumeClaimTemplates:
    - metadata:
        name: data
      spec:
        accessModes: ["ReadWriteOnce"]
        resources:
          requests:
            storage: 1Gi
```

#### 3.3 Update Tool List to Include StatefulSets

```python
@router.get("/tools")
async def list_tools(namespace: str):
    label_selector = f"{LABEL_KAGENTI_TYPE}={VALUE_TYPE_TOOL}"

    tools = []

    # Query Deployments
    deployments = k8s.list_deployments(namespace, label_selector)
    for deploy in deployments:
        tools.append({
            "name": deploy["metadata"]["name"],
            "workloadType": "deployment",
            "status": _get_deployment_status(deploy),
            # ... other fields
        })

    # Query StatefulSets
    statefulsets = k8s.list_statefulsets(namespace, label_selector)
    for sts in statefulsets:
        tools.append({
            "name": sts["metadata"]["name"],
            "workloadType": "statefulset",
            "status": _get_statefulset_status(sts),
            # ... other fields
        })

    return {"items": tools}
```

#### 3.4 Update Tool Get to Handle StatefulSets

```python
@router.get("/tools/{namespace}/{name}")
async def get_tool(namespace: str, name: str):
    # Try Deployment first
    try:
        deployment = k8s.get_deployment(namespace, name)
        service = k8s.get_service(namespace, f"{name}{TOOL_SERVICE_SUFFIX}")
        return {
            "metadata": deployment["metadata"],
            "spec": deployment["spec"],
            "status": _get_deployment_status(deployment),
            "service": service,
            "workloadType": "deployment",
        }
    except NotFoundError:
        pass

    # Try StatefulSet
    try:
        statefulset = k8s.get_statefulset(namespace, name)
        service = k8s.get_service(namespace, f"{name}{TOOL_SERVICE_SUFFIX}")
        return {
            "metadata": statefulset["metadata"],
            "spec": statefulset["spec"],
            "status": _get_statefulset_status(statefulset),
            "service": service,
            "workloadType": "statefulset",
        }
    except NotFoundError:
        raise HTTPException(404, f"Tool {name} not found in namespace {namespace}")
```

#### 3.5 Update Delete to Handle StatefulSets

```python
@router.delete("/tools/{namespace}/{name}")
async def delete_tool(namespace: str, name: str):
    deleted = []

    # Try Deployment
    try:
        k8s.delete_deployment(namespace, name)
        deleted.append(f"Deployment/{name}")
    except NotFoundError:
        pass

    # Try StatefulSet
    try:
        k8s.delete_statefulset(namespace, name)
        deleted.append(f"StatefulSet/{name}")
    except NotFoundError:
        pass

    # Delete Service
    service_name = f"{name}{TOOL_SERVICE_SUFFIX}"
    try:
        k8s.delete_service(namespace, service_name)
        deleted.append(f"Service/{service_name}")
    except NotFoundError:
        pass

    # Delete PVCs for StatefulSet (optional - may want to preserve data)
    # ...

    return {"deleted": deleted}
```

---

### Phase 4: Frontend Updates

**Goal:** Update frontend to work with new Deployment/StatefulSet-based tools.

#### 4.1 Update Type Definitions

**File:** `kagenti/ui-v2/src/types/index.ts`

```typescript
// Workload types for tools
export type ToolWorkloadType = 'deployment' | 'statefulset';

export interface Tool {
  name: string;
  namespace: string;
  description?: string;
  status: 'Ready' | 'Not Ready' | 'Progressing' | 'Failed';
  labels: {
    protocol?: string;
    framework?: string;
    type?: string;
    transport?: string;
  };
  workloadType: ToolWorkloadType;
  createdAt?: string;
}

export interface ToolDetail {
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
  status: WorkloadStatus;
  service?: ServiceInfo;
  workloadType: ToolWorkloadType;
}

export interface WorkloadStatus {
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

export interface CreateToolRequest {
  // ... existing fields ...
  workloadType?: ToolWorkloadType;  // default: 'deployment'
  persistentStorage?: {
    enabled: boolean;
    size: string;  // e.g., "1Gi"
  };
}
```

#### 4.2 Update Tool Catalog Page

**File:** `kagenti/ui-v2/src/pages/ToolCatalogPage.tsx`

- Add workload type indicator (icon or badge)
- Update status logic for Deployment/StatefulSet conditions
- No major UI changes needed

#### 4.3 Update Tool Detail Page

**File:** `kagenti/ui-v2/src/pages/ToolDetailPage.tsx`

- Update status tab to show Deployment/StatefulSet conditions
- Show replica count and availability
- Show Service information (ClusterIP, ports)
- Update YAML tab to show Deployment/StatefulSet YAML
- MCP tool discovery/invocation remains largely unchanged

#### 4.4 Update Import Tool Page

**File:** `kagenti/ui-v2/src/pages/ImportToolPage.tsx`

Add workload type selector:

```typescript
<FormGroup label="Workload Type" fieldId="workload-type">
  <FormSelect
    value={workloadType}
    onChange={(_, value) => setWorkloadType(value as ToolWorkloadType)}
  >
    <FormSelectOption value="deployment" label="Deployment (Recommended)" />
    <FormSelectOption value="statefulset" label="StatefulSet (Persistent Storage)" />
  </FormSelect>
  <FormHelperText>
    Use StatefulSet for tools requiring persistent storage.
  </FormHelperText>
</FormGroup>

{workloadType === 'statefulset' && (
  <FormGroup label="Storage Size" fieldId="storage-size">
    <TextInput
      id="storage-size"
      value={storageSize}
      onChange={(_, value) => setStorageSize(value)}
      placeholder="1Gi"
    />
    <FormHelperText>
      Size of persistent volume for tool data.
    </FormHelperText>
  </FormGroup>
)}
```

---

### Phase 5: Migration Tooling

**Goal:** Provide tools to migrate existing MCPServer CRD resources to Deployments/StatefulSets.

#### 5.1 CLI Migration Script

**File:** `kagenti/tools/migrate_tools.py`

```bash
# List tools that can be migrated (dry-run by default)
python -m kagenti.tools.migrate_tools --namespace <namespace>

# Dry-run migration
python -m kagenti.tools.migrate_tools --namespace team1 --dry-run

# Actually perform the migration
python -m kagenti.tools.migrate_tools --namespace team1 --no-dry-run

# Migrate and delete old MCPServer CRDs
python -m kagenti.tools.migrate_tools --namespace team1 --no-dry-run --delete-old

# Migrate a specific tool only
python -m kagenti.tools.migrate_tools --namespace team1 --tool my-tool --no-dry-run

# Output results as JSON
python -m kagenti.tools.migrate_tools --namespace team1 --json
```

#### 5.2 Migration Logic

1. **List MCPServer CRDs**: Query all MCPServer CRDs in the specified namespace with `kagenti.io/type=tool` label
2. **Check for existing Deployments**: Skip tools that already have a Deployment/StatefulSet with the same name
3. **Build Deployment manifest**: Extract configuration from MCPServer CRD and build Deployment spec
4. **Build Service manifest**: Create Service with new naming convention (`{name}-mcp`)
5. **Create resources**: Apply Deployment and Service to cluster
6. **Update MCP connection URLs**: If using internal URLs, update to new Service name
7. **Cleanup (optional)**: Delete the original MCPServer CRD if `--delete-old` is specified

#### 5.3 Migration Annotations

Migrated Deployments include tracking annotations:

```yaml
annotations:
  kagenti.io/migrated-from: "mcpserver-crd"
  kagenti.io/migration-timestamp: "2026-01-26T10:30:00+00:00"
  kagenti.io/original-service: "mcp-{name}-proxy"  # for reference
```

#### 5.4 Backend Migration Endpoints

**File:** `kagenti/backend/app/routers/tools.py`

##### List Migratable Tools

```http
GET /tools/migration/migratable?namespace=team1
```

Returns a list of MCPServer CRDs that can be migrated.

##### Migrate Single Tool

```http
POST /tools/{namespace}/{name}/migrate
Content-Type: application/json

{
  "workload_type": "deployment",
  "delete_old": false
}
```

##### Batch Migration

```http
POST /tools/migration/migrate-all?namespace=team1&dry_run=true&delete_old=false
```

#### 5.5 Backward Compatibility Period

**File:** `kagenti/backend/app/core/config.py`

```python
# config.py
enable_legacy_mcpserver_crd: bool = True  # Set to False after full migration
```

When enabled, the `list_tools` endpoint will:

1. Query Deployments/StatefulSets with `kagenti.io/type=tool` label
2. Query MCPServer CRDs in the namespace
3. Skip MCPServer CRDs that already have a corresponding Deployment (already migrated)
4. Return a combined list of both Deployment-based and CRD-based tools

---

### Phase 6: CI/E2E Test Updates

**Goal:** Update CI workflows and E2E tests to deploy tools using Deployments instead of MCPServer CRDs.

#### 6.1 Files Requiring Updates

The following files in `.github/` reference MCPServer or Toolhive and need updates:

| File | Current Purpose | Required Changes |
|------|-----------------|------------------|
| `.github/workflows/e2e-kind.yaml` | E2E workflow | Remove Toolhive CRD wait step, update tool deployment step |
| `.github/scripts/kagenti-operator/43-wait-toolhive-crds.sh` | Wait for Toolhive CRDs | Remove or make conditional |
| `.github/scripts/kagenti-operator/72-deploy-weather-tool.sh` | Deploy tool via MCPServer | Replace with Deployment+Service |
| `.github/scripts/kagenti-operator/73-patch-weather-tool.sh` | Patch Toolhive-created resources | Simplify or remove (volumes in manifest) |
| `.github/scripts/kagenti-operator/75-deploy-weather-tool-shipwright.sh` | Shipwright build + MCPServer | Update to create Deployment instead of MCPServer |
| `.github/scripts/lib/k8s-utils.sh` | K8s utility functions | Add `wait_for_tool_deployment` function |
| `kagenti/examples/mcpservers/weather_tool.yaml` | Example MCPServer manifest | Replace with Deployment+Service manifests |

Python E2E test files:

| File | Current Purpose | Required Changes |
|------|-----------------|------------------|
| `kagenti/tests/e2e/common/test_shipwright_tool_build.py` | Shipwright build tests | Update CRD references, add Deployment verification |
| `kagenti/tests/e2e/conftest.py` | Test fixtures | Update `toolhiveCRDs`/`toolhiveOperator` feature flags |

#### 6.2 Update Workflow: e2e-kind.yaml

**File:** `.github/workflows/e2e-kind.yaml`

##### Remove Toolhive CRD Wait Step

```yaml
# REMOVE this step (or make conditional for legacy mode)
- name: Wait for Toolhive CRDs to be established
  run: bash .github/scripts/kagenti-operator/43-wait-toolhive-crds.sh
```

##### Update Tool Deployment Step

```yaml
# CHANGE from:
- name: Deploy weather-tool via Toolhive MCPServer
  run: bash .github/scripts/kagenti-operator/72-deploy-weather-tool.sh

# TO:
- name: Deploy weather-tool via Deployment
  run: bash .github/scripts/kagenti-operator/72-deploy-weather-tool.sh
```

##### Simplify or Remove Patch Step

```yaml
# REMOVE this step (volumes now in manifest directly)
- name: Patch weather-tool StatefulSet for writable /tmp
  run: bash .github/scripts/kagenti-operator/73-patch-weather-tool.sh
```

#### 6.3 New Tool Deployment Script

**File:** `.github/scripts/kagenti-operator/72-deploy-weather-tool.sh`

Replace MCPServer deployment with Deployment + Service:

```bash
#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../lib/env-detect.sh"
source "$SCRIPT_DIR/../lib/logging.sh"
source "$SCRIPT_DIR/../lib/k8s-utils.sh"

log_step "72" "Deploying weather-tool via Deployment"

# Create Deployment
cat <<EOF | kubectl apply -f -
apiVersion: apps/v1
kind: Deployment
metadata:
  name: weather-tool
  namespace: team1
  labels:
    kagenti.io/type: tool
    kagenti.io/protocol: mcp
    kagenti.io/transport: streamable_http
    kagenti.io/framework: Python
    app.kubernetes.io/name: weather-tool
    app.kubernetes.io/managed-by: e2e-test
  annotations:
    description: "Weather MCP tool for E2E testing"
spec:
  replicas: 1
  selector:
    matchLabels:
      kagenti.io/type: tool
      app.kubernetes.io/name: weather-tool
  template:
    metadata:
      labels:
        kagenti.io/type: tool
        kagenti.io/protocol: mcp
        kagenti.io/transport: streamable_http
        kagenti.io/framework: Python
        app.kubernetes.io/name: weather-tool
    spec:
      serviceAccountName: weather-tool
      securityContext:
        runAsNonRoot: true
        seccompProfile:
          type: RuntimeDefault
      containers:
        - name: mcp
          image: registry.cr-system.svc.cluster.local:5000/weather-tool:v0.0.1
          imagePullPolicy: Always
          env:
            - name: PORT
              value: "8000"
            - name: HOST
              value: "0.0.0.0"
            - name: OTEL_EXPORTER_OTLP_ENDPOINT
              value: "http://otel-collector.kagenti-system.svc.cluster.local:8335"
            - name: KEYCLOAK_URL
              value: "http://keycloak.keycloak.svc.cluster.local:8080"
            - name: UV_NO_CACHE
              value: "1"
            - name: LLM_API_BASE
              value: "http://dockerhost:11434/v1"
            - name: LLM_API_KEY
              value: "dummy"
            - name: LLM_MODEL
              value: "qwen2.5:0.5b"
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
            - name: tmp
              mountPath: /tmp
      volumes:
        - name: cache
          emptyDir: {}
        - name: tmp
          emptyDir: {}
EOF

# Create Service
cat <<EOF | kubectl apply -f -
apiVersion: v1
kind: Service
metadata:
  name: weather-tool-mcp
  namespace: team1
  labels:
    kagenti.io/type: tool
    kagenti.io/protocol: mcp
    app.kubernetes.io/name: weather-tool
    app.kubernetes.io/managed-by: e2e-test
spec:
  type: ClusterIP
  selector:
    kagenti.io/type: tool
    app.kubernetes.io/name: weather-tool
  ports:
    - name: http
      port: 8000
      targetPort: 8000
      protocol: TCP
EOF

# Wait for deployment to be available
wait_for_deployment "weather-tool" "team1" 300 || {
    log_error "Weather-tool deployment not ready"
    kubectl get deployment weather-tool -n team1
    kubectl describe deployment weather-tool -n team1
    kubectl get pods -n team1 -l app.kubernetes.io/name=weather-tool
    exit 1
}

log_success "Weather-tool deployed successfully"
```

#### 6.4 Update Example Manifests

**File:** `kagenti/examples/mcpservers/weather_tool.yaml`

Rename to `kagenti/examples/tools/weather_tool.yaml` and update content:

```yaml
# Deployment for weather-tool
apiVersion: apps/v1
kind: Deployment
metadata:
  name: weather-tool
  namespace: team1
  labels:
    kagenti.io/type: tool
    kagenti.io/protocol: mcp
    kagenti.io/transport: streamable_http
    kagenti.io/framework: Python
    app.kubernetes.io/name: weather-tool
    app.kubernetes.io/managed-by: example
  annotations:
    description: "Weather MCP tool for E2E testing"
spec:
  replicas: 1
  selector:
    matchLabels:
      kagenti.io/type: tool
      app.kubernetes.io/name: weather-tool
  template:
    metadata:
      labels:
        kagenti.io/type: tool
        kagenti.io/protocol: mcp
        kagenti.io/transport: streamable_http
        kagenti.io/framework: Python
        app.kubernetes.io/name: weather-tool
    spec:
      containers:
        - name: mcp
          image: registry.cr-system.svc.cluster.local:5000/weather-tool:v0.0.1
          # ... (same as above)
---
# Service for weather-tool
apiVersion: v1
kind: Service
metadata:
  name: weather-tool-mcp
  namespace: team1
  labels:
    kagenti.io/type: tool
    kagenti.io/protocol: mcp
    app.kubernetes.io/name: weather-tool
spec:
  type: ClusterIP
  selector:
    kagenti.io/type: tool
    app.kubernetes.io/name: weather-tool
  ports:
    - name: http
      port: 8000
      targetPort: 8000
      protocol: TCP
```

#### 6.5 Update Python E2E Tests

**File:** `kagenti/tests/e2e/common/test_shipwright_tool_build.py`

##### Update CRD Constants

```python
# REMOVE these constants:
# TOOLHIVE_GROUP = "toolhive.stacklok.dev"
# TOOLHIVE_VERSION = "v1alpha1"
# TOOLHIVE_MCP_PLURAL = "mcpservers"

# ADD these for verification:
APPS_GROUP = "apps"
APPS_VERSION = "v1"
DEPLOYMENTS_PLURAL = "deployments"
```

##### Update Test to Verify Deployment Creation

```python
class TestToolShipwrightBuildIntegration:
    """Integration tests for tool Shipwright build workflow."""

    def test_create_tool_build_and_deployment(
        self, k8s_custom_client, k8s_apps_client, shipwright_available, cleanup_tool_build
    ):
        """Test creating a Shipwright Build and verifying Deployment creation."""
        if not shipwright_available:
            pytest.skip("Shipwright not available")

        # Create Build manifest... (unchanged)

        # After build succeeds, verify Deployment is created (not MCPServer)
        # This would be done by the finalize endpoint in a real scenario
        deployment = k8s_apps_client.read_namespaced_deployment(
            name=TEST_TOOL_BUILD_NAME,
            namespace=TEST_NAMESPACE
        )

        # Verify required labels
        labels = deployment.metadata.labels
        assert labels.get("kagenti.io/type") == "tool"
        assert labels.get("kagenti.io/protocol") == "mcp"
        assert labels.get("app.kubernetes.io/name") == TEST_TOOL_BUILD_NAME
```

##### Add Deployment Client Fixture

```python
@pytest.fixture(scope="session")
def k8s_apps_client():
    """
    Load Kubernetes configuration and return AppsV1Api client.
    """
    try:
        from kubernetes import config as k8s_config
        k8s_config.load_kube_config()
    except Exception:
        try:
            from kubernetes import config as k8s_config
            k8s_config.load_incluster_config()
        except Exception as e:
            pytest.skip(f"Could not load Kubernetes config: {e}")

    return client.AppsV1Api()
```

#### 6.6 Update Test Configuration Fixtures

**File:** `kagenti/tests/e2e/conftest.py`

Update feature flag handling to reflect the migration:

```python
# In top_level_features list, consider deprecating:
top_level_features = [
    "gatewayApi",
    "certManager",
    "tekton",
    "kiali",
    # Deprecated - tools now use Deployments directly
    # "toolhiveCRDs",
    # "toolhiveOperator",
]

# Add new feature flag for migration period:
top_level_features = [
    "gatewayApi",
    "certManager",
    "tekton",
    "kiali",
    "useDeploymentForTools",  # NEW: indicates tools use Deployments
]
```

#### 6.7 Update k8s-utils.sh

**File:** `.github/scripts/lib/k8s-utils.sh`

Add utility function for waiting on tool deployments:

```bash
# Wait for tool deployment to be available
wait_for_tool_deployment() {
    local tool_name="$1"
    local namespace="$2"
    local timeout="${3:-300}"

    kubectl wait --for=condition=available --timeout="${timeout}s" \
        "deployment/$tool_name" -n "$namespace" || {
        echo "ERROR: Tool deployment $tool_name not ready in $namespace"
        kubectl describe "deployment/$tool_name" -n "$namespace"
        kubectl get pods -n "$namespace" -l "app.kubernetes.io/name=$tool_name"
        kubectl logs -n "$namespace" -l "app.kubernetes.io/name=$tool_name" --tail=50 || true
        return 1
    }
}

# Wait for tool service to exist
wait_for_tool_service() {
    local tool_name="$1"
    local namespace="$2"
    local timeout="${3:-60}"
    local service_name="${tool_name}-mcp"

    local elapsed=0
    while [ $elapsed -lt $timeout ]; do
        if kubectl get service "$service_name" -n "$namespace" &> /dev/null; then
            return 0
        fi
        sleep 2
        elapsed=$((elapsed + 2))
    done

    echo "ERROR: Service $service_name not found in $namespace after ${timeout}s"
    return 1
}
```

#### 6.8 Update Shipwright Build Script

**File:** `.github/scripts/kagenti-operator/75-deploy-weather-tool-shipwright.sh`

Replace MCPServer creation (Step 5) with Deployment + Service:

```bash
# Step 5: Create Deployment for the tool (replaces MCPServer)
echo ""
echo "Step 5: Creating Deployment resource..."
cat <<EOF | kubectl apply -f -
apiVersion: apps/v1
kind: Deployment
metadata:
  name: ${TOOL_NAME}
  namespace: ${NAMESPACE}
  labels:
    kagenti.io/type: tool
    kagenti.io/protocol: mcp
    kagenti.io/transport: streamable_http
    kagenti.io/built-by: shipwright
    kagenti.io/build-name: ${TOOL_NAME}
    app.kubernetes.io/name: ${TOOL_NAME}
spec:
  replicas: 1
  selector:
    matchLabels:
      kagenti.io/type: tool
      app.kubernetes.io/name: ${TOOL_NAME}
  template:
    metadata:
      labels:
        kagenti.io/type: tool
        kagenti.io/protocol: mcp
        kagenti.io/transport: streamable_http
        app.kubernetes.io/name: ${TOOL_NAME}
    spec:
      containers:
        - name: mcp
          image: ${OUTPUT_IMAGE}
          ports:
            - containerPort: 8000
          resources:
            limits:
              cpu: "500m"
              memory: "512Mi"
            requests:
              cpu: "100m"
              memory: "128Mi"
          volumeMounts:
            - name: tmp
              mountPath: /tmp
      volumes:
        - name: tmp
          emptyDir: {}
EOF

# Step 5b: Create Service
echo "Creating Service..."
cat <<EOF | kubectl apply -f -
apiVersion: v1
kind: Service
metadata:
  name: ${TOOL_NAME}-mcp
  namespace: ${NAMESPACE}
  labels:
    kagenti.io/type: tool
    kagenti.io/protocol: mcp
    app.kubernetes.io/name: ${TOOL_NAME}
spec:
  type: ClusterIP
  selector:
    kagenti.io/type: tool
    app.kubernetes.io/name: ${TOOL_NAME}
  ports:
    - name: http
      port: 8000
      targetPort: 8000
EOF

echo "Deployment '${TOOL_NAME}' and Service '${TOOL_NAME}-mcp' created."

# Step 6: Wait for Deployment to be ready (replaces MCPServer wait)
echo ""
echo "Step 6: Waiting for Deployment to be ready..."
kubectl wait --for=condition=available deployment/${TOOL_NAME} -n ${NAMESPACE} --timeout=120s || {
    echo "Warning: Deployment not ready within timeout, checking status..."
    kubectl get deployment ${TOOL_NAME} -n ${NAMESPACE} -o yaml
}

echo ""
echo "=== Weather Tool Deployment Complete ==="
echo "Tool Name: ${TOOL_NAME}"
echo "Namespace: ${NAMESPACE}"
echo "Image: ${OUTPUT_IMAGE}"
echo "Service: ${TOOL_NAME}-mcp"
echo ""
echo "To verify the tool is running:"
echo "  kubectl get deployment ${TOOL_NAME} -n ${NAMESPACE}"
echo "  kubectl get service ${TOOL_NAME}-mcp -n ${NAMESPACE}"
echo "  kubectl get pods -l app.kubernetes.io/name=${TOOL_NAME} -n ${NAMESPACE}"
```

#### 6.9 Cleanup: Remove/Archive Obsolete Scripts

After migration is complete, the following scripts can be removed or archived:

| Script | Action |
|--------|--------|
| `.github/scripts/kagenti-operator/43-wait-toolhive-crds.sh` | Remove |
| `.github/scripts/kagenti-operator/73-patch-weather-tool.sh` | Remove (volumes in manifest) |
| `kagenti/examples/mcpservers/` | Move to `kagenti/examples/legacy/mcpservers/` |

#### 6.10 MCP Connection URL Update in Tests

Update any E2E tests that connect to MCP tools to use the new service naming:

```python
# OLD: mcp-{name}-proxy.{namespace}.svc.cluster.local:8000/mcp
# NEW: {name}-mcp.{namespace}.svc.cluster.local:8000/mcp

def get_mcp_url(tool_name: str, namespace: str) -> str:
    """Get MCP endpoint URL for a tool."""
    return f"http://{tool_name}-mcp.{namespace}.svc.cluster.local:8000/mcp"
```

---

## 5. API Changes

### New/Modified Endpoints

| Endpoint | Change | Phase |
|----------|--------|-------|
| `POST /tools` | Add `workloadType` param, create Deployment/StatefulSet+Service | 2-3 |
| `GET /tools` | Query Deployments/StatefulSets instead of MCPServer CRD | 2 |
| `GET /tools/{ns}/{name}` | Return Deployment/StatefulSet details | 2 |
| `DELETE /tools/{ns}/{name}` | Delete Deployment/StatefulSet+Service | 2 |
| `POST /tools/{ns}/{name}/finalize-shipwright-build` | Create Deployment/StatefulSet instead of MCPServer | 2 |
| `POST /tools/{ns}/{name}/migrate` | New: Migrate MCPServer CRD to Deployment | 5 |
| `GET /tools/migration/migratable` | New: List migratable MCPServer CRDs | 5 |

### Request/Response Schema Changes

**CreateToolRequest:**
```json
{
  "name": "my-tool",
  "namespace": "team1",
  "workloadType": "deployment",  // NEW: default "deployment"
  "persistentStorage": {         // NEW: for StatefulSet
    "enabled": false,
    "size": "1Gi"
  }
  // ... other fields unchanged
}
```

**Tool (list response):**
```json
{
  "name": "my-tool",
  "namespace": "team1",
  "status": "Ready",
  "workloadType": "deployment",  // NEW
  "labels": {...}
}
```

**ToolDetail (get response):**
```json
{
  "metadata": {...},
  "spec": {...},  // Deployment/StatefulSet spec instead of MCPServer spec
  "status": {...},  // Deployment/StatefulSet status
  "service": {...},  // NEW: Service info
  "workloadType": "deployment"  // NEW
}
```

---

## 6. MCP Connection Updates

### Service Name Change

The MCP connection URL changes due to new Service naming:

| Old (Toolhive) | New (Direct) |
|----------------|--------------|
| `mcp-{name}-proxy` | `{name}-mcp` |
| `http://mcp-{name}-proxy.{ns}.svc.cluster.local:8000/mcp` | `http://{name}-mcp.{ns}.svc.cluster.local:8000/mcp` |

### Update MCP Connection Logic

**File:** `kagenti/backend/app/routers/tools.py`

```python
def _get_mcp_service_url(namespace: str, name: str) -> str:
    """Get the in-cluster MCP service URL for a tool."""
    service_name = f"{name}{TOOL_SERVICE_SUFFIX}"  # {name}-mcp
    return f"http://{service_name}.{namespace}.svc.cluster.local:8000/mcp"


@router.post("/tools/{namespace}/{name}/connect")
async def connect_to_tool(namespace: str, name: str):
    url = _get_mcp_service_url(namespace, name)
    async with streamablehttp_client(url) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            return {"tools": [tool.model_dump() for tool in tools.tools]}
```

### Backward Compatibility for Connection

During migration, the connect endpoint should try both URLs:

```python
@router.post("/tools/{namespace}/{name}/connect")
async def connect_to_tool(namespace: str, name: str):
    # Try new URL first
    new_url = _get_mcp_service_url(namespace, name)  # {name}-mcp
    old_url = f"http://mcp-{name}-proxy.{namespace}.svc.cluster.local:8000/mcp"

    for url in [new_url, old_url]:
        try:
            async with streamablehttp_client(url) as (read, write, _):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    tools = await session.list_tools()
                    return {"tools": [tool.model_dump() for tool in tools.tools]}
        except Exception:
            continue

    raise HTTPException(503, f"Cannot connect to MCP tool {name}")
```

---

## 7. RBAC Requirements

### New Permissions Required

The Kagenti backend ServiceAccount needs additional permissions (many shared with agent migration):

```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: kagenti-backend
rules:
  # Existing permissions for MCPServer CRD...

  # Deployments (may already exist from agent migration)
  - apiGroups: ["apps"]
    resources: ["deployments"]
    verbs: ["get", "list", "create", "update", "patch", "delete"]

  # Services (may already exist from agent migration)
  - apiGroups: [""]
    resources: ["services"]
    verbs: ["get", "list", "create", "delete"]

  # Pods (for status/logs)
  - apiGroups: [""]
    resources: ["pods", "pods/log"]
    verbs: ["get", "list"]

  # StatefulSets
  - apiGroups: ["apps"]
    resources: ["statefulsets"]
    verbs: ["get", "list", "create", "update", "patch", "delete"]

  # PersistentVolumeClaims (for StatefulSet cleanup)
  - apiGroups: [""]
    resources: ["persistentvolumeclaims"]
    verbs: ["get", "list", "delete"]
```

### Helm Chart Updates

**File:** `charts/kagenti/templates/ui.yaml`

Update the RBAC rules for the kagenti-backend ServiceAccount.

---

## 8. Testing Strategy

### Unit Tests

- Test manifest builders produce valid YAML with correct labels
- Test label selectors return correct resources
- Test status mapping logic for both Deployment and StatefulSet
- Test MCP URL generation

### Integration Tests

- Create tool via API, verify Deployment + Service created
- Create tool with StatefulSet, verify StatefulSet + Service + PVC
- Delete tool, verify cleanup (including PVCs if applicable)
- Build tool from source, verify finalization creates Deployment
- Test MCP connection with new Service naming
- Test migration endpoint

### E2E Tests

**File:** `kagenti/tests/e2e/`

- Full workflow: Import tool → Build → Deploy → Connect → Invoke → Delete
- Migration: Create MCPServer CRD → Migrate → Verify Deployment → Verify MCP connection

### Manual Testing Checklist

- [ ] Import tool from image (Deployment created)
- [ ] Import tool from image with StatefulSet option (StatefulSet created)
- [ ] Import tool from source (Build → Deployment)
- [ ] Tool appears in catalog with correct status
- [ ] Tool detail page shows Deployment/StatefulSet info
- [ ] MCP tools discovery works (connect & list tools)
- [ ] MCP tool invocation works
- [ ] Delete tool cleans up all resources (including PVCs for StatefulSet)
- [ ] HTTPRoute works correctly
- [ ] Migrate existing MCPServer CRD to Deployment
- [ ] MCP connection works after migration

---

## 9. Rollback Plan

### Feature Flag

Add feature flag to switch between MCPServer CRD and Deployment modes:

**File:** `kagenti/backend/app/core/config.py`

```python
USE_DEPLOYMENT_FOR_TOOLS = os.getenv("USE_DEPLOYMENT_FOR_TOOLS", "true").lower() == "true"
```

### Rollback Steps

1. Set `USE_DEPLOYMENT_FOR_TOOLS=false`
2. Restart backend
3. New tools will use MCPServer CRD
4. Existing Deployment-based tools continue to work (MCP connection tries both URLs)
5. Run reverse migration if needed

### Data Preservation

- Deployments/StatefulSets can be converted back to MCPServer CRD if needed
- All configuration stored in Deployment spec/annotations
- Shipwright Build resources unchanged
- PVCs for StatefulSets preserved unless explicitly deleted

---

## Implementation Timeline

| Phase | Description | Dependencies |
|-------|-------------|--------------|
| 1 | Backend Infrastructure | None |
| 2 | Deployment Support | Phase 1 |
| 3 | StatefulSet Support | Phase 2 |
| 4 | Frontend Updates | Phase 2-3 |
| 5 | Migration Tooling | Phase 2-4 |
| 6 | CI/E2E Test Updates | Phase 2 |

**Notes:**
- Phase 3 (StatefulSet) can be implemented in parallel with Phase 4 (Frontend) after Phase 2 is complete.
- Phase 6 (CI/E2E) can be started as soon as Phase 2 is complete, and should be updated alongside backend changes to ensure CI passes.

---

## Open Questions

1. **Should we preserve the old Service name (`mcp-{name}-proxy`) or use new naming (`{name}-mcp`)?**
   - Recommendation: Use new naming for clarity, with backward compatibility during migration

2. **How to handle PVC cleanup for StatefulSets?**
   - Option A: Delete PVCs automatically (data loss)
   - Option B: Keep PVCs, require manual cleanup (safer)
   - Recommendation: Option B with UI warning

3. **Should migrated tools retain both old and new Services temporarily?**
   - Recommendation: No, clean break with URL fallback in connect endpoint

4. **What about tools with custom Toolhive operator features?**
   - Document any feature gaps
   - Most features map directly to Deployment spec

---

## References

- [Kubernetes Deployments](https://kubernetes.io/docs/concepts/workloads/controllers/deployment/)
- [Kubernetes StatefulSets](https://kubernetes.io/docs/concepts/workloads/controllers/statefulset/)
- [Kubernetes Services](https://kubernetes.io/docs/concepts/services-networking/service/)
- [Kubernetes Labels and Selectors](https://kubernetes.io/docs/concepts/overview/working-with-objects/labels/)
- [MCP Protocol](https://modelcontextprotocol.io/)
- [Agent Migration Plan](./migrate-agent-crd-to-workloads.md)
