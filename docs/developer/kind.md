---
draft: true       # excluded from https://www.rossoctl.dev/
---

# Kind Development Guide

This guide covers local Rossoctl development using Kind (Kubernetes in Docker).

## Table of Contents

- [Prerequisites](#prerequisites)
- [Quick Start](#quick-start)
- [Credentials Setup](#credentials-setup)
- [Full Deployment Workflow](#full-deployment-workflow)
- [Accessing Services](#accessing-services)
- [Running E2E Tests](#running-e2e-tests)
- [Debugging](#debugging)
- [Namespace Provisioning](#namespace-provisioning)
- [Script Reference](#script-reference)

## Prerequisites

| Requirement | Minimum | Purpose |
|-------------|---------|---------|
| Docker | 12GB RAM, 4 cores | Container runtime for Kind |
| Kind | Latest | Local Kubernetes cluster |
| kubectl | 1.28+ | Kubernetes CLI |
| Helm | 3.12+ | Package manager |
| Python | 3.11+ | E2E tests |
| uv | Latest | Python package manager |
| jq | Latest | JSON processing |

<details>
<summary><b>macOS</b></summary>

```bash
# Install Homebrew if needed: https://brew.sh
brew install kind kubectl helm jq python@3.11

# Install uv
curl -LsSf https://astral.sh/uv/install.sh | sh

# Docker Desktop: https://docker.com/products/docker-desktop
```
</details>

<details>
<summary><b>Linux (Ubuntu/Debian)</b></summary>

```bash
# kubectl
curl -LO "https://dl.k8s.io/release/$(curl -L -s https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl"
sudo install kubectl /usr/local/bin/

# Kind
curl -Lo ./kind https://kind.sigs.k8s.io/dl/latest/kind-linux-amd64
sudo install kind /usr/local/bin/

# Helm
curl https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | bash

# Other tools
sudo apt-get update && sudo apt-get install -y jq python3.11 python3.11-venv

# uv
curl -LsSf https://astral.sh/uv/install.sh | sh

# Docker: https://docs.docker.com/engine/install/ubuntu/
```
</details>

<details>
<summary><b>Linux (Fedora/RHEL)</b></summary>

```bash
# kubectl
curl -LO "https://dl.k8s.io/release/$(curl -L -s https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl"
sudo install kubectl /usr/local/bin/

# Kind
curl -Lo ./kind https://kind.sigs.k8s.io/dl/latest/kind-linux-amd64
sudo install kind /usr/local/bin/

# Helm
curl https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | bash

# Other tools
sudo dnf install -y jq python3.11

# uv
curl -LsSf https://astral.sh/uv/install.sh | sh

# Docker/Podman: https://docs.docker.com/engine/install/fedora/
```
</details>

## Quick Start

```bash
# Direct install — composable, no extra dependencies
scripts/kind/setup-rossoctl.sh --with-all

# Or full CI-style run (create → deploy → test → keep cluster)
./.github/scripts/local-setup/kind-full-test.sh --skip-cluster-destroy

# Show service URLs and credentials
./.github/scripts/local-setup/show-services.sh
```

Access the UI at: **http://rossoctl-ui.localtest.me:8080**

Login with Keycloak admin credentials shown by `show-services.sh`.

## Direct Installation

The `scripts/kind/setup-rossoctl.sh` bash installer creates a Kind cluster and
deploys Rossoctl with composable `--with-*` flags. It requires only `kind`,
`helm` (v3), and `kubectl` — no Python or `uv` needed.

### Examples

```bash
# Core only (cert-manager, Gateway API, Istio GW controller, Keycloak, operator, webhook)
scripts/kind/setup-rossoctl.sh

# Everything
scripts/kind/setup-rossoctl.sh --with-all

# Core + Istio ambient + UI (no SPIRE, no builds)
scripts/kind/setup-rossoctl.sh --with-istio --with-ui

# Reuse existing cluster
scripts/kind/setup-rossoctl.sh --skip-cluster --with-all

# With secrets
scripts/kind/setup-rossoctl.sh --with-all --secrets-file charts/rossoctl/.secrets.yaml
```

### Flag Reference

| Flag | Components |
|------|------------|
| `--with-istio` | Full Istio ambient mesh (mTLS, waypoints); Gateway API controller always installed as core |
| `--with-spire` | SPIRE + SPIFFE IdP setup |
| `--with-backend` | Rossoctl backend API |
| `--with-ui` | Rossoctl UI (auto-enables backend) |
| `--with-mcp-gateway` | MCP Gateway |
| `--with-kuadrant` | Kuadrant operator (auto-enables MCP Gateway) |
| `--with-otel` | OpenTelemetry collector |
| `--with-mlflow` | MLflow trace backend (auto-enables OTel + Istio ambient) |
| `--with-builds` | Tekton + Shipwright (build agents from source) |
| `--with-kiali` | Kiali + Prometheus (auto-enables Istio ambient) |
| `--with-all` | All of the above |

| Option | Description |
|--------|-------------|
| `--skip-cluster` | Reuse existing Kind cluster |
| `--secrets-file FILE` | YAML file with secrets for the Rossoctl Helm chart |
| `--cluster-name NAME` | Kind cluster name (default: `rossoctl`) |
| `--domain DOMAIN` | Domain for services (default: `localtest.me`) |
| `--dry-run` | Show commands without executing |

### Cleanup

```bash
# Uninstall platform, keep cluster
scripts/kind/cleanup-rossoctl.sh

# Uninstall and destroy cluster
scripts/kind/cleanup-rossoctl.sh --destroy-cluster
```

## Credentials Setup

See [Common Setup](./README.md#common-setup-all-environments) for credentials configuration.

## Full Deployment Workflow

The `kind-full-test.sh` script runs 6 phases:

```
Phase 1: Create Kind Cluster
Phase 2: Install Rossoctl Platform
Phase 3: Deploy Test Agents
Phase 4: Run E2E Tests
Phase 5: Rossoctl Uninstall (optional)
Phase 6: Destroy Kind Cluster (optional)
```

### Common Workflows

```bash
# ┌─────────────────────────────────────────────────────────────────────────────┐
# │ First-time setup: create → deploy → test → keep cluster                     │
# └─────────────────────────────────────────────────────────────────────────────┘
./.github/scripts/local-setup/kind-full-test.sh --skip-cluster-destroy

# ┌─────────────────────────────────────────────────────────────────────────────┐
# │ Iterate on existing cluster (skip create, keep cluster)                     │
# └─────────────────────────────────────────────────────────────────────────────┘
./.github/scripts/local-setup/kind-full-test.sh --skip-cluster-create --skip-cluster-destroy

# ┌─────────────────────────────────────────────────────────────────────────────┐
# │ Fresh Rossoctl install on existing cluster                                   │
# └─────────────────────────────────────────────────────────────────────────────┘
./.github/scripts/local-setup/kind-full-test.sh --skip-cluster-create --clean-rossoctl --skip-cluster-destroy

# ┌─────────────────────────────────────────────────────────────────────────────┐
# │ Full CI run: create → deploy → test → destroy                               │
# └─────────────────────────────────────────────────────────────────────────────┘
./.github/scripts/local-setup/kind-full-test.sh

# ┌─────────────────────────────────────────────────────────────────────────────┐
# │ Cleanup: destroy cluster when done                                          │
# └─────────────────────────────────────────────────────────────────────────────┘
./.github/scripts/local-setup/kind-full-test.sh --include-cluster-destroy
```

### Running Individual Phases

Use `--include-<phase>` to run only specific phases:

```bash
# Create cluster only
./.github/scripts/local-setup/kind-full-test.sh --include-cluster-create

# Install Rossoctl only (on existing cluster)
./.github/scripts/local-setup/kind-full-test.sh --include-rossoctl-install

# Deploy agents only
./.github/scripts/local-setup/kind-full-test.sh --include-agents

# Run tests only
./.github/scripts/local-setup/kind-full-test.sh --include-test
```

## Accessing Services

### Service URLs

After deployment, services are available via `.localtest.me` domains:

| Service | URL |
|---------|-----|
| **Rossoctl UI** | http://rossoctl-ui.localtest.me:8080 |
| **Keycloak Admin** | http://keycloak.localtest.me:8080/admin |
| **Phoenix (Traces)** | http://phoenix.localtest.me:8080 _(only when `components.phoenix.enabled: true`)_ |
| **Kiali** | http://kiali.localtest.me:8080 |

> **Note:** `.localtest.me` is a special domain that resolves to 127.0.0.1

### Port Forwarding

If DNS resolution fails, use port forwarding:

```bash
# Access UI
kubectl port-forward -n rossoctl-system svc/http-istio 8080:80
# Visit: http://localhost:8080

# Access Keycloak
kubectl port-forward -n keycloak svc/keycloak 8081:80
# Visit: http://localhost:8081
```

### Show All Services

```bash
./.github/scripts/local-setup/show-services.sh
```

This displays:
- Service URLs
- Keycloak admin credentials
- Pod status
- Quick reference commands

## Running E2E Tests

### Full Test Suite

```bash
./.github/scripts/local-setup/kind-full-test.sh --include-test
```

### Manual Test Run

```bash
# Install test dependencies
uv sync

# Set config file
export ROSSOCTL_CONFIG_FILE=deployments/envs/dev_values.yaml

# Run tests
uv run pytest rossoctl/tests/e2e/ -v
```

### Run Specific Tests

```bash
# Run single test file
uv run pytest rossoctl/tests/e2e/test_agent_api.py -v

# Run tests matching pattern
uv run pytest rossoctl/tests/e2e/ -v -k "test_weather"
```

## Debugging

### Set Kubeconfig

```bash
export KUBECONFIG=~/.kube/config
```

### View Pod Status

```bash
# All pods
kubectl get pods -A

# Platform pods
kubectl get pods -n rossoctl-system

# Agent pods
kubectl get pods -n team1
```

### Check Logs

```bash
# Agent logs
kubectl logs -n team1 deployment/weather-service -f

# Operator logs
kubectl logs -n rossoctl-system deployment/operator -f

# Keycloak logs
kubectl logs -n keycloak deployment/keycloak -f
```

### Recent Events

```bash
kubectl get events -A --sort-by='.lastTimestamp' | tail -30
```

### Describe Resources

```bash
# Describe failing pod
kubectl describe pod -n team1 <pod-name>

# Check agent CRD
kubectl describe agent -n team1 weather-service
```

## Namespace Provisioning

### Adding New Team Namespaces

Namespaces are configured in Helm values:

```yaml
# deployments/envs/dev_values.yaml
charts:
  rossoctl:
    values:
      agentNamespaces:
        - team1
        - team2
        - my-new-team  # Add new namespace here
```

Re-run the installer to create the namespace with all required resources:

```bash
./.github/scripts/local-setup/kind-full-test.sh --skip-cluster-create --include-rossoctl-install --skip-cluster-destroy
```

### What Gets Created

Each agent namespace receives:

| Resource | Purpose |
|----------|---------|
| `authbridge-config` ConfigMap | AuthBridge + SPIRE configuration |
| `github-token-secret` | GitHub credentials |
| `github-shipwright-secret` | Build authentication |
| `ghcr-secret` | GHCR registry pull |
| `openai-secret` | OpenAI API key |
| `quay-registry-secret` | Quay.io registry |

Namespace labels:

```yaml
labels:
  rossoctl-enabled: "true"
  istio-discovery: enabled
  istio.io/dataplane-mode: ambient
```

### Updating Secrets on Running Cluster

```bash
# Update OpenAI key
export OPENAI_API_KEY="sk-..."

kubectl delete secret openai-secret -n team1 --ignore-not-found
kubectl create secret generic openai-secret -n team1 --from-literal=apikey="$OPENAI_API_KEY"

# Restart pods to pick up changes
kubectl rollout restart deployment/weather-service -n team1
kubectl rollout status deployment/weather-service -n team1
```

## Script Reference

### Platform Scripts (`scripts/kind/`)

| Script | Purpose |
|--------|---------|
| `setup-rossoctl.sh` | **Composable installer** — create cluster + deploy platform |
| `cleanup-rossoctl.sh` | Uninstall platform (optionally destroy cluster) |

### CI / Test Scripts (`.github/scripts/`)

| Script | Purpose |
|--------|---------|
| `local-setup/kind-full-test.sh` | Unified Kind test runner with phase control |
| `local-setup/show-services.sh` | Display all services, URLs, and credentials |
| `kind/create-cluster.sh` | Create Kind cluster |
| `kind/destroy-cluster.sh` | Delete Kind cluster |

### Phase Options (`kind-full-test.sh`)

| Option | Effect | Use Case |
|--------|--------|----------|
| `--skip-cluster-destroy` | Create, install, deploy, test | **Main flow**: keep cluster for debugging |
| `--include-cluster-destroy` | Destroy only | **Cleanup**: destroy cluster when done |
| (no options) | All phases | Full run (create → test → destroy) |
| `--skip-cluster-create --skip-cluster-destroy` | Install, deploy, test | Iterate on existing cluster |
| `--include-<phase>` | Selected phase(s) | Run specific phase(s) only |
| `--clean-rossoctl` | Uninstall before install | Fresh Rossoctl installation |

