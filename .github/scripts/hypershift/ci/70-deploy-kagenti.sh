#!/usr/bin/env bash
# Deploy Kagenti to HyperShift cluster
set -euo pipefail

echo "Deploying Kagenti to cluster..."

# Set Python interpreter for Ansible (required in CI where .venv doesn't exist)
export ANSIBLE_PYTHON_INTERPRETER=$(which python3)

# Create minimal secrets file for CI with auto-generated values
SECRETS_FILE="deployments/envs/.secret_values.yaml"
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

# Check if deployments/ansible exists
if [ -d "deployments/ansible" ]; then
    cd deployments/ansible
    pip install -r requirements.txt 2>/dev/null || true
    ./run-install.sh --env ocp --no-kind
else
    echo "::warning::deployments/ansible not found, skipping Kagenti deployment"
fi

echo "Kagenti deployment complete"
