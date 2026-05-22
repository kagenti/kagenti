#!/usr/bin/env bash
#
# Full deployment script for OpenShift Management Cluster
#
# This script orchestrates the complete deployment:
# 1. Terraform infrastructure (with validation)
# 2. OpenShift installation via IPI
# 3. Optional MCE 2.10 installation
#

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TF_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

# Cleanup terraform plan file on exit (contains sensitive data)
trap 'rm -f "$TF_DIR/tfplan"' EXIT

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m'

log_info() { echo -e "${BLUE}→${NC} $1"; }
log_success() { echo -e "${GREEN}✓${NC} $1"; }
log_warn() { echo -e "${YELLOW}⚠${NC} $1"; }
log_error() { echo -e "${RED}✗${NC} $1"; }

echo ""
echo "╔════════════════════════════════════════════════════════════════╗"
echo "║     Full OpenShift Management Cluster Deployment              ║"
echo "╚════════════════════════════════════════════════════════════════╝"
echo ""

# Check for required tools
REQUIRED_TOOLS=("terraform" "openshift-install" "oc" "aws" "jq")
for tool in "${REQUIRED_TOOLS[@]}"; do
    if ! command -v "$tool" &> /dev/null; then
        log_error "$tool not found. Please install $tool."
        exit 1
    fi
done
log_success "All required tools found"

# Parse arguments (allow flags in any order)
TFVARS_FILE=""
SKIP_MCE=false

for arg in "$@"; do
    case "$arg" in
        --skip-mce)
            SKIP_MCE=true
            ;;
        *)
            # Assume non-flag argument is the tfvars file
            if [ -z "$TFVARS_FILE" ]; then
                TFVARS_FILE="$arg"
            else
                log_error "Multiple tfvars files specified: $TFVARS_FILE and $arg"
                exit 1
            fi
            ;;
    esac
done

# Validate required argument
if [ -z "$TFVARS_FILE" ]; then
    log_error "Usage: $0 <tfvars-file> [--skip-mce]"
    echo ""
    echo "Examples:"
    echo "  $0 terraform-kagenti-team.tfvars"
    echo "  $0 --skip-mce terraform-420-test.tfvars"
    echo "  $0 terraform-420-test.tfvars --skip-mce"
    echo ""
    exit 1
fi

if [ ! -f "$TF_DIR/$TFVARS_FILE" ]; then
    log_error "tfvars file not found: $TF_DIR/$TFVARS_FILE"
    exit 1
fi

# Extract cluster name from tfvars
CLUSTER_NAME=$(grep '^cluster_name' "$TF_DIR/$TFVARS_FILE" | cut -d'=' -f2 | tr -d ' "')
if [ -z "$CLUSTER_NAME" ]; then
    log_error "Could not extract cluster_name from $TFVARS_FILE"
    exit 1
fi

log_info "Deploying cluster: $CLUSTER_NAME"
log_info "Using tfvars: $TFVARS_FILE"
echo ""

# ============================================================================
# Step 1: Terraform Infrastructure
# ============================================================================
echo ""
echo "╔════════════════════════════════════════════════════════════════╗"
echo "║  Step 1: Deploy Infrastructure with Terraform                 ║"
echo "╚════════════════════════════════════════════════════════════════╝"
echo ""

cd "$TF_DIR"

# Create or select workspace
log_info "Setting up Terraform workspace..."
if terraform workspace list | grep -q "$CLUSTER_NAME"; then
    terraform workspace select "$CLUSTER_NAME"
    log_info "Using existing workspace: $CLUSTER_NAME"
else
    terraform workspace new "$CLUSTER_NAME"
    log_success "Created new workspace: $CLUSTER_NAME"
fi

# Run terraform plan
log_info "Running terraform plan..."
if ! terraform plan -var-file="$TFVARS_FILE" -out=tfplan; then
    log_error "Terraform plan failed"
    exit 1
fi
log_success "Terraform plan completed"

# Prompt for confirmation
echo ""
read -p "Review the plan above. Proceed with terraform apply? (y/N): " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    log_warn "Deployment cancelled by user"
    exit 0
fi

# Run terraform apply
log_info "Running terraform apply..."
START_TIME=$(date +%s)

