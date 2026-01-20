#!/usr/bin/env bash
#
# Setup HyperShift CI Credentials
#
# WHY THIS SCRIPT EXISTS:
#   HyperShift allows running OpenShift clusters with hosted control planes,
#   where worker nodes run in AWS but control plane runs on a management cluster.
#   This enables fast, cost-effective ephemeral clusters for CI/CD testing.
#
#   To provision these clusters, we need:
#   - AWS credentials to create worker node infrastructure (EC2, ELB, Route53)
#   - OpenShift service account to manage HyperShift resources on the mgmt cluster
#   - Pull secret to download OpenShift container images
#   - Base domain for cluster DNS
#
#   This script creates all these credentials in one idempotent operation,
#   with least-privilege permissions for both CI and debugging use cases.
#
# IDEMPOTENT: Safe to run multiple times - updates existing resources.
#
# REQUIREMENTS:
#   - Bash 3.2+, AWS CLI v2, OpenShift CLI (oc), jq
#
# PREREQUISITES:
#   - Logged into AWS: aws sts get-caller-identity
#   - Logged into OpenShift (HyperShift management cluster): oc whoami
#
# CONFIGURATION:
#   MANAGED_BY_TAG   - Primary identifier for all resources (default: kagenti-hypershift-ci)
#                      Used for: naming prefix, IAM ARN scoping, resource tagging
#   AWS_REGION       - AWS region (auto-detected from cluster, fallback: us-east-1)
#
# NAMING & SCOPING STRATEGY:
#   This script uses ONE identifier for everything: MANAGED_BY_TAG
#
#   1. RESOURCE NAMING:
#      - All AWS/OpenShift resources are prefixed with MANAGED_BY_TAG
#      - Example: IAM user "kagenti-hypershift-ci", role "kagenti-hypershift-ci-role"
#
#   2. IAM ARN SCOPING:
#      - Policies restrict operations to resources matching "${MANAGED_BY_TAG}-*"
#      - Example: S3 buckets, IAM roles must match "kagenti-hypershift-ci-*"
#
#   3. RESOURCE TAGGING:
#      - All created resources get tag: ManagedBy=${MANAGED_BY_TAG}
#      - Applied via: --additional-tags ManagedBy=${MANAGED_BY_TAG}
#      - Enables tag-based IAM conditions for EC2/ELB
#
#   CRITICAL: Cluster names MUST be prefixed with MANAGED_BY_TAG!
#      - create-cluster.sh auto-generates: ${MANAGED_BY_TAG}-<random>
#      - Or provide suffix: CLUSTER_SUFFIX=mytest → ${MANAGED_BY_TAG}-mytest
#
# CREATES:
#   AWS:
#     ${MANAGED_BY_TAG}                        - IAM user with scoped permissions
#     ${MANAGED_BY_TAG}-debug                  - IAM user with read-only access
#     ${MANAGED_BY_TAG}-role                   - IAM role for hcp CLI (--role-arn)
#   OpenShift:
#     ${MANAGED_BY_TAG} namespace              - Namespace for CI resources
#     ${MANAGED_BY_TAG} SA                     - Service account for HyperShift
#   Local:
#     .env.hypershift-ci                       - All credentials in sourceable format
#
# USAGE:
#   ./.github/scripts/hypershift/setup-hypershift-ci-credentials.sh
#   ./.github/scripts/hypershift/setup-hypershift-ci-credentials.sh --rotate
#   MANAGED_BY_TAG=myproject-ci ./.github/scripts/hypershift/setup-hypershift-ci-credentials.sh
#
# OPTIONS:
#   --rotate    Delete existing access keys and .env file, then create fresh credentials
#

set -euo pipefail

# Parse arguments
ROTATE_KEYS=false
for arg in "$@"; do
    case $arg in
        --rotate)
            ROTATE_KEYS=true
            ;;
    esac
done

# Disable AWS CLI pager for non-interactive use
export AWS_PAGER=""

# Handle --rotate: delete .env file early so we start fresh
if [ "$ROTATE_KEYS" = true ]; then
    ENV_FILE=".env.hypershift-ci"
    if [ -f "$ENV_FILE" ]; then
        echo "Rotating credentials: removing existing $ENV_FILE"
        rm -f "$ENV_FILE"
    fi
fi

# ============================================================================
# UTILITIES (defined early so they can be used throughout the script)
# ============================================================================

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log_info() { echo -e "${BLUE}→${NC} $1"; }
log_success() { echo -e "${GREEN}✓${NC} $1"; }
log_warn() { echo -e "${YELLOW}⚠${NC} $1"; }
log_error() { echo -e "${RED}✗${NC} $1"; exit 1; }

# Cross-platform base64 encode (no line wrapping)
base64_encode() {
    if [[ "$OSTYPE" == "darwin"* ]]; then
        base64
    else
        base64 -w0
    fi
}

# Cross-platform base64 decode
base64_decode() {
    if [[ "$OSTYPE" == "darwin"* ]]; then
        base64 -D
    else
        base64 -d
    fi
}

# ============================================================================
# CONFIGURATION
# ============================================================================

# Primary identifier - used for naming, IAM scoping, and tagging
# Format: lowercase alphanumeric with hyphens, 5-30 chars
MANAGED_BY_TAG="${MANAGED_BY_TAG:-kagenti-hypershift-ci}"

# Validate (must be lowercase alphanumeric, can include hyphens, 5-30 chars)
if ! [[ "$MANAGED_BY_TAG" =~ ^[a-z][a-z0-9-]{4,29}$ ]]; then
    echo "Error: MANAGED_BY_TAG must be 5-30 chars, start with letter, contain only lowercase letters, numbers, hyphens" >&2
    exit 1
fi

# Generate policy name from MANAGED_BY_TAG (capitalize, remove hyphens)
# e.g., "kagenti-hypershift-ci" -> "KagentiHypershiftCi"
POLICY_NAME_BASE=$(echo "$MANAGED_BY_TAG" | sed -E 's/(^|-)([a-z])/\U\2/g')

# Derived names - ALL use MANAGED_BY_TAG as prefix
IAM_CI_USER="${MANAGED_BY_TAG}"
IAM_CI_POLICY="${POLICY_NAME_BASE}Policy"
IAM_DEBUG_USER="${MANAGED_BY_TAG}-debug"
IAM_DEBUG_POLICY="${POLICY_NAME_BASE}DebugPolicy"
# IAM Role for hcp CLI to pass to hosted control plane
IAM_HCP_ROLE="${MANAGED_BY_TAG}-role"
IAM_HCP_ROLE_POLICY="${POLICY_NAME_BASE}RolePolicy"
SA_NAMESPACE="${MANAGED_BY_TAG}"
SA_NAME="${MANAGED_BY_TAG}"
CLUSTER_ROLE_NAME="${MANAGED_BY_TAG}-k8s-role"
CLUSTER_ROLE_BINDING_NAME="${MANAGED_BY_TAG}-k8s-binding"

# AWS Region - auto-detect from cluster infrastructure, fallback to us-east-1
if [ -z "${AWS_REGION:-}" ]; then
    DETECTED_REGION=$(oc get infrastructure cluster -o jsonpath='{.status.platformStatus.aws.region}' 2>/dev/null || echo "")
    if [ -n "$DETECTED_REGION" ]; then
        AWS_REGION="$DETECTED_REGION"
    else
        AWS_REGION="us-east-1"
    fi
fi

