# ADR-0001: Agent Runtime Contract (ARC)

|                |            |
| -------------- | ---------- |
| Date           | 2026-05-13 (updated 2026-06-12) |
| Scope          | Kagenti Operator, Webhook, AgentRuntime CRD, Agent Container Interface |
| Status         | Draft |
| Authors        | [Roland Huss](https://github.com/rhuss) |
| Supersedes     | N/A |
| Superseded by  | N/A |
| Tickets        | [RHAIRFE-2389](https://redhat.atlassian.net/browse/RHAIRFE-2389), [RHAISTRAT-1952](https://redhat.atlassian.net/browse/RHAISTRAT-1952) |

## What

Define a versioned contract between the Kagenti platform and agent containers. The contract specifies what the platform injects into every managed agent Pod (environment variables, volume mounts, identity, proxy configuration) and what agents must expose in return (A2A agent card, health probes). The contract materializes as an [AGENTS.md](https://agents.md/) file mounted at `/arc/AGENTS.md` inside every managed Pod, conforming to the AGENTS.md open standard with ARC-specific YAML frontmatter extensions.

The contract is called ARC, short for Agent Runtime Contract. Its initial version is `v1alpha1`.

## Why

### The Invisible Contract Problem

Every sidecar decision we have made over the past six months implicitly defined parts of an unwritten contract. When the webhook started injecting `HTTP_PROXY`, that created an expectation: agents should route outbound traffic through the proxy. When the SPIRE CSI driver started mounting X.509 SVIDs, that created another: agents can find their identity at a known socket path. When AuthBridge started intercepting inbound requests, that created a third: agents receive plain HTTP because the sidecar already handled TLS.

None of these expectations are documented in a place the agent can read. They exist in Slack threads, in the webhook source code, in Helm chart comments, and in the heads of the three people who built the sidecar stack. An agent developer deploying a new container today has two options: read the operator code, or ask on Slack. Neither scales.

The problem gets worse as Kagenti matures. Every time we change the sidecar model (adding a new env var, renaming a mount path, changing what `HTTP_PROXY` points to), we risk breaking agents that assumed the old behavior. Without a contract, there is no way to know what assumptions exist, no migration path to offer, and no version to bump.

### Why a Contract, Not Documentation

Documentation describes the system. A contract defines the interface.

The distinction matters because a contract is testable, versionable, and enforceable. You can write a test that verifies the contract is satisfied. You can bump the version when the contract changes. You can reject an agent that doesn't meet its obligations. Documentation gives you none of these properties.

More concretely: the contract lives inside the running container. It is not a wiki page the developer reads once and forgets. It is a file at a known path (`/arc/AGENTS.md`) that the agent can read at startup, parse programmatically, and use to self-configure. An AI-native agent (Claude Code running inside an OpenShell Sandbox, or an OpenClaw agent bootstrapping itself) can read the contract and know, without any hardcoded knowledge, what the platform provides and what the platform expects.

The pattern is straightforward: talk to localhost, complexity is behind the scenes, and the contract tells you what's behind the scenes.

### Why Now

The ARC emerged from three converging pressures in Sprint 5:

**First**, the OBO delegation gap surfaced as a concrete blocker. Tracing the token exchange plugin end-to-end (#kagenti-identity, May 12) revealed that no major agent framework (Claude Code, LangChain, CrewAI, OpenClaw) carries the inbound user token through to outbound requests. The sidecar's token exchange waits for a `subject_token` that nobody provides. Solving this requires the agent to know what headers to forward and what the sidecar does with them. Without a contract, there is no standard way to communicate this. The thread concluded with a clear recommendation: "We would need to document this well, and drive toward ARC, what we inject and what we require."

**Second**, the AgentOps strategy discussion (#agentops-leads, May 5-10) identified ARC as a key differentiator. The review of kagent's inheritance model versus Kagenti's composition model confirmed that our value lies in augmenting existing workloads, not owning them. The ARC makes composition concrete: the platform injects capabilities, the contract documents what's available, and the agent opts in to what it needs. The consensus was direct: "Let's focus on the Agent Runtime Contract with Service/Agent Bindings and AgentMesh as a decentralized way to connect agents."

**Third**, the contract concept had been building across multiple channels since early May. The initial ARC proposal (#team-rh-ai-agent-ops, May 8) laid out the env vars, mount paths, and agent requirements. The team agreed it should be a Sprint 5 spike alongside the sidecar model decision, because the contract defines what the proxy (whatever form it takes) must provide to the agent container. Separately, the need for a platform contract had been raised in the context of agent deployment requirements (#agentops-leads, Feb 23): "I think we need to work on our platform contract. For the platform to serve the agent well, what does the platform need from the agent developer."

## Forces and Constraints

1. **Contract completeness vs. implementation velocity.** A comprehensive contract takes longer to define but prevents rework. An incomplete contract ships faster but creates ambiguity that agents must resolve at runtime. Completeness wins here because the contract is the foundation for every feature that follows (OBO, MCP discovery, skills projection). Getting the foundation wrong is more expensive than getting it late.

2. **Single file vs. multiple files.** Putting the entire contract in one AGENTS.md file is simple to discover but limits machine parseability. Splitting across multiple files (AGENTS.md, servers.json, skills/) adds complexity but lets each file serve its audience (Markdown for humans and LLMs, JSON for programmatic tools). The answer is a hybrid: a single `/arc/` root directory with AGENTS.md as the entry point and structured data files alongside it.

3. **Kagenti-specific env vars vs. standard names.** Inventing new variable names (like `KAGENTI_CONTRACT_VERSION`) creates a clean namespace but ignores existing conventions. Reusing standard names (like `HTTP_PROXY`, `OTEL_EXPORTER_OTLP_ENDPOINT`) preserves compatibility but mixes Kagenti-managed and externally-managed variables. We split the difference: Kagenti-invented variables get an `ARC_` prefix, standard variables keep their established names.

4. **AGENTS.md standard conformance vs. custom format.** The [AGENTS.md open standard](https://agents.md/) (Linux Foundation, Agentic AI Foundation) is adopted by 60,000+ repositories and supported by Claude Code, Codex CLI, Gemini CLI, Cursor, and Copilot. Conforming to it means AI coding agents discover the contract automatically. Deviating means building custom discovery. Conformance is the obvious choice. ARC-specific metadata goes in YAML frontmatter as extension fields, which the standard explicitly supports as forward-compatible.

5. **MCP Gateway vs. individual MCP servers.** The MCP Gateway (built on Envoy/Kuadrant) aggregates all registered MCP servers behind a single broker URL. But agents also need direct access to sidecar-local tools and individually deployed servers. Both models belong in a single discovery file (`/arc/mcp/servers.json`), using the `mcpServers` JSON format. This format is a de facto standard across the MCP ecosystem, used by Claude Code, Claude Desktop, Cursor, Windsurf, Gemini, LM Studio, and ToolHive for MCP client configuration.

6. **Dedicated ARC section in CRD vs. derivation from existing config.** A dedicated `spec.arc` section on AgentRuntime would centralize ARC config but duplicates information the controller can derive from existing sources: target type from `spec.targetRef.kind`, tracing from namespace-level config, contract version from the platform. Derivation is cleaner. The controller assembles the contract from multiple inputs rather than requiring the user to restate them. The one per-agent choice that does belong in the spec is OBO delegation mode (`spec.oboMode`), because it controls sidecar behavior for token forwarding vs. exchange.

Design constraints (not tensions):
- The webhook is the existing injection mechanism (mutating admission webhook in kagenti-operator).
- The controller already reconciles AgentRuntime CRs and will be extended, not replaced.
- SPIRE is the identity provider. SPIFFE X.509 SVIDs are projected via CSI driver.
- ServiceBinding conventions are adopted (directory structure, env var name) without requiring the ServiceBinding Operator.

## Goals

- Define a versioned contract (`v1alpha1`) between the Kagenti platform and agent containers
- Mount the contract as `/arc/AGENTS.md` (conforming to the AGENTS.md open standard) in every managed agent Pod
- Generate target-specific contract content (Deployment vs. Sandbox vs. StatefulSet)
- Provide MCP server discovery via `/arc/mcp/servers.json` using the standard `mcpServers` format
- Derive ARC content from existing configuration sources (target type, namespace config, platform config) rather than requiring a dedicated ARC section in the CRD
- Regenerate contract ConfigMaps automatically when platform configuration changes
- Enable AI-native agents to self-configure from the contract without hardcoded platform knowledge

## Non-Goals

- Defining the sidecar implementation details (how envoy-proxy terminates TLS, how SPIFFE helper fetches SVIDs)
- Building the MCP Gateway (separate project, see [MCP Gateway on OpenShift](https://docs.google.com/document/d/1liziAy55qQBd80qRN63WTZjhu5mJRQ4-OlogP_edftQ/edit))
- Defining adapter base images or certified framework images (product decision, not architecture)
- Cross-project contract governance (start Kagenti-owned, propose shared governance with OpenShell later)
- Implementing the OBO token exchange in the sidecar (ARC defines what the agent sees; the exchange mechanism is a sidecar concern)
- Replacing the existing AuthBridge ConfigMaps (those remain for sidecar configuration; ARC adds agent-facing documentation)

## How

### The `/arc/` Directory

All ARC-managed content lives under a single root directory mounted into every managed agent Pod:

```
/arc/
  AGENTS.md            # Contract file (YAML frontmatter + Markdown body)
  mcp/
    servers.json       # MCP server discovery (standard mcpServers format)
  skills/              # Skill artifacts (populated by init container)
```

The webhook injects this as a composite volume mount. `AGENTS.md` and `mcp/servers.json` are backed by controller-generated ConfigMaps. `skills/` is an emptyDir populated by an init container.

Credentials live outside `/arc/`, under `$SERVICE_BINDING_ROOT` (default `/bindings/`), following the [ServiceBinding Specification v1.1.0](https://servicebinding.io/spec/core/1.1.0/) conventions. Kagenti adopts the convention (directory structure, `type` file per binding, `SERVICE_BINDING_ROOT` env var) without requiring the ServiceBinding Operator. The kagenti-operator controller creates the projected files and the webhook mounts them. Agents built for any ServiceBinding-compatible platform can read Kagenti-projected credentials without modification. The reverse also holds.

Why keep credentials outside `/arc/`? The contract describes how to find credentials, but the credentials themselves follow an independent, portable standard. Mixing them into `/arc/` would couple the contract's lifecycle with credential rotation, and it would break the ServiceBinding convention that other platforms depend on.

### Environment Variables

The webhook injects two categories of environment variables:

**ARC-prefixed (Kagenti-invented):**

| Variable | Value | Purpose |
|----------|-------|---------|
| `ARC_CONTRACT_VERSION` | `v1alpha1` | Contract version |
| `ARC_AGENT_ID` | SPIFFE ID | Agent identity |
| `ARC_NAMESPACE` | Pod namespace | Agent namespace |
| `ARC_MCP_CONFIG` | `/arc/mcp/servers.json` | MCP server config path |
| `ARC_SKILLS_DIR` | `/arc/skills/` | Skills directory path |

**Standard (well-known, unmodified):**

| Variable | Value | Purpose |
|----------|-------|---------|
| `HTTP_PROXY` / `HTTPS_PROXY` | Sidecar endpoint | Outbound proxy |
| `SPIFFE_ENDPOINT_SOCKET` | CSI mount path | SPIRE Workload API |
| `SERVICE_BINDING_ROOT` | `/bindings` | ServiceBinding root |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | Collector URL | Tracing (conditional) |

The `ARC_` prefix eliminates naming collisions and makes Kagenti-originated variables instantly identifiable. `grep ARC_` in a Pod's environment shows exactly what the platform injected.

### AGENTS.md Format

The contract file conforms to the [AGENTS.md open standard](https://agents.md/) with ARC-specific YAML frontmatter. The frontmatter fields are extension fields. Standard AGENTS.md tooling ignores them (the spec requires forward-compatible handling of unrecognized fields). ARC-aware tooling reads them for programmatic contract inspection.

No cleartext credentials appear anywhere in the file. Credential entries describe how to retrieve them from ServiceBinding paths.

Here is an abbreviated example for a Deployment target with tracing enabled and no OBO delegation. The full rendered contract is in [agents-md-format.md](../specs/001-agent-runtime-contract/contracts/agents-md-format.md).

````markdown
---
arc_version: v1alpha1
target_type: Deployment
obo_mode: none
tracing_enabled: true
bindings: [identity, model-access, trace-collector]
---

# Agent Runtime Contract

**Version**: v1alpha1 | **Target**: Deployment | **Generated**: 2026-06-12T10:00:00Z

## Platform-Provided Environment Variables

| Variable | Value | Description |
|----------|-------|-------------|
| `ARC_CONTRACT_VERSION` | `v1alpha1` | Contract version |
| `ARC_AGENT_ID` | `spiffe://kagenti.local/ns/team1/sa/weather-agent` | Your SPIFFE identity |
| `HTTP_PROXY` | `http://127.0.0.1:15001` | Route all outbound HTTP through this |
| ... | | *(10 variables total, see [format spec](../specs/001-agent-runtime-contract/contracts/agents-md-format.md))* |

## Agent Requirements

Your container MUST expose: A2A agent card (`GET /.well-known/agent-card.json`),
liveness probe, readiness probe.

*(Full contract includes: mount paths, auth behavior with inbound/outbound/OBO
scenarios, MCP server discovery via `/arc/mcp/servers.json`, credential paths
under `$SERVICE_BINDING_ROOT`. See [agents-md-format.md](../specs/001-agent-runtime-contract/contracts/agents-md-format.md).)*
````

### Target-Specific Generation

The controller detects the target type from the AgentRuntime CR's `spec.targetRef.kind` and generates different AGENTS.md content:

| Target | Detection | Contract Differences | v1alpha1 |
|--------|-----------|---------------------|----------|
| Deployment | `kind: Deployment` | Full sidecar stack: proxy, SPIFFE CSI, all env vars. Auth section documents mTLS + JWT. | In scope |
| StatefulSet | `kind: StatefulSet` | Same as Deployment (identical PodTemplateSpec injection). Additional note about PVC persistence. | In scope |
| Sandbox | `kind: Sandbox` or `openshell.ai/managed-by` annotation | Light injection: OTEL env vars only. Auth section: "identity managed by OpenShell supervisor." No proxy sidecar. | Deferred |

Deployment and StatefulSet receive identical treatment from the ARC injection perspective since both use PodTemplateSpec. The distinction between them is a documentation detail, not an injection difference.

Sandbox support is deferred from v1alpha1. The controller recognizes Sandbox target types (via `kind: Sandbox` or the `openshell.ai/managed-by` annotation) but rejects them with an `UnsupportedTargetType` status condition. This is preferable to silent ignoring: the operator communicates clearly that the target type is known but not yet supported.

The agent reads the same path (`/arc/AGENTS.md`) regardless of target type. The content reflects what is actually available in the current environment.

### MCP Server Discovery

The file at `/arc/mcp/servers.json` uses the standard `mcpServers` format with Kagenti extensions for transport and auth hints:

```json
{
  "mcpServers": {
    "gateway": {
      "url": "http://mcp-gateway-broker.mcp-system:8080/mcp",
      "transport": "streamable-http"
    },
    "weather-tool": {
      "url": "http://weather-tool-service.team1:8080/mcp",
      "transport": "streamable-http"
    }
  }
}
```

Each entry requires a `url` and may include `transport` (e.g., `streamable-http`) and `auth` (type and credential reference, never cleartext). Standard MCP clients ignore the extended fields; ARC-aware agents can use them for transport selection and auth bootstrapping.

The controller assembles `servers.json` from three sources: direct URL entries declared in `spec.mcp.servers[]`, symbolic references resolved by plugins, and platform-level defaults (MCP Gateway URL from operator config or namespace annotation). When no servers are available, the file contains `{"mcpServers": {}}`, never omitted entirely.

#### Resolver Plugin Architecture

MCP server references in the AgentRuntime CR can be direct URLs or symbolic names that the operator resolves at reconciliation time:

```yaml
spec:
  mcp:
    servers:
      - name: "weather-tool"
        url: "http://weather-tool-service.team1:8080/mcp"     # direct
      - name: "github-mcp"
        type: "catalog"
        ref: "github-mcp-server"                               # symbolic
```

Symbolic references are resolved by a plugin framework that follows the same pattern as the AuthBridge plugin architecture in kagenti-extensions: a Go `ResolverRegistry` with `RegisterResolver(name, factory)`, resolver implementations in their own packages with `init()` registration, and build-time selection via blank imports. This is the `database/sql.Register` pattern.

Upstream ships two resolvers: `direct` (URL passthrough) and `label` (in-namespace discovery via `kagenti.io/protocol=mcp` label selector). Midstream and downstream builds add resolvers for their infrastructure (MCP Gateway lookup, RHOAI catalog query) by adding blank imports to the operator binary. No upstream code changes required. No external webhook calls during reconciliation.

#### Partial Resolution

When a symbolic reference fails to resolve (plugin not registered, catalog entry not found, resolution timeout), the controller does not block the agent. It generates `servers.json` with only the successfully resolved entries, sets an `MCPResolutionFailed` status condition on the AgentRuntime CR listing what failed and why, and notes the unresolved references in AGENTS.md. The agent Pod starts and operates with whatever resolved.

This trade-off favors availability over completeness. An agent that needs three MCP servers and gets two is more useful than an agent stuck in Pending because the third couldn't resolve. The status condition makes the gap visible to operators and tooling.

### ARC Configuration: Derived, Not Declared

There is no dedicated `spec.arc` section in the AgentRuntime CRD. The controller derives the contract content from existing configuration sources:

| ARC concern | Source | How derived |
|-------------|--------|-------------|
| Target type | `spec.targetRef.kind` | Already in AgentRuntime spec |
| OBO delegation mode | `spec.oboMode` | New field, per-agent choice (controls sidecar token behavior) |
| MCP servers | `spec.mcp.servers[]` | New field, per-agent choice (which MCP servers to expose) |
| Tracing | Namespace annotation or platform config | `kagenti.io/tracing: enabled` on namespace, or platform-level OTEL config |
| Contract version | Platform-level config | Operator flag or ConfigMap. Same for all agents on the platform. |

Two new CRD fields capture per-agent choices. `spec.oboMode` controls sidecar behavior for token forwarding vs. exchange. `spec.mcp.servers[]` declares which MCP servers should be available to this agent (direct URLs or symbolic references resolved by plugins). Everything else is derived from existing sources.

```yaml
apiVersion: agent.kagenti.dev/v1alpha1
kind: AgentRuntime
metadata:
  name: my-agent
  namespace: team1
spec:
  type: agent
  targetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: my-agent
  oboMode: "none"               # "none" (default) | "token-forwarding" | "correlation-header"
  mcp:
    servers:
      - name: "weather-tool"
        url: "http://weather-tool-service.team1:8080/mcp"
      - name: "github-mcp"
        type: "catalog"
        ref: "github-mcp-server"
```

The controller reads `spec.targetRef.kind`, `spec.oboMode`, `spec.mcp.servers[]`, namespace annotations, and platform config during reconciliation. It assembles these into the AGENTS.md content, the servers.json content, and the appropriate webhook injection configuration. Platform-level MCP defaults (MCP Gateway URL from operator config or namespace annotation) are merged into every agent's servers.json automatically, without requiring per-agent declaration.

### Contract Versioning

The contract is versioned from day one. `v1alpha1` signals that the interface is expected to evolve.

**Version bump rules:**
- Adding new env vars or mount paths: no version bump required
- Renaming or removing existing env vars/paths: version bump required, migration path documented in AGENTS.md
- Changing semantics (e.g., what `HTTP_PROXY` points to): version bump required

`ARC_CONTRACT_VERSION` is injected as an env var and stated in the AGENTS.md frontmatter. Both always match. An agent can check the version at startup and fail fast if it doesn't support the contract version.

### ConfigMap Lifecycle

The controller generates two ConfigMaps per AgentRuntime CR:

- `<agent>-arc-contract`: contains the rendered AGENTS.md
- `<agent>-arc-mcp`: contains servers.json

Both have ownerReferences to the AgentRuntime CR, so they cascade-delete when the agent is removed.

The webhook mounts these ConfigMaps as standard volume mounts. Kubernetes blocks Pod scheduling until referenced ConfigMaps exist, so the agent container never starts without its contract. No init container or readiness polling is needed.

The controller regenerates these ConfigMaps when:
- The AgentRuntime CR is created or updated (including `spec.mcp.servers[]` changes)
- MCP tool Deployments (label `kagenti.io/protocol=mcp`) are added or removed
- Platform-level configuration changes (tracing config, contract version, MCP Gateway URL)
- MCP resolver resolution changes (a previously-failing reference starts resolving)

Kubernetes propagates ConfigMap updates to mounted volumes via kubelet sync (typically within one minute). No Pod restart is required.

### OBO Delegation (Opt-In)

Two mechanisms, both optional. Agents that don't participate get client-credentials auth (the agent's own SPIFFE identity) by default.

**Token forwarding** (`spec.oboMode: token-forwarding`): The agent reads the inbound `Authorization` header and includes it on outbound requests. The sidecar intercepts the outbound request, extracts the forwarded token, and performs an RFC 8693 token exchange with the agent's identity as the actor. The AuthBridge sidecar's `token-exchange` plugin (in kagenti-extensions) already implements the RFC 8693 mechanics for this mode.

**Correlation header** (`spec.oboMode: correlation-header`): The agent forwards the `X-Kagenti-Request-Id` header (injected by the sidecar on inbound requests). The sidecar uses the correlation ID to look up the stored user token for outbound exchanges. This reduces security exposure because the agent never sees the actual user token. This mode requires new sidecar work (inbound token stashing, correlation-ID-based lookup) not yet present in AuthBridge.

The AGENTS.md documents which OBO mode is active and what the agent must do to participate. For `mode: none`, the OBO section states that outbound requests use the agent's own identity.

**v1alpha1 scope**: The `spec.oboMode` field is defined in the CRD with all three values for forward compatibility. Only `none` is implemented. Setting `token-forwarding` or `correlation-header` causes the controller to set an `OBOModeNotSupported` status condition. Token forwarding is a fast-follow since the sidecar support exists; correlation header requires more sidecar development.

### ServiceBinding Conventions

Credentials are projected as files under `$SERVICE_BINDING_ROOT` (default `/bindings/`), following [ServiceBinding spec v1.1.0](https://servicebinding.io/spec/core/1.1.0/):

| Path | Contents | Type File |
|------|----------|-----------|
| `identity/` | SPIFFE X.509 SVID (cert, key, bundle) | `spiffe` |
| `model-access/` | Model endpoint URL, API key, provider | `model` |
| `trace-collector/` | OTEL endpoint, sampling config | `otel` |

Each subdirectory contains a `type` file identifying the service category. This is a convention adoption, not a dependency. Kagenti does not require the ServiceBinding Operator. The directory structure and env var name follow the spec so that agents built for ServiceBinding-compatible platforms work on Kagenti without modification.

## Alternatives Considered

### A: Contract-first ADR with concrete paths (chosen)

Full contract in the ADR body: every env var, every mount path, every agent requirement, plus target detection logic and example AGENTS.md content per target type. Versioned as `v1alpha1`.

This is what you are reading. The thinking is done. The env vars, mount paths, auth model, target types, and AGENTS.md concept are discussed and largely agreed. A concrete ADR turns conversation into commitment.

The cost is a long ADR where every detail is debatable. The `v1alpha1` designation mitigates this: nothing here is set in stone. It is set in alpha.

### B: Layered ADR (decision body + appendix)

The ADR covers the "why" (architectural decisions). A separate appendix contains the concrete tables of env vars, paths, and formats.

Two documents. The appendix may be perceived as deferrable, and "deferrable" in practice means "never written." The concrete artifact is exactly what people need this week.

### C: Minimal ADR, defer to spec

Principles only. All concrete details go to a separate specification document.

Fastest to review. Least controversial. But it doesn't deliver the concrete artifact that customers need for OBO delegation, that the OpenShell integration needs for target-specific behavior, and that agent developers need to stop asking on Slack. Another review round for the spec adds weeks.

### D: No contract, document in the wiki

Write a "Platform Features for Agents" page on the wiki. No versioning, no machine-readable format, no in-container discovery.

This is what we have today. It doesn't work. The information is scattered, stale, and invisible to the agent at runtime.

## Open Questions

1. **Contract governance.** Long-term, the contract spec should live in its own repo, shared between Kagenti and OpenShell. This is the right direction but adds coordination overhead. For `v1alpha1`, the contract is Kagenti-owned. Cross-project governance is a proposal for a future ADR.

2. **Skills projection source.** The `/arc/skills/` mount path and directory structure are defined. The mechanism for downloading skills into that directory (MLflow registry, OCI artifacts, Git clone) is not yet decided. The init container interface is stable; the source is pluggable.

3. **Adapter base images.** Certified base images (e.g., `registry.redhat.io/agent-base/claude-code:latest`) that come with ARC-aware configuration are a product decision. The ARC defines the interface that these base images would implement.

4. **AGENTS.md machine-readable companion.** The YAML frontmatter provides basic metadata for programmatic access. If non-LLM tooling needs richer structured data (full env var tables as JSON, complete mount path manifests), a companion `/arc/contract.json` could be added in a future version without changing the AGENTS.md format.

## References

- [AGENTS.md Open Standard](https://agents.md/) (Linux Foundation, Agentic AI Foundation)
- [ServiceBinding Specification v1.1.0](https://servicebinding.io/spec/core/1.1.0/)
- [ToolHive MCP Client Configuration](https://docs.stacklok.com/toolhive/guides-cli/client-configuration)
- [MCP Gateway on OpenShift](https://docs.google.com/document/d/1liziAy55qQBd80qRN63WTZjhu5mJRQ4-OlogP_edftQ/edit)
- [MCP Gateway Project](https://docs.google.com/document/d/1luG4uffBFIMnpQ26I7dHF4yA7pERLgLQJSZikMiPlZs/edit)
- [Agent Auth and Audience Models](https://docs.google.com/document/d/1HGAYq1u27sHVdifpvYU5rsAiB3PVSfJ0AGBXDtoCnYc/edit)
- [kagent vs Kagenti Comparison](https://docs.google.com/document/d/1Xvcc-UL0_cDWBXj9_eOv8pNgZkm5xUUbH0Q9kuziS4k/edit)
- [Kagenti: From Inheritance to Composition](https://docs.google.com/document/d/1puOWivXrQ29JlQ5ySq0zeXZTKnMJY0y_ApFPrh7N-Sg/edit)
- [ODH-ADR-AgentOps-0003: AgentMesh](https://docs.google.com/document/d/1MRKi6d2sswEb8Zh-sGJ7aZ6rIGXhxzWhXcnoUwGrqSc/edit)
- [OpenShell HTTP_PROXY approach](https://github.com/NVIDIA/OpenShell/issues/981)
- Slack: [ARC proposal (#team-rh-ai-agent-ops, May 8)](https://redhat-external.slack.com/archives/C089A7U0JGQ/p1778239381616079)
- Slack: [AgentOps strategy and ARC as differentiator (#agentops-leads, May 5)](https://redhat-external.slack.com/archives/C08BFNC3JRQ/p1777970367743339)
- Slack: [OBO delegation gap analysis (#kagenti-identity, May 12)](https://redhat-external.slack.com/archives/C0AFNRQSC22/p1778582588509819)
- Slack: [Agent deployment contract requirements (#agentops-leads, Feb 23)](https://redhat-external.slack.com/archives/C08BFNC3JRQ/p1771868568246789)

Author: Roland Huss [AIA HAb CeNc Hin R Claude Opus 4.6 v1.0](https://aiattribution.github.io/statements/AIA-HAb-CeNc-Hin-R-?model=Claude%20Opus%204.6-v1.0)
