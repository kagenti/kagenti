#!/usr/bin/env bash
#
# Find Orphaned AWS Resources
#
# Searches for AWS resources matching a prefix (default: kagenti-hypershift).
# Useful for identifying orphaned resources from failed cluster creations.
#
# USAGE:
#   ./.github/scripts/hypershift/find-orphaned-resources.sh [OPTIONS] [prefix]
#
# OPTIONS:
#   --region REGION    AWS region (default: from env or us-east-1)
#   --no-color         Disable colored output
#   --summary-only     Only show summary, not individual resources
#   -h, --help         Show this help
#
# EXAMPLES:
#   ./find-orphaned-resources.sh                           # Search for kagenti-hypershift*
#   ./find-orphaned-resources.sh kagenti-hypershift-custom # More specific prefix
#   ./find-orphaned-resources.sh --summary-only            # Just show counts
#

set -euo pipefail

# ============================================================================
# Configuration
# ============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"

# Default values
PREFIX="kagenti-hypershift"
REGION="${AWS_REGION:-us-east-1}"
NO_COLOR=false
SUMMARY_ONLY=false

# Colors
if [[ -t 1 ]]; then
    RED='\033[0;31m'
    GREEN='\033[0;32m'
    YELLOW='\033[1;33m'
    BLUE='\033[0;34m'
    CYAN='\033[0;36m'
    BOLD='\033[1m'
    DIM='\033[2m'
    NC='\033[0m'
else
    RED='' GREEN='' YELLOW='' BLUE='' CYAN='' BOLD='' DIM='' NC=''
fi

# ============================================================================
# Parse Arguments
# ============================================================================

while [[ $# -gt 0 ]]; do
    case $1 in
        --region)
            REGION="$2"
            shift 2
            ;;
        --no-color)
            NO_COLOR=true
            RED='' GREEN='' YELLOW='' BLUE='' CYAN='' BOLD='' DIM='' NC=''
            shift
            ;;
        --summary-only)
            SUMMARY_ONLY=true
            shift
            ;;
        -h|--help)
            head -30 "$0" | tail -25
            exit 0
            ;;
        -*)
            echo "Unknown option: $1" >&2
            exit 1
            ;;
        *)
            PREFIX="$1"
            shift
            ;;
    esac
done

# ============================================================================
# Helper Functions
# ============================================================================

log_header() {
    echo ""
    echo -e "${BLUE}═══════════════════════════════════════════════════════════════${NC}"
    echo -e "${BLUE}$1${NC}"
    echo -e "${BLUE}═══════════════════════════════════════════════════════════════${NC}"
}

log_section() {
    echo ""
    echo -e "${CYAN}───────────────────────────────────────────────────────────────${NC}"
    echo -e "${BOLD}$1${NC}"
    echo -e "${CYAN}───────────────────────────────────────────────────────────────${NC}"
}

log_resource_type() {
    echo ""
    echo -e "  ${YELLOW}$1:${NC}"
}

log_resource() {
    echo -e "    ${DIM}$1${NC}"
}

log_none() {
    echo -e "    ${DIM}(none)${NC}"
}

# ============================================================================
# Resource Discovery Functions
# ============================================================================

# Associative arrays for tracking
declare -A VPC_NAMES
declare -A VPC_CLUSTERS
declare -A CLUSTER_RESOURCES
declare -a ORPHANED_RESOURCES

# Counters
declare -A RESOURCE_COUNTS

# Find VPCs by name prefix
find_vpcs() {
    aws ec2 describe-vpcs \
        --region "$REGION" \
        --filters "Name=tag:Name,Values=*${PREFIX}*" \
        --query 'Vpcs[*].[VpcId,State,CidrBlock,Tags[?Key==`Name`].Value|[0],Tags[?Key==`kubernetes.io/cluster`]|[0].Key]' \
        --output text 2>/dev/null || echo ""
}

