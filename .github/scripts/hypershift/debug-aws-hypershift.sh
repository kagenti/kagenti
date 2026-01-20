#!/usr/bin/env bash
#
# Debug AWS HyperShift Resources
#
# Runs read-only AWS commands to identify resources related to a HyperShift cluster.
# Useful for debugging stuck deletions and orphaned resources.
#
# USAGE:
#   ./.github/scripts/hypershift/debug-aws-hypershift.sh [OPTIONS] [cluster-name]
#
# OPTIONS:
#   --check    Quiet mode - only return exit code (0=no resources, 1=resources exist)
#
# EXAMPLES:
#   ./.github/scripts/hypershift/debug-aws-hypershift.sh                           # Uses default: kagenti-hypershift-ci-local
#   ./.github/scripts/hypershift/debug-aws-hypershift.sh kagenti-hypershift-ci-123 # Specific cluster
#   ./.github/scripts/hypershift/debug-aws-hypershift.sh --check local             # Check mode, returns exit code
#

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"

# Parse arguments
CHECK_MODE=false
CLUSTER_NAME=""

for arg in "$@"; do
    case $arg in
        --check)
            CHECK_MODE=true
            ;;
        *)
            CLUSTER_NAME="$arg"
            ;;
    esac
done

# Load credentials
if [ -f "$REPO_ROOT/.env.hypershift-ci" ]; then
    # shellcheck source=/dev/null
    source "$REPO_ROOT/.env.hypershift-ci"
fi

# Default cluster name
if [ -z "$CLUSTER_NAME" ]; then
    CLUSTER_NAME="${MANAGED_BY_TAG:-kagenti-hypershift-ci}-local"
fi

# Handle suffix-only input (add prefix if needed)
if [[ "$CLUSTER_NAME" != "${MANAGED_BY_TAG:-kagenti-hypershift-ci}-"* ]]; then
    CLUSTER_NAME="${MANAGED_BY_TAG:-kagenti-hypershift-ci}-${CLUSTER_NAME}"
fi

# Track if any resources are found
RESOURCES_FOUND=false

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m'

