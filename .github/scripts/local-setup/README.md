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
# │ STEP 1: Create cluster and deploy platform (~15-20 min)                     │
# │ No external login required - Kind runs locally with Docker                  │
# └─────────────────────────────────────────────────────────────────────────────┘
./.github/scripts/local-setup/cleanup-cluster.sh
./.github/scripts/local-setup/deploy-platform.sh

# ┌─────────────────────────────────────────────────────────────────────────────┐
# │ STEP 2: Deploy agents and run E2E tests                                     │
# └─────────────────────────────────────────────────────────────────────────────┘
./.github/scripts/kagenti-operator/71-build-weather-tool.sh
./.github/scripts/kagenti-operator/72-deploy-weather-tool.sh
./.github/scripts/kagenti-operator/73-patch-weather-tool.sh
./.github/scripts/kagenti-operator/74-deploy-weather-agent.sh
./.github/scripts/kagenti-operator/90-run-e2e-tests.sh

# ┌─────────────────────────────────────────────────────────────────────────────┐
# │ STEP 3: Access UI                                                           │
# └─────────────────────────────────────────────────────────────────────────────┘
./.github/scripts/local-setup/access-ui.sh
kubectl port-forward -n kagenti-system svc/http-istio 8080:80
# Visit: http://kagenti-ui.localtest.me:8080

# ┌─────────────────────────────────────────────────────────────────────────────┐
# │ CLEANUP: Delete cluster when done                                           │
# └─────────────────────────────────────────────────────────────────────────────┘
./.github/scripts/local-setup/cleanup-cluster.sh
```

---

### OpenShift (Standard RHOCP)

**Prerequisites**: oc CLI, OpenShift cluster-admin access

```bash
# ┌─────────────────────────────────────────────────────────────────────────────┐
# │ STEP 1: Login to OpenShift cluster (cluster-admin required)                 │
# └─────────────────────────────────────────────────────────────────────────────┘
oc login https://api.your-cluster.example.com:6443 -u kubeadmin -p <password>
# Or: export KUBECONFIG=/path/to/your/kubeconfig

# ┌─────────────────────────────────────────────────────────────────────────────┐
# │ STEP 2: Install Kagenti platform                                            │
# └─────────────────────────────────────────────────────────────────────────────┘
./.github/scripts/kagenti-operator/30-run-installer.sh --env ocp
./.github/scripts/kagenti-operator/41-wait-crds.sh
./.github/scripts/kagenti-operator/42-apply-pipeline-template.sh
./.github/scripts/kagenti-operator/43-wait-toolhive-crds.sh

# ┌─────────────────────────────────────────────────────────────────────────────┐
# │ STEP 3: Deploy agents and run E2E tests                                     │
# └─────────────────────────────────────────────────────────────────────────────┘
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

#### Quick Run

```bash
# ┌─────────────────────────────────────────────────────────────────────────────┐
# │ ONE-TIME SETUP (requires AWS admin + OCP cluster-admin on mgmt cluster)    │
# └─────────────────────────────────────────────────────────────────────────────┘
MANAGED_BY_TAG="${MANAGED_BY_TAG:-kagenti-hypershift-ci}"   # Controls IAM user/policy naming
CLUSTER_SUFFIX="${CLUSTER_SUFFIX:-local}"                   # Customize per-cluster
# Cluster name = ${MANAGED_BY_TAG}-${CLUSTER_SUFFIX} → e.g., kagenti-hypershift-ci-local

./.github/scripts/hypershift/setup-hypershift-ci-credentials.sh    # Creates IAM + .env.hypershift-ci
./.github/scripts/hypershift/local-setup.sh                        # Installs hcp CLI + ansible

# Optional: Verify mgmt cluster capacity and autoscaling
# ./.github/scripts/hypershift/setup-autoscaling.sh                # Check/configure autoscaling

# ┌─────────────────────────────────────────────────────────────────────────────┐
# │ DEVELOPMENT WORKFLOW (most common - keep cluster, iterate fast)            │
# └─────────────────────────────────────────────────────────────────────────────┘

# First time: Create cluster and run tests, keep cluster for iteration
./.github/scripts/hypershift/run-full-test.sh --skip-destroy       # ~25 min

# Iterate: Clean kagenti, redeploy, test (keeps cluster)
export KUBECONFIG=~/clusters/hcp/kagenti-hypershift-ci-local/auth/kubeconfig
./deployments/ansible/cleanup-install.sh                            # ~2 min
./.github/scripts/hypershift/run-full-test.sh --skip-create --skip-destroy  # ~10 min

# When done developing: Destroy cluster
source .env.hypershift-ci
./.github/scripts/hypershift/destroy-cluster.sh local               # ~10 min

# ┌─────────────────────────────────────────────────────────────────────────────┐
# │ FULL CI TEST (create → deploy → test → destroy)                            │
# └─────────────────────────────────────────────────────────────────────────────┘
source .env.hypershift-ci
./.github/scripts/hypershift/run-full-test.sh                       # ~35 min total

# ┌─────────────────────────────────────────────────────────────────────────────┐
# │ ALL OPTIONS                                                                 │
# └─────────────────────────────────────────────────────────────────────────────┘
./.github/scripts/hypershift/run-full-test.sh                       # Full CI run
./.github/scripts/hypershift/run-full-test.sh pr123                 # Custom cluster suffix
./.github/scripts/hypershift/run-full-test.sh --skip-destroy        # First dev run, keep cluster
./.github/scripts/hypershift/run-full-test.sh --skip-create --skip-destroy  # Iterate on existing cluster
./.github/scripts/hypershift/run-full-test.sh --skip-create --clean-kagenti --skip-destroy  # Fresh kagenti on existing cluster
./.github/scripts/hypershift/run-full-test.sh --skip-create         # Final run, destroy cluster
```

