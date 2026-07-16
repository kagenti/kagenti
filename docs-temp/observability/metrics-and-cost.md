---
sidebar_label: Metrics & Cost
sidebar_position: 3
---

# Metrics & Cost

Beyond individual traces, you need the aggregate picture: how much traffic agents handle, how they perform, and — because models cost money per token — how much they spend and on whose behalf. Rossoctl attributes token usage so cost is never a mystery.

## Metrics

Standard operational metrics are emitted for the platform and agents — request rates, latencies, error rates — so you can build the dashboards and alerts you'd expect for any workload, in your existing metrics stack.

## Token cost attribution

Every model call's token usage is captured and attributed to the **agent** and the **user/team** behind it. That turns "our model bill went up" into "team1's research agent doubled its token use this week," which is something you can actually act on.

| You can answer | Why it helps |
|----------------|--------------|
| Which agents cost the most? | Prioritize optimization where it pays off |
| Which team is driving spend? | Chargeback and capacity planning |
| Did a change blow up token use? | Catch regressions before the bill does |

:::tip Set cost expectations early
Review token attribution during rollout, not at invoice time. An agent stuck in a retry loop can
quietly 10x its spend — attribution makes that obvious.
:::

:::note For contributors
Confirm which metrics are exported and where token/cost attribution surfaces (UI vs. metrics backend).
Source: the Observability & Token Cost Management workstream and `kagenti/docs/components.md`.
:::
