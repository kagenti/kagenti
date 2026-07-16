---
sidebar_label: Network Visualization
sidebar_position: 4
---

# Network Visualization

Multi-agent systems create a web of connections — agents calling agents, agents calling tools through the gateway, everything over the mesh. [Kiali](https://kiali.io/) gives you a live topology view of that web, built on the Istio service mesh underneath Rossoctl.

## What Kiali shows

- **Topology** — a graph of which workloads talk to which, in real time.
- **Traffic health** — request rates, success/error ratios, and latency on each edge.
- **mTLS status** — confirmation that traffic between workloads is mutually authenticated.

## Open it

```bash
rossoctl install --local --with-observability
rossoctl ui open --view mesh
```

## When to reach for it

- **Understanding a system** — see how a multi-agent setup actually wires together, not how you think it does.
- **Debugging connectivity** — a broken edge or a spike in errors on one link points you straight at the problem.
- **Verifying security posture** — confirm mTLS is on across the mesh.

:::tip Pair it with traces
Kiali tells you *where* traffic is failing; a [trace](tracing.md) tells you *why*. Use the topology to
find the bad edge, then open the trace for that call.
:::

:::note For contributors
Expand from `kagenti/docs/kiali/README.md`. Replace `--view mesh` with the real access path and add a
screenshot (`kagenti/docs/images/kiali-graph.jpg`).
:::
