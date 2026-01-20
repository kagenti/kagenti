#!/usr/bin/env bash
#
# Pre-flight Check for HyperShift CI
#
# Verifies all prerequisites for the full HyperShift CI workflow:
# - Tools: jq, aws, oc, hcp, ansible-playbook, ansible-galaxy
# - AWS authentication and IAM permissions
# - OpenShift authentication and cluster-admin permissions
# - HyperShift CRD installation
# - Pull secret accessibility
# - Base domain discovery
#
# USAGE:
#   ./.github/scripts/hypershift/preflight-check.sh
#

set -euo pipefail

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

ERRORS=0

log_info() { echo -e "${BLUE}→${NC} $1"; }
log_success() { echo -e "${GREEN}✓${NC} $1"; }
log_warn() { echo -e "${YELLOW}⚠${NC} $1"; }
log_error() { echo -e "${RED}✗${NC} $1"; ERRORS=$((ERRORS + 1)); }

echo ""
echo "╔════════════════════════════════════════════════════════════════╗"
echo "║           HyperShift CI Pre-flight Check                       ║"
echo "╚════════════════════════════════════════════════════════════════╝"
echo ""

# ============================================================================
# 1. TOOLS (for setup script)
# ============================================================================

log_info "Checking tools for setup..."

# jq
if command -v jq &>/dev/null; then
    log_success "jq: $(jq --version)"
else
    log_error "jq not found. Install with: brew install jq"
fi

# AWS CLI
if command -v aws &>/dev/null; then
    log_success "aws: $(aws --version 2>&1 | head -1)"
else
    log_error "aws CLI not found. Install from: https://aws.amazon.com/cli/"
fi

# oc CLI
if command -v oc &>/dev/null; then
    OC_VERSION=$(oc version --client 2>/dev/null | head -1 || echo "unknown")
    log_success "oc: $OC_VERSION"
else
    log_error "oc CLI not found. Install from: https://mirror.openshift.com/pub/openshift-v4/clients/ocp/"
fi

echo ""

# ============================================================================
# 1b. TOOLS (for cluster creation)
# ============================================================================

log_info "Checking tools for cluster creation..."

# hcp CLI (HyperShift)
if command -v hcp &>/dev/null; then
    HCP_VERSION=$(hcp version 2>/dev/null | head -1 || echo "unknown")
    log_success "hcp: $HCP_VERSION"
else
    log_warn "hcp CLI not found (will be installed by local-setup.sh from OpenShift console)"
fi

# ansible-playbook
if command -v ansible-playbook &>/dev/null; then
    ANSIBLE_VERSION=$(ansible-playbook --version 2>/dev/null | head -1 || echo "unknown")
    log_success "ansible-playbook: $ANSIBLE_VERSION"
else
    log_error "ansible-playbook not found. Install with: pip install ansible-core"
fi

# ansible-galaxy
if command -v ansible-galaxy &>/dev/null; then
    log_success "ansible-galaxy: available"
else
    log_error "ansible-galaxy not found. Install with: pip install ansible-core"
fi

echo ""

# ============================================================================
# 2. AWS AUTHENTICATION
# ============================================================================

log_info "Checking AWS authentication..."

if aws sts get-caller-identity &>/dev/null; then
    AWS_ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
    AWS_ARN=$(aws sts get-caller-identity --query Arn --output text)
    log_success "AWS authenticated: $AWS_ARN"
else
    log_error "Not logged into AWS. Set AWS_ACCESS_KEY_ID/AWS_SECRET_ACCESS_KEY or run: aws configure"
fi

echo ""

# ============================================================================
# 3. AWS IAM PERMISSIONS (need admin for setup)
# ============================================================================

log_info "Checking AWS IAM permissions for setup..."

# Check current identity - warn if using CI user instead of admin
AWS_ARN=$(aws sts get-caller-identity --query Arn --output text 2>/dev/null || echo "")
if echo "$AWS_ARN" | grep -q "kagenti-hypershift-ci"; then
    log_error "Logged in as CI user ($AWS_ARN). Setup requires IAM admin."
    log_info "  Run: unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY"
    log_info "  Then use admin credentials or default AWS profile"
else
    log_success "AWS identity: $AWS_ARN"
fi

# Check iam:CreatePolicy permission using simulate-principal-policy
CAN_CREATE_POLICY=$(aws iam simulate-principal-policy \
    --policy-source-arn "$AWS_ARN" \
    --action-names iam:CreatePolicy \
    --query 'EvaluationResults[0].EvalDecision' \
    --output text 2>/dev/null || echo "error")

