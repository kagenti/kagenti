#!/usr/bin/env bash
# Setup Dependencies (Wave 10)
# Installs Python dependencies and tools

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../lib/env-detect.sh"
source "$SCRIPT_DIR/../lib/logging.sh"

log_step "10" "Setting up dependencies"

if [ "$IS_CI" = true ]; then
    log_info "Running in CI - installing dependencies"

    # Install uv for Python package management
    log_info "Installing uv..."
    python -m pip install --upgrade pip
    pip install uv

    # Install jq for JSON processing
    log_info "Installing jq..."
    sudo apt-get update -qq && sudo apt-get install -y jq
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
fi

log_success "Dependencies setup complete"
