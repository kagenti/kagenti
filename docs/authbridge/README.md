---
draft: true       # excluded from https://www.rossoctl.dev/
---

# AuthBridge

AuthBridge provides platform primitives to secure AI agents by managing agent
identity, authentication, and authorization invisibly — and enforces network
guardrails that scope access to minimum necessary permissions with full
auditability.

**Why it matters:** AI agents make autonomous, non-deterministic decisions about
which tools or services to call, making it unsafe to trust them with secrets or
self-authorization. AuthBridge shifts credential management to the platform layer
where it is enforced (not advisory), surviving prompt injection and agent compromise
while preserving the full identity delegation chain from end user through
orchestrator to tool.

## What AuthBridge Does

- **Transparent token injection** — agents never see or manage tokens used in outgoing calls;
  AuthBridge intercepts outbound requests and attaches audience-scoped tokens automatically
- **Token exchange** — as an example, AuthBridge may use the agent workload identity
  (SPIFFE JWT-SVID) or the K8s service account token to obtain short-lived,
  audience-specific OAuth tokens via token exchange (RFC 8693)
- **Tool access control** — restricts which external services (MCP tools, other agents, APIs, LLMs)
  each agent can reach, based on host allowlists and protocol-aware policies
- **Inbound validation** — verifies JWT tokens on incoming requests, ensuring only
  authorized callers can invoke an agent
- **Delegation chains** — preserves the identity chain (user → orchestrator → agent → tool)
  so every hop is authenticated and authorized
- **No privileged mode required** — the default deployment uses a single unprivileged
  sidecar container with standard HTTP_PROXY routing

## How It Works

```
┌─────────────────────────────────────────────────────────────────┐
│  Agent Pod                                                       │
│                                                                  │
│  ┌─────────────┐    HTTP_PROXY     ┌──────────────────────┐     │
│  │   Agent     │ ───────────────── │  AuthBridge Proxy    │     │
│  │ (any        │                   │                      │     │
│  │  framework) │ ◄──── reverse ─── │  - JWT validation    │     │
│  │             │       proxy       │  - Token injection   │     │
│  └─────────────┘                   │  - Access control    │     │
│                                    └──────────┬───────────┘     │
└───────────────────────────────────────────────┼─────────────────┘
                                                │
                    ┌──────────────┬─────────────┼──────────────────┐
                    │              │             │                   │
                    ▼              ▼             ▼                   ▼
            ┌──────────────┐ ┌──────────────┐ ┌──────────────┐ ┌──────────────┐
            │  Keycloak    │ │Other Agents  │ │  MCP Tools   │ │  LLM APIs    │
            │  (token      │ │  (A2A,       │ │  (weather,   │ │  (OpenAI,    │
            │   exchange)  │ │   delegation)│ │   github...) │ │   Anthropic) │
            └──────────────┘ └──────────────┘ └──────────────┘ └──────────────┘
                                      ...                  ...
```

**Inbound flow:** A request arrives at the agent → AuthBridge validates the caller's
JWT → if valid, forwards to the agent container.

**Outbound flow:** The agent makes an HTTP call to a tool, other agent or LLM → AuthBridge
intercepts via HTTP_PROXY → ensures agent is allowed to make the call → injects an
audience-scoped token → forwards the request to the destination.

## For End Users

When you interact with an agent, AuthBridge is working behind the scenes to protect you:

- The agent can only access tools, agents and data it's explicitly authorized for — it
  cannot reach arbitrary services even if compromised or hallucinating
- The calling user identity is carried through the delegation chain so access decisions
  may reflect the calling user permissions, as well as supporting a shared service
  account when desired
- Every tool call and agent call the agent makes is logged and auditable
- The platform enforces these guarantees — the agent cannot bypass them

Learn more: [Security Model](security-model.md)

## For Agent Developers

You only need to pass the received token as-is to any outbound call you make.
AuthBridge verifies the inbound token before it reaches you and handles auth for
your outbound calls:

