#!/usr/bin/env bash
#
# Cleanup Stale HyperShift Clusters
#
# Detects and deletes clusters with auto-cleanup labels that have exceeded their TTL.
#
# USAGE:
#   ./cleanup-stale-clusters.sh [OPTIONS]
#
# OPTIONS:
#   --dry-run           Show what would be deleted (default behavior)
#   --apply             Actually delete stale clusters (USE WITH CAUTION)
#   --pattern PATTERN   Only process clusters matching pattern (e.g., "*-pr-*")
#   --verbose           Show all clusters, not just stale ones
#   --help              Show this help message
#
# DETECTION CRITERIA:
#   1. Has label: kagenti.io/auto-cleanup=enabled
#   2. Age > kagenti.io/ttl-hours (in hours)
#   3. NOT protected (kagenti.io/protected!=true)
#   4. Matches MANAGED_BY_TAG pattern (if filtering enabled)
#
# EXAMPLES:
#   # Dry-run: show what would be deleted
#   ./cleanup-stale-clusters.sh --dry-run
#
#   # Apply: actually delete stale clusters
#   ./cleanup-stale-clusters.sh --apply
#
#   # Only check CI clusters
#   ./cleanup-stale-clusters.sh --dry-run --pattern "kagenti-hypershift-ci-*"
#
#   # Verbose: show all clusters with auto-cleanup enabled
#   ./cleanup-stale-clusters.sh --dry-run --verbose
#

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"

# ============================================================================
# Parse arguments
# ============================================================================

DRY_RUN=true
PATTERN_FILTER=""
VERBOSE=false

while [[ $# -gt 0 ]]; do
    case "$1" in
        --dry-run)
            DRY_RUN=true
            shift
            ;;
        --apply)
            DRY_RUN=false
            shift
            ;;
        --pattern)
            PATTERN_FILTER="$2"
            shift 2
            ;;
        --verbose)
            VERBOSE=true
            shift
            ;;
        --help)
            grep "^#" "$0" | grep -v "#!/usr/bin/env" | sed 's/^# //' | sed 's/^#//'
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            echo "Use --help for usage information"
            exit 1
            ;;
    esac
done

# ============================================================================
# Colors and logging
# ============================================================================

GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log_success() { echo -e "${GREEN}✓${NC} $1"; }
log_error() { echo -e "${RED}✗${NC} $1"; }
log_warn() { echo -e "${YELLOW}⚠${NC} $1"; }
log_info() { echo -e "${BLUE}→${NC} $1"; }

# ============================================================================
# Prerequisites
# ============================================================================

if [ -z "${KUBECONFIG:-}" ]; then
    log_error "KUBECONFIG not set"
    log_info "Please source credentials first (e.g., source .env.kagenti-hypershift-custom)"
    exit 1
fi

if ! command -v oc &>/dev/null; then
    log_error "oc command not found"
    exit 1
fi

if ! oc whoami &>/dev/null; then
    log_error "Cannot access management cluster"
    log_info "Please ensure KUBECONFIG points to management cluster"
    exit 1
fi

MGMT_CLUSTER=$(oc whoami --show-server 2>/dev/null || echo "unknown")

# ============================================================================
# Banner
# ============================================================================

echo ""
echo "╔════════════════════════════════════════════════════════════════╗"
echo "║          Cleanup Stale HyperShift Clusters                     ║"
echo "╚════════════════════════════════════════════════════════════════╝"
echo ""
echo "Management Cluster: $MGMT_CLUSTER"
echo "Mode: $([ "$DRY_RUN" = "true" ] && echo "DRY-RUN (no deletions)" || echo "APPLY (will delete)")"
[ -n "$PATTERN_FILTER" ] && echo "Pattern filter: $PATTERN_FILTER"
echo ""

# ============================================================================
# Find clusters with auto-cleanup enabled
# ============================================================================

log_info "Finding clusters with auto-cleanup enabled..."

CLUSTERS=$(oc get hostedclusters -n clusters \
    -l kagenti.io/auto-cleanup=enabled \
    -o jsonpath='{range .items[*]}{.metadata.name}{" "}{end}' 2>/dev/null || echo "")

if [ -z "$CLUSTERS" ]; then
    log_info "No clusters found with auto-cleanup labels"
    exit 0
fi

CLUSTER_COUNT=$(echo "$CLUSTERS" | wc -w | tr -d ' ')
log_info "Found $CLUSTER_COUNT cluster(s) with auto-cleanup enabled"
echo ""

# ============================================================================
# Process each cluster
# ============================================================================

NOW_EPOCH=$(date +%s)
STALE_COUNT=0
PROTECTED_COUNT=0
OK_COUNT=0
DELETED_COUNT=0
FAILED_COUNT=0

