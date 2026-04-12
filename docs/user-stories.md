# Use Cases

Scenarios that define the Kagenti vision across verticals. Each maps to a
persona from [PERSONAS_AND_ROLES.md](../PERSONAS_AND_ROLES.md). Detailed
drill-downs are linked where they exist.

For the taxonomy of agent operational models these scenarios target (read-only
insight, synchronous task, async task, monitoring, event-driven), see
[Use Case Types](./use-case-types.md).

## Index

| Area | Personas | Drill-Down |
|------|----------|------------|
| [Deployment & Access Control](#deployment--access-control) | Agent Developer | — |
| [Platform Governance](#platform-governance) | Platform Operator | — |
| [Identity & Trust](#identity--trust) | Platform Operator, Security Specialist | — |
| [Observability](#observability) | Platform Operator, Agent Developer | — |
| [Agent Lifecycle](#agent-lifecycle) | Platform Operator | — |
| [Agent Discovery](#agent-discovery) | Platform Operator | — |
| [Multi-Tenancy](#multi-tenancy) | Platform Operator | — |
| [Developer Experience](#developer-experience) | Agent Developer | — |
| [Inbox Pattern](#inbox-pattern) | Agent Developer, Platform Operator, End User | — |
| [Agentic Runtime & Sandbox](#agentic-runtime--sandbox) | Agent Developer, Platform Operator | [agentic-runtime/use-cases.md](agentic-runtime/use-cases.md) |

---

## Deployment & Access Control

**As an Agent Developer**, I want to deploy an agent with access to both internal resources (database, memory service) and external resources (GitHub, S3, allow-listed domains), so that my agent can operate across trust boundaries without exposing internal services.

**As an Agent Developer**, I want to restrict access to my deployed agent to only myself, so that I can iterate privately before exposing it.

**As an Agent Developer**, I want to grant my team access to my deployed agent without requiring platform-level intervention.

**As an Agent Developer**, I want to grant other agents I have deployed access to my agent, so that I can compose multi-agent workflows via A2A without opening access beyond my own workloads.

---

## Platform Governance

**As a Platform Operator**, I want to configure which inference providers and models are available per team, so that I can control cost and enforce approved model lists.

**As a Platform Operator**, I want to control egress to specific external endpoints per namespace, so that network policy is centrally managed.

**As a Platform Operator**, I want to apply a common guardrails policy to all incoming requests, so that content safety and compliance rules are enforced uniformly across agents.

---

## Identity & Trust

**As a Platform Operator**, I want to integrate my build system with AgentCard resources to attach build provenance signatures, so that deployed agents carry verifiable evidence of their build origin and integrity.

**As a Security and Identity Specialist**, I want to sign an agent's A2A AgentCard with the workload's SPIFFE SVID, so that consumers can verify the agent's identity is attested by SPIRE before trusting its advertised capabilities.

---

## Observability

**As a Platform Operator**, I want each namespace to route agent telemetry to its own observability backend (metrics sink, MLflow instance), so that teams have isolated visibility into their agents without cross-tenant data leakage.

**As an Agent Developer**, I want my A2A agent to be auto-instrumented with OpenTelemetry GenAI semantic conventions, so that traces, token usage, and tool calls are captured without manual instrumentation.

---

## Agent Lifecycle

**As a Platform Operator**, I want to enforce that agents are admitted to a namespace only after evaluation at a restricted access level, so that untested or unverified agents cannot access production resources before demonstrating expected behavior.

---

## Agent Discovery

**As a Platform Operator**, I want to list all running agents across namespaces and filter them by capability, skill, protocol, and other AgentCard attributes, so that I have a unified view of the agent fleet and can reason about platform-wide capacity and coverage.

---

## Multi-Tenancy

**As a Platform Operator**, I want to define token usage quotas per role and namespace, so that I can enforce cost boundaries and prevent any single team or workload from consuming disproportionate inference capacity.

---

## Developer Experience

**As an Agent Developer**, I want to quickly deploy a locally-developed agent into a remote cluster with scoped personal access, so that I can test against real infrastructure without a heavyweight CI/CD cycle.

**As an Agent Developer**, I want to deploy and test multi-agent workflows in a live namespace, so that I can validate agent-to-agent interactions under realistic conditions.

---

## Inbox Pattern

**As an Agent Developer**, I want to define my agent's inbox source declaratively (queue topic, webhook path, event filter), so that the platform handles delivery and I focus on task logic.

**As a Platform Operator**, I want inbox-bound messages to carry authenticated sender identity through AuthBridge, so that authorization policies apply to asynchronous work items the same way they do for synchronous A2A calls.

**As a Platform Operator**, I want inbox-based agents to autoscale based on queue depth, so that compute matches demand without manual intervention.

**As an End User**, I want to submit a task to an agent and receive a handle I can poll for results, so that I am not blocked on long-running work.

---

## Agentic Runtime & Sandbox

Detailed use cases for the sandboxed agentic runtime: coding agents, DevOps
agents, tool-calling agents, MCP tool approval models, and sandboxing profile
selection.

See: [agentic-runtime/use-cases.md](agentic-runtime/use-cases.md)
(PR [#1005](https://github.com/kagenti/kagenti/pull/1005))
