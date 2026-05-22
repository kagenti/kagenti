#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../lib/env-detect.sh"
source "$SCRIPT_DIR/../lib/logging.sh"

log_step "80" "Installing test dependencies"

cd "$REPO_ROOT"

# Use uv for reproducible installs (respects uv.lock)
# This ensures CI uses the exact same package versions as local development
if ! command -v uv &>/dev/null; then
    log_info "Installing uv..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.local/bin:$PATH"
fi

log_info "Installing dependencies with uv sync (locked versions)..."
uv sync --extra test

log_success "Test dependencies installed (via uv)"
