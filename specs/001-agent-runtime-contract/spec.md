# Feature Specification: Agent Runtime Contract (ARC)

**Feature Branch**: `001-agent-runtime-contract`  
**Created**: 2026-05-13  
**Status**: Draft  
**Input**: User description: "Agent Runtime Contract (ARC) - versioned specification of what the Kagenti platform provides to agent containers and what agents must expose in return"

## Clarifications

### Session 2026-05-13

- Q: Should AGENTS.md be pure Markdown or include a machine-parseable section for non-LLM tooling? → A: Markdown with YAML frontmatter. Machine-parseable header (version, target type, available bindings) plus Markdown body.
- Q: How should agents discover MCP servers, given both the MCP Gateway (single broker) and individual MCP servers (ToolHive model) need to be supported? → A: Single `/arc/mcp/servers.json` file in standard `mcpServers` format listing all endpoints (gateway + individual). `ARC_MCP_CONFIG` env var points to the file. Replaces `PLATFORM_MCP_SERVERS` env var.
- Q: When does the controller regenerate the AGENTS.md ConfigMap? → A: On relevant config changes (MCPServerRegistration, tracing config, contract version). Kubernetes propagates updates to mounted volumes automatically via kubelet sync. No Pod restart required.
- Path convention: All ARC-managed content lives under `/arc/` with subdirectories: `/arc/AGENTS.md`, `/arc/mcp/`, `/arc/skills/`. Replaces scattered `/mnt/mcp/`, `/mnt/skills/` paths.
- Env var naming: Kagenti-invented vars use `ARC_` prefix (`ARC_CONTRACT_VERSION`, `ARC_AGENT_ID`, `ARC_NAMESPACE`, `ARC_MCP_CONFIG`). Standard/well-known vars keep their names (`HTTP_PROXY`, `HTTPS_PROXY`, `SPIFFE_ENDPOINT_SOCKET`, `OTEL_EXPORTER_OTLP_ENDPOINT`, `SERVICE_BINDING_ROOT`).
- AgentRuntime CRD: No dedicated `spec.arc` section. Controller derives contract from existing config. `spec.oboMode` for OBO delegation (per-agent sidecar behavior). `spec.mcp.servers[]` for MCP server references with resolver plugin architecture.
- MCP server discovery: AgentRuntime `spec.mcp.servers[]` lists MCP server references (direct URL or symbolic ref resolved by plugins). Platform-level defaults (gateway URL) merged automatically from operator/namespace config. Extended `servers.json` includes transport type, auth hints, and credential references.
- Skills mount convention: Skills mount at `/arc/skills/<name>/` by default. The `mountPath` field in `spec.skills[]` becomes optional (defaults to `/arc/skills/<name>/`). Skill names must be unique within an AgentRuntime for distinct mount paths.
- Future: Per-agent tool filtering via MCPVirtualServer CRs (not in v1alpha1 scope).

### Session 2026-06-12

- Q: When a symbolic MCP server reference fails to resolve (plugin not found, catalog entry missing), what should happen? → A: Partial resolution. The controller generates `servers.json` with only successfully resolved entries, sets an `MCPResolutionFailed` status condition on the AgentRuntime CR, and AGENTS.md notes the unresolved references. The Pod starts and runs with whatever resolved successfully.
- Q: Is Sandbox/OpenShell target support in scope for the initial v1alpha1 implementation? → A: Deferred. Deployment and StatefulSet (identical from ARC perspective, same PodTemplateSpec injection) are in scope. Sandbox targets are recognized but rejected with a clear "not yet supported" status condition. Sandbox support is a fast-follow.
- Q: How should the Pod wait for the AGENTS.md ConfigMap before the agent container starts? → A: Standard ConfigMap volume mount. Kubernetes natively blocks Pod scheduling until the referenced ConfigMap exists. No init container needed. The webhook adds the volume and volume mount; the kubelet handles the rest.
- Q: Are MCP resolver plugins compiled Go interfaces or external webhooks? → A: Compiled Go interface with build-time flexibility, following the authbridge plugin pattern (kagenti-extensions). Resolvers register via `init()` + `RegisterResolver()`. Each operator binary selects its resolver set via blank imports (`_ "pkg/resolvers/gateway"`). Upstream ships basic resolvers (direct URL, label discovery); midstream/downstream adds infrastructure-specific resolvers by changing the import list. No external webhook calls during reconciliation.
- Q: Should OBO delegation modes be implemented in the initial v1alpha1? → A: Deferred. The CRD field `spec.oboMode` is defined with all three values (`none`, `token-forwarding`, `correlation-header`) for forward compatibility, but only `none` (client-credentials) is implemented. `token-forwarding` and `correlation-header` return a "not yet implemented" status condition. Note: the authbridge sidecar's `token-exchange` plugin already supports RFC 8693 exchange (the mechanics behind `token-forwarding`), so wiring it in is a fast-follow. `correlation-header` requires new sidecar work (inbound token stashing, correlation-ID lookup).

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Agent Developer Discovers Platform Capabilities (Priority: P1)

