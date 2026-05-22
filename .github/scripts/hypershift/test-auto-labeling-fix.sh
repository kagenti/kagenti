#!/usr/bin/env bash
#
# Test Auto-Labeling Fix
#
# Creates a test cluster with auto-cleanup enabled and verifies labels are applied.
# Uses a very short cluster name to avoid AWS IAM length limits.
#
# USAGE:
#   ./test-auto-labeling-fix.sh [--skip-deletion]
#
# OPTIONS:
#   --skip-deletion  Keep the cluster after testing (don't delete)
#

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Parse arguments
SKIP_DELETION=false
if [[ "${1:-}" == "--skip-deletion" ]]; then
    SKIP_DELETION=true
fi

# Colors
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log_success() { echo -e "${GREEN}✓${NC} $1"; }
log_error() { echo -e "${RED}✗${NC} $1"; }
log_warn() { echo -e "${YELLOW}⚠${NC} $1"; }
log_info() { echo -e "${BLUE}→${NC} $1"; }

TEST_FAILED=0

# Use very short cluster suffix to avoid AWS IAM name length issues
CLUSTER_SUFFIX="al"  # "al" for "auto-labeling"
MANAGED_BY_TAG="${MANAGED_BY_TAG:-kagenti-hypershift-custom}"
FULL_CLUSTER_NAME="${MANAGED_BY_TAG}-${CLUSTER_SUFFIX}"

echo ""
echo "╔════════════════════════════════════════════════════════════════╗"
echo "║       Test Auto-Cleanup Labeling Fix                          ║"
echo "╚════════════════════════════════════════════════════════════════╝"
echo ""
echo "Cluster: $FULL_CLUSTER_NAME"
echo "Skip deletion: $SKIP_DELETION"
echo ""

# ============================================================================
# Step 1: Check prerequisites
# ============================================================================

log_info "Checking prerequisites..."

if [ -z "${KUBECONFIG:-}" ]; then
    log_error "KUBECONFIG not set"
    log_info "Please source credentials first: source .env.kagenti-hypershift-custom"
    exit 1
fi

if ! oc whoami &>/dev/null; then
    log_error "Cannot access management cluster"
    log_info "Please ensure KUBECONFIG points to management cluster"
    exit 1
fi

MGMT_CLUSTER=$(oc whoami --show-server 2>/dev/null || echo "unknown")
log_success "Management cluster access: $MGMT_CLUSTER"

# Check if cluster already exists
if oc get hostedcluster "$FULL_CLUSTER_NAME" -n clusters &>/dev/null; then
    log_warn "Cluster $FULL_CLUSTER_NAME already exists"
    log_info "Skipping creation, will verify labels on existing cluster"
    SKIP_CREATION=true
else
    SKIP_CREATION=false
fi

# ============================================================================
# Step 2: Create cluster with auto-cleanup enabled
# ============================================================================

if [ "$SKIP_CREATION" = "false" ]; then
    log_info "Creating cluster with ENABLE_AUTO_CLEANUP=true..."
    log_info "This will take ~15 minutes..."
    echo ""

    if ENABLE_AUTO_CLEANUP=true "$SCRIPT_DIR/create-cluster.sh" "$CLUSTER_SUFFIX" > /tmp/test-auto-labeling-create.log 2>&1; then
        log_success "Cluster created successfully"
    else
        log_error "Cluster creation failed"
        echo ""
        echo "Last 50 lines of creation log:"
        tail -50 /tmp/test-auto-labeling-create.log
        exit 1
    fi
fi

# ============================================================================
# Step 3: Verify labels were applied
# ============================================================================

log_info "Verifying auto-cleanup labels..."
echo ""

# Give labels a moment to propagate
sleep 2

if ! oc get hostedcluster "$FULL_CLUSTER_NAME" -n clusters &>/dev/null; then
    log_error "Cluster $FULL_CLUSTER_NAME not found"
    exit 1
fi

# Check required labels
LABELS=$(oc get hostedcluster "$FULL_CLUSTER_NAME" -n clusters -o jsonpath='{.metadata.labels}' 2>/dev/null)

