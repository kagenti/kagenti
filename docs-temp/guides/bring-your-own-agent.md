---
sidebar_label: Bring Your Own Agent
sidebar_position: 4
---

# Bring Your Own Agent

Rossoctl runs agents built with any framework, as long as they speak [A2A](https://a2aproject.github.io/A2A/). You don't rewrite your agent to adopt the platform — you wrap it so it publishes an Agent Card and accepts A2A requests, then deploy it like any other workload.

## The one requirement: speak A2A

Your agent needs to:

1. Serve an **Agent Card** at `/.well-known/agent-card.json` describing its skills.
2. Accept A2A messages on its HTTP endpoint.

Most frameworks have a thin A2A adapter for this; if yours doesn't, the wrapper is small.

## Framework notes

| Framework | How it fits |
|-----------|-------------|
| **LangGraph** | Wrap the compiled graph behind an A2A handler; expose tools via MCP. |
| **CrewAI** | Expose the crew's entrypoint as an A2A skill. |
| **AG2 / AutoGen** | Bridge the conversable agent to A2A messages. |
| **Custom loop** | Implement the A2A endpoint directly — it's a small HTTP contract. |

## Deploy it

Once your agent speaks A2A, it's just an `AgentRuntime`:

```bash
rossoctl agent deploy my-langgraph-agent \
  --image ghcr.io/my-org/my-langgraph-agent:1.0.0 \
  --namespace team1
```

Everything else — identity, tool access through the gateway, tracing — is applied by the platform.

:::tip Keep tools in MCP
Expose your agent's tools as MCP servers rather than wiring them in directly. That way the gateway
governs and audits tool calls, and other agents can reuse the same tools.
:::

:::note For contributors
Add concrete adapter snippets per framework and link to `kagenti/docs/developing-kagenti-app.md` and any
sample repos. Confirm the exact Agent Card fields A2A requires.
:::
