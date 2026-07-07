---
sidebar_label: Troubleshooting
sidebar_position: 10
---

# Troubleshooting

Common problems and how to resolve them, grouped by where they show up. If you don't find your issue here, check the component's traces ([Tracing](observability/tracing.md)) and the [FAQ](faq.md).

## Install & platform

### Pods stuck `Pending` on Kind

Usually resource pressure. Give the Docker/Podman VM more CPU/RAM (8 CPU / 16 GB minimum) and reinstall.

### Image pulls fail or time out

Preload images into the cluster before installing:

```bash
rossoctl images preload --local
```

### CRDs not updated after an upgrade

Helm doesn't always upgrade CRDs. Apply the new CRDs explicitly before `helm upgrade` (see [Helm](deployment/helm.md)).

## Identity & auth

### 401 / token errors calling a tool

The delegated token likely failed validation or exchange. Confirm the tool is registered with a credential and that a [policy](security/authorization-and-policy.md) permits the agent→tool delegation.

### Mesh-wide 503 on a long-running cluster

Workload certificates (SVIDs) may have expired on a cluster that's been up for a long time, breaking gateway-routed traffic. Restart the affected workloads to force re-issuance, and track the fix in the identity workstream.

## Tools & gateway

### MCP Inspector "Connect" fails on OpenShift

Often a certificate-trust issue: the Route's certificate isn't trusted by the browser, or the Inspector proxy address isn't set. Use a CA-signed certificate for browser-facing Routes.

## Agents

### Agent deploys but never becomes `Ready`

```bash
rossoctl agent describe <name> -n <ns>
kubectl logs deploy/<name> -n <ns>
```

Check the model backend is reachable (`LLM_API_BASE`) and any referenced `Secret` exists.

:::tip Start from the trace
For behavior problems (as opposed to crashes), the fastest path is usually the agent's
[trace](observability/tracing.md) — it shows the exact call that failed.
:::

:::note For contributors
Expand from `kagenti/docs/troubleshooting.md` and the embedded troubleshooting sections in `install.md`,
`sandbox-guide.md`, and `new-tool.md`. Link real issues (#1335, #1899, #2085, #2100) where useful.
:::
