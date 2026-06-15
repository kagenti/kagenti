# Tasks: Agent Runtime Contract (ARC)

**Input**: Design documents from `specs/001-agent-runtime-contract/`
**Prerequisites**: plan.md (required), spec.md (required), research.md, data-model.md, contracts/
**Updated**: 2026-06-12 (aligned with clarification session)

**Organization**: Tasks are grouped by implementation phase. This feature spans two repos: `kagenti-operator` (Go) and `kagenti` (this repo, Python/Helm). Tasks are tagged with their target repo.

**Scope**: v1alpha1. Sandbox/OpenShell targets deferred. OBO modes beyond `none` deferred. ARC is an orthogonal concept; the AgentRuntime CRD has NO `spec.arc` section. Per-agent choices use top-level fields (`spec.oboMode`, `spec.mcp`). Everything else is derived by the controller.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (e.g., US1, US2, US3)
- Include exact file paths in descriptions

## Path Conventions

- **kagenti-operator** (Go): `api/v1alpha1/`, `internal/webhook/`, `internal/controller/`
- **kagenti** (this repo): `kagenti/backend/app/`, `charts/kagenti/`, `docs/`

---

## Phase 1: Setup

**Purpose**: Define the ARC contract formats. No code changes yet, just the artifacts that all implementation tasks reference.

- [ ] T001 Define AGENTS.md template file with YAML frontmatter schema and all body sections per contracts/agents-md-format.md, create as a Go template in kagenti-operator at internal/controller/arc/templates/agents.md.tmpl
- [ ] T002 [P] Define servers.json schema per contracts/servers-json-format.md, create as Go template in kagenti-operator at internal/controller/arc/templates/servers.json.tmpl
- [x] T003 [P] Write ADR document ADR-0001 at docs/adr/0001-agent-runtime-contract.md

---

## Phase 2: CRD Extension + Webhook Foundation

**Purpose**: Extend the AgentRuntime CRD with new top-level fields and update the webhook for ARC injection. MUST be complete before any user story can be validated on a cluster.

**Target repo**: kagenti-operator

- [ ] T004 Add `OBOMode` field (string, enum: none|token-forwarding|correlation-header, default: none) to AgentRuntimeSpec in kagenti-operator api/v1alpha1/agentruntime_types.go. This is a top-level `spec.oboMode` field, NOT under a `spec.arc` section.
- [ ] T005 Add `MCP` struct with `Servers []MCPServerRef` to AgentRuntimeSpec in kagenti-operator api/v1alpha1/agentruntime_types.go. MCPServerRef has `Name`, `URL` (direct), `Type` + `Ref` (symbolic). Top-level `spec.mcp.servers[]` field.
- [ ] T006 Add ARC status conditions to AgentRuntime status types: `ContractReady`, `MCPResolutionFailed`, `OBOModeNotSupported`, `UnsupportedTargetType` in kagenti-operator api/v1alpha1/agentruntime_types.go
- [ ] T007 Run controller-gen to regenerate CRD manifests in kagenti-operator config/crd/bases/ and deepcopy in api/v1alpha1/zz_generated.deepcopy.go
- [ ] T008 Update webhook Pod mutator to inject `ARC_CONTRACT_VERSION`, `ARC_AGENT_ID`, `ARC_NAMESPACE`, `ARC_MCP_CONFIG`, `ARC_SKILLS_DIR` env vars in kagenti-operator internal/webhook/pod_mutator.go
- [ ] T009 [P] Update webhook Pod mutator to inject `SERVICE_BINDING_ROOT` env var (default `/bindings`) in kagenti-operator internal/webhook/pod_mutator.go
- [ ] T010 Update webhook Pod mutator to add `/arc/AGENTS.md` and `/arc/mcp/servers.json` ConfigMap volume mounts (subPath) in kagenti-operator internal/webhook/pod_mutator.go. Standard ConfigMap volume mount blocks Pod scheduling until ConfigMap exists.
- [ ] T011 Add conditional `OTEL_EXPORTER_OTLP_ENDPOINT` injection: read tracing config from namespace annotations or platform-level config (NOT from a CRD field), in kagenti-operator internal/webhook/pod_mutator.go
- [ ] T012 [P] Update webhook Pod mutator to configure `livenessProbe` and `readinessProbe` fields on the agent container using paths from AgentRuntime CR or defaults, in kagenti-operator internal/webhook/pod_mutator.go
- [ ] T013 Update RBAC ClusterRole to grant controller permissions for ConfigMap create/update/delete in kagenti-operator config/rbac/role.yaml
- [ ] T014 Implement target type validation: if `spec.targetRef.kind` is `Sandbox` or has `openshell.ai/managed-by` annotation, set `UnsupportedTargetType` status condition with message "Sandbox target type not yet supported in v1alpha1". In kagenti-operator internal/controller/agentruntime_controller.go
- [ ] T015 Implement OBO mode validation: if `spec.oboMode` is `token-forwarding` or `correlation-header`, set `OBOModeNotSupported` status condition with message "OBO mode not yet implemented in v1alpha1". In kagenti-operator internal/controller/agentruntime_controller.go

