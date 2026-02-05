# Kind Development Guide

This guide covers local Kagenti development using Kind (Kubernetes in Docker).

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
# One command to deploy everything and run tests
./.github/scripts/local-setup/kind-full-test.sh --skip-cluster-destroy

# Show service URLs and credentials
./.github/scripts/local-setup/show-services.sh
```

Access the UI at: **http://kagenti-ui.localtest.me:8080**

Login with Keycloak admin credentials shown by `show-services.sh`.

## Credentials Setup

See [Common Setup](./README.md#common-setup-all-environments) for credentials configuration.

## Full Deployment Workflow

The `kind-full-test.sh` script runs 6 phases:

```
Phase 1: Create Kind Cluster
Phase 2: Install Kagenti Platform
Phase 3: Deploy Test Agents
Phase 4: Run E2E Tests
Phase 5: Kagenti Uninstall (optional)
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
# │ Fresh Kagenti install on existing cluster                                   │
# └─────────────────────────────────────────────────────────────────────────────┘
./.github/scripts/local-setup/kind-full-test.sh --skip-cluster-create --clean-kagenti --skip-cluster-destroy

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

# Install Kagenti only (on existing cluster)
./.github/scripts/local-setup/kind-full-test.sh --include-kagenti-install

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
| **Kagenti UI** | http://kagenti-ui.localtest.me:8080 |
| **Keycloak Admin** | http://keycloak.localtest.me:8080/admin |
| **Phoenix (Traces)** | http://phoenix.localtest.me:8080 |
| **Kiali** | http://kiali.localtest.me:8080 |

> **Note:** `.localtest.me` is a special domain that resolves to 127.0.0.1

### Port Forwarding

If DNS resolution fails, use port forwarding:

```bash
# Access UI
kubectl port-forward -n kagenti-system svc/http-istio 8080:80
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
export KAGENTI_CONFIG_FILE=deployments/envs/dev_values.yaml

# Run tests
uv run pytest kagenti/tests/e2e/ -v
```

### Run Specific Tests

```bash
# Run single test file
uv run pytest kagenti/tests/e2e/test_agent_api.py -v

# Run tests matching pattern
uv run pytest kagenti/tests/e2e/ -v -k "test_weather"
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
kubectl get pods -n kagenti-system

# Agent pods
kubectl get pods -n team1
```

### Check Logs

```bash
# Agent logs
kubectl logs -n team1 deployment/weather-service -f

# Operator logs
kubectl logs -n kagenti-system deployment/kagenti-operator -f

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
  kagenti:
    values:
      agentNamespaces:
        - team1
        - team2
        - my-new-team  # Add new namespace here
```

Re-run the installer to create the namespace with all required resources:

```bash
./.github/scripts/local-setup/kind-full-test.sh --skip-cluster-create --include-kagenti-install --skip-cluster-destroy
```

### What Gets Created

Each agent namespace receives:

| Resource | Purpose |
|----------|---------|
| `environments` ConfigMap | 8 environment presets (ollama, openai, mcp-weather, etc.) |
| `github-token-secret` | GitHub credentials |
| `github-shipwright-secret` | Build authentication |
| `ghcr-secret` | GHCR registry pull |
| `openai-secret` | OpenAI API key |
| `quay-registry-secret` | Quay.io registry |

Namespace labels:

```yaml
labels:
  kagenti-enabled: "true"
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

### Entry Point Scripts

| Script | Purpose |
|--------|---------|
| `kind-full-test.sh` | Unified Kind test runner with phase control |
| `show-services.sh` | Display all services, URLs, and credentials |

### Kind Scripts (`.github/scripts/kind/`)

| Script | Purpose |
|--------|---------|
| `create-cluster.sh` | Create Kind cluster |
| `destroy-cluster.sh` | Delete Kind cluster |
| `deploy-platform.sh` | Full Kagenti deployment |
| `run-e2e-tests.sh` | Run E2E test suite |
| `access-ui.sh` | Show service URLs and port-forward commands |

### Phase Options

| Option | Effect | Use Case |
|--------|--------|----------|
| `--skip-cluster-destroy` | Create, install, deploy, test | **Main flow**: keep cluster for debugging |
| `--include-cluster-destroy` | Destroy only | **Cleanup**: destroy cluster when done |
| (no options) | All phases | Full run (create → test → destroy) |
| `--skip-cluster-create --skip-cluster-destroy` | Install, deploy, test | Iterate on existing cluster |
| `--include-<phase>` | Selected phase(s) | Run specific phase(s) only |
| `--clean-kagenti` | Uninstall before install | Fresh Kagenti installation |

