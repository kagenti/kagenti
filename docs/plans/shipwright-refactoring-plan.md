# Shipwright Build Refactoring Plan

## Overview

This plan outlines the refactoring of the Kagenti UI to trigger container image builds via **Shipwright Build** (`build.shipwright.io`) instead of the current AgentBuild CRD + Tekton pipeline approach. The plan covers both **agents** and **MCP tools**.

### Current State
- **Agents**: UI creates `AgentBuild` CRD → Kagenti Operator triggers Tekton Pipeline
- **Agent CRD** references `AgentBuild` via `imageSource.buildRef`
- **Tools**: Only support deployment from existing container images (no build from source)

### Target State
- **UI** creates Shipwright `Build` + `BuildRun` CRDs directly for both agents and tools
- **Agent/Tool CRDs** are created with direct image reference after build completes
- UI polls BuildRun status and creates Agent/MCPServer when build succeeds
- User can select `ClusterBuildStrategy` in UI
- Shared build infrastructure for both resource types

### Phases Overview

| Phase | Stages | Description |
|-------|--------|-------------|
| **Phase 1: Agent Builds** | Stages 1-5 | ✅ Shipwright builds for agents (completed) |
| **Phase 2: Shared Infrastructure** | Stage 6 | ✅ Extract common build utilities (completed) |
| **Phase 3: Tool Builds** | Stages 7-9 | ✅ Add Shipwright builds for tools (completed) |

### Key Resources

| Resource | API Group | Purpose |
|----------|-----------|---------|
| Build | `shipwright.io/v1beta1` | Defines build configuration (source, strategy, output) |
| BuildRun | `shipwright.io/v1beta1` | Triggers and tracks a build execution |
| ClusterBuildStrategy | `shipwright.io/v1beta1` | Cluster-wide build strategy (e.g., `buildah`, `buildah-insecure-push`) |

### Available ClusterBuildStrategies

| Strategy | Use Case |
|----------|----------|
| `buildah-insecure-push` | Dev environment with internal registry (no TLS) |
| `buildah` | Production with external registries (quay.io, ghcr.io, docker.io) |

---

## Stage 1: Backend API Changes

**Objective**: Add Shipwright Build/BuildRun support to the backend without removing existing AgentBuild support.

### 1.1 Add Shipwright Constants

**File**: `kagenti/backend/app/core/constants.py`

Add new constants:
```python
# Shipwright CRD Definitions
SHIPWRIGHT_CRD_GROUP = "shipwright.io"
SHIPWRIGHT_CRD_VERSION = "v1beta1"
SHIPWRIGHT_BUILDS_PLURAL = "builds"
SHIPWRIGHT_BUILDRUNS_PLURAL = "buildruns"
SHIPWRIGHT_CLUSTER_BUILD_STRATEGIES_PLURAL = "clusterbuildstrategies"

# Shipwright defaults
DEFAULT_BUILD_STRATEGY_DEV = "buildah-insecure-push"
DEFAULT_BUILD_STRATEGY_PROD = "buildah"
SHIPWRIGHT_GIT_SECRET_NAME = "github-shipwright-secret"
DEFAULT_BUILD_TIMEOUT = "15m"
```

### 1.2 Add Shipwright Models

**File**: `kagenti/backend/app/routers/agents.py`

Add new Pydantic models:
```python
class ShipwrightBuildRequest(BaseModel):
    """Request fields for Shipwright build configuration."""
    buildStrategy: str = "buildah-insecure-push"  # ClusterBuildStrategy name
    dockerfile: str = "Dockerfile"
    buildArgs: Optional[List[str]] = None  # KEY=VALUE format
    buildTimeout: str = "15m"

class CreateAgentRequest(BaseModel):
    # ... existing fields ...

    # New: Shipwright build configuration
    useShipwright: bool = True  # Default to Shipwright for new builds
    shipwrightConfig: Optional[ShipwrightBuildRequest] = None
```

### 1.3 Add Shipwright Manifest Builders

**File**: `kagenti/backend/app/routers/agents.py`

Add new functions:

```python
def _build_shipwright_build_manifest(request: CreateAgentRequest) -> dict:
    """Build a Shipwright Build CRD manifest."""
    # Returns Build manifest with:
    # - source.git (url, revision, cloneSecret, contextDir)
    # - strategy (ClusterBuildStrategy reference)
    # - paramValues (dockerfile, build-args)
    # - output (image, pushSecret)
    # - timeout
    # - retention (succeededLimit, failedLimit)
    pass

def _build_shipwright_buildrun_manifest(build_name: str, namespace: str) -> dict:
    """Build a Shipwright BuildRun CRD manifest to trigger a build."""
    # Returns BuildRun manifest with:
    # - generateName: {build_name}-run-
    # - build.name reference
    pass
```

### 1.4 Add Shipwright API Endpoints

**File**: `kagenti/backend/app/routers/agents.py`

Add new endpoints:

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/agents/{namespace}/{name}/shipwright-build` | GET | Get Shipwright Build status |
| `/agents/{namespace}/{name}/shipwright-buildrun` | GET | Get BuildRun status |
| `/agents/{namespace}/{name}/shipwright-buildrun` | POST | Trigger new BuildRun |
| `/build-strategies` | GET | List available ClusterBuildStrategies |

### 1.5 Modify Agent Creation Flow

**File**: `kagenti/backend/app/routers/agents.py`

Modify `create_agent` function:

```python
async def create_agent(request: CreateAgentRequest, kube: KubernetesService):
    if request.deploymentMethod == "source":
        if request.useShipwright:
            # 1. Create Shipwright Build
            build_manifest = _build_shipwright_build_manifest(request)
            await kube.create_custom_resource(
                group=SHIPWRIGHT_CRD_GROUP,
                version=SHIPWRIGHT_CRD_VERSION,
                plural=SHIPWRIGHT_BUILDS_PLURAL,
                namespace=request.namespace,
                body=build_manifest
            )

            # 2. Create BuildRun to trigger build
            buildrun_manifest = _build_shipwright_buildrun_manifest(
                request.name, request.namespace
            )
            buildrun = await kube.create_custom_resource(
                group=SHIPWRIGHT_CRD_GROUP,
                version=SHIPWRIGHT_CRD_VERSION,
                plural=SHIPWRIGHT_BUILDRUNS_PLURAL,
                namespace=request.namespace,
                body=buildrun_manifest
            )

            # 3. Return response (Agent created later after build completes)
            return CreateAgentResponse(
                success=True,
                name=request.name,
                namespace=request.namespace,
                message=f"Shipwright build started. BuildRun: {buildrun['metadata']['name']}"
            )
        else:
            # Existing AgentBuild flow (for backward compatibility)
            ...