**Checkpoint**: CRD extended with top-level fields, webhook injects ARC env vars and volume mounts, deferred features rejected with status conditions.

---

## Phase 3: MCP Resolver Framework

**Purpose**: Build the resolver plugin architecture before MCP server discovery tasks can use it.

**Target repo**: kagenti-operator

- [ ] T016 Implement `ResolverRegistry` with `RegisterResolver(name, factory)` following the authbridge plugin pattern (`init()` + blank imports), in kagenti-operator internal/controller/arc/resolver/registry.go
- [ ] T017 Define `Resolver` interface: `Name() string`, `Resolve(ctx, ServerRef) (*ServerEntry, error)` in kagenti-operator internal/controller/arc/resolver/types.go
- [ ] T018 Implement `direct` resolver: URL passthrough, returns ServerEntry from MCPServerRef.URL, in kagenti-operator internal/controller/arc/resolver/direct/resolver.go with `init()` registration
- [ ] T019 Implement `label` resolver: discovers Deployments with `kagenti.io/protocol=mcp` in agent's namespace via label selector, returns ServerEntry per Service, in kagenti-operator internal/controller/arc/resolver/label/resolver.go with `init()` registration
- [ ] T020 Wire resolvers into operator main.go via blank imports: `_ "internal/controller/arc/resolver/direct"` and `_ "internal/controller/arc/resolver/label"`

**Checkpoint**: Resolver framework operational. Direct and label resolvers registered at build time.

---

## Phase 4: User Story 1 - Agent Developer Discovers Platform Capabilities (P1) MVP

**Goal**: Every managed agent Pod has `/arc/AGENTS.md` mounted with the full contract.

**Independent Test**: Deploy agent to Kind, exec into Pod, verify `/arc/AGENTS.md` exists with correct contract version, env var table, mount paths, and auth behavior sections.

**Target repo**: kagenti-operator

- [ ] T021 [US1] Create AGENTS.md Go template engine in kagenti-operator internal/controller/arc/agents_md.go: function that takes AgentRuntime CR + cluster config and renders the AGENTS.md template with YAML frontmatter and all body sections. Target type derived from `spec.targetRef.kind`. Contract version from platform config. Tracing from namespace annotations.
- [ ] T022 [US1] Create ConfigMap builder in kagenti-operator internal/controller/arc/configmap.go: function that wraps rendered AGENTS.md into a `<agent>-arc-contract` ConfigMap with ownerReference to AgentRuntime CR
- [ ] T023 [US1] Add AGENTS.md ConfigMap generation to AgentRuntime controller reconcile loop in kagenti-operator internal/controller/agentruntime_controller.go: on AgentRuntime create/update, generate and apply the contract ConfigMap. Set `ContractReady` status condition on success.
- [ ] T024 [US1] Implement credential redaction in AGENTS.md generation: env var table shows retrieval instructions (file paths under `$SERVICE_BINDING_ROOT`) instead of cleartext values, in kagenti-operator internal/controller/arc/agents_md.go

**Checkpoint**: Agent Pod has `/arc/AGENTS.md` with full contract. AI-native agents can read and self-configure.

---

## Phase 5: MCP Server Discovery (US7 partial)

**Goal**: `/arc/mcp/servers.json` populated from `spec.mcp.servers[]` (resolved via plugins) + platform defaults.