# Shared OIDC S3 bucket - auto-detect from existing hosted clusters
# HyperShift management clusters often use a shared bucket for OIDC discovery
# This bucket name does NOT follow our prefix pattern, so we need explicit access
OIDC_S3_BUCKET="${OIDC_S3_BUCKET:-}"
if [ -z "$OIDC_S3_BUCKET" ]; then
    # Try to detect from existing hosted clusters
    EXISTING_ISSUER=$(oc get hostedclusters -A -o jsonpath='{.items[0].spec.issuerURL}' 2>/dev/null || echo "")
    if [ -n "$EXISTING_ISSUER" ]; then
        # Extract bucket name from URL like https://hyperocto.s3.us-east-1.amazonaws.com/...
        OIDC_S3_BUCKET=$(echo "$EXISTING_ISSUER" | sed -E 's|https://([^.]+)\.s3\.[^.]+\.amazonaws\.com/.*|\1|')
        if [ -n "$OIDC_S3_BUCKET" ] && [ "$OIDC_S3_BUCKET" != "$EXISTING_ISSUER" ]; then
            log_info "Auto-detected shared OIDC bucket: $OIDC_S3_BUCKET"
        else
            OIDC_S3_BUCKET=""
        fi
    fi
fi

echo ""
echo "╔════════════════════════════════════════════════════════════════╗"
echo "║         HyperShift CI Credentials Setup (Idempotent)          ║"
echo "╚════════════════════════════════════════════════════════════════╝"
echo ""
echo "Managed by tag: ${MANAGED_BY_TAG}"
echo ""

# ============================================================================
# PREREQUISITES CHECK (delegate to preflight-check.sh)
# ============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

log_info "Running pre-flight checks..."
if ! "$SCRIPT_DIR/preflight-check.sh"; then
    log_error "Pre-flight checks failed. Please fix the issues above."
fi
log_success "All pre-flight checks passed"

# Extract values needed for setup (preflight already validated these work)
AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
AWS_USER_ARN=$(aws sts get-caller-identity --query Arn --output text)

# Log the AWS region being used
if [ -n "${DETECTED_REGION:-}" ]; then
    log_success "AWS Region: $AWS_REGION (auto-detected from cluster)"
else
    log_info "AWS Region: $AWS_REGION (default)"
fi

echo ""

# ============================================================================
# 1. AWS IAM USERS (Idempotent)
# ============================================================================

log_info "Setting up AWS IAM users..."

# AWS IAM Policy for CI - HyperShift cluster lifecycle
#
# RESOURCE SCOPING STRATEGY:
#   We use multiple techniques to limit what CI can touch:
#
#   1. TAG CONDITIONS (EC2, ELB):
#      - Require "ManagedBy=${MANAGED_BY_TAG}" tag on created resources
#      - Only allow operations on resources with matching tags
#      - IMPORTANT: Provisioning scripts must add this tag to all resources!
#
#   2. ARN PATTERNS (S3, IAM):
#      - S3 buckets must start with "${MANAGED_BY_TAG}-"
#      - IAM roles/profiles must start with "${MANAGED_BY_TAG}-"
#      - IMPORTANT: Cluster names must start with ${MANAGED_BY_TAG}- prefix!
#
#   3. READ-ONLY WILDCARDS:
#      - Describe* actions use "*" (read-only, no risk)
#
#   4. STILL BROAD (documented):
#      - Route53: All hosted zones (could be tightened to specific zone ID)
#      - OIDC providers: Can't be scoped by name pattern
#
# NAMING CONVENTION FOR CLUSTERS:
#   Use: ${MANAGED_BY_TAG}-<suffix>
#   Example: kagenti-hypershift-ci-pr123, kagenti-hypershift-ci-local
#
# The policy is generated dynamically to include MANAGED_BY_TAG.
#
generate_ci_policy() {
    cat <<POLICY
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "EC2DescribeReadOnly",
      "Effect": "Allow",
      "Action": [
        "ec2:DescribeInstances",
        "ec2:DescribeInstanceStatus",
        "ec2:DescribeSecurityGroups",
        "ec2:DescribeVpcs",
        "ec2:DescribeSubnets",
        "ec2:DescribeAvailabilityZones",
        "ec2:DescribeNetworkInterfaces",
        "ec2:DescribeImages",
        "ec2:DescribeTags"
      ],
      "Resource": "*"
    },
    {
      "Sid": "EC2CreateWithTag",
      "Effect": "Allow",
      "Action": [
        "ec2:RunInstances",
        "ec2:CreateSecurityGroup",
        "ec2:CreateNetworkInterface",
        "ec2:CreateTags"
      ],
      "Resource": "*",
      "Condition": {
        "StringEquals": {
          "aws:RequestTag/ManagedBy": "${MANAGED_BY_TAG}"
        }
      }
    },
    {
      "Sid": "EC2ManageTaggedResources",
      "Effect": "Allow",
      "Action": [
        "ec2:TerminateInstances",
        "ec2:DeleteSecurityGroup",
        "ec2:AuthorizeSecurityGroupIngress",
        "ec2:AuthorizeSecurityGroupEgress",
        "ec2:RevokeSecurityGroupIngress",
        "ec2:RevokeSecurityGroupEgress",
        "ec2:DeleteNetworkInterface",
        "ec2:ModifyNetworkInterfaceAttribute",
        "ec2:DeleteTags"
      ],
      "Resource": "*",
      "Condition": {
        "StringEquals": {
          "aws:ResourceTag/ManagedBy": "${MANAGED_BY_TAG}"
        }
      }
    },
    {
      "Sid": "ELBDescribeReadOnly",
      "Effect": "Allow",
      "Action": [
        "elasticloadbalancing:DescribeLoadBalancers",
        "elasticloadbalancing:DescribeLoadBalancerAttributes",
        "elasticloadbalancing:DescribeTargetGroups",
        "elasticloadbalancing:DescribeListeners",
        "elasticloadbalancing:DescribeTags"
      ],
      "Resource": "*"
    },
    {
      "Sid": "ELBCreateWithTag",
      "Effect": "Allow",
      "Action": [
        "elasticloadbalancing:CreateLoadBalancer",
        "elasticloadbalancing:CreateTargetGroup",
        "elasticloadbalancing:AddTags"
      ],
      "Resource": "*",
      "Condition": {
        "StringEquals": {
          "aws:RequestTag/ManagedBy": "${MANAGED_BY_TAG}"
        }
      }
    },
    {
      "Sid": "ELBManageTaggedResources",
      "Effect": "Allow",
      "Action": [
        "elasticloadbalancing:DeleteLoadBalancer",
        "elasticloadbalancing:ModifyLoadBalancerAttributes",
        "elasticloadbalancing:DeleteTargetGroup",
        "elasticloadbalancing:RegisterTargets",
        "elasticloadbalancing:DeregisterTargets",
        "elasticloadbalancing:CreateListener",
        "elasticloadbalancing:DeleteListener"
      ],
      "Resource": "*",
      "Condition": {
        "StringEquals": {
          "aws:ResourceTag/ManagedBy": "${MANAGED_BY_TAG}"
        }
      }
    },
    {
      "Sid": "Route53ReadOnly",
      "Effect": "Allow",
      "Action": [
        "route53:GetHostedZone",
        "route53:ListHostedZones",
        "route53:ListHostedZonesByName",
        "route53:ListResourceRecordSets"
      ],
      "Resource": "*"
    },
    {
      "Sid": "Route53ChangeRecords",
      "Effect": "Allow",
      "Action": [
        "route53:ChangeResourceRecordSets"
      ],
      "Resource": "arn:aws:route53:::hostedzone/*"
    },
    {
      "Sid": "S3PrefixedBuckets",
      "Effect": "Allow",
      "Action": [
        "s3:CreateBucket",
        "s3:DeleteBucket",
        "s3:PutObject",
        "s3:GetObject",
        "s3:DeleteObject",
        "s3:ListBucket",
        "s3:PutBucketPolicy",
        "s3:GetBucketPolicy",
        "s3:GetBucketLocation",
        "s3:PutBucketTagging",
        "s3:PutBucketPublicAccessBlock",
        "s3:GetBucketPublicAccessBlock"
      ],
      "Resource": [
        "arn:aws:s3:::${MANAGED_BY_TAG}-*",
        "arn:aws:s3:::${MANAGED_BY_TAG}-*/*"
      ]
    },
