# Brainstorm: Agent Runtime Contract (ARC)

**Date:** 2026-05-12
**Status:** active
**Participants:** Roland Huss, Adel Zaalouk, Dimitri Saridakis, Gordon Sim, Akram Ben Aissi, Hai Huang (via Slack threads)

## Problem Framing

Every sidecar decision (envoy vs lightweight proxy, iptables vs HTTP_PROXY, cert paths, env var names) implicitly defines parts of an unwritten contract between the Kagenti platform and the agent container. Without making this contract explicit, we risk:

- Breaking agent deployments when we change the sidecar model
- Different components (webhook, operator, authbridge) assuming different paths, ports, and env vars
- No documentation for agent developers on what to expect from the platform
- No way for AI-native agents (Claude Code, OpenClaw) to self-configure by reading what the platform provides

The Agent Runtime Contract (ARC) is the versioned specification of what the platform provides to agent containers and what agents must expose in return. It's the interface between the platform and the agent, regardless of which framework (LangChain, CrewAI, Claude Code, OpenClaw) runs inside the container.

## Context from Prior Discussions

The ARC concept emerged across several threads:

- **Roland's Slack post (May 5):** First formal proposal of the ARC, listing env vars, mounts, and agent requirements. Referenced ServiceBinding spec as inspiration.
- **Adel + Dimitri + Roland call (May 11):** Confirmed ARC as the #1 priority for Sprint 5. Adel: "You cannot build something as a black box without a contract." Compared to Dapr's model (talk to localhost, complexity handled by the sidecar).
- **Adel's doc "Musings on OpenShell, Kagenti, and the ARC" (May 11):** Detailed proposal including mount paths, env vars, certified adapter base images, and contract versioning. Proposed the contract should be unified across OpenShell and Kagenti.
- **Auth models analysis:** Defined the auth behavior visible to agents (plain HTTP inbound, HTTP_PROXY outbound, sidecar handles the rest).
- **Sunrise customer call (May 11):** Validated the need for Entra ID integration and OBO delegation, both of which require the ARC to define how identity and tokens reach the agent.
- **Kagenti Slack #kagenti (May 12):** Discussion of token forwarding for OBO scenarios. Consensus: the ARC should document this as an optional agent requirement, not a mandatory one.

## Approaches Considered

### A: Contract-first ADR with concrete paths and targets (chosen)

Full contract in the ADR body: every env var, every mount path, every agent requirement, plus target detection logic and example AGENTS.md content per target type. Versioned as `v1alpha1`.

- **Pros:** Implementable directly. No ambiguity. Delivers on the "something to read this week" commitment. Turns three days of conversation into a reviewable artifact.
- **Cons:** Long ADR. Every detail is debatable. Risk of premature commitment on specific names/paths (mitigated by `v1alpha1` designation).

### B: Layered ADR (decision body + appendix)

ADR covers the "why" (architectural decisions). A separate appendix contains the concrete tables.

- **Pros:** ADR stays focused on decisions. Appendix evolves independently.
- **Cons:** Two documents. The appendix may be perceived as deferrable.

### C: Minimal ADR, defer to spec

Principles only. All concrete details go to a separate spec.

- **Pros:** Fastest to review. Least controversial.
- **Cons:** Doesn't deliver the concrete artifact people need. Another review round for the spec.

## Decision

**Approach A.** The thinking is done. The env vars, mount paths, auth model, target types, and AGENTS.md concept are discussed and largely agreed. A concrete ADR turns conversation into commitment.

## Key Requirements

### ADR Format and Structure

- Format: `ODH-ADR-AgentOps-0004` using the same table-header structure as ADRs 0001-0003
- Voice: Use the prose plugin with a **reasoning** voice. The document should build a logical case while remaining a genuinely enjoyable read. Dense technical content, but with rhythm, opinions, and clear narrative flow. Not a dry spec sheet.

### What the Platform Provides (injected by webhook/sidecar)

**Environment variables:**

| Variable | Purpose | Provisioned by |
|----------|---------|---------------|
| `HTTP_PROXY` / `HTTPS_PROXY` | Proxy sidecar endpoint | Webhook injection |
| `SPIFFE_ENDPOINT_SOCKET` | SPIRE Workload API socket | CSI volume mount |
| `KAGENTI_AGENT_ID` | Agent identifier (SPIFFE ID) | Webhook injection |
| `KAGENTI_NAMESPACE` | Agent's namespace | Webhook injection |
| `KAGENTI_CONTRACT_VERSION` | ARC version (e.g., `v1alpha1`) | Webhook injection |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | OTEL collector endpoint | Webhook injection (when tracing enabled) |
| `PLATFORM_MCP_SERVERS` | JSON list of MCP server URLs | Controller (resolved from MCPServerRegistration CRs) |
| `SKILLS_DIR` | Path to mounted skills | Controller |
| `SERVICE_BINDING_ROOT` | ServiceBinding convention root (default: `/bindings`) | Webhook injection |

