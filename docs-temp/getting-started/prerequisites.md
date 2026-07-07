---
sidebar_label: Prerequisites
sidebar_position: 1
---

# Prerequisites

Before you install Rosso, make sure your workstation and target cluster meet the requirements below. Most first-time users run everything locally on Kind — that path needs only Docker or Podman and a few CLIs.

:::info Naming
Rosso is mid-rename from *Kagenti*. Commands and resources on this site use the target names —
`rossoctl`, the `rossoctl.dev` API group, and the `rosso-system` namespace. You may still see
`kagenti`-prefixed names in some components until the rename lands.
:::

## Workstation tools

| Tool | Version | Why |
|------|---------|-----|
| Docker or Podman | latest | Runs the local Kind cluster and builds images |
| `kubectl` | 1.29+ | Talks to the cluster |
| `kind` | 0.23+ | Local Kubernetes for development |
| `rossoctl` | latest | The Rosso CLI (installs the platform, manages agents and tools) |
| `helm` | 3.14+ | Optional — for chart-based installs |

## Cluster requirements

For a **local** cluster, a machine with **8 CPU / 16 GB RAM** free is comfortable; the platform and a couple of agents fit within that. For a **shared or production** cluster, size against the [production checklist](../deployment/production-checklist.md).

Supported targets:

- **Kind** — local development (recommended for your first run).
- **OpenShift** — 4.16+ (4.19+ for OLM-managed workload identity).
- **Helm / OCI charts** — any conformant Kubernetes cluster.

## Model access

Agents need a model backend. You can point Rosso at a hosted API (any OpenAI-compatible endpoint) or run models locally with [Ollama](../guides/use-local-models.md). Have an API key ready if you plan to use a hosted provider.

:::note For contributors
Pin exact versions once we settle a support matrix, and confirm the minimum CPU/RAM against a fresh
Kind install. Source: `kagenti/docs/install.md` and `kagenti/docs/developer/kind.md`.
:::