# Find EC2 instances by name or cluster tag
find_instances() {
    local vpc_id="${1:-}"
    local filters="Name=tag:Name,Values=*${PREFIX}*"
    if [[ -n "$vpc_id" ]]; then
        filters="Name=vpc-id,Values=$vpc_id"
    fi
    aws ec2 describe-instances \
        --region "$REGION" \
        --filters "$filters" "Name=instance-state-name,Values=pending,running,stopping,stopped,shutting-down" \
        --query 'Reservations[*].Instances[*].[InstanceId,State.Name,InstanceType,Tags[?Key==`Name`].Value|[0]]' \
        --output text 2>/dev/null || echo ""
}

# Find NAT Gateways
find_nat_gateways() {
    local vpc_id="${1:-}"
    if [[ -n "$vpc_id" ]]; then
        aws ec2 describe-nat-gateways \
            --region "$REGION" \
            --filter "Name=vpc-id,Values=$vpc_id" "Name=state,Values=pending,available,deleting,failed" \
            --query 'NatGateways[*].[NatGatewayId,State,SubnetId]' \
            --output text 2>/dev/null || echo ""
    else
        aws ec2 describe-nat-gateways \
            --region "$REGION" \
            --filter "Name=tag:Name,Values=*${PREFIX}*" "Name=state,Values=pending,available,deleting,failed" \
            --query 'NatGateways[*].[NatGatewayId,State,VpcId]' \
            --output text 2>/dev/null || echo ""
    fi
}

# Find Internet Gateways
find_internet_gateways() {
    local vpc_id="${1:-}"
    if [[ -n "$vpc_id" ]]; then
        aws ec2 describe-internet-gateways \
            --region "$REGION" \
            --filters "Name=attachment.vpc-id,Values=$vpc_id" \
            --query 'InternetGateways[*].[InternetGatewayId,Attachments[0].State,Tags[?Key==`Name`].Value|[0]]' \
            --output text 2>/dev/null || echo ""
    else
        aws ec2 describe-internet-gateways \
            --region "$REGION" \
            --filters "Name=tag:Name,Values=*${PREFIX}*" \
            --query 'InternetGateways[*].[InternetGatewayId,Attachments[0].State,Attachments[0].VpcId]' \
            --output text 2>/dev/null || echo ""
    fi
}

# Find VPC Endpoints
find_vpc_endpoints() {
    local vpc_id="${1:-}"
    if [[ -n "$vpc_id" ]]; then
        aws ec2 describe-vpc-endpoints \
            --region "$REGION" \
            --filters "Name=vpc-id,Values=$vpc_id" \
            --query 'VpcEndpoints[*].[VpcEndpointId,State,ServiceName]' \
            --output text 2>/dev/null || echo ""
    fi
}

# Find Network Interfaces
find_enis() {
    local vpc_id="${1:-}"
    if [[ -n "$vpc_id" ]]; then
        aws ec2 describe-network-interfaces \
            --region "$REGION" \
            --filters "Name=vpc-id,Values=$vpc_id" \
            --query 'NetworkInterfaces[*].[NetworkInterfaceId,Status,Description]' \
            --output text 2>/dev/null || echo ""
    fi
}

# Find Security Groups
find_security_groups() {
    local vpc_id="${1:-}"
    if [[ -n "$vpc_id" ]]; then
        aws ec2 describe-security-groups \
            --region "$REGION" \
            --filters "Name=vpc-id,Values=$vpc_id" \
            --query 'SecurityGroups[?GroupName!=`default`].[GroupId,GroupName]' \
            --output text 2>/dev/null || echo ""
    else
        aws ec2 describe-security-groups \
            --region "$REGION" \
            --filters "Name=tag:Name,Values=*${PREFIX}*" \
            --query 'SecurityGroups[*].[GroupId,GroupName,VpcId]' \
            --output text 2>/dev/null || echo ""
    fi
}

# Find Subnets
find_subnets() {
    local vpc_id="${1:-}"
    if [[ -n "$vpc_id" ]]; then
        aws ec2 describe-subnets \
            --region "$REGION" \
            --filters "Name=vpc-id,Values=$vpc_id" \
            --query 'Subnets[*].[SubnetId,State,CidrBlock,AvailabilityZone]' \
            --output text 2>/dev/null || echo ""
    fi
}