if [ "$CAN_CREATE_POLICY" = "allowed" ]; then
    log_success "AWS IAM: Can create policies"
elif [ "$CAN_CREATE_POLICY" = "error" ]; then
    # simulate-principal-policy may not be available, fall back to simple check
    IAM_CHECK=$(aws iam list-policies --scope Local --max-items 1 2>&1 || true)
    if echo "$IAM_CHECK" | grep -q "AccessDenied"; then
        log_error "AWS IAM: Access denied. Need IAM admin permissions"
    else
        log_warn "AWS IAM: Cannot verify CreatePolicy permission (will attempt during setup)"
    fi
else
    log_error "AWS IAM: Cannot create policies (got: $CAN_CREATE_POLICY). Need IAM admin"
fi

# Check iam:CreateRole permission
CAN_CREATE_ROLE=$(aws iam simulate-principal-policy \
    --policy-source-arn "$AWS_ARN" \
    --action-names iam:CreateRole \
    --query 'EvaluationResults[0].EvalDecision' \
    --output text 2>/dev/null || echo "error")

if [ "$CAN_CREATE_ROLE" = "allowed" ]; then
    log_success "AWS IAM: Can create roles"
elif [ "$CAN_CREATE_ROLE" != "error" ]; then
    log_error "AWS IAM: Cannot create roles (got: $CAN_CREATE_ROLE). Need IAM admin"
fi

echo ""

# ============================================================================
# 4. OPENSHIFT AUTHENTICATION
# ============================================================================

log_info "Checking OpenShift authentication..."

if oc whoami &>/dev/null; then
    OC_USER=$(oc whoami)
    OC_SERVER=$(oc whoami --show-server)
    log_success "OpenShift authenticated: $OC_USER @ $OC_SERVER"
else
    log_error "Not logged into OpenShift. Run: oc login <server>"
fi

echo ""

# ============================================================================
# 5. OPENSHIFT PERMISSIONS
# ============================================================================

log_info "Checking OpenShift permissions..."

# ClusterRole creation
# Note: "not namespace scoped" warning is expected - ClusterRoles are cluster-wide resources
CAN_CREATE_CR=$(oc auth can-i create clusterroles 2>&1)
if echo "$CAN_CREATE_CR" | grep -q "yes"; then
    log_success "Can create ClusterRoles"
else
    log_error "Cannot create ClusterRoles - need cluster-admin"
fi

# ClusterRoleBinding creation
# Note: "not namespace scoped" warning is expected - ClusterRoleBindings are cluster-wide resources
CAN_CREATE_CRB=$(oc auth can-i create clusterrolebindings 2>&1)
if echo "$CAN_CREATE_CRB" | grep -q "yes"; then
    log_success "Can create ClusterRoleBindings"
else
    log_error "Cannot create ClusterRoleBindings - need cluster-admin"
fi

# Pull secret access
if oc auth can-i get secrets -n openshift-config &>/dev/null; then
    CAN_GET_SECRETS=$(oc auth can-i get secrets -n openshift-config)
    if [ "$CAN_GET_SECRETS" = "yes" ]; then
        log_success "Can read secrets in openshift-config namespace"
    else
        log_error "Cannot read secrets in openshift-config - need cluster-admin"
    fi
else
    log_error "Cannot check secret read permissions"
fi

echo ""

# ============================================================================
# 6. HYPERSHIFT CRD
# ============================================================================

log_info "Checking HyperShift installation..."

if oc get crd hostedclusters.hypershift.openshift.io &>/dev/null; then
    log_success "HyperShift CRD found - HyperShift is installed"
else
    log_error "HyperShift CRD not found. Is this a HyperShift management cluster?"
fi

echo ""

# ============================================================================
# 7. PULL SECRET
# ============================================================================

log_info "Checking pull secret accessibility..."

PULL_SECRET_DATA=$(oc get secret pull-secret -n openshift-config -o jsonpath='{.data.\.dockerconfigjson}' 2>/dev/null || echo "")
if [ -n "$PULL_SECRET_DATA" ]; then
    # Decode and validate JSON
    if echo "$PULL_SECRET_DATA" | base64 -d 2>/dev/null | jq -e '.auths' &>/dev/null; then
        REGISTRY_COUNT=$(echo "$PULL_SECRET_DATA" | base64 -d | jq -r '.auths | keys | length')
        log_success "Pull secret valid ($REGISTRY_COUNT registries configured)"

        # Show registries
        REGISTRIES=$(echo "$PULL_SECRET_DATA" | base64 -d | jq -r '.auths | keys | join(", ")')
        log_info "  Registries: $REGISTRIES"
    else
        log_error "Pull secret exists but is not valid JSON"
    fi
