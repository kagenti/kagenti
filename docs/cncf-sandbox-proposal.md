# CNCF Sandbox Application: Kagenti

> **Status:** DRAFT -- for team review before submission.
>
> This document mirrors every field of the
> [CNCF Sandbox application form](https://github.com/cncf/sandbox/blob/main/.github/ISSUE_TEMPLATE/application.yml).
> Items requiring team input are marked with `[!IMPORTANT]` callouts.
> File the issue at <https://github.com/cncf/sandbox/issues/new?template=application.yml> once all are resolved.

---

## Basic Project Information

### Project summary

Cloud-native platform for deploying, securing, and managing AI agents on Kubernetes -- providing framework-neutral lifecycle management, zero-trust authentication (SPIFFE/SPIRE + OAuth 2.0 token exchange), multi-protocol support (A2A, MCP), and built-in observability.

### Project description

<!-- 100-300 words -->

Kagenti is a cloud-native platform for deploying and operating AI agents on Kubernetes. As organizations adopt agentic AI -- where autonomous agents act on behalf of users, call APIs, invoke tools, and collaborate with other agents -- the infrastructure needs shift from simple model serving to a full lifecycle platform with identity, authorization, build pipelines, observability, and multi-tenancy. Kagenti provides this infrastructure so that agent developers focus on agent logic, not platform concerns.

The project has five core areas:

1. **Zero-trust identity and authorization** (`kagenti-extensions`) -- A Kubernetes mutating admission webhook injects authentication sidecars (Envoy proxy, SPIFFE helper, Keycloak client registration) into agent pods. AuthBridge transparently validates inbound JWTs and exchanges outbound tokens (RFC 8693) with subject preservation, creating a full audit chain: which user authorized which agent to perform which action. Workloads are automatically registered as OAuth2 clients using their SPIFFE identity, eliminating static credentials.

2. **Agent and tool lifecycle** (`kagenti/backend`) -- A FastAPI backend provides REST APIs for the full CRUD lifecycle of agents and tools: create, deploy, build from source (via Shipwright), delete, and inspect. Container images are built from Git sources directly on-cluster using Shipwright BuildRuns.

3. **Multi-protocol agent communication** -- Native support for A2A (Agent-to-Agent) protocol including agent card discovery (`/.well-known/agent-card.json`) and chat, plus MCP (Model Context Protocol) for tool integration with inspection and invocation endpoints.

4. **Platform UI** (`kagenti/ui-v2`) -- A React dashboard providing agent and tool catalogs, deployment wizards, build progress tracking, MCP gateway management, observability views, and admin configuration -- all backed by Keycloak-based RBAC (viewer/operator/admin roles).

5. **Observability and experiment tracking** -- Integrated Phoenix (LLM trace visualization), OpenTelemetry Collector (trace export), and MLflow (experiment tracking), all deployed via Helm with OAuth2 authentication through Keycloak.

The platform deploys as Helm charts on any conformant Kubernetes cluster (Kind, OpenShift, EKS) with Istio ambient mesh for mTLS, namespace-based multi-tenancy for team isolation, and a full infrastructure-as-code stack (Keycloak, SPIRE, cert-manager, Istio, Phoenix, MLflow).

---

## Project Details

### Org repo URL

https://github.com/kagenti

*(All repos under the org are in scope of the application.)*

### Project repo URL

https://github.com/kagenti/kagenti

### Additional repos in scope of the application

- https://github.com/kagenti/kagenti-extensions -- Kubernetes admission webhook, AuthBridge (AuthProxy + client-registration), Helm chart
- https://github.com/kagenti/agent-examples -- Reference agent implementations and demo tools

### Website URL

https://kagenti.io

### Roadmap

> [!IMPORTANT]
> **ACTION REQUIRED -- Roadmap URL**: Create a public roadmap and paste the URL here. Options:
> - A `ROADMAP.md` file in `kagenti/kagenti`
> - A GitHub Projects board at `https://github.com/orgs/kagenti/projects/...`

### Roadmap context

Kagenti's roadmap is organized around three themes:

1. **Hardening AuthBridge** -- SPIRE JWT-based Keycloak client authentication (eliminating admin credentials), route-based per-host token exchange, and dynamic client registration improvements. Tracked in kagenti-extensions issues #82, #85, #69, and PR #79.

2. **Agent Attestation** -- Extending SPIFFE workload identity with stackable attestors that add agent-specific claims (Agent Card hash, capabilities, SBOM provenance) to the identity chain. This enables fine-grained policy such as "only allow agents built from this pipeline" or "only allow agents with a signed Agent Card." Tracked in kagenti/kagenti#612 (Agent Attestation Epic).

3. **Ecosystem Integration** -- MCP Gateway integration (via Kuadrant) for centralized policy and audit at the boundary between agents and tools, A2A (Agent-to-Agent) protocol support for agent discovery, and framework-agnostic attestation across agent SDKs.

### Contributing guide

https://github.com/kagenti/kagenti/blob/main/CONTRIBUTING.md

### Code of Conduct (CoC)

The project has adopted the [CNCF Code of Conduct](https://github.com/cncf/foundation/blob/main/code-of-conduct.md).

https://github.com/kagenti/kagenti/blob/main/CODE_OF_CONDUCT.md

### Adopters

> [!NOTE]
> **OPTIONAL** -- No `ADOPTERS.md` exists yet. This field is optional but strengthens the application.

### Maintainers file

https://github.com/kagenti/kagenti/blob/main/MAINTAINERS.md

### Security policy file

https://github.com/kagenti/kagenti/blob/main/SECURITY.md

### Standard or specification?

N/A. Kagenti is not a standard or specification. It implements existing standards including OAuth 2.0 Token Exchange (RFC 8693), SPIFFE (Secure Production Identity Framework for Everyone), and OpenID Connect.

### Business product or service to project separation

> [!IMPORTANT]
> **ACTION REQUIRED -- Team confirmation**: Confirm or revise the statement below.

This project is unrelated to any product or service. Kagenti is a community-driven open-source project that composes existing CNCF and open-source building blocks (SPIFFE/SPIRE, Envoy, Keycloak) into a pluggable blueprint for securing AI agent workloads on Kubernetes.

---

## Cloud Native Context

### Why CNCF?

Kagenti is built entirely on CNCF technologies -- SPIFFE/SPIRE for workload identity, Envoy for traffic proxying, and Kubernetes as the target platform. Contributing Kagenti to the CNCF provides:

1. **Neutral governance** -- As AI agents become a standard part of cloud-native infrastructure, the authentication and identity layer they depend on should be governed by a neutral foundation, not a single vendor.

2. **Ecosystem alignment** -- Kagenti fills a specific gap in the CNCF landscape: bridging workload identity (SPIFFE) with OAuth 2.0 delegation for agentic workloads. Being part of the CNCF ensures this work is coordinated with upstream SPIFFE/SPIRE, Envoy, and emerging agent standards.

3. **Community adoption** -- The CNCF's reach accelerates adoption and contribution. Kagenti's value increases with community feedback on interoperability gaps between identity providers, policy engines, and agent frameworks.

4. **Upstream collaboration** -- Kagenti has already identified gaps in SPIFFE attestation for AI agents (stackable attestors, agent-specific claims). CNCF membership provides a forum to drive these upstream improvements in collaboration with TAG Security and the SPIFFE project.

### Benefit to the landscape

Kagenti benefits the Cloud Native Landscape by addressing a critical emerging need: **secure identity and delegation for AI agents**.

The current landscape provides excellent primitives -- SPIFFE/SPIRE for workload identity, Envoy for traffic management, and various policy engines -- but no project composes these into a turnkey solution for the agentic AI use case. Specifically:

- **Subject preservation through token exchange**: When an agent acts on behalf of a user, Kagenti's token exchange preserves the user's identity (`sub` claim) while scoping the token to the target service. This creates a full audit chain: which user authorized which agent to perform which action.

- **Zero auth code for agent developers**: Sidecar injection means agent developers focus on agent logic, not OAuth flows, token refresh, or SPIRE integration. This lowers the barrier to building secure agents.

- **Automatic workload-to-OAuth-client mapping**: Using SPIFFE IDs as OAuth client identifiers eliminates static credential management and manual Keycloak provisioning.

No existing CNCF project provides this combination of transparent token exchange, subject preservation, and automatic identity-to-OAuth bridging for Kubernetes workloads.

### Cloud native 'fit'

Kagenti is cloud-native by design:

- **Kubernetes-native**: The mutating admission webhook follows established Kubernetes patterns (similar to Istio sidecar injection). Injection is controlled via namespace and pod labels, integrating naturally with GitOps workflows.

- **Sidecar architecture**: Authentication concerns are fully externalized into sidecar containers, following the separation-of-concerns principle central to cloud-native design. Applications require zero code changes.

- **Declarative configuration**: Helm charts, Kustomize manifests, and declarative Keycloak sync (`keycloak_sync.py`) enable infrastructure-as-code deployment.

- **Multi-architecture**: All container images are built for linux/amd64 and linux/arm64 via GitHub Actions CI/CD.

- **Observable**: Prometheus metrics endpoints and structured logging are built into the webhook controller. The platform integrates OpenTelemetry Collector for distributed trace export and Phoenix for LLM trace visualization, enabling end-to-end observability of agent interactions.

- **Standards-based**: Built on OAuth 2.0 (RFC 6749), Token Exchange (RFC 8693), SPIFFE, and OpenID Connect -- not proprietary protocols.

### Cloud native 'integration'

Kagenti complements and depends on several CNCF projects:

| CNCF Project | Relationship |
|---|---|
| **SPIFFE/SPIRE** (Graduated) | Core dependency. Provides workload identity (JWT-SVIDs) that Kagenti uses for automatic Keycloak client registration and token exchange. Kagenti extends SPIFFE's value by bridging workload identity into the OAuth 2.0 delegation model. |
| **Envoy** (Graduated) | Core dependency. AuthBridge uses Envoy as the sidecar proxy with a gRPC external processor (ext_proc) for JWT validation and token exchange. |
| **Kubernetes** (Graduated) | Target platform. The webhook uses the Kubernetes admission API; all components are deployed as pods. |
| **cert-manager** (Graduated) | Used for webhook TLS certificate management. |
| **Helm** (Graduated) | The webhook is packaged and distributed as a Helm chart via OCI registry. |
| **Prometheus** (Graduated) | Metrics collection via ServiceMonitor for the webhook controller. |
| **OpenTelemetry** (Graduated) | Kagenti deploys an OpenTelemetry Collector for distributed trace export, enabling end-to-end observability of agent interactions alongside Phoenix for LLM trace visualization. |
| **Kuadrant** (Sandbox) | Complementary. Kagenti's roadmap includes MCP Gateway integration via Kuadrant for centralized policy and audit at the agent-to-tool boundary. |

### Cloud native overlap

Kagenti has limited overlap with existing CNCF projects:

- **Istio / Linkerd (service meshes)**: Both provide sidecar-based traffic management and mTLS. Kagenti's sidecar injection is architecturally similar but serves a different purpose: OAuth 2.0 token exchange and JWT validation rather than mTLS and traffic routing. Kagenti is designed to coexist with Istio (the `init-iptables.sh` script explicitly handles Istio ambient mesh coexistence with ztunnel fwmark and HBONE port exclusions). Kagenti does not replace a service mesh; it adds an authentication layer that service meshes do not provide.

- **SPIFFE/SPIRE**: Kagenti depends on SPIFFE/SPIRE but does not duplicate its functionality. SPIFFE provides the identity; Kagenti bridges that identity into the OAuth 2.0 world (Keycloak client registration, token exchange). This is a complementary relationship.

- **OAuth2-proxy**: A simpler authentication reverse proxy focused on user-facing web applications. It does not support token exchange (RFC 8693), SPIFFE integration, or the sidecar injection pattern for Kubernetes workloads.

### Similar projects

| Project | Relationship to Kagenti |
|---|---|
| **Istio** (CNCF) | Service mesh with sidecar injection. Focuses on mTLS and traffic management, not OAuth token exchange. Kagenti coexists with Istio. |
| **SPIFFE/SPIRE** (CNCF) | Workload identity framework. Kagenti is a consumer and extender of SPIFFE identity. |
| **OAuth2-proxy** (open source) | Simple auth proxy for web apps. Does not support RFC 8693 token exchange, SPIFFE, or sidecar injection. |
| **Kuadrant** (CNCF Sandbox) | API gateway policy. Complementary -- Kagenti's roadmap includes Kuadrant integration for the MCP Gateway. |
| **Keycloak** (CNCF) | Identity provider. Kagenti uses Keycloak as the OAuth2/OIDC backend but could work with other providers that support RFC 8693. |
| **Dex** (open source) | OIDC identity provider. Does not support token exchange (RFC 8693). |

No existing project provides Kagenti's specific combination of automatic SPIFFE-to-OAuth bridging, transparent token exchange with subject preservation, and sidecar-based injection for Kubernetes workloads.

### Landscape

> [!IMPORTANT]
> **ACTION REQUIRED -- Landscape listing**: Submit a landscape application at [landscape.cncf.io](https://landscape.cncf.io/) before or in parallel with this submission.

Kagenti is not yet listed on the [Cloud Native Landscape](https://landscape.cncf.io/). We plan to submit a landscape application in parallel with this Sandbox application.

---

## CNCF Policies

### Trademark and accounts

- [x] If the project is accepted, I agree to donate all project trademarks and accounts to the CNCF

> [!IMPORTANT]
> **ACTION REQUIRED -- Trademark acknowledgment**: All maintainers must acknowledge this before submission.

### IP policy

- [x] If the project is accepted, I agree the project will follow the CNCF IP Policy

> [!IMPORTANT]
> **ACTION REQUIRED -- IP policy acknowledgment**: All maintainers must acknowledge this before submission.

### Will the project require a license exception?

N/A. Kagenti uses the Apache License 2.0 for all project code. All third-party dependencies use licenses on the [CNCF Allowlist](https://github.com/cncf/foundation/blob/main/policies-guidance/allowed-third-party-license-policy.md). The project enforces the [Developer Certificate of Origin (DCO)](https://developercertificate.org/) on all pull requests via CI checks, ensuring all contributions are properly signed off.

### Project "Domain Technical Review"

> [!IMPORTANT]
> **ACTION REQUIRED -- TAG engagement**: Schedule a Day 0 technical review with [TAG Security](https://github.com/cncf/tag-security) before submission.

We have not yet engaged with a TAG for a formal technical review. We plan to engage with TAG Security given Kagenti's focus on workload identity and authentication.

---

## Contact Information

### Application contact email(s)

> [!IMPORTANT]
> **ACTION REQUIRED -- Contact emails**: Provide comma-separated email addresses of individuals who should be contacted regarding this application.

### Contributing or sponsoring entity signatory information

> [!IMPORTANT]
> **ACTION REQUIRED -- Signatory information**: Fill in the appropriate table below.

If an organization:

| Name | Address | Type (e.g., Delaware corporation) | Signatory name and title | Email address |
|---|---|---|---|---|
| | | | | |

Or, if an individual or individual(s):

| Name | Country | Email address |
|---|---|---|
| | | |
| | | |

---

## Additional Information

### CNCF contacts

> [!NOTE]
> **OPTIONAL -- CNCF contacts**: List any people who are part of CNCF leadership (TOC, TAGs, etc.) who are familiar with the project.

### Additional information

- **KubeCon Europe 2026**: The Kagenti project has an accepted presentation at KubeCon + CloudNativeCon Europe 2026: *"When an Agent Acts on Your Behalf, Who Holds the Keys? -- Cryptographic Identity and Delegation for Cloud-Native AI Agents."*

- **Blog**: The project maintains a blog at [medium.com/kagenti-the-agentic-platform](https://medium.com/kagenti-the-agentic-platform).

- **Security posture**: The project runs [OpenSSF Scorecard](https://securityscorecards.dev/) via GitHub Actions with a badge in the README, demonstrating commitment to supply-chain security best practices.

- **Technical highlights**:
  - Subject preservation through RFC 8693 token exchange ensures full audit trail (user + agent visible at every hop)
  - Coexistence with Istio ambient mesh (iptables rules handle ztunnel fwmark and HBONE)
  - Route-based token exchange supporting per-host audience configuration via `routes.yaml`
  - Multi-arch container images (amd64/arm64) published to `ghcr.io/kagenti/`
  - Helm chart distributed via OCI registry

- **Vision**: Kagenti aims to establish best practices for AI agent identity and delegation in cloud-native environments, with a long-term vision of stackable attestors that enrich workload identity with agent-specific claims (provenance, capabilities, Agent Card verification).

---

## Pre-Submission Checklist

The following items **must be completed** before filing the CNCF Sandbox issue:

### Required (blocking submission)

| Item | Status | Action |
|---|---|---|
| `CONTRIBUTING.md` | **Exists** | [Link](https://github.com/kagenti/kagenti/blob/main/CONTRIBUTING.md) -- has contribution guidelines, DCO info, development setup |
| `CODE_OF_CONDUCT.md` | **Exists** | [Link](https://github.com/kagenti/kagenti/blob/main/CODE_OF_CONDUCT.md) -- references CNCF Code of Conduct |
| `SECURITY.md` | **Exists** | [Link](https://github.com/kagenti/kagenti/blob/main/SECURITY.md) -- has vulnerability reporting policy |
| `MAINTAINERS.md` | **Exists** | [Link](https://github.com/kagenti/kagenti/blob/main/MAINTAINERS.md) -- lists core maintainers with contact info |
| Public roadmap | Missing | Create a GitHub Projects board or `ROADMAP.md` and link it above |
| Contact emails | Missing | Fill in the contact information section above |
| Signatory information | Missing | Fill in the signatory table above |
| Trademark/IP acknowledgment | Pending | All maintainers must acknowledge the CNCF trademark and IP policy checkboxes |
| Root `LICENSE` file | Missing in `kagenti-extensions` | Add the full Apache 2.0 license text to the repo root |

### Recommended (strengthens the application)

| Item | Status | Action |
|---|---|---|
| `ADOPTERS.md` | Missing | Create listing any organizations or individuals using Kagenti |
| `GOVERNANCE.md` | Missing | Create describing project governance model (maintainer roles, decision process, etc.) |
| [OpenSSF Best Practices Badge](https://www.bestpractices.dev/) | Not started | Apply for the CII Best Practices badge (separate from the OpenSSF Scorecard already in CI) |
| CNCF Landscape listing | Not listed | Submit at [landscape.cncf.io](https://landscape.cncf.io/) |
| TAG Security engagement | Not started | Schedule a Day 0 technical review presentation with TAG Security |
| Business/product separation | Needs confirmation | Team to confirm the "unrelated to any product" statement or describe separation |

### Review checklist

Before submitting, all team members should review and confirm:

- [ ] Project summary accurately represents Kagenti
- [ ] Project description is complete and compelling (100-300 words)
- [ ] All URLs are correct and publicly accessible
- [ ] Roadmap context reflects current priorities
- [ ] Cloud native overlap section is fair and accurate
- [ ] Similar projects comparison is complete
- [ ] All **ACTION REQUIRED** items above have been resolved
