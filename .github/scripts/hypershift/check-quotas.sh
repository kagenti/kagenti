#!/usr/bin/env bash
#
# Check AWS Service Quotas and Current Usage
#
# Shows current resource usage vs quota limits to help plan cluster capacity.
# Useful for understanding how many more HyperShift clusters can be created.
#
# USAGE:
#   ./.github/scripts/hypershift/check-quotas.sh
#   ./.github/scripts/hypershift/check-quotas.sh --request-increases
#
# OPTIONS:
#   --request-increases  Request quota increases for quotas below recommended levels
#
# REQUIREMENTS:
#   - AWS CLI configured with appropriate permissions
#   - aws sts get-caller-identity must work
#

set -euo pipefail

# Parse arguments
REQUEST_INCREASES=false
for arg in "$@"; do
    case $arg in
        --request-increases)
            REQUEST_INCREASES=true
            ;;
    esac
done

# Disable AWS CLI pager
export AWS_PAGER=""

# Colors (use $'...' syntax for proper escape sequence interpretation)
RED=$'\033[0;31m'
GREEN=$'\033[0;32m'
YELLOW=$'\033[1;33m'
BLUE=$'\033[0;34m'
CYAN=$'\033[0;36m'
NC=$'\033[0m'

log_info() { echo -e "${BLUE}→${NC} $1"; }
log_success() { echo -e "${GREEN}✓${NC} $1"; }
log_warn() { echo -e "${YELLOW}⚠${NC} $1"; }
log_error() { echo -e "${RED}✗${NC} $1"; }

echo ""
echo "╔════════════════════════════════════════════════════════════════╗"
echo "║         AWS Service Quotas and Usage Check                     ║"
echo "╚════════════════════════════════════════════════════════════════╝"
echo ""

# Verify AWS credentials
if ! aws sts get-caller-identity &>/dev/null; then
    log_error "AWS credentials not configured. Run: aws configure"
    exit 1
fi

AWS_REGION="${AWS_REGION:-us-east-1}"
log_info "Region: $AWS_REGION"
echo ""

# Track warnings for quota increase requests
QUOTA_WARNINGS=0
QUOTAS_TO_UPDATE=()

# Function to get quota value
get_quota() {
    local service_code="$1"
    local quota_code="$2"

    local value
    value=$(aws service-quotas get-service-quota \
        --service-code "$service_code" \
        --quota-code "$quota_code" \
        --region "$AWS_REGION" \
        --query 'Quota.Value' \
        --output text 2>/dev/null | head -1 || echo "0")

    # Sanitize: remove decimals, keep only first line, ensure numeric
    value="${value%.*}"
    value="${value%%$'\n'*}"
    if [ "$value" = "None" ] || [ -z "$value" ] || ! [[ "$value" =~ ^[0-9]+$ ]]; then
        echo "0"
    else
        echo "$value"
    fi
}

# Function to display quota line with usage
show_quota_line() {
    local name="$1"
    local used="$2"
    local quota="$3"
    local recommended="$4"
    local service_code="${5:-}"
    local quota_code="${6:-}"

    local remaining=$((quota - used))
    local percent=0
    if [ "$quota" -gt 0 ]; then
        percent=$((used * 100 / quota))
    fi

    # Color based on usage
    local color="$GREEN"
    if [ "$percent" -ge 80 ]; then
        color="$RED"
    elif [ "$percent" -ge 60 ]; then
        color="$YELLOW"
    fi

    # Check if below recommended
    local rec_warning=""
    if [ "$quota" -lt "$recommended" ]; then
        rec_warning=" ${YELLOW}(rec: $recommended)${NC}"
        QUOTA_WARNINGS=$((QUOTA_WARNINGS + 1))
        if [ -n "$service_code" ] && [ -n "$quota_code" ]; then
            QUOTAS_TO_UPDATE+=("$service_code|$quota_code|$name|$recommended")
        fi
    fi

    printf "  %-45s %s%3d%s / %3d  (free: %3d)%s\n" "$name" "$color" "$used" "$NC" "$quota" "$remaining" "$rec_warning"
}

