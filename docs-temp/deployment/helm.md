---
sidebar_label: Helm
sidebar_position: 4
---

:::danger Placeholder content
This content is placeholder and should be replaced, edited, or deleted by the content owners.
:::

# Deploy with Helm

For shared clusters and GitOps pipelines, install Rossoctl from its OCI Helm charts. This gives you versioned, declarative installs you can manage the same way as the rest of your platform.

## Charts

Rossoctl publishes OCI charts:

```text
oci://ghcr.io/rossoctl/rossoctl            # the platform
oci://ghcr.io/rossoctl/rossoctl-deps       # dependencies (mesh, identity, etc.)
oci://ghcr.io/rossoctl/mcp-gateway      # the MCP gateway
```

## Install

```bash
helm install rossoctl oci://ghcr.io/rossoctl/rossoctl \
  --namespace rossoctl-system --create-namespace \
  --values values.yaml
```

## Upgrade

```bash
helm upgrade rossoctl oci://ghcr.io/rossoctl/rossoctl \
  --namespace rossoctl-system \
  --values values.yaml
```

:::warning CRD upgrades
Helm does not always upgrade CRDs on `helm upgrade`. When a release adds or changes custom resources,
apply the new CRDs explicitly before upgrading the chart, or the operator may not reconcile new fields.
:::

## Values

Keep environment differences in `values.yaml` — component toggles, resource sizing, and secrets references. See [Configuration](configuration.md) for the options that matter most.

:::note For contributors
Confirm chart coordinates and names against `kagenti/docs/install.md` (today `oci://ghcr.io/kagenti/...`).
Document the CRD-upgrade step precisely — it's a known sharp edge (see issue #1335).
:::
