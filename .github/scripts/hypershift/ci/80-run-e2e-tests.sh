#!/usr/bin/env bash
# Run E2E tests on HyperShift cluster
# This script installs test dependencies and calls hypershift-full-test.sh with --include-test
set -euo pipefail

echo "Running E2E tests..."

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="${GITHUB_WORKSPACE:-$(cd "$SCRIPT_DIR/../../../.." && pwd)}"

cd "$REPO_ROOT"

# Install uv for reproducible installs (respects uv.lock)
if ! command -v uv &>/dev/null; then
    echo "Installing uv..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.local/bin:$PATH"
fi

# Install test dependencies with locked versions
uv sync --extra test

# Use hypershift-full-test.sh with whitelist mode (--include-test)
# hypershift-full-test.sh handles AGENT_URL detection from route and calls 90-run-e2e-tests.sh
# Note: CLUSTER_SUFFIX is set by the workflow (e.g., pr594), don't override it
exec "$REPO_ROOT/.github/scripts/local-setup/hypershift-full-test.sh" \
    --include-test \
    --env ocp
