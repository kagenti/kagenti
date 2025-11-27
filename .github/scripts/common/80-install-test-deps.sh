#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../lib/env-detect.sh"
source "$SCRIPT_DIR/../lib/logging.sh"

log_step "80" "Installing test dependencies"

cd "$REPO_ROOT"

# Upgrade pip to support editable installs with pyproject.toml
python3 -m pip install --upgrade pip setuptools wheel

# Install package in editable mode with test dependencies
python3 -m pip install -e .[test]

log_success "Test dependencies installed"
