#!/usr/bin/env bash
#
# Find Orphaned AWS Resources
#
# Searches for AWS resources matching a prefix using the same filtering
# logic as our cleanup scripts (kubernetes.io/cluster/* tag-key filtering).
#
# USAGE:
#   ./.github/scripts/hypershift/find-orphaned-resources.sh [OPTIONS]
#
# OPTIONS:
#   --custom-prefix PREFIX   Override the default prefix (default: $MANAGED_BY_TAG)
#   --region REGION          AWS region (default: from env or us-east-1)
#   --no-color               Disable colored output
#   --summary-only           Only show summary, not individual resources
#   --delete-all             Delete all found resources (requires confirmation)
#   -h, --help               Show this help
#
# EXAMPLES:
#   source .env.kagenti-hypershift-ci && ./find-orphaned-resources.sh
#   ./find-orphaned-resources.sh --custom-prefix kagenti-hypershift
#   ./find-orphaned-resources.sh --custom-prefix kagenti-hypershift-custom-ladas --delete-all
#   ./find-orphaned-resources.sh --summary-only
#

set -euo pipefail

# ============================================================================
# Configuration
# ============================================================================

# Default values - MANAGED_BY_TAG from environment, must not be empty
CUSTOM_PREFIX=""
REGION="${AWS_REGION:-us-east-1}"
SUMMARY_ONLY=false
DELETE_ALL=false

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
            RED='' GREEN='' YELLOW='' BLUE='' CYAN='' BOLD='' DIM='' NC=''
            shift
            ;;
        --summary-only)
            SUMMARY_ONLY=true
            shift
            ;;
        --delete-all)
            DELETE_ALL=true
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

# Print a formatted table row
print_row() {
    local format="$1"
    shift
    printf "    $format\n" "$@"
}

