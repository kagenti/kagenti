---
sidebar_label: Local (Kind)
sidebar_position: 2
---

# Deploy on Kind

[Kind](https://kind.sigs.k8s.io/) (Kubernetes in Docker) is the recommended way to run Rossoctl locally — for development, demos, and evaluation. It's the same path the [Installation](../getting-started/installation.md) quickstart uses, with more detail and options here.

## Create the cluster and install

```bash
rossoctl install --local
```

This provisions a Kind cluster and installs the platform. To choose components:

```bash
rossoctl install --local \
  --with-identity \
  --with-gateway \
  --with-observability \
  --with-sandbox
```

## Preload images (optional, faster)

On slow networks, preload the platform images into the Kind nodes to avoid pulling them during install:

```bash
rossoctl images preload --local
```

## Access the cluster

```bash
kubectl config use-context kind-rosso
rossoctl status
rossoctl ui open
```

## Tear down

```bash
rossoctl uninstall --local
# or delete the whole cluster
kind delete cluster --name rosso
```

:::tip Resource pressure
If pods stay `Pending`, your Docker VM likely needs more CPU/RAM. Bump it to at least 8 CPU / 16 GB and
reinstall.
:::

:::note For contributors
Map these to the real `scripts/kind/setup-kagenti.sh` flags and `kagenti/docs/developer/kind.md`.
Confirm the kube-context name and the image-preload command.
:::
