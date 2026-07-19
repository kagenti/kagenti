# Local Testing & Deployment Scripts

Scripts for deploying and testing the Rossoctl platform on Kind, OpenShift, or HyperShift.

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

# Full run: create cluster → deploy rossoctl → test → destroy
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
kubectl port-forward -n rossoctl-system svc/http-istio 8080:80
# Visit: http://rossoctl-ui.localtest.me:8080

# Cleanup
./.github/scripts/kind/destroy-cluster.sh
```

---

### OpenShift (Standard RHOCP)

**Prerequisites**: oc CLI, OpenShift cluster-admin access

No AWS credentials or `.env` file needed - just `oc login` and run.

```bash
# ┌─────────────────────────────────────────────────────────────────────────────┐
# │ OPTION A: Unified test runner (recommended)                                 │
# └─────────────────────────────────────────────────────────────────────────────┘
oc login https://api.your-cluster.example.com:6443 -u kubeadmin -p <password>

# Full rossoctl test cycle on any OpenShift cluster
./.github/scripts/local-setup/openshift-full-test.sh

# Iterate on existing deployment (skip reinstall)
./.github/scripts/local-setup/openshift-full-test.sh --skip-rossoctl-install

# Run only tests
./.github/scripts/local-setup/openshift-full-test.sh --include-test

# Show help
./.github/scripts/local-setup/openshift-full-test.sh --help

# ┌─────────────────────────────────────────────────────────────────────────────┐
# │ OPTION B: Step-by-step (manual control)                                     │
# └─────────────────────────────────────────────────────────────────────────────┘
oc login https://api.your-cluster.example.com:6443 -u kubeadmin -p <password>

# Install Rossoctl platform
./scripts/ocp/setup-rossoctl.sh --rossoctl-repo .

# Deploy agents and tools, run E2E tests
./.github/scripts/operator/71-build-weather-tool.sh
./.github/scripts/operator/72-deploy-weather-tool.sh
./.github/scripts/operator/74-deploy-weather-agent.sh

export AGENT_URL="https://$(oc get route -n team1 weather-service -o jsonpath='{.spec.host}')"
export ROSSOCTL_CONFIG_FILE=deployments/envs/ocp_values.yaml
./.github/scripts/operator/90-run-e2e-tests.sh
```

> **Note**: `openshift-full-test.sh` is a thin wrapper around `hypershift-full-test.sh`
> with `--skip-cluster-create --skip-cluster-destroy` enabled by default.

---

### HyperShift (Ephemeral OpenShift)

**Prerequisites**: AWS CLI, oc CLI, bash 3.2+, jq

#### One-Time Setup

```bash
# Requires: AWS admin + OCP cluster-admin on management cluster
./.github/scripts/hypershift/setup-hypershift-ci-credentials.sh    # Creates IAM + .env.rossoctl-hypershift-custom
./.github/scripts/hypershift/local-setup.sh                        # Installs hcp CLI
```

#### Naming & Credential Scoping

HyperShift uses a two-level naming system controlled by environment variables:

**1. `MANAGED_BY_TAG`** - Controls credential scoping and cluster prefix
   - Default: `rossoctl-hypershift-custom` (for local development)
   - CI uses: `rossoctl-hypershift-ci` (from GitHub secrets)
   - Drives the `.env` filename and AWS IAM resource naming
   - Typically set once per project/team, not per cluster

**2. `CLUSTER_SUFFIX`** - Controls the specific cluster instance
   - Default: first 5 characters of `$USER` (e.g., `ladas`)
   - Pass as first argument to the script to override
   - Full cluster name = `${MANAGED_BY_TAG}-${CLUSTER_SUFFIX}`

**How they work together:**

```
MANAGED_BY_TAG=rossoctl-hypershift-custom   # Set by setup or environment
CLUSTER_SUFFIX=mlflow                       # Passed as argument