# =============================================================================
# VPC Resources
# =============================================================================
echo -e "${CYAN}VPC Resources:${NC}"

# Count VPCs
VPC_COUNT=$(aws ec2 describe-vpcs --region "$AWS_REGION" --query 'Vpcs | length(@)' --output text 2>/dev/null || echo "0")
VPC_QUOTA=$(get_quota "vpc" "L-F678F1CE")
show_quota_line "VPCs per region" "$VPC_COUNT" "$VPC_QUOTA" 5 "vpc" "L-F678F1CE"

# Count Internet Gateways
IGW_COUNT=$(aws ec2 describe-internet-gateways --region "$AWS_REGION" --query 'InternetGateways | length(@)' --output text 2>/dev/null || echo "0")
IGW_QUOTA=$(get_quota "vpc" "L-A4707A72")
show_quota_line "Internet gateways per region" "$IGW_COUNT" "$IGW_QUOTA" 5 "vpc" "L-A4707A72"

# Count NAT Gateways
NAT_COUNT=$(aws ec2 describe-nat-gateways --region "$AWS_REGION" --filter "Name=state,Values=available,pending" --query 'NatGateways | length(@)' --output text 2>/dev/null || echo "0")
NAT_QUOTA=$(get_quota "vpc" "L-FE5A380F")
show_quota_line "NAT gateways (active)" "$NAT_COUNT" "$NAT_QUOTA" 15 "vpc" "L-FE5A380F"

# Count Elastic IPs
EIP_COUNT=$(aws ec2 describe-addresses --region "$AWS_REGION" --query 'Addresses | length(@)' --output text 2>/dev/null || echo "0")
EIP_QUOTA=$(get_quota "ec2" "L-0263D0A3")
show_quota_line "Elastic IPs" "$EIP_COUNT" "$EIP_QUOTA" 15 "ec2" "L-0263D0A3"

echo ""

# =============================================================================
# EC2 Resources
# =============================================================================
echo -e "${CYAN}EC2 Resources:${NC}"

# Count running instances
INSTANCE_COUNT=$(aws ec2 describe-instances --region "$AWS_REGION" \
    --filters "Name=instance-state-name,Values=running,pending" \
    --query 'Reservations[*].Instances | length(@)' --output text 2>/dev/null || echo "0")
# On-Demand vCPU quota (this is vCPUs, not instances)
VCPU_QUOTA=$(get_quota "ec2" "L-1216C47A")
# Show as instance count (quota is in vCPUs, divide by 4 for m5.xlarge)
show_quota_line "Running instances (estimated)" "$INSTANCE_COUNT" "$((VCPU_QUOTA / 4))" 10

# Count Security Groups
SG_COUNT=$(aws ec2 describe-security-groups --region "$AWS_REGION" --query 'SecurityGroups | length(@)' --output text 2>/dev/null || echo "0")
SG_QUOTA=$(get_quota "ec2" "L-0EA8095F")
show_quota_line "Security groups (all VPCs)" "$SG_COUNT" "$SG_QUOTA" 50 "ec2" "L-0EA8095F"

# Count Launch Templates
LT_COUNT=$(aws ec2 describe-launch-templates --region "$AWS_REGION" --query 'LaunchTemplates | length(@)' --output text 2>/dev/null || echo "0")
LT_QUOTA=$(get_quota "ec2" "L-74FC7D96")
show_quota_line "Launch templates" "$LT_COUNT" "$LT_QUOTA" 10 "ec2" "L-74FC7D96"

echo ""

# =============================================================================
# ELB Resources
# =============================================================================
echo -e "${CYAN}Load Balancer Resources:${NC}"

# Count Network Load Balancers
NLB_COUNT=$(aws elbv2 describe-load-balancers --region "$AWS_REGION" \
    --query "LoadBalancers[?Type=='network'] | length(@)" --output text 2>/dev/null || echo "0")
NLB_QUOTA=$(get_quota "elasticloadbalancing" "L-69A177A2")
show_quota_line "Network Load Balancers" "$NLB_COUNT" "$NLB_QUOTA" 10 "elasticloadbalancing" "L-69A177A2"