```

---

## Stage 2: Frontend UI Changes

**Objective**: Update the Import Agent page to support Shipwright configuration and build strategy selection.

### 2.1 Add Build Strategy State

**File**: `kagenti/ui-v2/src/pages/ImportAgentPage.tsx`

Add new state:
```typescript
// Build configuration
const [useShipwright, setUseShipwright] = useState(true);
const [buildStrategy, setBuildStrategy] = useState('buildah-insecure-push');
const [availableStrategies, setAvailableStrategies] = useState<string[]>([]);
const [dockerfile, setDockerfile] = useState('Dockerfile');
const [buildTimeout, setBuildTimeout] = useState('15m');
```

### 2.2 Add API Service Methods

**File**: `kagenti/ui-v2/src/services/api.ts`

Add new methods:
```typescript
export const buildService = {
  // List available ClusterBuildStrategies
  listStrategies: async (): Promise<string[]> => {
    const response = await apiClient.get('/build-strategies');
    return response.data;
  },

  // Get Shipwright build status
  getBuildStatus: async (namespace: string, name: string): Promise<BuildStatus> => {
    const response = await apiClient.get(`/agents/${namespace}/${name}/shipwright-build`);
    return response.data;
  },

  // Get BuildRun status
  getBuildRunStatus: async (namespace: string, name: string): Promise<BuildRunStatus> => {
    const response = await apiClient.get(`/agents/${namespace}/${name}/shipwright-buildrun`);
    return response.data;
  },

  // Trigger new BuildRun
  triggerBuildRun: async (namespace: string, name: string): Promise<void> => {
    await apiClient.post(`/agents/${namespace}/${name}/shipwright-buildrun`);
  },
};
```

### 2.3 Add Build Strategy Selector Component

**File**: `kagenti/ui-v2/src/components/BuildStrategySelector.tsx`

Create new component:
```typescript
interface BuildStrategySelectorProps {
  value: string;
  onChange: (strategy: string) => void;
  registryType: string;  // Auto-select based on registry
}

export const BuildStrategySelector: React.FC<BuildStrategySelectorProps> = ({
  value,
  onChange,
  registryType,
}) => {
  // Fetch available strategies
  // Auto-select appropriate strategy based on registry:
  // - local → buildah-insecure-push
  // - external (quay, ghcr, dockerhub) → buildah
  // Allow manual override
};
```

### 2.4 Update Import Agent Form

**File**: `kagenti/ui-v2/src/pages/ImportAgentPage.tsx`

Add new form sections:

1. **Build Configuration Section** (expandable):
   - Build Strategy dropdown (with auto-selection based on registry)
   - Dockerfile path input
   - Build timeout input
   - Build arguments (optional, expandable list)

2. **Strategy Descriptions** (helper text):
   - `buildah-insecure-push`: "For internal registries without TLS (dev/kind clusters)"
   - `buildah`: "For external registries with TLS (quay.io, ghcr.io, docker.io)"

### 2.5 Update Submit Handler

Modify the mutation to include Shipwright config:
```typescript
const mutation = useMutation({
  mutationFn: async (data: CreateAgentData) => {
    return agentService.create({
      ...data,
      useShipwright: true,
      shipwrightConfig: {
        buildStrategy: buildStrategy,
        dockerfile: dockerfile,
        buildTimeout: buildTimeout,
        buildArgs: buildArgs.filter(arg => arg.trim()),
      },
    });
  },
});
```

---

## Stage 3: Build Progress Page & Auto-Finalization

**Objective**: Implement a dedicated Build Progress page that tracks BuildRun status and automatically creates the Agent upon build completion.

### 3.1 Store Agent Config in Build Annotations

**Problem**: When using Shipwright, the Agent CRD is not created until the build completes. We need to preserve the user's agent configuration (protocol, framework, HTTPRoute, env vars, etc.) during the build.

**Solution**: Store agent configuration in the Shipwright Build's annotations.

**File**: `kagenti/backend/app/routers/agents.py`

In `_build_shipwright_build_manifest()`:
```python
# Build agent configuration to store in annotation
agent_config = {
    "protocol": request.protocol,
    "framework": request.framework,
    "createHttpRoute": request.createHttpRoute,
    "registrySecret": request.registrySecret,
}
if request.envVars:
    agent_config["envVars"] = [ev.model_dump(exclude_none=True) for ev in request.envVars]
if request.servicePorts:
    agent_config["servicePorts"] = [sp.model_dump() for sp in request.servicePorts]

# Add to Build manifest
manifest["metadata"]["annotations"] = {
    "kagenti.io/agent-config": json.dumps(agent_config),
}
```

### 3.2 Add Comprehensive Build Info Endpoint

**File**: `kagenti/backend/app/routers/agents.py`

```python
class ShipwrightBuildInfoResponse(BaseModel):
    """Combined Build and BuildRun status with agent config."""
    # Build info
    name: str
    namespace: str
    buildRegistered: bool
    outputImage: str
    strategy: str
    gitUrl: str
    gitRevision: str
    contextDir: str

    # Latest BuildRun info
    hasBuildRun: bool
    buildRunName: Optional[str] = None
    buildRunPhase: Optional[str] = None  # Pending, Running, Succeeded, Failed
    buildRunStartTime: Optional[str] = None
    buildRunCompletionTime: Optional[str] = None
    buildRunOutputImage: Optional[str] = None
    buildRunOutputDigest: Optional[str] = None
    buildRunFailureMessage: Optional[str] = None

    # Agent configuration from annotations
    agentConfig: Optional[AgentConfigFromBuild] = None

@router.get("/{namespace}/{name}/shipwright-build-info")
async def get_shipwright_build_info(...) -> ShipwrightBuildInfoResponse:
    """Get full Shipwright Build info including agent config and BuildRun status."""