# Logging functions (respect CHECK_MODE, always return 0 to avoid set -e issues)
log_header() { [ "$CHECK_MODE" = false ] && echo -e "\n${BLUE}═══════════════════════════════════════════════════════════════${NC}" && echo -e "${BLUE}$1${NC}" && echo -e "${BLUE}═══════════════════════════════════════════════════════════════${NC}" || true; }
log_section() { [ "$CHECK_MODE" = false ] && echo -e "\n${YELLOW}>>> $1${NC}" || true; }
log_found() { [ "$CHECK_MODE" = false ] && echo -e "${GREEN}[FOUND]${NC} $1" || true; }
log_empty() { [ "$CHECK_MODE" = false ] && echo -e "${NC}[NONE]${NC} $1" || true; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

log_header "AWS HyperShift Debug: $CLUSTER_NAME"

if [ "$CHECK_MODE" = false ]; then
    echo ""
    echo "Cluster Name: $CLUSTER_NAME"
    echo "AWS Region:   ${AWS_REGION:-us-east-1}"
    echo "Managed By:   ${MANAGED_BY_TAG:-kagenti-hypershift-ci}"
    echo ""
fi

# Check AWS credentials
log_section "Verifying AWS Credentials"
if [ "$CHECK_MODE" = false ]; then
    if aws sts get-caller-identity --output table 2>/dev/null; then
        echo ""
    else
        log_error "AWS credentials not configured or invalid"
        exit 1
    fi
else
    if ! aws sts get-caller-identity --output text &>/dev/null; then
        log_error "AWS credentials not configured or invalid"
        exit 1
    fi
fi

# ============================================================================
# EC2 Resources
# ============================================================================

log_section "EC2 Instances (tagged with kubernetes.io/cluster/$CLUSTER_NAME)"
INSTANCES=$(aws ec2 describe-instances \
    --filters "Name=tag-key,Values=kubernetes.io/cluster/$CLUSTER_NAME" \
    --query 'Reservations[*].Instances[*].[InstanceId,State.Name,InstanceType,Tags[?Key==`Name`].Value|[0]]' \
    --output text 2>/dev/null || echo "")
if [ -n "$INSTANCES" ]; then
    RESOURCES_FOUND=true
    log_found "EC2 Instances:"
    [ "$CHECK_MODE" = false ] && echo "$INSTANCES" | column -t
else
    log_empty "No EC2 instances found"
fi

log_section "VPCs (tagged with kubernetes.io/cluster/$CLUSTER_NAME)"
VPCS=$(aws ec2 describe-vpcs \
    --filters "Name=tag-key,Values=kubernetes.io/cluster/$CLUSTER_NAME" \
    --query 'Vpcs[*].[VpcId,State,CidrBlock,Tags[?Key==`Name`].Value|[0]]' \
    --output text 2>/dev/null || echo "")
if [ -n "$VPCS" ]; then
    RESOURCES_FOUND=true
    log_found "VPCs:"
    [ "$CHECK_MODE" = false ] && echo "$VPCS" | column -t
else
    log_empty "No VPCs found"
fi

log_section "Subnets (tagged with kubernetes.io/cluster/$CLUSTER_NAME)"
SUBNETS=$(aws ec2 describe-subnets \
    --filters "Name=tag-key,Values=kubernetes.io/cluster/$CLUSTER_NAME" \
    --query 'Subnets[*].[SubnetId,State,CidrBlock,AvailabilityZone]' \
    --output text 2>/dev/null || echo "")
if [ -n "$SUBNETS" ]; then
    RESOURCES_FOUND=true
    log_found "Subnets:"
    [ "$CHECK_MODE" = false ] && echo "$SUBNETS" | column -t
else
    log_empty "No subnets found"
fi

log_section "Security Groups (tagged with kubernetes.io/cluster/$CLUSTER_NAME)"
SGS=$(aws ec2 describe-security-groups \
    --filters "Name=tag-key,Values=kubernetes.io/cluster/$CLUSTER_NAME" \
    --query 'SecurityGroups[*].[GroupId,GroupName,VpcId]' \
    --output text 2>/dev/null || echo "")
if [ -n "$SGS" ]; then
    RESOURCES_FOUND=true
    log_found "Security Groups:"
    [ "$CHECK_MODE" = false ] && echo "$SGS" | column -t
else
    log_empty "No security groups found"
fi

log_section "NAT Gateways (tagged with kubernetes.io/cluster/$CLUSTER_NAME)"
NATS=$(aws ec2 describe-nat-gateways \
    --filter "Name=tag-key,Values=kubernetes.io/cluster/$CLUSTER_NAME" \
    --query 'NatGateways[*].[NatGatewayId,State,VpcId]' \
    --output text 2>/dev/null || echo "")
if [ -n "$NATS" ]; then
    RESOURCES_FOUND=true
    log_found "NAT Gateways:"
    [ "$CHECK_MODE" = false ] && echo "$NATS" | column -t
else
    log_empty "No NAT gateways found"
fi

log_section "Internet Gateways (tagged with kubernetes.io/cluster/$CLUSTER_NAME)"
IGWS=$(aws ec2 describe-internet-gateways \
    --filters "Name=tag-key,Values=kubernetes.io/cluster/$CLUSTER_NAME" \
    --query 'InternetGateways[*].[InternetGatewayId,Attachments[0].State,Attachments[0].VpcId]' \
    --output text 2>/dev/null || echo "")
if [ -n "$IGWS" ]; then
    RESOURCES_FOUND=true
    log_found "Internet Gateways:"
    [ "$CHECK_MODE" = false ] && echo "$IGWS" | column -t
else
    log_empty "No internet gateways found"
fi

log_section "Elastic IPs (tagged with kubernetes.io/cluster/$CLUSTER_NAME)"
EIPS=$(aws ec2 describe-addresses \
    --filters "Name=tag-key,Values=kubernetes.io/cluster/$CLUSTER_NAME" \
    --query 'Addresses[*].[AllocationId,PublicIp,AssociationId]' \
    --output text 2>/dev/null || echo "")
if [ -n "$EIPS" ]; then
    RESOURCES_FOUND=true
    log_found "Elastic IPs:"
    [ "$CHECK_MODE" = false ] && echo "$EIPS" | column -t
else
    log_empty "No Elastic IPs found"
fi

# ============================================================================
# Load Balancers
# ============================================================================

log_section "Classic Load Balancers (name contains $CLUSTER_NAME)"
CLBS=$(aws elb describe-load-balancers \
    --query "LoadBalancerDescriptions[?contains(LoadBalancerName, '$CLUSTER_NAME')].[LoadBalancerName,Scheme,VPCId]" \
    --output text 2>/dev/null || echo "")
if [ -n "$CLBS" ]; then
    RESOURCES_FOUND=true
    log_found "Classic ELBs:"
    [ "$CHECK_MODE" = false ] && echo "$CLBS" | column -t
else
    log_empty "No classic load balancers found"
fi

log_section "Application/Network Load Balancers (name contains $CLUSTER_NAME)"
ALBS=$(aws elbv2 describe-load-balancers \
    --query "LoadBalancers[?contains(LoadBalancerName, '$CLUSTER_NAME')].[LoadBalancerName,Type,State.Code]" \
    --output text 2>/dev/null || echo "")
if [ -n "$ALBS" ]; then
    RESOURCES_FOUND=true
    log_found "ALB/NLBs:"
    [ "$CHECK_MODE" = false ] && echo "$ALBS" | column -t
else
    log_empty "No ALB/NLB load balancers found"
fi

# ============================================================================
# S3 Buckets
# ============================================================================

log_section "S3 Buckets (name contains $CLUSTER_NAME)"
BUCKETS=$(aws s3api list-buckets --query "Buckets[?contains(Name, '$CLUSTER_NAME')].Name" --output text 2>/dev/null || echo "")
if [ -n "$BUCKETS" ]; then
    RESOURCES_FOUND=true
    log_found "S3 Buckets:"
    [ "$CHECK_MODE" = false ] && echo "$BUCKETS" | tr '\t' '\n'
else
    log_empty "No S3 buckets found"
fi

# ============================================================================
# IAM Resources
# ============================================================================

log_section "IAM Roles (name contains $CLUSTER_NAME)"
ROLES=$(aws iam list-roles --query "Roles[?contains(RoleName, '$CLUSTER_NAME')].RoleName" --output text 2>/dev/null || echo "")
if [ -n "$ROLES" ]; then
    RESOURCES_FOUND=true
    log_found "IAM Roles:"
    [ "$CHECK_MODE" = false ] && echo "$ROLES" | tr '\t' '\n'
else
    log_empty "No IAM roles found"
fi

log_section "IAM Instance Profiles (name contains $CLUSTER_NAME)"
PROFILES=$(aws iam list-instance-profiles --query "InstanceProfiles[?contains(InstanceProfileName, '$CLUSTER_NAME')].InstanceProfileName" --output text 2>/dev/null || echo "")
if [ -n "$PROFILES" ]; then
    RESOURCES_FOUND=true
    log_found "Instance Profiles:"
    [ "$CHECK_MODE" = false ] && echo "$PROFILES" | tr '\t' '\n'
else
    log_empty "No instance profiles found"
fi

log_section "OIDC Providers (ARN contains $CLUSTER_NAME)"
OIDC=$(aws iam list-open-id-connect-providers --query 'OpenIDConnectProviderList[*].Arn' --output text 2>/dev/null | tr '\t' '\n' | grep "$CLUSTER_NAME" || echo "")
if [ -n "$OIDC" ]; then
    RESOURCES_FOUND=true
    log_found "OIDC Providers:"
    [ "$CHECK_MODE" = false ] && echo "$OIDC"
else
    log_empty "No OIDC providers found"
fi

# ============================================================================
# Route53
# ============================================================================

log_section "Route53 Hosted Zones (name contains $CLUSTER_NAME)"
ZONES=$(aws route53 list-hosted-zones --query "HostedZones[?contains(Name, '$CLUSTER_NAME')].[Name,Id,Config.PrivateZone]" --output text 2>/dev/null || echo "")
if [ -n "$ZONES" ]; then
    RESOURCES_FOUND=true
    log_found "Hosted Zones:"
    [ "$CHECK_MODE" = false ] && echo "$ZONES" | column -t
else
    log_empty "No Route53 zones found for cluster name"
fi

# ============================================================================
# Summary and Exit Code
# ============================================================================

if [ "$CHECK_MODE" = true ]; then
    # In check mode, exit with code based on whether resources were found
    if [ "$RESOURCES_FOUND" = true ]; then
        exit 1  # Resources exist
    else
        exit 0  # No resources (safe to remove finalizer)
    fi
fi

log_header "Summary"

echo ""
echo "Resources checked for cluster: $CLUSTER_NAME"
echo ""

if [ "$RESOURCES_FOUND" = true ]; then
    echo -e "${RED}AWS resources still exist!${NC}"
    echo "These resources may be blocking cluster deletion."
    echo "The HyperShift operator needs to clean up these resources before the"
    echo "HostedCluster finalizer can be removed."
    echo ""
    echo "To force remove the finalizer (use with caution - may orphan AWS resources):"
    echo "  oc patch hostedcluster -n clusters $CLUSTER_NAME -p '{\"metadata\":{\"finalizers\":null}}' --type=merge"
    echo ""
    echo "To manually delete AWS resources (after removing finalizer):"
    echo "  # Delete in order: instances, NATs, subnets, IGWs, VPCs, roles, S3, OIDC"
else
    echo -e "${GREEN}All AWS resources have been cleaned up.${NC}"
    echo "It is safe to remove the HostedCluster finalizer if it is stuck."
    echo ""
    echo "To remove the finalizer:"
    echo "  oc patch hostedcluster -n clusters $CLUSTER_NAME -p '{\"metadata\":{\"finalizers\":null}}' --type=merge"
fi
echo ""
