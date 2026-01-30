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

# Wait for cluster to be fully ready before deploying
# HyperShift clusters can take time for all components to initialize
echo "Waiting for cluster nodes to be ready..."
MAX_RETRIES=30
RETRY_DELAY=10
for i in $(seq 1 $MAX_RETRIES); do
    NOT_READY=$(kubectl get nodes --no-headers 2>/dev/null | grep -v " Ready" | wc -l || echo "999")
    TOTAL=$(kubectl get nodes --no-headers 2>/dev/null | wc -l || echo "0")
    if [[ "$NOT_READY" == "0" && "$TOTAL" -gt 0 ]]; then
        echo "All $TOTAL nodes are ready"
        break
    fi
    echo "[$i/$MAX_RETRIES] Waiting for nodes... ($((TOTAL - NOT_READY))/$TOTAL ready)"
    if [[ $i -eq $MAX_RETRIES ]]; then
        echo "ERROR: Nodes not ready after $((MAX_RETRIES * RETRY_DELAY)) seconds"
        kubectl get nodes
        exit 1
    fi
    sleep $RETRY_DELAY
done

# Wait for OLM (Operator Lifecycle Manager) to be available
# This is required for installing OpenShift operators via Subscriptions
echo "Waiting for OLM to be available..."
for i in $(seq 1 $MAX_RETRIES); do
    if kubectl api-resources | grep -q "subscriptions.*operators.coreos.com" 2>/dev/null; then
        echo "OLM Subscription API is available"
        break
    fi
    echo "[$i/$MAX_RETRIES] Waiting for OLM..."
    if [[ $i -eq $MAX_RETRIES ]]; then
        echo "WARNING: OLM not available after $((MAX_RETRIES * RETRY_DELAY)) seconds"
        echo "Continuing anyway - some operators may not install correctly"
    fi
    sleep $RETRY_DELAY
done

# Use hypershift-full-test.sh with whitelist mode (--include-X flags)
# This runs: install + agents only
exec "$REPO_ROOT/.github/scripts/local-setup/hypershift-full-test.sh" \
    --include-kagenti-install \
    --include-agents \
    --env ocp \
    ci