```

### 3.3 Finalize Build Endpoint

**File**: `kagenti/backend/app/routers/agents.py`

```python
@router.post("/{namespace}/{name}/finalize-shipwright-build")
async def finalize_shipwright_build(
    namespace: str,
    name: str,
    request: FinalizeShipwrightBuildRequest,  # All fields optional
    kube: KubernetesService = Depends(get_kubernetes_service),
) -> CreateAgentResponse:
    """Create Agent CRD after Shipwright build completes successfully.

    Reads agent configuration from Build annotations if not provided in request.
    """
    # 1. Get latest BuildRun, verify success
    # 2. Extract output image from BuildRun status
    # 3. Read agent config from Build annotations
    # 4. Merge request with stored config (request takes precedence)
    # 5. Create Agent CRD with built image
    # 6. Create HTTPRoute if createHttpRoute is true
    # 7. Add kagenti.io/shipwright-build annotation to Agent
```

### 3.4 Build Progress Page

**File**: `kagenti/ui-v2/src/pages/BuildProgressPage.tsx`

A dedicated page at `/agents/:namespace/:name/build` that:
- Polls build info every 5 seconds using `shipwrightService.getBuildInfo()`
- Shows progress bar with phase (Pending → Running → Succeeded/Failed)
- Displays build details (strategy, duration, BuildRun name)
- Shows source configuration (Git URL, revision, context dir, output image)
- Shows agent configuration that will be applied (protocol, framework, HTTPRoute, etc.)
- **Auto-finalizes** when build succeeds (calls `finalizeBuild()`)
- Redirects to agent detail page after successful finalization
- Shows retry button on build failure

```typescript
// Auto-finalize when build succeeds
useEffect(() => {
  if (buildInfo?.buildRunPhase === 'Succeeded' && !isAutoFinalizing) {
    setIsAutoFinalizing(true);
    finalizeMutation.mutate();
  }
}, [buildInfo?.buildRunPhase]);
```

### 3.5 Smart Navigation Flow

**Files**:
- `kagenti/ui-v2/src/App.tsx` - Add route for `/agents/:namespace/:name/build`
- `kagenti/ui-v2/src/pages/ImportAgentPage.tsx` - Navigate to build page after submission
- `kagenti/ui-v2/src/pages/AgentDetailPage.tsx` - Redirect to build page if build exists but agent doesn't

**Import Flow**:
1. User submits form → Creates Build + BuildRun
2. Navigate to `/agents/{namespace}/{name}/build`
3. Build Progress page polls status
4. On success → Auto-finalize → Redirect to `/agents/{namespace}/{name}`

**Direct Navigation Handling**:
- If user navigates to `/agents/{namespace}/{name}` while build is in progress:
  - Check if Agent exists → If not, check for Shipwright Build
  - If Build exists → Redirect to `/agents/{namespace}/{name}/build`
  - If no Build → Show "Agent not found" error

### 3.6 Agent Detail Page - Shipwright Build Status

**File**: `kagenti/ui-v2/src/pages/AgentDetailPage.tsx`

For agents built with Shipwright (have `kagenti.io/shipwright-build` annotation):
- Fetch and display Shipwright Build status on the Status tab
- Show Build info (name, strategy, output image, Git source)
- Show latest BuildRun info (phase, duration, output image with digest)

---

## Stage 4: Cleanup and Migration

**Objective**: Deprecate AgentBuild, enforce Shipwright for new builds, and update documentation.

### 4.1 Feature Flag (Already Implemented)

**File**: `kagenti/backend/app/core/config.py`

```python
class Settings(BaseSettings):
    use_shipwright_builds: bool = True
    shipwright_default_strategy: str = "buildah-insecure-push"
    shipwright_default_timeout: str = "15m"
```

### 4.2 Backend Deprecation

**File**: `kagenti/backend/app/routers/agents.py`

**Implemented changes:**
1. Marked `get_agent_build_status` endpoint as deprecated using FastAPI's `deprecated=True`
2. Added warning log when deprecated endpoint is called
3. Added warning log when AgentBuild creation is attempted (useShipwright=False)
4. Added deprecation docstring to `_build_agent_build_manifest()` function
5. Updated `delete_agent` to also delete Shipwright Build and BuildRuns

```python
@router.get(
    "/{namespace}/{name}/build",
    response_model=BuildStatusResponse,
    deprecated=True,
    summary="Get AgentBuild status (deprecated)",
)
async def get_agent_build_status(...):
    """DEPRECATED: Use /shipwright-build-info endpoint instead."""
    logger.warning("Deprecated endpoint called: get_agent_build_status...")
