---
sidebar_label: Installation
sidebar_position: 2
---

# Installation

This page gets the Rosso platform running on a local Kind cluster — the fastest way to try it. For other targets and production settings, see [Deployment](../deployment/overview.md).

## 1. Install the CLI

```bash
# macOS / Linux (Homebrew)
brew install rossoctl

# Verify
rossoctl version
```

## 2. Stand up the platform

`rossoctl` creates a local Kind cluster and installs the control plane, gateway, identity, and observability components for you.

```bash
rossoctl install --local
```

The installer is composable — enable only what you need:

```bash
rossoctl install --local \
  --with-observability \
  --with-gateway \
  --with-identity
```

:::tip First install takes a few minutes
The installer pulls a number of images (Istio, Keycloak, SPIRE, the gateway). Grab a coffee on the
first run; subsequent installs reuse the cache.
:::

## 3. Verify

```bash
rossoctl status
kubectl get pods -n rosso-system
```

You should see the control-plane pods `Running`. If something is stuck, see [Troubleshooting](../troubleshooting.md).

## Next steps

- [Quickstart](quickstart.md) — deploy a sample agent and talk to it.
- [Deploy your first agent](deploy-your-first-agent.md) — bring your own.

:::note For contributors
Confirm the real install commands and flags against `kagenti/docs/install.md` (today the installer is
`scripts/kind/setup-kagenti.sh` with `--with-*` flags). Replace the Homebrew line if the CLI ships a
different way.
:::