An agent developer deploying a new agent container to Kagenti needs to understand what the platform provides (identity, credentials, proxy, telemetry) and what the agent must expose (health probes, A2A card endpoint). Today this information is scattered across Slack threads, docs, and tribal knowledge. With ARC, the developer reads a single file (`/arc/AGENTS.md`) mounted into the container that describes everything the platform injected and everything the agent must provide. All ARC-managed content lives under the `/arc/` root directory (`/arc/AGENTS.md`, `/arc/mcp/`, `/arc/skills/`), giving agents one entry point to the entire contract.

**Why this priority**: Without a discoverable contract, every new agent deployment requires back-and-forth with the platform team. This is the core value proposition of the ARC: make the contract self-documenting and machine-readable inside the running container.

**Independent Test**: Deploy a minimal agent container to a Kagenti-managed namespace and verify that `/arc/AGENTS.md` exists, contains the current contract version, lists all injected `ARC_*` environment variables, describes available mount paths under `/arc/`, and documents required agent endpoints.

**Acceptance Scenarios**:

1. **Given** an agent Pod managed by Kagenti, **When** the Pod starts, **Then** the file `/arc/AGENTS.md` is mounted and contains the contract version, available environment variables, mount paths, auth behavior, and agent requirements.
2. **Given** an agent Pod managed by Kagenti, **When** the developer reads `/arc/AGENTS.md`, **Then** no cleartext credentials appear in the file; credential retrieval instructions reference file paths under `$SERVICE_BINDING_ROOT`.
3. **Given** an AI-native agent (e.g., Claude Code, OpenClaw), **When** the agent reads `/arc/AGENTS.md` at startup, **Then** it can programmatically determine what platform services are available and self-configure accordingly.

---

### User Story 2 - Platform Injects Identity and Proxy Transparently (Priority: P1)

An agent container receives plain HTTP traffic on its port. It makes outbound requests through `HTTP_PROXY`. The sidecar handles all TLS termination, mTLS authentication, JWT validation, and token exchange. The agent developer never writes authentication code. The pattern is straightforward: talk to localhost, complexity is behind the scenes.

**Why this priority**: Transparent auth is the primary mechanism that makes Kagenti agents framework-neutral. Without it, every agent framework needs custom auth integration code.

**Independent Test**: Deploy an agent that listens on plain HTTP and makes an outbound HTTP request through the proxy. Verify the sidecar presents the agent's SPIFFE identity on the outbound connection and terminates TLS on inbound connections.

**Acceptance Scenarios**:

1. **Given** an agent Pod with sidecar injection, **When** an external request arrives, **Then** the sidecar terminates TLS and forwards plain HTTP to the agent container.
2. **Given** an agent Pod with `HTTP_PROXY` configured, **When** the agent makes an outbound HTTP request, **Then** the sidecar intercepts the request, attaches the agent's SPIFFE X.509 SVID, and establishes mTLS with the destination.
3. **Given** a user-to-agent request with a JWT, **When** the sidecar validates the JWT, **Then** the agent receives the plain HTTP request without needing to handle token validation.

