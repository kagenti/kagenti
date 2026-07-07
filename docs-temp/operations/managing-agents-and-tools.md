---
sidebar_label: Managing Agents & Tools
sidebar_position: 2
---

# Managing Agents & Tools

Agents and tools have a lifecycle: you deploy them, update them as code changes, pause the ones you aren't using, and retire them when they're done. Rosso manages that lifecycle through the operator, so these are declarative, reviewable operations.

## Update an agent

Roll out a new version by updating the image or redeploying from source; the operator handles the rollout:

```bash
rossoctl agent deploy orders-agent \
  --image ghcr.io/my-org/orders-agent:1.3.0 \
  --namespace team1
```

## Hibernate and wake

Idle agents don't need to hold resources. Hibernate them and wake on demand:

```bash
rossoctl agent hibernate orders-agent --namespace team1
rossoctl agent wake orders-agent --namespace team1
```

:::tip Hibernate long-tail agents
Many agents are used in bursts. Hibernating the long tail frees capacity for active workloads and
lowers cost, with a small cold-start on wake.
:::

## Retire

```bash
rossoctl agent delete orders-agent --namespace team1
```

Retiring an agent also cleans up its registered identity and gateway wiring.

## Inspect

```bash
rossoctl agent describe orders-agent --namespace team1
rossoctl tool list --namespace team1
```

Use `describe` to confirm status, connected tools, and the current revision when diagnosing behavior.

:::note For contributors
Confirm the `hibernate`/`wake`/`promote` verbs exist as described (lifecycle is owned by the operator —
see the "Agent Lifecycle Management" workstream). Align with `kagenti/docs/new-agent.md`.
:::
