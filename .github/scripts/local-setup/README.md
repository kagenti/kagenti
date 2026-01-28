# Local Testing & Deployment Scripts

Scripts for deploying and testing the Kagenti platform on Kind, OpenShift, or HyperShift.

All commands run from the **repo root** (no cd to other directories).

## Quick Start Commands

Choose your environment and copy the commands:

---

### Kind (Local Docker)

**Prerequisites**: Docker (12GB RAM, 4 cores), Kind, kubectl, Helm, Python 3.11+, jq

```bash
# ┌─────────────────────────────────────────────────────────────────────────────┐
# │ OPTION A: Unified test runner (recommended)                                 │
# └─────────────────────────────────────────────────────────────────────────────┘

# Full run: create cluster → deploy kagenti → test → destroy
./.github/scripts/local-setup/kind-full-test.sh

# Dev flow: run tests, keep cluster for debugging
./.github/scripts/local-setup/kind-full-test.sh --skip-cluster-destroy

# Iterate on existing cluster
./.github/scripts/local-setup/kind-full-test.sh --skip-cluster-create --skip-cluster-destroy

# Cleanup only
./.github/scripts/local-setup/kind-full-test.sh --include-cluster-destroy

# ┌─────────────────────────────────────────────────────────────────────────────┐
# │ OPTION B: Step-by-step (manual control)                                     │
# └─────────────────────────────────────────────────────────────────────────────┘

# Create cluster
./.github/scripts/kind/create-cluster.sh

# Deploy platform and agents
./.github/scripts/kind/deploy-platform.sh

# Run tests
./.github/scripts/kind/run-e2e-tests.sh

# Access UI
./.github/scripts/kind/access-ui.sh
kubectl port-forward -n kagenti-system svc/http-istio 8080:80
# Visit: http://kagenti-ui.localtest.me:8080

# Cleanup
./.github/scripts/kind/destroy-cluster.sh
```

---

### OpenShift (Standard RHOCP)

**Prerequisites**: oc CLI, OpenShift cluster-admin access

```bash
# ┌─────────────────────────────────────────────────────────────────────────────┐
# │ OPTION A: Use HyperShift runner (skipping cluster ops)                      │
# └─────────────────────────────────────────────────────────────────────────────┘
oc login https://api.your-cluster.example.com:6443 -u kubeadmin -p <password>

# Full kagenti test cycle (no cluster create/destroy)
./.github/scripts/local-setup/hypershift-full-test.sh \
    --skip-cluster-create --skip-cluster-destroy

# ┌─────────────────────────────────────────────────────────────────────────────┐
# │ OPTION B: Step-by-step (manual control)                                     │
# └─────────────────────────────────────────────────────────────────────────────┘
oc login https://api.your-cluster.example.com:6443 -u kubeadmin -p <password>

# Install Kagenti platform
./.github/scripts/kagenti-operator/30-run-installer.sh --env ocp
./.github/scripts/kagenti-operator/41-wait-crds.sh
./.github/scripts/kagenti-operator/42-apply-pipeline-template.sh
./.github/scripts/kagenti-operator/43-wait-toolhive-crds.sh

# Deploy agents and run E2E tests
./.github/scripts/kagenti-operator/71-build-weather-tool.sh
./.github/scripts/kagenti-operator/72-deploy-weather-tool.sh
./.github/scripts/kagenti-operator/73-patch-weather-tool.sh
./.github/scripts/kagenti-operator/74-deploy-weather-agent.sh

export AGENT_URL="https://$(oc get route -n team1 weather-service -o jsonpath='{.spec.host}')"
export KAGENTI_CONFIG_FILE=deployments/envs/ocp_values.yaml
./.github/scripts/kagenti-operator/90-run-e2e-tests.sh
```

---

### HyperShift (Ephemeral OpenShift)

**Prerequisites**: AWS CLI, oc CLI, bash 3.2+, jq

#### One-Time Setup

```bash
# Requires: AWS admin + OCP cluster-admin on management cluster
./.github/scripts/hypershift/setup-hypershift-ci-credentials.sh    # Creates IAM + .env.kagenti-hypershift-custom
./.github/scripts/hypershift/local-setup.sh                        # Installs hcp CLI + ansible
```

#### Naming Conventions

| Component | Local Default | CI Default |
|-----------|--------------|------------|
| MANAGED_BY_TAG | `kagenti-hypershift-custom` | `kagenti-hypershift-ci` |
| .env file | `.env.kagenti-hypershift-custom` | (from secrets) |
| Cluster suffix | `$USER` (e.g., `ladas`) | varies |
| Full cluster name | `kagenti-hypershift-custom-ladas` | `kagenti-hypershift-ci-<suffix>` |

Customize the cluster suffix by passing it as an argument (e.g., `pr529` → `kagenti-hypershift-custom-pr529`).

#### Main Testing Flow