$(if [ -n "$OIDC_S3_BUCKET" ]; then cat <<S3OIDC
    {
      "Sid": "S3SharedOIDCBucket",
      "Effect": "Allow",
      "Action": [
        "s3:PutObject",
        "s3:GetObject",
        "s3:DeleteObject",
        "s3:ListBucket",
        "s3:GetBucketLocation"
      ],
      "Resource": [
        "arn:aws:s3:::${OIDC_S3_BUCKET}",
        "arn:aws:s3:::${OIDC_S3_BUCKET}/${MANAGED_BY_TAG}-*"
      ]
    },
S3OIDC
fi)
    {
      "Sid": "IAMReadOnly",
      "Effect": "Allow",
      "Action": [
        "iam:GetRole",
        "iam:GetUser",
        "iam:ListRoles",
        "iam:GetInstanceProfile",
        "iam:ListInstanceProfiles",
        "iam:ListInstanceProfilesForRole",
        "iam:GetRolePolicy",
        "iam:ListRolePolicies",
        "iam:ListAttachedRolePolicies",
        "iam:ListOpenIDConnectProviders"
      ],
      "Resource": "*"
    },
    {
      "Sid": "IAMPrefixedRoles",
      "Effect": "Allow",
      "Action": [
        "iam:CreateRole",
        "iam:DeleteRole",
        "iam:TagRole",
        "iam:AttachRolePolicy",
        "iam:DetachRolePolicy",
        "iam:PutRolePolicy",
        "iam:DeleteRolePolicy",
        "iam:PassRole"
      ],
      "Resource": "arn:aws:iam::*:role/${MANAGED_BY_TAG}-*"
    },
    {
      "Sid": "IAMPrefixedInstanceProfiles",
      "Effect": "Allow",
      "Action": [
        "iam:CreateInstanceProfile",
        "iam:DeleteInstanceProfile",
        "iam:TagInstanceProfile",
        "iam:AddRoleToInstanceProfile",
        "iam:RemoveRoleFromInstanceProfile"
      ],
      "Resource": "arn:aws:iam::*:instance-profile/${MANAGED_BY_TAG}-*"
    },
    {
      "Sid": "IAMOIDCProviders",
      "Effect": "Allow",
      "Action": [
        "iam:CreateOpenIDConnectProvider",
        "iam:DeleteOpenIDConnectProvider",
        "iam:GetOpenIDConnectProvider",
        "iam:TagOpenIDConnectProvider"
      ],
      "Resource": "arn:aws:iam::*:oidc-provider/*"
    },
    {
      "Sid": "STSIdentity",
      "Effect": "Allow",
      "Action": [
        "sts:GetCallerIdentity"
      ],
      "Resource": "*"
    },
    {
      "Sid": "STSAssumeRolePrefixed",
      "Effect": "Allow",
      "Action": [
        "sts:AssumeRole"
      ],
      "Resource": "arn:aws:iam::*:role/${MANAGED_BY_TAG}-*"
    }
  ]
}
POLICY
}

IAM_CI_POLICY_DOC=$(generate_ci_policy)

# Read-only policy for debugging
IAM_DEBUG_POLICY_DOC=$(cat <<'POLICY'
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "EC2ReadOnly",
      "Effect": "Allow",
      "Action": [
        "ec2:Describe*",
        "ec2:Get*"
      ],
      "Resource": "*"
    },
    {
      "Sid": "ELBReadOnly",
      "Effect": "Allow",
      "Action": [
        "elasticloadbalancing:Describe*"
      ],
      "Resource": "*"
    },
    {
      "Sid": "Route53ReadOnly",
      "Effect": "Allow",
      "Action": [
        "route53:Get*",
        "route53:List*"
      ],
      "Resource": "*"
    },
    {
      "Sid": "S3ReadOnly",
      "Effect": "Allow",
      "Action": [
        "s3:Get*",
        "s3:List*"
      ],
      "Resource": "*"
    },
    {
      "Sid": "IAMReadOnly",
      "Effect": "Allow",
      "Action": [
        "iam:Get*",
        "iam:List*"
      ],
      "Resource": "*"
    },
    {
      "Sid": "STSReadOnly",
      "Effect": "Allow",
      "Action": [
        "sts:GetCallerIdentity"
      ],
      "Resource": "*"
    },
    {
      "Sid": "CloudWatchReadOnly",
      "Effect": "Allow",
      "Action": [
        "cloudwatch:Describe*",
        "cloudwatch:Get*",
        "cloudwatch:List*",
        "logs:Describe*",
        "logs:Get*",
        "logs:FilterLogEvents"
      ],
      "Resource": "*"
    }
  ]
}
POLICY
)

# Function to create/update IAM user with policy (idempotent)
setup_iam_user() {
    local USER_NAME=$1
    local POLICY_NAME=$2
    local POLICY_DOC=$3
    local USER_PURPOSE=$4

    log_info "Setting up IAM user '$USER_NAME' ($USER_PURPOSE)..."

    # Create user if not exists
    if aws iam get-user --user-name "$USER_NAME" &>/dev/null; then
        log_success "  User exists"
    else
        aws iam create-user --user-name "$USER_NAME" --tags Key=Purpose,Value="$USER_PURPOSE" Key=ManagedBy,Value="${MANAGED_BY_TAG}"
        log_success "  Created user"
    fi

    # Create or update policy
    local POLICY_ARN="arn:aws:iam::${AWS_ACCOUNT_ID}:policy/${POLICY_NAME}"
    if aws iam get-policy --policy-arn "$POLICY_ARN" &>/dev/null; then
        # Delete ALL non-default versions to make room for new one
        local OLD_VERSIONS
        OLD_VERSIONS=$(aws iam list-policy-versions --policy-arn "$POLICY_ARN" \
            --query "Versions[?IsDefaultVersion==\`false\`].VersionId" --output text)
        for ver in $OLD_VERSIONS; do
            aws iam delete-policy-version --policy-arn "$POLICY_ARN" --version-id "$ver" 2>/dev/null || true
        done
        # Create new version
        aws iam create-policy-version \
            --policy-arn "$POLICY_ARN" \
            --policy-document "$POLICY_DOC" \
            --set-as-default >/dev/null
        log_success "  Updated policy"
    else
        aws iam create-policy \
            --policy-name "$POLICY_NAME" \
            --policy-document "$POLICY_DOC" \
            --tags Key=Purpose,Value="$USER_PURPOSE" Key=ManagedBy,Value="${MANAGED_BY_TAG}" >/dev/null
        log_success "  Created policy"
    fi

    # Attach policy (idempotent - attach-user-policy doesn't error if already attached)
    aws iam attach-user-policy --user-name "$USER_NAME" --policy-arn "$POLICY_ARN"
    log_success "  Policy attached"
}