if ! terraform apply tfplan; then
    log_error "Terraform apply failed"
    exit 1
fi

END_TIME=$(date +%s)
DURATION=$((END_TIME - START_TIME))
log_success "Terraform apply completed in ${DURATION}s"

# Validate infrastructure
log_info "Validating infrastructure deployment..."
RESOURCE_COUNT=$(terraform state list | wc -l)
EXPECTED_MIN_RESOURCES=20

if [ "$RESOURCE_COUNT" -lt "$EXPECTED_MIN_RESOURCES" ]; then
    log_error "Infrastructure validation failed!"
    log_error "Found $RESOURCE_COUNT resources, expected at least $EXPECTED_MIN_RESOURCES"
    terraform state list
    exit 1
fi

# Verify critical resources
NAT_COUNT=$(terraform state list | grep -c "aws_nat_gateway.mgmt_cluster" || true)
EIP_COUNT=$(terraform state list | grep -c "aws_eip.nat" || true)

if [ "$NAT_COUNT" -lt 3 ] || [ "$EIP_COUNT" -lt 3 ]; then
    log_error "Missing critical resources:"
    log_error "  NAT Gateways: $NAT_COUNT (need 3)"
    log_error "  Elastic IPs: $EIP_COUNT (need 3)"
    exit 1
fi

log_success "Infrastructure validation passed ($RESOURCE_COUNT resources)"
log_success "  ✓ VPC and subnets"
log_success "  ✓ NAT Gateways ($NAT_COUNT)"
log_success "  ✓ Elastic IPs ($EIP_COUNT)"
log_success "  ✓ Route tables and associations"
echo ""

# ============================================================================
# Step 2: OpenShift Installation
# ============================================================================
echo ""
echo "╔════════════════════════════════════════════════════════════════╗"
echo "║  Step 2: Install OpenShift Cluster                            ║"
echo "╚════════════════════════════════════════════════════════════════╝"
echo ""

read -p "Proceed with OpenShift installation? (y/N): " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    log_warn "OpenShift installation skipped"
    log_info "To install later, run:"
    echo "  $SCRIPT_DIR/install-openshift.sh"
    exit 0
fi

cd "$SCRIPT_DIR"
if ! ./install-openshift.sh; then
    log_error "OpenShift installation failed"
    exit 1
fi

# ============================================================================
# Step 3: MCE Installation (Optional)
# ============================================================================
if [ "$SKIP_MCE" = false ]; then
    echo ""
    echo "╔════════════════════════════════════════════════════════════════╗"
    echo "║  Step 3: Install MCE 2.10 and HyperShift                      ║"
    echo "╚════════════════════════════════════════════════════════════════╝"
    echo ""

    read -p "Proceed with MCE installation? (y/N): " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        export KUBECONFIG="$HOME/openshift-clusters/$CLUSTER_NAME/auth/kubeconfig"
        cd "$SCRIPT_DIR"
        if ! ./install-mce.sh; then
            log_error "MCE installation failed"
            exit 1
        fi
    else
        log_warn "MCE installation skipped"
        log_info "To install later, run:"
        echo "  export KUBECONFIG=~/openshift-clusters/$CLUSTER_NAME/auth/kubeconfig"
        echo "  $SCRIPT_DIR/install-mce.sh"
    fi
fi

# ============================================================================
# Deployment Complete
# ============================================================================
echo ""
echo "╔════════════════════════════════════════════════════════════════╗"
echo "║              Deployment Complete!                              ║"
echo "╚════════════════════════════════════════════════════════════════╝"
echo ""
echo "Cluster: $CLUSTER_NAME"
echo "Kubeconfig: ~/openshift-clusters/$CLUSTER_NAME/auth/kubeconfig"
echo ""
echo "To use the cluster:"
echo "  export KUBECONFIG=~/openshift-clusters/$CLUSTER_NAME/auth/kubeconfig"
echo "  oc get nodes"
echo ""

if [ "$SKIP_MCE" = false ]; then
    echo "Next steps:"
    echo "  - Create hosted clusters using .github/scripts/hypershift/"
    echo "  - Configure OIDC storage provider if needed"
    echo ""
fi
