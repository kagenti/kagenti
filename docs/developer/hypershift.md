# HyperShift Development Guide

This guide covers Kagenti development using HyperShift to create OpenShift clusters on AWS.

## Table of Contents

- [Prerequisites](#prerequisites)
- [One-Time Setup](#one-time-setup)
- [Naming Conventions](#naming-conventions)
- [Quick Start](#quick-start)
- [Main Testing Flow](#main-testing-flow)
- [Custom Cluster Suffixes](#custom-cluster-suffixes)
- [Running Individual Phases](#running-individual-phases)
- [Kubeconfig Management](#kubeconfig-management)
- [Accessing Services](#accessing-services)
- [Debugging](#debugging)
- [Script Reference](#script-reference)

## Prerequisites

| Requirement | Minimum | Purpose |
|-------------|---------|---------|
| AWS CLI | 2.x | AWS resource management |
| oc CLI | 4.19+ | OpenShift CLI |
| Bash | 3.2+ | Script execution |
| jq | Latest | JSON processing |
| Python | 3.11+ | E2E tests |
| uv | Latest | Python package manager |

<details>
<summary><b>macOS</b></summary>

```bash
brew install awscli jq python@3.11

# OpenShift CLI
brew install openshift-cli

# uv
curl -LsSf https://astral.sh/uv/install.sh | sh
```
</details>

<details>
<summary><b>Linux (Ubuntu/Debian)</b></summary>

```bash
# AWS CLI
curl "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o "awscliv2.zip"
unzip awscliv2.zip && sudo ./aws/install

# OpenShift CLI - download from https://console.redhat.com/openshift/downloads
# Or use mirror: https://mirror.openshift.com/pub/openshift-v4/clients/ocp/latest/

# Other tools
sudo apt-get update && sudo apt-get install -y jq python3.11 python3.11-venv

# uv
curl -LsSf https://astral.sh/uv/install.sh | sh
```
</details>

<details>
<summary><b>Linux (Fedora/RHEL)</b></summary>

```bash
# AWS CLI
curl "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o "awscliv2.zip"
unzip awscliv2.zip && sudo ./aws/install

# OpenShift CLI
sudo dnf install -y openshift-clients

# Other tools
sudo dnf install -y jq python3.11

# uv
curl -LsSf https://astral.sh/uv/install.sh | sh
```
</details>

### Required Access

- **AWS**: Admin access for one-time credential setup, scoped credentials for daily use
- **Management Cluster**: cluster-admin access to the HyperShift management cluster

## One-Time Setup

### Step 1: Set AWS Admin Credentials

```bash
export AWS_ACCESS_KEY_ID="<your-admin-access-key>"
export AWS_SECRET_ACCESS_KEY="<your-admin-secret-key>"
export AWS_REGION="us-east-1"  # optional, defaults to us-east-1
```

### Step 2: Login to Management Cluster

```bash
export KUBECONFIG=~/.kube/hypershift_mgmt
oc login https://api.management-cluster.example.com:6443 ...
```

### Step 3: Create Scoped Credentials

```bash
# Creates IAM user + OCP service account for cluster management
./.github/scripts/hypershift/setup-hypershift-ci-credentials.sh

# Output: .env.kagenti-hypershift-custom (contains scoped credentials)
```

### Step 4: Install hcp CLI and Ansible

```bash
./.github/scripts/hypershift/local-setup.sh
```

### Step 5: Verify Setup

```bash
source .env.kagenti-hypershift-custom
./.github/scripts/hypershift/preflight-check.sh
```

## Naming Conventions

| Component | Default | Example |
|-----------|---------|---------|
| MANAGED_BY_TAG | `kagenti-hypershift-custom` | Prefix for all resources |
| .env file | `.env.kagenti-hypershift-custom` | Contains scoped credentials |
| Cluster suffix | `$USER` | Your username (e.g., `ladas`) |
| Full cluster name | `<MANAGED_BY_TAG>-<suffix>` | `kagenti-hypershift-custom-ladas` |

Customize the cluster suffix by passing it as an argument.

## Quick Start

```bash
# Source credentials
source .env.kagenti-hypershift-custom

# Deploy cluster with Kagenti and run tests
./.github/scripts/local-setup/hypershift-full-test.sh --skip-cluster-destroy

# Show service URLs and credentials
./.github/scripts/local-setup/show-services.sh
```

## Main Testing Flow

### Step 1: Deploy and Test (Keep Cluster)

```bash
# Source credentials
source .env.kagenti-hypershift-custom

# Create cluster → deploy Kagenti → run tests → keep cluster for debugging
./.github/scripts/local-setup/hypershift-full-test.sh --skip-cluster-destroy

# Show services and credentials
./.github/scripts/local-setup/show-services.sh
```

### Step 2: Destroy When Done

```bash
./.github/scripts/local-setup/hypershift-full-test.sh --include-cluster-destroy
```

### Full CI Run (Create → Test → Destroy)

```bash
./.github/scripts/local-setup/hypershift-full-test.sh
```

This takes approximately 50 minutes.

## Custom Cluster Suffixes

Use custom suffixes for testing specific PRs or features:

```bash
# Custom suffix: creates kagenti-hypershift-custom-pr529
./.github/scripts/local-setup/hypershift-full-test.sh pr529 --skip-cluster-destroy

# Show services for custom cluster
./.github/scripts/local-setup/show-services.sh pr529

# Destroy custom cluster
./.github/scripts/local-setup/hypershift-full-test.sh pr529 --include-cluster-destroy
```

### More Examples

```bash
# Feature testing
./.github/scripts/local-setup/hypershift-full-test.sh feature1 --skip-cluster-destroy
# Creates: kagenti-hypershift-custom-feature1

# Iterate on existing cluster
./.github/scripts/local-setup/hypershift-full-test.sh --skip-cluster-create --skip-cluster-destroy

# Fresh Kagenti on existing cluster
./.github/scripts/local-setup/hypershift-full-test.sh --skip-cluster-create --clean-kagenti --skip-cluster-destroy
```

## Running Individual Phases

Use `--include-<phase>` to run only specific phases:

```bash
# Create cluster only
./.github/scripts/local-setup/hypershift-full-test.sh --include-cluster-create

# Install Kagenti only (on existing cluster)
./.github/scripts/local-setup/hypershift-full-test.sh --include-kagenti-install

# Deploy agents only
./.github/scripts/local-setup/hypershift-full-test.sh --include-agents

# Run tests only
./.github/scripts/local-setup/hypershift-full-test.sh --include-test

# Uninstall Kagenti only
./.github/scripts/local-setup/hypershift-full-test.sh --include-kagenti-uninstall

# Destroy cluster only
./.github/scripts/local-setup/hypershift-full-test.sh --include-cluster-destroy

# Combine phases: create + install only
./.github/scripts/local-setup/hypershift-full-test.sh --include-cluster-create --include-kagenti-install
```

## Kubeconfig Management

### Kubeconfig Locations

HyperShift hosted cluster kubeconfigs are stored at:

```
~/clusters/hcp/<MANAGED_BY_TAG>-<cluster-suffix>/auth/kubeconfig
```

Examples:
- `~/clusters/hcp/kagenti-hypershift-custom-ladas/auth/kubeconfig`
- `~/clusters/hcp/kagenti-hypershift-custom-pr529/auth/kubeconfig`

### Using the Kubeconfig

```bash
# Set for your cluster
export KUBECONFIG=~/clusters/hcp/kagenti-hypershift-custom-$USER/auth/kubeconfig

# Or for custom suffix
export KUBECONFIG=~/clusters/hcp/kagenti-hypershift-custom-pr529/auth/kubeconfig

# Verify connection
oc get nodes
```

### Management vs Hosted Cluster

| Cluster | Purpose | Kubeconfig |
|---------|---------|------------|
| **Management** | Create/destroy hosted clusters | `~/.kube/hypershift_mgmt` |
| **Hosted** | Run Kagenti platform | `~/clusters/hcp/<cluster-name>/auth/kubeconfig` |

The scripts automatically switch between kubeconfigs as needed.

## Accessing Services

### Show All Services

```bash
# Default cluster
./.github/scripts/local-setup/show-services.sh

# Custom suffix
./.github/scripts/local-setup/show-services.sh pr529
```

### Service Routes

After deployment, services are available via OpenShift routes:

| Service | How to Find URL |
|---------|-----------------|
| **Kagenti UI** | `oc get route -n kagenti-system kagenti-ui` |
| **Keycloak Admin** | `oc get route -n keycloak keycloak` |
| **Phoenix (Traces)** | `oc get route -n kagenti-system phoenix` |
| **Kiali** | `oc get route -n istio-system kiali` |
| **OpenShift Console** | `oc get route -n openshift-console console` |

### Get kubeadmin Password

```bash
cat ~/clusters/hcp/<cluster-name>/auth/kubeadmin-password
```

## Debugging

### Set Kubeconfig for Hosted Cluster

```bash
export KUBECONFIG=~/clusters/hcp/kagenti-hypershift-custom-$USER/auth/kubeconfig
```

### View Pod Status

```bash
oc get pods -A
oc get pods -n kagenti-system
oc get pods -n team1
```

### Check Logs

```bash
# Agent logs
oc logs -n team1 deployment/weather-service -f

# Operator logs
oc logs -n kagenti-system deployment/kagenti-operator -f
```

### Debug AWS Resources

Find orphaned AWS resources for a cluster (read-only):

```bash
source .env.kagenti-hypershift-custom
./.github/scripts/hypershift/debug-aws-hypershift.sh

# For custom suffix
./.github/scripts/hypershift/debug-aws-hypershift.sh pr529
```

### Check AWS Quotas

```bash
./.github/scripts/hypershift/check-quotas.sh
```

### Recent Events

```bash
oc get events -A --sort-by='.lastTimestamp' | tail -30
```

## Script Reference

### Entry Point Scripts

| Script | Purpose |
|--------|---------|
| `hypershift-full-test.sh [suffix]` | Unified HyperShift test runner with phase control |
| `show-services.sh [suffix]` | Display all services, URLs, and credentials |

### HyperShift Scripts (`.github/scripts/hypershift/`)

| Script | Purpose |
|--------|---------|
| `create-cluster.sh [suffix]` | Create HyperShift cluster (~10-15 min) |
| `destroy-cluster.sh [suffix]` | Destroy HyperShift cluster (~10 min) |
| `setup-hypershift-ci-credentials.sh` | One-time AWS/OCP credential setup |
| `local-setup.sh` | Install hcp CLI and ansible collections |
| `preflight-check.sh` | Verify prerequisites |
| `debug-aws-hypershift.sh [suffix]` | Find orphaned AWS resources (read-only) |
| `check-quotas.sh` | Check AWS service quotas |

### Phase Options

| Option | Effect | Use Case |
|--------|--------|----------|
| `--skip-cluster-destroy` | Create, install, deploy, test | **Main flow**: keep cluster for debugging |
| `--include-cluster-destroy` | Destroy only | **Cleanup**: destroy cluster when done |
| (no options) | All phases | Full run (create → test → destroy) |
| `--skip-cluster-create --skip-cluster-destroy` | Install, deploy, test | Iterate on existing cluster |
| `--include-<phase>` | Selected phase(s) | Run specific phase(s) only |
| `--clean-kagenti` | Uninstall before install | Fresh Kagenti installation |
| `[suffix]` | Custom cluster name | Use suffix instead of $USER |

## Credentials Parity with CI

| GitHub Secret | .env Variable | Cluster Secret |
|---------------|---------------|----------------|
| `OPENAI_API_KEY` | `OPENAI_API_KEY` | `openai-secret` |
| `GITHUB_TOKEN` | `GITHUB_TOKEN_VALUE` | `github-token-secret` |
| `AWS_ACCESS_KEY_ID` | `AWS_ACCESS_KEY_ID` | (used for cluster ops) |
| `AWS_SECRET_ACCESS_KEY` | `AWS_SECRET_ACCESS_KEY` | (used for cluster ops) |

