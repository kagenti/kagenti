#!/usr/bin/env bash
# Run E2E tests on HyperShift cluster
# This script sets up the environment and calls 90-run-e2e-tests.sh
set -euo pipefail

echo "Running E2E tests..."

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="${GITHUB_WORKSPACE:-$(cd "$SCRIPT_DIR/../../../.." && pwd)}"

# Get agent URL via OpenShift route
ROUTE_HOST=$(oc get route -n team1 weather-service -o jsonpath='{.spec.host}' 2>/dev/null || echo "")
if [ -n "$ROUTE_HOST" ]; then
    export AGENT_URL="https://$ROUTE_HOST"
    echo "Agent URL: $AGENT_URL"
else
    echo "::warning::weather-service route not found"
    # Fallback to localhost (90-run-e2e-tests.sh default)
    export AGENT_URL="http://localhost:8000"
fi

# KAGENTI_CONFIG_FILE should be passed in from the workflow, default to ocp_values
export KAGENTI_CONFIG_FILE="${KAGENTI_CONFIG_FILE:-deployments/envs/ocp_values.yaml}"
echo "Config file: $KAGENTI_CONFIG_FILE"

# Install test dependencies first (90-run-e2e-tests.sh assumes pytest is available)
pip install -e ".[test]"

# Run the shared E2E test script
exec "$REPO_ROOT/.github/scripts/kagenti-operator/90-run-e2e-tests.sh"
