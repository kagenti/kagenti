# Research: Agent Runtime Contract (ARC)

**Date**: 2026-06-12 (updated from 2026-05-13)
**Spec**: [spec.md](spec.md)

## R1: Webhook Injection Architecture

**Decision**: Extend the existing webhook in `kagenti-operator` (Go) to inject ARC environment variables and `/arc/` volume mounts alongside the current AuthBridge sidecar stack.

**Rationale**: The webhook already injects 5 containers and multiple ConfigMap mounts. ARC env vars and the `/arc/` volume mount are additions to the same mutation path. No new webhook needed.

**Current state**:
- Webhook lives in `kagenti-operator` repo (Go, separate from this repo)
- Triggered by `kagenti.io/type: agent` label on Pods
- Opt-out via `kagenti.io/inject: disabled` label
- Injects: proxy-init, sign-agentcard, envoy-proxy, spiffe-helper, client-registration
- Per-sidecar control via labels: `KAGENTI_ENVOY_PROXY_INJECT_LABEL`, `KAGENTI_SPIFFE_HELPER_INJECT_LABEL`, `KAGENTI_CLIENT_REGISTRATION_INJECT_LABEL`

**ARC changes needed in kagenti-operator**:
- Add `ARC_*` env var injection to the webhook mutation
- Add `/arc/AGENTS.md` and `/arc/mcp/servers.json` ConfigMap volume mounts (subPath)
- Conditionally inject `OTEL_EXPORTER_OTLP_ENDPOINT` based on namespace annotations or AgentRuntime CR config
- Standard ConfigMap volume mount ensures Pod blocks until ConfigMap exists (no init container needed)

## R2: AgentRuntime CRD Extension

**Decision**: Add `spec.oboMode` and `spec.mcp.servers[]` as top-level fields to the existing AgentRuntime CRD. No dedicated `spec.arc` section.

**Rationale**: The controller derives ARC contract content from multiple existing sources (target type from `spec.targetRef.kind`, tracing from namespace annotations, contract version from platform config). Adding a `spec.arc` section would duplicate information already derivable. Only per-agent choices (OBO mode, MCP server selection) need explicit CRD fields.

**Current CRD**:
- API: `agent.kagenti.dev/v1alpha1`
- Fields: `spec.type` (agent/tool), `spec.targetRef` (Deployment/StatefulSet/Sandbox), `spec.authBridgeMode`, `spec.mtlsMode`
- Defined in: `kagenti-operator` repo (Go types)
- Created by: Python backend (`_build_agentruntime_manifest()` in `agents.py`)

**New fields**:
```yaml
spec:
  oboMode: "none"  # "none" | "token-forwarding" | "correlation-header"
  mcp:
    servers:
      - name: "weather-tool"
        url: "http://weather-tool-service.team1:8080/mcp"
      - name: "github-mcp"
        type: "catalog"
        ref: "github-mcp-server"
```

**v1alpha1 scope**: `oboMode` field defined with all three values for forward compatibility, but only `none` is implemented. `token-forwarding` and `correlation-header` return a "not yet implemented" status condition.

**Cross-repo coordination**: The Python backend in this repo must be updated to include `spec.oboMode` and `spec.mcp` when building AgentRuntime manifests.

## R3: AGENTS.md Generation

**Decision**: Generate AGENTS.md in the Go operator controller (not Python backend), mounted via ConfigMap.

**Rationale**: The operator controller already reconciles AgentRuntime CRs and has access to cluster-wide state (MCP tool Deployments, namespace config). The Python backend creates the AgentRuntime CR but doesn't manage Pod-level resources after creation. AGENTS.md must be regenerated on config changes, which is a controller reconciliation concern.

**ConfigMap pattern**:
- Controller generates `<agent>-arc-contract` ConfigMap per AgentRuntime CR
- ConfigMap contains `AGENTS.md` key (contract file), mounted at `/arc/AGENTS.md` via subPath
- Controller generates `<agent>-arc-mcp` ConfigMap with `servers.json` key, mounted at `/arc/mcp/servers.json` via subPath
- Skills init container populates `/arc/skills/` (emptyDir shared volume, existing mechanism)
- Controller watches AgentRuntime CR changes and MCP-relevant config changes, regenerates ConfigMaps
- ownerReferences ensure cascade deletion when AgentRuntime CR is deleted
- Standard ConfigMap volume mount blocks Pod scheduling until ConfigMap exists

## R4: MCP Server Discovery

**Decision**: Resolver plugin architecture following the authbridge pattern. `spec.mcp.servers[]` lists references resolved at reconciliation time. Platform-level defaults merged automatically.

**Rationale**: The spec requires both direct URL references and symbolic references resolved by plugins. The authbridge codebase already implements this pattern: Go `init()` + `RegisterPlugin()` + blank imports for build-time selection. The same pattern applies to MCP resolvers.

