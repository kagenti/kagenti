# HyperShift Development Guide

This guide covers Kagenti development using HyperShift to create OpenShift clusters on AWS.

## Table of Contents

- [Prerequisites](#prerequisites)
- [One-Time Setup](#one-time-setup)
- [Quick Start](#quick-start)
- [Management Cluster Operations](#management-cluster-operations)
- [Hosted Cluster Operations](#hosted-cluster-operations)
- [Script Reference](#script-reference)

---

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
# AWS CLI (via snap)
sudo snap install aws-cli --classic

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
sudo dnf install -y awscli2

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

---

## One-Time Setup

These steps run on the **management cluster** and only need to be done once.

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

### Step 5: Setup Autoscaling (Optional)

```bash
./.github/scripts/hypershift/setup-autoscaling.sh
```

### Step 6: Verify Setup

```bash
source .env.kagenti-hypershift-custom
./.github/scripts/hypershift/preflight-check.sh
```

### Naming Conventions

| Component | Default | Example |
|-----------|---------|---------|
| MANAGED_BY_TAG | `kagenti-hypershift-custom` | Prefix for all resources |
| .env file | `.env.kagenti-hypershift-custom` | Contains scoped credentials |
| Cluster suffix | `$USER` | Your username (e.g., `ladas`) |
| Full cluster name | `<MANAGED_BY_TAG>-<suffix>` | `kagenti-hypershift-custom-ladas` |

Customize the cluster suffix by passing it as an argument.

---

## Quick Start

After one-time setup, this is the typical development flow:

```bash
# 1. Source credentials
source .env.kagenti-hypershift-custom

# 2. Create cluster, deploy Kagenti, run tests (keep cluster for debugging)
./.github/scripts/local-setup/hypershift-full-test.sh --skip-cluster-destroy

# 3. Show service URLs and credentials
./.github/scripts/local-setup/show-services.sh

# 4. When done, destroy the cluster
./.github/scripts/local-setup/hypershift-full-test.sh --include-cluster-destroy
```

### Custom Cluster Suffix

```bash
# Create cluster with custom suffix (e.g., for PR testing)
./.github/scripts/local-setup/hypershift-full-test.sh pr529 --skip-cluster-destroy

# Show services for that cluster
./.github/scripts/local-setup/show-services.sh pr529

# Destroy when done
./.github/scripts/local-setup/hypershift-full-test.sh pr529 --include-cluster-destroy
```

### Common Workflows

```bash
# Full run: create → deploy → test → destroy (~50 min)
./.github/scripts/local-setup/hypershift-full-test.sh

# Iterate on existing cluster (skip create/destroy)
./.github/scripts/local-setup/hypershift-full-test.sh --skip-cluster-create --skip-cluster-destroy

# Fresh Kagenti install on existing cluster
./.github/scripts/local-setup/hypershift-full-test.sh --skip-cluster-create --clean-kagenti --skip-cluster-destroy
```

---

## Management Cluster Operations

Operations that run on the **management cluster** (where HyperShift operator runs).

**Kubeconfig:** `~/.kube/hypershift_mgmt`

### Check AWS Quotas

Before creating clusters, verify you have sufficient AWS quota:

```bash
source .env.kagenti-hypershift-custom
./.github/scripts/hypershift/check-quotas.sh
```

### Create Hosted Cluster

```bash
source .env.kagenti-hypershift-custom

# Default cluster (uses $USER as suffix)
./.github/scripts/local-setup/hypershift-full-test.sh --include-cluster-create

# Custom suffix
./.github/scripts/local-setup/hypershift-full-test.sh pr529 --include-cluster-create
```

Cluster creation takes ~10-15 minutes.

### Destroy Hosted Cluster

```bash
source .env.kagenti-hypershift-custom

# Default cluster
./.github/scripts/local-setup/hypershift-full-test.sh --include-cluster-destroy

# Custom suffix
./.github/scripts/local-setup/hypershift-full-test.sh pr529 --include-cluster-destroy
```

### Debug AWS Resources

Find orphaned AWS resources for a cluster (read-only):

```bash
source .env.kagenti-hypershift-custom

# Default cluster
./.github/scripts/hypershift/debug-aws-hypershift.sh

# Custom suffix
./.github/scripts/hypershift/debug-aws-hypershift.sh pr529
```

### Setup Autoscaling

Configure management cluster and nodepool autoscaling:

```bash
./.github/scripts/hypershift/setup-autoscaling.sh
```

---

## Hosted Cluster Operations

Operations that run on the **hosted cluster** (where Kagenti platform runs).

**Kubeconfig:** `~/clusters/hcp/<cluster-name>/auth/kubeconfig`

### Kubeconfig Management

Hosted cluster kubeconfigs are stored at:

```
~/clusters/hcp/<MANAGED_BY_TAG>-<cluster-suffix>/auth/kubeconfig
```

Examples:
- `~/clusters/hcp/kagenti-hypershift-custom-ladas/auth/kubeconfig`
- `~/clusters/hcp/kagenti-hypershift-custom-pr529/auth/kubeconfig`

```bash
# Set kubeconfig for your cluster
export KUBECONFIG=~/clusters/hcp/kagenti-hypershift-custom-$USER/auth/kubeconfig

# Or for custom suffix
export KUBECONFIG=~/clusters/hcp/kagenti-hypershift-custom-pr529/auth/kubeconfig

# Verify connection
oc get nodes
```

### Cluster Comparison

| Cluster | Purpose | Kubeconfig |
|---------|---------|------------|
| **Management** | Create/destroy hosted clusters | `~/.kube/hypershift_mgmt` |
| **Hosted** | Run Kagenti platform | `~/clusters/hcp/<cluster-name>/auth/kubeconfig` |

The scripts automatically switch between kubeconfigs as needed.

### Install Kagenti Platform

```bash
./.github/scripts/local-setup/hypershift-full-test.sh --include-kagenti-install
```

### Deploy Test Agents

```bash
./.github/scripts/local-setup/hypershift-full-test.sh --include-agents
```

### Run E2E Tests

```bash
./.github/scripts/local-setup/hypershift-full-test.sh --include-test
```

### Uninstall Kagenti

```bash
./.github/scripts/local-setup/hypershift-full-test.sh --include-kagenti-uninstall
```

### Access Services

```bash
# Show all services, URLs, and credentials
./.github/scripts/local-setup/show-services.sh

# For custom suffix
./.github/scripts/local-setup/show-services.sh pr529
```

Service routes:

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

### Debug Pods and Logs

```bash
# View pod status
oc get pods -A
oc get pods -n kagenti-system
oc get pods -n team1

# Check logs
oc logs -n team1 deployment/weather-service -f
oc logs -n kagenti-system deployment/kagenti-operator -f

# Recent events
oc get events -A --sort-by='.lastTimestamp' | tail -30
```

---

## Script Reference

### Entry Point Scripts

| Script | Purpose |
|--------|---------|
| `hypershift-full-test.sh [suffix]` | Unified test runner with phase control |
| `show-services.sh [suffix]` | Display all services, URLs, and credentials |

### Management Cluster Scripts (`.github/scripts/hypershift/`)

| Script | Purpose |
|--------|---------|
| `create-cluster.sh [suffix]` | Create HyperShift cluster (~10-15 min) |
| `destroy-cluster.sh [suffix]` | Destroy HyperShift cluster (~10 min) |
| `setup-hypershift-ci-credentials.sh` | One-time AWS/OCP credential setup |
| `local-setup.sh` | Install hcp CLI and ansible collections |
| `preflight-check.sh` | Verify prerequisites |
| `check-quotas.sh` | Check AWS service quotas |
| `setup-autoscaling.sh` | Configure autoscaling |
| `debug-aws-hypershift.sh [suffix]` | Find orphaned AWS resources (read-only) |

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

### Credentials Parity with CI

| GitHub Secret | .env Variable | Cluster Secret |
|---------------|---------------|----------------|
| `OPENAI_API_KEY` | `OPENAI_API_KEY` | `openai-secret` |
| `GITHUB_TOKEN` | `GITHUB_TOKEN_VALUE` | `github-token-secret` |
| `AWS_ACCESS_KEY_ID` | `AWS_ACCESS_KEY_ID` | (used for cluster ops) |
| `AWS_SECRET_ACCESS_KEY` | `AWS_SECRET_ACCESS_KEY` | (used for cluster ops) |
