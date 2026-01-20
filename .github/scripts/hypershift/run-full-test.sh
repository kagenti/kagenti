#!/usr/bin/env bash
#
# Run Full HyperShift Test (Phase 2 + Phase 3)
#
# Creates a HyperShift cluster, deploys Kagenti, and runs E2E tests.
# Stops immediately if any step fails.
#
# USAGE:
#   ./.github/scripts/hypershift/run-full-test.sh [options] [cluster-suffix]
#
# OPTIONS:
#   --skip-create    Reuse existing cluster (skip cluster creation)
#   --skip-destroy   Keep cluster after tests (skip cluster destruction)
#   --clean-kagenti  Uninstall kagenti before installing (fresh install)
#
# EXAMPLES:
#   ./.github/scripts/hypershift/run-full-test.sh                    # Full CI run
#   ./.github/scripts/hypershift/run-full-test.sh --skip-destroy     # First dev run, keep cluster
#   ./.github/scripts/hypershift/run-full-test.sh --skip-create --skip-destroy  # Iterate on existing cluster
#   ./.github/scripts/hypershift/run-full-test.sh --skip-create --clean-kagenti --skip-destroy  # Fresh kagenti on existing cluster
#   ./.github/scripts/hypershift/run-full-test.sh --skip-create      # Final run, destroy cluster
#

set -euo pipefail

# Handle Ctrl+C properly - kill all child processes
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

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"

# Parse arguments
SKIP_CREATE=false
SKIP_DESTROY=false
CLEAN_KAGENTI=false
CLUSTER_SUFFIX=""

while [[ $# -gt 0 ]]; do
    case $1 in
        --skip-create)
            SKIP_CREATE=true
            shift
            ;;
        --skip-destroy)
            SKIP_DESTROY=true
            shift
            ;;
        --clean-kagenti)
            CLEAN_KAGENTI=true
            shift
            ;;
        *)
            CLUSTER_SUFFIX="$1"
            shift
            ;;
    esac
done

# Default suffix
CLUSTER_SUFFIX="${CLUSTER_SUFFIX:-local}"

# Colors
GREEN='\033[0;32m'
BLUE='\033[0;34m'
RED='\033[0;31m'
NC='\033[0m'

log_phase() { echo -e "\n${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"; echo -e "${BLUE}┃${NC} $1"; echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}\n"; }
log_step() { echo -e "${GREEN}▶${NC} $1"; }
log_error() { echo -e "${RED}✗${NC} $1" >&2; }

cd "$REPO_ROOT"

# ============================================================================
# Load credentials
# ============================================================================

if [ ! -f ".env.hypershift-ci" ]; then
    log_error ".env.hypershift-ci not found. Run setup-hypershift-ci-credentials.sh first."
    exit 1
fi

# shellcheck source=/dev/null
source .env.hypershift-ci

MANAGED_BY_TAG="${MANAGED_BY_TAG:-kagenti-hypershift-ci}"
CLUSTER_NAME="${MANAGED_BY_TAG}-${CLUSTER_SUFFIX}"

echo ""
echo "Configuration:"
echo "  Cluster Name:   $CLUSTER_NAME"
echo "  Skip Create:    $SKIP_CREATE"
echo "  Skip Destroy:   $SKIP_DESTROY"
echo "  Clean Kagenti:  $CLEAN_KAGENTI"
echo ""

# ============================================================================
# PHASE 2: Create Cluster
# ============================================================================

if [ "$SKIP_CREATE" = "false" ]; then
    log_phase "PHASE 2: Create HyperShift Cluster"
    log_step "Creating cluster: $CLUSTER_NAME"

    ./.github/scripts/hypershift/create-cluster.sh "$CLUSTER_SUFFIX"
else
    log_phase "PHASE 2: Skipping Cluster Creation (--skip-create)"
fi

# ============================================================================
# PHASE 3: Deploy Kagenti + E2E Tests
# ============================================================================

log_phase "PHASE 3: Deploy Kagenti + Run E2E Tests"

# Set kubeconfig for the created cluster
export KUBECONFIG="$HOME/clusters/hcp/$CLUSTER_NAME/auth/kubeconfig"

if [ ! -f "$KUBECONFIG" ]; then
    log_error "Kubeconfig not found at $KUBECONFIG"
    log_error "Either cluster creation failed or cluster doesn't exist."
    exit 1
fi

log_step "Using kubeconfig: $KUBECONFIG"
oc get nodes

if [ "$CLEAN_KAGENTI" = "true" ]; then
    log_step "Uninstalling Kagenti (--clean-kagenti)..."
    ./deployments/ansible/cleanup-install.sh
fi

log_step "Installing Kagenti platform..."
./.github/scripts/kagenti-operator/30-run-installer.sh --env ocp

log_step "Waiting for CRDs..."
./.github/scripts/kagenti-operator/41-wait-crds.sh

log_step "Applying pipeline template..."
./.github/scripts/kagenti-operator/42-apply-pipeline-template.sh

log_step "Waiting for Toolhive CRDs..."
./.github/scripts/kagenti-operator/43-wait-toolhive-crds.sh

log_step "Building weather-tool..."
./.github/scripts/kagenti-operator/71-build-weather-tool.sh

log_step "Deploying weather-tool..."
./.github/scripts/kagenti-operator/72-deploy-weather-tool.sh

log_step "Patching weather-tool..."
./.github/scripts/kagenti-operator/73-patch-weather-tool.sh

log_step "Deploying weather-agent..."
./.github/scripts/kagenti-operator/74-deploy-weather-agent.sh

log_step "Running E2E tests..."
export AGENT_URL="https://$(oc get route -n team1 weather-service -o jsonpath='{.spec.host}')"
export KAGENTI_CONFIG_FILE=deployments/envs/ocp_values.yaml
./.github/scripts/kagenti-operator/90-run-e2e-tests.sh

# ============================================================================
# Cleanup (optional)
# ============================================================================

if [ "$SKIP_DESTROY" = "false" ]; then
    log_phase "CLEANUP: Destroying Cluster"

    # Reload CI creds (in case KUBECONFIG was changed)
    # shellcheck source=/dev/null
    source .env.hypershift-ci

    ./.github/scripts/hypershift/destroy-cluster.sh "$CLUSTER_SUFFIX"
else
    log_phase "CLEANUP: Skipping (--skip-destroy)"
    echo ""
    echo "Cluster kept for debugging. To destroy later:"
    echo "  source .env.hypershift-ci"
    echo "  ./.github/scripts/hypershift/destroy-cluster.sh $CLUSTER_SUFFIX"
    echo ""
fi

echo ""
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${GREEN}┃${NC} Full test completed successfully!"
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""