---

### User Story 3 - Controller Generates Target-Specific Contracts (Priority: P2)

The Kagenti controller detects the target type of each agent Pod (vanilla Deployment, OpenShell Sandbox, StatefulSet) and generates a target-specific AGENTS.md. A Deployment gets the full sidecar stack documentation. A Sandbox gets a light version noting that identity is managed by the OpenShell supervisor. The agent reads the same file path regardless of target type, but the content reflects what is actually available.

**Why this priority**: Target-specific contracts prevent confusion when agents run in different environments. Without this, an agent in a Sandbox might attempt to use proxy features that were never injected.

**Independent Test**: Deploy agents to two different target types (Deployment and StatefulSet) and verify that each Pod's `/arc/AGENTS.md` content is generated correctly with full sidecar stack documentation. *(v1alpha1 scope: Deployment and StatefulSet only. Sandbox target-type differentiation is deferred.)*

**Acceptance Scenarios**:

1. **Given** an agent with `spec.targetRef.kind: Deployment`, **When** the controller generates AGENTS.md, **Then** the file documents full sidecar injection: proxy, SPIFFE CSI, OTEL env vars, and mTLS/JWT auth paths.
2. **Given** an agent with `spec.targetRef.kind: Sandbox` or the `openshell.ai/managed-by` annotation, **When** the controller generates AGENTS.md, **Then** the file documents light injection (OTEL env vars only) and states that identity is managed by the OpenShell supervisor. *(Deferred from v1alpha1: controller rejects Sandbox targets with a status condition.)*
3. **Given** a new agent Pod is created, **When** the controller processes the Pod, **Then** AGENTS.md is generated as a ConfigMap and mounted at `/arc/AGENTS.md` before the agent container starts.

---

### User Story 4 - Contract Versioning Enables Safe Evolution (Priority: P2)

The ARC is versioned from day one (`v1alpha1`). The version is injected as the `ARC_CONTRACT_VERSION` environment variable and stated in AGENTS.md. Adding new environment variables or mount paths does not require a version bump. Renaming, removing, or changing the semantics of existing contract elements requires a version bump with a documented migration path.

**Why this priority**: Versioning prevents silent contract breakage when the platform evolves. Agents can check the contract version and adapt or fail clearly.

**Independent Test**: Deploy an agent, read `ARC_CONTRACT_VERSION`, verify it matches the version in AGENTS.md. Then simulate a contract change (add a new env var) and verify no version bump occurs. Simulate a rename and verify the version increments.

**Acceptance Scenarios**:

1. **Given** an agent Pod managed by Kagenti, **When** the Pod starts, **Then** the `ARC_CONTRACT_VERSION` environment variable is set and its value matches the version stated in `/arc/AGENTS.md`.
2. **Given** a platform update that adds a new environment variable, **When** the agent Pod restarts, **Then** the contract version remains unchanged and the new variable is documented in AGENTS.md.
3. **Given** a platform update that renames or removes an existing environment variable, **When** the change is deployed, **Then** the contract version is bumped and AGENTS.md includes a migration note describing the change.

---

### User Story 5 - OBO Delegation for User-Context Agent Calls (Priority: P3)

An agent needs to call an external service on behalf of the user who initiated the request (On-Behalf-Of delegation). Two opt-in mechanisms exist: token forwarding (agent reads the inbound `Authorization` header and includes it on outbound requests) and correlation header forwarding (agent forwards `X-Kagenti-Request-Id`, sidecar looks up the stored user token). Agents that don't opt in get client-credentials auth (the agent's own identity).

**Why this priority**: OBO is required for specific customer scenarios (e.g., Sunrise Entra ID integration) but not for all agents. Making it opt-in prevents forcing auth complexity on simple agents.

**Independent Test**: Deploy an agent with `spec.oboMode: none` (default) and verify it gets client-credentials auth for outbound requests. *(v1alpha1 scope: only `none` is implemented. `token-forwarding` and `correlation-header` tests apply to future releases.)*