# Find Route Tables
find_route_tables() {
    local vpc_id="${1:-}"
    if [[ -n "$vpc_id" ]]; then
        aws ec2 describe-route-tables \
            --region "$REGION" \
            --filters "Name=vpc-id,Values=$vpc_id" \
            --query 'RouteTables[?!Associations[?Main==`true`]].[RouteTableId,Tags[?Key==`Name`].Value|[0]]' \
            --output text 2>/dev/null || echo ""
    fi
}

# Find Elastic IPs
find_eips() {
    aws ec2 describe-addresses \
        --region "$REGION" \
        --filters "Name=tag:Name,Values=*${PREFIX}*" \
        --query 'Addresses[*].[AllocationId,PublicIp,AssociationId,Tags[?Key==`Name`].Value|[0]]' \
        --output text 2>/dev/null || echo ""
}

# Find EBS Volumes
find_volumes() {
    aws ec2 describe-volumes \
        --region "$REGION" \
        --filters "Name=tag:Name,Values=*${PREFIX}*" "Name=status,Values=available,in-use,creating" \
        --query 'Volumes[*].[VolumeId,State,Size,Tags[?Key==`Name`].Value|[0]]' \
        --output text 2>/dev/null || echo ""
}

# Find Classic Load Balancers
find_classic_elbs() {
    aws elb describe-load-balancers \
        --region "$REGION" \
        --query "LoadBalancerDescriptions[?contains(LoadBalancerName, '${PREFIX}')].[LoadBalancerName,Scheme,VPCId]" \
        --output text 2>/dev/null || echo ""
}

# Find ALB/NLB Load Balancers
find_elbv2() {
    aws elbv2 describe-load-balancers \
        --region "$REGION" \
        --query "LoadBalancers[?contains(LoadBalancerName, '${PREFIX}')].[LoadBalancerName,Type,State.Code,VpcId]" \
        --output text 2>/dev/null || echo ""
}

# Find S3 Buckets
find_s3_buckets() {
    aws s3api list-buckets \
        --query "Buckets[?contains(Name, '${PREFIX}')].Name" \
        --output text 2>/dev/null || echo ""
}

# Find IAM Roles
find_iam_roles() {
    aws iam list-roles \
        --query "Roles[?contains(RoleName, '${PREFIX}')].RoleName" \
        --output text 2>/dev/null || echo ""
}

# Find Instance Profiles
find_instance_profiles() {
    aws iam list-instance-profiles \
        --query "InstanceProfiles[?contains(InstanceProfileName, '${PREFIX}')].InstanceProfileName" \
        --output text 2>/dev/null || echo ""
}

# Find OIDC Providers
find_oidc_providers() {
    aws iam list-open-id-connect-providers \
        --query 'OpenIDConnectProviderList[*].Arn' \
        --output text 2>/dev/null | tr '\t' '\n' | grep "$PREFIX" || echo ""
}

# Find Route53 Hosted Zones
find_route53_zones() {
    aws route53 list-hosted-zones \
        --query "HostedZones[?contains(Name, '${PREFIX}')].[Name,Id,Config.PrivateZone]" \
        --output text 2>/dev/null || echo ""
}

# ============================================================================
# Main Logic
# ============================================================================

log_header "Find Orphaned AWS Resources"

echo ""
echo "Region:        $REGION"
echo "Search Prefix: $PREFIX"

# Verify AWS credentials
echo ""
echo -n "Verifying AWS credentials... "
if aws sts get-caller-identity --output text &>/dev/null; then
    echo -e "${GREEN}OK${NC}"
else
    echo -e "${RED}FAILED${NC}"
    echo "Error: AWS credentials not configured or invalid" >&2
    exit 1
fi

# ============================================================================
# Phase 1: Find VPCs (primary grouping)
# ============================================================================

echo ""
echo "Searching for resources..."

VPCS=$(find_vpcs)
VPC_COUNT=0

if [[ -n "$VPCS" ]]; then
    while IFS=$'\t' read -r vpc_id state cidr name cluster_tag; do
        if [[ -n "$vpc_id" && "$vpc_id" != "None" ]]; then
            VPC_NAMES["$vpc_id"]="$name"
            VPC_COUNT=$((VPC_COUNT + 1))

            # Extract cluster name from tag if present
            if [[ -n "$cluster_tag" && "$cluster_tag" != "None" ]]; then
                cluster_name="${cluster_tag#kubernetes.io/cluster/}"
                VPC_CLUSTERS["$vpc_id"]="$cluster_name"
            fi
        fi
    done <<< "$VPCS"
