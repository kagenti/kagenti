#!/usr/bin/env bash
#
# Tag Untagged Resources
#
# Tags AWS resources in CI-managed VPCs that weren't tagged by HyperShift.
# This includes resources like the main route table that AWS auto-creates.
#
# USAGE:
#   ./.github/scripts/hypershift/tag-untagged-resources.sh <cluster-name>
#   ./.github/scripts/hypershift/tag-untagged-resources.sh kagenti-hypershift-ci-local
#
# This script finds resources in VPCs tagged with our managed-by tag and
# ensures all child resources also have the tag.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"

# Colors
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m'

log_info() { echo -e "${BLUE}→${NC} $1"; }
log_success() { echo -e "${GREEN}✓${NC} $1"; }
log_warn() { echo -e "${YELLOW}⚠${NC} $1"; }

# Load credentials
if [ -f "$REPO_ROOT/.env.hypershift-ci" ]; then
    # shellcheck source=/dev/null
    source "$REPO_ROOT/.env.hypershift-ci"
fi

# Tag configuration
TAG_KEY="kagenti.io/managed-by"
TAG_VALUE="${MANAGED_BY_TAG:-kagenti-hypershift-ci}"

# Optional: filter by cluster name
CLUSTER_NAME="${1:-}"

echo ""
echo "╔════════════════════════════════════════════════════════════════╗"
echo "║           Tag Untagged AWS Resources                           ║"
echo "╚════════════════════════════════════════════════════════════════╝"
echo ""
echo "Tag: $TAG_KEY=$TAG_VALUE"
if [ -n "$CLUSTER_NAME" ]; then
    echo "Cluster filter: $CLUSTER_NAME"
fi
echo ""

# Find VPCs with our tag
log_info "Finding VPCs with tag $TAG_KEY=$TAG_VALUE..."
VPCS=$(aws ec2 describe-vpcs \
    --filters "Name=tag:$TAG_KEY,Values=$TAG_VALUE" \
    --query 'Vpcs[*].VpcId' \
    --output text 2>/dev/null || echo "")

if [ -z "$VPCS" ]; then
    log_warn "No VPCs found with tag $TAG_KEY=$TAG_VALUE"
    exit 0
fi

echo "Found VPCs: $VPCS"
echo ""

TAGGED_COUNT=0

# Function to tag a resource if it doesn't have our tag
tag_resource() {
    local resource_id="$1"
    local resource_type="$2"

    # Check if already tagged
    local has_tag
    has_tag=$(aws ec2 describe-tags \
        --filters "Name=resource-id,Values=$resource_id" "Name=key,Values=$TAG_KEY" \
        --query 'Tags[0].Value' \
        --output text 2>/dev/null || echo "None")

    if [ "$has_tag" = "None" ] || [ -z "$has_tag" ]; then
        log_info "Tagging $resource_type: $resource_id"
        aws ec2 create-tags \
            --resources "$resource_id" \
            --tags "Key=$TAG_KEY,Value=$TAG_VALUE" 2>/dev/null || {
            log_warn "Failed to tag $resource_id"
            return 1
        }
        TAGGED_COUNT=$((TAGGED_COUNT + 1))
    fi
}

# Process each VPC
for VPC_ID in $VPCS; do
    log_info "Processing VPC: $VPC_ID"

    # Tag route tables (main route table is often untagged)
    log_info "  Checking route tables..."
    ROUTE_TABLES=$(aws ec2 describe-route-tables \
        --filters "Name=vpc-id,Values=$VPC_ID" \
        --query 'RouteTables[*].RouteTableId' \
        --output text 2>/dev/null || echo "")

    for RT_ID in $ROUTE_TABLES; do
        tag_resource "$RT_ID" "RouteTable"
    done

    # Tag subnets
    log_info "  Checking subnets..."
    SUBNETS=$(aws ec2 describe-subnets \
        --filters "Name=vpc-id,Values=$VPC_ID" \
        --query 'Subnets[*].SubnetId' \
        --output text 2>/dev/null || echo "")

    for SUBNET_ID in $SUBNETS; do
        tag_resource "$SUBNET_ID" "Subnet"
    done

    # Tag internet gateways
    log_info "  Checking internet gateways..."
    IGWS=$(aws ec2 describe-internet-gateways \
        --filters "Name=attachment.vpc-id,Values=$VPC_ID" \
        --query 'InternetGateways[*].InternetGatewayId' \
        --output text 2>/dev/null || echo "")

    for IGW_ID in $IGWS; do
        tag_resource "$IGW_ID" "InternetGateway"
    done

    # Tag NAT gateways
    log_info "  Checking NAT gateways..."
    NAT_GWS=$(aws ec2 describe-nat-gateways \
        --filter "Name=vpc-id,Values=$VPC_ID" "Name=state,Values=available,pending" \
        --query 'NatGateways[*].NatGatewayId' \
        --output text 2>/dev/null || echo "")

    for NAT_ID in $NAT_GWS; do
        tag_resource "$NAT_ID" "NatGateway"
    done

    # Tag security groups (except default)
    log_info "  Checking security groups..."
    SGS=$(aws ec2 describe-security-groups \
        --filters "Name=vpc-id,Values=$VPC_ID" \
        --query 'SecurityGroups[?GroupName!=`default`].GroupId' \
        --output text 2>/dev/null || echo "")

    for SG_ID in $SGS; do
        tag_resource "$SG_ID" "SecurityGroup"
    done

    # Tag Elastic IPs associated with NAT gateways
    log_info "  Checking Elastic IPs..."
    for NAT_ID in $NAT_GWS; do
        EIP_ALLOC=$(aws ec2 describe-nat-gateways \
            --nat-gateway-ids "$NAT_ID" \
            --query 'NatGateways[0].NatGatewayAddresses[0].AllocationId' \
            --output text 2>/dev/null || echo "None")

        if [ "$EIP_ALLOC" != "None" ] && [ -n "$EIP_ALLOC" ]; then
            tag_resource "$EIP_ALLOC" "ElasticIP"
        fi
    done

    echo ""
done

if [ "$TAGGED_COUNT" -gt 0 ]; then
    log_success "Tagged $TAGGED_COUNT previously untagged resource(s)"
else
    log_success "All resources already have the $TAG_KEY tag"
fi
