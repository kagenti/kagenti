---
sidebar_label: Authorization & Policy
sidebar_position: 5
---

:::danger Placeholder content
This content is placeholder and should be replaced, edited, or deleted by the content owners.
:::

# Authorization & Policy

Identity tells you *who*; authorization decides *what they may do*. On Rossoctl, policy is enforced centrally — at the gateway and through AuthBridge — so you reason about permissions in one place rather than trusting each agent to behave.

## Scoped permissions

Agents don't get blanket access. A policy grants a specific agent the right to call a specific tool, on behalf of a specific set of users. Anything not granted is denied.

```yaml
apiVersion: rossoctl.dev/v1
kind: ToolAccessPolicy
metadata:
  name: orders-can-ticket
  namespace: team1
spec:
  agent: orders-agent
  tool: ticketing
  allow:
    - action: create
    - action: read
```

## Guardrails

Beyond access control, **guardrails** enforce content-safety and compliance rules on what agents send and receive — filtering unsafe outputs or blocking disallowed actions. These run as plugins on the gateway's request path, so they apply uniformly to every agent.

## Human-in-the-loop

For high-stakes actions, require a human to approve before the call proceeds:

:::tip When to require approval
Reach for human-in-the-loop on irreversible or sensitive actions — spending money, deleting data,
messaging customers. Keep it off the hot path for read-only calls so agents stay useful.
:::

## Deny by default

:::warning
Write policies as allow-lists. Start from "nothing is permitted" and grant the minimum each agent needs.
A denylist quietly fails open as new tools and actions appear.
:::

:::note For contributors
Confirm the policy resource shape (this `ToolAccessPolicy` is illustrative) and the guardrails plugin
mechanism against `kagenti/docs/components.md` (Plugins Adapter) and the AuthBridge docs.
:::