# Count Target Groups
TG_COUNT=$(aws elbv2 describe-target-groups --region "$AWS_REGION" --query 'TargetGroups | length(@)' --output text 2>/dev/null || echo "0")
TG_QUOTA=$(get_quota "elasticloadbalancing" "L-B6DF7632")
show_quota_line "Target groups" "$TG_COUNT" "$TG_QUOTA" 30 "elasticloadbalancing" "L-B6DF7632"

echo ""

# =============================================================================
# S3 Resources
# =============================================================================
echo -e "${CYAN}S3 Resources:${NC}"

# Count S3 buckets (global, not regional)
S3_COUNT=$(aws s3api list-buckets --query 'Buckets | length(@)' --output text 2>/dev/null || echo "0")
S3_QUOTA=$(get_quota "s3" "L-DC2B2D3D")
show_quota_line "S3 buckets (account-wide)" "$S3_COUNT" "$S3_QUOTA" 10 "s3" "L-DC2B2D3D"

echo ""

# =============================================================================
# IAM Resources
# =============================================================================
echo -e "${CYAN}IAM Resources:${NC}"

# Count IAM Roles
ROLE_COUNT=$(aws iam list-roles --query 'Roles | length(@)' --output text 2>/dev/null || echo "0")
ROLE_QUOTA=$(get_quota "iam" "L-FE177D64")
show_quota_line "IAM roles (account-wide)" "$ROLE_COUNT" "$ROLE_QUOTA" 50 "iam" "L-FE177D64"

# Count Instance Profiles
IP_COUNT=$(aws iam list-instance-profiles --query 'InstanceProfiles | length(@)' --output text 2>/dev/null || echo "0")
IP_QUOTA=$(get_quota "iam" "L-6E65F664")
show_quota_line "Instance profiles (account-wide)" "$IP_COUNT" "$IP_QUOTA" 20 "iam" "L-6E65F664"

echo ""

# =============================================================================
# Route53 Resources
# =============================================================================
echo -e "${CYAN}Route53 Resources:${NC}"

# Count Hosted Zones
HZ_COUNT=$(aws route53 list-hosted-zones --query 'HostedZones | length(@)' --output text 2>/dev/null || echo "0")
HZ_QUOTA=$(get_quota "route53" "L-4EA4796A")
show_quota_line "Hosted zones (account-wide)" "$HZ_COUNT" "$HZ_QUOTA" 10 "route53" "L-4EA4796A"

echo ""

# =============================================================================
# Summary
# =============================================================================
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

if [ "$QUOTA_WARNINGS" -gt 0 ]; then
    log_warn "Found $QUOTA_WARNINGS quota(s) below recommended levels"

    if [ "$REQUEST_INCREASES" = true ]; then
        echo ""
        log_info "Requesting quota increases..."
        for quota_entry in "${QUOTAS_TO_UPDATE[@]}"; do
            IFS='|' read -r svc_code q_code q_name desired <<< "$quota_entry"
            log_info "Requesting $q_name increase to $desired..."

            request_id=$(aws service-quotas request-service-quota-increase \
                --service-code "$svc_code" \
                --quota-code "$q_code" \
                --desired-value "$desired" \
                --region "$AWS_REGION" \
                --query 'RequestedQuota.Id' \
                --output text 2>/dev/null || echo "FAILED")

            if [ "$request_id" != "FAILED" ] && [ -n "$request_id" ]; then
                log_success "  Request submitted: $request_id"
            else
                log_warn "  Failed (may already have pending request)"
            fi
        done
        echo ""
        log_info "Quota increases typically take 1-3 business days for approval"
    else
        echo ""
        log_info "To request quota increases: $0 --request-increases"
    fi
else
    log_success "All quotas are at or above recommended levels"
fi

echo ""
echo "Legend: ${GREEN}green${NC} = <60% used, ${YELLOW}yellow${NC} = 60-80% used, ${RED}red${NC} = >80% used"
echo ""
