---
sidebar_label: Configuration Reference
sidebar_position: 3
---

# Configuration Reference

The complete set of configuration values for a Rossoctl install. For the common cases and how-to, see [Deployment: Configuration](../deployment/configuration.md); this page is the exhaustive lookup.

## Helm values

Values are grouped by component. The table below is a starting scaffold — expand it to the full chart schema.

| Value | Default | Description |
|-------|---------|-------------|
| `features.sandbox` | `false` | Enable OpenShell sandboxing |
| `features.skills` | `false` | Enable skills |
| `features.externalSkills` | `false` | Enable the Skillberry store |
| `gateway.replicas` | `1` | MCP Gateway replicas |
| `identity.trustDomain` | `rossoctl.local` | SPIFFE trust domain |
| `observability.enabled` | `false` | Install the observability stack |
| `observability.tracing.exporter` | — | OTLP endpoint for traces |

## `rossoctl config` keys

The CLI writes the same settings:

```bash
rossoctl config set features.skills=true
rossoctl config get features.skills
rossoctl config list
```

## Secrets and external stores

Sensitive values (model keys, tool credentials, database passwords) are referenced from Kubernetes `Secret`s or an external secrets manager — never set inline. See [Configuration](../deployment/configuration.md).

:::note For contributors
Replace this scaffold with the generated values reference from the Helm charts. Confirm real defaults
and key names against the chart in `kagenti/kagenti`.
:::
