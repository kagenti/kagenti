---
sidebar_label: Overview
sidebar_position: 1
---

:::danger Placeholder content
This content is placeholder and should be replaced, edited, or deleted by the content owners.
:::

# Security & Identity Overview

Rossoctl's job is to let agents — including autonomous ones — run on your infrastructure without becoming a liability. That means a security model built in from the start, not bolted on. This section explains each mechanism; start here for the shape of it.

## Principles

- **Zero trust.** No component trusts another because of a shared secret. Every workload has a verifiable, cryptographic identity.
- **No static credentials.** Access is granted through short-lived, scoped tokens issued at runtime — there are no long-lived API keys to leak.
- **Least privilege, per call.** An agent gets exactly the access it needs, for the specific action, on behalf of the specific user.
- **Everything is auditable.** Every tool call is attributable to a user and an agent.
- **Contain the blast radius.** Sandboxing and workspace isolation keep a misbehaving agent from reaching what it shouldn't.

## The building blocks

| Layer | Mechanism | Page |
|-------|-----------|------|
| Workload identity | SPIFFE/SPIRE SVIDs | [Workload Identity](workload-identity.md) |
| User & service auth | Keycloak / OIDC, API RBAC | [Authentication](authentication.md) |
| Delegation | RFC 8693 token exchange, AuthBridge | [Token Exchange & AuthBridge](token-exchange-and-authbridge.md) |
| Permissions | Scoped policy, guardrails, HITL | [Authorization & Policy](authorization-and-policy.md) |
| Accountability | Audit trail, agent trust | [Audit & Governance](audit-and-governance.md) |
| Isolation | OpenShell sandboxing | [Sandbox agents](../guides/sandbox-agents.md) |

## A threat-model lens

:::tip Ask these questions of any agent
- If this agent is compromised, what can it reach? (isolation + egress policy)
- What credentials could leak, and how long are they valid? (short-lived tokens)
- Can I prove, after the fact, what it did and for whom? (audit)
:::

:::note For contributors
Ground the threat model and principles in `kagenti/docs/identity-guide.md` and
`kagenti/docs/authbridge/security-model.md`. Consider embedding the identity architecture diagram.
:::
