---
sidebar_label: Configure the MCP Gateway
sidebar_position: 2
---

:::danger Placeholder content
This content is placeholder and should be replaced, edited, or deleted by the content owners.
:::

# Configure the MCP Gateway

The MCP Gateway is the single front door for tool calls. This guide shows how to register MCP servers, set routing prefixes, and require authentication — the day-to-day tasks of running tools on Rossoctl. For the concept, see [Tools & MCP](../concepts/tools-and-mcp.md).

## Register an MCP server

Point the gateway at your MCP server and give it a routing prefix:

```yaml
apiVersion: rossoctl.dev/v1
kind: MCPServerRegistration
metadata:
  name: ticketing
  namespace: team1
spec:
  toolPrefix: ticketing
  url: http://ticketing-mcp.team1.svc/mcp
```

```bash
rossoctl apply -f ticketing.yaml
rossoctl tool list --namespace team1
```

Agents now reach the tool's capabilities as `ticketing/*` through the gateway.

## Require authentication

For tools that act on real systems, require a credential and let the gateway handle delegated tokens rather than sharing a static key:

```yaml
spec:
  toolPrefix: ticketing
  url: https://ticketing-mcp.team1.svc/mcp
  credentialRef:
    name: ticketing-oauth
```

:::tip No-auth vs. authenticated tools
A read-only demo tool (like weather) can run without auth. Anything that mutates state or reads
sensitive data should require authentication and flow through [token exchange](../security/token-exchange-and-authbridge.md).
:::

## Connect agents

```bash
rossoctl agent connect orders-agent --tool ticketing --namespace team1
```

## Inspect routing

```bash
rossoctl gateway routes --namespace team1
```

Use this to confirm prefixes don't collide and that each tool resolves to the expected server.

:::note For contributors
Align resource fields and commands with `kagenti/docs/gateway.md`. Document the real credential/secret
wiring and the `mcp-broker-router` behavior; add a troubleshooting pointer for 503s.
:::
