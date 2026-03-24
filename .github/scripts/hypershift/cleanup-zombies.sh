#!/usr/bin/env bash
#
# Cleanup Zombie HyperShift Resources
#
# This script identifies and destroys zombie HyperShift clusters and AWS resources
# that are blocking CI runs due to quota exhaustion.
#
# Zombie detection criteria:
#   1. HostedClusters older than 6 hours (normal E2E run < 2 hours)
#   2. HostedClusters with deletionTimestamp but still exist (stuck finalizers)
#   3. HostedClusters without matching CI slot leases (orphaned from failed jobs)
#   4. VPCs without matching HostedClusters (orphaned AWS resources)
#   5. VPC endpoints consuming quota without active clusters
#
# USAGE:
#   # Dry run (default - shows what would be cleaned)
#   ./.github/scripts/hypershift/cleanup-zombies.sh
#
#   # Force cleanup (actually deletes resources)
#   ./.github/scripts/hypershift/cleanup-zombies.sh --force
#
#   # Cleanup specific cluster
#   ./.github/scripts/hypershift/cleanup-zombies.sh --cluster <cluster-name> --force
#
# EXAMPLES:
#   source .env.kagenti-hypershift-custom
#   ./.github/scripts/hypershift/cleanup-zombies.sh --force
#

set -euo pipefail

# ============================================================================
# Configuration
# ============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"

# Zombie thresholds
MAX_CLUSTER_AGE_HOURS=${MAX_CLUSTER_AGE_HOURS:-6}  # Clusters older than 6h are zombies
NAMESPACE="clusters"
MANAGED_BY_TAG="${MANAGED_BY_TAG:-kagenti-hypershift-custom}"
LEASE_PREFIX="kagenti-ci-slot"

# Mode
FORCE=false
SPECIFIC_CLUSTER=""
DRY_RUN=true

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

# Counters
ZOMBIE_COUNT=0
CLEANED_COUNT=0
FAILED_COUNT=0

# ============================================================================
# Argument Parsing
# ============================================================================

while [[ $# -gt 0 ]]; do
    case $1 in
        --force)
            FORCE=true
            DRY_RUN=false
            shift
            ;;
        --cluster)
            SPECIFIC_CLUSTER="$2"
            shift 2
            ;;
        --max-age-hours)
            MAX_CLUSTER_AGE_HOURS="$2"
            shift 2
            ;;
        -h|--help)
            sed -n '2,/^$/p' "$0" | sed 's/^# \?//'
            exit 0
            ;;
        *)
            echo "Unknown option: $1" >&2
            echo "Run with --help for usage" >&2
            exit 1
            ;;
    esac
done

# ============================================================================
# Helper Functions
# ============================================================================