```

### 4.3 UI Migration

**File**: `kagenti/ui-v2/src/pages/ImportAgentPage.tsx`

**Implemented changes:**
1. Removed "Use Shipwright" checkbox - Shipwright is now always used for source builds
2. Removed `useShipwright` state variable
3. Form submission always sets `useShipwright: true`
4. Kept backward compatibility for viewing existing AgentBuild status on Agent detail page

### 4.4 Documentation Updates

**Updated files:**

**`docs/components.md`:**
- Added "Container Build Systems" section comparing Shipwright vs AgentBuild
- Documented Shipwright build flow and ClusterBuildStrategies
- Added Shipwright Build YAML example
- Marked AgentBuild example as deprecated

**`docs/new-agent.md`:**
- Added "Step 5: Configure Build Options" for Shipwright settings
- Documented build strategy auto-selection based on registry type
- Documented advanced build options (Dockerfile, timeout, build args)
- Updated to describe Build Progress page flow
- Updated Troubleshooting section with Shipwright-specific commands

---

## Stage 5: Testing and Validation

### 5.1 Backend Unit Tests ✅

**File**: `kagenti/backend/tests/test_shipwright.py`

**Implemented 33 unit tests covering:**

1. **Build manifest generation (11 tests)**
   - Default values for build manifest
   - Build name and namespace
   - Git source configuration
   - Build strategy selection based on registry type
   - Custom build strategy override
   - Dockerfile path configuration
   - Build arguments
   - Build timeout
   - Output image configuration
   - Push secret inclusion
   - Agent config annotation storage

2. **BuildRun manifest generation (3 tests)**
   - Default BuildRun structure
   - Label propagation
   - Build name reference

3. **Build strategy selection logic (4 tests)**
   - Internal registry → `buildah-insecure-push`
   - External quay.io → `buildah`
   - External ghcr.io → `buildah`
   - Manual override respected

4. **Model validation (2 tests)**
   - ShipwrightBuildConfig default values
   - Custom configuration values

5. **BuildRun phase detection (6 tests)**
   - Pending state
   - Running state
   - Succeeded state
   - Failed state
   - Unknown state handling
   - Missing status handling

6. **Agent config parsing (4 tests)**
   - Parse config from annotations
   - Handle missing annotations
   - Handle empty annotations
   - Handle malformed JSON

7. **Response model (3 tests)**
   - Build info response structure
   - Response with BuildRun info
   - Response with agent config

### 5.2 Integration Tests ✅

**File**: `kagenti/tests/e2e/common/test_shipwright_build.py`

**Implemented tests covering:**

1. **Shipwright availability tests**
   - `test_shipwright_crds_installed` - Verify Shipwright CRDs present
   - `test_build_strategies_exist` - Verify expected ClusterBuildStrategies available

2. **Build lifecycle tests**
   - `test_create_build` - Verify Build CRD creation
   - `test_create_buildrun` - Verify BuildRun triggers build
   - `test_buildrun_status_progression` - Verify status updates

3. **Annotation tests**
   - `test_agent_config_in_annotations` - Verify agent config storage in Build annotations

**Test fixtures:**
- `k8s_custom_client` - CustomObjectsApi for CRD operations
- `shipwright_available` - Check if Shipwright is installed
- `cleanup_build` - Automatic cleanup of test resources

### 5.3 Manual Testing Checklist

- [ ] Build with `buildah-insecure-push` on Kind cluster
- [ ] Build with `buildah` pushing to quay.io
- [ ] Strategy auto-selection based on registry
- [ ] Manual strategy override
- [ ] Build progress display
- [ ] Build failure handling
- [ ] Agent creation after successful build
- [ ] HTTPRoute creation

---

# Phase 2: Shared Build Infrastructure

## Stage 6: Extract Common Build Utilities

**Objective**: Refactor agent-specific Shipwright code into shared utilities that can be used by both agents and tools.

### 6.1 Create Shared Build Module

**File**: `kagenti/backend/app/services/shipwright.py` (NEW)

Extract common functionality into a dedicated service module:

```python
"""
Shared Shipwright build utilities for agents and tools.
"""

from enum import Enum
from typing import Optional, List, Dict, Any
from pydantic import BaseModel

class ResourceType(Enum):
    """Type of resource being built."""
    AGENT = "agent"
    TOOL = "tool"

class ShipwrightBuildConfig(BaseModel):
    """Configuration for Shipwright builds (shared by agents and tools)."""
    buildStrategy: str = "buildah-insecure-push"
    dockerfile: str = "Dockerfile"
    buildArgs: Optional[List[str]] = None
    buildTimeout: str = "15m"

class BuildSourceConfig(BaseModel):
    """Git source configuration for builds."""
    gitUrl: str
    gitRevision: str = "main"
    contextDir: str
    gitSecretName: str = "github-shipwright-secret"

class BuildOutputConfig(BaseModel):
    """Output image configuration for builds."""
    registry: str
    imageName: str
    imageTag: str = "latest"
    pushSecretName: Optional[str] = None

def select_build_strategy(registry: str, override: Optional[str] = None) -> str:
    """Select appropriate ClusterBuildStrategy based on registry.

    Args:
        registry: Target container registry URL
        override: Optional manual override

    Returns:
        ClusterBuildStrategy name
    """
    if override:
        return override

    # Internal registries use insecure push
    internal_indicators = [
        "registry.cr-system",
        "localhost",
        "127.0.0.1",
        ".svc.cluster.local",
    ]

    for indicator in internal_indicators:
        if indicator in registry.lower():
            return "buildah-insecure-push"

    # External registries use secure push
    return "buildah"

def build_shipwright_build_manifest(
    name: str,
    namespace: str,
    resource_type: ResourceType,
    source: BuildSourceConfig,
    output: BuildOutputConfig,
    config: ShipwrightBuildConfig,
    labels: Dict[str, str],
    resource_config: Dict[str, Any],
) -> dict:
    """Build a Shipwright Build CRD manifest.

    Args:
        name: Build name
        namespace: Target namespace
        resource_type: AGENT or TOOL
        source: Git source configuration
        output: Output image configuration
        config: Build configuration (strategy, dockerfile, etc.)
        labels: Additional labels for the Build
        resource_config: Agent/tool configuration to store in annotation

    Returns:
        Shipwright Build manifest dict
    """
    # Common implementation...

def build_shipwright_buildrun_manifest(
    build_name: str,
    namespace: str,
    resource_type: ResourceType,
    labels: Dict[str, str],
) -> dict:
    """Build a Shipwright BuildRun CRD manifest.

    Args:
        build_name: Name of the Build to trigger
        namespace: Target namespace
        resource_type: AGENT or TOOL
        labels: Additional labels for the BuildRun

    Returns:
        Shipwright BuildRun manifest dict
    """
    # Common implementation...

def parse_buildrun_phase(buildrun: dict) -> str:
    """Parse BuildRun phase from status conditions.

    Returns: Pending, Running, Succeeded, Failed, or Unknown
    """
    # Common implementation...

def extract_resource_config_from_build(build: dict, resource_type: ResourceType) -> Optional[dict]:
    """Extract agent/tool config from Build annotations.

    Args:
        build: Shipwright Build resource
        resource_type: AGENT or TOOL (determines annotation key)

    Returns:
        Parsed configuration dict or None
    """
    annotation_key = f"kagenti.io/{resource_type.value}-config"
    # Common implementation...
```

### 6.2 Shared Pydantic Models

**File**: `kagenti/backend/app/models/shipwright.py` (NEW)

Move shared models to a dedicated module:

```python
"""
Shared Pydantic models for Shipwright builds.
"""

from typing import Optional, List
from pydantic import BaseModel