→ Cluster name:  rossoctl-hypershift-custom-mlflow
→ Credentials:   .env.rossoctl-hypershift-custom (scoped IAM + kubeconfig)
→ Kubeconfig:    ~/clusters/hcp/rossoctl-hypershift-custom-mlflow/auth/kubeconfig
```

| Component | Local Default | CI Default |
|-----------|--------------|------------|
| `MANAGED_BY_TAG` | `rossoctl-hypershift-custom` | `rossoctl-hypershift-ci` |
| `.env` file | `.env.rossoctl-hypershift-custom` | (from GitHub secrets) |
| `CLUSTER_SUFFIX` | First 5 chars of `$USER` | PR number or workflow ID |
| Full cluster name | `rossoctl-hypershift-custom-$USER` | `rossoctl-hypershift-ci-<suffix>` |

**Setting a custom suffix:**

```bash
# Default (uses your username truncated to 5 chars)
./.github/scripts/local-setup/hypershift-full-test.sh --skip-cluster-destroy
# Creates: rossoctl-hypershift-custom-ladas

# Custom suffix (pass as first positional argument)
./.github/scripts/local-setup/hypershift-full-test.sh mlflow --skip-cluster-destroy
# Creates: rossoctl-hypershift-custom-mlflow

./.github/scripts/local-setup/hypershift-full-test.sh pr529 --skip-cluster-destroy
# Creates: rossoctl-hypershift-custom-pr529
```

**Multiple clusters:** You can run multiple clusters simultaneously by using different suffixes.
Each cluster has its own kubeconfig at `~/clusters/hcp/${MANAGED_BY_TAG}-${suffix}/auth/kubeconfig`.

**AWS IAM limits:** Cluster names must be ≤32 characters (AWS IAM role name limit).
With the default `MANAGED_BY_TAG` (26 chars), suffixes can be up to 5 characters.

#### Main Testing Flow (Worktree Recommended)

The recommended workflow uses git worktrees to test feature branches on HyperShift
without switching your main working directory. This allows you to:

- Keep your main branch clean for other work
- Test multiple features in parallel on separate clusters
- Run tests against feature branch code while credentials stay in repo root

```bash
# ┌─────────────────────────────────────────────────────────────────────────────┐
# │ WORKTREE WORKFLOW (RECOMMENDED)                                             │
# │ Test feature branches without switching directories                         │
# └─────────────────────────────────────────────────────────────────────────────┘

# 1. Create a worktree for your feature branch (from repo root)
git worktree add .worktrees/my-feature origin/my-feature-branch

# 2. Source credentials, then run tests from the worktree
#    Scripts auto-detect pre-sourced env vars and worktree paths
source .env.rossoctl-hypershift-custom && \
  .worktrees/my-feature/.github/scripts/local-setup/hypershift-full-test.sh \
  --skip-cluster-destroy

# 3. Show services (credentials still active from step 2)
.worktrees/my-feature/.github/scripts/local-setup/show-services.sh

# 4. When done - destroy cluster
source .env.rossoctl-hypershift-custom && \
  .worktrees/my-feature/.github/scripts/local-setup/hypershift-full-test.sh \
  --include-cluster-destroy

# 5. Optional: clean up worktree
git worktree remove .worktrees/my-feature
```

#### Main Testing Flow (Direct)

If testing from the main branch or same directory as your .env file:

```bash
# ┌─────────────────────────────────────────────────────────────────────────────┐
# │ STEP 1: Run tests, keep cluster for debugging                               │
# │         Default cluster: rossoctl-hypershift-custom-$USER                     │
# └─────────────────────────────────────────────────────────────────────────────┘

# source the env created by setup-hypershift-ci-credentials.sh
source .env.rossoctl-hypershift-custom

# Deploy the cluster with rossoctl example stack
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
# Creates: rossoctl-hypershift-custom-ladas

# ┌─────────────────────────────────────────────────────────────────────────────┐
# │ Custom cluster suffix - useful for testing specific PRs or features         │
# └─────────────────────────────────────────────────────────────────────────────┘
./.github/scripts/local-setup/hypershift-full-test.sh pr529 --skip-cluster-destroy
# Creates: rossoctl-hypershift-custom-pr529 cluster

