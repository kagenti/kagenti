#!/usr/bin/env bash
#
# Terraform Destroy Wrapper for HyperShift Infrastructure
#
# Destroys AWS infrastructure (VPC, IAM, networking) created by Terraform
#
# USAGE:
#   ./.github/scripts/hypershift/terraform/destroy.sh <environment> <cluster-name>
#
# EXAMPLES:
#   ./.github/scripts/hypershift/terraform/destroy.sh 4.20 kagenti-hypershift-custom-test
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
echo "║        Terraform Destroy - HyperShift Infrastructure           ║"
echo "╚════════════════════════════════════════════════════════════════╝"
echo ""

# Validate environment directory exists
if [ ! -d "$TF_ENV_DIR" ]; then
    log_error "Environment directory not found: $TF_ENV_DIR"
    exit 1
fi

cd "$TF_ENV_DIR"

# Check if Terraform state exists
if [ ! -f terraform.tfstate ] && [ ! -f .terraform/terraform.tfstate ]; then
    log_warn "No Terraform state found - nothing to destroy"
    exit 0
fi

# Override cluster_name from argument
export TF_VAR_cluster_name="$CLUSTER_NAME"

log_info "Terraform environment: $ENVIRONMENT"
log_info "Cluster name: $CLUSTER_NAME"
log_info "Working directory: $TF_ENV_DIR"
echo ""

# Initialize Terraform (in case modules changed)
log_info "Initializing Terraform..."
terraform init

# Plan destroy
log_info "Planning infrastructure destruction..."
terraform plan -destroy -out=tfplan-destroy

# Prompt for destroy (skip in CI)
if [ "${CI:-false}" != "true" ] && [ "${AUTO_APPROVE:-false}" != "true" ]; then
    echo ""
    log_warn "This will destroy all Terraform-managed infrastructure for cluster: $CLUSTER_NAME"
    read -p "Destroy infrastructure? (yes/no): " -r
    if [[ ! $REPLY =~ ^[Yy]es$ ]]; then
        log_warn "Destroy cancelled"
        rm -f tfplan-destroy
        exit 0
    fi
fi

# Destroy
log_info "Destroying infrastructure..."
terraform apply tfplan-destroy
rm -f tfplan-destroy

# Cleanup outputs file
OUTPUT_FILE="$TF_ENV_DIR/terraform-outputs.json"
if [ -f "$OUTPUT_FILE" ]; then
    rm -f "$OUTPUT_FILE"
    log_info "Removed outputs file: $OUTPUT_FILE"
fi

echo ""
log_success "Infrastructure destroyed successfully"
echo ""
