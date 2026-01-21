#!/usr/bin/env bash
# Deploy Kagenti to HyperShift cluster
# This script is a thin wrapper that calls the shared kagenti-operator scripts.
# This ensures CI and local development use the same code paths.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="${GITHUB_WORKSPACE:-$(cd "$SCRIPT_DIR/../../../.." && pwd)}"

echo "Deploying Kagenti to cluster..."

# Set Python interpreter for Ansible (required in CI where .venv doesn't exist)
export ANSIBLE_PYTHON_INTERPRETER=$(which python3)

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

# Step 1: Install Kagenti platform (uses shared script)
echo "=== Installing Kagenti platform ==="
"$REPO_ROOT/.github/scripts/kagenti-operator/30-run-installer.sh" --env ocp

# Step 2: Wait for CRDs
echo "=== Waiting for CRDs ==="
"$REPO_ROOT/.github/scripts/kagenti-operator/41-wait-crds.sh"

# Step 3: Apply pipeline template
echo "=== Applying pipeline template ==="
"$REPO_ROOT/.github/scripts/kagenti-operator/42-apply-pipeline-template.sh"

# Step 4: Wait for Toolhive CRDs
echo "=== Waiting for Toolhive CRDs ==="
"$REPO_ROOT/.github/scripts/kagenti-operator/43-wait-toolhive-crds.sh"

# Step 5: Build weather-tool
echo "=== Building weather-tool ==="
"$REPO_ROOT/.github/scripts/kagenti-operator/71-build-weather-tool.sh"

# Step 6: Deploy weather-tool
echo "=== Deploying weather-tool ==="
"$REPO_ROOT/.github/scripts/kagenti-operator/72-deploy-weather-tool.sh"

# Step 7: Patch weather-tool
echo "=== Patching weather-tool ==="
"$REPO_ROOT/.github/scripts/kagenti-operator/73-patch-weather-tool.sh"

# Step 8: Deploy weather-agent
echo "=== Deploying weather-agent ==="
"$REPO_ROOT/.github/scripts/kagenti-operator/74-deploy-weather-agent.sh"

echo "Kagenti deployment complete"
