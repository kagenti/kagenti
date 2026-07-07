---
sidebar_label: Helm
sidebar_position: 4
---

# Deploy with Helm

For shared clusters and GitOps pipelines, install Rosso from its OCI Helm charts. This gives you versioned, declarative installs you can manage the same way as the rest of your platform.

## Charts

Rosso publishes OCI charts:

```text
oci://ghcr.io/rosso/rosso            # the platform
oci://ghcr.io/rosso/rosso-deps       # dependencies (mesh, identity, etc.)
oci://ghcr.io/rosso/mcp-gateway      # the MCP gateway
```

## Install

```bash
helm install rosso oci://ghcr.io/rosso/rosso \
  --namespace rosso-system --create-namespace \
  --values values.yaml
```

## Upgrade

```bash
helm upgrade rosso oci://ghcr.io/rosso/rosso \
  --namespace rosso-system \
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
