---
sidebar_label: Configuration
sidebar_position: 5
---

# Configuration

Rosso is configured through Helm values (or `rossoctl config`) and a set of feature flags. This page covers the settings you'll touch most; the full list lives in the [Configuration Reference](../reference/configuration-reference.md).

## Feature flags

Optional capabilities are off by default. Turn on only what you use:

| Flag | Enables |
|------|---------|
| `features.sandbox` | OpenShell agent sandboxing |
| `features.skills` | Skills |
| `features.externalSkills` | The Skillberry shared skill store |
| `features.integrations` | Third-party integrations |
| `features.admin` | Admin surfaces in the UI/API |

```bash
rossoctl config set features.skills=true
```

## Secrets

Reference secrets; don't inline them. Store model keys and tool credentials as Kubernetes `Secret`s and point components at them by name.

:::warning
Anything sensitive belongs in a `Secret` (or an external secrets manager), never in `values.yaml`
committed to Git.
:::

## Sizing

Set resource requests/limits per component in values for shared clusters. Start from the defaults, then adjust based on the [observability](../observability/overview.md) data once you're running real workloads.

:::note For contributors
Confirm the flag names and defaults against `kagenti/docs/skills.md` and the repo `CLAUDE.md`
feature-flag policy. Build out the values table in the Reference page.
:::