**Acceptance Scenarios**:

1. **Given** an agent that reads and forwards the inbound `Authorization` header, **When** the agent makes an outbound request through the proxy, **Then** the sidecar performs an RFC 8693 token exchange, attaching the agent's identity as the actor. *(Deferred from v1alpha1.)*
2. **Given** an agent that forwards the `X-Kagenti-Request-Id` correlation header, **When** the agent makes an outbound request, **Then** the sidecar uses the correlation ID to look up the stored user token and performs the exchange without the agent ever seeing the token. *(Deferred from v1alpha1.)*
3. **Given** an agent that does not forward any auth headers, **When** the agent makes an outbound request through the proxy, **Then** the sidecar uses client-credentials auth (the agent's own SPIFFE identity) for the outbound call.

---

### User Story 6 - ServiceBinding-Compatible Credential Projection (Priority: P3)

Credentials (SPIFFE identity, model access keys, trace collector config) are projected as files following the ServiceBinding spec v1.1.0 conventions. The `$SERVICE_BINDING_ROOT` environment variable points to the root directory (default: `/bindings`), with subdirectories for each service category (`identity/`, `model-access/`, `trace-collector/`). Each subdirectory contains a `type` file identifying the service category.

**Why this priority**: Following ServiceBinding conventions means agents built for other ServiceBinding-compatible platforms work on Kagenti without modification, and Kagenti agents are portable to those platforms.

**Independent Test**: Deploy an agent and verify that `$SERVICE_BINDING_ROOT` is set, the expected subdirectories exist, each contains a `type` file, and credentials are readable from the projected file paths.

**Acceptance Scenarios**:

1. **Given** an agent Pod managed by Kagenti, **When** the Pod starts, **Then** `$SERVICE_BINDING_ROOT` is set (default `/bindings`) and contains subdirectories `identity/`, `model-access/`, and `trace-collector/`.
2. **Given** the `identity/` binding directory, **When** the agent reads its contents, **Then** it finds the SPIFFE X.509 SVID certificate, key, and trust bundle files, plus a `type` file with value `spiffe`.
3. **Given** the `model-access/` binding directory, **When** the agent reads its contents, **Then** it finds the model endpoint URL, API key, and provider type files, plus a `type` file with value `model`.

---

### User Story 7 - AgentRuntime CR Declares MCP Servers and OBO Mode (Priority: P2)

An agent developer declares which MCP servers should be available and the OBO delegation mode in the AgentRuntime CR. The controller derives the rest of the contract from existing config sources (target type from `spec.targetRef.kind`, tracing from namespace annotations, contract version from platform config). There is no dedicated `spec.arc` section; the controller assembles the contract from multiple inputs.

MCP server references in `spec.mcp.servers[]` can be direct URLs or symbolic names resolved by operator plugins. The operator has a resolver plugin architecture: upstream ships basic resolvers (direct URL, in-namespace label discovery), midstream/downstream builds add resolvers for specific infrastructure (MCP Gateway, RHOAI catalog). Platform-level defaults (e.g., MCP Gateway URL) are merged automatically from operator or namespace config without requiring per-agent declaration.

Skills mount at `/arc/skills/<name>/` by convention. The existing `spec.skills[]` field's `mountPath` becomes optional, defaulting to `/arc/skills/<name>/`. Skill names must be unique within an AgentRuntime.

**Why this priority**: The AgentRuntime CR is the natural place for per-agent configuration. MCP server references and OBO mode are per-agent choices. Platform-level settings (tracing, contract version) are derived, not duplicated.

**Independent Test**: Create an AgentRuntime CR with `spec.mcp.servers` listing a direct URL and a symbolic reference. Deploy the agent and verify that `/arc/mcp/servers.json` contains resolved entries for both servers (with transport type and auth hints), and AGENTS.md documents client-credentials auth (default `spec.oboMode: none`). Create a second AgentRuntime CR with defaults and verify platform-default MCP servers only. *(v1alpha1 scope: OBO modes beyond `none` are deferred.)*

**Acceptance Scenarios**:

1. **Given** an AgentRuntime CR with `spec.mcp.servers` listing a direct URL entry, **When** the controller generates servers.json, **Then** the entry appears with the URL, transport type, and appropriate auth hints.
2. **Given** an AgentRuntime CR with `spec.mcp.servers` listing a symbolic reference (e.g., `type: catalog, ref: github-mcp-server`), **When** the controller reconciles, **Then** the resolver plugin resolves the reference to a concrete URL and connection descriptor in servers.json.
3. **Given** an AgentRuntime CR with `spec.oboMode: token-forwarding`, **When** the agent Pod is created, **Then** AGENTS.md documents the token forwarding mechanism and the sidecar is configured for RFC 8693 exchanges.
4. **Given** an AgentRuntime CR with no `spec.mcp` section, **When** the controller generates servers.json, **Then** only platform-level defaults (e.g., MCP Gateway from namespace/operator config) appear in the file.
5. **Given** an AgentRuntime CR with `spec.skills` listing a skill without `mountPath`, **When** the operator mounts the skill, **Then** it is mounted at `/arc/skills/<name>/`.
6. **Given** a change to the AgentRuntime CR (e.g., adding an MCP server), **When** the controller reconciles, **Then** servers.json and AGENTS.md ConfigMaps are regenerated and propagated to the running Pod.

---

### Edge Cases

- What happens when an agent is deployed to a target type not recognized by the controller? The controller should reject the agent configuration with a clear error message indicating the unsupported target type.
- How does the system handle a Pod that starts before the controller has generated the AGENTS.md ConfigMap? The webhook adds a standard ConfigMap volume mount at admission time. Kubernetes natively blocks Pod scheduling until the referenced ConfigMap exists, so the agent container never starts without the contract. No init container is needed.
- What happens when an agent reads `/arc/mcp/servers.json` but no MCP servers or gateways are configured? The file MUST contain an empty `mcpServers` object (`{"mcpServers": {}}`), not be omitted, so agents can distinguish "no servers available" from "file not mounted."
- What happens when a symbolic MCP server reference fails to resolve (e.g., resolver plugin not registered, catalog entry not found)? The controller generates `servers.json` with only the successfully resolved entries, sets an `MCPResolutionFailed` status condition on the AgentRuntime CR, and includes a note in AGENTS.md listing the unresolved references. The agent Pod starts and operates with the resolved servers.
- What happens when the sidecar is unavailable but `HTTP_PROXY` is configured? Outbound requests fail with a connection error. The AGENTS.md should document that agents must handle proxy unavailability gracefully (retry with backoff).
- What happens when `$SERVICE_BINDING_ROOT` directories are mounted but empty (e.g., model access not configured for this agent)? The subdirectory should still exist with a `type` file, but without credential files. Agents should check for file existence before attempting to read credentials.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The Kagenti webhook MUST inject the following environment variables into every managed agent Pod. Kagenti-invented variables use the `ARC_` prefix; standard/well-known variables keep their established names:
  - `ARC_CONTRACT_VERSION` - ARC version (e.g., `v1alpha1`)
  - `ARC_AGENT_ID` - Agent identifier (SPIFFE ID)
  - `ARC_NAMESPACE` - Agent's namespace
  - `ARC_MCP_CONFIG` - Path to MCP server configuration file (`/arc/mcp/servers.json`)
  - `ARC_SKILLS_DIR` - Path to mounted skills (`/arc/skills/`)
  - `HTTP_PROXY` / `HTTPS_PROXY` - Proxy sidecar endpoint (standard)
  - `SPIFFE_ENDPOINT_SOCKET` - SPIRE Workload API socket (standard)
  - `SERVICE_BINDING_ROOT` - ServiceBinding convention root (standard, default: `/bindings`)
- **FR-002**: The Kagenti webhook MUST conditionally inject `OTEL_EXPORTER_OTLP_ENDPOINT` (standard name) when tracing is enabled in the AgentRuntime CR or at the namespace level.
- **FR-003**: The Kagenti controller MUST generate an `/arc/mcp/servers.json` file in extended `mcpServers` format (URL, transport type, auth hints, credential references) listing all available MCP endpoints and mount it into the agent Pod under the `/arc/mcp/` directory. The file MUST NOT contain cleartext credentials; credential entries reference Secrets or ServiceBinding paths.
- **FR-004**: The Kagenti controller MUST generate a target-specific AGENTS.md file for each managed agent Pod and mount it at `/arc/AGENTS.md` via a ConfigMap volume.
- **FR-005**: AGENTS.md MUST conform to the [AGENTS.md open standard](https://agents.md/) and use YAML frontmatter for machine-parseable ARC metadata (contract version, target type, available bindings list) as extension fields. The Markdown body MUST document: available environment variables with current values (except credentials), available mount paths, auth behavior description, agent requirements, and target-specific instructions.
- **FR-006**: AGENTS.md MUST NOT contain cleartext credentials. Credential entries MUST describe retrieval instructions (file paths under `$SERVICE_BINDING_ROOT`).
- **FR-007**: The platform MUST project credentials as files following the ServiceBinding spec v1.1.0 conventions under `$SERVICE_BINDING_ROOT` (default: `/bindings`) with subdirectories `identity/`, `model-access/`, and `trace-collector/`.
- **FR-008**: Each ServiceBinding subdirectory MUST contain a `type` file identifying the service category.
- **FR-009**: The SPIFFE identity binding (`identity/`) MUST contain the X.509 SVID certificate, private key, and trust bundle files, provisioned via the SPIRE CSI driver.
- **FR-010**: All ARC-managed content MUST be mounted under a single `/arc/` root directory: `/arc/AGENTS.md` (contract file), `/arc/mcp/` (MCP server configuration), `/arc/skills/<name>/` (skill artifacts per skill). MCP and AGENTS.md are populated via controller-generated ConfigMaps. Skills are mounted via OCI ImageVolumes or init containers.
- **FR-011**: Every managed agent MUST expose an A2A agent card endpoint at `/.well-known/agent-card.json`. This is a documented expectation in AGENTS.md; the platform does not validate the endpoint at deployment time. The controller verifies endpoint availability via the readiness probe path, not by probing the agent card URL.
- **FR-012**: Every managed agent MUST expose liveness and readiness health probe endpoints. The webhook configures the Pod's `livenessProbe` and `readinessProbe` fields to point at the agent's declared probe paths (from the AgentRuntime CR or defaults).
- **FR-013**: The controller MUST detect the target type via `spec.targetRef.kind` (Deployment, StatefulSet, Sandbox) and the `openshell.ai/managed-by` annotation.
- **FR-014**: For Sandbox/OpenShell targets, the controller MUST generate a light AGENTS.md (no proxy sidecar docs, identity noted as managed by OpenShell supervisor) and skip sidecar injection. *(Deferred from v1alpha1: controller rejects Sandbox targets with a "not yet supported" status condition.)*
- **FR-015**: For Sandbox/OpenShell targets, the webhook MUST still inject OTEL environment variables. *(Deferred from v1alpha1.)*
- **FR-016**: The contract version (`v1alpha1`) MUST be injected as `ARC_CONTRACT_VERSION` and stated in AGENTS.md.
- **FR-017**: Adding new environment variables or mount paths MUST NOT require a contract version bump.
- **FR-018**: Renaming, removing, or semantically changing existing contract elements MUST require a version bump with a documented migration path in AGENTS.md.
- **FR-019**: The platform MUST support two opt-in OBO delegation mechanisms: token forwarding (agent forwards `Authorization` header, sidecar performs RFC 8693 exchange) and correlation header forwarding (agent forwards `X-Kagenti-Request-Id`, sidecar looks up stored user token). *(Deferred from v1alpha1: CRD field defined but only `none` implemented. `token-forwarding` is a fast-follow since authbridge's token-exchange plugin already supports RFC 8693. `correlation-header` requires new sidecar work.)*
- **FR-020**: Agents that do not opt into OBO delegation MUST receive client-credentials auth (agent's own SPIFFE identity) for outbound requests.
- **FR-021**: `/arc/mcp/servers.json` MUST contain an empty `mcpServers` object (`{"mcpServers": {}}`) when no MCP servers or gateways are configured, not be omitted.
- **FR-022**: The controller MUST reject agent configurations that reference unsupported target types with a clear error message.
- **FR-023**: The controller MUST regenerate the AGENTS.md ConfigMap and the `/arc/mcp/servers.json` ConfigMap when relevant platform configuration changes (MCPServerRegistration CRs, AgentRuntime CR, tracing config, contract version). Kubernetes volume propagation delivers updates to running Pods without requiring a restart.
- **FR-024**: The AgentRuntime CR MUST support `spec.oboMode` (none, token-forwarding, correlation-header) to control per-agent OBO delegation behavior in the sidecar. The controller MUST derive all other ARC configuration from existing sources: target type from `spec.targetRef.kind`, tracing from namespace annotations or platform config, contract version from platform-level config.
- **FR-025**: The AgentRuntime CR MUST support `spec.mcp.servers[]` listing MCP server references. Each entry MUST have a `name` and either a direct `url` or a symbolic reference (`type` + `ref`) resolved by an operator plugin at reconciliation time.
- **FR-026**: The operator MUST support a resolver plugin architecture for MCP server references, following the authbridge plugin pattern: a Go `ResolverRegistry` with `RegisterResolver(name, factory)`, resolver implementations in their own packages with `init()` registration, and build-time selection via blank imports. Upstream ships basic resolvers (direct URL passthrough, in-namespace label discovery via `kagenti.io/protocol=mcp`). Midstream/downstream builds add resolvers for specific infrastructure (e.g., MCP Gateway, RHOAI catalog) by adding blank imports to the operator binary, without modifying upstream operator code.
- **FR-027**: Platform-level MCP defaults (e.g., MCP Gateway URL from operator config or namespace annotation) MUST be merged into every agent's `servers.json` automatically, without requiring per-agent declaration in `spec.mcp.servers[]`.
- **FR-028**: Each entry in `/arc/mcp/servers.json` MUST include at minimum `url` and MAY include `transport` (e.g., `streamable-http`), and `auth` (type, credential reference). No cleartext credentials in the file.
- **FR-029**: The `mountPath` field in `spec.skills[]` MUST be optional. When omitted, the operator MUST mount the skill at `/arc/skills/<name>/` where `<name>` is the skill's `name` field. Skill names MUST be unique within an AgentRuntime to ensure distinct mount paths.
- **FR-030**: When a symbolic MCP server reference in `spec.mcp.servers[]` fails to resolve (resolver plugin not registered, catalog entry not found, resolution timeout), the controller MUST generate `servers.json` with only the successfully resolved entries, set an `MCPResolutionFailed` status condition on the AgentRuntime CR, and note unresolved references in AGENTS.md. The agent Pod MUST NOT be blocked from starting due to unresolved MCP references.

### Key Entities

- **Agent Runtime Contract (ARC)**: The versioned specification defining the interface between the Kagenti platform and agent containers. Describes what the platform provides (env vars, mounts, auth, identity) and what agents must expose (endpoints, probes).
- **AGENTS.md**: A controller-generated, target-specific Markdown file mounted at `/arc/AGENTS.md` in every managed agent Pod. Contains the materialized contract for the specific agent's deployment context.
- **Target Type**: The kind of workload hosting the agent (Deployment, StatefulSet, Sandbox). Determines which platform capabilities are injected and what AGENTS.md content is generated.
- **ServiceBinding**: A credential projection convention following the ServiceBinding spec v1.1.0. Credentials are mounted as files under `$SERVICE_BINDING_ROOT` with subdirectories per service category.
- **OBO Delegation**: On-Behalf-Of token exchange mechanism allowing agents to call external services with the calling user's identity. Opt-in via header forwarding.
- **AgentRuntime CR**: The Kubernetes custom resource where agent developers declare MCP server references (`spec.mcp.servers[]`), OBO mode (`spec.oboMode`), and skills (`spec.skills[]`). The controller derives the rest of the contract from existing config sources.
- **MCP Server Resolver**: A plugin interface in the operator that resolves symbolic MCP server references to concrete connection descriptors (URL, transport, auth hints). Upstream provides basic resolvers; midstream/downstream builds add infrastructure-specific resolvers.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 100% of managed agent Pods have a readable `/arc/AGENTS.md` file mounted before the agent container starts.
- **SC-002**: Agent developers can deploy a new agent without any platform team assistance by reading only the contract file and public documentation. Measurable: a developer unfamiliar with the platform can deploy a functioning agent using only `/arc/AGENTS.md` and public docs within 30 minutes, with zero support requests for "what env vars are available" or "how do I configure auth."
- **SC-003**: AI-native agents can self-configure from the contract file within 30 seconds of startup, without requiring hardcoded platform knowledge.
- **SC-004**: Switching an agent between target types (Deployment to StatefulSet) requires zero agent code changes; only the contract content changes. *(Deployment to Sandbox transition is deferred from v1alpha1.)*
- **SC-005**: Adding a new platform capability (env var, mount path) to the contract does not break any existing agent deployments.
- **SC-006**: All credential access follows the ServiceBinding convention, verified by agents built for other ServiceBinding-compatible platforms reading Kagenti-projected credentials without modification.
- **SC-007**: Agents that do not opt into OBO delegation continue to function with client-credentials auth, verified by deploying an agent with no auth header forwarding and confirming successful outbound calls.

## Assumptions

- The Kagenti webhook (mutating admission webhook) is the existing injection mechanism and will be extended, not replaced, to inject ARC-related environment variables and volume mounts.
- The Kagenti controller already manages agent Pods and will be extended to generate AGENTS.md ConfigMaps.
- SPIRE is deployed and the CSI driver is available for projecting SPIFFE X.509 SVIDs into agent Pods.
- The `v1alpha1` designation signals that the contract is expected to evolve; breaking changes are permitted with version bumps during the alpha phase.
- OpenShell/Sandbox integration is deferred from v1alpha1 scope. The initial implementation covers Deployment and StatefulSet targets (identical from the ARC injection perspective since both use PodTemplateSpec). The controller recognizes Sandbox target types but rejects them with a clear "not yet supported" status condition. Sandbox support is a fast-follow.
- The AGENTS.md format conforms to the [AGENTS.md open standard](https://agents.md/) (Linux Foundation / Agentic AI Foundation). The spec supports optional YAML frontmatter with forward-compatible extension fields. ARC-specific frontmatter fields (`contract_version`, `target_type`, `bindings`) are treated as extension fields that standard AGENTS.md tooling ignores. This gives compatibility with Claude Code, Codex CLI, Gemini CLI, Cursor, and Copilot out of the box.
- The ServiceBinding Operator is not a hard dependency. Kagenti adopts the directory structure and environment variable conventions from the ServiceBinding spec without requiring the operator itself.
- Skill artifacts are distributed as OCI images via the existing `spec.skills[]` mechanism. The ARC adds a mount path convention (`/arc/skills/<name>/`) as the default when `mountPath` is omitted.
- The AgentRuntime CRD already exists in the Kagenti operator. This spec adds `spec.oboMode` and `spec.mcp.servers[]` as new fields. No dedicated `spec.arc` section; the controller derives contract content from existing config sources.
- The MCP Gateway URL is configured at the platform or namespace level (operator flag, ConfigMap, or namespace annotation). The operator merges it into every agent's servers.json. The specific configuration mechanism for platform-level defaults is left to the operator implementation.
- The resolver plugin architecture allows midstream/downstream builds to add infrastructure-specific MCP server resolvers without forking the upstream operator.