# Function to get or create access keys
# Exports to CI_NEW_* variables to avoid overriding admin AWS credentials
setup_access_keys() {
    local USER_NAME=$1
    local KEY_VAR_NAME=$2
    local SECRET_VAR_NAME=$3

    log_info "Setting up access keys for '$USER_NAME'..."

    local EXISTING_KEYS
    EXISTING_KEYS=$(aws iam list-access-keys --user-name "$USER_NAME" --query 'AccessKeyMetadata[*].AccessKeyId' --output text)

    if [ -n "$EXISTING_KEYS" ]; then
        if [ "$ROTATE_KEYS" = true ]; then
            log_info "  Rotating: deleting existing access keys..."
            for key_id in $EXISTING_KEYS; do
                aws iam delete-access-key --user-name "$USER_NAME" --access-key-id "$key_id"
                log_success "  Deleted key: $key_id"
            done
            EXISTING_KEYS=""
        else
            log_warn "  Access keys already exist: $EXISTING_KEYS"
            log_warn "  Keeping existing keys (will preserve from .env.hypershift-ci)"
            log_warn "  To rotate: $0 --rotate"
            return 1
        fi
    fi

    # Create new keys (either no keys existed, or we just deleted them)
    if [ -z "$EXISTING_KEYS" ]; then
        local KEY_OUTPUT
        KEY_OUTPUT=$(aws iam create-access-key --user-name "$USER_NAME")
        # Export to CI_NEW_* to avoid overriding admin credentials
        export "CI_NEW_${KEY_VAR_NAME}=$(echo "$KEY_OUTPUT" | jq -r '.AccessKey.AccessKeyId')"
        export "CI_NEW_${SECRET_VAR_NAME}=$(echo "$KEY_OUTPUT" | jq -r '.AccessKey.SecretAccessKey')"
        log_success "  Created new access keys"
        return 0
    fi
}

# Setup both users
setup_iam_user "$IAM_CI_USER" "$IAM_CI_POLICY" "$IAM_CI_POLICY_DOC" "${MANAGED_BY_TAG}"
setup_iam_user "$IAM_DEBUG_USER" "$IAM_DEBUG_POLICY" "$IAM_DEBUG_POLICY_DOC" "${MANAGED_BY_TAG}-debug"

# Setup access keys
setup_access_keys "$IAM_CI_USER" "AWS_ACCESS_KEY_ID" "AWS_SECRET_ACCESS_KEY" || \
    log_warn "CI user keys not available - .env file will have empty AWS credentials"
setup_access_keys "$IAM_DEBUG_USER" "AWS_DEBUG_ACCESS_KEY_ID" "AWS_DEBUG_SECRET_ACCESS_KEY" || \
    log_warn "Debug user keys not available - .env file will have empty debug credentials"

echo ""

# ============================================================================
# 1b. AWS IAM ROLE FOR HCP CLI (Idempotent)
# ============================================================================
#
# The hcp CLI requires a --role-arn argument. This role is assumed by the
# hosted control plane components to manage AWS infrastructure (EC2, ELB, etc).
#
# SECURITY MODEL:
#   - CI User (above): Scoped via tags and ARN patterns - used for ansible tasks
#   - HCP Role (this): Broader permissions - used by hcp CLI for cluster operations
#
# WHY HCP ROLE IS BROADER:
#   The hcp CLI creates resources with dynamic names we don't fully control.
#   However, we ADD SCOPING where possible:
#
#   1. S3 BUCKETS: Scoped to "${MANAGED_BY_TAG}-*"
#      - hcp creates buckets like "{cluster-name}-oidc"
#      - Cluster names must start with MANAGED_BY_TAG (enforced by naming)
#
#   2. IAM ROLES/PROFILES: Scoped to "${MANAGED_BY_TAG}-*"
#      - hcp creates roles like "{cluster-name}-worker-role"
#
#   3. EC2/ELB/VPC: Remain broad (Resource: "*")
#      - hcp creates these with cluster-specific names
#      - Tag-based scoping is possible but hcp doesn't always tag consistently
#      - Resources are tagged via --additional-tags for cleanup/tracking
#
#   4. ROUTE53: Broad (all hosted zones)
#      - Could be scoped to specific zone ID if known
#
# CRITICAL: Cluster names MUST start with "${MANAGED_BY_TAG}-" for scoping!
#   Good: kagenti-hypershift-ci-local, kagenti-hypershift-ci-pr123
#   Bad:  my-test-cluster (bypasses S3 and IAM scoping)
#

log_info "Setting up IAM role for hcp CLI..."

# Trust policy - allows any IAM user/role in this account to assume this role
# This enables both local testing (any user) and CI (the CI user)
HCP_ROLE_TRUST_POLICY=$(cat <<TRUSTPOLICY
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Action": "sts:AssumeRole",
            "Principal": {
                "AWS": "arn:aws:iam::${AWS_ACCOUNT_ID}:root"
            }
        }
    ]
}
TRUSTPOLICY
)

