#!/usr/bin/env bash
#
# MCE Upgrade Wrapper Script
#
# This script safely upgrades MCE while preserving HyperShift OIDC S3 configuration.
# It backs up the current config, approves the upgrade, waits for completion,
# and restores the OIDC configuration.
#
# USAGE:
#   ./mce-upgrade-wrapper.sh [install-plan-name]
#
# If install-plan-name is not provided, the script will detect pending upgrades.
#

set -euo pipefail

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log_info() { echo -e "${BLUE}→${NC} $1"; }
log_success() { echo -e "${GREEN}✓${NC} $1"; }
log_warn() { echo -e "${YELLOW}⚠${NC} $1"; }
log_error() { echo -e "${RED}✗${NC} $1"; exit 1; }

echo ""
echo "╔════════════════════════════════════════════════════════════════╗"
echo "║           MCE Upgrade with OIDC Preservation                   ║"
echo "╚════════════════════════════════════════════════════════════════╝"
echo ""

# Check prerequisites
command -v oc >/dev/null 2>&1 || log_error "oc CLI not found"
command -v jq >/dev/null 2>&1 || log_error "jq not found"

# Verify cluster access
if ! oc whoami &>/dev/null; then
    log_error "Not logged into OpenShift cluster"
fi

log_info "Logged in as: $(oc whoami) @ $(oc whoami --show-server)"
echo ""

# ============================================================================
# Step 1: Backup current OIDC configuration
# ============================================================================
log_info "Step 1: Backing up HyperShift OIDC configuration..."

BACKUP_DIR="/tmp/mce-upgrade-backup-$(date +%Y%m%d-%H%M%S)"
mkdir -p "$BACKUP_DIR"

# Check if OIDC is configured
OIDC_CONFIGURED=false
if oc get deployment operator -n hypershift -o jsonpath='{.spec.template.spec.containers[0].args}' 2>/dev/null | grep -q "oidc-storage-provider-s3"; then
    OIDC_CONFIGURED=true
    log_success "OIDC configuration detected"

    # Extract OIDC configuration
    OIDC_BUCKET=$(oc get deployment operator -n hypershift -o json | \
        jq -r '.spec.template.spec.containers[0].args[] | select(contains("oidc-storage-provider-s3-bucket-name"))' | \
        cut -d= -f2)
    OIDC_REGION=$(oc get deployment operator -n hypershift -o json | \
        jq -r '.spec.template.spec.containers[0].args[] | select(contains("oidc-storage-provider-s3-region"))' | \
        cut -d= -f2)

    log_info "  Bucket: $OIDC_BUCKET"
    log_info "  Region: $OIDC_REGION"

    # Save to backup file
    cat > "$BACKUP_DIR/oidc-patch.json" <<EOF
[
  {"op": "add", "path": "/spec/template/spec/containers/0/args/-", "value": "--oidc-storage-provider-s3-bucket-name=$OIDC_BUCKET"},
  {"op": "add", "path": "/spec/template/spec/containers/0/args/-", "value": "--oidc-storage-provider-s3-region=$OIDC_REGION"},
  {"op": "add", "path": "/spec/template/spec/containers/0/args/-", "value": "--oidc-storage-provider-s3-credentials=/etc/oidc-storage-provider-s3-creds/credentials"}
]
EOF

    log_success "OIDC configuration backed up to: $BACKUP_DIR/oidc-patch.json"
else
    log_warn "No OIDC configuration found (not configured or already removed)"
fi

echo ""

# ============================================================================
# Step 2: Check for pending MCE upgrade
# ============================================================================
log_info "Step 2: Checking for pending MCE upgrades..."

INSTALL_PLAN="${1:-}"

if [ -z "$INSTALL_PLAN" ]; then
    # Auto-detect pending install plans
    PENDING_PLANS=$(oc get installplan -n multicluster-engine \
        -o json | jq -r '.items[] | select(.spec.approved == false and (.spec.clusterServiceVersionNames[] | contains("multicluster-engine"))) | .metadata.name' 2>/dev/null || echo "")

    if [ -z "$PENDING_PLANS" ]; then
        log_warn "No pending MCE upgrades found"
        log_info "Current MCE version: $(oc get subscription multicluster-engine -n multicluster-engine -o jsonpath='{.status.currentCSV}')"

        if [ "$OIDC_CONFIGURED" = true ]; then
            log_info "OIDC configuration is intact, no action needed"
        fi
        exit 0
    fi

    # Use the first pending plan
    INSTALL_PLAN=$(echo "$PENDING_PLANS" | head -n1)
fi

log_success "Found install plan: $INSTALL_PLAN"

# Get upgrade details
CURRENT_CSV=$(oc get subscription multicluster-engine -n multicluster-engine -o jsonpath='{.status.currentCSV}')
TARGET_CSV=$(oc get installplan "$INSTALL_PLAN" -n multicluster-engine -o jsonpath='{.spec.clusterServiceVersionNames[0]}' | grep multicluster-engine || echo "unknown")

