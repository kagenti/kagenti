---
sidebar_label: Add Your First Tool
sidebar_position: 5
---

:::danger Placeholder content
This content is placeholder and should be replaced, edited, or deleted by the content owners.
:::

# Add Your First Tool

Agents get their reach from tools. Rossoctl exposes tools over the [Model Context Protocol (MCP)](https://modelcontextprotocol.io/) and routes every call through the **MCP Gateway**, which handles discovery, authentication, and audit for you. This page registers a tool and connects it to an agent.

## 1. Deploy an MCP tool

```bash
rossoctl tool deploy weather-mcp \
  --image ghcr.io/rossoctl-samples/weather-mcp:latest \
  --namespace team1
```

Behind the scenes this registers the tool with the gateway so agents can discover it by name.

## 2. Connect it to an agent

```bash
rossoctl agent connect weather --tool weather-mcp --namespace team1
```

The agent now sees the tool's capabilities and can call them. All traffic flows through the gateway, so the call is authenticated and recorded — the agent never holds the tool's credentials directly.

## 3. Confirm the wiring

```bash
rossoctl tool list --namespace team1
rossoctl agent describe weather --namespace team1
```

The agent's description should list `weather-mcp` under connected tools.

:::tip Tools can be shared
Register a tool once and connect it to many agents. The gateway enforces which agent may call which
tool — see [Authorization & Policy](../security/authorization-and-policy.md).
:::

## Next steps

- [Configure the MCP Gateway](../guides/configure-the-mcp-gateway.md) — routing, prefixes, and auth for real tools.
- [Concepts: Tools and MCP](../concepts/tools-and-mcp.md) — how it works under the hood.

:::note For contributors
Confirm the tool-deploy and connect commands against `kagenti/docs/new-tool.md` and
`kagenti/docs/gateway.md` (real flow uses `MCP_URL`/`MCP_URLS` and an `MCPServerRegistration`).
:::
