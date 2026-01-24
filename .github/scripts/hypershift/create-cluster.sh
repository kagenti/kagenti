#!/usr/bin/env bash
#
# Create HyperShift Cluster
#
# Creates an ephemeral OpenShift cluster via HyperShift for testing.
# Cluster names are AUTOMATICALLY prefixed with MANAGED_BY_TAG to ensure
# IAM scoping works correctly.
#
# USAGE:
#   ./.github/scripts/hypershift/create-cluster.sh [cluster-suffix]
#
# CLUSTER NAMING:
#   - Full name: ${MANAGED_BY_TAG}-${CLUSTER_SUFFIX}
#   - MANAGED_BY_TAG comes from .env.hypershift-ci (default: kagenti-hypershift-ci)
#   - Default suffix: "local"
#   - Custom suffix: passed as argument
#   - Random suffix: CLUSTER_SUFFIX="" generates random 6-char suffix
#
# EXAMPLES:
#   ./.github/scripts/hypershift/create-cluster.sh              # ${MANAGED_BY_TAG}-local
#   ./.github/scripts/hypershift/create-cluster.sh pr123        # ${MANAGED_BY_TAG}-pr123
#   CLUSTER_SUFFIX=test ./.github/scripts/hypershift/create-cluster.sh  # ${MANAGED_BY_TAG}-test
#   CLUSTER_SUFFIX="" ./.github/scripts/hypershift/create-cluster.sh    # ${MANAGED_BY_TAG}-<random>
#   REPLICAS=3 INSTANCE_TYPE=m5.2xlarge ./.github/scripts/hypershift/create-cluster.sh
#

set -euo pipefail

# Handle Ctrl+C properly - kill all child processes (especially ansible)
cleanup() {
    echo ""
    echo -e "\033[0;31m✗ Interrupted! Killing child processes...\033[0m"
    # Kill entire process group
    kill -TERM -$$ 2>/dev/null || true
    sleep 1
    kill -9 -$$ 2>/dev/null || true
    exit 130
}
trap cleanup SIGINT SIGTERM

# Detect CI mode
CI_MODE="${GITHUB_ACTIONS:-false}"

# Ensure ~/.local/bin is in PATH (where local-setup.sh installs hcp)
export PATH="$HOME/.local/bin:$PATH"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
PARENT_DIR="$(cd "$REPO_ROOT/.." && pwd)"

# In CI, hypershift-automation is cloned to /tmp; locally it's a sibling directory
if [ "$CI_MODE" = "true" ]; then
    HYPERSHIFT_AUTOMATION_DIR="/tmp/hypershift-automation"
else
    HYPERSHIFT_AUTOMATION_DIR="$PARENT_DIR/hypershift-automation"
fi

# Configuration with defaults
REPLICAS="${REPLICAS:-2}"
INSTANCE_TYPE="${INSTANCE_TYPE:-m5.xlarge}"
OCP_VERSION="${OCP_VERSION:-4.20.10}"

# Cluster suffix - if not set, use positional arg, then default to "local"
# Set CLUSTER_SUFFIX="" to generate a random suffix
if [ -n "${CLUSTER_SUFFIX+x}" ]; then
    # CLUSTER_SUFFIX is explicitly set (even if empty)
    :