fi

RESOURCE_COUNTS["VPCs"]=$VPC_COUNT

# ============================================================================
# Phase 2: For each VPC, find associated resources
# ============================================================================

if [[ $SUMMARY_ONLY == false ]]; then
    for vpc_id in "${!VPC_NAMES[@]}"; do
        vpc_name="${VPC_NAMES[$vpc_id]}"
        cluster="${VPC_CLUSTERS[$vpc_id]:-unknown}"

        log_section "VPC: $vpc_id ($vpc_name)"
        if [[ -n "${VPC_CLUSTERS[$vpc_id]:-}" ]]; then
            echo -e "Cluster: ${CYAN}${VPC_CLUSTERS[$vpc_id]}${NC}"
        fi

        # EC2 Instances (delete first)
        instances=$(find_instances "$vpc_id")
        if [[ -n "$instances" ]]; then
            log_resource_type "EC2 Instances"
            while IFS=$'\t' read -r id state type name; do
                [[ -n "$id" ]] && log_resource "$id  $state  $type  $name"
            done <<< "$instances"
            count=$(echo "$instances" | grep -c . || echo 0)
            RESOURCE_COUNTS["EC2 Instances"]=$((${RESOURCE_COUNTS["EC2 Instances"]:-0} + count))
        fi

        # Load Balancers (delete early)
        # (checked globally, not per-VPC for simplicity)

        # NAT Gateways
        nats=$(find_nat_gateways "$vpc_id")
        if [[ -n "$nats" ]]; then
            log_resource_type "NAT Gateways"
            while IFS=$'\t' read -r id state subnet; do
                [[ -n "$id" ]] && log_resource "$id  $state  subnet: $subnet"
            done <<< "$nats"
            count=$(echo "$nats" | grep -c . || echo 0)
            RESOURCE_COUNTS["NAT Gateways"]=$((${RESOURCE_COUNTS["NAT Gateways"]:-0} + count))
        fi

        # VPC Endpoints
        endpoints=$(find_vpc_endpoints "$vpc_id")
        if [[ -n "$endpoints" ]]; then
            log_resource_type "VPC Endpoints"
            while IFS=$'\t' read -r id state service; do
                [[ -n "$id" ]] && log_resource "$id  $state  $service"
            done <<< "$endpoints"
            count=$(echo "$endpoints" | grep -c . || echo 0)
            RESOURCE_COUNTS["VPC Endpoints"]=$((${RESOURCE_COUNTS["VPC Endpoints"]:-0} + count))
        fi

        # Network Interfaces
        enis=$(find_enis "$vpc_id")
        if [[ -n "$enis" ]]; then
            log_resource_type "Network Interfaces"
            while IFS=$'\t' read -r id status desc; do
                [[ -n "$id" ]] && log_resource "$id  $status  ${desc:0:50}"
            done <<< "$enis"
            count=$(echo "$enis" | grep -c . || echo 0)
            RESOURCE_COUNTS["Network Interfaces"]=$((${RESOURCE_COUNTS["Network Interfaces"]:-0} + count))
        fi

        # Security Groups
        sgs=$(find_security_groups "$vpc_id")
        if [[ -n "$sgs" ]]; then
            log_resource_type "Security Groups"
            while IFS=$'\t' read -r id name; do
                [[ -n "$id" ]] && log_resource "$id  $name"
            done <<< "$sgs"
            count=$(echo "$sgs" | grep -c . || echo 0)
            RESOURCE_COUNTS["Security Groups"]=$((${RESOURCE_COUNTS["Security Groups"]:-0} + count))
        fi

        # Subnets
        subnets=$(find_subnets "$vpc_id")
        if [[ -n "$subnets" ]]; then
            log_resource_type "Subnets"
            while IFS=$'\t' read -r id state cidr az; do
                [[ -n "$id" ]] && log_resource "$id  $state  $cidr  $az"
            done <<< "$subnets"
            count=$(echo "$subnets" | grep -c . || echo 0)
            RESOURCE_COUNTS["Subnets"]=$((${RESOURCE_COUNTS["Subnets"]:-0} + count))
        fi

        # Internet Gateways
        igws=$(find_internet_gateways "$vpc_id")
        if [[ -n "$igws" ]]; then
            log_resource_type "Internet Gateways"
            while IFS=$'\t' read -r id state name; do
                [[ -n "$id" ]] && log_resource "$id  $state  $name"
            done <<< "$igws"
            count=$(echo "$igws" | grep -c . || echo 0)
            RESOURCE_COUNTS["Internet Gateways"]=$((${RESOURCE_COUNTS["Internet Gateways"]:-0} + count))
        fi

        # Route Tables
        rtbs=$(find_route_tables "$vpc_id")
        if [[ -n "$rtbs" ]]; then
            log_resource_type "Route Tables"
            while IFS=$'\t' read -r id name; do
                [[ -n "$id" ]] && log_resource "$id  $name"
            done <<< "$rtbs"
            count=$(echo "$rtbs" | grep -c . || echo 0)
            RESOURCE_COUNTS["Route Tables"]=$((${RESOURCE_COUNTS["Route Tables"]:-0} + count))
        fi

        # VPC itself
        log_resource_type "VPC"
        log_resource "$vpc_id  $vpc_name"
    done