# Role policy - permissions needed by hcp CLI for cluster lifecycle
# Based on hypershift-automation/hcp/templates/policy.json.j2
# ENHANCED with scoping where possible (S3, IAM)
#
# NOTE: This policy uses ${MANAGED_BY_TAG} for scoping.
# The heredoc below uses variable substitution.
#
HCP_ROLE_POLICY_DOC=$(cat <<ROLEPOLICY
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Sid": "EC2Broad",
            "Effect": "Allow",
            "Action": [
                "ec2:CreateDhcpOptions",
                "ec2:DeleteSubnet",
                "ec2:ReplaceRouteTableAssociation",
                "ec2:DescribeAddresses",
                "ec2:DescribeInstances",
                "ec2:DeleteVpcEndpoints",
                "ec2:CreateNatGateway",
                "ec2:CreateVpc",
                "ec2:DescribeDhcpOptions",
                "ec2:AttachInternetGateway",
                "ec2:DeleteVpcEndpointServiceConfigurations",
                "ec2:DeleteRouteTable",
                "ec2:AssociateRouteTable",
                "ec2:DescribeInternetGateways",
                "ec2:DescribeAvailabilityZones",
                "ec2:CreateRoute",
                "ec2:CreateInternetGateway",
                "ec2:RevokeSecurityGroupEgress",
                "ec2:ModifyVpcAttribute",
                "ec2:DeleteInternetGateway",
                "ec2:DescribeVpcEndpointConnections",
                "ec2:RejectVpcEndpointConnections",
                "ec2:DescribeRouteTables",
                "ec2:ReleaseAddress",
                "ec2:AssociateDhcpOptions",
                "ec2:TerminateInstances",
                "ec2:CreateTags",
                "ec2:DeleteTags",
                "ec2:DeleteRoute",
                "ec2:CreateRouteTable",
                "ec2:DetachInternetGateway",
                "ec2:DescribeVpcEndpointServiceConfigurations",
                "ec2:DescribeNatGateways",
                "ec2:DisassociateRouteTable",
                "ec2:AllocateAddress",
                "ec2:DescribeSecurityGroups",
                "ec2:RevokeSecurityGroupIngress",
                "ec2:CreateVpcEndpoint",
                "ec2:DescribeVpcs",
                "ec2:DeleteSecurityGroup",
                "ec2:DeleteDhcpOptions",
                "ec2:DeleteNatGateway",
                "ec2:DescribeVpcEndpoints",
                "ec2:DeleteVpc",
                "ec2:CreateSubnet",
                "ec2:DescribeSubnets",
                "ec2:CreateSecurityGroup",
                "ec2:ModifyInstanceAttribute",
                "ec2:AuthorizeSecurityGroupIngress",
                "ec2:AuthorizeSecurityGroupEgress",
                "ec2:DescribeLaunchTemplates",
                "ec2:DescribeLaunchTemplateVersions",
                "ec2:CreateLaunchTemplate",
                "ec2:CreateLaunchTemplateVersion",
                "ec2:DeleteLaunchTemplate",
                "ec2:RunInstances"
            ],
            "Resource": "*"
        },
        {
            "Sid": "ELBBroad",
            "Effect": "Allow",
            "Action": [
                "elasticloadbalancing:DeleteLoadBalancer",
                "elasticloadbalancing:DescribeLoadBalancers",
                "elasticloadbalancing:DescribeTargetGroups",
                "elasticloadbalancing:DeleteTargetGroup",
                "elasticloadbalancing:CreateLoadBalancer",
                "elasticloadbalancing:CreateTargetGroup",
                "elasticloadbalancing:CreateListener",
                "elasticloadbalancing:DeleteListener",
                "elasticloadbalancing:RegisterTargets",
                "elasticloadbalancing:DeregisterTargets",
                "elasticloadbalancing:ModifyLoadBalancerAttributes",
                "elasticloadbalancing:ModifyTargetGroupAttributes",
                "elasticloadbalancing:DescribeListeners",
                "elasticloadbalancing:DescribeLoadBalancerAttributes",
                "elasticloadbalancing:DescribeTargetGroupAttributes",
                "elasticloadbalancing:DescribeTargetHealth",
                "elasticloadbalancing:AddTags"
            ],
            "Resource": "*"
        },
        {
            "Sid": "IAMReadOnly",
            "Effect": "Allow",
            "Action": [
                "iam:GetRole",
                "iam:GetInstanceProfile",
                "iam:ListAttachedRolePolicies",
                "iam:GetRolePolicy",
                "iam:GetOpenIDConnectProvider",
                "iam:ListOpenIDConnectProviders"
            ],
            "Resource": "*"
        },
        {
            "Sid": "IAMPassWorkerRole",
            "Effect": "Allow",
            "Action": "iam:PassRole",
            "Resource": [
                "arn:aws:iam::*:role/${MANAGED_BY_TAG}-*-worker-role",
                "arn:aws:iam::*:role/${MANAGED_BY_TAG}-*"
            ],
            "Condition": {
                "ForAnyValue:StringEqualsIfExists": {
                    "iam:PassedToService": "ec2.amazonaws.com"
                }
            }
        },
        {
            "Sid": "IAMPrefixedRoles",
            "Effect": "Allow",
            "Action": [
                "iam:CreateRole",
                "iam:DeleteRole",
                "iam:TagRole",
                "iam:UpdateRole",
                "iam:UpdateAssumeRolePolicy",
                "iam:PutRolePolicy",
                "iam:DeleteRolePolicy"
            ],
            "Resource": "arn:aws:iam::*:role/${MANAGED_BY_TAG}-*"
        },
        {
            "Sid": "IAMPrefixedInstanceProfiles",
            "Effect": "Allow",
            "Action": [
                "iam:CreateInstanceProfile",
                "iam:DeleteInstanceProfile",
                "iam:TagInstanceProfile",
                "iam:AddRoleToInstanceProfile",
                "iam:RemoveRoleFromInstanceProfile"
            ],
            "Resource": "arn:aws:iam::*:instance-profile/${MANAGED_BY_TAG}-*"
        },
        {
            "Sid": "IAMOIDCProviders",
            "Effect": "Allow",
            "Action": [
                "iam:CreateOpenIDConnectProvider",
                "iam:DeleteOpenIDConnectProvider",
                "iam:TagOpenIDConnectProvider"
            ],
            "Resource": "arn:aws:iam::*:oidc-provider/*"
        },
        {
            "Sid": "Route53Broad",
            "Effect": "Allow",
            "Action": [
                "route53:ListHostedZonesByVPC",
                "route53:CreateHostedZone",
                "route53:ListHostedZones",
                "route53:ChangeResourceRecordSets",
                "route53:ListResourceRecordSets",
                "route53:DeleteHostedZone",
                "route53:AssociateVPCWithHostedZone",
                "route53:ListHostedZonesByName"
            ],
            "Resource": "*"
        },
        {
            "Sid": "S3ReadOnly",
            "Effect": "Allow",
            "Action": [
                "s3:ListAllMyBuckets",
                "s3:GetBucketLocation"
            ],
            "Resource": "*"
        },
        {
            "Sid": "S3PrefixedBuckets",
            "Effect": "Allow",
            "Action": [
                "s3:CreateBucket",
                "s3:DeleteBucket",
                "s3:ListBucket",
                "s3:PutObject",
                "s3:GetObject",
                "s3:DeleteObject",
                "s3:PutBucketPolicy",
                "s3:GetBucketPolicy",
                "s3:PutBucketTagging",
                "s3:PutBucketPublicAccessBlock",
                "s3:GetBucketPublicAccessBlock"
            ],
            "Resource": [
                "arn:aws:s3:::${MANAGED_BY_TAG}-*",
                "arn:aws:s3:::${MANAGED_BY_TAG}-*/*"
            ]
        },
$(if [ -n "$OIDC_S3_BUCKET" ]; then cat <<S3OIDCROLE
        {
            "Sid": "S3SharedOIDCBucket",
            "Effect": "Allow",
            "Action": [
                "s3:PutObject",
                "s3:GetObject",
                "s3:DeleteObject",
                "s3:ListBucket",
                "s3:GetBucketLocation"
            ],
            "Resource": [
                "arn:aws:s3:::${OIDC_S3_BUCKET}",
                "arn:aws:s3:::${OIDC_S3_BUCKET}/${MANAGED_BY_TAG}-*"
            ]
        },
S3OIDCROLE
fi)
        {
            "Sid": "STS",
            "Effect": "Allow",
            "Action": [
                "sts:GetCallerIdentity"
            ],
            "Resource": "*"
        }
    ]
}
ROLEPOLICY
)

# Create or update IAM role
ROLE_ARN="arn:aws:iam::${AWS_ACCOUNT_ID}:role/${IAM_HCP_ROLE}"

if aws iam get-role --role-name "$IAM_HCP_ROLE" &>/dev/null; then
    log_success "  Role '$IAM_HCP_ROLE' exists"
    # Update trust policy
    aws iam update-assume-role-policy --role-name "$IAM_HCP_ROLE" --policy-document "$HCP_ROLE_TRUST_POLICY"
    log_success "  Updated trust policy"
else
    aws iam create-role \
        --role-name "$IAM_HCP_ROLE" \
        --assume-role-policy-document "$HCP_ROLE_TRUST_POLICY" \
        --tags Key=Purpose,Value="${MANAGED_BY_TAG}-hcp-cli" Key=ManagedBy,Value="${MANAGED_BY_TAG}" >/dev/null
    log_success "  Created role '$IAM_HCP_ROLE'"
fi

