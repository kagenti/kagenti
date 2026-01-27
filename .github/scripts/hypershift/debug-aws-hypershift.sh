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

# Sanitized username for default cluster suffix
SANITIZED_USER=$(echo "${USER:-local}" | tr '[:upper:]' '[:lower:]' | sed 's/[^a-z0-9]/-/g' | cut -c1-10)

# Find and load .env file - priority: 1) .env.${MANAGED_BY_TAG}, 2) legacy .env.hypershift-ci, 3) any .env.kagenti-*
MANAGED_BY_TAG="${MANAGED_BY_TAG:-kagenti-hypershift-custom}"
find_env_file() {
    if [ -f "$REPO_ROOT/.env.${MANAGED_BY_TAG}" ]; then
        echo "$REPO_ROOT/.env.${MANAGED_BY_TAG}"
    elif [ -f "$REPO_ROOT/.env.hypershift-ci" ]; then
        echo "$REPO_ROOT/.env.hypershift-ci"
    else
        ls "$REPO_ROOT"/.env.kagenti-* 2>/dev/null | head -1
    fi
}

ENV_FILE=$(find_env_file)
if [ -n "$ENV_FILE" ] && [ -f "$ENV_FILE" ]; then
    # shellcheck source=/dev/null
    source "$ENV_FILE"
fi

# MANAGED_BY_TAG may have been overridden by sourcing the .env file above

# Default cluster name
if [ -z "$CLUSTER_NAME" ]; then
    CLUSTER_NAME="${MANAGED_BY_TAG}-${SANITIZED_USER}"
fi

# Handle suffix-only input (add prefix if needed)
if [[ "$CLUSTER_NAME" != "${MANAGED_BY_TAG}-"* ]]; then
    CLUSTER_NAME="${MANAGED_BY_TAG}-${CLUSTER_NAME}"
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

# Check AWS credentials (use --no-cli-pager to avoid interactive prompts)
log_section "Verifying AWS Credentials"
if [ "$CHECK_MODE" = false ]; then
    if aws sts get-caller-identity --output table --no-cli-pager 2>/dev/null; then
        echo ""
    else
        log_error "AWS credentials not configured or invalid"
        exit 1
    fi
else
    if ! aws sts get-caller-identity --output text --no-cli-pager &>/dev/null; then
        log_error "AWS credentials not configured or invalid"
        exit 1
    fi
fi

# ============================================================================
# EC2 Resources
# ============================================================================

log_section "EC2 Instances (tagged with kubernetes.io/cluster/$CLUSTER_NAME)"
# Filter out 'terminated' state instances (they're just finalizing and will disappear)
INSTANCES=$(aws ec2 describe-instances \
    --filters "Name=tag-key,Values=kubernetes.io/cluster/$CLUSTER_NAME" \
    --query 'Reservations[*].Instances[?State.Name!=`terminated`].[InstanceId,State.Name,InstanceType,Tags[?Key==`Name`].Value|[0]]' \
    --output text 2>/dev/null || echo "")
if [ -n "$INSTANCES" ]; then
    RESOURCES_FOUND=true
    log_found "EC2 Instances:"
    [ "$CHECK_MODE" = false ] && echo "$INSTANCES" | column -t
