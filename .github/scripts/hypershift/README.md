# HyperShift CI Scripts

Scripts for provisioning ephemeral OpenShift clusters via HyperShift for testing.

## Overview

All operations are **idempotent** - safe to rerun after updates.

## Scripts

| Script | Purpose |
|--------|---------|
| `preflight-check.sh` | Verify prerequisites before setup |
| `setup-hypershift-ci-credentials.sh` | One-time credential setup (AWS IAM + OCP SA) |
| `local-setup.sh` | Install hcp CLI, clone hypershift-automation, install collections |
| `create-cluster.sh [suffix]` | Create HyperShift cluster |
| `destroy-cluster.sh <name>` | Destroy a HyperShift cluster |
| `debug-aws-hypershift.sh` | Debug AWS resources and connectivity |
| `setup-autoscaling.sh` | Configure cluster autoscaling |

## Quick Start

```bash
# 1. Run preflight check
./.github/scripts/hypershift/preflight-check.sh

# 2. One-time setup (creates AWS IAM + OCP service account)
./.github/scripts/hypershift/setup-hypershift-ci-credentials.sh

# 3. Install prerequisites (hcp CLI, ansible collections)
./.github/scripts/hypershift/local-setup.sh

# 4. Create cluster (~10-15 minutes)
./.github/scripts/hypershift/create-cluster.sh
# Creates: kagenti-hypershift-ci-local

# 5. Access cluster
export KUBECONFIG=~/clusters/hcp/kagenti-hypershift-ci-local/auth/kubeconfig
oc get nodes
cat ~/clusters/hcp/kagenti-hypershift-ci-local/cluster-info.txt

# 6. Install Kagenti (uses ZTWIM for SPIRE on OCP 4.19+)
cd ../kagenti
./deployments/ansible/run-install.sh --env ocp

# 7. Run E2E tests
export AGENT_URL="https://$(oc get route -n team1 weather-service -o jsonpath='{.spec.host}')"
export KAGENTI_CONFIG_FILE=deployments/envs/ocp_values.yaml
uv run pytest kagenti/tests/e2e/common kagenti/tests/e2e/kagenti_operator -v

# 8. Destroy cluster when done
./.github/scripts/hypershift/destroy-cluster.sh local
```

## Cluster Naming

Cluster names are auto-prefixed with `MANAGED_BY_TAG` for IAM scoping:

```bash
# Default suffix: "local"
./create-cluster.sh                          # kagenti-hypershift-ci-local

# Custom suffix via argument
./create-cluster.sh pr123                    # kagenti-hypershift-ci-pr123

# Random suffix (for parallel testing)
CLUSTER_SUFFIX="" ./create-cluster.sh        # kagenti-hypershift-ci-abc123

# With custom options
REPLICAS=3 INSTANCE_TYPE=m5.2xlarge OCP_VERSION=4.20.10 ./create-cluster.sh
```

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `CLUSTER_SUFFIX` | `local` | Suffix for cluster name |
| `REPLICAS` | `2` | Number of worker nodes |
| `INSTANCE_TYPE` | `m5.xlarge` | AWS instance type |
| `OCP_VERSION` | `4.20.10` | OpenShift version (4.19+ supports ZTWIM) |
| `MANAGED_BY_TAG` | from .env | Prefix for all resources |

## Important Notes

- **OCP 4.19+ required** for ZTWIM (Zero Trust Workload Identity Manager / SPIRE operator)
- **Credentials** are stored in `.env.hypershift-ci` (git-ignored)
- **IAM scoping** uses HyperShift's built-in `kubernetes.io/cluster/<name>=owned` tag