```bash
# ┌─────────────────────────────────────────────────────────────────────────────┐
# │ STEP 1: Run tests, keep cluster for debugging                               │
# │         Default cluster: kagenti-hypershift-custom-$USER                     │
# └─────────────────────────────────────────────────────────────────────────────┘

# source the env created by setup-hypershift-ci-credentials.sh
source .env.kagenti-hypershift-custom

# Deploy the cluster with kagenti example stack
./.github/scripts/local-setup/hypershift-full-test.sh --skip-cluster-destroy

# Show services urls and credentials
./.github/scripts/local-setup/show-services.sh

# ┌─────────────────────────────────────────────────────────────────────────────┐
# │ STEP 2: When done - destroy cluster                                         │
# └─────────────────────────────────────────────────────────────────────────────┘
./.github/scripts/local-setup/hypershift-full-test.sh --include-cluster-destroy
```

#### Common Examples

```bash
# Default cluster (uses your username as suffix)
./.github/scripts/local-setup/hypershift-full-test.sh --skip-cluster-destroy
# Creates: kagenti-hypershift-custom-ladas

# ┌─────────────────────────────────────────────────────────────────────────────┐
# │ Custom cluster suffix - useful for testing specific PRs or features         │
# └─────────────────────────────────────────────────────────────────────────────┘
./.github/scripts/local-setup/hypershift-full-test.sh pr529 --skip-cluster-destroy
# Creates: kagenti-hypershift-custom-pr529 cluster

# Show services urls and credentials of the custom kagenti-hypershift-custom-pr529 cluster
./.github/scripts/local-setup/show-services.sh pr529

./.github/scripts/local-setup/hypershift-full-test.sh feature1 --skip-cluster-destroy
# Creates: kagenti-hypershift-custom-feature1

# Destroy specific cluster
./.github/scripts/local-setup/hypershift-full-test.sh pr529 --include-cluster-destroy

# ┌─────────────────────────────────────────────────────────────────────────────┐
# │ More examples                                        │
# └─────────────────────────────────────────────────────────────────────────────┘

# Full CI run: create → deploy → test → destroy (~50 min)
./.github/scripts/local-setup/hypershift-full-test.sh

# Iterate on existing cluster (skip create, keep cluster)
./.github/scripts/local-setup/hypershift-full-test.sh --skip-cluster-create --skip-cluster-destroy

# Fresh kagenti install on existing cluster
./.github/scripts/local-setup/hypershift-full-test.sh --skip-cluster-create --clean-kagenti --skip-cluster-destroy
```

#### Running Individual Phases

Use `--include-<phase>` to run only specific phases:

```bash
# Create cluster only
./.github/scripts/local-setup/hypershift-full-test.sh --include-cluster-create

# Install kagenti only (on existing cluster)
./.github/scripts/local-setup/hypershift-full-test.sh --include-kagenti-install

# Deploy agents only
./.github/scripts/local-setup/hypershift-full-test.sh --include-agents

# Run tests only
./.github/scripts/local-setup/hypershift-full-test.sh --include-test

# Uninstall kagenti only
./.github/scripts/local-setup/hypershift-full-test.sh --include-kagenti-uninstall

# Destroy cluster only
./.github/scripts/local-setup/hypershift-full-test.sh --include-cluster-destroy

# Combine phases: create + install only
./.github/scripts/local-setup/hypershift-full-test.sh --include-cluster-create --include-kagenti-install
```

---

## Debugging

Commands for debugging the deployed cluster. First, set the KUBECONFIG for your target cluster:

```bash
# For HyperShift - use the hosted cluster kubeconfig
export KUBECONFIG=~/clusters/hcp/kagenti-hypershift-custom-$USER/auth/kubeconfig

# For Kind
export KUBECONFIG=~/.kube/config

# For OpenShift - use oc login instead
oc login https://api.your-cluster.example.com:6443 -u kubeadmin -p <password>
```

Then run debugging commands:

```bash
# View pod status
kubectl get pods -A

# Check agent logs
kubectl logs -n team1 deployment/weather-service -f

# Check operator logs
kubectl logs -n kagenti-system deployment/kagenti-operator -f

# Recent events
kubectl get events -A --sort-by='.lastTimestamp' | tail -30
```

### HyperShift Setup & Debugging & Monitoring

#### Admin Operations (one-time setup)

Requires AWS admin credentials + management cluster admin access:

```bash
# Set up AWS admin credentials
export AWS_ACCESS_KEY_ID="<your-admin-access-key>"
export AWS_SECRET_ACCESS_KEY="<your-admin-secret-key>"
export AWS_REGION="us-east-1"  # optional, defaults to us-east-1

# Login to management cluster
export KUBECONFIG=~/.kube/hypershift_kagenti_ci
oc login ...

# Optional: customize the managed-by tag (drives naming of users, clusters, resources)
export MANAGED_BY_TAG="kagenti-hypershift-custom"  # default

# Create scoped AWS IAM user + OCP service account for cluster management
./.github/scripts/hypershift/setup-hypershift-ci-credentials.sh

# Optional: configure autoscaling
./.github/scripts/hypershift/setup-autoscaling.sh

# Optional: check AWS quotas
./.github/scripts/hypershift/check-quotas.sh
```

