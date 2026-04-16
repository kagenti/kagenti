# Kagenti Platform Operator

Kubernetes operator that manages the lifecycle of Kagenti platform components.
Built with [Kubebuilder](https://book.kubebuilder.io/).

## Overview

The Platform Operator reconciles a cluster-scoped `KagentiPlatform` custom resource
to install, configure, and monitor Kagenti components:

- **Agent Operator** (kagenti-operator)
- **Admission Webhook** (kagenti-webhook)
- **UI** (frontend + backend)
- **Auth** (generic OIDC, with optional Keycloak support)
- **MCP Gateway**

It also validates that required infrastructure dependencies (cert-manager, Tekton,
Gateway API, etc.) are present before attempting installation.

## Quick Start

```bash
# Install CRDs
make install

# Run locally against a cluster
make run

# Apply sample CR
kubectl apply -f config/samples/kagenti_v1alpha1_kagentiplatform.yaml
```

## Development

```bash
# Generate deepcopy and manifests
make generate manifests

# Run tests (unit + envtest)
make setup-envtest
KUBEBUILDER_ASSETS=$(bin/setup-envtest use 1.32 -p path) \
  go test $(go list ./... | grep -v test/e2e) -v

# Build container image
make docker-build IMG=ghcr.io/kagenti/kagenti-platform-operator:dev
```

## CRD

The `KagentiPlatform` CRD is cluster-scoped (singleton). Key spec fields:

| Field | Description |
|-------|-------------|
| `agentOperator.managementState` | `Managed` / `Removed` / `Unmanaged` |
| `webhook.managementState` | `Managed` / `Removed` / `Unmanaged` |
| `ui.managementState` | `Managed` / `Removed` / `Unmanaged` |
| `auth.managementState` | `Managed` / `Removed` / `Unmanaged` |
| `auth.oidc.issuerURL` | OIDC provider issuer URL |
| `infrastructure.<dep>.requirement` | `Required` / `Optional` / `Ignored` |
| `domain` | Base domain for ingress (default: `localtest.me`) |

Status reports per-component health and infrastructure availability:

```bash
kubectl get kagentiplatform kagenti -o wide
# NAME     PHASE   AGE
# kagenti  Ready   5m
```

## License

Apache 2.0 - See [LICENSE](../LICENSE)