**Independent Test**: Deploy agent with `spec.mcp.servers` listing a direct URL. Verify `/arc/mcp/servers.json` contains the entry. Deploy MCP tool with `kagenti.io/protocol=mcp` label, verify it appears via label resolver.

**Target repo**: kagenti-operator

- [ ] T025 [US7] Implement servers.json generation: resolve `spec.mcp.servers[]` entries via ResolverRegistry (direct URL entries via direct resolver, symbolic refs via their typed resolver), merge with platform-level MCP defaults (gateway URL from operator config or namespace annotation), build JSON. In kagenti-operator internal/controller/arc/servers_json.go
- [ ] T026 [US7] Implement partial resolution: when a resolver fails (plugin not registered, resolution error, timeout), log warning, skip the entry, set `MCPResolutionFailed` status condition on AgentRuntime CR listing unresolved references. Note unresolved refs in AGENTS.md. In kagenti-operator internal/controller/arc/servers_json.go
- [ ] T027 [US7] Create `<agent>-arc-mcp` ConfigMap with ownerReference and mount at `/arc/mcp/servers.json` as subPath, in kagenti-operator internal/controller/arc/configmap.go
- [ ] T028 [US7] Handle empty state: generate `{"mcpServers": {}}` when no entries resolved and no platform defaults configured, in kagenti-operator internal/controller/arc/servers_json.go
- [ ] T029 [US7] Add watch for Deployments with `kagenti.io/protocol=mcp` label changes and AgentRuntime CR changes to trigger MCP ConfigMap regeneration, in kagenti-operator internal/controller/agentruntime_controller.go

**Checkpoint**: MCP discovery works with resolver framework. Agents read servers.json to find gateway and individual tools. Partial resolution handles failures gracefully.

---

## Phase 6: User Story 2 - Transparent Auth (P1) + User Story 4 - Contract Versioning (P2)

**Goal**: Auth is transparent. Contract version is consistent. AGENTS.md documents both.

**Can run in parallel with Phase 5.**

- [ ] T030 [US2] Ensure existing webhook injects `HTTP_PROXY`, `HTTPS_PROXY`, `SPIFFE_ENDPOINT_SOCKET` env vars correctly for Deployment/StatefulSet targets. Verify no gaps in kagenti-operator internal/webhook/pod_mutator.go
- [ ] T031 [US2] Ensure AGENTS.md auth behavior section accurately documents: inbound (sidecar terminates TLS), outbound (proxy presents SVID), agent-to-agent (mTLS), user-to-agent (JWT validation) in kagenti-operator internal/controller/arc/agents_md.go
- [ ] T032 [P] [US2] Add SPIFFE identity binding under `$SERVICE_BINDING_ROOT/identity/` with type file (`spiffe`), mapping existing SPIRE CSI volume outputs (cert, key, bundle) to ServiceBinding convention paths in kagenti-operator internal/webhook/pod_mutator.go
- [ ] T033 [US4] Implement contract version injection: `ARC_CONTRACT_VERSION` env var value matches AGENTS.md frontmatter `contract_version` field, sourced from platform-level config (operator flag or ConfigMap). In kagenti-operator internal/controller/arc/agents_md.go and internal/webhook/pod_mutator.go
- [ ] T034 [US4] Implement target type rejection for unsupported types: controller sets error status condition with message listing the unsupported type and supported alternatives (Deployment, StatefulSet), in kagenti-operator internal/controller/agentruntime_controller.go

**Checkpoint**: Auth is transparent. Contract version is consistent across env var and AGENTS.md.

---

## Phase 7: Skills Mount Convention + AgentRuntime Config Regeneration (US7)

**Goal**: Skills mount at `/arc/skills/<name>/` by default. ConfigMaps regenerate on relevant changes.

- [ ] T035 [US7] Make `mountPath` optional in `spec.skills[]`: when omitted, default to `/arc/skills/<name>/`. Skill names must be unique within an AgentRuntime. In kagenti-operator internal/webhook/pod_mutator.go or internal/controller/agentruntime_controller.go
- [ ] T036 [US7] Implement ConfigMap regeneration on AgentRuntime CR changes: controller watches AgentRuntime updates and regenerates AGENTS.md and servers.json ConfigMaps, in kagenti-operator internal/controller/agentruntime_controller.go
- [ ] T037 [US7] Document OBO mode in AGENTS.md: for `spec.oboMode: none` (the only implemented mode), generate "client-credentials" section. For deferred modes, the status condition already blocks. In kagenti-operator internal/controller/arc/agents_md.go

