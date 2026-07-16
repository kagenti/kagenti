---
sidebar_label: Quickstart
sidebar_position: 2
---

# Quickstart

In about ten minutes you'll go from an empty cluster to a running agent you can talk to. This walks the whole loop end to end; later pages go deeper on each step.

## Before you start

You've installed the CLI and the platform ([Installation](installation.md)) and `rossoctl status` is healthy.

## 1. Deploy a sample agent

Rossoctl ships a few example agents. Deploy the weather agent:

```bash
rossoctl agent deploy weather --namespace team1
```

Watch it come up:

```bash
rossoctl agent list --namespace team1
```

```text
NAME      STATUS    URL
weather   Running   http://weather.team1.svc/.well-known/agent-card.json
```

## 2. Add a tool

Give the agent a tool to call over MCP:

```bash
rossoctl tool deploy weather-mcp --namespace team1
rossoctl agent connect weather --tool weather-mcp --namespace team1
```

## 3. Talk to it

```bash
rossoctl agent chat weather --namespace team1
```

```text
> What's the weather in Amsterdam?
It's 14°C and overcast in Amsterdam right now.
```

:::tip Prefer a UI?
The Rossoctl dashboard offers the same import-deploy-test loop with a visual chat window. Open it with
`rossoctl ui open`.
:::

## What just happened

You deployed an agent, registered a tool with the MCP gateway, wired them together, and had a conversation — all governed by the platform's identity and policy layer, with traces captured automatically.

## Next steps

- [Deploy your first agent](deploy-your-first-agent.md) — bring your own instead of the sample.
- [Concepts: Architecture](../concepts/architecture.md) — understand what you just used.

:::note For contributors
Replace the sample commands with the real demo flow from `kagenti/docs/demos/README.md` (the weather
demo). Confirm the exact `rossoctl` subcommands and the agent-card URL format.
:::
