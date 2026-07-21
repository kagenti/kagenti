---
sidebar_label: Scaling & Resiliency
sidebar_position: 4
---

:::danger Placeholder content
This content is placeholder and should be replaced, edited, or deleted by the content owners.
:::

# Scaling & Resiliency

As usage grows, you scale agents and the platform to match — and you make sure a failure in one place doesn't cascade. This page covers the scaling levers and the resiliency practices that keep a busy cluster stable.

## Scaling agents

- **Replicas** — run multiple replicas of high-traffic agents; the gateway load-balances across them.
- **Hibernation** — [hibernate](managing-agents-and-tools.md) idle agents to free capacity for active ones.
- **Quotas** — apply namespace resource quotas so one team can't exhaust the cluster.

```bash
rossoctl agent scale orders-agent --replicas 3 --namespace team1
```

## Scaling the platform

The gateway, operator, and identity components each scale independently. Baseline them against real traffic using the [observability](../observability/overview.md) data, then size for peak.

## Resiliency practices

- **Consistency** — avoid corruption from agents acting on stale or inconsistent state; prefer idempotent tool actions.
- **Graceful degradation** — if a tool or model backend is down, agents should fail cleanly rather than hang.
- **Isolation** — keep tenants in separate namespaces so a noisy or failing workload is contained.

:::warning Long-running clusters
Watch for slow-burn issues on clusters that run for weeks — expiring workload certificates, growing
session storage, drifting mesh state. Bake periodic checks into your ops routine.
:::

:::note For contributors
Tie this to the Resiliency & Consistency workstream. Add concrete HPA/quotas examples and the known
long-running-cluster SVID-expiry caveat (issue #1899).
:::