**Checkpoint**: Full v1alpha1 operator feature set. Skills default mount path works. ConfigMaps regenerate.

---

## Phase 8: Backend + Helm Integration

**Purpose**: Python backend and Helm charts updated to use the new CRD fields.

**Target repo**: kagenti (this repo)

- [ ] T038 Update `_build_agentruntime_manifest()` to include `spec.oboMode` (string, default "none") and `spec.mcp.servers[]` (list from API request) in kagenti/backend/app/routers/agents.py. No `spec.arc` section.
- [ ] T039 [P] Add ARC-related values to charts/kagenti/values.yaml: `arcContractVersion` (default "v1alpha1"), `mcpGateway.url` (optional, platform-level MCP default)
- [ ] T040 [P] Add MCP server configuration options to agent creation API: accept `mcpServers` list in create/update agent request body in kagenti/backend/app/routers/agents.py, pass through to `spec.mcp.servers[]`
- [ ] T041 Bump kagenti-operator chart version in charts/kagenti/Chart.yaml to require ARC-enabled operator

**Checkpoint**: End-to-end flow works: UI/API creates agent with MCP servers, operator injects contract.

---

## Phase 9: Polish and Validation

**Purpose**: Documentation, validation, and cleanup.

- [ ] T042 [P] Update docs/kagenti-agent-identity-architecture.md to reference ARC and the `/arc/` mount convention
- [ ] T043 [P] Update docs/components.md to document ARC as a platform component
- [ ] T044 Validate quickstart.md scenarios on a Kind cluster: deploy agent, read AGENTS.md, use MCP servers, verify auth
- [ ] T045 Run pre-commit checks on all changed files in this repo

---

## Stretch Goals (not blocking v1alpha1)

- [ ] T-S1 [US6] Create `$SERVICE_BINDING_ROOT/model-access/` binding directory with type file (`model`), projected from model endpoint Secret in kagenti-operator internal/webhook/pod_mutator.go
- [ ] T-S2 [US6] Create `$SERVICE_BINDING_ROOT/trace-collector/` binding directory with type file (`otel`), projected from OTEL collector config in kagenti-operator internal/webhook/pod_mutator.go

---

## Dependencies and Execution Order

### Phase Dependencies

- **Phase 1 (Setup)**: No dependencies, start immediately
- **Phase 2 (CRD + Webhook)**: Depends on Phase 1 (templates defined)
- **Phase 3 (Resolver Framework)**: Depends on Phase 2 (CRD types defined)
- **Phase 4 (US1 AGENTS.md)**: Depends on Phase 2 (webhook mounts ConfigMap)
- **Phase 5 (MCP Discovery)**: Depends on Phase 3 (resolver framework) + Phase 2
- **Phase 6 (Auth + Versioning)**: Depends on Phase 2. Can run in parallel with Phases 4-5.
- **Phase 7 (Skills + Regen)**: Depends on Phase 4 (AGENTS.md generation exists)
- **Phase 8 (Backend + Helm)**: Depends on Phase 2 (CRD extended)
- **Phase 9 (Polish)**: Depends on all prior phases

### Cross-Repo Sequencing

1. **kagenti-operator**: Phases 2-7 (CRD, webhook, resolver, controller)
2. **kagenti**: Phase 8 (backend + Helm), Phase 9 (docs)
3. Operator must be released and chart version bumped before end-to-end validation

### MVP (User Story 1 Only)

1. Phase 1 (templates) + Phase 2 (CRD + webhook) + Phase 4 (AGENTS.md generation)
2. Deploy agent on Kind, exec into Pod, verify `/arc/AGENTS.md`
3. This alone delivers the core value: agents can read their contract

---

## Notes

- [P] tasks = different files, no dependencies
- [Story] label maps task to specific user story for traceability
- NO `spec.arc` section in the CRD. ARC is the concept; per-agent fields are `spec.oboMode` and `spec.mcp.servers[]`. Everything else is derived.
- Cross-repo tasks are tagged with target repo in description
- Operator changes (Go) must be released before backend/Helm changes can be validated end-to-end
