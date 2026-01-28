#!/usr/bin/env bash
# Deploy Kagenti to HyperShift cluster
# This script is a thin wrapper that calls hypershift-full-test.sh with appropriate options.
# This ensures CI and local development use the exact same code paths.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="${GITHUB_WORKSPACE:-$(cd "$SCRIPT_DIR/../../../.." && pwd)}"

echo "Deploying Kagenti to cluster..."

# Set Python interpreter for Ansible (required in CI where .venv doesn't exist)
ANSIBLE_PYTHON_INTERPRETER=$(which python3)
export ANSIBLE_PYTHON_INTERPRETER

# Create minimal secrets file for CI with auto-generated values
SECRETS_FILE="$REPO_ROOT/deployments/envs/.secret_values.yaml"
if [ ! -f "$SECRETS_FILE" ]; then
    echo "Creating minimal secrets file for CI..."
    cat > "$SECRETS_FILE" << 'EOF'
# Auto-generated secrets for CI
global: {}
charts:
  kagenti:
    values:
      secrets:
        # Placeholder - not needed for basic E2E tests
        githubUser: "ci-user"
        githubToken: "ci-token-placeholder"
EOF
fi

cd "$REPO_ROOT"

# Use hypershift-full-test.sh with whitelist mode (--include-X flags)
# This runs: install + agents only
exec "$REPO_ROOT/.github/scripts/local-setup/hypershift-full-test.sh" \
    --include-kagenti-install \
    --include-agents \
    --env ocp \
    ci
