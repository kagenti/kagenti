# Review Guide: Agent Runtime Contract (ARC)

**Generated**: 2026-06-12 | **Spec**: [spec.md](spec.md) | **RFE**: [RHAIRFE-2389](https://redhat.atlassian.net/browse/RHAIRFE-2389)

## Why This Change

The platform already injects proxy config and identity certificates into agent Pods, and the sidecar terminates TLS before traffic reaches the agent. But these expectations are not captured in a single place. An agent developer deploying a new container has to look up documentation scattered across multiple sources to understand what the platform provides and what the agent must do.

The ARC formalizes this as a versioned, bidirectional contract. The platform injects capabilities, the agent follows obligations, and a machine-readable file lets AI-native agents self-configure without human intervention.

## What Changes

The developer declares what the agent needs in the AgentRuntime custom resource (which MCP servers, which skills, which model). The platform figures out the actual URLs and credentials and pushes them into the Pod as environment variables and mounted files. An agent that declares access to a model served through MaaS gets the endpoint URL and API key as projected files. Skills are pulled from pluggable sources (OCI images, a platform skill catalog, the Red Hat skill catalog) and mounted at known paths. No connection strings, no manual wiring.

**Platform-provided capabilities:**
- Identity (SPIFFE X.509 certificates via CSI driver)
- Outbound proxy (mTLS, access policy enforcement)
- MCP tool endpoints (resolved from per-agent declarations and platform defaults)
- Model access (endpoint URL, API credentials as projected files)
- Tracing (OpenTelemetry collector endpoint)
- Skills (mounted from pluggable sources)
- Credentials (projected as files following ServiceBinding conventions)

**Agent obligations:**
- Route outbound traffic through `HTTP_PROXY` so the platform can enforce mTLS and access policies
- Carry the inbound user bearer token on outbound requests when participating in On-Behalf-Of flows
- Expose health probes and an A2A agent card endpoint

For AI-native agents (Claude Code, Codex CLI, OpenClaw), the injected configuration is also written out as an AGENTS.md file conforming to the [AGENTS.md open standard](https://agents.md/). The agent can parse it at startup to discover what the platform provided and what it must do in return. Together, the injected env vars, mounted files, and machine-readable contract form the Agent Runtime Contract (ARC), versioned as `v1alpha1`.

No breaking changes to existing agent deployments; this is purely additive.

## How It Works

The implementation spans two repos. In **kagenti-operator** (Go): the AgentRuntime CRD gets `spec.oboMode` and `spec.mcp.servers[]` fields, the webhook is extended to inject `ARC_*` env vars and `/arc/` volume mounts, and the controller generates per-agent ConfigMaps containing the rendered AGENTS.md and servers.json. The controller derives contract content from existing config sources (target type from `spec.targetRef.kind`, tracing from namespace annotations, contract version from platform config, MCP servers from resolver plugins).

In **kagenti** (this repo): the Python backend passes the new fields through to AgentRuntime manifests, Helm charts get ARC default values, and the ADR documents the architecture.

ConfigMaps use ownerReferences to the AgentRuntime CR for lifecycle management. Kubernetes propagates updates to mounted volumes via kubelet sync (no Pod restart needed).

## When It Applies

**Applies when**:
- Any agent Pod managed by Kagenti (label `kagenti.io/type: agent`)
- Deployment and StatefulSet target types (identical injection, both use PodTemplateSpec)
- Both MCP Gateway and individual MCP server configurations
- OBO delegation scenarios (token-forwarding or correlation-header modes)

**Does not apply when**:
- Sidecar implementation details (how envoy-proxy terminates TLS, how SPIFFE helper fetches SVIDs); ARC describes what the agent sees, not how the sidecar works
- MCP Gateway internals (separate project); only the agent-facing discovery interface is in scope
- Adapter base images or certified framework images (product decision, deferred)
- Sandbox/OpenShell target type (deferred from v1alpha1; controller recognizes but rejects with status condition)

## Key Decisions

1. **`/arc/` root directory** for all contract content instead of scattered paths (`/mnt/mcp/`, `/mnt/skills/`). Single entry point for agents. Credentials stay outside `/arc/` under `$SERVICE_BINDING_ROOT` to follow ServiceBinding conventions independently.

2. **`ARC_` prefix** for Kagenti-invented env vars (`ARC_CONTRACT_VERSION`, `ARC_AGENT_ID`, `ARC_NAMESPACE`, `ARC_MCP_CONFIG`, `ARC_SKILLS_DIR`). Standard vars keep their names (`HTTP_PROXY`, `SPIFFE_ENDPOINT_SOCKET`, `OTEL_EXPORTER_OTLP_ENDPOINT`).

3. **AGENTS.md open standard conformance** with YAML frontmatter extensions rather than a custom format. The standard supports forward-compatible extension fields. This gives automatic discovery by Claude Code, Codex CLI, Gemini CLI, Cursor, and Copilot.

4. **Standard `mcpServers` JSON format** for MCP discovery, supporting both gateway and individual servers in one file. This is the same format used by Claude Code, Cursor, Windsurf, Gemini, and others for MCP client configuration.

5. **No dedicated `spec.arc` in the CRD**. The controller derives contract content from existing config sources. Only `spec.oboMode` and `spec.mcp.servers[]` are added as new fields because they are per-agent choices.

6. **ServiceBinding v1.1.0 conventions** for credential projection without requiring the ServiceBinding Operator. The kagenti-operator controller creates the projected files directly.

7. **Resolver plugin architecture** for MCP server references. Upstream ships basic resolvers (direct URL, label discovery). Midstream/downstream builds add resolvers for specific infrastructure (MCP Gateway, RHOAI catalog) via blank imports, without modifying upstream code.

## Areas Needing Attention

- **Cross-repo coordination**: 75% of implementation is in kagenti-operator (Go), 25% in this repo (Python/Helm). Operator changes must ship first.

- **ServiceBinding directories**: The spec requires `model-access/` and `trace-collector/` bindings, but current codebase has no ServiceBinding integration at all. These may be stretch goals for `v1alpha1` depending on what secrets/configs are available to project.

- **ConfigMap regeneration scope**: The controller watches AgentRuntime CR changes and MCP tool Deployments. If platform-level config changes (tracing, contract version) are stored in a ConfigMap or operator flag, the watch scope needs to include those objects.

- **Partial MCP resolution**: When a symbolic reference fails to resolve, the controller generates servers.json with only the resolved entries and sets an `MCPResolutionFailed` status condition. This favors availability over completeness. Review whether this trade-off is right for all scenarios.

## Open Questions

1. **Contract governance**: Long-term, the contract spec should live in a shared repo between Kagenti and OpenShell. For `v1alpha1`, it's Kagenti-owned.

2. **Skills projection source**: The `/arc/skills/` mount path is defined. The mechanism for downloading skills (OCI images, platform catalog, Red Hat catalog) is pluggable.

3. **AGENTS.md machine-readable companion**: If non-LLM tooling needs richer structured data than YAML frontmatter provides, a companion `/arc/contract.json` could be added later.

## Review Checklist

- [ ] The injection-first framing is clear: platform pushes config, developer declares intent
- [ ] Agent obligations are complete (proxy routing, OBO token forwarding, health probes, A2A card)
- [ ] Key decisions are justified (especially `ARC_` prefix, no `spec.arc`, ServiceBinding conventions)
- [ ] Scope matches stated boundaries (no sidecar internals, no MCP Gateway internals)
- [ ] Cross-repo implementation plan is realistic (operator first, then backend/Helm)
- [ ] AGENTS.md example is complete and conformant with the open standard
- [ ] Environment variable naming convention is consistent throughout
- [ ] Edge cases are addressed (unsupported target type, empty MCP servers, missing ConfigMap, partial MCP resolution)

---

<!-- Code phase sections are appended below this line by the phase-manager command -->