# Show services urls and credentials of the custom rossoctl-hypershift-custom-pr529 cluster
./.github/scripts/local-setup/show-services.sh pr529

./.github/scripts/local-setup/hypershift-full-test.sh feature1 --skip-cluster-destroy
# Creates: rossoctl-hypershift-custom-feature1

# Destroy specific cluster
./.github/scripts/local-setup/hypershift-full-test.sh pr529 --include-cluster-destroy

# ┌─────────────────────────────────────────────────────────────────────────────┐
# │ More examples                                        │
# └─────────────────────────────────────────────────────────────────────────────┘

# Full CI run: create → deploy → test → destroy (~50 min)
./.github/scripts/local-setup/hypershift-full-test.sh

# Iterate on existing cluster (skip create, keep cluster)
./.github/scripts/local-setup/hypershift-full-test.sh --skip-cluster-create --skip-cluster-destroy

# Fresh rossoctl install on existing cluster
./.github/scripts/local-setup/hypershift-full-test.sh --skip-cluster-create --clean-rossoctl --skip-cluster-destroy
```

#### Running Individual Phases

Use `--include-<phase>` to run only specific phases:

```bash
# Create cluster only
./.github/scripts/local-setup/hypershift-full-test.sh --include-cluster-create

# Install rossoctl only (on existing cluster)
./.github/scripts/local-setup/hypershift-full-test.sh --include-rossoctl-install

# Deploy agents only
./.github/scripts/local-setup/hypershift-full-test.sh --include-agents

# Run tests only
./.github/scripts/local-setup/hypershift-full-test.sh --include-test

# Uninstall rossoctl only
./.github/scripts/local-setup/hypershift-full-test.sh --include-rossoctl-uninstall

# Destroy cluster only
./.github/scripts/local-setup/hypershift-full-test.sh --include-cluster-destroy

# Combine phases: create + install only
./.github/scripts/local-setup/hypershift-full-test.sh --include-cluster-create --include-rossoctl-install
```

---

## Debugging

Commands for debugging the deployed cluster. First, set the KUBECONFIG for your target cluster:

```bash
# For HyperShift - use the hosted cluster kubeconfig
export KUBECONFIG=~/clusters/hcp/rossoctl-hypershift-custom-$USER/auth/kubeconfig

# For Kind
export KUBECONFIG=~/.kube/config

# For OpenShift - use oc login instead
oc login https://api.your-cluster.example.com:6443 -u kubeadmin -p <password>
```

### HyperShift: Two Kubeconfigs

HyperShift workflows use **two separate kubeconfigs** - don't mix them up:

| Kubeconfig | Purpose | Location |
|------------|---------|----------|
| **Management cluster** | Create/destroy hosted clusters | Set via `KUBECONFIG` in `.env.rossoctl-hypershift-custom` |
| **Hosted cluster** | Deploy Rossoctl, run tests | `~/clusters/hcp/<cluster-name>/auth/kubeconfig` |

The full test script handles this automatically:
- **Phases 1 & 6** (create/destroy): Uses management cluster kubeconfig
- **Phases 2-5** (install/agents/test): Uses hosted cluster kubeconfig

#### Simplified Usage: Middle Phases Only

When only running middle phases (install/agents/test), you don't need to source the full `.env` file.
Just set `KUBECONFIG` to point to the hosted cluster and skip create/destroy:

```bash
# Run only middle phases on an existing cluster
export KUBECONFIG=~/clusters/hcp/rossoctl-hypershift-custom-ladas/auth/kubeconfig
./.github/scripts/local-setup/hypershift-full-test.sh --skip-cluster-create --skip-cluster-destroy

# Or using whitelist mode (only specified phases run)
export KUBECONFIG=~/clusters/hcp/rossoctl-hypershift-custom-ladas/auth/kubeconfig
./.github/scripts/local-setup/hypershift-full-test.sh --include-rossoctl-install --include-agents --include-test
```

#### Full Usage: With Cluster Create/Destroy

When creating or destroying clusters, you need the full credentials:

```bash
# Full workflow with cluster operations
source .env.rossoctl-hypershift-custom
./.github/scripts/local-setup/hypershift-full-test.sh --skip-cluster-destroy

