---
title: Cost control
description: Remove unused tool definitions, and set a spending limit.
sidebar_position: 8
---

Agents waste tokens in two ways that you can correct. They send the definition of each tool that they
can call, on each turn. And they often have no spending limit.

:::warning Alpha
The plugins on this page are experiments. The behaviour and the configuration will change.
:::

Start with this page, not with [intent-based access](intent-based-access.md) or
[tool call validation](tool-validation.md). These plugins do not evaluate the decisions of the agent,
so the risk is much lower.

## Step 1: measure the cost

You cannot reduce a cost that you did not measure. On your computer, one command is sufficient:

```bash
curl -fsSL https://www.rossoctl.dev/cortex/install.sh \
  | sh -s -- --claude-code
```

Then run `agentop observe` in one terminal and your agent in a second terminal. Each model call, tool call and
agent message appears as it happens. See [Quickstart on a laptop](../../get-started/laptop.md).

In a cluster, the same data goes to your trace store. See
[Observability](../../operate/observability.md).

## Step 2: remove unused tool definitions

An agent sends the definition of each tool that it can call, on each turn. It calls only a small number
of them. On a typical coding agent, the definitions that the agent never uses are **4 percent to 20
percent of the prompt on each turn**. You pay for them again on each turn, for the complete session.

The `tool-prune` plugin removes them from the request before the request leaves the pod.

This reduction is the least expensive one that is available. It does not change the logic of the agent, and it does not change the answers. The plugin removes
only the definitions that the agent does not use.

See the
[plugin catalogue](https://github.com/rossoctl/cortex/blob/main/authbridge/docs/plugin-catalog.md#tool-prune).

:::note
The plugin makes a judgement about the tools that an agent needs. If an agent uses a tool rarely,
confirm that the agent can still use that tool after you enable the plugin.
:::

## Step 3: set a spending limit

Two plugins set two different limits.

### A limit for one session

The `session-budget` plugin sets a limit on the tokens, the number of calls and the duration of one
session. It keeps the counts in Redis. It runs on the outbound chain.

Use this plugin to stop one task that does not end. An example is an agent that repeats a model call
many times.

### A limit for one day

The `litellm-budget-track` plugin reads the `x-litellm-response-cost` header that LiteLLM returns, and
applies a daily limit.

The correct chain depends on your arrangement:

| Your arrangement | Chain |
| --- | --- |
| RossoCortex is in front of the model endpoint | Inbound |
| RossoCortex runs an agent with `authbridge exec` | Outbound |

For the configuration of both plugins, see the
[plugin catalogue](https://github.com/rossoctl/cortex/blob/main/authbridge/docs/plugin-catalog.md).

## Step 4: compact large tool output

If the cost comes from the size of the tool output, and not from the number of calls, the `tool-prune`
plugin does not help. See [Context compaction](context-compaction.md).

Do this step last. It changes what the model receives.

## Related pages

- [Context compaction](context-compaction.md)
- [Observability](../../operate/observability.md) gives the traces and the metrics for each agent.
- [RossoCortex](../core/cortex.md) explains where these plugins run.
