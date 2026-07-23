---
sidebar_label: Overview
sidebar_position: 1
---

:::danger Placeholder content
This content is placeholder and should be replaced, edited, or deleted by the content owners.
:::

# Deployment Overview

Rossoctl runs on any conformant Kubernetes cluster. This page helps you pick a target and points to the right install guide; the following pages cover each in detail.

## Choose a target

| Target | Best for | Guide |
|--------|----------|-------|
| **Kind** | Local development, demos, first look | [Local (Kind)](local-kind.md) |
| **OpenShift** | Enterprise clusters, integrated security | [OpenShift](openshift.md) |
| **Helm / OCI** | Any Kubernetes, GitOps pipelines | [Helm](helm.md) |

:::tip Not sure?
Start on **Kind** locally to learn the platform, then use **Helm** to install into a shared cluster.
Reach for the **OpenShift** guide only for OpenShift-specific steps (routes, OLM, SCCs).
:::

## What gets installed

A full install brings up the four pillars:

- **Control plane** — the operator and CRDs.
- **Networking** — Istio (ambient mesh) and the MCP Gateway.
- **Security** — SPIRE (workload identity) and Keycloak (auth).
- **Observability** — the OpenTelemetry collector, and optionally MLflow/Phoenix and Kiali.

The installer is composable — enable only the components you need with `--with-*` flags.

## Before you install

- Meet the [prerequisites](../getting-started/prerequisites.md).
- Decide your namespace-per-team layout.
- Have model access ready ([local](../guides/use-local-models.md) or hosted).

## After you install

- Harden with the [production checklist](production-checklist.md).
- Tune components in [Configuration](configuration.md).
- Move to day-two [Operations](../operations/overview.md).

:::note For contributors
Confirm the component list and `--with-*` flags against `kagenti/docs/install.md`. Add version support
matrix (OCP versions, Kubernetes minimums).
:::
