# OpenShift Development Guide

This guide covers Kagenti development on standard OpenShift (RHOCP) clusters.

> **Note:** This guide is for existing OpenShift clusters. To create new clusters on AWS, see [HyperShift Development Guide](./hypershift.md).

## Table of Contents

- [Prerequisites](#prerequisites)
- [Quick Start](#quick-start)
- [Login and Authentication](#login-and-authentication)
- [Deployment Options](#deployment-options)
- [Full Deployment Workflow](#full-deployment-workflow)
- [Step-by-Step Deployment](#step-by-step-deployment)
- [Accessing Services](#accessing-services)
- [Debugging](#debugging)
- [Namespace Provisioning](#namespace-provisioning)
- [Script Reference](#script-reference)

## Prerequisites

| Requirement | Minimum | Notes |
|-------------|---------|-------|
| oc CLI | 4.19+ | [OpenShift CLI](https://docs.openshift.com/container-platform/latest/cli_reference/openshift_cli/getting-started-cli.html) |
| kubectl | 1.28+ | Usually bundled with oc |
| Helm | 3.12+ | `brew install helm` |
| Python | 3.11+ | For E2E tests |
| uv | Latest | `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| jq | Latest | `brew install jq` |

### Required Access

- **OpenShift cluster-admin** access to the target cluster

## Quick Start

```bash
# Login to your OpenShift cluster
oc login https://api.your-cluster.example.com:6443 -u kubeadmin -p <password>

# Deploy and test (skip cluster create/destroy since cluster already exists)
./.github/scripts/local-setup/hypershift-full-test.sh \
    --skip-cluster-create --skip-cluster-destroy

# Show service URLs and credentials
./.github/scripts/local-setup/show-services.sh
```

## Login and Authentication

### Using kubeadmin

```bash
oc login https://api.your-cluster.example.com:6443 -u kubeadmin -p <password>
```

### Using OAuth Token

```bash
# Get token from OpenShift Console: User Menu → Copy Login Command
oc login --token=sha256~xxxxx --server=https://api.your-cluster.example.com:6443
```

### Verify Connection

```bash
oc whoami
oc get nodes
```

## Deployment Options

### Option A: Unified Test Runner (Recommended)

Use the HyperShift test runner with cluster operations skipped:

```bash
oc login https://api.your-cluster.example.com:6443 -u kubeadmin -p <password>

# Full Kagenti test cycle (no cluster create/destroy)
./.github/scripts/local-setup/hypershift-full-test.sh \
    --skip-cluster-create --skip-cluster-destroy
```

### Option B: Step-by-Step (Manual Control)

For more control over individual deployment phases, use the step-by-step approach below.

## Full Deployment Workflow

The unified test runner executes these phases:

```
Phase 1: Create Cluster     → SKIPPED (cluster already exists)
Phase 2: Install Kagenti Platform
Phase 3: Deploy Test Agents
Phase 4: Run E2E Tests
Phase 5: Kagenti Uninstall  → optional
Phase 6: Destroy Cluster    → SKIPPED (cluster is persistent)
```

### Common Workflows

```bash
# ┌─────────────────────────────────────────────────────────────────────────────┐
# │ First-time deployment: install → deploy agents → test                       │
# └─────────────────────────────────────────────────────────────────────────────┘
./.github/scripts/local-setup/hypershift-full-test.sh \
    --skip-cluster-create --skip-cluster-destroy

# ┌─────────────────────────────────────────────────────────────────────────────┐
# │ Iterate on existing deployment (skip install)                               │
# └─────────────────────────────────────────────────────────────────────────────┘
./.github/scripts/local-setup/hypershift-full-test.sh \
    --skip-cluster-create --skip-kagenti-install --skip-cluster-destroy

# ┌─────────────────────────────────────────────────────────────────────────────┐
# │ Fresh Kagenti install (clean existing, then install)                        │
# └─────────────────────────────────────────────────────────────────────────────┘
./.github/scripts/local-setup/hypershift-full-test.sh \
    --skip-cluster-create --clean-kagenti --skip-cluster-destroy

# ┌─────────────────────────────────────────────────────────────────────────────┐
# │ Run tests only                                                              │
# └─────────────────────────────────────────────────────────────────────────────┘
./.github/scripts/local-setup/hypershift-full-test.sh --include-test

# ┌─────────────────────────────────────────────────────────────────────────────┐
# │ Uninstall Kagenti                                                           │
# └─────────────────────────────────────────────────────────────────────────────┘
./.github/scripts/local-setup/hypershift-full-test.sh --include-kagenti-uninstall
```

## Step-by-Step Deployment

For manual control using the Ansible installer directly:

### Step 1: Login to Cluster

```bash
oc login https://api.your-cluster.example.com:6443 -u kubeadmin -p <password>
```

### Step 2: Configure Secrets

```bash
# Copy and edit secrets file
cp deployments/envs/secret_values.yaml.example deployments/envs/.secret_values.yaml
vi deployments/envs/.secret_values.yaml
```

Required values:

```yaml
charts:
  kagenti:
    values:
      secrets:
        openaiApiKey: "sk-..."      # Required for LLM features
        githubUser: "your-username"  # Required for Shipwright builds
        githubToken: "ghp_..."       # Required for private repos
```

### Step 3: Install Kagenti Platform

```bash
# Run the Ansible installer for OpenShift
deployments/ansible/run-install.sh --env ocp
```

The installer will:
- Deploy Kagenti platform components
- Configure Istio Ambient mesh
- Set up Keycloak authentication
- Create agent namespaces (team1, team2)

### Step 4: Verify Installation

```bash
# Check platform pods
oc get pods -n kagenti-system

# Check Keycloak
oc get pods -n keycloak

# Check CRDs are available
oc get crds | grep kagenti
```

### Step 5: Deploy Example Agents (Optional)

To deploy the example weather agent for testing:

```bash
# Apply the weather agent example
oc apply -f kagenti/examples/weather-agent/ -n team1

# Wait for deployment
oc rollout status deployment/weather-service -n team1
```

### Step 6: Run E2E Tests (Optional)

```bash
# Get the agent URL from the route
export AGENT_URL="https://$(oc get route -n team1 weather-service -o jsonpath='{.spec.host}')"
export KAGENTI_CONFIG_FILE=deployments/envs/ocp_values.yaml

# Run tests
uv run pytest kagenti/tests/e2e/ -v
```

## Accessing Services

### Show All Services

```bash
./.github/scripts/local-setup/show-services.sh
```

### Get Route URLs

```bash
# Kagenti UI
oc get route -n kagenti-system kagenti-ui -o jsonpath='{.spec.host}'

# Keycloak Admin
oc get route -n keycloak keycloak -o jsonpath='{.spec.host}'

# Phoenix (Traces)
oc get route -n kagenti-system phoenix -o jsonpath='{.spec.host}'

# Kiali
oc get route -n istio-system kiali -o jsonpath='{.spec.host}'

# OpenShift Console
oc get route -n openshift-console console -o jsonpath='{.spec.host}'
```

### Services Table

| Service | Route Command | Auth |
|---------|---------------|------|
| **Kagenti UI** | `oc get route -n kagenti-system kagenti-ui` | Keycloak |
| **Keycloak Admin** | `oc get route -n keycloak keycloak` | Keycloak admin |
| **Phoenix** | `oc get route -n kagenti-system phoenix` | None |
| **Kiali** | `oc get route -n istio-system kiali` | kubeadmin |
| **OpenShift Console** | `oc get route -n openshift-console console` | kubeadmin |

### Get Keycloak Credentials

```bash
oc get secret -n keycloak keycloak-initial-admin \
    -o jsonpath='{.data.username}' | base64 -d && echo
oc get secret -n keycloak keycloak-initial-admin \
    -o jsonpath='{.data.password}' | base64 -d && echo
```

## Debugging

### View Pod Status

```bash
# All pods
oc get pods -A

# Platform pods
oc get pods -n kagenti-system

# Agent pods
oc get pods -n team1

# Keycloak pods
oc get pods -n keycloak
```

### Check Logs

```bash
# Agent logs
oc logs -n team1 deployment/weather-service -f

# Operator logs
oc logs -n kagenti-system deployment/kagenti-operator -f

# Keycloak logs
oc logs -n keycloak deployment/keycloak -f
```

### Recent Events

```bash
oc get events -A --sort-by='.lastTimestamp' | tail -30
```

### Describe Resources

```bash
# Describe failing pod
oc describe pod -n team1 <pod-name>

# Check agent CRD
oc describe agent -n team1 weather-service

# Check route
oc describe route -n team1 weather-service
```

### Check Route Status

```bash
# All routes
oc get routes -A

# Route details
oc get route -n team1 weather-service -o yaml
```

## Namespace Provisioning

### Adding New Team Namespaces

Namespaces are configured in Helm values:

```yaml
# deployments/envs/ocp_values.yaml
charts:
  kagenti:
    values:
      agentNamespaces:
        - team1
        - team2
        - my-new-team  # Add new namespace here
```

Re-run the installer:

```bash
deployments/ansible/run-install.sh --env ocp
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
  istio.io/use-waypoint: waypoint
  shared-gateway-access: "true"
```

### Updating Secrets on Running Cluster

```bash
# Update OpenAI key
export OPENAI_API_KEY="sk-..."

oc delete secret openai-secret -n team1 --ignore-not-found
oc create secret generic openai-secret -n team1 --from-literal=apikey="$OPENAI_API_KEY"

# Restart pods to pick up changes
oc rollout restart deployment/weather-service -n team1
oc rollout status deployment/weather-service -n team1
```

## Script Reference

### Entry Point Scripts

| Script | Purpose |
|--------|---------|
| `hypershift-full-test.sh` | Unified test runner (use with `--skip-cluster-*`) |
| `show-services.sh` | Display all services, URLs, and credentials |

### Ansible Installer (`deployments/ansible/`)

| Script | Purpose |
|--------|---------|
| `run-install.sh --env ocp` | Install Kagenti platform on OpenShift |
| `cleanup-install.sh` | Uninstall Kagenti platform |

See [Ansible README](../../deployments/ansible/README.md) for advanced options.

### Phase Options (for hypershift-full-test.sh)

| Option | Effect | Use Case |
|--------|--------|----------|
| `--skip-cluster-create --skip-cluster-destroy` | Install, deploy, test | **OpenShift standard flow** |
| `--include-kagenti-install` | Install only | Install Kagenti platform |
| `--include-agents` | Deploy only | Deploy example agents |
| `--include-test` | Test only | Run E2E tests |
| `--include-kagenti-uninstall` | Uninstall only | Remove Kagenti platform |
| `--clean-kagenti` | Uninstall before install | Fresh Kagenti installation |

## Environment Comparison

| Feature | Kind | OpenShift | HyperShift |
|---------|------|-----------|------------|
| **Entry Script** | `kind-full-test.sh` | `hypershift-full-test.sh --skip-cluster-*` | `hypershift-full-test.sh` |
| **SPIRE** | Vanilla | ZTWIM Operator | ZTWIM Operator |
| **Values File** | `dev_values.yaml` | `ocp_values.yaml` | `ocp_values.yaml` |
| **Cluster Lifecycle** | Persistent | Persistent | Create/Destroy |
| **AWS Required** | No | No | Yes |
| **Min OCP Version** | N/A | 4.19+ | 4.19+ |

## Future Documentation (TODO)

> **NOTE:** The following documentation is planned:

- **CRD Reference** - Full schema documentation for AgentCard, Build CRDs with required vs optional fields and `kubectl explain` examples
- **Agent Instrumentation** - OTEL endpoint `http://otel-collector.kagenti-system.svc.cluster.local:8335`, environment variables, A2A SDK telemetry decorators
- **Istio Ambient Security** - L4-only policies with ztunnel, when waypoint proxies are needed for L7, AuthorizationPolicy examples
