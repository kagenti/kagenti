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

| Requirement | Minimum | Notes |
|-------------|---------|-------|
| Docker | 12GB RAM, 4 cores | Required for Kind |
| Kind | Latest | `brew install kind` or [kind.sigs.k8s.io](https://kind.sigs.k8s.io/) |
| kubectl | 1.28+ | `brew install kubectl` |
| Helm | 3.12+ | `brew install helm` |
| Python | 3.11+ | For E2E tests |
| uv | Latest | `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| jq | Latest | `brew install jq` |

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

### Option 1: Secrets File (Recommended)

```bash
# Copy the example file
cp deployments/envs/secret_values.yaml.example deployments/envs/.secret_values.yaml

# Edit with your values
vi deployments/envs/.secret_values.yaml
```

Required values:

```yaml
charts:
  kagenti:
    values:
      secrets:
        # Required for agent LLM features
        openaiApiKey: "sk-..."

        # Required for private repos and Shipwright builds
        githubUser: "your-username"
        githubToken: "ghp_..."
```

### Option 2: Environment Variables

```bash
export OPENAI_API_KEY="sk-..."
export GITHUB_USER="your-username"
export GITHUB_TOKEN_VALUE="ghp_..."

# Force regeneration from env vars
rm -f deployments/envs/.secret_values.yaml
```

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

| Option | Runs | Use Case |
|--------|------|----------|
| `--skip-cluster-destroy` | 1-4 | **Main flow**: run tests, keep cluster |
| `--include-cluster-destroy` | 6 | **Cleanup**: destroy cluster when done |
| (no options) | 1-4,6 | Full CI run (create + test + destroy) |
| `--skip-cluster-create --skip-cluster-destroy` | 2-4 | Iterate on existing cluster |
| `--include-<phase>` | selected | Run specific phase(s) only |
| `--clean-kagenti` | - | Uninstall Kagenti before installing |

## Future Documentation (TODO)

> **NOTE:** The following documentation is planned:

- **CRD Reference** - Full schema documentation for AgentCard, Build CRDs with required vs optional fields and `kubectl explain` examples
- **Agent Instrumentation** - OTEL endpoint `http://otel-collector.kagenti-system.svc.cluster.local:8335`, environment variables, A2A SDK telemetry decorators
- **Istio Ambient Security** - L4-only policies with ztunnel, when waypoint proxies are needed for L7, AuthorizationPolicy examples