#### Detailed Instructions

<details>
<summary>Click to expand step-by-step instructions</summary>

```bash
# ┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
# ┃ PHASE 1: ONE-TIME SETUP (run once per environment)                          ┃
# ┃ Requires: AWS IAM admin + OCP cluster-admin on management cluster           ┃
# ┃ Creates:  Scoped CI user (AWS) + service account (OCP) with minimal privs   ┃
# ┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛
# AWS login (if using SSO)
# aws sso login --profile your-profile
# export AWS_PROFILE=your-profile

aws sts get-caller-identity                                        # Verify AWS admin

# Option A: Login interactively
# oc login https://api.mgmt-cluster.example.com:6443 -u kubeadmin    # Login to mgmt cluster

# Option B: Use existing kubeconfig
# export KUBECONFIG=~/.kube/my-mgmt-cluster.kubeconfig

oc whoami && oc status                                             # Verify cluster access

MANAGED_BY_TAG="${MANAGED_BY_TAG:-kagenti-hypershift-ci}"          # Controls IAM user/policy naming
CLUSTER_SUFFIX="${CLUSTER_SUFFIX:-local}"                          # Customize per-cluster
# Cluster name = ${MANAGED_BY_TAG}-${CLUSTER_SUFFIX} → e.g., kagenti-hypershift-ci-local

./.github/scripts/hypershift/setup-hypershift-ci-credentials.sh    # Creates IAM + .env.hypershift-ci
./.github/scripts/hypershift/local-setup.sh                        # Installs hcp CLI + ansible

# Optional: Debug orphaned AWS resources or configure autoscaling
# ./.github/scripts/hypershift/debug-aws-hypershift.sh             # Find orphaned AWS resources (read-only)
# ./.github/scripts/hypershift/setup-autoscaling.sh                # Configure mgmt/nodepool autoscaling

# ┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
# ┃ PHASE 2: CREATE CLUSTER (uses scoped CI credentials from .env.hypershift-ci)┃
# ┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛
source .env.hypershift-ci                                          # Load scoped CI creds
./.github/scripts/hypershift/create-cluster.sh                     # Creates kagenti-hypershift-ci-local

# ┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
# ┃ PHASE 3: DEPLOY KAGENTI + E2E (uses hosted cluster kubeconfig)              ┃
# ┃ Credentials: KUBECONFIG from created cluster (cluster-admin on hosted)      ┃
# ┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛
# Kubeconfig path: ~/clusters/hcp/<cluster-name>/auth/kubeconfig
export KUBECONFIG=~/clusters/hcp/kagenti-hypershift-ci-local/auth/kubeconfig
oc get nodes

./.github/scripts/kagenti-operator/30-run-installer.sh --env ocp
./.github/scripts/kagenti-operator/41-wait-crds.sh
./.github/scripts/kagenti-operator/42-apply-pipeline-template.sh
./.github/scripts/kagenti-operator/43-wait-toolhive-crds.sh

./.github/scripts/kagenti-operator/71-build-weather-tool.sh
./.github/scripts/kagenti-operator/72-deploy-weather-tool.sh
./.github/scripts/kagenti-operator/73-patch-weather-tool.sh
./.github/scripts/kagenti-operator/74-deploy-weather-agent.sh

export AGENT_URL="https://$(oc get route -n team1 weather-service -o jsonpath='{.spec.host}')"
export KAGENTI_CONFIG_FILE=deployments/envs/ocp_values.yaml
./.github/scripts/kagenti-operator/90-run-e2e-tests.sh

# ┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
# ┃ ITERATE: Clean kagenti and re-run Phase 3 (keeps cluster, fast iteration)  ┃
# ┃ Use this to iterate on kagenti/agents without destroying the cluster       ┃
# ┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛
export KUBECONFIG=~/clusters/hcp/kagenti-hypershift-ci-local/auth/kubeconfig
./deployments/ansible/cleanup-install.sh                           # ~2 min: clean kagenti only
# Then re-run Phase 3 steps above (30-run-installer.sh through 90-run-e2e-tests.sh)
# Or use the automated script:
./.github/scripts/hypershift/run-full-test.sh --skip-create --skip-destroy

# ┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
# ┃ CLEANUP: Destroy cluster (uses scoped CI credentials)                       ┃
# ┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛
source .env.hypershift-ci                                          # Reload CI creds
./.github/scripts/hypershift/destroy-cluster.sh local              # Destroys kagenti-hypershift-ci-local
```