class ShipwrightBuildConfig(BaseModel):
    """Shipwright build configuration (shared by agents and tools)."""
    buildStrategy: str = "buildah-insecure-push"
    dockerfile: str = "Dockerfile"
    buildArgs: Optional[List[str]] = None
    buildTimeout: str = "15m"

class ShipwrightBuildInfoResponse(BaseModel):
    """Combined Build and BuildRun status (shared response model)."""
    # Build info
    name: str
    namespace: str
    resourceType: str  # "agent" or "tool"
    buildRegistered: bool
    outputImage: str
    strategy: str
    gitUrl: str
    gitRevision: str
    contextDir: str

    # Latest BuildRun info
    hasBuildRun: bool
    buildRunName: Optional[str] = None
    buildRunPhase: Optional[str] = None
    buildRunStartTime: Optional[str] = None
    buildRunCompletionTime: Optional[str] = None
    buildRunOutputImage: Optional[str] = None
    buildRunOutputDigest: Optional[str] = None
    buildRunFailureMessage: Optional[str] = None

    # Resource configuration from annotations (generic dict)
    resourceConfig: Optional[dict] = None
```

### 6.3 Refactor Agent Router to Use Shared Utilities

**File**: `kagenti/backend/app/routers/agents.py`

Update agent router to use the shared module:

```python
from app.services.shipwright import (
    ResourceType,
    build_shipwright_build_manifest,
    build_shipwright_buildrun_manifest,
    select_build_strategy,
    parse_buildrun_phase,
    extract_resource_config_from_build,
)
from app.models.shipwright import ShipwrightBuildConfig, ShipwrightBuildInfoResponse

# Replace agent-specific implementations with calls to shared utilities
def _build_shipwright_build_manifest(request: CreateAgentRequest) -> dict:
    """Build Shipwright Build manifest for an agent."""
    return build_shipwright_build_manifest(
        name=request.name,
        namespace=request.namespace,
        resource_type=ResourceType.AGENT,
        source=BuildSourceConfig(...),
        output=BuildOutputConfig(...),
        config=request.shipwrightConfig or ShipwrightBuildConfig(),
        labels={
            "kagenti.io/protocol": request.protocol,
            "kagenti.io/framework": request.framework,
        },
        resource_config={
            "protocol": request.protocol,
            "framework": request.framework,
            "createHttpRoute": request.createHttpRoute,
            # ... other agent-specific config
        },
    )
```

### 6.4 Shared Frontend Build Service

**File**: `kagenti/ui-v2/src/services/shipwright.ts` (NEW)

Create a generic build service:

```typescript
/**
 * Shared Shipwright build service for agents and tools.
 */

export type ResourceType = 'agent' | 'tool';

export interface ShipwrightBuildInfo {
  name: string;
  namespace: string;
  resourceType: ResourceType;
  buildRegistered: boolean;
  outputImage: string;
  strategy: string;
  gitUrl: string;
  gitRevision: string;
  contextDir: string;
  hasBuildRun: boolean;
  buildRunName?: string;
  buildRunPhase?: string;
  buildRunStartTime?: string;
  buildRunCompletionTime?: string;
  buildRunOutputImage?: string;
  buildRunOutputDigest?: string;
  buildRunFailureMessage?: string;
  resourceConfig?: Record<string, unknown>;
}

export const shipwrightService = {
  /**
   * Get build info for an agent or tool.
   */
  getBuildInfo: async (
    resourceType: ResourceType,
    namespace: string,
    name: string
  ): Promise<ShipwrightBuildInfo> => {
    const basePath = resourceType === 'agent' ? 'agents' : 'tools';
    const response = await apiClient.get(
      `/${basePath}/${namespace}/${name}/shipwright-build-info`
    );
    return response.data;
  },

  /**
   * Trigger a new BuildRun.
   */
  triggerBuildRun: async (
    resourceType: ResourceType,
    namespace: string,
    name: string
  ): Promise<void> => {
    const basePath = resourceType === 'agent' ? 'agents' : 'tools';
    await apiClient.post(`/${basePath}/${namespace}/${name}/shipwright-buildrun`);
  },

  /**
   * Finalize a build (create Agent/MCPServer).
   */
  finalizeBuild: async (
    resourceType: ResourceType,
    namespace: string,
    name: string,
    overrides?: Record<string, unknown>
  ): Promise<void> => {
    const basePath = resourceType === 'agent' ? 'agents' : 'tools';
    await apiClient.post(
      `/${basePath}/${namespace}/${name}/finalize-shipwright-build`,
      overrides
    );
  },
};
```

### 6.5 Generic Build Progress Page Component

**File**: `kagenti/ui-v2/src/components/BuildProgressView.tsx` (NEW)

Extract build progress UI into a reusable component:

```typescript
/**
 * Reusable build progress component for agents and tools.
 */

interface BuildProgressViewProps {
  resourceType: 'agent' | 'tool';
  namespace: string;
  name: string;
  onBuildComplete: () => void;
  onBuildFailed: () => void;
}

export const BuildProgressView: React.FC<BuildProgressViewProps> = ({
  resourceType,
  namespace,
  name,
  onBuildComplete,
  onBuildFailed,
}) => {
  // Shared build progress UI implementation
  // - Polls build info using shipwrightService
  // - Shows progress bar with phase
  // - Displays build details
  // - Auto-finalizes on success
  // - Shows retry button on failure
};
```

---

# Phase 3: Shipwright Builds for Tools

## Stage 7: Tool Build Backend Support

**Objective**: Add Shipwright Build/BuildRun support to the tools router.

### 7.1 Update CreateToolRequest Model

**File**: `kagenti/backend/app/routers/tools.py`

Add source build fields to the tool creation request:

```python
from app.models.shipwright import ShipwrightBuildConfig

class CreateToolRequest(BaseModel):
    """Request to create a new MCP tool."""

    name: str
    namespace: str
    protocol: str = "streamable_http"
    framework: str = "Python"
    envVars: Optional[List[EnvVar]] = None
    servicePorts: Optional[List[ServicePort]] = None
    createHttpRoute: bool = False

    # Deployment method: "image" (existing) or "source" (new)
    deploymentMethod: str = "image"

    # For image deployment (existing)
    containerImage: Optional[str] = None
    imagePullSecret: Optional[str] = None

    # For source build (new - Shipwright)
    gitUrl: Optional[str] = None
    gitRevision: str = "main"
    contextDir: Optional[str] = None
    registryUrl: Optional[str] = None
    registrySecret: Optional[str] = None
    imageTag: str = "v0.0.1"
    shipwrightConfig: Optional[ShipwrightBuildConfig] = None