elif [ $# -ge 1 ]; then
    CLUSTER_SUFFIX="$1"
else
    CLUSTER_SUFFIX="local"
fi

# Generate random suffix if empty
if [ -z "$CLUSTER_SUFFIX" ]; then
    CLUSTER_SUFFIX=$(LC_ALL=C tr -dc 'a-z0-9' < /dev/urandom | head -c 6)
fi

# Colors
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m'

log_info() { echo -e "${BLUE}→${NC} $1"; }
log_success() { echo -e "${GREEN}✓${NC} $1"; }
log_warn() { echo -e "${YELLOW}⚠${NC} $1"; }

echo ""
echo "╔════════════════════════════════════════════════════════════════╗"
echo "║           Create HyperShift Cluster                            ║"
echo "╚════════════════════════════════════════════════════════════════╝"
echo ""

# ============================================================================
# 1. Load credentials
# ============================================================================

if [ "$CI_MODE" = "true" ]; then
    # CI mode: credentials are passed via environment variables from GitHub secrets
    # Required: MANAGED_BY_TAG, AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_REGION,
    #           BASE_DOMAIN, HCP_ROLE_NAME, KUBECONFIG (already set in GITHUB_ENV)
    log_success "Using CI credentials from environment"
else
    # Local mode: load from .env file
    if [ ! -f "$REPO_ROOT/.env.hypershift-ci" ]; then
        echo "Error: .env.hypershift-ci not found. Run setup-hypershift-ci-credentials.sh first." >&2
        exit 1
    fi
    # shellcheck source=/dev/null
    source "$REPO_ROOT/.env.hypershift-ci"
    log_success "Loaded credentials from .env.hypershift-ci"
fi

# Construct cluster name: ${MANAGED_BY_TAG}-${CLUSTER_SUFFIX}
# This ensures all clusters are prefixed correctly for IAM scoping
CLUSTER_NAME="${MANAGED_BY_TAG}-${CLUSTER_SUFFIX}"
log_success "Cluster name: $CLUSTER_NAME"

# ============================================================================
# 2. Verify prerequisites
# ============================================================================

if [ ! -d "$HYPERSHIFT_AUTOMATION_DIR" ]; then
    if [ "$CI_MODE" = "true" ]; then
        echo "Error: hypershift-automation not found at $HYPERSHIFT_AUTOMATION_DIR" >&2
        echo "Ensure the clone step ran before this script." >&2
    else
        echo "Error: hypershift-automation not found. Run local-setup.sh first." >&2
    fi
    exit 1
fi

if [ ! -f "$HOME/.pullsecret.json" ]; then
    if [ "$CI_MODE" = "true" ]; then
        echo "Error: Pull secret not found at ~/.pullsecret.json" >&2
        echo "Ensure the setup-credentials step ran before this script." >&2
    else
        echo "Error: Pull secret not found. Run local-setup.sh first." >&2
    fi
    exit 1
fi

# Verify KUBECONFIG is set
if [ -z "${KUBECONFIG:-}" ]; then
    if [ "$CI_MODE" = "true" ]; then
        echo "Error: KUBECONFIG not set. Check the setup-credentials step." >&2
    else
        echo "Error: KUBECONFIG not set. Is .env.hypershift-ci properly configured?" >&2
    fi
    exit 1
fi

if [ ! -f "$KUBECONFIG" ]; then
    echo "Error: KUBECONFIG file not found at $KUBECONFIG" >&2
    if [ "$CI_MODE" != "true" ]; then
        echo "Re-run setup-hypershift-ci-credentials.sh to regenerate it." >&2
    fi
    exit 1
fi

log_success "Using management cluster kubeconfig: $KUBECONFIG"

# ============================================================================
# 3. Verify AWS credentials
# ============================================================================

if [ -z "${AWS_ACCESS_KEY_ID:-}" ] || [ -z "${AWS_SECRET_ACCESS_KEY:-}" ]; then
    echo "Error: AWS credentials not set. Check .env.hypershift-ci" >&2
    exit 1
fi

log_success "AWS credentials configured"

# ============================================================================
# 4. Show configuration
# ============================================================================

echo ""
echo "Cluster configuration:"
echo "  Name:          $CLUSTER_NAME"
echo "  Region:        $AWS_REGION"
echo "  Replicas:      $REPLICAS"
echo "  Instance Type: $INSTANCE_TYPE"
echo "  OCP Version:   $OCP_VERSION"
echo "  Base Domain:   $BASE_DOMAIN"
echo "  IAM Scope Tag: kagenti.io/managed-by=$MANAGED_BY_TAG"
echo ""

# ============================================================================
# 5. Pre-flight check - verify no conflicting resources exist
# ============================================================================

CONTROL_PLANE_NS="clusters-$CLUSTER_NAME"

# Check if namespace already exists (indicates incomplete cleanup)
if oc get ns "$CONTROL_PLANE_NS" &>/dev/null; then
    echo ""
    echo "╔════════════════════════════════════════════════════════════════════════════╗"
    echo "║   ERROR: Control plane namespace already exists                            ║"
    echo "╚════════════════════════════════════════════════════════════════════════════╝"
    echo ""
    echo "Namespace: $CONTROL_PLANE_NS"
    echo ""
    echo "This indicates a previous cluster was not fully cleaned up."
    echo "Creating a new cluster with the same name will fail."
    echo ""
    echo "To fix this, run the destroy script first:"
    echo "  ./.github/scripts/hypershift/destroy-cluster.sh $CLUSTER_SUFFIX"
    echo ""
    echo "If the namespace is stuck, try force-deleting it:"
    echo "  oc delete ns $CONTROL_PLANE_NS --wait=false"
    echo "  oc patch ns $CONTROL_PLANE_NS -p '{\"metadata\":{\"finalizers\":null}}' --type=merge"
    echo ""
    exit 1
fi

# Check if HostedCluster resource already exists
if oc get hostedcluster "$CLUSTER_NAME" -n clusters &>/dev/null; then
    echo ""
    echo "╔════════════════════════════════════════════════════════════════════════════╗"
    echo "║   ERROR: HostedCluster resource already exists                             ║"
    echo "╚════════════════════════════════════════════════════════════════════════════╝"
    echo ""
    echo "HostedCluster: clusters/$CLUSTER_NAME"
    echo ""
    echo "To fix this, run the destroy script first:"
    echo "  ./.github/scripts/hypershift/destroy-cluster.sh $CLUSTER_SUFFIX"
    echo ""
    exit 1
fi

log_success "Pre-flight check passed - no conflicting resources"

# ============================================================================
# 6. Create cluster
# ============================================================================

log_info "Creating cluster (this may take 10-15 minutes)..."

cd "$HYPERSHIFT_AUTOMATION_DIR"

# Pass kagenti.io/managed-by tag for IAM scoping - this namespaced tag is applied
# to all AWS resources (VPC, subnets, security groups, EC2 instances, etc.) and
# allows IAM policies to restrict operations to only resources tagged with this value.
# The tag key follows Kubernetes label conventions to avoid conflicts with other tools.
ansible-playbook site.yml \
    -e '{"create": true, "destroy": false, "create_iam": false}' \
    -e '{"iam": {"hcp_role_name": "'"$HCP_ROLE_NAME"'"}}' \
    -e "domain=$BASE_DOMAIN" \
    -e "additional_tags=kagenti.io/managed-by=${MANAGED_BY_TAG}" \
    -e '{"clusters": [{"name": "'"$CLUSTER_NAME"'", "region": "'"$AWS_REGION"'", "replicas": '"$REPLICAS"', "instance_type": "'"$INSTANCE_TYPE"'", "image": "'"$OCP_VERSION"'"}]}'

# ============================================================================
# 7. Summary and Next Steps
# ============================================================================

CLUSTER_KUBECONFIG="$HOME/clusters/hcp/$CLUSTER_NAME/auth/kubeconfig"
CLUSTER_INFO="$HOME/clusters/hcp/$CLUSTER_NAME/cluster-info.txt"

# Wait for cluster to be ready (both CI and local mode)
export KUBECONFIG="$CLUSTER_KUBECONFIG"
log_info "Waiting for cluster API to be reachable..."

# Wait for API server with retries (up to 5 minutes)
for i in {1..30}; do
    if oc get nodes &>/dev/null; then
        log_success "Cluster API is reachable"
        break
    fi
    if [ $i -eq 30 ]; then
        log_warn "Cluster API not reachable after 5 minutes, continuing anyway..."
    else
        echo "  Attempt $i/30 - waiting for API server..."
        sleep 10
    fi
done

log_info "Waiting for nodes to be ready..."
oc wait --for=condition=Ready nodes --all --timeout=600s || log_warn "Timeout waiting for nodes, some may not be ready"
oc get nodes
oc get clusterversion

log_success "Cluster $CLUSTER_NAME created and ready"

# In CI mode, output for subsequent steps
if [ "$CI_MODE" = "true" ]; then
    echo "cluster_kubeconfig=$CLUSTER_KUBECONFIG" >> "$GITHUB_OUTPUT"
    echo "cluster_name=$CLUSTER_NAME" >> "$GITHUB_OUTPUT"
else
    # Local mode: show next steps
    echo ""
    echo "╔════════════════════════════════════════════════════════════════════════════╗"
    echo "║                           Cluster Created                                  ║"
    echo "╚════════════════════════════════════════════════════════════════════════════╝"
    echo ""

    if [ -f "$CLUSTER_INFO" ]; then
        echo "Cluster info (console URL, credentials):"
        echo "  cat $CLUSTER_INFO"
        echo ""
    fi

    cat << EOF
# ┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
# ┃ PHASE 3: DEPLOY KAGENTI + E2E (uses hosted cluster kubeconfig)              ┃
# ┃ Credentials: KUBECONFIG from created cluster (cluster-admin on hosted)      ┃
# ┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛
export KUBECONFIG=$CLUSTER_KUBECONFIG
oc get nodes

./.github/scripts/kagenti-operator/30-run-installer.sh --env ocp
./.github/scripts/kagenti-operator/41-wait-crds.sh
./.github/scripts/kagenti-operator/42-apply-pipeline-template.sh
./.github/scripts/kagenti-operator/43-wait-toolhive-crds.sh

./.github/scripts/kagenti-operator/71-build-weather-tool.sh
./.github/scripts/kagenti-operator/72-deploy-weather-tool.sh
./.github/scripts/kagenti-operator/73-patch-weather-tool.sh
./.github/scripts/kagenti-operator/74-deploy-weather-agent.sh

export AGENT_URL="https://\$(oc get route -n team1 weather-service -o jsonpath='{.spec.host}')"
export KAGENTI_CONFIG_FILE=deployments/envs/ocp_values.yaml
./.github/scripts/kagenti-operator/90-run-e2e-tests.sh

# ┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
# ┃ CLEANUP: Destroy cluster (uses scoped CI credentials)                       ┃
# ┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛
source .env.hypershift-ci
./.github/scripts/hypershift/destroy-cluster.sh ${CLUSTER_SUFFIX}
EOF
    echo ""
fi