</details>

---

## Script Reference

### Local Setup Scripts (this directory)

| Script | Purpose |
|--------|---------|
| `cleanup-cluster.sh` | Delete Kind cluster |
| `deploy-platform.sh` | Full Kagenti deployment on Kind |
| `run-e2e-tests.sh` | Run E2E test suite |
| `access-ui.sh` | Show service URLs and port-forward commands |
| `chat-with-agent.sh` | Interactive agent chat CLI |
| `show-services.sh` | Display all deployed services |

### Kagenti Operator Scripts (`.github/scripts/kagenti-operator/`)

| Script | Purpose |
|--------|---------|
| `30-run-installer.sh [--env <dev\|ocp>]` | Run Ansible installer (default: dev) |
| `41-wait-crds.sh` | Wait for Kagenti CRDs |
| `42-apply-pipeline-template.sh` | Apply Tekton pipeline template |
| `43-wait-toolhive-crds.sh` | Wait for Toolhive CRDs |
| `71-build-weather-tool.sh` | Build weather-tool image via AgentBuild |
| `72-deploy-weather-tool.sh` | Deploy weather-tool Component |
| `73-patch-weather-tool.sh` | Patch weather-tool for OpenShift |
| `74-deploy-weather-agent.sh` | Deploy weather-agent Component |
| `90-run-e2e-tests.sh` | Run E2E tests |

### HyperShift Scripts (`.github/scripts/hypershift/`)

| Script | Purpose |
|--------|---------|
| `run-full-test.sh [suffix] [options]` | Automated test runner (see options below) |
| `create-cluster.sh [suffix]` | Create HyperShift cluster (~10-15 min) |
| `destroy-cluster.sh [suffix]` | Destroy HyperShift cluster (~10 min) |
| `setup-hypershift-ci-credentials.sh` | One-time AWS/OCP credential setup |
| `local-setup.sh` | Install hcp CLI and ansible collections |
| `preflight-check.sh` | Verify prerequisites (called by setup script) |
| `debug-aws-hypershift.sh` | Find orphaned AWS resources (read-only) |
| `setup-autoscaling.sh` | Configure mgmt/nodepool autoscaling |

**run-full-test.sh Options:**

| Option | Description | Use Case |
|--------|-------------|----------|
| (no options) | Full test: create → deploy → E2E → destroy | CI, one-off testing |
| `--skip-destroy` | Keep cluster after tests | First dev run |
| `--skip-create` | Reuse existing cluster | Final run (destroys cluster) |
| `--skip-create --skip-destroy` | Iterate on existing cluster | Fast iteration |
| `--clean-kagenti` | Uninstall kagenti before installing | Fresh kagenti install |
| `[suffix]` | Custom cluster suffix (e.g., `pr123`) | Multiple clusters |

## Environment Comparison

| Feature | Kind | OpenShift | HyperShift |
|---------|------|-----------|------------|
| SPIRE | Vanilla | ZTWIM Operator | ZTWIM Operator |
| Values File | `dev_values.yaml` | `ocp_values.yaml` | `ocp_values.yaml` |
| Cluster Lifetime | Persistent | Persistent | Ephemeral |
| AWS Required | No | No | Yes |
| Min OCP Version | N/A | 4.19+ | 4.19+ |

## Debugging

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