```

### 7.2 Add Tool Build Manifest Generation

**File**: `kagenti/backend/app/routers/tools.py`

```python
from app.services.shipwright import (
    ResourceType,
    build_shipwright_build_manifest,
    build_shipwright_buildrun_manifest,
    BuildSourceConfig,
    BuildOutputConfig,
)

def _build_tool_shipwright_build_manifest(request: CreateToolRequest) -> dict:
    """Build Shipwright Build manifest for an MCP tool."""

    source = BuildSourceConfig(
        gitUrl=request.gitUrl,
        gitRevision=request.gitRevision,
        contextDir=request.contextDir,
    )

    output = BuildOutputConfig(
        registry=request.registryUrl,
        imageName=request.name,
        imageTag=request.imageTag,
        pushSecretName=request.registrySecret,
    )

    tool_config = {
        "protocol": request.protocol,
        "framework": request.framework,
        "createHttpRoute": request.createHttpRoute,
    }
    if request.envVars:
        tool_config["envVars"] = [ev.model_dump() for ev in request.envVars]
    if request.servicePorts:
        tool_config["servicePorts"] = [sp.model_dump() for sp in request.servicePorts]

    return build_shipwright_build_manifest(
        name=request.name,
        namespace=request.namespace,
        resource_type=ResourceType.TOOL,
        source=source,
        output=output,
        config=request.shipwrightConfig or ShipwrightBuildConfig(),
        labels={
            "kagenti.io/protocol": request.protocol,
            "kagenti.io/framework": request.framework,
        },
        resource_config=tool_config,
    )
```

### 7.3 Add Tool Shipwright Endpoints

**File**: `kagenti/backend/app/routers/tools.py`

Add new endpoints for Shipwright builds:

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/tools/{namespace}/{name}/shipwright-build-info` | GET | Get Build + BuildRun status |
| `/tools/{namespace}/{name}/shipwright-buildrun` | POST | Trigger new BuildRun |
| `/tools/{namespace}/{name}/finalize-shipwright-build` | POST | Create MCPServer after build |

```python
@router.get("/{namespace}/{name}/shipwright-build-info")
async def get_tool_shipwright_build_info(
    namespace: str,
    name: str,
    kube: KubernetesService = Depends(get_kubernetes_service),
) -> ShipwrightBuildInfoResponse:
    """Get Shipwright Build info for a tool."""
    # Implementation using shared utilities...

@router.post("/{namespace}/{name}/shipwright-buildrun")
async def create_tool_buildrun(
    namespace: str,
    name: str,
    kube: KubernetesService = Depends(get_kubernetes_service),
) -> dict:
    """Trigger a new BuildRun for a tool."""
    # Implementation using shared utilities...

@router.post("/{namespace}/{name}/finalize-shipwright-build")
async def finalize_tool_shipwright_build(
    namespace: str,
    name: str,
    request: FinalizeToolBuildRequest,
    kube: KubernetesService = Depends(get_kubernetes_service),
) -> CreateToolResponse:
    """Create MCPServer CRD after Shipwright build completes.

    1. Get latest BuildRun, verify success
    2. Extract output image from BuildRun status
    3. Read tool config from Build annotations
    4. Create MCPServer CRD with built image
    5. Create HTTPRoute if createHttpRoute is true
    6. Add kagenti.io/shipwright-build annotation to MCPServer
    """
```

### 7.4 Update Tool Creation Flow

**File**: `kagenti/backend/app/routers/tools.py`

Modify `create_tool` to support source builds:

```python
@router.post("", response_model=CreateToolResponse)
async def create_tool(
    request: CreateToolRequest,
    kube: KubernetesService = Depends(get_kubernetes_service),
) -> CreateToolResponse:
    """Create a new MCP tool."""

    if request.deploymentMethod == "source":
        # Validate source build fields
        if not request.gitUrl or not request.contextDir:
            raise HTTPException(
                status_code=400,
                detail="gitUrl and contextDir required for source builds",
            )

        # Create Shipwright Build
        build_manifest = _build_tool_shipwright_build_manifest(request)
        kube.create_custom_resource(
            group=SHIPWRIGHT_CRD_GROUP,
            version=SHIPWRIGHT_CRD_VERSION,
            plural=SHIPWRIGHT_BUILDS_PLURAL,
            namespace=request.namespace,
            body=build_manifest,
        )

        # Create BuildRun to trigger build
        buildrun_manifest = build_shipwright_buildrun_manifest(
            build_name=request.name,
            namespace=request.namespace,
            resource_type=ResourceType.TOOL,
            labels={"kagenti.io/tool-name": request.name},
        )
        buildrun = kube.create_custom_resource(
            group=SHIPWRIGHT_CRD_GROUP,
            version=SHIPWRIGHT_CRD_VERSION,
            plural=SHIPWRIGHT_BUILDRUNS_PLURAL,
            namespace=request.namespace,
            body=buildrun_manifest,
        )

        return CreateToolResponse(
            success=True,
            name=request.name,
            namespace=request.namespace,
            message=f"Shipwright build started. BuildRun: {buildrun['metadata']['name']}",
        )

    else:  # deploymentMethod == "image"
        # Existing image deployment flow...
```

### 7.5 Update Tool Deletion to Clean Up Builds

**File**: `kagenti/backend/app/routers/tools.py`

Update `delete_tool` to also delete Shipwright resources:

