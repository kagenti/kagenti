# Implementation Plan: Agent Runtime Contract (ARC)

**Branch**: `001-agent-runtime-contract` | **Date**: 2026-06-12 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `specs/001-agent-runtime-contract/spec.md`

## Summary

The ARC defines the versioned interface between the Kagenti platform and agent containers. The platform injects environment variables, volume mounts, and configuration files into every managed agent Pod. Agents read a single contract file (`/arc/AGENTS.md`) to discover what the platform provides and what they must expose. Implementation spans two repos: `kagenti-operator` (Go: CRD, webhook, controller) and `kagenti` (Python backend manifest builder, Helm charts, AGENTS.md template).

## Technical Context

**Language/Version**: Go 1.24+ (operator), Python 3.11+ (backend)
**Primary Dependencies**: controller-runtime, client-go (operator); FastAPI (backend)
**Storage**: Kubernetes ConfigMaps (contract files), SPIRE CSI (identity)
**Testing**: Go test (operator), pytest (backend E2E)
**Target Platform**: Kubernetes 1.28+, OpenShift 4.14+
**Project Type**: Kubernetes operator extension + backend API update
**Performance Goals**: AGENTS.md generation < 1s per AgentRuntime reconciliation
**Constraints**: Cross-repo coordination (kagenti-operator + kagenti). v1alpha1 scope: Deployment/StatefulSet only, OBO deferred to `none`.
**Scale/Scope**: ~10-50 agents per cluster in typical deployments

## Constitution Check

*GATE: No project-specific constitution configured. Proceeding with Kubernetes and Kagenti conventions.*

## Project Structure

### Documentation (this feature)

```text
specs/001-agent-runtime-contract/
├── plan.md              # This file
├── research.md          # Phase 0 output (updated)
├── data-model.md        # Phase 1 output (updated)
├── quickstart.md        # Phase 1 output
├── contracts/           # Phase 1 output
│   ├── agents-md-format.md   # AGENTS.md format contract
│   └── servers-json-format.md # servers.json format contract
└── tasks.md             # Phase 2 output (via /speckit-tasks)
```

### Source Code (cross-repo)

```text
# kagenti-operator repo (Go)
api/v1alpha1/
├── agentruntime_types.go    # CRD types: add spec.oboMode, spec.mcp.servers[]
└── zz_generated.deepcopy.go # Generated

internal/
├── controller/
│   ├── agentruntime_controller.go  # Reconciler: AGENTS.md + servers.json generation
│   └── arc/
│       ├── agents_md.go            # AGENTS.md template rendering
│       ├── servers_json.go         # servers.json generation
│       └── resolver/               # MCP server resolver framework
│           ├── registry.go         # RegisterResolver + ResolverRegistry
│           ├── direct.go           # Direct URL resolver (upstream)
│           └── label.go            # Label-based discovery resolver (upstream)
└── webhook/
    └── pod_mutator.go              # Inject ARC_* env vars, /arc/ volume mounts

# kagenti repo (this repo)
kagenti/backend/app/
├── routers/agents.py           # Update _build_agentruntime_manifest()
└── core/constants.py           # ARC_* env var constants

charts/kagenti/
├── values.yaml                 # ARC default config (contract version, MCP gateway URL)
└── templates/                  # Any ARC-related ConfigMap templates
```

**Structure Decision**: Extension of existing repos. No new repos or projects. Operator changes in kagenti-operator, backend/Helm changes in kagenti.

## Key Design Decisions

### 1. No `spec.arc` section in CRD

The controller derives ARC configuration from existing fields. New CRD fields:
- `spec.oboMode` (string: none|token-forwarding|correlation-header, default: none)
- `spec.mcp.servers[]` (list of MCP server references)

Tracing config comes from namespace annotations or platform-level config. Contract version comes from platform-level config. Target type comes from `spec.targetRef.kind`.

### 2. MCP Resolver Plugin Architecture

