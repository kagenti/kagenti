#!/usr/bin/env bash
#
# Terraform Apply Wrapper for HyperShift Infrastructure
#
# Creates AWS infrastructure (VPC, IAM, networking) for HyperShift cluster
#
# USAGE:
#   ./.github/scripts/hypershift/terraform/apply.sh <environment> <cluster-name>
#
# EXAMPLES:
#   ./.github/scripts/hypershift/terraform/apply.sh 4.20 kagenti-hypershift-custom-test
#

set -euo pipefail

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

# Validate arguments
if [ $# -lt 2 ]; then
    echo "Usage: $0 <environment> <cluster-name>" >&2
    echo "" >&2
    echo "Examples:" >&2
    echo "  $0 4.20 kagenti-hypershift-custom-test" >&2
    echo "  $0 4.20 kagenti-hypershift-ci-123" >&2
    exit 1
fi

ENVIRONMENT="$1"
CLUSTER_NAME="$2"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../../.." && pwd)"
TF_ENV_DIR="$REPO_ROOT/terraform/environments/$ENVIRONMENT"

echo ""
echo "╔════════════════════════════════════════════════════════════════╗"
echo "║         Terraform Apply - HyperShift Infrastructure            ║"
echo "╚════════════════════════════════════════════════════════════════╝"
echo ""

# Validate environment directory exists
if [ ! -d "$TF_ENV_DIR" ]; then
    log_error "Environment directory not found: $TF_ENV_DIR"
    log_error "Available environments:"
    ls -1 "$REPO_ROOT/terraform/environments/" 2>/dev/null | sed 's/^/  - /'
    exit 1
fi

cd "$TF_ENV_DIR"

# Check if terraform.tfvars exists
if [ ! -f terraform.tfvars ]; then
    log_warn "terraform.tfvars not found"
    if [ -f terraform.tfvars.example ]; then
        log_info "Creating terraform.tfvars from example..."
        cp terraform.tfvars.example terraform.tfvars
        log_warn "Please edit terraform.tfvars with your configuration"
        log_info "File location: $TF_ENV_DIR/terraform.tfvars"
        exit 1
    else
        log_error "No terraform.tfvars or terraform.tfvars.example found"
        exit 1
    fi
fi

# Override cluster_name from argument
export TF_VAR_cluster_name="$CLUSTER_NAME"

log_info "Terraform environment: $ENVIRONMENT"
log_info "Cluster name: $CLUSTER_NAME"
log_info "Working directory: $TF_ENV_DIR"
echo ""

# Initialize Terraform
log_info "Initializing Terraform..."
terraform init -upgrade

# Validate configuration
log_info "Validating Terraform configuration..."
terraform validate

# Plan
log_info "Planning infrastructure changes..."
terraform plan -out=tfplan

# Prompt for apply (skip in CI)
if [ "${CI:-false}" != "true" ] && [ "${AUTO_APPROVE:-false}" != "true" ]; then
    echo ""
    read -p "Apply these changes? (yes/no): " -r
    if [[ ! $REPLY =~ ^[Yy]es$ ]]; then
        log_warn "Apply cancelled"
        rm -f tfplan
        exit 0
    fi
fi

# Apply
log_info "Applying infrastructure changes..."
terraform apply tfplan
rm -f tfplan

# Show outputs
echo ""
log_success "Infrastructure created successfully"
echo ""
log_info "Infrastructure Outputs:"
terraform output

# Save outputs to file for Ansible integration
OUTPUT_FILE="$TF_ENV_DIR/terraform-outputs.json"
terraform output -json > "$OUTPUT_FILE"
log_success "Outputs saved to: $OUTPUT_FILE"

echo ""
echo "╔════════════════════════════════════════════════════════════════╗"
echo "║                  Infrastructure Ready                          ║"
echo "╚════════════════════════════════════════════════════════════════╝"
echo ""
