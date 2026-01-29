#!/usr/bin/env bash
#
# Find Orphaned AWS Resources
#
# Searches for AWS resources matching a prefix.
# Default prefix: $MANAGED_BY_TAG (from environment)
# Useful for identifying orphaned resources from failed cluster creations.
#
# USAGE:
#   ./.github/scripts/hypershift/find-orphaned-resources.sh [OPTIONS]
#
# OPTIONS:
#   --custom-prefix PREFIX   Override the default prefix (default: $MANAGED_BY_TAG)
#   --region REGION          AWS region (default: from env or us-east-1)
#   --no-color               Disable colored output
#   --summary-only           Only show summary, not individual resources
#   -h, --help               Show this help
#
# EXAMPLES:
#   source .env.kagenti-hypershift-ci && ./find-orphaned-resources.sh
#   ./find-orphaned-resources.sh --custom-prefix kagenti-hypershift
#   ./find-orphaned-resources.sh --summary-only
#

set -euo pipefail

# ============================================================================
# Configuration
# ============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"

# Default values - MANAGED_BY_TAG from environment, must not be empty
CUSTOM_PREFIX=""
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
        --custom-prefix)
            CUSTOM_PREFIX="$2"
            shift 2
            ;;
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
            head -28 "$0" | tail -23
            exit 0
            ;;
        -*)
            echo "Unknown option: $1" >&2
            echo "Use --help for usage information" >&2
            exit 1
            ;;
        *)
            # Backwards compatibility: positional arg sets custom prefix
            CUSTOM_PREFIX="$1"
            shift
            ;;
    esac
done

# Determine prefix to use
if [[ -n "$CUSTOM_PREFIX" ]]; then
    PREFIX="$CUSTOM_PREFIX"
elif [[ -n "${MANAGED_BY_TAG:-}" ]]; then
    PREFIX="$MANAGED_BY_TAG"
else
    echo "Error: No prefix specified." >&2
    echo "" >&2
    echo "Either:" >&2
    echo "  1. Set MANAGED_BY_TAG environment variable (e.g., source .env.kagenti-hypershift-ci)" >&2
    echo "  2. Use --custom-prefix <prefix> option" >&2
    echo "" >&2
    echo "Example:" >&2
    echo "  source .env.kagenti-hypershift-ci && $0" >&2
    echo "  $0 --custom-prefix kagenti-hypershift" >&2
    exit 1
fi

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

# Simple counter variables (bash 3.x compatible)
COUNT_VPCS=0
COUNT_INSTANCES=0
COUNT_NATS=0
COUNT_IGWS=0
COUNT_ENDPOINTS=0
COUNT_ENIS=0
COUNT_SGS=0
COUNT_SUBNETS=0
COUNT_RTBS=0
COUNT_EIPS=0
COUNT_VOLUMES=0
COUNT_ELBS=0
COUNT_S3=0
COUNT_ROLES=0
COUNT_PROFILES=0
COUNT_OIDC=0
COUNT_ZONES=0

# Store VPC info in simple arrays (bash 3.x compatible)
VPC_IDS=""
VPC_NAMES_LIST=""

# ============================================================================
# Resource Discovery Functions
# ============================================================================

# Find VPCs by name prefix
find_vpcs() {
    aws ec2 describe-vpcs \
        --region "$REGION" \
        --filters "Name=tag:Name,Values=*${PREFIX}*" \
        --query 'Vpcs[*].[VpcId,State,CidrBlock,Tags[?Key==`Name`].Value|[0]]' \
        --output text 2>/dev/null || echo ""
}