else
    log_empty "No EC2 instances found (or only in 'terminated' state)"
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

    # Show VPC dependencies (these block VPC deletion but aren't tagged)
    if [ "$CHECK_MODE" = false ]; then
        for VPC_ID in $(echo "$VPCS" | awk '{print $1}'); do
            echo ""
            echo "  VPC Dependencies for $VPC_ID (blocking deletion):"

            # Route Tables (non-main)
            RTS=$(aws ec2 describe-route-tables \
                --filters "Name=vpc-id,Values=$VPC_ID" \
                --query 'RouteTables[?Associations[0].Main!=`true`].[RouteTableId]' \
                --output text 2>/dev/null || echo "")
            if [ -n "$RTS" ]; then
                echo "    Route Tables: $RTS"
            fi

            # VPC Endpoints
            VPCES=$(aws ec2 describe-vpc-endpoints \
                --filters "Name=vpc-id,Values=$VPC_ID" \
                --query 'VpcEndpoints[*].[VpcEndpointId,ServiceName]' \
                --output text 2>/dev/null || echo "")
            if [ -n "$VPCES" ]; then
                echo "    VPC Endpoints:"
                echo "$VPCES" | sed 's/^/      /'
            fi

            # Security Groups (non-default)
            SGS_IN_VPC=$(aws ec2 describe-security-groups \
                --filters "Name=vpc-id,Values=$VPC_ID" \
                --query 'SecurityGroups[?GroupName!=`default`].[GroupId,GroupName]' \
                --output text 2>/dev/null || echo "")
            if [ -n "$SGS_IN_VPC" ]; then
                echo "    Security Groups (non-default):"
                echo "$SGS_IN_VPC" | sed 's/^/      /'
            fi

            # Network Interfaces
            ENIS=$(aws ec2 describe-network-interfaces \
                --filters "Name=vpc-id,Values=$VPC_ID" \
                --query 'NetworkInterfaces[*].[NetworkInterfaceId,Description]' \
                --output text 2>/dev/null || echo "")
            if [ -n "$ENIS" ]; then
                echo "    Network Interfaces:"
                echo "$ENIS" | sed 's/^/      /'
            fi
        done
    fi
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
# Filter out 'deleted' state NAT gateways (they're just finalizing and will disappear)
NATS=$(aws ec2 describe-nat-gateways \
    --filter "Name=tag-key,Values=kubernetes.io/cluster/$CLUSTER_NAME" \
    --query 'NatGateways[?State!=`deleted`].[NatGatewayId,State,VpcId]' \
    --output text 2>/dev/null || echo "")
if [ -n "$NATS" ]; then
    RESOURCES_FOUND=true
    log_found "NAT Gateways:"
    [ "$CHECK_MODE" = false ] && echo "$NATS" | column -t
else
    log_empty "No NAT gateways found (or only in 'deleted' state)"
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
# OpenShift/Kubernetes Resources (on management cluster)
# ============================================================================

log_section "HostedCluster (in 'clusters' namespace)"
if command -v oc &>/dev/null && [ -n "${KUBECONFIG:-}" ] && [ -f "${KUBECONFIG:-}" ]; then
    HC=$(oc get hostedcluster "$CLUSTER_NAME" -n clusters -o jsonpath='{.metadata.name},{.status.phase},{.metadata.deletionTimestamp}' 2>/dev/null || echo "")
    if [ -n "$HC" ]; then
        RESOURCES_FOUND=true
        log_found "HostedCluster: $HC"
    else
        log_empty "No HostedCluster found"
    fi
else
    log_empty "oc not available or KUBECONFIG not set"
fi