fi

# ============================================================================
# Phase 3: Find global/non-VPC resources
# ============================================================================

if [[ $SUMMARY_ONLY == false ]]; then
    log_section "Global Resources (not VPC-specific)"
fi

# Load Balancers
elbs=$(find_classic_elbs)
elbv2s=$(find_elbv2)
if [[ -n "$elbs" || -n "$elbv2s" ]]; then
    if [[ $SUMMARY_ONLY == false ]]; then
        log_resource_type "Load Balancers"
        if [[ -n "$elbs" ]]; then
            while IFS=$'\t' read -r name scheme vpc; do
                [[ -n "$name" ]] && log_resource "(classic) $name  $scheme  vpc: $vpc"
            done <<< "$elbs"
        fi
        if [[ -n "$elbv2s" ]]; then
            while IFS=$'\t' read -r name type state vpc; do
                [[ -n "$name" ]] && log_resource "($type) $name  $state  vpc: $vpc"
            done <<< "$elbv2s"
        fi
    fi
    count1=$(echo "$elbs" | grep -c . 2>/dev/null || echo 0)
    count2=$(echo "$elbv2s" | grep -c . 2>/dev/null || echo 0)
    RESOURCE_COUNTS["Load Balancers"]=$((count1 + count2))
fi

# Elastic IPs
eips=$(find_eips)
if [[ -n "$eips" ]]; then
    if [[ $SUMMARY_ONLY == false ]]; then
        log_resource_type "Elastic IPs"
        while IFS=$'\t' read -r alloc_id ip assoc name; do
            [[ -n "$alloc_id" ]] && log_resource "$alloc_id  $ip  ${assoc:-not-associated}  $name"
        done <<< "$eips"
    fi
    count=$(echo "$eips" | grep -c . || echo 0)
    RESOURCE_COUNTS["Elastic IPs"]=$count
fi

# EBS Volumes
volumes=$(find_volumes)
if [[ -n "$volumes" ]]; then
    if [[ $SUMMARY_ONLY == false ]]; then
        log_resource_type "EBS Volumes"
        while IFS=$'\t' read -r id state size name; do
            [[ -n "$id" ]] && log_resource "$id  $state  ${size}GB  $name"
        done <<< "$volumes"
    fi
    count=$(echo "$volumes" | grep -c . || echo 0)
    RESOURCE_COUNTS["EBS Volumes"]=$count
fi

# S3 Buckets
buckets=$(find_s3_buckets)
if [[ -n "$buckets" ]]; then
    if [[ $SUMMARY_ONLY == false ]]; then
        log_resource_type "S3 Buckets"
        for bucket in $buckets; do
            log_resource "$bucket"
        done
    fi
    count=$(echo "$buckets" | wc -w | tr -d ' ')
    RESOURCE_COUNTS["S3 Buckets"]=$count
fi