# Later, destroy the cluster
source .env.rossoctl-hypershift-custom
./.github/scripts/local-setup/hypershift-full-test.sh --include-cluster-destroy
```

#### Manual Script Usage

When running individual scripts manually, ensure you're using the correct kubeconfig:

```bash
# For cluster operations (create/destroy)
source .env.rossoctl-hypershift-custom
# KUBECONFIG now points to management cluster

# For Rossoctl operations (install/test)
export KUBECONFIG=~/clusters/hcp/rossoctl-hypershift-custom-ladas/auth/kubeconfig
kubectl get pods -n rossoctl-system
```

Then run debugging commands:

```bash
# View pod status
kubectl get pods -A

# Check agent logs
kubectl logs -n team1 deployment/weather-service -f

# Check operator logs
kubectl logs -n rossoctl-system deployment/operator -f

# Recent events
kubectl get events -A --sort-by='.lastTimestamp' | tail -30
```

### HyperShift Setup & Debugging & Monitoring

#### Admin Operations (one-time setup)

Requires AWS admin credentials + management cluster admin access:

```bash
# Set up AWS admin credentials (admin, used only for setup)
export AWS_ACCESS_KEY_ID="<your-admin-access-key>"
export AWS_SECRET_ACCESS_KEY="<your-admin-secret-key>"
export AWS_REGION="us-east-1"  # optional, defaults to us-east-1

# Login to management cluster
export KUBECONFIG=~/.kube/hypershift_rossoctl_ci
oc login ...

# Optional: customize the managed-by tag (drives naming of users, clusters, resources)
# This determines what .env file is created and the cluster name prefix
export MANAGED_BY_TAG="rossoctl-hypershift-custom"  # default for local dev

# Create scoped AWS IAM user + OCP service account for cluster management
./.github/scripts/hypershift/setup-hypershift-ci-credentials.sh
#
# This script creates:
#   - AWS IAM user with scoped permissions for cluster create/destroy
#   - OCP ServiceAccount with cluster-admin for HyperShift operations
#   - Output: .env.${MANAGED_BY_TAG} (e.g., .env.rossoctl-hypershift-custom)
#
# The .env file contains:
#   - AWS_ACCESS_KEY_ID/SECRET for the scoped IAM user
#   - KUBECONFIG path for the management cluster
#   - MANAGED_BY_TAG value for consistent naming

# Optional: check AWS quotas before creating clusters (needs AWS creds only)
source .env.rossoctl-hypershift-custom  # For AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY
./.github/scripts/hypershift/check-quotas.sh
```

#### Optional: Configure Autoscaling

The management cluster and hosted clusters can autoscale based on demand.
**Requires**: Both AWS credentials and management cluster kubeconfig.

```bash
# Source credentials (provides AWS creds + KUBECONFIG for management cluster)
source .env.rossoctl-hypershift-custom

# Show current utilization and scaling options
./.github/scripts/hypershift/setup-autoscaling.sh

# Configure management cluster autoscaling (max 3 workers per zone)
./.github/scripts/hypershift/setup-autoscaling.sh --mgmt-max 3

# Configure hosted cluster NodePool autoscaling
./.github/scripts/hypershift/setup-autoscaling.sh --nodepool-min 2 --nodepool-max 6

# Apply the generated commands (default is dry-run, shows commands)
./.github/scripts/hypershift/setup-autoscaling.sh --mgmt-max 3 --apply
```

**Different teams/projects:** Use different `MANAGED_BY_TAG` values to create isolated credential sets:

```bash
# Team A setup
export MANAGED_BY_TAG="rossoctl-hypershift-team-a"
./.github/scripts/hypershift/setup-hypershift-ci-credentials.sh
# Output: .env.rossoctl-hypershift-team-a