# Create or update role policy
ROLE_POLICY_ARN="arn:aws:iam::${AWS_ACCOUNT_ID}:policy/${IAM_HCP_ROLE_POLICY}"
if aws iam get-policy --policy-arn "$ROLE_POLICY_ARN" &>/dev/null; then
    # Delete old versions to make room
    OLD_VERSIONS=$(aws iam list-policy-versions --policy-arn "$ROLE_POLICY_ARN" \
        --query "Versions[?IsDefaultVersion==\`false\`].VersionId" --output text)
    for ver in $OLD_VERSIONS; do
        aws iam delete-policy-version --policy-arn "$ROLE_POLICY_ARN" --version-id "$ver" 2>/dev/null || true
    done
    aws iam create-policy-version \
        --policy-arn "$ROLE_POLICY_ARN" \
        --policy-document "$HCP_ROLE_POLICY_DOC" \
        --set-as-default >/dev/null
    log_success "  Updated role policy"
else
    aws iam create-policy \
        --policy-name "$IAM_HCP_ROLE_POLICY" \
        --policy-document "$HCP_ROLE_POLICY_DOC" \
        --tags Key=Purpose,Value="${MANAGED_BY_TAG}-hcp-cli" Key=ManagedBy,Value="${MANAGED_BY_TAG}" >/dev/null
    log_success "  Created role policy"
fi

# Attach policy to role (idempotent)
aws iam attach-role-policy --role-name "$IAM_HCP_ROLE" --policy-arn "$ROLE_POLICY_ARN"
log_success "  Policy attached to role"

# Export role ARN for use in .env file
export HCP_ROLE_ARN="$ROLE_ARN"

echo ""

# ============================================================================
# 2. OPENSHIFT SERVICE ACCOUNT (Idempotent)
# ============================================================================

log_info "Setting up OpenShift service account..."

# Create namespace (idempotent via apply)
oc apply -f - <<EOF
apiVersion: v1
kind: Namespace
metadata:
  name: ${SA_NAMESPACE}
  labels:
    app.kubernetes.io/managed-by: hypershift-ci-setup
EOF
log_success "Namespace '${SA_NAMESPACE}' exists"

# Create service account (idempotent via apply)
oc apply -f - <<EOF
apiVersion: v1
kind: ServiceAccount
metadata:
  name: ${SA_NAME}
  namespace: ${SA_NAMESPACE}
  labels:
    app.kubernetes.io/managed-by: hypershift-ci-setup
EOF
log_success "ServiceAccount '${SA_NAME}' exists"

# Create cluster role (idempotent via apply)
# RBAC scope analysis:
#   - hostedclusters/nodepools: Full CRUD needed for cluster lifecycle
#   - secrets: Needed to create pull-secret, read kubeconfig after cluster creation
#   - configmaps: Needed for cluster configuration
#   - namespaces: Create/delete for cluster isolation
#   - events: Read-only for debugging cluster provisioning issues
#   - nodes/pods: Read-only for status checks
# Note: secrets/configmaps are cluster-scoped because HyperShift creates
# resources in dynamically-named namespaces (e.g., clusters-<name>)
oc apply -f - <<EOF
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: ${CLUSTER_ROLE_NAME}
  labels:
    app.kubernetes.io/managed-by: hypershift-ci-setup
rules:
  # HyperShift resources - full lifecycle management
  - apiGroups: ["hypershift.openshift.io"]
    resources: ["hostedclusters", "nodepools", "hostedcontrolplanes"]
    verbs: ["get", "list", "watch", "create", "update", "patch", "delete"]
  # Secrets - full lifecycle for cluster secrets (kubeconfig, pull-secret, etc)
  - apiGroups: [""]
    resources: ["secrets"]
    verbs: ["get", "list", "watch", "create", "update", "patch", "delete"]
  # ConfigMaps - cluster configuration
  - apiGroups: [""]
    resources: ["configmaps"]
    verbs: ["get", "list", "watch", "create", "update", "patch", "delete"]
  # Namespaces - full lifecycle for cluster namespaces (hcp patches labels/annotations)
  - apiGroups: [""]
    resources: ["namespaces"]
    verbs: ["get", "list", "watch", "create", "update", "patch", "delete"]
  # Services - for checking ingress/load balancers
  - apiGroups: [""]
    resources: ["services"]
    verbs: ["get", "list", "watch"]
  # Read-only for debugging
  - apiGroups: [""]
    resources: ["nodes", "pods", "events"]
    verbs: ["get", "list", "watch"]
  # Pod logs - needed for debugging HyperShift operator and control plane issues
  - apiGroups: [""]
    resources: ["pods/log"]
    verbs: ["get", "list"]
  # Routes - for checking ignition and other routes
  - apiGroups: ["route.openshift.io"]
    resources: ["routes"]
    verbs: ["get", "list", "watch"]
  # CAPI resources - for machine/nodepool status
  - apiGroups: ["cluster.x-k8s.io"]
    resources: ["machines", "machinesets", "machinedeployments", "clusters"]
    verbs: ["get", "list", "watch"]
  # AWS CAPI resources
  - apiGroups: ["infrastructure.cluster.x-k8s.io"]
    resources: ["awsmachines", "awsmachinetemplates", "awsclusters"]
    verbs: ["get", "list", "watch"]
  # Deployments and other workloads for debugging control plane
  - apiGroups: ["apps"]
    resources: ["deployments", "statefulsets", "replicasets"]
    verbs: ["get", "list", "watch"]
EOF
log_success "ClusterRole '${CLUSTER_ROLE_NAME}' applied"

# Create cluster role binding (idempotent via apply)
oc apply -f - <<EOF
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: ${CLUSTER_ROLE_BINDING_NAME}
  labels:
    app.kubernetes.io/managed-by: hypershift-ci-setup
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: ClusterRole
  name: ${CLUSTER_ROLE_NAME}
subjects:
  - kind: ServiceAccount
    name: ${SA_NAME}
    namespace: ${SA_NAMESPACE}
EOF
log_success "ClusterRoleBinding '${CLUSTER_ROLE_BINDING_NAME}' applied"

# Create long-lived token secret (idempotent via apply)
# Note: This uses the legacy annotation method which still works in OpenShift
oc apply -f - <<EOF
apiVersion: v1
kind: Secret
metadata:
  name: ${SA_NAME}-token
  namespace: ${SA_NAMESPACE}
  annotations:
    kubernetes.io/service-account.name: ${SA_NAME}
  labels:
    app.kubernetes.io/managed-by: hypershift-ci-setup
type: kubernetes.io/service-account-token
EOF
log_success "Token secret '${SA_NAME}-token' exists"

# Wait for token to be populated by the controller (up to 30 seconds)
log_info "Waiting for token to be populated..."
for i in {1..30}; do
    SA_TOKEN=$(oc get secret "${SA_NAME}-token" -n "$SA_NAMESPACE" -o jsonpath='{.data.token}' 2>/dev/null || echo "")
    if [ -n "$SA_TOKEN" ]; then
        break
    fi
    sleep 1
done

if [ -z "$SA_TOKEN" ]; then
    log_error "Token was not populated. Check service account controller."
fi

# Decode token
SA_TOKEN=$(echo "$SA_TOKEN" | base64_decode)

# Get API server URL and CA cert
API_SERVER=$(oc whoami --show-server)
CA_DATA=$(oc get secret "${SA_NAME}-token" -n "$SA_NAMESPACE" -o jsonpath='{.data.ca\.crt}')

