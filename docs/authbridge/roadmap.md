---
draft: true       # excluded from https://www.rossoctl.dev/
---

# AuthBridge Roadmap

## Current State (Shipped)

AuthBridge today provides:

- **Unified binary** with three deployment modes (envoy-sidecar, proxy-sidecar, waypoint)
- **Token exchange** via RFC 8693 with SPIFFE workload identity or K8s service account tokens
- **Inbound JWT validation** with configurable bypass paths
- **Host-based route configuration** for outbound access control
- **MCP and A2A protocol parsers** for request inspection
- **Session store** (experimental) for cross-request correlation
- **Plugin pipeline** with typed extension slots (MCP, A2A, Security, Delegation)
- **Operator-managed client registration** (admin creds moved out of agent namespaces)
- **Image optimization** — 29 MB distroless image for proxy-sidecar mode

## Near Term

### Lean AuthBridge Default ([#1428](https://github.com/rossoctl/rossoctl/issues/1428))

Make proxy-sidecar the default deployment mode:
- Webhook injects HTTP_PROXY/HTTPS_PROXY env vars instead of iptables
- Single unprivileged container per agent pod
- No Envoy dependency for the default path
- Envoy-sidecar retained as opt-in for transparent interception

### Enforceable Proxy Routing ([#1429](https://github.com/rossoctl/rossoctl/issues/1429))

Close the HTTP_PROXY bypass gap:
- NetworkPolicy prevents agent containers from making direct egress
- Only the proxy sidecar is allowed outbound connections
- Webhook auto-generates NetworkPolicy when injecting the sidecar

### Eliminate Keycloak Admin Credentials ([#1426](https://github.com/rossoctl/rossoctl/issues/1426))

Remove all privileged credentials from agent namespaces:
- Operator reads admin creds from rossoctl-system only (not agent namespaces)
- SPIFFE-authenticated Dynamic Client Registration (no admin creds anywhere)
- Federated SPIFFE client auth replaces client secrets (pending Keycloak 26.6.x)

### Plugin Pipeline ([#1458](https://github.com/rossoctl/rossoctl/issues/1458))

Extend AuthBridge beyond token exchange:
- Stabilize v1 plugin interface
- gRPC plugin protocol for out-of-process plugins (language-agnostic)
- Integration with SPARK/ToolGuard guardrails
- Integration with CPEX + ContextForge plugins
- Invest in Praxis to replace Envoy when feature gaps are closed

## Vision

### Intent-Based Access Control

Move beyond host-level allowlists to understanding *what* an agent is trying to do:

- **Session-aware guardrails** — the session store correlates user intents (A2A messages)
  with agent actions (MCP tool calls, LLM requests). Guardrail plugins evaluate whether
  a tool call aligns with the original intent.
- **Multi-turn context** — decisions consider the full conversation history, not just
  the current request. A `delete_user` call after a weather conversation is suspicious.
- **Append-after-allow semantics** — only successful requests are recorded in the
  session, keeping the context clean for policy evaluation.

### Secure Agent Delegation ([#1181](https://github.com/rossoctl/rossoctl/issues/1181))

Two-level authorization for MCP tool access:
- Coarse-grained: inter-agent JWT token exchange via Keycloak
- Fine-grained: per-tool authorization at the MCP Gateway (Kuadrant policies)
- End users can see and control what tools agents access on their behalf

### Just-In-Time User Login ([#1435](https://github.com/rossoctl/rossoctl/issues/1435))

For synchronous task assistants that need real-time access to user data:
- Agent requests access at the moment it's needed (not pre-stored)
- User approves or denies in real-time
- Access is scoped to the specific task and expires immediately after

### AI Access Control ([#790](https://github.com/rossoctl/rossoctl/issues/790))

Human language policy for fine-grained access control:
- Admins write policies in natural language ("Agent X can read weather data but not
  modify user profiles")
- AIAC infers intent from Agent Cards, tasks, and context
- Derives fine-grained access rules for each Policy Decision Point

### Runtime-Attested Agent Cards ([#1302](https://github.com/rossoctl/rossoctl/issues/1302))

Cryptographically verifiable agent capabilities:
- Agent Cards signed with JWS over JCS-canonicalized content
- Runtime attestation proves the card matches the actual running agent
- Consumers can verify agent identity and capabilities before delegating

### Event-Driven Agent Identity ([#1460](https://github.com/rossoctl/rossoctl/issues/1460))

Authorization for asynchronous agent communication:
- Cryptographic event origin verification for CloudEvents
- Signed event envelopes prevent impersonation via message brokers
- Event-specific access policies (who can publish/subscribe to which event types)

### AuthBroker ([#922](https://github.com/rossoctl/rossoctl/issues/922))

Trust-aware authorization across agent → tool → resource flows:
- Policy Enforcement Points at each service boundary
- Dynamic, request-level authorization decisions
- Integration with existing identity infrastructure (Keycloak, AuthBridge)

### Modular AuthBridge ([#1187](https://github.com/rossoctl/rossoctl/issues/1187))

Environment-adaptive deployment:
- Run across Kubernetes, OpenShift, VMs, bare metal
- Service mesh abstraction (Istio, Linkerd, or no mesh — self-providing mTLS)
- Persona-driven consumption (security teams, ops teams, guardrail admins)
- Praxis evaluation as next-generation proxy runtime

## Architecture Direction

```
Today                              Future
─────                              ──────
                                   
Envoy + ext_proc    ──────►   Praxis (Rust, AI-native proxy)
                                   │
Go plugin pipeline  ──────►   Native filter pipeline
                                   │
Host allowlists     ──────►   Intent-based + protocol-aware policy
                                   │
Per-pod sidecar     ──────►   Sidecar / Gateway / DaemonSet (adaptive)
                                   │
Token exchange only ──────►   Token exchange + guardrails + governance
```

The long-term direction is a single, modular proxy runtime (likely Praxis) that
combines traffic interception, identity management, protocol-aware policy, and
content guardrails in one composable system — deployed however the environment
requires.

## Further Reading

- [Identity in Agentic Platforms](https://medium.com/rossoctl-the-agentic-platform/identity-in-agentic-platforms-enabling-secure-least-privilege-access-996527f1c983)
- [Security in and around MCP, Part 2](https://medium.com/rossoctl-the-agentic-platform/security-in-and-around-mcp-part-2-mcp-in-deployment-65bdd0ba9dc6)
- [Security in and around MCP, Part 3](https://medium.com/rossoctl-the-agentic-platform/security-in-and-around-mcp-part-3-mcp-server-identity-10d6768d96c1)