**Resolver plugin architecture**:
- `ResolverRegistry` with `RegisterResolver(name, factory)` (same pattern as authbridge's `plugins.RegisterPlugin`)
- Each resolver in its own Go package with `init()` registration
- Operator binary selects resolvers via blank imports
- Upstream ships: `direct` (URL passthrough), `label` (in-namespace `kagenti.io/protocol=mcp` label discovery)
- Midstream/downstream adds: `gateway` (MCP Gateway URL), `catalog` (RHOAI catalog lookup)

**Partial resolution**: When symbolic references fail to resolve, the controller generates `servers.json` with only the successfully resolved entries, sets an `MCPResolutionFailed` status condition, and notes unresolved references in AGENTS.md. The Pod starts with whatever resolved.

**servers.json generation**:
```json
{
  "mcpServers": {
    "gateway": {
      "url": "http://mcp-gateway-broker.mcp-system:8080/mcp",
      "transport": "streamable-http"
    },
    "weather-tool": {
      "url": "http://weather-tool-service.team1:8080/mcp",
      "transport": "streamable-http",
      "auth": {
        "type": "none"
      }
    }
  }
}
```

## R5: ServiceBinding Integration

**Decision**: Implement ServiceBinding conventions from scratch. No existing integration to extend.

**Rationale**: Zero ServiceBinding references in current codebase. Credentials are currently via Secrets/ConfigMaps mounted directly. The ARC introduces `$SERVICE_BINDING_ROOT` as a new pattern.

**v1alpha1 scope**:
- `$SERVICE_BINDING_ROOT/identity/` with SPIFFE SVID (cert, key, bundle, type file)
- Mount paths align with existing SPIRE CSI driver output
- `model-access/` and `trace-collector/` as stretch goals (credentials currently in Secrets)

## R6: Cross-Repo Implementation Strategy

**Decision**: Implementation spans two repos. Changes must be coordinated.

| Change | Repo | Language |
|--------|------|----------|
| AgentRuntime CRD: `spec.oboMode`, `spec.mcp.servers[]` fields | kagenti-operator | Go |
| ARC status conditions (`ContractReady`, `MCPResolutionFailed`) | kagenti-operator | Go |
| Webhook: ARC env var injection | kagenti-operator | Go |
| Webhook: `/arc/` volume mount injection | kagenti-operator | Go |
| Controller: AGENTS.md ConfigMap generation | kagenti-operator | Go |
| Controller: servers.json ConfigMap generation | kagenti-operator | Go |
| Controller: MCP resolver framework + upstream resolvers | kagenti-operator | Go |
| Backend: `_build_agentruntime_manifest()` update | kagenti (this repo) | Python |
| Helm chart: ARC defaults in values.yaml | kagenti (this repo) | YAML |
| AGENTS.md template/format definition | kagenti (this repo) | Markdown |

**Sequencing**: Operator changes first (CRD, webhook, controller), then backend/Helm changes to use the new CRD fields.

## R7: v1alpha1 Scope Boundary

**Decision**: Implement core contract mechanics with deferrals for Sandbox and OBO.

| Feature | v1alpha1 | Rationale |
|---------|----------|-----------|
| Deployment + StatefulSet | Yes | Same PodTemplateSpec, identical injection |
| Sandbox/OpenShell | Deferred | Controller rejects with status condition |
| OBO `none` | Yes | Default, client-credentials via SPIFFE |
| OBO `token-forwarding` | Deferred | CRD field defined, authbridge sidecar ready, fast-follow |
| OBO `correlation-header` | Deferred | Requires new sidecar work (token stashing) |
| Resolver: direct URL | Yes | Trivial passthrough |
| Resolver: label discovery | Yes | Tools already labeled |
| Resolver: gateway/catalog | Deferred | Midstream/downstream concern |

## Alternatives Considered

### No `spec.arc` section vs dedicated section
- **Dedicated `spec.arc`**: Clean grouping but duplicates info derivable from existing fields (target type, tracing, contract version).
- **Top-level fields** (chosen): `spec.oboMode` and `spec.mcp.servers[]` at top level. Controller derives everything else. Less duplication, simpler CRD.

### AGENTS.md generation in Python backend vs Go operator
- **Python backend**: Simpler to prototype, but backend doesn't manage Pod lifecycle after creation. Can't react to config changes (no watch/reconcile loop).
- **Go operator** (chosen): Has reconciliation loop, watches CRs, can regenerate ConfigMaps on changes. Proper Kubernetes controller pattern.

### MCP resolver: webhook vs compiled Go interface
- **External webhook**: Network calls during reconciliation, latency, failure modes.
- **Compiled Go interface** (chosen): Following authbridge `init()` + `RegisterPlugin()` pattern. Build-time selection via blank imports. No runtime overhead.

### ConfigMap readiness: init container vs volume mount
- **Init container**: Extra container, poll loop, more complexity.
- **Standard ConfigMap volume mount** (chosen): Kubernetes blocks Pod scheduling until ConfigMap exists natively. Zero additional code.