log_header() { echo -e "\n${BLUE}═══════════════════════════════════════════════════════════════${NC}"; echo -e "${BLUE}$1${NC}"; echo -e "${BLUE}═══════════════════════════════════════════════════════════════${NC}"; }
log_section() { echo -e "\n${YELLOW}>>> $1${NC}"; }
log_info() { echo -e "${CYAN}[INFO]${NC} $1"; }
log_success() { echo -e "${GREEN}[OK]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }
log_zombie() { echo -e "${RED}[ZOMBIE]${NC} $1"; ((ZOMBIE_COUNT++)) || true; }

# Parse ISO timestamp to epoch
parse_iso_date() {
    local iso_date="$1"
    date -d "$iso_date" +%s 2>/dev/null || date -j -f "%Y-%m-%dT%H:%M:%SZ" "$iso_date" +%s 2>/dev/null || echo "0"
}

# Calculate age in hours
get_age_hours() {
    local created="$1"
    local now_epoch=$(date +%s)
    local created_epoch=$(parse_iso_date "$created")
    if [ "$created_epoch" -eq 0 ]; then
        echo "unknown"
        return
    fi
    local age_seconds=$((now_epoch - created_epoch))
    echo $((age_seconds / 3600))
}

# Check if cleanup should run on this cluster
should_cleanup_cluster() {
    local cluster_name="$1"
    local created="$2"
    local deletion_ts="$3"
    local holder="$4"

    local age_hours=$(get_age_hours "$created")

    # Skip if specific cluster requested and this isn't it
    if [ -n "$SPECIFIC_CLUSTER" ] && [ "$cluster_name" != "$SPECIFIC_CLUSTER" ]; then
        return 1
    fi

    # Zombie check 1: Has deletionTimestamp but still exists (stuck finalizer)
    if [ -n "$deletion_ts" ]; then
        log_zombie "$cluster_name - Stuck with deletionTimestamp since $(get_age_hours "$deletion_ts")h ago"
        return 0
    fi

    # Zombie check 2: Older than max age
    if [ "$age_hours" != "unknown" ] && [ "$age_hours" -gt "$MAX_CLUSTER_AGE_HOURS" ]; then
        log_zombie "$cluster_name - Age: ${age_hours}h (max: ${MAX_CLUSTER_AGE_HOURS}h)"
        return 0
    fi

    # Zombie check 3: No matching lease (orphaned from failed job)
    if [ -z "$holder" ]; then
        if [ "$age_hours" != "unknown" ] && [ "$age_hours" -gt 1 ]; then  # Allow 1h grace period for new clusters
            log_zombie "$cluster_name - No matching CI slot lease (orphaned)"
            return 0
        fi
    fi

    return 1
}

# Destroy a zombie cluster
destroy_zombie_cluster() {
    local cluster_name="$1"

    log_info "Destroying zombie cluster: $cluster_name"

    if [ "$DRY_RUN" = true ]; then
        log_info "[DRY RUN] Would destroy: $cluster_name"
        return 0
    fi

    # Extract cluster suffix for 55-cleanup script
    local cluster_suffix="${cluster_name#${MANAGED_BY_TAG}-}"

    # Use the improved cleanup script with all resource cleanup
    export CLUSTER_SUFFIX="$cluster_suffix"
    if "$SCRIPT_DIR/ci/55-cleanup-existing-cluster.sh"; then
        log_success "Destroyed: $cluster_name"
        ((CLEANED_COUNT++))
        return 0
    else
        log_error "Failed to destroy: $cluster_name"
        ((FAILED_COUNT++))
        return 1
    fi
}

# Force remove finalizers from stuck cluster
force_remove_finalizers() {
    local cluster_name="$1"

    log_warn "Force removing finalizers from: $cluster_name"

    if [ "$DRY_RUN" = true ]; then
        log_info "[DRY RUN] Would remove finalizers from: $cluster_name"
        return 0
    fi

    # Check if AWS resources are already cleaned up
    if "$SCRIPT_DIR/debug-aws-hypershift.sh" --check "$cluster_name"; then
        log_success "AWS resources already cleaned for: $cluster_name"

        # Safe to remove finalizer
        if oc patch hostedcluster -n clusters "$cluster_name" \
            -p '{"metadata":{"finalizers":null}}' --type=merge 2>/dev/null; then
            log_success "Removed finalizers from: $cluster_name"

            # Wait for deletion
            for _ in {1..30}; do
                if ! oc get hostedcluster -n clusters "$cluster_name" &>/dev/null; then
                    log_success "HostedCluster deleted: $cluster_name"
                    ((CLEANED_COUNT++))
                    return 0
                fi
                sleep 2
            done
            log_warn "HostedCluster still exists after finalizer removal: $cluster_name"
        else
            log_error "Failed to remove finalizers from: $cluster_name"
            ((FAILED_COUNT++))
            return 1
        fi
    else
        log_error "AWS resources still exist for: $cluster_name - cannot safely remove finalizer"
        log_info "Run: ./.github/scripts/hypershift/debug-aws-hypershift.sh $cluster_name"
        ((FAILED_COUNT++))
        return 1
    fi
}

# Cleanup orphaned VPCs (VPCs without HostedClusters)
cleanup_orphaned_vpcs() {
    log_section "Checking for orphaned VPCs"

    # Get all VPCs tagged with our prefix
    local vpcs=$(aws ec2 describe-vpcs \
        --region "${AWS_REGION:-us-east-1}" \
        --filters "Name=tag-key,Values=kubernetes.io/cluster/${MANAGED_BY_TAG}-*" \
        --query 'Vpcs[*].[VpcId,Tags[?Key==`Name`].Value|[0]]' \
        --output text 2>/dev/null || echo "")

    if [ -z "$vpcs" ]; then
        log_info "No VPCs found with tag prefix: kubernetes.io/cluster/${MANAGED_BY_TAG}-*"
        return 0
    fi

    # Get all active HostedClusters
    local active_clusters=$(oc get hostedclusters -n clusters \
        -o jsonpath='{range .items[?(@.metadata.name)]}{.metadata.name}{"\n"}{end}' 2>/dev/null || echo "")

    echo "$vpcs" | while read -r vpc_id vpc_name; do
        [ -z "$vpc_id" ] && continue

        # Extract cluster name from VPC name (format: <cluster-name>-vpc)
        local cluster_name="${vpc_name%-vpc}"

        # Check if HostedCluster exists
        if ! echo "$active_clusters" | grep -q "^${cluster_name}$"; then
            log_zombie "Orphaned VPC: $vpc_id ($vpc_name) - cluster '$cluster_name' doesn't exist"

            if [ "$DRY_RUN" = true ]; then
                log_info "[DRY RUN] Would cleanup VPC: $vpc_id"
            else
                # Use the improved cleanup script to clean all AWS resources
                log_info "Cleaning up orphaned VPC and all resources: $vpc_id ($cluster_name)"

                # Extract cluster suffix
                local cluster_suffix="${cluster_name#${MANAGED_BY_TAG}-}"

                # Use improved 55-cleanup script that handles VPC + all other resources
                export CLUSTER_SUFFIX="$cluster_suffix"
                if "$SCRIPT_DIR/ci/55-cleanup-existing-cluster.sh" 2>&1 | grep -v "TASK\|PLAY\|ok:"; then
                    log_success "Cleaned up all resources for: $cluster_name"
                    ((CLEANED_COUNT++))
                else
                    log_error "Failed to cleanup resources for: $cluster_name"
                    ((FAILED_COUNT++))
                fi
            fi
        fi
    done
}

# ============================================================================
# Main
# ============================================================================

log_header "HyperShift Zombie Cleanup"

echo ""
echo "Configuration:"
echo "  Managed By Tag: $MANAGED_BY_TAG"
echo "  Max Age:        ${MAX_CLUSTER_AGE_HOURS}h"
echo "  Mode:           $([ "$DRY_RUN" = true ] && echo 'DRY RUN (use --force to cleanup)' || echo 'FORCE - WILL DELETE RESOURCES')"
echo "  Specific:       ${SPECIFIC_CLUSTER:-all clusters}"
echo ""

# Verify prerequisites
if [ -z "${AWS_ACCESS_KEY_ID:-}" ] || [ -z "${AWS_SECRET_ACCESS_KEY:-}" ]; then
    log_error "AWS credentials not set. Run: source .env.kagenti-hypershift-custom"
    exit 1
fi

if [ -z "${KUBECONFIG:-}" ] || [ ! -f "${KUBECONFIG}" ]; then
    log_error "KUBECONFIG not set or file not found"
    exit 1
fi

if ! command -v oc &>/dev/null; then
    log_error "oc CLI not found"
    exit 1
fi

# Check AWS credentials
log_section "Verifying AWS Credentials"
if ! aws sts get-caller-identity --output text &>/dev/null; then
    log_error "AWS credentials invalid or expired"
    exit 1
fi
log_success "AWS credentials valid"

# Check management cluster access
log_section "Verifying Management Cluster Access"
if ! oc get ns "$NAMESPACE" &>/dev/null; then
    log_error "Cannot access namespace '$NAMESPACE' on management cluster"
    exit 1
fi
log_success "Management cluster access verified"

# ============================================================================
# Find Zombie HostedClusters
# ============================================================================

log_section "Scanning for Zombie HostedClusters"

# Get all HostedClusters
clusters_json=$(oc get hostedclusters -n clusters \
    -o jsonpath='{range .items[*]}{.metadata.name}{"|"}{.metadata.creationTimestamp}{"|"}{.metadata.deletionTimestamp}{"\n"}{end}' 2>/dev/null || echo "")

if [ -z "$clusters_json" ]; then
    log_info "No HostedClusters found"
else
    # Get all CI slot leases to check for orphans
    leases=$(oc get leases -n clusters -l app=kagenti-ci \
        -o jsonpath='{range .items[*]}{.spec.holderIdentity}{"\n"}{end}' 2>/dev/null || echo "")

    while IFS='|' read -r cluster_name created deletion_ts; do
        [ -z "$cluster_name" ] && continue

        # Check if cluster has a matching lease
        cluster_suffix="${cluster_name#${MANAGED_BY_TAG}-}"
        holder=""
        if echo "$leases" | grep -q "^${cluster_suffix}:"; then
            holder="has-lease"
        fi

        # Check if this is a zombie
        if should_cleanup_cluster "$cluster_name" "$created" "$deletion_ts" "$holder"; then
            # Destroy the zombie (continue on error to process all zombies)
            if [ -n "$deletion_ts" ]; then
                # Already marked for deletion - force remove finalizers
                force_remove_finalizers "$cluster_name" || true
            else
                # Not yet deleted - initiate destroy
                destroy_zombie_cluster "$cluster_name" || true
            fi
        else
            log_success "$cluster_name - Active (age: $(get_age_hours "$created")h)"
        fi
    done <<< "$clusters_json"
fi

# ============================================================================
# Find Orphaned VPCs
# ============================================================================

cleanup_orphaned_vpcs

# ============================================================================
# Find Orphaned OIDC Providers
# ============================================================================

cleanup_orphaned_oidc() {
    log_section "Checking for orphaned OIDC providers"

    # Get all OIDC providers
    local oidc_providers=$(aws iam list-open-id-connect-providers \
        --query "OpenIDConnectProviderList[?contains(Arn, '${MANAGED_BY_TAG}')].Arn" \
        --output text 2>/dev/null || echo "")

    if [ -z "$oidc_providers" ]; then
        log_info "No OIDC providers found with prefix: ${MANAGED_BY_TAG}"
        return 0
    fi

    # Get all active HostedClusters
    local active_clusters=$(oc get hostedclusters -n clusters \
        -o jsonpath='{range .items[?(@.metadata.name)]}{.metadata.name}{"\n"}{end}' 2>/dev/null || echo "")

    local oidc_count=0
    for oidc_arn in $oidc_providers; do
        # Extract cluster name from OIDC ARN
        local cluster_name=$(echo "$oidc_arn" | grep -oP "${MANAGED_BY_TAG}[^/]*" | head -1)

        # Check if HostedCluster exists
        if ! echo "$active_clusters" | grep -q "^${cluster_name}$"; then
            log_zombie "Orphaned OIDC provider: $oidc_arn"
            ((oidc_count++)) || true

            if [ "$DRY_RUN" = false ]; then
                if aws iam delete-open-id-connect-provider --open-id-connect-provider-arn "$oidc_arn" 2>/dev/null; then
                    log_success "Deleted OIDC provider: $oidc_arn"
                    ((CLEANED_COUNT++))
                else
                    log_error "Failed to delete OIDC provider: $oidc_arn"
                    ((FAILED_COUNT++))
                fi
            fi
        fi
    done

    if [ "$oidc_count" -eq 0 ]; then
        log_info "No orphaned OIDC providers found"
    else
        log_warn "Found $oidc_count orphaned OIDC provider(s)"
    fi
}

# ============================================================================
# Find Orphaned Elastic IPs
# ============================================================================

cleanup_orphaned_eips() {
    log_section "Checking for orphaned Elastic IPs"

    # Get all Elastic IPs tagged with our prefix
    # We get AllocationId, PublicIp, and all tag keys, then filter in bash
    local eip_data=$(aws ec2 describe-addresses \
        --region "${AWS_REGION:-us-east-1}" \
        --filters "Name=tag-key,Values=kubernetes.io/cluster/${MANAGED_BY_TAG}-*" \
        --query 'Addresses[*].[AllocationId,PublicIp,Tags[*].Key|join(`,`, @)]' \
        --output text 2>/dev/null || echo "")

    if [ -z "$eip_data" ]; then
        log_info "No Elastic IPs found with tag prefix: kubernetes.io/cluster/${MANAGED_BY_TAG}-*"
        return 0
    fi

    # Get all active HostedClusters
    local active_clusters=$(oc get hostedclusters -n clusters \
        -o jsonpath='{range .items[?(@.metadata.name)]}{.metadata.name}{"\n"}{end}' 2>/dev/null || echo "")

    local eip_count=0
    while IFS=$'\t' read -r alloc_id public_ip tag_keys; do
        [ -z "$alloc_id" ] && continue

        # Extract cluster name from tags
        local cluster_name=""
        for tag in $(echo "$tag_keys" | tr ',' '\n'); do
            if [[ "$tag" == "kubernetes.io/cluster/${MANAGED_BY_TAG}-"* ]]; then
                cluster_name=$(echo "$tag" | sed "s|kubernetes.io/cluster/||")
                break
            fi
        done

        if [ -z "$cluster_name" ]; then
            log_warn "Could not extract cluster name from EIP $alloc_id tags"
            continue
        fi

        # Check if HostedCluster exists
        if ! echo "$active_clusters" | grep -q "^${cluster_name}$"; then
            log_zombie "Orphaned Elastic IP: $alloc_id ($public_ip) - cluster: $cluster_name"
            ((eip_count++)) || true

            if [ "$DRY_RUN" = false ]; then
                if aws ec2 release-address --region "${AWS_REGION:-us-east-1}" --allocation-id "$alloc_id" 2>/dev/null; then
                    log_success "Released Elastic IP: $alloc_id"
                    ((CLEANED_COUNT++))
                else
                    log_error "Failed to release Elastic IP: $alloc_id"
                    ((FAILED_COUNT++))
                fi
            fi
        fi
    done <<< "$eip_data"

    if [ "$eip_count" -eq 0 ]; then
        log_info "No orphaned Elastic IPs found"
    else
        log_warn "Found $eip_count orphaned Elastic IP(s)"
    fi
}

# ============================================================================
# Find Orphaned Route53 Zones
# ============================================================================

cleanup_orphaned_route53() {
    log_section "Checking for orphaned Route53 hosted zones"

    # Get all hosted zones matching our prefix
    local zones=$(aws route53 list-hosted-zones \
        --query "HostedZones[?contains(Name, '${MANAGED_BY_TAG}')].Id" \
        --output text 2>/dev/null || echo "")

    if [ -z "$zones" ]; then
        log_info "No Route53 zones found with prefix: ${MANAGED_BY_TAG}"
        return 0
    fi

    # Get all active HostedClusters
    local active_clusters=$(oc get hostedclusters -n clusters \
        -o jsonpath='{range .items[?(@.metadata.name)]}{.metadata.name}{"\n"}{end}' 2>/dev/null || echo "")

    local zone_count=0
    for zone_id in $zones; do
        # Extract zone ID (remove /hostedzone/ prefix)
        local zone_id_clean="${zone_id##*/}"

        # Get zone name
        local zone_name=$(aws route53 get-hosted-zone --id "$zone_id_clean" \
            --query 'HostedZone.Name' --output text 2>/dev/null || echo "")

        # Extract cluster name from zone name
        local cluster_name=$(echo "$zone_name" | sed -E "s/\.hypershift\.local\.$//; s/\..*//")

        # Check if HostedCluster exists
        if ! echo "$active_clusters" | grep -q "^${cluster_name}$"; then
            log_zombie "Orphaned Route53 zone: $zone_id_clean ($zone_name)"
            ((zone_count++)) || true

            if [ "$DRY_RUN" = false ]; then
                log_info "Deleting Route53 zone: $zone_id_clean"

                # Delete all record sets except NS and SOA
                local record_sets=$(aws route53 list-resource-record-sets \
                    --hosted-zone-id "$zone_id_clean" \
                    --query "ResourceRecordSets[?Type != 'NS' && Type != 'SOA'].[Name,Type]" \
                    --output text 2>/dev/null || echo "")

                if [ -n "$record_sets" ]; then
                    echo "$record_sets" | while IFS=$'\t' read -r name type; do
                        [ -z "$name" ] && continue
                        local change_batch=$(aws route53 list-resource-record-sets \
                            --hosted-zone-id "$zone_id_clean" \
                            --query "ResourceRecordSets[?Name=='${name}' && Type=='${type}']" \
                            --output json 2>/dev/null)
                        if [ -n "$change_batch" ] && [ "$change_batch" != "[]" ]; then
                            aws route53 change-resource-record-sets \
                                --hosted-zone-id "$zone_id_clean" \
                                --change-batch "{\"Changes\":[{\"Action\":\"DELETE\",\"ResourceRecordSet\":$(echo "$change_batch" | jq '.[0]')}]}" \
                                2>&1 >/dev/null || true
                        fi
                    done
                fi

                # Delete the hosted zone
                if aws route53 delete-hosted-zone --id "$zone_id_clean" 2>/dev/null; then
                    log_success "Deleted Route53 zone: $zone_id_clean"
                    ((CLEANED_COUNT++))
                else
                    log_error "Failed to delete Route53 zone: $zone_id_clean"
                    ((FAILED_COUNT++))
                fi
            fi
        fi
    done

    if [ "$zone_count" -eq 0 ]; then
        log_info "No orphaned Route53 zones found"
    else
        log_warn "Found $zone_count orphaned Route53 zone(s)"
    fi
}

# Call all orphan cleanup functions
# NOTE: IAM role cleanup is intentionally NOT included because HCP manages IAM roles
cleanup_orphaned_oidc
cleanup_orphaned_eips
cleanup_orphaned_route53

# ============================================================================
# Check VPC Endpoint Quota
# ============================================================================

log_section "VPC Endpoint Quota Check"

vpc_endpoint_count=$(aws ec2 describe-vpc-endpoints \
    --region "${AWS_REGION:-us-east-1}" \
    --query 'VpcEndpoints[*].VpcEndpointId' \
    --output text 2>/dev/null | wc -w || echo "0")

vpc_endpoint_quota=$(aws service-quotas get-service-quota \
    --service-code vpc \
    --quota-code L-29B6F2EB \
    --region "${AWS_REGION:-us-east-1}" \
    --query 'Quota.Value' \
    --output text 2>/dev/null || echo "50")

vpc_endpoint_percent=$((vpc_endpoint_count * 100 / ${vpc_endpoint_quota%.*}))

echo "VPC Endpoints: $vpc_endpoint_count / ${vpc_endpoint_quota%.*} (${vpc_endpoint_percent}%)"

if [ "$vpc_endpoint_percent" -gt 80 ]; then
    log_warn "VPC endpoint quota usage above 80% - cleanup recommended"
elif [ "$vpc_endpoint_percent" -gt 90 ]; then
    log_error "VPC endpoint quota usage above 90% - cleanup CRITICAL"
fi

# ============================================================================
# Summary
# ============================================================================

log_header "Cleanup Summary"

echo ""
echo "Zombies Found:   $ZOMBIE_COUNT"
echo "Cleaned:         $CLEANED_COUNT"
echo "Failed:          $FAILED_COUNT"
echo "Mode:            $([ "$DRY_RUN" = true ] && echo 'DRY RUN' || echo 'FORCE')"
echo ""

if [ "$DRY_RUN" = true ] && [ "$ZOMBIE_COUNT" -gt 0 ]; then
    echo -e "${YELLOW}This was a dry run. To actually cleanup zombies, run:${NC}"
    echo -e "${YELLOW}  $0 --force${NC}"
    echo ""
fi

if [ "$FAILED_COUNT" -gt 0 ]; then
    log_error "Some cleanups failed. Check logs above for details."
    exit 1
fi

if [ "$ZOMBIE_COUNT" -eq 0 ]; then
    log_success "No zombie resources found!"
else
    if [ "$DRY_RUN" = false ]; then
        log_success "Zombie cleanup complete!"
    fi
fi

exit 0