```python
@router.delete("/{namespace}/{name}", response_model=DeleteResponse)
async def delete_tool(
    namespace: str,
    name: str,
    kube: KubernetesService = Depends(get_kubernetes_service),
) -> DeleteResponse:
    """Delete a tool and associated Shipwright resources."""

    # Delete BuildRuns first
    try:
        buildruns = kube.list_custom_resources(
            group=SHIPWRIGHT_CRD_GROUP,
            version=SHIPWRIGHT_CRD_VERSION,
            namespace=namespace,
            plural=SHIPWRIGHT_BUILDRUNS_PLURAL,
            label_selector=f"kagenti.io/build-name={name}",
        )
        for buildrun in buildruns:
            kube.delete_custom_resource(...)
    except ApiException:
        pass  # Ignore if not found

    # Delete Build
    try:
        kube.delete_custom_resource(
            group=SHIPWRIGHT_CRD_GROUP,
            version=SHIPWRIGHT_CRD_VERSION,
            namespace=namespace,
            plural=SHIPWRIGHT_BUILDS_PLURAL,
            name=name,
        )
    except ApiException:
        pass  # Ignore if not found

    # Delete MCPServer
    kube.delete_custom_resource(
        group=TOOLHIVE_CRD_GROUP,
        version=TOOLHIVE_CRD_VERSION,
        namespace=namespace,
        plural=TOOLHIVE_MCP_PLURAL,
        name=name,
    )

    return DeleteResponse(success=True, message=f"Tool '{name}' deleted")
```

---

## Stage 8: Tool Build Frontend Support

**Objective**: Update the Import Tool page to support building from source.

### 8.1 Add Deployment Method Selection

**File**: `kagenti/ui-v2/src/pages/ImportToolPage.tsx`

Add deployment method toggle:

```typescript
// New state for deployment method
const [deploymentMethod, setDeploymentMethod] = useState<'image' | 'source'>('image');

// Source build fields (shown when deploymentMethod === 'source')
const [gitUrl, setGitUrl] = useState('');
const [gitRevision, setGitRevision] = useState('main');
const [contextDir, setContextDir] = useState('');
const [registryUrl, setRegistryUrl] = useState('');
const [registrySecret, setRegistrySecret] = useState('');
const [imageTag, setImageTag] = useState('v0.0.1');

// Build configuration (shared component)
const [buildStrategy, setBuildStrategy] = useState('buildah-insecure-push');
const [dockerfile, setDockerfile] = useState('Dockerfile');
const [buildTimeout, setBuildTimeout] = useState('15m');
```

### 8.2 Update Tool Form UI

**File**: `kagenti/ui-v2/src/pages/ImportToolPage.tsx`

Add form sections for source builds:

1. **Deployment Method Toggle**:
   - "Deploy from existing image" (default)
   - "Build from source"

2. **Source Configuration Section** (shown for source builds):
   - Git Repository URL
   - Git Branch/Tag
   - Source Subfolder (context directory)
   - Registry URL for built image
   - Registry Secret (optional)
   - Image Tag

3. **Build Configuration Section** (expandable, for source builds):
   - Build Strategy dropdown
   - Dockerfile path
   - Build timeout
   - Build arguments

### 8.3 Add Tool Build Progress Page

**File**: `kagenti/ui-v2/src/pages/ToolBuildProgressPage.tsx` (NEW)

Create build progress page for tools (uses shared component):

```typescript
/**
 * Build progress page for tools at /tools/:namespace/:name/build
 */

export const ToolBuildProgressPage: React.FC = () => {
  const { namespace, name } = useParams();
  const navigate = useNavigate();

  return (
    <BuildProgressView
      resourceType="tool"
      namespace={namespace!}
      name={name!}
      onBuildComplete={() => navigate(`/tools/${namespace}/${name}`)}
      onBuildFailed={() => {/* Show retry options */}}
    />
  );
};
```

### 8.4 Add Route for Tool Build Page

**File**: `kagenti/ui-v2/src/App.tsx`

```typescript
// Add route for tool build progress
<Route path="/tools/:namespace/:name/build" element={<ToolBuildProgressPage />} />
```

### 8.5 Update Tool Detail Page

**File**: `kagenti/ui-v2/src/pages/ToolDetailPage.tsx`

For tools built with Shipwright (have `kagenti.io/shipwright-build` annotation):
- Fetch and display Shipwright Build status on Status tab
- Show Build info (strategy, output image, Git source)
- Show latest BuildRun info (phase, duration)

### 8.6 Update Navigation Flow

- After source build submission → Navigate to `/tools/{namespace}/{name}/build`
- Build Progress page polls status → Auto-finalize on success → Redirect to tool detail
- If user navigates to `/tools/{namespace}/{name}` while build is in progress → Redirect to build page

---

## Stage 9: Tool Build Testing and CI

**Objective**: Add tests and CI support for tool Shipwright builds.

### 9.1 Backend Unit Tests

**File**: `kagenti/backend/tests/test_shipwright_tools.py` (NEW)

Test cases:
- Tool Build manifest generation
- Tool BuildRun manifest generation
- Tool config annotation storage/retrieval
- Finalize tool build endpoint
- Delete tool with Shipwright cleanup

### 9.2 Shared Utility Tests

**File**: `kagenti/backend/tests/test_shipwright_shared.py` (NEW)

Test cases:
- `select_build_strategy()` for various registries
- `build_shipwright_build_manifest()` with different resource types
- `build_shipwright_buildrun_manifest()` with different resource types
- `parse_buildrun_phase()` for various statuses
- `extract_resource_config_from_build()` for agents and tools

### 9.3 Integration Tests

**File**: `kagenti/tests/e2e/common/test_shipwright_tool_build.py` (NEW)

Test cases:
- Create Shipwright Build for a tool
- Create BuildRun and verify status progression
- Tool config stored in Build annotations
- MCPServer created after successful build

### 9.4 CI Script Updates

**Files**:
- `.github/scripts/kagenti-operator/75-deploy-weather-tool-shipwright.sh` (NEW)

Create CI script for building tools with Shipwright:

```bash
#!/usr/bin/env bash
# Deploy weather-tool via Shipwright build

# 1. Apply Shipwright Build
kubectl apply -f "$REPO_ROOT/kagenti/examples/tools/weather_tool_shipwright_build.yaml"

# 2. Create BuildRun
BUILDRUN_NAME=$(kubectl create -f "$REPO_ROOT/kagenti/examples/tools/weather_tool_shipwright_buildrun.yaml" -o jsonpath='{.metadata.name}')

# 3. Wait for BuildRun to succeed
kubectl wait --for=condition=Succeeded --timeout=600s buildrun/$BUILDRUN_NAME -n team1

# 4. Apply MCPServer with built image
kubectl apply -f "$REPO_ROOT/kagenti/examples/tools/weather_tool_shipwright.yaml"
```

