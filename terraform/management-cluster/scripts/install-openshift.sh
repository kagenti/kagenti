#!/usr/bin/env bash
#
# Install OpenShift on pre-provisioned infrastructure
#
# This script uses the Terraform-created infrastructure to install OpenShift
# via the openshift-install IPI method.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TF_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
REPO_ROOT="$(cd "$TF_DIR/../.." && pwd)"

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
echo "║          Install OpenShift Management Cluster (IPI)           ║"
echo "╚════════════════════════════════════════════════════════════════╝"
echo ""

# Check prerequisites
# Prefer openshift-install from ~/bin (version-specific)
if [ -x "$HOME/bin/openshift-install" ]; then
    export PATH="$HOME/bin:$PATH"
fi

if ! command -v openshift-install &> /dev/null; then
    log_error "openshift-install not found"
    log_info "Download from: https://console.redhat.com/openshift/downloads"
    exit 1
fi

if ! command -v jq &> /dev/null; then
    log_error "jq not found. Please install jq."
    exit 1
fi

# Load cluster metadata from Terraform
METADATA_FILE="$TF_DIR/output/cluster-metadata.json"
if [ ! -f "$METADATA_FILE" ]; then
    log_error "Cluster metadata not found: $METADATA_FILE"
    log_info "Run 'terraform apply' in terraform/management-cluster first"
    exit 1
fi

CLUSTER_NAME=$(jq -r '.cluster_name' "$METADATA_FILE")
BASE_DOMAIN=$(jq -r '.base_domain' "$METADATA_FILE")
OCP_VERSION=$(jq -r '.ocp_version' "$METADATA_FILE")
AWS_REGION=$(jq -r '.aws_region' "$METADATA_FILE")

log_info "Cluster: $CLUSTER_NAME.$BASE_DOMAIN"
log_info "Version: $OCP_VERSION"
log_info "Region: $AWS_REGION"
echo ""

# Setup installation directory
INSTALL_DIR="$HOME/openshift-clusters/$CLUSTER_NAME"
if [ -d "$INSTALL_DIR" ]; then
    log_warn "Installation directory already exists: $INSTALL_DIR"
    read -p "Remove and continue? (y/N): " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        log_error "Aborted"
        exit 1
    fi
    rm -rf "$INSTALL_DIR"
fi

mkdir -p "$INSTALL_DIR"
log_success "Created install directory: $INSTALL_DIR"

# Load credentials
if [ -z "${PULL_SECRET:-}" ]; then
    if [ -f "$HOME/.pullsecret.json" ]; then
        PULL_SECRET=$(cat "$HOME/.pullsecret.json")
        log_success "Loaded pull secret from ~/.pullsecret.json"
    else
        log_error "PULL_SECRET not set and ~/.pullsecret.json not found"
        log_info "Get your pull secret from: https://console.redhat.com/openshift/install/pull-secret"
        exit 1
    fi
fi

# Generate SSH key if needed
SSH_KEY_PATH="$HOME/.ssh/openshift-$CLUSTER_NAME"
if [ ! -f "$SSH_KEY_PATH" ]; then
    log_info "Generating SSH key pair..."
    ssh-keygen -t ed25519 -f "$SSH_KEY_PATH" -N "" -C "openshift-$CLUSTER_NAME"
    log_success "Generated SSH key: $SSH_KEY_PATH"
fi
SSH_PUBLIC_KEY=$(cat "${SSH_KEY_PATH}.pub")

# Create install-config.yaml from template
log_info "Creating install-config.yaml..."
TEMPLATE_FILE="$TF_DIR/output/install-config.yaml.tpl"

if [ ! -f "$TEMPLATE_FILE" ]; then
    log_error "Template not found: $TEMPLATE_FILE"
    exit 1
fi

# Replace placeholders
sed \
    -e "s|PULL_SECRET_PLACEHOLDER|${PULL_SECRET}|" \
    -e "s|SSH_KEY_PLACEHOLDER|${SSH_PUBLIC_KEY}|" \
    "$TEMPLATE_FILE" > "$INSTALL_DIR/install-config.yaml"

# Save a backup
cp "$INSTALL_DIR/install-config.yaml" "$INSTALL_DIR/install-config.yaml.backup"
log_success "Created install-config.yaml"

echo ""
log_info "Starting OpenShift installation (this will take 30-45 minutes)..."
echo ""

# Run openshift-install
cd "$INSTALL_DIR"
openshift-install create cluster --dir "$INSTALL_DIR" --log-level=info

# Check if installation succeeded
if [ $? -eq 0 ]; then
    log_success "OpenShift installation completed!"
    echo ""
    echo "╔════════════════════════════════════════════════════════════════╗"
    echo "║                  Installation Complete                        ║"
    echo "╚════════════════════════════════════════════════════════════════╝"
    echo ""
    echo "Cluster details:"
    echo "  Console: https://console-openshift-console.apps.$CLUSTER_NAME.$BASE_DOMAIN"
    echo "  API: https://api.$CLUSTER_NAME.$BASE_DOMAIN:6443"
    echo ""
    echo "Credentials:"
    echo "  Kubeconfig: $INSTALL_DIR/auth/kubeconfig"
    echo "  Username: kubeadmin"
    echo "  Password: (see $INSTALL_DIR/auth/kubeadmin-password)"
    echo ""
    echo "Next step: Install MCE 2.10"
    echo "  $SCRIPT_DIR/install-mce.sh"
    echo ""

    # Export kubeconfig
    export KUBECONFIG="$INSTALL_DIR/auth/kubeconfig"

    # Verify cluster
    log_info "Verifying cluster..."
    oc get nodes
    oc get clusterversion

else
    log_error "OpenShift installation failed"
    log_info "Check logs in: $INSTALL_DIR/.openshift_install.log"
    exit 1
fi
