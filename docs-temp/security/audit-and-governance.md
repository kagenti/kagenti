---
sidebar_label: Audit & Governance
sidebar_position: 6
---

:::danger Placeholder content
This content is placeholder and should be replaced, edited, or deleted by the content owners.
:::

# Audit & Governance

Governance is being able to answer, after the fact, *what did this agent do, on whose behalf, and was it allowed?* Rossoctl records every tool call and grounds it in verifiable identity, so autonomous agents remain accountable.

## The audit trail

Every call an agent makes through the gateway is recorded with:

- The **user** the action was performed for (via the delegated token).
- The **agent** that made the call (via its workload identity).
- The **tool** and action invoked, and the result.
- A **timestamp** and correlation ID to tie multi-step actions together.

Because identity is cryptographic and delegation is explicit, the audit trail is trustworthy — entries can't be forged by a workload impersonating another.

## Tool governance

The gateway is a deterministic control point between agents and the outside world. That's where you apply filtering, require approvals, and record calls — so governance doesn't depend on the agent choosing to cooperate.

## Agent and skill trust

- **Agent trust** — agents can carry signed Agent Cards and attestation of their capabilities, so you know an agent is what it claims to be.
- **Skill governance** — [skills](../concepts/skills.md) are versioned, reviewable artifacts; you control which ones are approved and running.

:::tip Governance is a feature, not paperwork
The same audit trail that satisfies compliance also makes incidents debuggable: when an agent does
something surprising, you can see exactly what it called and why.
:::

:::note For contributors
Expand from `about.md` (differentiating capabilities: Audit Trail, Tool Governance, Agent Trust, Skills
Governance) and the AuthBridge docs. Add the real audit-log format and where to read it once available.
:::
