---
sidebar_label: Overview
sidebar_position: 1
---

:::danger Placeholder content
This content is placeholder and should be replaced, edited, or deleted by the content owners.
:::

# Operations Overview

Once Rossoctl is installed and agents are live, the work shifts to day-two operations: keeping agents healthy, managing their lifecycle, handling state, and scaling with demand. This section is for whoever runs the platform after launch.

## The day-two surface

| Area | What you do | Page |
|------|-------------|------|
| Lifecycle | Deploy, update, hibernate, retire agents and tools | [Managing agents & tools](managing-agents-and-tools.md) |
| State | Preserve memory and sessions across restarts | [State & sessions](state-and-sessions.md) |
| Scale | Handle load; stay consistent and resilient | [Scaling & resiliency](scaling-and-resiliency.md) |
| Health | Watch traces, metrics, cost | [Observability](../observability/overview.md) |
| Fixes | Diagnose common problems | [Troubleshooting](../troubleshooting.md) |

## A healthy baseline

```bash
rossoctl status
kubectl get pods -n rossoctl-system
rossoctl agent list --all-namespaces
```

Know what "normal" looks like — pod counts, latency, token spend — so you can spot drift early. The [observability](../observability/overview.md) data is how you establish that baseline.

:::tip Operate by namespace
Namespaces are your unit of isolation and blast-radius control. Give teams their own, and apply quotas
so one team's agents can't starve another's.
:::

:::note For contributors
This section is lighter on source material in `kagenti/docs/` today — build it out from operational
experience and the runtime/sandbox lifecycle docs (`agentic-runtime/*`).
:::