# Build kubeconfig
KUBECONFIG_CONTENT=$(cat <<EOF
apiVersion: v1
kind: Config
clusters:
- cluster:
    server: ${API_SERVER}
    certificate-authority-data: ${CA_DATA}
  name: mgmt-cluster
contexts:
- context:
    cluster: mgmt-cluster
    user: ${SA_NAME}
    namespace: ${SA_NAMESPACE}
  name: ${MANAGED_BY_TAG}
current-context: ${MANAGED_BY_TAG}
users:
- name: ${SA_NAME}
  user:
    token: ${SA_TOKEN}
EOF
)

# Save kubeconfig to standard location (~/.kube/)
MGMT_KUBECONFIG_PATH="$HOME/.kube/${MANAGED_BY_TAG}-mgmt.kubeconfig"
mkdir -p "$HOME/.kube"
echo "$KUBECONFIG_CONTENT" > "$MGMT_KUBECONFIG_PATH"
chmod 600 "$MGMT_KUBECONFIG_PATH"
log_success "Saved kubeconfig to $MGMT_KUBECONFIG_PATH"

# Also export base64 version for GitHub Actions secrets
export HYPERSHIFT_MGMT_KUBECONFIG
HYPERSHIFT_MGMT_KUBECONFIG=$(echo "$KUBECONFIG_CONTENT" | base64_encode)
export HYPERSHIFT_MGMT_KUBECONFIG_PATH="$MGMT_KUBECONFIG_PATH"
log_success "Generated base64 kubeconfig for GitHub Actions"

echo ""

# ============================================================================
# 3. PULL SECRET
# ============================================================================

log_info "Extracting pull secret from cluster..."

PULL_SECRET=$(oc get secret pull-secret -n openshift-config -o jsonpath='{.data.\.dockerconfigjson}' | base64_decode)

if echo "$PULL_SECRET" | jq -e '.auths' &>/dev/null; then
    REGISTRY_COUNT=$(echo "$PULL_SECRET" | jq -r '.auths | keys | length')
    log_success "Pull secret valid ($REGISTRY_COUNT registries)"
    export PULL_SECRET
else
    log_error "Failed to extract valid pull secret"
fi

echo ""

# ============================================================================
# 4. BASE DOMAIN (must have a PUBLIC Route53 hosted zone)
# ============================================================================

log_info "Discovering base domain..."

# Try to get from ingress config
APPS_DOMAIN=$(oc get ingresses.config.openshift.io cluster -o jsonpath='{.spec.domain}' 2>/dev/null || echo "")

if [ -n "$APPS_DOMAIN" ]; then
    # Remove 'apps.' prefix if present
    DETECTED_DOMAIN="${APPS_DOMAIN#apps.}"
    log_info "Detected domain from ingress: $DETECTED_DOMAIN"
else
    # Try to get from existing hosted clusters
    DETECTED_DOMAIN=$(oc get hostedclusters -A -o jsonpath='{.items[0].spec.dns.baseDomain}' 2>/dev/null || echo "")
    if [ -n "$DETECTED_DOMAIN" ]; then
        log_info "Detected domain from hosted cluster: $DETECTED_DOMAIN"
    fi
fi

# Find a PUBLIC Route53 hosted zone (required by HyperShift)
# Try the detected domain and progressively shorter parent domains
BASE_DOMAIN=""
if [ -n "$DETECTED_DOMAIN" ]; then
    DOMAIN_TO_CHECK="$DETECTED_DOMAIN"
    while [ -n "$DOMAIN_TO_CHECK" ] && [ -z "$BASE_DOMAIN" ]; do
        ZONE_INFO=$(aws route53 list-hosted-zones-by-name --dns-name "$DOMAIN_TO_CHECK" --max-items 1 \
            --query "HostedZones[?Name=='${DOMAIN_TO_CHECK}.' && Config.PrivateZone==\`false\`].Name" \
            --output text 2>/dev/null || echo "")

        if [ -n "$ZONE_INFO" ] && [ "$ZONE_INFO" != "None" ]; then
            BASE_DOMAIN="$DOMAIN_TO_CHECK"
        else
            # Try parent domain (strip first segment)
            if [[ "$DOMAIN_TO_CHECK" == *.* ]]; then
                DOMAIN_TO_CHECK="${DOMAIN_TO_CHECK#*.}"
            else
                DOMAIN_TO_CHECK=""
            fi
        fi
    done
fi

if [ -n "$BASE_DOMAIN" ]; then
    if [ "$BASE_DOMAIN" != "$DETECTED_DOMAIN" ]; then
        log_warn "Detected domain ($DETECTED_DOMAIN) has no public Route53 zone"
        log_success "Using public zone: $BASE_DOMAIN"
    else
        log_success "Base domain: $BASE_DOMAIN (public Route53 zone found)"
    fi
    export BASE_DOMAIN
else
    log_warn "Could not find a PUBLIC Route53 hosted zone"
    log_info "Available public zones:"
    aws route53 list-hosted-zones --query "HostedZones[?Config.PrivateZone==\`false\`].Name" --output text 2>/dev/null | tr '\t' '\n' | sed 's/\.$//; s/^/  /' || true
    log_warn "Set BASE_DOMAIN manually in .env.hypershift-ci after setup"
    export BASE_DOMAIN=""
fi

echo ""

# ============================================================================
# 5. SAVE TO .env FILE
# ============================================================================

log_info "Saving credentials to .env.hypershift-ci..."

ENV_FILE=".env.hypershift-ci"

# Preserve existing CI credentials if we didn't create new ones
# (extract values without sourcing to avoid overriding admin AWS creds)
if [ -z "${CI_AWS_ACCESS_KEY_ID:-}" ] && [ -f "$ENV_FILE" ]; then
    log_info "Preserving existing CI credentials from $ENV_FILE..."
    CI_AWS_ACCESS_KEY_ID=$(grep -E '^export AWS_ACCESS_KEY_ID=' "$ENV_FILE" 2>/dev/null | cut -d'"' -f2 || true)
    CI_AWS_SECRET_ACCESS_KEY=$(grep -E '^export AWS_SECRET_ACCESS_KEY=' "$ENV_FILE" 2>/dev/null | cut -d'"' -f2 || true)
    CI_AWS_DEBUG_ACCESS_KEY_ID=$(grep -E '^export AWS_DEBUG_ACCESS_KEY_ID=' "$ENV_FILE" 2>/dev/null | cut -d'"' -f2 || true)
    CI_AWS_DEBUG_SECRET_ACCESS_KEY=$(grep -E '^export AWS_DEBUG_SECRET_ACCESS_KEY=' "$ENV_FILE" 2>/dev/null | cut -d'"' -f2 || true)
fi

# Prefer newly created keys, fall back to preserved old keys
# (setup_access_keys exports to CI_NEW_* when it creates new keys)
FINAL_AWS_ACCESS_KEY_ID="${CI_NEW_AWS_ACCESS_KEY_ID:-${CI_AWS_ACCESS_KEY_ID:-}}"
FINAL_AWS_SECRET_ACCESS_KEY="${CI_NEW_AWS_SECRET_ACCESS_KEY:-${CI_AWS_SECRET_ACCESS_KEY:-}}"
FINAL_AWS_DEBUG_ACCESS_KEY_ID="${CI_NEW_AWS_DEBUG_ACCESS_KEY_ID:-${CI_AWS_DEBUG_ACCESS_KEY_ID:-}}"
FINAL_AWS_DEBUG_SECRET_ACCESS_KEY="${CI_NEW_AWS_DEBUG_SECRET_ACCESS_KEY:-${CI_AWS_DEBUG_SECRET_ACCESS_KEY:-}}"