#### Debug Commands (with scoped credentials)

```bash
# Debug a specific cluster (e.g., pr529)
source .env.kagenti-hypershift-ci && ./.github/scripts/hypershift/debug-aws-hypershift.sh pr529
source .env.kagenti-hypershift-ci && ./.github/scripts/local-setup/show-services.sh pr529

# Debug default user cluster
source .env.kagenti-hypershift-custom && ./.github/scripts/hypershift/debug-aws-hypershift.sh
source .env.kagenti-hypershift-custom && ./.github/scripts/local-setup/show-services.sh
```

---

## Script Reference

### Entry Point Scripts (this directory)

| Script | Purpose |
|--------|---------|
| `kind-full-test.sh` | Unified Kind test runner (same interface as HyperShift) |
| `hypershift-full-test.sh` | Unified HyperShift test runner with phase control |
| `show-services.sh` | Display all services, URLs, and credentials (auto-detects Kind/OpenShift/HyperShift) |

### Kind Scripts (`.github/scripts/kind/`)

| Script | Purpose |
|--------|---------|
| `create-cluster.sh` | Create Kind cluster |
| `destroy-cluster.sh` | Delete Kind cluster |
| `deploy-platform.sh` | Full Kagenti deployment on Kind |
| `run-e2e-tests.sh` | Run E2E test suite |
| `access-ui.sh` | Show service URLs and port-forward commands |

### Kagenti Operator Scripts (`.github/scripts/kagenti-operator/`)

| Script | Purpose |
|--------|---------|
| `30-run-installer.sh [--env <dev\|ocp>]` | Run Ansible installer (default: dev) |
| `41-wait-crds.sh` | Wait for Kagenti CRDs |
| `42-apply-pipeline-template.sh` | Apply Tekton pipeline template |
| `43-wait-toolhive-crds.sh` | Wait for Toolhive CRDs |
| `71-build-weather-tool.sh` | Build weather-tool image via Shipwright |
| `72-deploy-weather-tool.sh` | Deploy weather-tool Component |
| `73-patch-weather-tool.sh` | Patch weather-tool for OpenShift |
| `74-deploy-weather-agent.sh` | Deploy weather-agent Component |
| `90-run-e2e-tests.sh` | Run E2E tests |

### HyperShift Scripts (`.github/scripts/hypershift/`)

| Script | Purpose |
|--------|---------|
| `create-cluster.sh [suffix]` | Create HyperShift cluster (~10-15 min) |
| `destroy-cluster.sh [suffix]` | Destroy HyperShift cluster (~10 min) |
| `setup-hypershift-ci-credentials.sh` | One-time AWS/OCP credential setup |
| `local-setup.sh` | Install hcp CLI and ansible collections |
| `preflight-check.sh` | Verify prerequisites (called by setup script) |
| `debug-aws-hypershift.sh [suffix]` | Find orphaned AWS resources for a cluster (read-only) |
| `check-quotas.sh` | Check AWS service quotas and current usage |
| `setup-autoscaling.sh` | Configure mgmt/nodepool autoscaling |

## Phase Options (kind-full-test.sh & hypershift-full-test.sh)

Both scripts support the same unified phase control interface:

**Phases**: `cluster-create` → `kagenti-install` → `agents` → `test` → `kagenti-uninstall` → `cluster-destroy`

| Option | Runs | Use Case |
|--------|------|----------|
| `--skip-cluster-destroy` | 1-4 | **Main flow**: run tests, keep cluster |
| `--include-cluster-destroy` | 6 | **Cleanup**: destroy cluster when done |
| (no options) | 1-4,6 | Full CI run (create + test + destroy) |
| `--skip-cluster-create --skip-cluster-destroy` | 2-4 | Iterate on existing cluster |
| `--include-<phase>` | selected | Run specific phase(s) only |
| `--include-kagenti-uninstall` | 5 | Uninstall kagenti (opt-in) |
| `--clean-kagenti` | - | Uninstall kagenti before installing |
| `[suffix]` | - | Custom cluster suffix (HyperShift only) |

## Environment Comparison

| Feature | Kind | OpenShift | HyperShift |
|---------|------|-----------|------------|
| Entry Script | `kind-full-test.sh` | `hypershift-full-test.sh --skip-cluster-*` | `hypershift-full-test.sh` |
| SPIRE | Vanilla | ZTWIM Operator | ZTWIM Operator |
| Values File | `dev_values.yaml` | `ocp_values.yaml` | `ocp_values.yaml` |
| Cluster Lifetime | Persistent | Persistent | Ephemeral |
| AWS Required | No | No | Yes |
| Min OCP Version | N/A | 4.19+ | 4.19+ |


