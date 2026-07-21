---
sidebar_label: OpenShift
sidebar_position: 3
---

:::danger Placeholder content
This content is placeholder and should be replaced, edited, or deleted by the content owners.
:::

# Deploy on OpenShift

Rossoctl runs on OpenShift with a few platform-specific considerations — routes for ingress, OLM-managed operators, and security context constraints. This page covers what differs from a vanilla Kubernetes install.

## Requirements

- **OpenShift 4.16+** (4.19+ for OLM-managed SPIRE / workload identity).
- Cluster-admin (or equivalent) for the initial install, which creates CRDs and operators.

## Install

```bash
rossoctl install --openshift
```

The installer wires up OpenShift **Routes** for external access to the gateway and UI, and integrates with the platform's certificate handling.

## Routes and TLS

External endpoints are exposed as Routes. For browser-facing endpoints (the UI, MCP Inspector), make sure the Route's certificate is trusted by clients — self-signed certs will cause connection failures in the browser.

:::warning Self-signed certs
On clusters using self-signed certificates, browser-based tools can fail to connect until the Route
certificate is trusted or replaced with a CA-signed one. See [Troubleshooting](../troubleshooting.md).
:::

## Verify

```bash
rossoctl status
oc get routes -n rossoctl-system
```

:::note For contributors
Expand from `kagenti/docs/install.md` and `kagenti/docs/ocp/openshift-install.md`. Confirm the OCP
version floor, SCC requirements, and the exact install command. Reference the MCP Inspector cert issues
(#2085, #2100) in troubleshooting.
:::
