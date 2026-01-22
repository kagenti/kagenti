#!/usr/bin/env bash
#
# Destroy HyperShift Cluster
#
# Destroys an ephemeral OpenShift cluster created via HyperShift.
#
# USAGE:
#   ./.github/scripts/hypershift/destroy-cluster.sh <cluster-suffix-or-full-name>
#
# EXAMPLES:
#   ./.github/scripts/hypershift/destroy-cluster.sh local      # destroys kagenti-hypershift-ci-local
#   ./.github/scripts/hypershift/destroy-cluster.sh pr123      # destroys kagenti-hypershift-ci-pr123
#   ./.github/scripts/hypershift/destroy-cluster.sh kagenti-hypershift-ci-local  # full name also works
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

# Require cluster name/suffix
if [ $# -lt 1 ]; then
    # Load credentials to get MANAGED_BY_TAG for dynamic help message
    if [ -f "$REPO_ROOT/.env.hypershift-ci" ]; then
        # shellcheck source=/dev/null
        source "$REPO_ROOT/.env.hypershift-ci"
    fi
    MANAGED_BY_TAG="${MANAGED_BY_TAG:-kagenti-hypershift-ci}"
    echo "Usage: $0 <cluster-suffix-or-full-name>" >&2
    echo "Example: $0 local                    # destroys ${MANAGED_BY_TAG}-local" >&2
    echo "Example: $0 ${MANAGED_BY_TAG}-local  # full name also works" >&2
    exit 1
fi

CLUSTER_INPUT="$1"

# Colors
GREEN='\033[0;32m'
BLUE='\033[0;34m'
RED='\033[0;31m'
NC='\033[0m'

log_info() { echo -e "${BLUE}→${NC} $1"; }
log_success() { echo -e "${GREEN}✓${NC} $1"; }

echo ""
echo "╔════════════════════════════════════════════════════════════════╗"
echo "║           Destroy HyperShift Cluster                           ║"
echo "╚════════════════════════════════════════════════════════════════╝"
echo ""

# ============================================================================
# 1. Load credentials
# ============================================================================

if [ "$CI_MODE" = "true" ]; then
    # CI mode: credentials are passed via environment variables from GitHub secrets
    # Required: MANAGED_BY_TAG, AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_REGION,
    #           HCP_ROLE_NAME, KUBECONFIG (already set in GITHUB_ENV)
    log_success "Using CI credentials from environment"
else
    # Local mode: load from .env file
    if [ ! -f "$REPO_ROOT/.env.hypershift-ci" ]; then
        echo "Error: .env.hypershift-ci not found." >&2
        exit 1
    fi
    # shellcheck source=/dev/null
    source "$REPO_ROOT/.env.hypershift-ci"
    log_success "Loaded credentials from .env.hypershift-ci"
fi

# Construct full cluster name if only suffix was provided
# If input starts with MANAGED_BY_TAG, use as-is; otherwise prefix it
if [[ "$CLUSTER_INPUT" == "${MANAGED_BY_TAG}-"* ]]; then
    CLUSTER_NAME="$CLUSTER_INPUT"
else
    CLUSTER_NAME="${MANAGED_BY_TAG}-${CLUSTER_INPUT}"
fi
echo "Cluster to destroy: $CLUSTER_NAME"
echo ""

# ============================================================================
# 2. Verify prerequisites
# ============================================================================

if [ ! -d "$HYPERSHIFT_AUTOMATION_DIR" ]; then
    if [ "$CI_MODE" = "true" ]; then
        echo "Error: hypershift-automation not found at $HYPERSHIFT_AUTOMATION_DIR" >&2
        echo "Ensure the clone step ran before this script." >&2
    else
        echo "Error: hypershift-automation not found at $HYPERSHIFT_AUTOMATION_DIR" >&2
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
# 4. Pre-check: Handle already-stuck finalizers BEFORE ansible
# ============================================================================

# Check if HostedCluster exists and is already stuck in deletion
HC_EXISTS=$(oc get hostedcluster -n clusters "$CLUSTER_NAME" -o name 2>/dev/null || echo "")
DELETION_TS=$(oc get hostedcluster -n clusters "$CLUSTER_NAME" -o jsonpath='{.metadata.deletionTimestamp}' 2>/dev/null || echo "")

if [ -n "$HC_EXISTS" ] && [ -n "$DELETION_TS" ]; then
    log_info "HostedCluster already marked for deletion (since $DELETION_TS)"
    log_info "Checking if AWS resources are already cleaned up..."

    # Use the debug script with --check mode to verify AWS cleanup
    if "$SCRIPT_DIR/debug-aws-hypershift.sh" --check "$CLUSTER_NAME"; then
        log_success "All AWS resources are already deleted"

        # Get current finalizers
        FINALIZERS=$(oc get hostedcluster -n clusters "$CLUSTER_NAME" -o jsonpath='{.metadata.finalizers}' 2>/dev/null || echo "")

        if [ -n "$FINALIZERS" ] && [ "$FINALIZERS" != "null" ]; then
            log_info "Removing stuck finalizer (skipping ansible wait loops)..."
            oc patch hostedcluster -n clusters "$CLUSTER_NAME" \
                -p '{"metadata":{"finalizers":null}}' --type=merge
            log_success "Finalizer removed"

            # Wait for deletion
            log_info "Waiting for HostedCluster to be deleted..."
            for i in {1..30}; do
                if ! oc get hostedcluster -n clusters "$CLUSTER_NAME" &>/dev/null; then
                    log_success "HostedCluster deleted"
                    break
                fi
                sleep 2
            done

            # Skip ansible if cluster is now gone
            if ! oc get hostedcluster -n clusters "$CLUSTER_NAME" &>/dev/null; then
                log_success "Cluster cleanup complete (finalizer was stuck, no ansible needed)"
                # Jump to local file cleanup
                SKIP_ANSIBLE=true
            fi
        fi
    else
        log_info "AWS resources still exist, proceeding with ansible destroy..."
    fi
fi

# ============================================================================
# 5. Destroy cluster via ansible (if needed)
# ============================================================================

if [ "${SKIP_ANSIBLE:-false}" != "true" ]; then
    # Check if cluster still exists
    if oc get hostedcluster -n clusters "$CLUSTER_NAME" &>/dev/null; then
        log_info "Destroying cluster '$CLUSTER_NAME' via ansible..."

        cd "$HYPERSHIFT_AUTOMATION_DIR"

        ansible-playbook site.yml \
            -e '{"create": false, "destroy": true, "create_iam": false}' \
            -e '{"iam": {"hcp_role_name": "'"$HCP_ROLE_NAME"'"}}' \
            -e '{"clusters": [{"name": "'"$CLUSTER_NAME"'", "region": "'"$AWS_REGION"'"}]}' || true

        cd "$REPO_ROOT"

        # Post-ansible check for stuck finalizers
        HC_EXISTS=$(oc get hostedcluster -n clusters "$CLUSTER_NAME" -o name 2>/dev/null || echo "")

        if [ -n "$HC_EXISTS" ]; then
            log_info "HostedCluster still exists after ansible, checking AWS resources..."

            if "$SCRIPT_DIR/debug-aws-hypershift.sh" --check "$CLUSTER_NAME"; then
                log_success "All AWS resources are deleted"

                FINALIZERS=$(oc get hostedcluster -n clusters "$CLUSTER_NAME" -o jsonpath='{.metadata.finalizers}' 2>/dev/null || echo "")

                if [ -n "$FINALIZERS" ] && [ "$FINALIZERS" != "null" ]; then
                    log_info "Removing stuck finalizer..."
                    oc patch hostedcluster -n clusters "$CLUSTER_NAME" \
                        -p '{"metadata":{"finalizers":null}}' --type=merge
                    log_success "Finalizer removed"

                    log_info "Waiting for HostedCluster to be deleted..."
                    for i in {1..30}; do
                        if ! oc get hostedcluster -n clusters "$CLUSTER_NAME" &>/dev/null; then
                            log_success "HostedCluster deleted"
                            break
                        fi
                        sleep 2
                    done
                fi
            else
                echo -e "${RED}✗${NC} AWS resources still exist. Manual cleanup may be required."
                echo ""
                echo "  Run full debug for details:"
                echo "  ./.github/scripts/hypershift/debug-aws-hypershift.sh $CLUSTER_NAME"
            fi
        fi
    else
        log_success "Cluster already deleted"
    fi
fi

# ============================================================================
# 6. Cleanup control plane namespace (prevents encryption key mismatch on retry)
# ============================================================================

CONTROL_PLANE_NS="clusters-$CLUSTER_NAME"
if oc get ns "$CONTROL_PLANE_NS" &>/dev/null; then
    log_info "Waiting for control plane namespace '$CONTROL_PLANE_NS' to be deleted..."

    # Wait for namespace to be deleted (up to 2 minutes)
    NS_DELETED=false
    for i in {1..24}; do
        if ! oc get ns "$CONTROL_PLANE_NS" &>/dev/null; then
            NS_DELETED=true
            break
        fi
        echo "  Waiting... ($i/24)"
        sleep 5
    done

    if [ "$NS_DELETED" = "false" ]; then
        log_info "Namespace still exists, force-deleting..."

        # Remove finalizers from all resources in namespace
        # Include deployments which can have hypershift.openshift.io/component-finalizer
        for resource in hostedcontrolplane deployment secret configmap pvc; do
            oc get "$resource" -n "$CONTROL_PLANE_NS" -o name 2>/dev/null | while read -r name; do
                oc patch "$name" -n "$CONTROL_PLANE_NS" -p '{"metadata":{"finalizers":null}}' --type=merge 2>/dev/null || true
            done
        done

        # Delete namespace with --wait=false and remove finalizers
        oc delete ns "$CONTROL_PLANE_NS" --wait=false 2>/dev/null || true
        oc patch ns "$CONTROL_PLANE_NS" -p '{"metadata":{"finalizers":null}}' --type=merge 2>/dev/null || true

        # Wait again for namespace deletion
        for i in {1..12}; do
            if ! oc get ns "$CONTROL_PLANE_NS" &>/dev/null; then
                break
            fi
            sleep 5
        done
    fi

    if ! oc get ns "$CONTROL_PLANE_NS" &>/dev/null; then
        log_success "Control plane namespace deleted"
    else
        echo -e "${RED}✗${NC} Failed to delete namespace '$CONTROL_PLANE_NS'. Manual cleanup may be required."
    fi
else
    log_success "Control plane namespace already deleted"
fi

# ============================================================================
# 7. Cleanup local files
# ============================================================================

CLUSTER_DIR="$HOME/clusters/hcp/$CLUSTER_NAME"
if [ -d "$CLUSTER_DIR" ]; then
    log_info "Removing local cluster directory..."
    rm -rf "$CLUSTER_DIR"
    log_success "Removed $CLUSTER_DIR"
fi

echo ""
echo "╔════════════════════════════════════════════════════════════════╗"
echo "║                    Cluster Destroyed                           ║"
echo "╚════════════════════════════════════════════════════════════════╝"
echo ""
