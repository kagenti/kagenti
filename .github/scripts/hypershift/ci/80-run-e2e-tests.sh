#!/usr/bin/env bash
# Run E2E tests on HyperShift cluster
# This script installs test dependencies and calls run-full-test.sh with --include-test
set -euo pipefail

echo "Running E2E tests..."

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="${GITHUB_WORKSPACE:-$(cd "$SCRIPT_DIR/../../../.." && pwd)}"

cd "$REPO_ROOT"

# Install test dependencies first (90-run-e2e-tests.sh assumes pytest is available)
pip install -e ".[test]"

# Use run-full-test.sh with whitelist mode (--include-test)
# run-full-test.sh handles AGENT_URL detection from route and calls 90-run-e2e-tests.sh
exec "$REPO_ROOT/.github/scripts/hypershift/run-full-test.sh" \
    --include-test \
    --env ocp \
    ci