log_section "Control Plane Namespace (clusters-$CLUSTER_NAME)"
if command -v oc &>/dev/null && [ -n "${KUBECONFIG:-}" ] && [ -f "${KUBECONFIG:-}" ]; then
    NS=$(oc get ns "clusters-$CLUSTER_NAME" -o jsonpath='{.metadata.name},{.status.phase},{.metadata.deletionTimestamp}' 2>/dev/null || echo "")
    if [ -n "$NS" ]; then
        RESOURCES_FOUND=true
        log_found "Namespace: $NS"

        if [ "$CHECK_MODE" = false ]; then
            # Show blocking resources (why namespace can't be deleted)
            echo "  Blocking resources:"

            # Count by resource type
            DEPLOY_COUNT=$(oc get deployment -n "clusters-$CLUSTER_NAME" --no-headers 2>/dev/null | wc -l | tr -d ' ')
            RS_COUNT=$(oc get replicaset -n "clusters-$CLUSTER_NAME" --no-headers 2>/dev/null | wc -l | tr -d ' ')
            POD_COUNT=$(oc get pod -n "clusters-$CLUSTER_NAME" --no-headers 2>/dev/null | wc -l | tr -d ' ')
            SECRET_COUNT=$(oc get secret -n "clusters-$CLUSTER_NAME" --no-headers 2>/dev/null | wc -l | tr -d ' ')
            CM_COUNT=$(oc get configmap -n "clusters-$CLUSTER_NAME" --no-headers 2>/dev/null | wc -l | tr -d ' ')
            SVC_COUNT=$(oc get service -n "clusters-$CLUSTER_NAME" --no-headers 2>/dev/null | wc -l | tr -d ' ')

            echo "    - Deployments: $DEPLOY_COUNT"
            echo "    - ReplicaSets: $RS_COUNT"
            echo "    - Pods: $POD_COUNT"
            echo "    - Services: $SVC_COUNT"
            echo "    - Secrets: $SECRET_COUNT"
            echo "    - ConfigMaps: $CM_COUNT"

            # Show resources with finalizers (these block deletion)
            FINALIZED=$(oc get all -n "clusters-$CLUSTER_NAME" -o json 2>/dev/null | jq -r '.items[] | select(.metadata.finalizers != null and (.metadata.finalizers | length) > 0) | "\(.kind)/\(.metadata.name): \(.metadata.finalizers | join(", "))"' 2>/dev/null | head -10 || echo "")
            if [ -n "$FINALIZED" ]; then
                echo "  Resources with finalizers (blocking deletion):"
                echo "$FINALIZED" | sed 's/^/    /'
            fi

            # Show unhealthy pods
            CRASHLOOP=$(oc get pods -n "clusters-$CLUSTER_NAME" --field-selector=status.phase!=Running,status.phase!=Succeeded -o custom-columns='NAME:.metadata.name,STATUS:.status.phase,RESTARTS:.status.containerStatuses[0].restartCount' 2>/dev/null | grep -v "^NAME" | head -5 || echo "")
            if [ -n "$CRASHLOOP" ]; then
                echo "  Unhealthy pods:"
                echo "$CRASHLOOP" | sed 's/^/    /'
            fi
        fi
    else
        log_empty "No control plane namespace found"
    fi
else
    log_empty "oc not available or KUBECONFIG not set"
fi

log_section "NodePools (in 'clusters' namespace)"
if command -v oc &>/dev/null && [ -n "${KUBECONFIG:-}" ] && [ -f "${KUBECONFIG:-}" ]; then
    NP=$(oc get nodepools -n clusters -l "hypershift.openshift.io/hosted-control-plane=$CLUSTER_NAME" -o jsonpath='{range .items[*]}{.metadata.name},{.status.phase}{"\n"}{end}' 2>/dev/null || echo "")
    if [ -n "$NP" ]; then
        RESOURCES_FOUND=true
        log_found "NodePools:"
        [ "$CHECK_MODE" = false ] && echo "$NP" | sed 's/^/  /'
    else
        log_empty "No NodePools found"
    fi
else
    log_empty "oc not available or KUBECONFIG not set"
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
    echo -e "${RED}Orphaned resources still exist!${NC}"
    echo "These resources may be blocking cluster deletion."
    echo ""
    echo "To clean up:"
    echo "  # If HostedCluster still exists with finalizer:"
    echo "  oc patch hostedcluster -n clusters $CLUSTER_NAME -p '{\"metadata\":{\"finalizers\":null}}' --type=merge"
    echo ""
    echo "  # If control plane namespace is stuck:"
    echo "  oc delete ns clusters-$CLUSTER_NAME --wait=false"
    echo "  oc patch ns clusters-$CLUSTER_NAME -p '{\"metadata\":{\"finalizers\":null}}' --type=merge"
    echo ""
    echo "  # For AWS resources, delete in order:"
    echo "  # instances, NATs, subnets, IGWs, VPCs, roles, S3, OIDC"
else
    echo -e "${GREEN}All resources have been cleaned up.${NC}"
    echo "No orphaned AWS or OpenShift resources found."
fi
echo ""