else
    log_error "Cannot read pull secret from openshift-config namespace"
fi

echo ""

# ============================================================================
# 8. BASE DOMAIN
# ============================================================================

log_info "Checking base domain discovery..."

APPS_DOMAIN=$(oc get ingresses.config.openshift.io cluster -o jsonpath='{.spec.domain}' 2>/dev/null || echo "")
if [ -n "$APPS_DOMAIN" ]; then
    BASE_DOMAIN="${APPS_DOMAIN#apps.}"
    log_success "Base domain: $BASE_DOMAIN (from ingress config)"
else
    # Try hosted clusters
    HC_DOMAIN=$(oc get hostedclusters -A -o jsonpath='{.items[0].spec.dns.baseDomain}' 2>/dev/null || echo "")
    if [ -n "$HC_DOMAIN" ]; then
        BASE_DOMAIN="$HC_DOMAIN"
        log_success "Base domain: $BASE_DOMAIN (from existing hosted cluster)"
    else
        log_warn "Could not auto-detect base domain. You may need to set it manually."
        BASE_DOMAIN=""
    fi
fi

echo ""

# ============================================================================
# 9. ROUTE53 PUBLIC HOSTED ZONE
# ============================================================================

log_info "Checking Route53 public hosted zone..."

if [ -n "$BASE_DOMAIN" ]; then
    # HyperShift requires a PUBLIC hosted zone for the base domain
    # Check if a public hosted zone exists for this domain or a parent domain
    ZONE_FOUND=""
    DOMAIN_TO_CHECK="$BASE_DOMAIN"

    # Try the domain and progressively shorter parent domains
    while [ -n "$DOMAIN_TO_CHECK" ] && [ -z "$ZONE_FOUND" ]; do
        # List hosted zones and check for a public zone matching this domain
        ZONE_INFO=$(aws route53 list-hosted-zones-by-name --dns-name "$DOMAIN_TO_CHECK" --max-items 1 \
            --query "HostedZones[?Name=='${DOMAIN_TO_CHECK}.' && Config.PrivateZone==\`false\`].{Name:Name,Id:Id}" \
            --output text 2>/dev/null || echo "")

        if [ -n "$ZONE_INFO" ] && [ "$ZONE_INFO" != "None" ]; then
            ZONE_FOUND="$DOMAIN_TO_CHECK"
            log_success "Route53 public hosted zone found: $ZONE_FOUND"
        else
            # Try parent domain (strip first segment)
            if [[ "$DOMAIN_TO_CHECK" == *.* ]]; then
                DOMAIN_TO_CHECK="${DOMAIN_TO_CHECK#*.}"
            else
                DOMAIN_TO_CHECK=""
            fi
        fi
    done

    if [ -z "$ZONE_FOUND" ]; then
        log_error "No PUBLIC Route53 hosted zone found for $BASE_DOMAIN"
        log_info "  HyperShift requires a public hosted zone for DNS records"
        log_info "  Available public zones:"
        aws route53 list-hosted-zones --query "HostedZones[?Config.PrivateZone==\`false\`].Name" --output text 2>/dev/null | tr '\t' '\n' | sed 's/\.$//; s/^/    /' || true
        log_info "  Set BASE_DOMAIN in .env.hypershift-ci to match an available zone"
    elif [ "$ZONE_FOUND" != "$BASE_DOMAIN" ]; then
        log_warn "Auto-detected BASE_DOMAIN=$BASE_DOMAIN but public zone is: $ZONE_FOUND"
        log_info "  You may need to update BASE_DOMAIN in .env.hypershift-ci to: $ZONE_FOUND"
    fi
else
    log_warn "Cannot check Route53 - no base domain detected"
fi

echo ""

# ============================================================================
# SUMMARY
# ============================================================================

echo "╔════════════════════════════════════════════════════════════════╗"
if [ $ERRORS -eq 0 ]; then
    echo -e "║  ${GREEN}All checks passed!${NC} Ready to run setup script.              ║"
    echo "╚════════════════════════════════════════════════════════════════╝"
    echo ""
    echo "Run the setup script:"
    echo "  ./.github/scripts/hypershift/setup-hypershift-ci-credentials.sh"
    echo ""
    exit 0
else
    echo -e "║  ${RED}$ERRORS error(s) found.${NC} Please fix before running setup.        ║"
    echo "╚════════════════════════════════════════════════════════════════╝"
    echo ""
    exit 1
fi