- No SDKs to import, no auth code to write
- Your agent makes normal HTTP calls; adequate credentials are injected automatically
- If a call is blocked, you get a clear 403 with a reason (not a cryptic TLS error)
- Works with any framework (LangGraph, CrewAI, AG2, custom)

To configure which tools your agent can access, see the
[Deployment Guide](deployment-guide.md).

## For Platform Operators

AuthBridge deploys as a sidecar proxy. The default mode (proxy-sidecar) requires:
- 1 container per agent pod (~15-30 MB memory)
- No privileged mode
- No iptables
- No Envoy

See: [Deployment Guide](deployment-guide.md) for modes, configuration, and troubleshooting.

## For Security Architects

AuthBridge implements zero-trust for agent communication:
- Workload identity via SPIFFE/SPIRE (no static secrets)
- OAuth 2.0 Token Exchange (RFC 8693) with audience scoping
- Platform-enforced access control (agents cannot self-authorize)
- Protocol-aware inspection for MCP and A2A traffic

See: [Security Model](security-model.md) for the full threat model and trust boundaries.

## Quick Start

Deploy the weather agent demo with AuthBridge on a local Kind cluster:

```bash
# 1. Deploy Rossoctl with AuthBridge enabled
./.github/scripts/local-setup/kind-full-test.sh --skip-cluster-destroy

# 2. Send a request to the weather agent — AuthBridge handles auth transparently
curl -H "Authorization: Bearer $(python rossoctl/examples/identity/get_token.py)" \
  http://weather-agent.team1.svc:8000/run

# 3. Check AuthBridge logs to see token exchange in action
kubectl logs deploy/weather-agent -n team1 -c authbridge-proxy
```

For a progressive walkthrough: [Demos](demos.md)

## Documentation

| Document | Audience | Covers |
|----------|----------|--------|
| [Security Model](security-model.md) | End users, architects | Trust model, what's enforced, threat model |
| [Deployment Guide](deployment-guide.md) | Operators, developers | Modes, configuration, troubleshooting |
| [Sidecar Injection](sidecar-injection.md) | Operators, developers | Expected containers, label vocabulary, feature gates, how to switch modes |
| [Demos](demos.md) | Everyone | Progressive hands-on walkthrough |
| [Roadmap](roadmap.md) | Architects, contributors | Vision, upcoming features, epics |

## Technical Reference

For deep implementation details:

- [AuthBridge Binary README](https://github.com/rossoctl/cortex/blob/main/authbridge/cmd/README.md) — modes, YAML config, logging
- [AuthBridge Architecture](https://github.com/rossoctl/cortex/blob/main/authbridge/README.md) — sequence diagrams, protocol flows
- [AuthBridge Demos](https://github.com/rossoctl/cortex/blob/main/authbridge/demos/README.md) — step-by-step demo instructions
- [Identity Guide](../identity-guide.md) — platform-level SPIFFE/SPIRE and Keycloak architecture

## Blog Posts

- [Identity in Agentic Platforms: Enabling Secure Least-Privilege Access](https://medium.com/rossoctl-the-agentic-platform/identity-in-agentic-platforms-enabling-secure-least-privilege-access-996527f1c983)
- [Security in and around MCP, Part 2: MCP in Deployment](https://medium.com/rossoctl-the-agentic-platform/security-in-and-around-mcp-part-2-mcp-in-deployment-65bdd0ba9dc6)
- [Security in and around MCP, Part 3: MCP Server Identity](https://medium.com/rossoctl-the-agentic-platform/security-in-and-around-mcp-part-3-mcp-server-identity-10d6768d96c1)
- [Introducing MCP Gateway in Rossoctl](https://medium.com/rossoctl-the-agentic-platform/introducing-mcp-gateway-in-rossoctl-a-unified-front-door-for-your-mcp-servers-28db5b6ef62d)
- [Hands-on with MCP Gateway](https://medium.com/rossoctl-the-agentic-platform/hands-on-with-mcp-gateway-from-local-setup-to-agent-integration-in-rossoctl-f9bd3b7cc334)