# IAM Roles
roles=$(find_iam_roles)
if [[ -n "$roles" ]]; then
    if [[ $SUMMARY_ONLY == false ]]; then
        log_resource_type "IAM Roles"
        for role in $roles; do
            log_resource "$role"
        done
    fi
    count=$(echo "$roles" | wc -w | tr -d ' ')
    RESOURCE_COUNTS["IAM Roles"]=$count
fi

# Instance Profiles
profiles=$(find_instance_profiles)
if [[ -n "$profiles" ]]; then
    if [[ $SUMMARY_ONLY == false ]]; then
        log_resource_type "Instance Profiles"
        for profile in $profiles; do
            log_resource "$profile"
        done
    fi
    count=$(echo "$profiles" | wc -w | tr -d ' ')
    RESOURCE_COUNTS["Instance Profiles"]=$count
fi

# OIDC Providers
oidc=$(find_oidc_providers)
if [[ -n "$oidc" ]]; then
    if [[ $SUMMARY_ONLY == false ]]; then
        log_resource_type "OIDC Providers"
        while IFS= read -r arn; do
            [[ -n "$arn" ]] && log_resource "$arn"
        done <<< "$oidc"
    fi
    count=$(echo "$oidc" | grep -c . || echo 0)
    RESOURCE_COUNTS["OIDC Providers"]=$count
fi

# Route53 Zones
zones=$(find_route53_zones)
if [[ -n "$zones" ]]; then
    if [[ $SUMMARY_ONLY == false ]]; then
        log_resource_type "Route53 Hosted Zones"
        while IFS=$'\t' read -r name id private; do
            [[ -n "$name" ]] && log_resource "$name  $id  private: $private"
        done <<< "$zones"
    fi
    count=$(echo "$zones" | grep -c . || echo 0)
    RESOURCE_COUNTS["Route53 Zones"]=$count
fi

# ============================================================================
# Summary
# ============================================================================

log_header "SUMMARY"

echo ""
echo "VPCs found: ${RESOURCE_COUNTS["VPCs"]:-0}"
for vpc_id in "${!VPC_NAMES[@]}"; do
    echo "  - ${VPC_NAMES[$vpc_id]}"
done

echo ""
echo "Total resources by type:"

# Define display order (roughly dependency order for cleanup)
DISPLAY_ORDER=(
    "VPCs"
    "EC2 Instances"
    "Load Balancers"
    "NAT Gateways"
    "VPC Endpoints"
    "Network Interfaces"
    "Elastic IPs"
    "EBS Volumes"
    "Security Groups"
    "Subnets"
    "Internet Gateways"
    "Route Tables"
    "S3 Buckets"
    "IAM Roles"
    "Instance Profiles"
    "OIDC Providers"
    "Route53 Zones"
)

total_resources=0
for resource_type in "${DISPLAY_ORDER[@]}"; do
    count="${RESOURCE_COUNTS[$resource_type]:-0}"
    if [[ $count -gt 0 ]]; then
        printf "  %-20s %d\n" "$resource_type:" "$count"
        total_resources=$((total_resources + count))
    fi
done

echo ""
echo -e "${BOLD}Total: $total_resources resources${NC}"

if [[ $total_resources -gt 0 ]]; then
    echo ""
    echo -e "${YELLOW}Cleanup order (if needed):${NC}"
    echo "  1. Terminate EC2 instances (releases ENIs, EBS)"
    echo "  2. Delete load balancers"
    echo "  3. Delete NAT gateways (wait ~2 min for ENI release)"
    echo "  4. Delete VPC endpoints"
    echo "  5. Detach and delete ENIs"
    echo "  6. Delete EBS volumes"
    echo "  7. Release Elastic IPs"
    echo "  8. Delete security groups"
    echo "  9. Delete subnets"
    echo "  10. Detach and delete internet gateways"
    echo "  11. Delete route tables"
    echo "  12. Delete VPCs"
    echo "  13. Delete Route53 zones"
    echo "  14. Delete S3 buckets"
    echo "  15. Delete IAM roles and instance profiles"
    echo "  16. Delete OIDC providers"
    echo ""
    echo -e "${DIM}Tip: Use destroy-cluster.sh <cluster-suffix> to clean up a specific cluster${NC}"
fi

echo ""
