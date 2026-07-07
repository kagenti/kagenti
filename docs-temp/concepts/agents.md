---
sidebar_label: Agents
sidebar_position: 2
---

# Agents

An **agent** is a workload that reasons and acts — it takes a goal, decides what to do, and calls tools or other agents to get there. On Rosso, an agent is just a container that speaks [A2A](https://a2aproject.github.io/A2A/), enrolled with the platform through an `AgentRuntime` resource.

## What makes it an agent on Rosso

- **It publishes an Agent Card.** Every agent exposes a discovery document at `/.well-known/agent-card.json` describing its capabilities and skills. That's how other agents and the platform find and understand it.
- **It's enrolled via `AgentRuntime`.** You describe the workload (image or source, config, resources) and the operator reconciles the Deployment, Service, identity, and policy wiring.
- **It gets an identity.** At deploy time the agent receives a cryptographic workload identity (SPIFFE), so every call it makes can be attributed and authorized.

## Framework-neutral by design

Rosso doesn't ship an agent framework and doesn't ask you to adopt one. If your agent speaks A2A, it runs — whether it was built with LangGraph, CrewAI, AG2, AutoGen, a custom loop, or a coding agent like Claude Code. See [Bring your own agent](../guides/bring-your-own-agent.md).

## A minimal agent

```yaml
apiVersion: rossoctl.dev/v1
kind: AgentRuntime
metadata:
  name: research-agent
  namespace: team1
spec:
  image: ghcr.io/my-org/research-agent:1.2.0
  replicas: 1
```

## Agents talk to agents

Because discovery and messaging are standardized on A2A, one agent can call another the same way it calls a tool — enabling multi-agent systems (a supervisor delegating to specialists, for example) without custom glue.

:::tip Agents vs. tools
An **agent** decides *what* to do; a **tool** performs a specific action. Agents are A2A; tools are MCP.
The [MCP Gateway](tools-and-mcp.md) sits between them.
:::

:::note For contributors
Ground the Agent Card and `AgentRuntime` details in `kagenti/docs/components.md` and
`kagenti/docs/new-agent.md`. Note the ongoing migration from the legacy `agents.agent.kagenti.dev` CRD
to standard Deployments enrolled by the operator.
:::