log_info "  Current: $CURRENT_CSV"
log_info "  Target:  $TARGET_CSV"

echo ""
read -p "$(echo -e "${YELLOW}Proceed with MCE upgrade? (y/N):${NC} ")" -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    log_warn "Upgrade cancelled by user"
    exit 0
fi

echo ""

# ============================================================================
# Step 3: Approve and monitor upgrade
# ============================================================================
log_info "Step 3: Approving MCE upgrade..."

oc patch installplan "$INSTALL_PLAN" -n multicluster-engine \
    --type merge -p '{"spec":{"approved":true}}'

log_success "Install plan approved"
log_info "Waiting for MCE upgrade to complete (this may take 5-10 minutes)..."

# Wait for new CSV to be installed
TIMEOUT=600  # 10 minutes
ELAPSED=0
while [ $ELAPSED -lt $TIMEOUT ]; do
    CURRENT_VERSION=$(oc get subscription multicluster-engine -n multicluster-engine -o jsonpath='{.status.installedCSV}' 2>/dev/null || echo "")

    if [ -n "$CURRENT_VERSION" ] && [ "$CURRENT_VERSION" = "$TARGET_CSV" ]; then
        log_success "MCE upgraded to: $TARGET_CSV"
        break
    fi

    if [ $((ELAPSED % 30)) -eq 0 ]; then
        log_info "  Still upgrading... ($ELAPSED/$TIMEOUT seconds)"
    fi

    sleep 5
    ELAPSED=$((ELAPSED + 5))
done

if [ $ELAPSED -ge $TIMEOUT ]; then
    log_error "Upgrade timeout after $TIMEOUT seconds"
fi

# Wait for HyperShift operator to stabilize
log_info "Waiting for HyperShift operator to stabilize..."
sleep 10

if oc wait --for=condition=Available deployment/operator -n hypershift --timeout=300s 2>/dev/null; then
    log_success "HyperShift operator is available"
else
    log_warn "HyperShift operator may not be fully ready, continuing anyway..."
fi

echo ""

# ============================================================================
# Step 4: Restore OIDC configuration
# ============================================================================
if [ "$OIDC_CONFIGURED" = true ]; then
    log_info "Step 4: Restoring HyperShift OIDC configuration..."

    # Check if OIDC args were removed (expected)
    if oc get deployment operator -n hypershift -o jsonpath='{.spec.template.spec.containers[0].args}' 2>/dev/null | grep -q "oidc-storage-provider-s3"; then
        log_warn "OIDC configuration still present (unexpected - MCE may have preserved it)"
    else
        log_info "OIDC args removed as expected, restoring..."

        # Apply the backup patch
        oc patch deployment operator -n hypershift \
            --type=json \
            --patch-file="$BACKUP_DIR/oidc-patch.json"

        log_success "OIDC configuration restored"

        # Wait for operator rollout
        log_info "Waiting for HyperShift operator rollout..."
        if oc rollout status deployment operator -n hypershift --timeout=180s 2>/dev/null; then
            log_success "HyperShift operator rolled out successfully"
        else
            log_warn "Operator rollout may be slow, check manually: oc rollout status deployment operator -n hypershift"
        fi
    fi
else
    log_info "Step 4: Skipped (no OIDC configuration to restore)"
fi

echo ""

# ============================================================================
# Step 5: Verify configuration
# ============================================================================
log_info "Step 5: Verifying final state..."

# Run preflight check if available
PREFLIGHT_SCRIPT="$(dirname "$0")/preflight-check.sh"
if [ -f "$PREFLIGHT_SCRIPT" ]; then
    log_info "Running preflight check..."
    if bash "$PREFLIGHT_SCRIPT" 2>&1 | grep -q "✓.*OIDC"; then
        log_success "OIDC configuration verified"
    else
        log_warn "Preflight check did not confirm OIDC - manual verification recommended"
    fi
else
    # Manual verification
    if [ "$OIDC_CONFIGURED" = true ]; then
        if oc get deployment operator -n hypershift -o jsonpath='{.spec.template.spec.containers[0].args}' 2>/dev/null | grep -q "oidc-storage-provider-s3"; then
            log_success "OIDC configuration verified in operator deployment"
        else
            log_error "OIDC configuration NOT found in operator deployment"
        fi
    fi
fi

log_success "MCE version: $(oc get subscription multicluster-engine -n multicluster-engine -o jsonpath='{.status.installedCSV}')"

echo ""
echo "╔════════════════════════════════════════════════════════════════╗"
echo "║  ✓ MCE upgrade completed successfully                          ║"
echo "╚════════════════════════════════════════════════════════════════╝"
echo ""
log_info "Backup saved to: $BACKUP_DIR"
echo ""