### 9.5 Example Tool Manifests

**Files** (NEW):
- `kagenti/examples/tools/weather_tool_shipwright_build.yaml`
- `kagenti/examples/tools/weather_tool_shipwright_buildrun.yaml`
- `kagenti/examples/tools/weather_tool_shipwright.yaml`

### 9.6 Manual Testing Checklist

- [ ] Tool build with `buildah-insecure-push` on Kind cluster
- [ ] Tool build with `buildah` pushing to quay.io
- [ ] Tool build progress display
- [ ] Tool build failure handling
- [ ] MCPServer creation after successful build
- [ ] Tool deletion cleans up Shipwright resources
- [ ] Existing image deployment still works

---

## Implementation Order

### Phase 1: Agent Builds (Completed ✅)

| Stage | Description | Dependencies | Status |
|-------|-------------|--------------|--------|
| 1 | Backend API Changes | None | ✅ Complete |
| 2 | Frontend UI Changes | Stage 1 | ✅ Complete |
| 3 | Build Progress & Auto-Finalization | Stages 1, 2 | ✅ Complete |
| 4 | Cleanup and Migration | Stages 1-3 | ✅ Complete |
| 5 | Testing and Validation | Stages 1-4 | ✅ Complete |

### Phase 2: Shared Infrastructure (Completed ✅)

| Stage | Description | Dependencies | Status |
|-------|-------------|--------------|--------|
| 6 | Extract Common Build Utilities | Stages 1-5 | ✅ Complete |

### Phase 3: Tool Builds (Completed ✅)

| Stage | Description | Dependencies | Status |
|-------|-------------|--------------|--------|
| 7 | Tool Build Backend Support | Stage 6 | ✅ Complete |
| 8 | Tool Build Frontend Support | Stages 6, 7 | ✅ Complete |
| 9 | Tool Build Testing and CI | Stages 7, 8 | ✅ Complete |

---

## Shipwright Build Manifest Example

```yaml
apiVersion: shipwright.io/v1beta1
kind: Build
metadata:
  name: weather-service
  namespace: team1
  labels:
    kagenti.io/type: agent
    kagenti.io/protocol: a2a
    kagenti.io/framework: LangGraph
    app.kubernetes.io/created-by: kagenti-ui
spec:
  source:
    type: Git
    git:
      url: https://github.com/kagenti/agent-examples
      revision: main
      cloneSecret: github-shipwright-secret
    contextDir: a2a/weather_service
  strategy:
    name: buildah-insecure-push
    kind: ClusterBuildStrategy
  paramValues:
    - name: dockerfile
      value: Dockerfile
  output:
    image: registry.cr-system.svc.cluster.local:5000/weather-service:v0.0.1
  timeout: 15m
  retention:
    succeededLimit: 3
    failedLimit: 3
```

## Shipwright BuildRun Manifest Example

```yaml
apiVersion: shipwright.io/v1beta1
kind: BuildRun
metadata:
  generateName: weather-service-run-
  namespace: team1
  labels:
    kagenti.io/type: agent
    kagenti.io/agent-name: weather-service
    app.kubernetes.io/created-by: kagenti-ui
spec:
  build:
    name: weather-service
```

---

## Risk Mitigation

| Risk | Mitigation |
|------|------------|
| Shipwright not installed | Check for Shipwright CRDs on startup, show error if missing |
| Build strategy not found | Validate strategy exists before creating Build |
| Registry push failures | Clear error messages with troubleshooting steps |
| Backward compatibility | Keep AgentBuild support read-only for existing builds |
| Code duplication (agent/tool) | Extract shared utilities in Stage 6 before tool implementation |
| ToolHive CRD incompatibility | Verify MCPServer spec supports direct image references |

---

## Shared Components Summary

The following components are shared between agent and tool builds:

### Backend

| Component | File | Purpose |
|-----------|------|---------|
| `ShipwrightBuildConfig` | `app/models/shipwright.py` | Build configuration model |
| `ShipwrightBuildInfoResponse` | `app/models/shipwright.py` | Build status response model |
| `select_build_strategy()` | `app/services/shipwright.py` | Registry-based strategy selection |
| `build_shipwright_build_manifest()` | `app/services/shipwright.py` | Build CRD manifest generation |
| `build_shipwright_buildrun_manifest()` | `app/services/shipwright.py` | BuildRun CRD manifest generation |
| `parse_buildrun_phase()` | `app/services/shipwright.py` | Status phase detection |
| `extract_resource_config_from_build()` | `app/services/shipwright.py` | Config extraction from annotations |

### Frontend

| Component | File | Purpose |
|-----------|------|---------|
| `ShipwrightBuildInfo` | `services/shipwright.ts` | TypeScript interface for build info |
| `shipwrightService` | `services/shipwright.ts` | Shared API service for builds |
| `BuildProgressView` | `components/BuildProgressView.tsx` | Reusable build progress UI |
| `BuildStrategySelector` | `components/BuildStrategySelector.tsx` | Strategy selection dropdown |

### Labels and Annotations

| Label/Annotation | Values | Purpose |
|------------------|--------|---------|
| `kagenti.io/type` | `agent`, `tool` | Resource type identifier |
| `kagenti.io/shipwright-build` | Build name | Link resource to its Build |
| `kagenti.io/agent-config` | JSON | Agent config in Build annotation |
| `kagenti.io/tool-config` | JSON | Tool config in Build annotation |
| `kagenti.io/build-name` | Build name | Label on BuildRuns |

---

## Future Considerations

1. **Build Caching**: Configure Shipwright build caching for faster rebuilds
2. **Multi-arch Builds**: Support building for multiple architectures
3. **Build Logs Streaming**: Stream build logs to UI in real-time
4. **Webhook Triggers**: Support GitHub webhook-triggered builds
5. **Build Queue Management**: Handle concurrent builds and resource limits
6. **Build Templates**: Pre-configured build templates for common frameworks
7. **Source-to-Image (S2I)**: Support S2I build strategies for common languages