AUTO_CLEANUP=$(echo "$LABELS" | jq -r '.["kagenti.io/auto-cleanup"] // "missing"')
TTL_HOURS=$(echo "$LABELS" | jq -r '.["kagenti.io/ttl-hours"] // "missing"')
CLUSTER_TYPE=$(echo "$LABELS" | jq -r '.["kagenti.io/cluster-type"] // "missing"')

# Verify each label
if [ "$AUTO_CLEANUP" = "enabled" ]; then
    log_success "Label kagenti.io/auto-cleanup: $AUTO_CLEANUP"
else
    log_error "Label kagenti.io/auto-cleanup missing or incorrect: $AUTO_CLEANUP"
    TEST_FAILED=1
fi

if [ "$TTL_HOURS" != "missing" ] && [ "$TTL_HOURS" != "null" ]; then
    log_success "Label kagenti.io/ttl-hours: $TTL_HOURS"
else
    log_error "Label kagenti.io/ttl-hours missing"
    TEST_FAILED=1
fi

if [ "$CLUSTER_TYPE" != "missing" ] && [ "$CLUSTER_TYPE" != "null" ]; then
    log_success "Label kagenti.io/cluster-type: $CLUSTER_TYPE"
else
    log_error "Label kagenti.io/cluster-type missing"
    TEST_FAILED=1
fi

# Show all auto-cleanup labels
echo ""
log_info "All auto-cleanup labels:"
echo "$LABELS" | jq -r 'to_entries | map(select(.key | startswith("kagenti.io/"))) | from_entries'

# ============================================================================
# Step 4: Test with cleanup script
# ============================================================================

log_info "Testing with cleanup script (dry-run)..."
echo ""

if "$SCRIPT_DIR/cleanup-stale-clusters.sh" --dry-run --verbose 2>&1 | tee /tmp/test-cleanup-detection.log | grep -q "$FULL_CLUSTER_NAME"; then
    log_success "Cleanup script detected the cluster"

    # Check if it's correctly identified as NOT stale (should have 168h TTL for dev cluster)
    if grep -q "OK.*$FULL_CLUSTER_NAME" /tmp/test-cleanup-detection.log; then
        log_success "Cluster correctly identified as NOT stale (fresh cluster with long TTL)"
    else
        log_warn "Cluster status unclear, check output above"
    fi
else
    log_error "Cleanup script did not detect the cluster"
    TEST_FAILED=1
fi

# ============================================================================
# Step 5: Cleanup (optional)
# ============================================================================

if [ "$SKIP_DELETION" = "false" ]; then
    echo ""
    log_info "Cleaning up test cluster..."

    if "$SCRIPT_DIR/../local-setup/hypershift-full-test.sh" --include-cluster-destroy "$CLUSTER_SUFFIX" > /tmp/test-auto-labeling-destroy.log 2>&1; then
        log_success "Test cluster deleted"
    else
        log_warn "Cluster deletion may have failed (check /tmp/test-auto-labeling-destroy.log)"
    fi
else
    echo ""
    log_info "Skipping deletion (cluster preserved: $FULL_CLUSTER_NAME)"
    log_info "To delete manually: $SCRIPT_DIR/../local-setup/hypershift-full-test.sh --include-cluster-destroy $CLUSTER_SUFFIX"
fi

# ============================================================================
# Summary
# ============================================================================

echo ""
echo "╔════════════════════════════════════════════════════════════════╗"
echo "║                  Test Summary                                  ║"
echo "╚════════════════════════════════════════════════════════════════╝"
echo ""

if [ $TEST_FAILED -eq 0 ]; then
    log_success "✅ AUTO-LABELING FIX VERIFIED!"
    echo ""
    echo "The auto-cleanup labels are now correctly applied during cluster creation."
    echo "Phase 4 (CI Integration) can proceed."
    echo ""
    exit 0
else
    log_error "❌ AUTO-LABELING FIX FAILED"
    echo ""
    echo "Some labels were not applied correctly."
    echo "Check the logs above for details."
    echo ""
    exit 1
fi
