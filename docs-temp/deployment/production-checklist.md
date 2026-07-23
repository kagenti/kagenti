---
sidebar_label: Production Checklist
sidebar_position: 6
---

:::danger Placeholder content
This content is placeholder and should be replaced, edited, or deleted by the content owners.
:::

# Production Checklist

Going from a local demo to a production install is mostly about the things a quickstart skips: capacity, high availability, real certificates, backups, and locked-down policy. Work through this before you put agents in front of users.

## Capacity & availability

- [ ] Size control-plane and gateway components for expected load (see [Observability](../observability/overview.md) for baselining).
- [ ] Run more than one replica of the gateway and operator where supported.
- [ ] Set resource requests/limits on every component and on agents.
- [ ] Plan node capacity for peak concurrent agents and sandboxes.

## Security

- [ ] Real, CA-signed certificates for all external endpoints (no self-signed in prod).
- [ ] Keycloak backed by a production database and its own backup plan.
- [ ] Policies written as allow-lists; least privilege verified per agent ([Authorization & Policy](../security/authorization-and-policy.md)).
- [ ] Sandboxing enabled for any agent that runs code or acts autonomously.
- [ ] Secrets in a managed store; no long-lived credentials in manifests.

## Reliability

- [ ] Backups for stateful components (identity store, agent state).
- [ ] Upgrade runbook rehearsed, including the [CRD upgrade step](helm.md).
- [ ] Health and alerting wired to your monitoring stack.

## Observability

- [ ] Tracing enabled and shipping to your backend.
- [ ] Token/cost attribution reviewed so spend is visible per team.

:::tip Treat this as a gate
Make the checklist a real review step before a cluster serves production traffic, not a doc people read
once. Convert each item into an owner and a ticket.
:::

:::note For contributors
Flesh out each item with concrete commands/values as they solidify. Cross-check against
`kagenti/docs/install.md` and the release SOP for upgrade specifics.
:::