# Find EC2 instances
find_instances() {
    local vpc_id="${1:-}"
    if [[ -n "$vpc_id" ]]; then
        aws ec2 describe-instances \
            --region "$REGION" \
            --filters "Name=vpc-id,Values=$vpc_id" "Name=instance-state-name,Values=pending,running,stopping,stopped,shutting-down" \
            --query 'Reservations[*].Instances[*].[InstanceId,State.Name,InstanceType,Tags[?Key==`Name`].Value|[0]]' \
            --output text 2>/dev/null || echo ""
    else
        aws ec2 describe-instances \
            --region "$REGION" \
            --filters "Name=tag:Name,Values=*${PREFIX}*" "Name=instance-state-name,Values=pending,running,stopping,stopped,shutting-down" \
            --query 'Reservations[*].Instances[*].[InstanceId,State.Name,InstanceType,Tags[?Key==`Name`].Value|[0]]' \
            --output text 2>/dev/null || echo ""
    fi
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
# Count lines helper
# ============================================================================
count_lines() {
    local data="$1"
    if [[ -z "$data" ]]; then
        echo 0
    else
        echo "$data" | grep -c . 2>/dev/null || echo 0
    fi
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

if [[ -n "$VPCS" ]]; then
    while IFS=$'\t' read -r vpc_id state cidr name; do
        if [[ -n "$vpc_id" && "$vpc_id" != "None" ]]; then
            VPC_IDS="$VPC_IDS $vpc_id"
            VPC_NAMES_LIST="$VPC_NAMES_LIST|$vpc_id:$name"
            COUNT_VPCS=$((COUNT_VPCS + 1))
        fi
    done <<< "$VPCS"
fi

# ============================================================================
# Phase 2: For each VPC, find associated resources
# ============================================================================

if [[ $SUMMARY_ONLY == false ]]; then
    for vpc_id in $VPC_IDS; do
        # Extract VPC name from our list
        vpc_name=$(echo "$VPC_NAMES_LIST" | tr '|' '\n' | grep "^$vpc_id:" | cut -d: -f2-)
        [[ -z "$vpc_name" ]] && vpc_name="(unnamed)"

        log_section "VPC: $vpc_id ($vpc_name)"

        # EC2 Instances (delete first)
        instances=$(find_instances "$vpc_id")
        if [[ -n "$instances" ]]; then
            log_resource_type "EC2 Instances"
            while IFS=$'\t' read -r id inst_state type inst_name; do
                [[ -n "$id" && "$id" != "None" ]] && log_resource "$id  $inst_state  $type  $inst_name"
            done <<< "$instances"
            COUNT_INSTANCES=$((COUNT_INSTANCES + $(count_lines "$instances")))
        fi

        # NAT Gateways
        nats=$(find_nat_gateways "$vpc_id")
        if [[ -n "$nats" ]]; then
            log_resource_type "NAT Gateways"
            while IFS=$'\t' read -r id nat_state subnet; do
                [[ -n "$id" && "$id" != "None" ]] && log_resource "$id  $nat_state  subnet: $subnet"
            done <<< "$nats"
            COUNT_NATS=$((COUNT_NATS + $(count_lines "$nats")))
        fi

        # VPC Endpoints
        endpoints=$(find_vpc_endpoints "$vpc_id")
        if [[ -n "$endpoints" ]]; then
            log_resource_type "VPC Endpoints"
            while IFS=$'\t' read -r id ep_state service; do
                [[ -n "$id" && "$id" != "None" ]] && log_resource "$id  $ep_state  $service"
            done <<< "$endpoints"
            COUNT_ENDPOINTS=$((COUNT_ENDPOINTS + $(count_lines "$endpoints")))
        fi

        # Network Interfaces
        enis=$(find_enis "$vpc_id")
        if [[ -n "$enis" ]]; then
            log_resource_type "Network Interfaces"
            while IFS=$'\t' read -r id status desc; do
                [[ -n "$id" && "$id" != "None" ]] && log_resource "$id  $status  ${desc:0:50}"
            done <<< "$enis"
            COUNT_ENIS=$((COUNT_ENIS + $(count_lines "$enis")))
        fi

        # Security Groups
        sgs=$(find_security_groups "$vpc_id")
        if [[ -n "$sgs" ]]; then
            log_resource_type "Security Groups"
            while IFS=$'\t' read -r id sg_name; do
                [[ -n "$id" && "$id" != "None" ]] && log_resource "$id  $sg_name"
            done <<< "$sgs"
            COUNT_SGS=$((COUNT_SGS + $(count_lines "$sgs")))
        fi

        # Subnets
        subnets=$(find_subnets "$vpc_id")
        if [[ -n "$subnets" ]]; then
            log_resource_type "Subnets"
            while IFS=$'\t' read -r id sub_state sub_cidr az; do
                [[ -n "$id" && "$id" != "None" ]] && log_resource "$id  $sub_state  $sub_cidr  $az"
            done <<< "$subnets"
            COUNT_SUBNETS=$((COUNT_SUBNETS + $(count_lines "$subnets")))
        fi

        # Internet Gateways
        igws=$(find_internet_gateways "$vpc_id")
        if [[ -n "$igws" ]]; then
            log_resource_type "Internet Gateways"
            while IFS=$'\t' read -r id igw_state igw_name; do
                [[ -n "$id" && "$id" != "None" ]] && log_resource "$id  $igw_state  $igw_name"
            done <<< "$igws"
            COUNT_IGWS=$((COUNT_IGWS + $(count_lines "$igws")))
        fi

        # Route Tables
        rtbs=$(find_route_tables "$vpc_id")
        if [[ -n "$rtbs" ]]; then
            log_resource_type "Route Tables"
            while IFS=$'\t' read -r id rtb_name; do
                [[ -n "$id" && "$id" != "None" ]] && log_resource "$id  $rtb_name"
            done <<< "$rtbs"
            COUNT_RTBS=$((COUNT_RTBS + $(count_lines "$rtbs")))
        fi

        # VPC itself
        log_resource_type "VPC"
        log_resource "$vpc_id  $vpc_name"
    done
fi

# If summary only, still need to count VPC resources
if [[ $SUMMARY_ONLY == true ]]; then
    for vpc_id in $VPC_IDS; do
        COUNT_INSTANCES=$((COUNT_INSTANCES + $(count_lines "$(find_instances "$vpc_id")")))
        COUNT_NATS=$((COUNT_NATS + $(count_lines "$(find_nat_gateways "$vpc_id")")))
        COUNT_ENDPOINTS=$((COUNT_ENDPOINTS + $(count_lines "$(find_vpc_endpoints "$vpc_id")")))
        COUNT_ENIS=$((COUNT_ENIS + $(count_lines "$(find_enis "$vpc_id")")))
        COUNT_SGS=$((COUNT_SGS + $(count_lines "$(find_security_groups "$vpc_id")")))
        COUNT_SUBNETS=$((COUNT_SUBNETS + $(count_lines "$(find_subnets "$vpc_id")")))
        COUNT_IGWS=$((COUNT_IGWS + $(count_lines "$(find_internet_gateways "$vpc_id")")))
        COUNT_RTBS=$((COUNT_RTBS + $(count_lines "$(find_route_tables "$vpc_id")")))
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
            while IFS=$'\t' read -r lb_name scheme vpc; do
                [[ -n "$lb_name" && "$lb_name" != "None" ]] && log_resource "(classic) $lb_name  $scheme  vpc: $vpc"
            done <<< "$elbs"
        fi
        if [[ -n "$elbv2s" ]]; then
            while IFS=$'\t' read -r lb_name type lb_state vpc; do
                [[ -n "$lb_name" && "$lb_name" != "None" ]] && log_resource "($type) $lb_name  $lb_state  vpc: $vpc"
            done <<< "$elbv2s"
        fi
    fi
    COUNT_ELBS=$(($(count_lines "$elbs") + $(count_lines "$elbv2s")))
fi

# Elastic IPs
eips=$(find_eips)
if [[ -n "$eips" ]]; then
    if [[ $SUMMARY_ONLY == false ]]; then
        log_resource_type "Elastic IPs"
        while IFS=$'\t' read -r alloc_id ip assoc eip_name; do
            [[ -n "$alloc_id" && "$alloc_id" != "None" ]] && log_resource "$alloc_id  $ip  ${assoc:-not-associated}  $eip_name"
        done <<< "$eips"
    fi
    COUNT_EIPS=$(count_lines "$eips")
fi

# EBS Volumes
volumes=$(find_volumes)
if [[ -n "$volumes" ]]; then
    if [[ $SUMMARY_ONLY == false ]]; then
        log_resource_type "EBS Volumes"
        while IFS=$'\t' read -r id vol_state size vol_name; do
            [[ -n "$id" && "$id" != "None" ]] && log_resource "$id  $vol_state  ${size}GB  $vol_name"
        done <<< "$volumes"
    fi
    COUNT_VOLUMES=$(count_lines "$volumes")
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
    COUNT_S3=$(echo "$buckets" | wc -w | tr -d ' ')
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
    COUNT_ROLES=$(echo "$roles" | wc -w | tr -d ' ')
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
    COUNT_PROFILES=$(echo "$profiles" | wc -w | tr -d ' ')
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
    COUNT_OIDC=$(count_lines "$oidc")
fi

# Route53 Zones
zones=$(find_route53_zones)
if [[ -n "$zones" ]]; then
    if [[ $SUMMARY_ONLY == false ]]; then
        log_resource_type "Route53 Hosted Zones"
        while IFS=$'\t' read -r zone_name id private; do
            [[ -n "$zone_name" && "$zone_name" != "None" ]] && log_resource "$zone_name  $id  private: $private"
        done <<< "$zones"
    fi
    COUNT_ZONES=$(count_lines "$zones")
fi

# ============================================================================
# Summary
# ============================================================================

log_header "SUMMARY"

echo ""
echo "VPCs found: $COUNT_VPCS"
for vpc_id in $VPC_IDS; do
    vpc_name=$(echo "$VPC_NAMES_LIST" | tr '|' '\n' | grep "^$vpc_id:" | cut -d: -f2-)
    echo "  - $vpc_name"
done

echo ""
echo "Total resources by type:"

# Print counts if > 0
print_count() {
    local label="$1"
    local count="$2"
    if [[ $count -gt 0 ]]; then
        printf "  %-22s %d\n" "$label:" "$count"
    fi
}

print_count "VPCs" "$COUNT_VPCS"
print_count "EC2 Instances" "$COUNT_INSTANCES"
print_count "Load Balancers" "$COUNT_ELBS"
print_count "NAT Gateways" "$COUNT_NATS"
print_count "VPC Endpoints" "$COUNT_ENDPOINTS"
print_count "Network Interfaces" "$COUNT_ENIS"
print_count "Elastic IPs" "$COUNT_EIPS"
print_count "EBS Volumes" "$COUNT_VOLUMES"
print_count "Security Groups" "$COUNT_SGS"
print_count "Subnets" "$COUNT_SUBNETS"
print_count "Internet Gateways" "$COUNT_IGWS"
print_count "Route Tables" "$COUNT_RTBS"
print_count "S3 Buckets" "$COUNT_S3"
print_count "IAM Roles" "$COUNT_ROLES"
print_count "Instance Profiles" "$COUNT_PROFILES"
print_count "OIDC Providers" "$COUNT_OIDC"
print_count "Route53 Zones" "$COUNT_ZONES"

total_resources=$((COUNT_VPCS + COUNT_INSTANCES + COUNT_ELBS + COUNT_NATS + COUNT_ENDPOINTS + COUNT_ENIS + COUNT_EIPS + COUNT_VOLUMES + COUNT_SGS + COUNT_SUBNETS + COUNT_IGWS + COUNT_RTBS + COUNT_S3 + COUNT_ROLES + COUNT_PROFILES + COUNT_OIDC + COUNT_ZONES))

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