# Team B setup
export MANAGED_BY_TAG="rossoctl-hypershift-team-b"
./.github/scripts/hypershift/setup-hypershift-ci-credentials.sh
# Output: .env.rossoctl-hypershift-team-b
```

#### Debug Commands (with scoped credentials)

```bash
# Debug a specific cluster (e.g., pr529)
source .env.rossoctl-hypershift-ci && ./.github/scripts/hypershift/debug-aws-hypershift.sh pr529
source .env.rossoctl-hypershift-ci && ./.github/scripts/local-setup/show-services.sh pr529

# Debug default user cluster
source .env.rossoctl-hypershift-custom && ./.github/scripts/hypershift/debug-aws-hypershift.sh
source .env.rossoctl-hypershift-custom && ./.github/scripts/local-setup/show-services.sh
```

---

## Script Reference

### Entry Point Scripts (this directory)

| Script | Purpose |
|--------|---------|
| `kind-full-test.sh` | Unified Kind test runner (same interface as HyperShift) |
| `openshift-full-test.sh` | OpenShift test runner (no cluster create/destroy) |
| `hypershift-full-test.sh` | HyperShift test runner with full phase control |
| `show-services.sh` | Display all services, URLs, and credentials (auto-detects Kind/OpenShift/HyperShift) |

### Kind Scripts (`.github/scripts/kind/`)

| Script | Purpose |
|--------|---------|
| `create-cluster.sh` | Create Kind cluster |
| `destroy-cluster.sh` | Delete Kind cluster |
| `deploy-platform.sh` | Full Rossoctl deployment on Kind |
| `run-e2e-tests.sh` | Run E2E test suite |
| `access-ui.sh` | Show service URLs and port-forward commands |

### Rossoctl Operator Scripts (`.github/scripts/operator/`)

| Script | Purpose |
|--------|---------|
| `30-run-installer.sh [--env <dev\|ocp>]` | Run platform installer (default: dev) |
| `41-wait-crds.sh` | Wait for Rossoctl CRDs |
| `71-build-weather-tool.sh` | Build weather-tool image via Shipwright |
| `72-deploy-weather-tool.sh` | Deploy weather-tool Deployment + Service |
| `74-deploy-weather-agent.sh` | Deploy weather-agent Component |
| `90-run-e2e-tests.sh` | Run E2E tests |

### HyperShift Scripts (`.github/scripts/hypershift/`)

| Script | Purpose |
|--------|---------|
| `create-cluster.sh [suffix]` | Create HyperShift cluster (~10-15 min) |
| `destroy-cluster.sh [suffix]` | Destroy HyperShift cluster (~10 min) |
| `setup-hypershift-ci-credentials.sh` | One-time AWS/OCP credential setup |
| `local-setup.sh` | Install hcp CLI |
| `preflight-check.sh` | Verify prerequisites (called by setup script) |
| `debug-aws-hypershift.sh [suffix]` | Find orphaned AWS resources for a cluster (read-only) |
| `check-quotas.sh` | Check AWS service quotas and current usage |
| `setup-autoscaling.sh` | Configure mgmt/nodepool autoscaling |

## Phase Options (kind-full-test.sh & hypershift-full-test.sh)

Both scripts support the same unified phase control interface:

**Phases**: `cluster-create` → `rossoctl-install` → `agents` → `test` → `rossoctl-uninstall` → `cluster-destroy`

| Option | Runs | Use Case |
|--------|------|----------|
| `--skip-cluster-destroy` | 1-4 | **Main flow**: run tests, keep cluster |
| `--include-cluster-destroy` | 6 | **Cleanup**: destroy cluster when done |
| (no options) | 1-4,6 | Full CI run (create + test + destroy) |
| `--skip-cluster-create --skip-cluster-destroy` | 2-4 | Iterate on existing cluster |
| `--include-<phase>` | selected | Run specific phase(s) only |
| `--include-rossoctl-uninstall` | 5 | Uninstall rossoctl (opt-in) |
| `--clean-rossoctl` | - | Uninstall rossoctl before installing |
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