for CLUSTER_NAME in $CLUSTERS; do
    # Pattern filtering
    if [ -n "$PATTERN_FILTER" ]; then
        if ! [[ "$CLUSTER_NAME" == $PATTERN_FILTER ]]; then
            continue
        fi
    fi

    # Get cluster metadata
    CLUSTER_JSON=$(oc get hostedcluster "$CLUSTER_NAME" -n clusters -o json 2>/dev/null || echo "{}")

    # Check if protected
    PROTECTED=$(echo "$CLUSTER_JSON" | jq -r '.metadata.labels["kagenti.io/protected"] // "false"')
    if [ "$PROTECTED" = "true" ]; then
        if [ "$VERBOSE" = "true" ]; then
            log_success "PROTECTED: $CLUSTER_NAME"
            echo "       Protected clusters are never deleted"
            echo ""
        fi
        PROTECTED_COUNT=$((PROTECTED_COUNT + 1))
        continue
    fi

    # Get TTL and creation time
    TTL_HOURS=$(echo "$CLUSTER_JSON" | jq -r '.metadata.labels["kagenti.io/ttl-hours"] // "null"')
    CLUSTER_TYPE=$(echo "$CLUSTER_JSON" | jq -r '.metadata.labels["kagenti.io/cluster-type"] // "unknown"')
    CREATED_AT=$(echo "$CLUSTER_JSON" | jq -r '.metadata.creationTimestamp // "null"')

    # Validate TTL
    if [ "$TTL_HOURS" = "null" ] || ! [[ "$TTL_HOURS" =~ ^[0-9]+$ ]]; then
        log_warn "SKIP: $CLUSTER_NAME (invalid or missing TTL)"
        continue
    fi

    # Calculate age
    CREATED_EPOCH=$(date -d "$CREATED_AT" +%s 2>/dev/null || echo "0")
    if [ "$CREATED_EPOCH" -eq 0 ]; then
        log_warn "SKIP: $CLUSTER_NAME (invalid creation timestamp)"
        continue
    fi

    AGE_SECONDS=$((NOW_EPOCH - CREATED_EPOCH))
    AGE_HOURS=$((AGE_SECONDS / 3600))
    TTL_SECONDS=$((TTL_HOURS * 3600))

    # Format age display
    if [ "$AGE_HOURS" -lt 1 ]; then
        AGE_MINUTES=$((AGE_SECONDS / 60))
        AGE_DISPLAY="${AGE_MINUTES}m"
    else
        AGE_DISPLAY="${AGE_HOURS}h"
    fi

    # Check if stale
    if [ "$AGE_SECONDS" -gt "$TTL_SECONDS" ]; then
        OVER_SECONDS=$((AGE_SECONDS - TTL_SECONDS))
        OVER_HOURS=$((OVER_SECONDS / 3600))
        if [ "$OVER_HOURS" -lt 1 ]; then
            OVER_MINUTES=$((OVER_SECONDS / 60))
            OVER_DISPLAY="${OVER_MINUTES}m"
        else
            OVER_DISPLAY="${OVER_HOURS}h"
        fi

        log_warn "STALE: $CLUSTER_NAME"
        echo "       Age: $AGE_DISPLAY | TTL: ${TTL_HOURS}h | Over by: $OVER_DISPLAY"
        echo "       Type: $CLUSTER_TYPE | Created: $CREATED_AT"

        if [ "$DRY_RUN" = "true" ]; then
            echo "       Would delete (use --apply to execute)"
        else
            echo "       Deleting cluster..."
            # Use destroy-cluster.sh which handles ansible cleanup and stuck finalizers
            if "$SCRIPT_DIR/destroy-cluster.sh" "$CLUSTER_NAME" 2>&1 | tee "/tmp/cleanup-${CLUSTER_NAME}.log"; then
                log_success "Successfully deleted $CLUSTER_NAME"
                DELETED_COUNT=$((DELETED_COUNT + 1))
            else
                log_error "Failed to delete $CLUSTER_NAME (see /tmp/cleanup-${CLUSTER_NAME}.log)"
                FAILED_COUNT=$((FAILED_COUNT + 1))
            fi
        fi
        echo ""
        STALE_COUNT=$((STALE_COUNT + 1))
    else
        if [ "$VERBOSE" = "true" ]; then
            log_success "OK: $CLUSTER_NAME"
            echo "       Age: $AGE_DISPLAY | TTL: ${TTL_HOURS}h | Type: $CLUSTER_TYPE"
            echo ""
        fi
        OK_COUNT=$((OK_COUNT + 1))
    fi
done

# ============================================================================
# Summary
# ============================================================================

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "Summary:"
echo "  Total clusters: $CLUSTER_COUNT"
echo "  Stale clusters: $STALE_COUNT"
echo "  Protected clusters: $PROTECTED_COUNT"
echo "  Healthy clusters: $OK_COUNT"
echo ""

if [ "$DRY_RUN" = "true" ] && [ "$STALE_COUNT" -gt 0 ]; then
    echo "This was a DRY-RUN. No clusters were deleted."
    echo "To actually delete stale clusters, run with --apply flag."
    echo ""
elif [ "$DRY_RUN" = "false" ]; then
    if [ "$DELETED_COUNT" -gt 0 ]; then
        log_success "Successfully deleted $DELETED_COUNT cluster(s)"
    fi
    if [ "$FAILED_COUNT" -gt 0 ]; then
        log_error "Failed to delete $FAILED_COUNT cluster(s)"
    fi
    if [ "$STALE_COUNT" -eq 0 ]; then
        log_success "No stale clusters found"
    fi
else
    log_success "No stale clusters found"
fi
