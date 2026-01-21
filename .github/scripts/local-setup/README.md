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

#### One-Time Setup

```bash
# Requires: AWS admin + OCP cluster-admin on management cluster
./.github/scripts/hypershift/setup-hypershift-ci-credentials.sh    # Creates IAM + .env.hypershift-ci
./.github/scripts/hypershift/local-setup.sh                        # Installs hcp CLI + ansible
```

#### Main Testing Flow

```bash
# ┌─────────────────────────────────────────────────────────────────────────────┐
# │ STEP 1: Run tests, keep cluster for debugging (~25 min)                     │
# └─────────────────────────────────────────────────────────────────────────────┘
./.github/scripts/hypershift/run-full-test.sh --skip-destroy

# ┌─────────────────────────────────────────────────────────────────────────────┐
# │ STEP 2: When done - destroy cluster                                         │
# └─────────────────────────────────────────────────────────────────────────────┘
./.github/scripts/hypershift/run-full-test.sh --include-destroy
```

#### Common Examples

```bash
# Default cluster (kagenti-hypershift-ci-local)
./.github/scripts/hypershift/run-full-test.sh --skip-destroy

# Custom cluster suffix (kagenti-hypershift-ci-pr123)
./.github/scripts/hypershift/run-full-test.sh pr123 --skip-destroy
./.github/scripts/hypershift/run-full-test.sh pr123 --include-destroy

# Full CI run: create → deploy → test → destroy (~35 min)
./.github/scripts/hypershift/run-full-test.sh

# Iterate on existing cluster (skip create, keep cluster)
./.github/scripts/hypershift/run-full-test.sh --skip-create --skip-destroy

# Fresh kagenti install on existing cluster
./.github/scripts/hypershift/run-full-test.sh --skip-create --clean-kagenti --skip-destroy
```

#### Running Individual Phases

Use `--include-<phase>` to run only specific phases:

```bash
# Create cluster only
./.github/scripts/hypershift/run-full-test.sh --include-create

# Install kagenti only (on existing cluster)
./.github/scripts/hypershift/run-full-test.sh --include-install

# Deploy agents only
./.github/scripts/hypershift/run-full-test.sh --include-agents

# Run tests only
./.github/scripts/hypershift/run-full-test.sh --include-test

# Destroy cluster only
./.github/scripts/hypershift/run-full-test.sh --include-destroy

# Combine phases: create + install only
./.github/scripts/hypershift/run-full-test.sh --include-create --include-install
```

<details>
<summary>Click to expand step-by-step manual instructions</summary>

```bash
# ┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
# ┃ PHASE 1: CREATE CLUSTER                                                     ┃
# ┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛
source .env.hypershift-ci
./.github/scripts/hypershift/create-cluster.sh                     # or: create-cluster.sh pr123

# ┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
# ┃ PHASE 2-4: DEPLOY KAGENTI + AGENTS + TEST                                   ┃
# ┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛
export KUBECONFIG=~/clusters/hcp/kagenti-hypershift-ci-local/auth/kubeconfig

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
# ┃ ITERATE: Clean and redeploy (keeps cluster)                                 ┃
# ┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛
./deployments/ansible/cleanup-install.sh
# Re-run Phase 2-4 steps above

# ┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
# ┃ PHASE 5: DESTROY CLUSTER                                                    ┃
# ┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛
source .env.hypershift-ci
./.github/scripts/hypershift/destroy-cluster.sh local              # or: destroy-cluster.sh pr123
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

Phases: `create` → `install` → `agents` → `test` → `destroy`

| Option | Runs | Use Case |
|--------|------|----------|
| `--skip-destroy` | 1-4 | **Main flow**: run tests, keep cluster |
| `--include-destroy` | 5 | **Cleanup**: destroy cluster when done |
| (no options) | 1-5 | Full CI run (create + test + destroy) |
| `--skip-create --skip-destroy` | 2-4 | Iterate on existing cluster |
| `--include-<phase>` | selected | Run specific phase(s) only |
| `--clean-kagenti` | - | Uninstall kagenti before installing |
| `[suffix]` | - | Custom cluster suffix (e.g., `pr123`) |

**Modes**: `--skip-X` excludes phases, `--include-X` runs only specified phases.

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
