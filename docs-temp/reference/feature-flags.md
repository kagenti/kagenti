---
sidebar_label: Feature Flags
sidebar_position: 4
---

# Feature Flags

Optional capabilities in Rossoctl are gated behind feature flags and are **off by default**. This keeps a default install lean and lets you adopt newer capabilities deliberately. Flip a flag with `rossoctl config set` or a Helm value.

## Available flags

| Flag | Default | Enables |
|------|---------|---------|
| `features.sandbox` | `false` | OpenShell agent sandboxing ([guide](../guides/sandbox-agents.md)) |
| `features.skills` | `false` | Skills ([concept](../concepts/skills.md)) |
| `features.externalSkills` | `false` | The Skillberry shared skill store |
| `features.integrations` | `false` | Third-party integrations |
| `features.triggers` | `false` | Event-driven agent triggers |
| `features.admin` | `false` | Admin surfaces in the UI/API |

## Set a flag

```bash
# CLI
rossoctl config set features.skills=true

# Helm
helm upgrade rossoctl oci://ghcr.io/rossoctl/rossoctl \
  --namespace rossoctl-system \
  --set features.skills=true
```

:::tip Turn on only what you use
Each flag is a surface to secure and operate. Enable a capability when you have a use for it, not
speculatively — you can always turn it on later.
:::

:::note For contributors
Confirm the flag list and defaults against the repo `CLAUDE.md` feature-flag policy and
`kagenti/docs/skills.md`. Keep this in sync with the Configuration Reference.
:::
