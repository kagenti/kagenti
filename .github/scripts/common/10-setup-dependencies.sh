#!/usr/bin/env bash
# Setup Dependencies (Wave 10)
# Installs Python dependencies, Ansible, and collections

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../lib/env-detect.sh"
source "$SCRIPT_DIR/../lib/logging.sh"

log_step "10" "Setting up Python and Ansible dependencies"

if [ "$IS_CI" = true ]; then
    log_info "Running in CI - installing Python/Ansible dependencies"

    # Install uv for Python package management
    log_info "Installing uv..."
    python -m pip install --upgrade pip
    pip install uv

    # Install jq for JSON processing
    log_info "Installing jq..."
    sudo apt-get update -qq && sudo apt-get install -y jq

    # Install Ansible and Kubernetes Python libraries
    log_info "Installing Ansible and dependencies..."
    pip install ansible PyYAML kubernetes openshift

    # Install Ansible collections
    log_info "Installing Ansible collections..."
    ansible-galaxy collection install -r "$REPO_ROOT/deployments/ansible/collections-reqs.yml"
else
    log_info "Running locally - checking dependencies"

    # Check if required tools are installed
    command -v python3 >/dev/null 2>&1 || log_warn "Python 3 not found"
    command -v kubectl >/dev/null 2>&1 || log_warn "kubectl not found"
    command -v helm >/dev/null 2>&1 || log_warn "helm not found"

    # Install jq if missing (macOS)
    if ! command -v jq >/dev/null 2>&1; then
        if [ "$IS_MACOS" = true ]; then
            log_info "Installing jq via brew"
            brew install jq || log_warn "Failed to install jq"
        fi
    fi

    # Install Ansible if missing
    if ! command -v ansible-playbook >/dev/null 2>&1; then
        log_info "Installing Ansible"
        pip install ansible PyYAML kubernetes openshift
    fi

    # Install Ansible collections
    ansible-galaxy collection install -r "$REPO_ROOT/deployments/ansible/collections-reqs.yml"
fi

log_success "Python and Ansible dependencies setup complete"