**Mount paths:**

| Path | Contents | Provisioned by |
|------|----------|---------------|
| `/arc/AGENTS.md` | Controller-generated ARC file, target-specific | Kagenti controller (ConfigMap volume) |
| `$SERVICE_BINDING_ROOT/identity/` | SPIFFE X.509 SVID (cert, key, trust bundle) | SPIRE CSI driver |
| `$SERVICE_BINDING_ROOT/model-access/` | Model endpoint URL, API key, provider type | Controller (from MaaS/AI Gateway config) |
| `$SERVICE_BINDING_ROOT/trace-collector/` | OTEL endpoint, sampling config | Controller |
| `/mnt/skills/` | Skill artifacts (downloaded from MLflow or OCI) | Init container |
| `/mnt/mcp/` | MCP server metadata | Controller |

### What the Agent Must Provide

| Requirement | Details |
|------------|---------|
| A2A agent card endpoint | `/.well-known/agent-card.json` on a discoverable port |
| Health probes | Liveness and readiness endpoints |
| Container port | Discoverable from Pod spec (convention: 8080) |

### Optional Agent Capabilities (opt-in via ARC)

**OBO delegation (token forwarding):**
Two mechanisms, both optional. Agents that don't participate get client-credentials auth (agent's own identity) instead of on-behalf-of delegation.

- **Token forwarding:** Agent reads the inbound `Authorization` header and includes it on outbound requests. The sidecar exchanges it (RFC 8693) with the agent's identity as the actor.
- **Correlation header:** Agent forwards the `X-Kagenti-Request-Id` header (injected by the sidecar on inbound). The sidecar uses it to look up the stored user token for outbound exchanges. Less security exposure than forwarding the actual token.

### AGENTS.md: Controller-Generated, Target-Specific

The file at `/arc/AGENTS.md` is generated by the Kagenti controller for each agent Pod. It contains:
- Contract version
- Available env vars and their current values (except credentials, which list retrieval instructions only)
- Available mount paths
- Auth behavior (what the sidecar does for inbound/outbound)
- Agent requirements (what endpoints to expose)
- Target-specific instructions

**No cleartext credentials.** The file describes *how* to retrieve credentials (e.g., "read from `$SERVICE_BINDING_ROOT/model-access/api-key`"), not the credentials themselves.

**Target types and detection:**

| Target | Detection | AGENTS.md differences |
|--------|-----------|----------------------|
| Vanilla Deployment | `spec.targetRef.kind: Deployment` | Full sidecar stack: proxy, SPIFFE CSI, OTEL env vars. Auth section describes mTLS + JWT paths. |
| OpenShell Sandbox | `spec.targetRef.kind: Sandbox` or `openshell.ai/managed-by` annotation | Light injection: OTEL env vars only. Auth section: "identity managed by OpenShell supervisor." No proxy sidecar injected. |
| StatefulSet | `spec.targetRef.kind: StatefulSet` | Same as Deployment. PVC persistence noted in the file. |

The set of supported targets and their detection rules are hardcoded in the Kagenti controller. Adding a new target type requires a controller code change, not configuration.

### Auth Model (from auth models analysis)

| Scenario | Mechanism | What the agent sees |
|----------|-----------|-------------------|
| Agent-to-agent | mTLS (SPIFFE X.509 SVID) | Plain HTTP inbound (sidecar terminated TLS). Outbound via HTTP_PROXY (sidecar presents SVID). |
| User-to-agent | JWT with shared audience + role check | Plain HTTP inbound (sidecar validated JWT). Agent doesn't handle tokens. |
| Agent-to-external | CONNECT tunnel via HTTP_PROXY | Agent sends request, sidecar tunnels to destination. |

The agent container receives plain HTTP on its port. It makes outbound requests through `HTTP_PROXY`. The sidecar handles all TLS, authentication, and token exchange. This is the Dapr model: talk to localhost, complexity is behind the scenes.

### Versioning

The contract is versioned from day one: `v1alpha1`. The version is injected as `KAGENTI_CONTRACT_VERSION` env var and stated in the AGENTS.md file.

Changes between versions:
- New env vars or mount paths can be added without a version bump
- Renaming or removing env vars/paths requires a version bump with a documented migration path
- Semantic changes (e.g., changing what `HTTP_PROXY` points to) require a version bump

### ServiceBinding Conventions