Follows the authbridge plugin pattern (Go `init()` + side-effect imports):
- `ResolverRegistry` with `RegisterResolver(name, factory)`
- Each resolver in its own package with `init()` registration
- Operator binary selects resolvers via blank imports
- Upstream: `direct` (URL passthrough), `label` (in-namespace `kagenti.io/protocol=mcp` discovery)
- Midstream/downstream: add resolvers by changing import list

### 3. Partial MCP Resolution

When symbolic references fail to resolve:
- `servers.json` contains only successfully resolved entries
- `MCPResolutionFailed` status condition set on AgentRuntime CR
- AGENTS.md notes unresolved references
- Pod starts and runs with resolved servers

### 4. ConfigMap Readiness

Standard ConfigMap volume mount. Kubernetes blocks Pod scheduling until the referenced ConfigMap exists. No init container needed.

### 5. v1alpha1 Scope Boundary

| Feature | Status |
|---------|--------|
| Deployment target | In scope |
| StatefulSet target | In scope (same as Deployment from injection perspective) |
| Sandbox/OpenShell target | Deferred (rejected with status condition) |
| OBO `none` (client-credentials) | In scope |
| OBO `token-forwarding` | Deferred (CRD field defined, returns status condition) |
| OBO `correlation-header` | Deferred (CRD field defined, returns status condition) |
| MCP resolver: direct URL | In scope |
| MCP resolver: label discovery | In scope |
| MCP resolver: gateway/catalog | Deferred to midstream/downstream builds |
| ServiceBinding: identity | In scope |
| ServiceBinding: model-access | Stretch goal |
| ServiceBinding: trace-collector | Stretch goal |

## Implementation Sequence

### Phase 1: Operator CRD + Types (kagenti-operator)

1. Add `spec.oboMode` and `spec.mcp` fields to AgentRuntime types
2. Add ARC-related status conditions (`ContractReady`, `MCPResolutionFailed`)
3. Regenerate deepcopy, run CRD generation
4. Update RBAC markers for ConfigMap management

### Phase 2: Resolver Framework (kagenti-operator)

5. Implement `ResolverRegistry` with `RegisterResolver(name, factory)` pattern
6. Implement `direct` resolver (URL passthrough)
7. Implement `label` resolver (in-namespace `kagenti.io/protocol=mcp` discovery)
8. Wire resolvers into operator binary via blank imports

### Phase 3: Controller AGENTS.md + servers.json (kagenti-operator)

9. Implement `servers.json` generation (merge platform defaults + resolved refs)
10. Implement AGENTS.md template rendering (Go templates, target-type-aware)
11. Create per-agent ConfigMaps (`<agent>-arc-contract`, `<agent>-arc-mcp`)
12. Set ownerReferences for cascade deletion
13. Watch MCPServerRegistration/AgentRuntime changes, regenerate on relevant config changes

### Phase 4: Webhook ARC Injection (kagenti-operator)

14. Inject `ARC_*` env vars into agent container
15. Inject standard env vars (`HTTP_PROXY`, `SPIFFE_ENDPOINT_SOCKET`, `SERVICE_BINDING_ROOT`)
16. Conditionally inject `OTEL_EXPORTER_OTLP_ENDPOINT`
17. Add `/arc/AGENTS.md` ConfigMap volume mount (subPath)
18. Add `/arc/mcp/servers.json` ConfigMap volume mount (subPath)
19. Add `/arc/skills/` emptyDir mount (when skills configured)

### Phase 5: Backend + Helm (kagenti, this repo)

20. Update `_build_agentruntime_manifest()` to include `spec.oboMode` and `spec.mcp.servers[]`
21. Update Helm values.yaml with ARC defaults (contract version, MCP gateway URL)
22. Update E2E tests to verify ARC env vars and mounts

### Phase 6: Documentation + ADR

23. Update ADR-0001 with final ARC design
24. Create AGENTS.md template reference doc
