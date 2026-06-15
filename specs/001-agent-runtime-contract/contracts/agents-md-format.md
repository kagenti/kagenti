# Contract: AGENTS.md Format

**Version**: v1alpha1
**Standard**: [AGENTS.md open standard](https://agents.md/)

## Format

YAML frontmatter (ARC extension fields) + Markdown body.

## Example

```markdown
---
contract_version: v1alpha1
target_type: Deployment
bindings:
  - identity
  - model-access
arc_root: /arc
obo_mode: none
tracing_enabled: true
---

# Agent Runtime Contract

**Contract Version**: v1alpha1
**Target Type**: Deployment
**Generated**: 2026-05-13T10:00:00Z

## Platform-Provided Environment Variables

| Variable | Value | Description |
|----------|-------|-------------|
| `ARC_CONTRACT_VERSION` | `v1alpha1` | Contract version |
| `ARC_AGENT_ID` | `spiffe://localtest.me/ns/team1/sa/my-agent` | Agent SPIFFE identity |
| `ARC_NAMESPACE` | `team1` | Agent namespace |
| `ARC_MCP_CONFIG` | `/arc/mcp/servers.json` | MCP server configuration |
| `ARC_SKILLS_DIR` | `/arc/skills/` | Mounted skills directory |
| `HTTP_PROXY` | `http://127.0.0.1:15001` | Outbound proxy (sidecar) |
| `HTTPS_PROXY` | `http://127.0.0.1:15001` | Outbound proxy (sidecar) |
| `SPIFFE_ENDPOINT_SOCKET` | `unix:///spiffe-workload-api/spire-agent.sock` | SPIRE Workload API |
| `SERVICE_BINDING_ROOT` | `/bindings` | ServiceBinding root directory |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | `http://otel-collector.kagenti-system:4317` | OTEL collector |

## Mount Paths

| Path | Contents | Source |
|------|----------|--------|
| `/arc/AGENTS.md` | This contract file | Controller (ConfigMap) |
| `/arc/mcp/servers.json` | MCP server endpoints | Controller (ConfigMap) |
| `/arc/skills/` | Skill artifacts | Init container |
| `/bindings/identity/` | SPIFFE X.509 SVID | SPIRE CSI driver |
| `/bindings/model-access/` | Model endpoint credentials | Controller (Secret) |

## Auth Behavior

**Inbound (requests to this agent)**:
The sidecar terminates TLS and validates JWTs. Your container receives plain HTTP.
You do not need to handle TLS or token validation.

**Outbound (requests from this agent)**:
Route all outbound HTTP through `$HTTP_PROXY`. The sidecar attaches your SPIFFE
identity (mTLS) automatically.

**Agent-to-Agent**: mTLS via SPIFFE X.509 SVID. Transparent through the proxy.

**User-to-Agent**: JWT with shared audience + role check. Sidecar validates, you receive plain HTTP.

## Agent Requirements

Your agent container MUST:

1. **Expose an A2A agent card** at `/.well-known/agent-card.json` on your container port
2. **Expose health probes**: liveness and readiness endpoints
3. **Listen on a discoverable port** (convention: 8080)

## MCP Server Access

Available MCP servers are listed in `/arc/mcp/servers.json`.
Read this file to discover gateway and individual MCP server endpoints.

## Credentials

**Do not hardcode credentials.** Read from ServiceBinding paths:

- **SPIFFE identity**: `$SERVICE_BINDING_ROOT/identity/` (cert, key, bundle)
- **Model access**: `$SERVICE_BINDING_ROOT/model-access/` (url, api-key, provider)

## On-Behalf-Of Delegation

**Mode**: none (client-credentials)

Your outbound requests use your agent's own SPIFFE identity.
To enable user-context delegation, configure `spec.oboMode` in your AgentRuntime CR.
```

## Frontmatter Schema

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `contract_version` | string | yes | - | ARC version |
| `target_type` | string | yes | - | Deployment, StatefulSet, Sandbox |
| `bindings` | list[string] | yes | - | Available ServiceBinding categories |
| `arc_root` | string | yes | `/arc` | Root path for ARC content |
| `obo_mode` | string | yes | `none` | OBO delegation mode |
| `tracing_enabled` | boolean | no | false | OTEL tracing configured |

## Body Section Order

1. Header (contract version, target type, generation timestamp)
2. Platform-Provided Environment Variables
3. Mount Paths
4. Auth Behavior
5. Agent Requirements
6. MCP Server Access
7. Credentials
8. On-Behalf-Of Delegation
9. Target-Specific Notes (only for non-Deployment targets)

## Target-Type Variations

### Deployment (full contract)
All sections present. Full sidecar stack documented.

### StatefulSet
Same as Deployment. Additional note about PVC persistence.

### Sandbox (OpenShell)
- Auth Behavior: "Identity managed by OpenShell supervisor. No proxy sidecar."
- Mount Paths: No HTTP_PROXY-related mounts
- OTEL env vars still injected
- Credentials section references OpenShell credential projection