# Print table header
print_table_header() {
    local format="$1"
    shift
    echo -e "    ${DIM}$(printf "$format" "$@")${NC}"
    echo -e "    ${DIM}$(printf "$format" "$@" | sed 's/./-/g')${NC}"
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

# Store found resources for deletion
ALL_VPCS=""
ALL_INSTANCES=""
ALL_NATS=""
ALL_IGWS=""
ALL_ENDPOINTS=""
ALL_ENIS=""
ALL_SGS=""
ALL_SUBNETS=""
ALL_RTBS=""
ALL_EIPS=""
ALL_VOLUMES=""
ALL_ELBS_CLASSIC=""
ALL_ELBS_V2=""
ALL_S3=""
ALL_ROLES=""
ALL_PROFILES=""
ALL_OIDC=""
ALL_ZONES=""

# ============================================================================
# Resource Discovery Functions (using consistent filtering with cleanup scripts)
# ============================================================================

# Find VPCs using BOTH Name tag AND kubernetes.io/cluster/* tag-key
# This matches what debug-aws-hypershift.sh and 55-cleanup use
find_vpcs() {
    # Method 1: VPCs with Name tag containing prefix
    local by_name
    by_name=$(aws ec2 describe-vpcs \
        --region "$REGION" \
        --filters "Name=tag:Name,Values=*${PREFIX}*" \
        --query 'Vpcs[*].VpcId' \
        --output text 2>/dev/null || echo "")

    # Method 2: VPCs with kubernetes.io/cluster/* tag starting with prefix
    # Use tag-key filter to find any kubernetes cluster tag
    local by_tag
    by_tag=$(aws ec2 describe-vpcs \
        --region "$REGION" \
        --query "Vpcs[?Tags[?starts_with(Key, 'kubernetes.io/cluster/${PREFIX}')]].VpcId" \
        --output text 2>/dev/null || echo "")

    # Combine and deduplicate (grep -v returns 1 when no match, so use || true)
    echo "$by_name $by_tag" | tr ' \t' '\n' | grep -v '^$' | sort -u | tr '\n' ' ' || true
}

# Get VPC details including all tags
get_vpc_details() {
    local vpc_id="$1"
    aws ec2 describe-vpcs \
        --region "$REGION" \
        --vpc-ids "$vpc_id" \
        --query 'Vpcs[0]' \
        --output json 2>/dev/null || echo "{}"
}

# Extract specific tag from tags JSON
get_tag_value() {
    local tags_json="$1"
    local tag_key="$2"
    echo "$tags_json" | jq -r ".Tags[]? | select(.Key==\"$tag_key\") | .Value // empty" 2>/dev/null || echo ""
}

# Get kubernetes cluster tag (key and value)
get_cluster_tag() {
    local tags_json="$1"
    echo "$tags_json" | jq -r '.Tags[]? | select(.Key | startswith("kubernetes.io/cluster/")) | "\(.Key)=\(.Value)"' 2>/dev/null | head -1 || echo ""
}

# Find EC2 instances in VPC or by tag
find_instances() {
    local vpc_id="${1:-}"
    if [[ -n "$vpc_id" ]]; then
        aws ec2 describe-instances \
            --region "$REGION" \
            --filters "Name=vpc-id,Values=$vpc_id" "Name=instance-state-name,Values=pending,running,stopping,stopped,shutting-down" \
            --query 'Reservations[*].Instances[*].[InstanceId,State.Name,InstanceType,Tags]' \
            --output json 2>/dev/null || echo "[]"
    else
        aws ec2 describe-instances \
            --region "$REGION" \
            --query "Reservations[*].Instances[?Tags[?starts_with(Key, 'kubernetes.io/cluster/${PREFIX}')]].[InstanceId,State.Name,InstanceType,Tags]" \
            --output json 2>/dev/null || echo "[]"
    fi
}

# Find NAT Gateways in VPC
find_nat_gateways() {
    local vpc_id="${1:-}"
    if [[ -n "$vpc_id" ]]; then
        aws ec2 describe-nat-gateways \
            --region "$REGION" \
            --filter "Name=vpc-id,Values=$vpc_id" "Name=state,Values=pending,available,deleting,failed" \
            --query 'NatGateways[*].[NatGatewayId,State,SubnetId,Tags]' \
            --output json 2>/dev/null || echo "[]"
    fi
}

# Find Internet Gateways attached to VPC
find_internet_gateways() {
    local vpc_id="${1:-}"
    if [[ -n "$vpc_id" ]]; then
        aws ec2 describe-internet-gateways \
            --region "$REGION" \
            --filters "Name=attachment.vpc-id,Values=$vpc_id" \
            --query 'InternetGateways[*].[InternetGatewayId,Attachments[0].State,Tags]' \
            --output json 2>/dev/null || echo "[]"
    fi
}

# Find VPC Endpoints
find_vpc_endpoints() {
    local vpc_id="${1:-}"
    if [[ -n "$vpc_id" ]]; then
        aws ec2 describe-vpc-endpoints \
            --region "$REGION" \
            --filters "Name=vpc-id,Values=$vpc_id" \
            --query 'VpcEndpoints[*].[VpcEndpointId,State,ServiceName,Tags]' \
            --output json 2>/dev/null || echo "[]"
    fi
}

# Find Network Interfaces in VPC
find_enis() {
    local vpc_id="${1:-}"
    if [[ -n "$vpc_id" ]]; then
        aws ec2 describe-network-interfaces \
            --region "$REGION" \
            --filters "Name=vpc-id,Values=$vpc_id" \
            --query 'NetworkInterfaces[*].[NetworkInterfaceId,Status,Description,Attachment.AttachmentId]' \
            --output json 2>/dev/null || echo "[]"
    fi
}

# Find Security Groups in VPC (non-default)
find_security_groups() {
    local vpc_id="${1:-}"
    if [[ -n "$vpc_id" ]]; then
        aws ec2 describe-security-groups \
            --region "$REGION" \
            --filters "Name=vpc-id,Values=$vpc_id" \
            --query 'SecurityGroups[?GroupName!=`default`].[GroupId,GroupName,Tags]' \
            --output json 2>/dev/null || echo "[]"
    fi
}

# Find Subnets in VPC
find_subnets() {
    local vpc_id="${1:-}"
    if [[ -n "$vpc_id" ]]; then
        aws ec2 describe-subnets \
            --region "$REGION" \
            --filters "Name=vpc-id,Values=$vpc_id" \
            --query 'Subnets[*].[SubnetId,State,CidrBlock,AvailabilityZone,Tags]' \
            --output json 2>/dev/null || echo "[]"
    fi
}

# Find Route Tables in VPC (non-main)
# Note: Use Associations[0].Main != `true` instead of !Associations[?Main==`true`]
# because the latter doesn't work correctly when Associations is empty
find_route_tables() {
    local vpc_id="${1:-}"
    if [[ -n "$vpc_id" ]]; then
        aws ec2 describe-route-tables \
            --region "$REGION" \
            --filters "Name=vpc-id,Values=$vpc_id" \
            --query 'RouteTables[?Associations[0].Main != `true`].[RouteTableId,Tags]' \
            --output json 2>/dev/null || echo "[]"
    fi
}

# Find Elastic IPs by tag
find_eips() {
    aws ec2 describe-addresses \
        --region "$REGION" \
        --query "Addresses[?Tags[?starts_with(Key, 'kubernetes.io/cluster/${PREFIX}') || (Key=='Name' && contains(Value, '${PREFIX}'))]].[AllocationId,PublicIp,AssociationId,Tags]" \
        --output json 2>/dev/null || echo "[]"
}

# Find EBS Volumes by tag
find_volumes() {
    aws ec2 describe-volumes \
        --region "$REGION" \
        --query "Volumes[?Tags[?starts_with(Key, 'kubernetes.io/cluster/${PREFIX}') || (Key=='Name' && contains(Value, '${PREFIX}'))]].[VolumeId,State,Size,Tags]" \
        --output json 2>/dev/null || echo "[]"
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
        --query "LoadBalancers[?contains(LoadBalancerName, '${PREFIX}')].[LoadBalancerArn,LoadBalancerName,Type,State.Code,VpcId]" \
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
# Count lines/items helper
# ============================================================================
count_items() {
    local data="$1"
    if [[ -z "$data" || "$data" == "[]" ]]; then
        echo 0
    else
        # Count rows in the array (not individual cells)
        echo "$data" | jq 'if type == "array" then length else 0 end' 2>/dev/null || echo 0
    fi
}

count_lines() {
    local data="$1"
    if [[ -z "$data" ]]; then
        echo 0
    else
        echo "$data" | grep -c . 2>/dev/null || echo 0
    fi
}

# ============================================================================
# Display Functions
# ============================================================================

display_instances() {
    local instances_json="$1"
    local count
    # EC2 instances have nested Reservations, so flatten first
    count=$(echo "$instances_json" | jq '[.[][] | select(type == "array" and length > 0)] | length' 2>/dev/null || echo 0)

    if [[ "$count" -gt 0 ]]; then
        log_resource_type "EC2 Instances ($count)"
        print_table_header "%-20s %-14s %-12s %-50s %-55s %-30s" "INSTANCE_ID" "STATE" "TYPE" "NAME" "CLUSTER_TAG" "MANAGED_BY"

        # Use process substitution to avoid subshell (so ALL_INSTANCES is updated)
        while read -r instance; do
            [[ -z "$instance" ]] && continue
            local id state type name cluster_tag managed_by
            id=$(echo "$instance" | jq -r '.[0] // "N/A"')
            state=$(echo "$instance" | jq -r '.[1] // "N/A"')
            type=$(echo "$instance" | jq -r '.[2] // "N/A"')
            name=$(echo "$instance" | jq -r '.[3][]? | select(.Key=="Name") | .Value' 2>/dev/null | head -1)
            cluster_tag=$(echo "$instance" | jq -r '.[3][]? | select(.Key | startswith("kubernetes.io/cluster/")) | "\(.Key | split("/") | .[2])=\(.Value)"' 2>/dev/null | head -1)
            managed_by=$(echo "$instance" | jq -r '.[3][]? | select(.Key=="kagenti.io/managed-by") | .Value' 2>/dev/null | head -1)
            [[ -z "$name" ]] && name="N/A"
            [[ -z "$cluster_tag" ]] && cluster_tag="N/A"
            [[ -z "$managed_by" ]] && managed_by="N/A"
            print_row "%-20s %-14s %-12s %-50s %-55s %-30s" "$id" "$state" "$type" "$name" "$cluster_tag" "$managed_by"
            ALL_INSTANCES="$ALL_INSTANCES $id"
        done < <(echo "$instances_json" | jq -c '.[][] | select(type == "array" and length > 0)' 2>/dev/null)
        return 0
    fi
    return 0
}

display_nat_gateways() {
    local nats_json="$1"
    local count
    # NAT gateways return flat array: [[id, state, subnet, tags], ...]
    count=$(echo "$nats_json" | jq 'length' 2>/dev/null || echo 0)

    if [[ "$count" -gt 0 ]]; then
        log_resource_type "NAT Gateways ($count)"
        print_table_header "%-25s %-12s %-25s %-50s %-55s %-30s" "NAT_GATEWAY_ID" "STATE" "SUBNET_ID" "NAME" "CLUSTER_TAG" "MANAGED_BY"

        while read -r nat; do
            [[ -z "$nat" ]] && continue
            local id state subnet name cluster_tag managed_by
            id=$(echo "$nat" | jq -r '.[0] // "N/A"')
            state=$(echo "$nat" | jq -r '.[1] // "N/A"')
            subnet=$(echo "$nat" | jq -r '.[2] // "N/A"')
            name=$(echo "$nat" | jq -r '.[3][]? | select(.Key=="Name") | .Value' 2>/dev/null | head -1)
            cluster_tag=$(echo "$nat" | jq -r '.[3][]? | select(.Key | startswith("kubernetes.io/cluster/")) | "\(.Key | split("/") | .[2])=\(.Value)"' 2>/dev/null | head -1)
            managed_by=$(echo "$nat" | jq -r '.[3][]? | select(.Key=="kagenti.io/managed-by") | .Value' 2>/dev/null | head -1)
            [[ -z "$name" ]] && name="N/A"
            [[ -z "$cluster_tag" ]] && cluster_tag="N/A"
            [[ -z "$managed_by" ]] && managed_by="N/A"
            print_row "%-25s %-12s %-25s %-50s %-55s %-30s" "$id" "$state" "$subnet" "$name" "$cluster_tag" "$managed_by"
            ALL_NATS="$ALL_NATS $id"
        done < <(echo "$nats_json" | jq -c '.[]' 2>/dev/null)
        return 0
    fi
    return 0
}

display_security_groups() {
    local sgs_json="$1"
    local count
    count=$(echo "$sgs_json" | jq 'length' 2>/dev/null || echo 0)

    if [[ "$count" -gt 0 ]]; then
        log_resource_type "Security Groups ($count)"
        print_table_header "%-25s %-50s %-55s %-30s" "GROUP_ID" "GROUP_NAME" "CLUSTER_TAG" "MANAGED_BY"

        while read -r sg; do
            [[ -z "$sg" ]] && continue
            local id name cluster_tag managed_by
            id=$(echo "$sg" | jq -r '.[0] // "N/A"')
            name=$(echo "$sg" | jq -r '.[1] // "N/A"')
            cluster_tag=$(echo "$sg" | jq -r '.[2][]? | select(.Key | startswith("kubernetes.io/cluster/")) | "\(.Key | split("/") | .[2])=\(.Value)"' 2>/dev/null | head -1)
            managed_by=$(echo "$sg" | jq -r '.[2][]? | select(.Key=="kagenti.io/managed-by") | .Value' 2>/dev/null | head -1)
            [[ -z "$cluster_tag" ]] && cluster_tag="N/A"
            [[ -z "$managed_by" ]] && managed_by="N/A"
            print_row "%-25s %-50s %-55s %-30s" "$id" "$name" "$cluster_tag" "$managed_by"
            ALL_SGS="$ALL_SGS $id"
        done < <(echo "$sgs_json" | jq -c '.[]' 2>/dev/null)
        return 0
    fi
    return 0
}

display_subnets() {
    local subnets_json="$1"
    local count
    count=$(echo "$subnets_json" | jq 'length' 2>/dev/null || echo 0)

    if [[ "$count" -gt 0 ]]; then
        log_resource_type "Subnets ($count)"
        print_table_header "%-25s %-12s %-18s %-15s %-50s %-55s %-30s" "SUBNET_ID" "STATE" "CIDR" "AZ" "NAME" "CLUSTER_TAG" "MANAGED_BY"

        while read -r subnet; do
            [[ -z "$subnet" ]] && continue
            local id state cidr az name cluster_tag managed_by
            id=$(echo "$subnet" | jq -r '.[0] // "N/A"')
            state=$(echo "$subnet" | jq -r '.[1] // "N/A"')
            cidr=$(echo "$subnet" | jq -r '.[2] // "N/A"')
            az=$(echo "$subnet" | jq -r '.[3] // "N/A"')
            name=$(echo "$subnet" | jq -r '.[4][]? | select(.Key=="Name") | .Value' 2>/dev/null | head -1)
            cluster_tag=$(echo "$subnet" | jq -r '.[4][]? | select(.Key | startswith("kubernetes.io/cluster/")) | "\(.Key | split("/") | .[2])=\(.Value)"' 2>/dev/null | head -1)
            managed_by=$(echo "$subnet" | jq -r '.[4][]? | select(.Key=="kagenti.io/managed-by") | .Value' 2>/dev/null | head -1)
            [[ -z "$name" ]] && name="N/A"
            [[ -z "$cluster_tag" ]] && cluster_tag="N/A"
            [[ -z "$managed_by" ]] && managed_by="N/A"
            print_row "%-25s %-12s %-18s %-15s %-50s %-55s %-30s" "$id" "$state" "$cidr" "$az" "$name" "$cluster_tag" "$managed_by"
            ALL_SUBNETS="$ALL_SUBNETS $id"
        done < <(echo "$subnets_json" | jq -c '.[]' 2>/dev/null)
        return 0
    fi
    return 0
}

display_enis() {
    local enis_json="$1"
    local count
    count=$(echo "$enis_json" | jq 'length' 2>/dev/null || echo 0)

    if [[ "$count" -gt 0 ]]; then
        log_resource_type "Network Interfaces ($count)"
        print_table_header "%-25s %-12s %-50s" "ENI_ID" "STATUS" "DESCRIPTION"

        while read -r eni; do
            [[ -z "$eni" ]] && continue
            local id status desc
            id=$(echo "$eni" | jq -r '.[0] // "N/A"')
            status=$(echo "$eni" | jq -r '.[1] // "N/A"')
            desc=$(echo "$eni" | jq -r '.[2] // "N/A"')
            print_row "%-25s %-12s %-50s" "$id" "$status" "${desc:0:50}"
            ALL_ENIS="$ALL_ENIS $id"
        done < <(echo "$enis_json" | jq -c '.[]' 2>/dev/null)
        return 0
    fi
    return 0
}

display_igws() {
    local igws_json="$1"
    local count
    count=$(echo "$igws_json" | jq 'length' 2>/dev/null || echo 0)

    if [[ "$count" -gt 0 ]]; then
        log_resource_type "Internet Gateways ($count)"
        print_table_header "%-25s %-12s %-50s %-55s %-30s" "IGW_ID" "STATE" "NAME" "CLUSTER_TAG" "MANAGED_BY"

        while read -r igw; do
            [[ -z "$igw" ]] && continue
            local id state name cluster_tag managed_by
            id=$(echo "$igw" | jq -r '.[0] // "N/A"')
            state=$(echo "$igw" | jq -r '.[1] // "N/A"')
            name=$(echo "$igw" | jq -r '.[2][]? | select(.Key=="Name") | .Value' 2>/dev/null | head -1)
            cluster_tag=$(echo "$igw" | jq -r '.[2][]? | select(.Key | startswith("kubernetes.io/cluster/")) | "\(.Key | split("/") | .[2])=\(.Value)"' 2>/dev/null | head -1)
            managed_by=$(echo "$igw" | jq -r '.[2][]? | select(.Key=="kagenti.io/managed-by") | .Value' 2>/dev/null | head -1)
            [[ -z "$name" ]] && name="N/A"
            [[ -z "$cluster_tag" ]] && cluster_tag="N/A"
            [[ -z "$managed_by" ]] && managed_by="N/A"
            print_row "%-25s %-12s %-50s %-55s %-30s" "$id" "$state" "$name" "$cluster_tag" "$managed_by"
            ALL_IGWS="$ALL_IGWS $id"
        done < <(echo "$igws_json" | jq -c '.[]' 2>/dev/null)
        return 0
    fi
    return 0
}

display_rtbs() {
    local rtbs_json="$1"
    local count
    count=$(echo "$rtbs_json" | jq 'length' 2>/dev/null || echo 0)

    if [[ "$count" -gt 0 ]]; then
        log_resource_type "Route Tables ($count)"
        print_table_header "%-25s %-50s %-55s %-30s" "ROUTE_TABLE_ID" "NAME" "CLUSTER_TAG" "MANAGED_BY"

        while read -r rtb; do
            [[ -z "$rtb" ]] && continue
            local id name cluster_tag managed_by
            id=$(echo "$rtb" | jq -r '.[0] // "N/A"')
            name=$(echo "$rtb" | jq -r '.[1][]? | select(.Key=="Name") | .Value' 2>/dev/null | head -1)
            cluster_tag=$(echo "$rtb" | jq -r '.[1][]? | select(.Key | startswith("kubernetes.io/cluster/")) | "\(.Key | split("/") | .[2])=\(.Value)"' 2>/dev/null | head -1)
            managed_by=$(echo "$rtb" | jq -r '.[1][]? | select(.Key=="kagenti.io/managed-by") | .Value' 2>/dev/null | head -1)
            [[ -z "$name" ]] && name="N/A"
            [[ -z "$cluster_tag" ]] && cluster_tag="N/A"
            [[ -z "$managed_by" ]] && managed_by="N/A"
            print_row "%-25s %-50s %-55s %-30s" "$id" "$name" "$cluster_tag" "$managed_by"
            ALL_RTBS="$ALL_RTBS $id"
        done < <(echo "$rtbs_json" | jq -c '.[]' 2>/dev/null)
        return 0
    fi
    return 0
}

display_endpoints() {
    local endpoints_json="$1"
    local count
    count=$(echo "$endpoints_json" | jq 'length' 2>/dev/null || echo 0)

    if [[ "$count" -gt 0 ]]; then
        log_resource_type "VPC Endpoints ($count)"
        print_table_header "%-25s %-12s %-50s" "ENDPOINT_ID" "STATE" "SERVICE"

        while read -r ep; do
            [[ -z "$ep" ]] && continue
            local id state service
            id=$(echo "$ep" | jq -r '.[0] // "N/A"')
            state=$(echo "$ep" | jq -r '.[1] // "N/A"')
            service=$(echo "$ep" | jq -r '.[2] // "N/A"')
            print_row "%-25s %-12s %-50s" "$id" "$state" "${service:0:50}"
            ALL_ENDPOINTS="$ALL_ENDPOINTS $id"
        done < <(echo "$endpoints_json" | jq -c '.[]' 2>/dev/null)
        return 0
    fi
    return 0
}

# ============================================================================
# Delete Functions (matching cleanup script logic)
# ============================================================================

delete_all_resources() {
    echo ""
    echo -e "${RED}═══════════════════════════════════════════════════════════════${NC}"
    echo -e "${RED}                    DELETION CONFIRMATION                       ${NC}"
    echo -e "${RED}═══════════════════════════════════════════════════════════════${NC}"
    echo ""
    echo -e "${YELLOW}WARNING: This will permanently delete the following resources:${NC}"
    echo ""
    echo "  Region: $REGION"
    echo "  Prefix: $PREFIX"
    echo ""
    echo "  Resources to delete:"
    [[ $COUNT_INSTANCES -gt 0 ]] && echo "    - EC2 Instances:      $COUNT_INSTANCES"
    [[ $COUNT_ELBS -gt 0 ]]      && echo "    - Load Balancers:     $COUNT_ELBS"
    [[ $COUNT_NATS -gt 0 ]]      && echo "    - NAT Gateways:       $COUNT_NATS"
    [[ $COUNT_ENDPOINTS -gt 0 ]] && echo "    - VPC Endpoints:      $COUNT_ENDPOINTS"
    [[ $COUNT_ENIS -gt 0 ]]      && echo "    - Network Interfaces: $COUNT_ENIS"
    [[ $COUNT_VOLUMES -gt 0 ]]   && echo "    - EBS Volumes:        $COUNT_VOLUMES"
    [[ $COUNT_EIPS -gt 0 ]]      && echo "    - Elastic IPs:        $COUNT_EIPS"
    [[ $COUNT_SGS -gt 0 ]]       && echo "    - Security Groups:    $COUNT_SGS"
    [[ $COUNT_SUBNETS -gt 0 ]]   && echo "    - Subnets:            $COUNT_SUBNETS"
    [[ $COUNT_RTBS -gt 0 ]]      && echo "    - Route Tables:       $COUNT_RTBS"
    [[ $COUNT_IGWS -gt 0 ]]      && echo "    - Internet Gateways:  $COUNT_IGWS"
    [[ $COUNT_VPCS -gt 0 ]]      && echo "    - VPCs:               $COUNT_VPCS"
    [[ $COUNT_ZONES -gt 0 ]]     && echo "    - Route53 Zones:      $COUNT_ZONES"
    [[ $COUNT_S3 -gt 0 ]]        && echo "    - S3 Buckets:         $COUNT_S3"
    [[ $COUNT_ROLES -gt 0 ]]     && echo "    - IAM Roles:          $COUNT_ROLES"
    [[ $COUNT_PROFILES -gt 0 ]] && echo "    - Instance Profiles:  $COUNT_PROFILES"
    [[ $COUNT_OIDC -gt 0 ]]      && echo "    - OIDC Providers:     $COUNT_OIDC"
    echo ""
    echo -e "${RED}This action cannot be undone!${NC}"
    echo ""
    echo -n "Type 'yes' to confirm deletion: "
    read -r confirmation

    if [[ "$confirmation" != "yes" ]]; then
        echo ""
        echo -e "${GREEN}Deletion cancelled.${NC}"
        return 1
    fi

    echo ""
    echo -e "${YELLOW}Starting deletion in dependency order...${NC}"
    echo ""

    # 1. Terminate EC2 Instances
    if [[ -n "${ALL_INSTANCES// /}" ]]; then
        echo "  [1/16] Terminating EC2 instances..."
        for id in $ALL_INSTANCES; do
            echo "    Terminating: $id"
            aws ec2 terminate-instances --region "$REGION" --instance-ids "$id" 2>/dev/null || true
        done
        echo "    Waiting for instances to terminate..."
        for id in $ALL_INSTANCES; do
            aws ec2 wait instance-terminated --region "$REGION" --instance-ids "$id" 2>/dev/null || true
        done
        echo -e "    ${GREEN}Done${NC}"
    fi

    # 2. Delete Load Balancers
    if [[ -n "${ALL_ELBS_CLASSIC// /}" ]]; then
        echo "  [2/16] Deleting Classic Load Balancers..."
        for lb in $ALL_ELBS_CLASSIC; do
            echo "    Deleting: $lb"
            aws elb delete-load-balancer --region "$REGION" --load-balancer-name "$lb" 2>/dev/null || true
        done
        echo -e "    ${GREEN}Done${NC}"
    fi
    if [[ -n "${ALL_ELBS_V2// /}" ]]; then
        echo "  [2/16] Deleting ALB/NLB Load Balancers..."
        for arn in $ALL_ELBS_V2; do
            echo "    Deleting: $arn"
            aws elbv2 delete-load-balancer --region "$REGION" --load-balancer-arn "$arn" 2>/dev/null || true
        done
        echo -e "    ${GREEN}Done${NC}"
    fi

    # 3. Delete NAT Gateways (and wait with polling)
    if [[ -n "${ALL_NATS// /}" ]]; then
        echo "  [3/16] Deleting NAT Gateways..."
        for id in $ALL_NATS; do
            echo "    Deleting: $id"
            local delete_response
            delete_response=$(aws ec2 delete-nat-gateway --region "$REGION" --nat-gateway-id "$id" 2>&1) || true
            echo "      Response: $(echo "$delete_response" | jq -r '.NatGatewayId // .' 2>/dev/null || echo "$delete_response")"
        done
        echo "    Waiting for NAT Gateways to delete (polling every 10s, max 5 min)..."
        local max_wait=300
        local waited=0
        local interval=10
        while [[ $waited -lt $max_wait ]]; do
            local all_deleted=true
            for id in $ALL_NATS; do
                local state
                state=$(aws ec2 describe-nat-gateways --region "$REGION" --nat-gateway-ids "$id" \
                    --query 'NatGateways[0].State' --output text 2>/dev/null || echo "not-found")
                if [[ "$state" != "deleted" && "$state" != "not-found" && "$state" != "None" ]]; then
                    all_deleted=false
                    echo "      [$id] state: $state (waited ${waited}s)"
                fi
            done
            if [[ "$all_deleted" == "true" ]]; then
                echo "    All NAT Gateways deleted"
                break
            fi
            sleep $interval
            waited=$((waited + interval))
        done
        if [[ $waited -ge $max_wait ]]; then
            echo -e "    ${YELLOW}Warning: Timeout waiting for NAT Gateways, continuing...${NC}"
        fi
        echo -e "    ${GREEN}Done${NC}"
    fi

    # 4. Delete VPC Endpoints (with polling)
    if [[ -n "${ALL_ENDPOINTS// /}" ]]; then
        echo "  [4/16] Deleting VPC Endpoints..."
        for id in $ALL_ENDPOINTS; do
            echo "    Deleting: $id"
            aws ec2 delete-vpc-endpoints --region "$REGION" --vpc-endpoint-ids "$id" 2>/dev/null || true
        done
        echo "    Waiting for VPC Endpoints to delete (polling every 10s, max 3 min)..."
        local max_wait=180
        local waited=0
        local interval=10
        while [[ $waited -lt $max_wait ]]; do
            local all_deleted=true
            for id in $ALL_ENDPOINTS; do
                local state
                state=$(aws ec2 describe-vpc-endpoints --region "$REGION" --vpc-endpoint-ids "$id" \
                    --query 'VpcEndpoints[0].State' --output text 2>/dev/null || echo "not-found")
                if [[ "$state" != "deleted" && "$state" != "not-found" && "$state" != "None" ]]; then
                    all_deleted=false
                    echo "      [$id] state: $state (waited ${waited}s)"
                fi
            done
            if [[ "$all_deleted" == "true" ]]; then
                echo "    All VPC Endpoints deleted"
                break
            fi
            sleep $interval
            waited=$((waited + interval))
        done
        if [[ $waited -ge $max_wait ]]; then
            echo -e "    ${YELLOW}Warning: Timeout waiting for VPC Endpoints, continuing...${NC}"
        fi
        echo -e "    ${GREEN}Done${NC}"
    fi

    # 5. Detach and Delete ENIs (with wait and requester-managed handling)
    if [[ -n "${ALL_ENIS// /}" ]]; then
        echo "  [5/16] Detaching and deleting Network Interfaces..."
        for id in $ALL_ENIS; do
            # Get ENI info including description
            local eni_info
            eni_info=$(aws ec2 describe-network-interfaces --region "$REGION" \
                --network-interface-ids "$id" --output json 2>/dev/null || echo "{}")

            local description
            description=$(echo "$eni_info" | jq -r '.NetworkInterfaces[0].Description // empty' 2>/dev/null)

            # Skip requester-managed ENIs (created by AWS services like Lambda, EKS)
            if [[ "$description" =~ "AWS created network interface" ]] || \
               [[ "$description" =~ "ELB" ]] || \
               [[ "$description" =~ "Amazon EKS" ]]; then
                echo "    Skipping requester-managed ENI: $id (${description:0:50}...)"
                continue
            fi

            local attachment
            attachment=$(echo "$eni_info" | jq -r '.NetworkInterfaces[0].Attachment.AttachmentId // empty' 2>/dev/null)

            if [[ -n "$attachment" && "$attachment" != "None" && "$attachment" != "null" ]]; then
                echo "    Detaching: $id"
                aws ec2 detach-network-interface --region "$REGION" --attachment-id "$attachment" --force 2>/dev/null || true

                # Wait for ENI to become available (max 2 min)
                echo "      Waiting for ENI to become available..."
                local eni_wait=0
                local eni_max=120
                while [[ $eni_wait -lt $eni_max ]]; do
                    local eni_state
                    eni_state=$(aws ec2 describe-network-interfaces --region "$REGION" \
                        --network-interface-ids "$id" \
                        --query 'NetworkInterfaces[0].Status' --output text 2>/dev/null || echo "not-found")
                    if [[ "$eni_state" == "available" || "$eni_state" == "not-found" ]]; then
                        break
                    fi
                    echo "      [$id] state: $eni_state (waited ${eni_wait}s)"
                    sleep 5
                    eni_wait=$((eni_wait + 5))
                done
            fi

            echo "    Deleting: $id"
            aws ec2 delete-network-interface --region "$REGION" --network-interface-id "$id" 2>/dev/null || {
                echo -e "      ${YELLOW}Warning: Failed to delete $id (may be managed by AWS service)${NC}"
            }
        done
        # Wait for ENI deletions to propagate before proceeding (matches CI cleanup)
        echo "    Waiting 5s for ENI deletions to propagate..."
        sleep 5
        echo -e "    ${GREEN}Done${NC}"
    fi

    # 6. Delete EBS Volumes
    if [[ -n "${ALL_VOLUMES// /}" ]]; then
        echo "  [6/16] Deleting EBS Volumes..."
        for id in $ALL_VOLUMES; do
            echo "    Deleting: $id"
            aws ec2 delete-volume --region "$REGION" --volume-id "$id" 2>/dev/null || true
        done
        echo -e "    ${GREEN}Done${NC}"
    fi

    # 7. Release Elastic IPs
    if [[ -n "${ALL_EIPS// /}" ]]; then
        echo "  [7/16] Releasing Elastic IPs..."
        for id in $ALL_EIPS; do
            echo "    Releasing: $id"
            aws ec2 release-address --region "$REGION" --allocation-id "$id" 2>/dev/null || true
        done
        echo -e "    ${GREEN}Done${NC}"
    fi

    # 8. Delete Security Groups
    if [[ -n "${ALL_SGS// /}" ]]; then
        echo "  [8/16] Deleting Security Groups..."
        # First revoke all inter-SG rules
        echo "    Revoking inter-SG rules..."
        for id in $ALL_SGS; do
            aws ec2 revoke-security-group-ingress --region "$REGION" --group-id "$id" --source-group "$id" 2>/dev/null || true
            aws ec2 revoke-security-group-egress --region "$REGION" --group-id "$id" --source-group "$id" 2>/dev/null || true
        done
        # Delete
        for id in $ALL_SGS; do
            echo "    Deleting: $id"
            local sg_result
            sg_result=$(aws ec2 delete-security-group --region "$REGION" --group-id "$id" 2>&1)
            if [[ $? -ne 0 ]]; then
                echo -e "    ${RED}ERROR: Failed to delete security group $id${NC}"
                echo "    $sg_result"
                return 1
            fi
        done
        echo -e "    ${GREEN}Done${NC}"
    fi

    # 9. Delete Subnets (this removes route table associations automatically)
    if [[ -n "${ALL_SUBNETS// /}" ]]; then
        echo "  [9/16] Deleting Subnets..."
        for id in $ALL_SUBNETS; do
            echo "    Deleting: $id"
            local subnet_result
            subnet_result=$(aws ec2 delete-subnet --region "$REGION" --subnet-id "$id" 2>&1)
            if [[ $? -ne 0 ]]; then
                echo -e "    ${RED}ERROR: Failed to delete subnet $id${NC}"
                echo "    $subnet_result"
                return 1
            fi
        done
        # Wait for subnet deletion to propagate (matches CI cleanup)
        echo "    Waiting 5s for subnet deletion to propagate..."
        sleep 5
        echo -e "    ${GREEN}Done${NC}"
    fi

    # 10. Delete Route Tables (disassociate first, matching CI cleanup approach)
    if [[ -n "${ALL_RTBS// /}" ]]; then
        echo "  [10/16] Deleting Route Tables..."
        for id in $ALL_RTBS; do
            echo "    Processing: $id"

            # Check for remaining associations and disassociate them first
            # This is critical - route tables can't be deleted while associated
            local remaining_assocs
            remaining_assocs=$(aws ec2 describe-route-tables --region "$REGION" \
                --route-table-ids "$id" \
                --query 'RouteTables[0].Associations[?Main!=`true`].RouteTableAssociationId' \
                --output text 2>/dev/null || echo "")

            if [[ -n "$remaining_assocs" && "$remaining_assocs" != "None" ]]; then
                echo "      Disassociating: $remaining_assocs"
                for assoc in $remaining_assocs; do
                    aws ec2 disassociate-route-table --region "$REGION" \
                        --association-id "$assoc" 2>/dev/null || true
                done
            fi

            echo "    Deleting: $id"
            local rtb_result
            rtb_result=$(aws ec2 delete-route-table --region "$REGION" --route-table-id "$id" 2>&1)
            if [[ $? -ne 0 ]]; then
                echo -e "    ${RED}ERROR: Failed to delete route table $id${NC}"
                echo "    $rtb_result"
                return 1
            fi
        done
        echo -e "    ${GREEN}Done${NC}"
    fi

    # 11. Detach and Delete Internet Gateways
    if [[ -n "${ALL_IGWS// /}" ]]; then
        echo "  [11/16] Detaching and deleting Internet Gateways..."
        for vpc_id in $ALL_VPCS; do
            # Get IGWs attached to this VPC
            igws=$(aws ec2 describe-internet-gateways --region "$REGION" \
                --filters "Name=attachment.vpc-id,Values=$vpc_id" \
                --query 'InternetGateways[*].InternetGatewayId' --output text 2>/dev/null || echo "")
            for igw in $igws; do
                echo "    Detaching $igw from $vpc_id"
                aws ec2 detach-internet-gateway --region "$REGION" --internet-gateway-id "$igw" --vpc-id "$vpc_id" 2>/dev/null || true
                echo "    Deleting: $igw"
                aws ec2 delete-internet-gateway --region "$REGION" --internet-gateway-id "$igw" 2>/dev/null || true
            done
        done
        echo -e "    ${GREEN}Done${NC}"
    fi

    # 12. Delete VPCs
    if [[ -n "${ALL_VPCS// /}" ]]; then
        echo "  [12/16] Deleting VPCs..."
        for id in $ALL_VPCS; do
            echo "    Deleting: $id"
            local vpc_result
            vpc_result=$(aws ec2 delete-vpc --region "$REGION" --vpc-id "$id" 2>&1)
            if [[ $? -ne 0 ]]; then
                echo -e "    ${RED}ERROR: Failed to delete VPC $id${NC}"
                echo "    $vpc_result"
                # Show remaining dependencies for debugging
                echo "    Remaining ENIs in VPC:"
                while read -r line; do
                    echo "      $line"
                done < <(aws ec2 describe-network-interfaces --region "$REGION" \
                    --filters "Name=vpc-id,Values=$id" \
                    --query 'NetworkInterfaces[*].[NetworkInterfaceId,Description]' \
                    --output text 2>/dev/null | head -5) || true
                return 1
            fi
        done
        echo -e "    ${GREEN}Done${NC}"
    fi

    # 13. Delete Route53 Zones
    if [[ -n "${ALL_ZONES// /}" ]]; then
        echo "  [13/16] Deleting Route53 Zones..."
        for zone_id in $ALL_ZONES; do
            echo "    Cleaning zone: $zone_id"
            # Delete all records except NS and SOA
            while read -r record; do
                if [[ -n "$record" ]]; then
                    aws route53 change-resource-record-sets --hosted-zone-id "$zone_id" \
                        --change-batch "{\"Changes\":[{\"Action\":\"DELETE\",\"ResourceRecordSet\":$record}]}" 2>/dev/null || true
                fi
            done < <(aws route53 list-resource-record-sets --hosted-zone-id "$zone_id" \
                --query "ResourceRecordSets[?Type != 'NS' && Type != 'SOA']" \
                --output json 2>/dev/null | jq -c '.[]' 2>/dev/null)
            echo "    Deleting: $zone_id"
            aws route53 delete-hosted-zone --id "$zone_id" 2>/dev/null || true
        done
        echo -e "    ${GREEN}Done${NC}"
    fi

    # 14. Delete S3 Buckets (with versioning support)
    if [[ -n "${ALL_S3// /}" ]]; then
        echo "  [14/16] Deleting S3 Buckets..."
        for bucket in $ALL_S3; do
            echo "    Processing bucket: $bucket"

            # Check if versioning is enabled
            local versioning
            versioning=$(aws s3api get-bucket-versioning --bucket "$bucket" \
                --query 'Status' --output text 2>/dev/null || echo "Disabled")

            if [[ "$versioning" == "Enabled" || "$versioning" == "Suspended" ]]; then
                echo "      Bucket has versioning, deleting all versions..."
                # Delete all object versions
                while read -r obj; do
                    if [[ -n "$obj" && "$obj" != "null" ]]; then
                        local key version_id
                        key=$(echo "$obj" | jq -r '.Key')
                        version_id=$(echo "$obj" | jq -r '.VersionId')
                        aws s3api delete-object --bucket "$bucket" --key "$key" --version-id "$version_id" 2>/dev/null || true
                    fi
                done < <(aws s3api list-object-versions --bucket "$bucket" \
                    --query '{Objects: Versions[].{Key:Key,VersionId:VersionId}}' \
                    --output json 2>/dev/null | jq -c '.Objects[]?' 2>/dev/null)

                # Delete all delete markers
                while read -r obj; do
                    if [[ -n "$obj" && "$obj" != "null" ]]; then
                        local key version_id
                        key=$(echo "$obj" | jq -r '.Key')
                        version_id=$(echo "$obj" | jq -r '.VersionId')
                        aws s3api delete-object --bucket "$bucket" --key "$key" --version-id "$version_id" 2>/dev/null || true
                    fi
                done < <(aws s3api list-object-versions --bucket "$bucket" \
                    --query '{Objects: DeleteMarkers[].{Key:Key,VersionId:VersionId}}' \
                    --output json 2>/dev/null | jq -c '.Objects[]?' 2>/dev/null)
            else
                echo "      Emptying bucket (no versioning)..."
                aws s3 rm "s3://$bucket" --recursive 2>/dev/null || true
            fi

            echo "      Deleting bucket: $bucket"
            aws s3api delete-bucket --bucket "$bucket" --region "$REGION" 2>/dev/null || {
                echo -e "      ${YELLOW}Warning: Failed to delete bucket $bucket (may need manual cleanup)${NC}"
            }
        done
        echo -e "    ${GREEN}Done${NC}"
    fi

    # 15. Delete IAM Roles
    if [[ -n "${ALL_ROLES// /}" ]]; then
        echo "  [15/16] Deleting IAM Roles..."
        for role in $ALL_ROLES; do
            echo "    Cleaning up: $role"
            # Detach managed policies
            for policy in $(aws iam list-attached-role-policies --role-name "$role" --query 'AttachedPolicies[*].PolicyArn' --output text 2>/dev/null); do
                aws iam detach-role-policy --role-name "$role" --policy-arn "$policy" 2>/dev/null || true
            done
            # Delete inline policies
            for policy in $(aws iam list-role-policies --role-name "$role" --query 'PolicyNames[*]' --output text 2>/dev/null); do
                aws iam delete-role-policy --role-name "$role" --policy-name "$policy" 2>/dev/null || true
            done
            aws iam delete-role --role-name "$role" 2>/dev/null || true
        done
        echo -e "    ${GREEN}Done${NC}"
    fi

    # 16. Delete Instance Profiles
    if [[ -n "${ALL_PROFILES// /}" ]]; then
        echo "  [16/16] Deleting Instance Profiles..."
        for profile in $ALL_PROFILES; do
            echo "    Cleaning up: $profile"
            # Remove roles from profile
            for role in $(aws iam get-instance-profile --instance-profile-name "$profile" --query 'InstanceProfile.Roles[*].RoleName' --output text 2>/dev/null); do
                aws iam remove-role-from-instance-profile --instance-profile-name "$profile" --role-name "$role" 2>/dev/null || true
            done
            aws iam delete-instance-profile --instance-profile-name "$profile" 2>/dev/null || true
        done
        echo -e "    ${GREEN}Done${NC}"
    fi

    # 17. Delete OIDC Providers
    if [[ -n "${ALL_OIDC// /}" ]]; then
        echo "  [17/16] Deleting OIDC Providers..."
        for arn in $ALL_OIDC; do
            echo "    Deleting: $arn"
            aws iam delete-open-id-connect-provider --open-id-connect-provider-arn "$arn" 2>/dev/null || true
        done
        echo -e "    ${GREEN}Done${NC}"
    fi

    echo ""
    echo -e "${GREEN}═══════════════════════════════════════════════════════════════${NC}"
    echo -e "${GREEN}                    DELETION COMPLETE                          ${NC}"
    echo -e "${GREEN}═══════════════════════════════════════════════════════════════${NC}"
    echo ""

    return 0
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

VPC_IDS=$(find_vpcs)

# ============================================================================
# Phase 2: For each VPC, find associated resources
# ============================================================================

for vpc_id in $VPC_IDS; do
    [[ -z "$vpc_id" ]] && continue

    # Get VPC details
    vpc_json=$(get_vpc_details "$vpc_id")
    vpc_name=$(echo "$vpc_json" | jq -r '.Tags[]? | select(.Key=="Name") | .Value // "unnamed"' 2>/dev/null | head -1)
    vpc_cidr=$(echo "$vpc_json" | jq -r '.CidrBlock // "N/A"' 2>/dev/null)
    vpc_state=$(echo "$vpc_json" | jq -r '.State // "N/A"' 2>/dev/null)
    cluster_tag=$(get_cluster_tag "$vpc_json")

    ALL_VPCS="$ALL_VPCS $vpc_id"
    COUNT_VPCS=$((COUNT_VPCS + 1))

    if [[ $SUMMARY_ONLY == false ]]; then
        log_section "VPC: $vpc_id"
        echo ""
        echo -e "    ${BOLD}Name:${NC}        $vpc_name"
        echo -e "    ${BOLD}CIDR:${NC}        $vpc_cidr"
        echo -e "    ${BOLD}State:${NC}       $vpc_state"
        echo -e "    ${BOLD}Cluster Tag:${NC} ${cluster_tag:-N/A}"

        # EC2 Instances
        instances=$(find_instances "$vpc_id")
        display_instances "$instances"
        COUNT_INSTANCES=$((COUNT_INSTANCES + $(count_items "$instances")))

        # NAT Gateways
        nats=$(find_nat_gateways "$vpc_id")
        display_nat_gateways "$nats"
        COUNT_NATS=$((COUNT_NATS + $(count_items "$nats")))

        # VPC Endpoints
        endpoints=$(find_vpc_endpoints "$vpc_id")
        display_endpoints "$endpoints"
        COUNT_ENDPOINTS=$((COUNT_ENDPOINTS + $(count_items "$endpoints")))

        # ENIs
        enis=$(find_enis "$vpc_id")
        display_enis "$enis"
        COUNT_ENIS=$((COUNT_ENIS + $(count_items "$enis")))

        # Security Groups
        sgs=$(find_security_groups "$vpc_id")
        display_security_groups "$sgs"
        COUNT_SGS=$((COUNT_SGS + $(count_items "$sgs")))

        # Subnets
        subnets=$(find_subnets "$vpc_id")
        display_subnets "$subnets"
        COUNT_SUBNETS=$((COUNT_SUBNETS + $(count_items "$subnets")))

        # Internet Gateways
        igws=$(find_internet_gateways "$vpc_id")
        display_igws "$igws"
        COUNT_IGWS=$((COUNT_IGWS + $(count_items "$igws")))

        # Route Tables
        rtbs=$(find_route_tables "$vpc_id")
        display_rtbs "$rtbs"
        COUNT_RTBS=$((COUNT_RTBS + $(count_items "$rtbs")))
    else
        # Summary mode: just count
        COUNT_INSTANCES=$((COUNT_INSTANCES + $(count_items "$(find_instances "$vpc_id")")))
        COUNT_NATS=$((COUNT_NATS + $(count_items "$(find_nat_gateways "$vpc_id")")))
        COUNT_ENDPOINTS=$((COUNT_ENDPOINTS + $(count_items "$(find_vpc_endpoints "$vpc_id")")))
        COUNT_ENIS=$((COUNT_ENIS + $(count_items "$(find_enis "$vpc_id")")))
        COUNT_SGS=$((COUNT_SGS + $(count_items "$(find_security_groups "$vpc_id")")))
        COUNT_SUBNETS=$((COUNT_SUBNETS + $(count_items "$(find_subnets "$vpc_id")")))
        COUNT_IGWS=$((COUNT_IGWS + $(count_items "$(find_internet_gateways "$vpc_id")")))
        COUNT_RTBS=$((COUNT_RTBS + $(count_items "$(find_route_tables "$vpc_id")")))
    fi
done

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
    elb_count=$(($(count_lines "$elbs") + $(count_lines "$elbv2s")))
    COUNT_ELBS=$elb_count

    if [[ $SUMMARY_ONLY == false ]]; then
        log_resource_type "Load Balancers ($elb_count)"
        print_table_header "%-10s %-40s %-12s %-25s" "TYPE" "NAME/ARN" "SCHEME" "VPC"

        if [[ -n "$elbs" ]]; then
            while IFS=$'\t' read -r lb_name scheme vpc; do
                [[ -n "$lb_name" && "$lb_name" != "None" ]] && {
                    print_row "%-10s %-40s %-12s %-25s" "classic" "$lb_name" "$scheme" "$vpc"
                    ALL_ELBS_CLASSIC="$ALL_ELBS_CLASSIC $lb_name"
                }
            done <<< "$elbs"
        fi
        if [[ -n "$elbv2s" ]]; then
            while IFS=$'\t' read -r arn lb_name lb_type state vpc; do
                [[ -n "$arn" && "$arn" != "None" ]] && {
                    print_row "%-10s %-40s %-12s %-25s" "$lb_type" "${lb_name:0:40}" "$state" "$vpc"
                    ALL_ELBS_V2="$ALL_ELBS_V2 $arn"
                }
            done <<< "$elbv2s"
        fi
    fi
fi

# Elastic IPs
eips_json=$(find_eips)
eip_count=$(echo "$eips_json" | jq 'length' 2>/dev/null || echo 0)
if [[ "$eip_count" -gt 0 ]]; then
    COUNT_EIPS=$eip_count
    if [[ $SUMMARY_ONLY == false ]]; then
        log_resource_type "Elastic IPs ($eip_count)"
        print_table_header "%-25s %-16s %-25s %-50s %-55s %-30s" "ALLOCATION_ID" "PUBLIC_IP" "ASSOCIATION" "NAME" "CLUSTER_TAG" "MANAGED_BY"

        while read -r eip; do
            [[ -z "$eip" ]] && continue
            alloc_id=$(echo "$eip" | jq -r '.[0] // "N/A"')
            ip=$(echo "$eip" | jq -r '.[1] // "N/A"')
            assoc=$(echo "$eip" | jq -r '.[2] // "not-associated"')
            name=$(echo "$eip" | jq -r '.[3][]? | select(.Key=="Name") | .Value' 2>/dev/null | head -1)
            cluster_tag=$(echo "$eip" | jq -r '.[3][]? | select(.Key | startswith("kubernetes.io/cluster/")) | "\(.Key | split("/") | .[2])=\(.Value)"' 2>/dev/null | head -1)
            managed_by=$(echo "$eip" | jq -r '.[3][]? | select(.Key=="kagenti.io/managed-by") | .Value' 2>/dev/null | head -1)
            [[ -z "$name" ]] && name="N/A"
            [[ -z "$cluster_tag" ]] && cluster_tag="N/A"
            [[ -z "$managed_by" ]] && managed_by="N/A"
            [[ "$assoc" == "null" ]] && assoc="not-associated"
            print_row "%-25s %-16s %-25s %-50s %-55s %-30s" "$alloc_id" "$ip" "$assoc" "$name" "$cluster_tag" "$managed_by"
            ALL_EIPS="$ALL_EIPS $alloc_id"
        done < <(echo "$eips_json" | jq -c '.[]' 2>/dev/null)
    fi
fi

# EBS Volumes
volumes_json=$(find_volumes)
vol_count=$(echo "$volumes_json" | jq 'length' 2>/dev/null || echo 0)
if [[ "$vol_count" -gt 0 ]]; then
    COUNT_VOLUMES=$vol_count
    if [[ $SUMMARY_ONLY == false ]]; then
        log_resource_type "EBS Volumes ($vol_count)"
        print_table_header "%-25s %-12s %-8s %-50s %-55s %-30s" "VOLUME_ID" "STATE" "SIZE_GB" "NAME" "CLUSTER_TAG" "MANAGED_BY"

        while read -r vol; do
            [[ -z "$vol" ]] && continue
            id=$(echo "$vol" | jq -r '.[0] // "N/A"')
            state=$(echo "$vol" | jq -r '.[1] // "N/A"')
            size=$(echo "$vol" | jq -r '.[2] // "N/A"')
            name=$(echo "$vol" | jq -r '.[3][]? | select(.Key=="Name") | .Value' 2>/dev/null | head -1)
            cluster_tag=$(echo "$vol" | jq -r '.[3][]? | select(.Key | startswith("kubernetes.io/cluster/")) | "\(.Key | split("/") | .[2])=\(.Value)"' 2>/dev/null | head -1)
            managed_by=$(echo "$vol" | jq -r '.[3][]? | select(.Key=="kagenti.io/managed-by") | .Value' 2>/dev/null | head -1)
            [[ -z "$name" ]] && name="N/A"
            [[ -z "$cluster_tag" ]] && cluster_tag="N/A"
            [[ -z "$managed_by" ]] && managed_by="N/A"
            print_row "%-25s %-12s %-8s %-50s %-55s %-30s" "$id" "$state" "$size" "$name" "$cluster_tag" "$managed_by"
            ALL_VOLUMES="$ALL_VOLUMES $id"
        done < <(echo "$volumes_json" | jq -c '.[]' 2>/dev/null)
    fi
fi

# S3 Buckets
buckets=$(find_s3_buckets)
if [[ -n "$buckets" ]]; then
    COUNT_S3=$(echo "$buckets" | wc -w | tr -d ' ')
    if [[ $SUMMARY_ONLY == false ]]; then
        log_resource_type "S3 Buckets ($COUNT_S3)"
        print_table_header "%-60s" "BUCKET_NAME"
        for bucket in $buckets; do
            print_row "%-60s" "$bucket"
            ALL_S3="$ALL_S3 $bucket"
        done
    fi
fi

# IAM Roles
roles=$(find_iam_roles)
if [[ -n "$roles" ]]; then
    COUNT_ROLES=$(echo "$roles" | wc -w | tr -d ' ')
    if [[ $SUMMARY_ONLY == false ]]; then
        log_resource_type "IAM Roles ($COUNT_ROLES)"
        print_table_header "%-60s" "ROLE_NAME"
        for role in $roles; do
            print_row "%-60s" "$role"
            ALL_ROLES="$ALL_ROLES $role"
        done
    fi
fi

# Instance Profiles
profiles=$(find_instance_profiles)
if [[ -n "$profiles" ]]; then
    COUNT_PROFILES=$(echo "$profiles" | wc -w | tr -d ' ')
    if [[ $SUMMARY_ONLY == false ]]; then
        log_resource_type "Instance Profiles ($COUNT_PROFILES)"
        print_table_header "%-60s" "PROFILE_NAME"
        for profile in $profiles; do
            print_row "%-60s" "$profile"
            ALL_PROFILES="$ALL_PROFILES $profile"
        done
    fi
fi

# OIDC Providers
oidc=$(find_oidc_providers)
if [[ -n "$oidc" ]]; then
    COUNT_OIDC=$(count_lines "$oidc")
    if [[ $SUMMARY_ONLY == false ]]; then
        log_resource_type "OIDC Providers ($COUNT_OIDC)"
        print_table_header "%-80s" "PROVIDER_ARN"
        while IFS= read -r arn; do
            [[ -n "$arn" ]] && {
                print_row "%-80s" "$arn"
                ALL_OIDC="$ALL_OIDC $arn"
            }
        done <<< "$oidc"
    fi
fi

# Route53 Zones
zones=$(find_route53_zones)
if [[ -n "$zones" ]]; then
    COUNT_ZONES=$(count_lines "$zones")
    if [[ $SUMMARY_ONLY == false ]]; then
        log_resource_type "Route53 Hosted Zones ($COUNT_ZONES)"
        print_table_header "%-40s %-30s %-10s" "ZONE_NAME" "ZONE_ID" "PRIVATE"
        while IFS=$'\t' read -r zone_name id private; do
            [[ -n "$zone_name" && "$zone_name" != "None" ]] && {
                print_row "%-40s %-30s %-10s" "$zone_name" "$id" "$private"
                ALL_ZONES="$ALL_ZONES $id"
            }
        done <<< "$zones"
    fi
fi

# ============================================================================
# Summary
# ============================================================================

log_header "SUMMARY"

echo ""
echo "VPCs found: $COUNT_VPCS"
for vpc_id in $ALL_VPCS; do
    [[ -z "$vpc_id" ]] && continue
    vpc_json=$(get_vpc_details "$vpc_id")
    vpc_name=$(echo "$vpc_json" | jq -r '.Tags[]? | select(.Key=="Name") | .Value // "unnamed"' 2>/dev/null | head -1)
    cluster_tag=$(get_cluster_tag "$vpc_json")
    echo "  - $vpc_name ($vpc_id)"
    [[ -n "$cluster_tag" ]] && echo "    Tag: $cluster_tag"
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
    echo -e "${DIM}Tip: Use --delete-all to delete all found resources${NC}"
    echo -e "${DIM}     Use destroy-cluster.sh <cluster-suffix> to clean up a specific cluster${NC}"

    # If --delete-all was specified, proceed with deletion
    if [[ $DELETE_ALL == true ]]; then
        delete_all_resources
    fi
fi

echo ""