Follow the [ServiceBinding spec v1.1.0](https://servicebinding.io/spec/core/1.1.0/) conventions:
- `$SERVICE_BINDING_ROOT` as the standard directory (default: `/bindings`)
- Credentials projected as files in subdirectories (`identity/`, `model-access/`, `trace-collector/`)
- Each binding directory contains a `type` file identifying the service category

Don't take a hard dependency on the Service Binding Operator. Adopt the conventions (directory structure, env var name) so agents built for ServiceBinding work on Kagenti, and vice versa.

### OpenShell Compatibility

The ARC is designed to compose with OpenShell without requiring OpenShell-specific code in the controller:

- When `targetRef.kind: Sandbox`, the controller generates a light AGENTS.md (no proxy sidecar, identity managed by supervisor)
- The controller detects OpenShell-managed Pods via the `openshell.ai/managed-by` annotation and skips sidecar injection
- OTEL env vars are injected regardless of target type (both OpenShell and Kagenti agree on `OTEL_EXPORTER_OTLP_ENDPOINT`)

OpenShell's supervisor handles identity and proxy for sandboxed agents. Kagenti handles discovery, OTEL configuration, and MCP/skills projection. The AGENTS.md file reflects which system handles which concern for the current target.

## Open Questions

1. **Exact AGENTS.md format:** Markdown is human-readable and AI-readable. But should there also be a machine-parseable section (YAML frontmatter? JSON sidecar file?) for non-LLM tooling that needs to read the contract programmatically?

2. **Contract governance:** Adel's doc proposes the contract spec should live in its own repo, not in Kagenti or OpenShell. This is the right long-term direction but adds coordination overhead. For the ADR, start with Kagenti-owned and propose cross-project governance as a future step.

3. **MCP server metadata format:** `PLATFORM_MCP_SERVERS` as a JSON env var works for simple cases. For agents with many MCP servers, a file mount (`/mnt/mcp/servers.json`) may be more practical. The ADR should support both.

4. **Skills projection:** The `mlflow://` URI scheme for skills is aspirational. MLflow doesn't have a skills registry yet. The ADR should define the mount path and directory structure but note that the skill source is TBD.

5. **Adapter base images:** Adel's doc proposes Red Hat certified base images (`registry.redhat.io/agent-base/claude-code:latest`). This is a product decision, not an architectural one. The ADR should reference the concept but not define the registry paths.

## References

- [Adel's doc: Musings on OpenShell, Kagenti, and the ARC](https://docs.google.com/document/d/15RP9OLnz7_7H18UUYvfv-zEgLyP-gpY5aY6aJPGC_lI/edit)
- [AgentOps Vision and Strategy](docs/agentops-vision-strategy.md)
- [Agent Auth and Audience Models](https://docs.google.com/document/d/1HGAYq1u27sHVdifpvYU5rsAiB3PVSfJ0AGBXDtoCnYc/edit)
- [Meeting Summary: Adel + Dimitri + Roland (May 11)](docs/meeting-summary-2026-05-11-agentops-alignment.md)
- [Sunrise Customer Use Cases](docs/customer-sunrise-summary.md)
- [kagent vs Kagenti Comparison](https://docs.google.com/document/d/1Xvcc-UL0_cDWBXj9_eOv8pNgZkm5xUUbH0Q9kuziS4k/edit)
- [Kagenti: From Inheritance to Composition](https://docs.google.com/document/d/1puOWivXrQ29JlQ5ySq0zeXZTKnMJY0y_ApFPrh7N-Sg/edit)
- [ADR-0003: AgentMesh / MultiAgent Topology](https://docs.google.com/document/d/1MRKi6d2sswEb8Zh-sGJ7aZ6rIGXhxzWhXcnoUwGrqSc/edit)
- [ServiceBinding Specification v1.1.0](https://servicebinding.io/spec/core/1.1.0/)
- [AuthBridge Concerns Document](https://docs.google.com/document/d/1KevZD-e5qk9BaWYaSk4eeCrwY5QnA2m6l_S6jrEC3io/edit)
- [Sprint 5 Planning Doc](https://docs.google.com/document/d/1tTXcyFDThdBi-ELU2t4RW43Og0yaYwQIRe9CcRvTGoE/edit)
- Slack: Roland's ARC proposal (#team-rh-ai-agent-ops, May 8)
- Slack: Token forwarding discussion (#kagenti, May 12)
- Slack: Gordon's RFC 9068 audience feedback (#kagenti, May 12)

## Writing Instructions for the ADR

- Use the `prose:content-generator` skill with a **reasoning** voice
- The document should build a logical case, not read like a dry specification
- Include opinions, trade-off reasoning, and clear narrative flow
- Dense technical content is fine, but vary rhythm (short sentences after complex ones)
- Make it something people genuinely want to read, not something they feel obligated to skim
- Follow the ODH-ADR-AgentOps format (table header, What, Why, Goals, Non-Goals, How, Alternatives, Open Questions, References)
- No em-dashes, follow all style guide rules
- AI attribution at the end