cat > "$ENV_FILE" <<ENVFILE
# HyperShift CI Credentials
# Generated: $(date -u +"%Y-%m-%dT%H:%M:%SZ")
# Managed by: ${MANAGED_BY_TAG}
# DO NOT COMMIT THIS FILE

# =============================================================================
# HyperShift Management Cluster Kubeconfig
# =============================================================================
# Local usage: file path (standard ~/.kube/ location)
export KUBECONFIG="${MGMT_KUBECONFIG_PATH}"

# GitHub Actions: base64-encoded (for secrets)
HYPERSHIFT_MGMT_KUBECONFIG_BASE64="${HYPERSHIFT_MGMT_KUBECONFIG}"

# =============================================================================
# AWS Credentials - CI User (full permissions for cluster lifecycle)
# =============================================================================
export AWS_ACCESS_KEY_ID="${FINAL_AWS_ACCESS_KEY_ID}"
export AWS_SECRET_ACCESS_KEY="${FINAL_AWS_SECRET_ACCESS_KEY}"
export AWS_REGION="${AWS_REGION}"

# AWS IAM Role for hcp CLI (passed to ansible as iam.hcp_role_name)
export HCP_ROLE_NAME="${IAM_HCP_ROLE}"
export HCP_ROLE_ARN="${HCP_ROLE_ARN}"

# =============================================================================
# AWS Credentials - Debug User (read-only for debugging)
# =============================================================================
export AWS_DEBUG_ACCESS_KEY_ID="${FINAL_AWS_DEBUG_ACCESS_KEY_ID}"
export AWS_DEBUG_SECRET_ACCESS_KEY="${FINAL_AWS_DEBUG_SECRET_ACCESS_KEY}"

# =============================================================================
# Red Hat Pull Secret
# =============================================================================
export PULL_SECRET='${PULL_SECRET}'

# =============================================================================
# Base Domain (must match a PUBLIC Route53 hosted zone)
# =============================================================================
export BASE_DOMAIN="${BASE_DOMAIN}"

# =============================================================================
# Resource Naming and Tagging
# =============================================================================
# MANAGED_BY_TAG is the primary identifier for all resources
# Pass to ansible: -e "additional_tags=ManagedBy=\${MANAGED_BY_TAG}"
export MANAGED_BY_TAG="${MANAGED_BY_TAG}"

# =============================================================================
# Shared OIDC S3 Bucket (auto-detected from management cluster)
# =============================================================================
# HyperShift uses this bucket for OIDC discovery documents
# This is typically shared across all clusters on the management cluster
export OIDC_S3_BUCKET="${OIDC_S3_BUCKET:-}"
ENVFILE

chmod 600 "$ENV_FILE"

# Add to .gitignore if not already there
if [ -f .gitignore ]; then
    if ! grep -q "^\.env\.hypershift-ci$" .gitignore 2>/dev/null; then
        echo ".env.hypershift-ci" >> .gitignore
        log_success "Added .env.hypershift-ci to .gitignore"
    fi
else
    echo ".env.hypershift-ci" > .gitignore
    log_success "Created .gitignore with .env.hypershift-ci"
fi

log_success "Saved to .env.hypershift-ci"

echo ""

# ============================================================================
# 6. VERIFY
# ============================================================================

log_info "Verifying credentials..."

# Test management cluster access using the file we saved
if KUBECONFIG="$MGMT_KUBECONFIG_PATH" oc whoami &>/dev/null; then
    SA_IDENTITY=$(KUBECONFIG="$MGMT_KUBECONFIG_PATH" oc whoami)
    log_success "Management cluster access: OK ($SA_IDENTITY)"
else
    log_warn "Management cluster access: FAILED"
fi

# Test AWS access (if we have keys)
if [ -n "${AWS_ACCESS_KEY_ID:-}" ] && [ -n "${AWS_SECRET_ACCESS_KEY:-}" ]; then
    # Wait a moment for IAM propagation
    sleep 2
    if AWS_ACCESS_KEY_ID="$AWS_ACCESS_KEY_ID" AWS_SECRET_ACCESS_KEY="$AWS_SECRET_ACCESS_KEY" \
       aws sts get-caller-identity &>/dev/null; then
        log_success "AWS CI user access: OK"
    else
        log_warn "AWS CI user access: FAILED (keys may need more time to propagate)"
    fi
else
    log_warn "AWS CI user access: No keys available"
fi

echo ""
echo "╔════════════════════════════════════════════════════════════════╗"
echo "║                        Setup Complete                          ║"
echo "╚════════════════════════════════════════════════════════════════╝"
echo ""
echo "MANAGED_BY_TAG: ${MANAGED_BY_TAG}"
echo ""
echo "Created resources:"
echo "  AWS:  ${IAM_CI_USER}, ${IAM_DEBUG_USER}, ${IAM_HCP_ROLE}"
echo "  OCP:  ${SA_NAMESPACE}/${SA_NAME}"
echo "  Local: ${MGMT_KUBECONFIG_PATH}"
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "NEXT STEP - Create a cluster (copy & paste):"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "  # Creates cluster: ${MANAGED_BY_TAG}-local"
echo "  source .env.hypershift-ci && ./.github/scripts/hypershift/local-setup.sh && ./.github/scripts/hypershift/create-cluster.sh"
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "Or step by step:"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "  # 1. Load CI credentials (sets KUBECONFIG automatically)"
echo "  source .env.hypershift-ci"
echo ""
echo "  # 2. Verify access"
echo "  oc whoami"
echo ""
echo "  # 3. One-time local setup (installs hcp CLI, clones fork)"
echo "  ./.github/scripts/hypershift/local-setup.sh"
echo ""
echo "  # 4. Create cluster (creates: ${MANAGED_BY_TAG}-local)"
echo "  ./.github/scripts/hypershift/create-cluster.sh"
echo ""
echo "  # Or with custom suffix (creates: ${MANAGED_BY_TAG}-mytest)"
echo "  ./.github/scripts/hypershift/create-cluster.sh mytest"
echo ""
echo "  # Destroy cluster when done:"
echo "  ./.github/scripts/hypershift/destroy-cluster.sh local  # destroys ${MANAGED_BY_TAG}-local"
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "For GitHub Actions - add secrets (copy & paste after sourcing):"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
cat << 'SECRETS'
source .env.hypershift-ci && \
gh secret set HYPERSHIFT_MGMT_KUBECONFIG -a actions --body "$HYPERSHIFT_MGMT_KUBECONFIG_BASE64" && \
gh secret set AWS_ACCESS_KEY_ID -a actions --body "$AWS_ACCESS_KEY_ID" && \
gh secret set AWS_SECRET_ACCESS_KEY -a actions --body "$AWS_SECRET_ACCESS_KEY" && \
gh secret set AWS_REGION -a actions --body "$AWS_REGION" && \
gh secret set PULL_SECRET -a actions --body "$PULL_SECRET" && \
gh secret set BASE_DOMAIN -a actions --body "$BASE_DOMAIN" && \
gh secret set MANAGED_BY_TAG -a actions --body "$MANAGED_BY_TAG" && \
gh secret set HCP_ROLE_NAME -a actions --body "$HCP_ROLE_NAME"
SECRETS
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "To rotate AWS credentials (delete old keys, create new ones):"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "  # One command to rotate everything:"
echo "  ./.github/scripts/hypershift/setup-hypershift-ci-credentials.sh --rotate"
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "NOTE: Re-running this script updates policies/roles but preserves"
echo "      existing access keys. Use --rotate to create fresh credentials."
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
