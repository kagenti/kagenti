#!/usr/bin/env bash
# Run E2E tests on HyperShift cluster
set -euo pipefail

echo "Running E2E tests..."

# Get agent URL via OpenShift route
AGENT_URL=$(oc get route -n team1 weather-service -o jsonpath='{.spec.host}' 2>/dev/null || echo "")
if [ -n "$AGENT_URL" ]; then
    export AGENT_URL="https://$AGENT_URL"
    echo "Agent URL: $AGENT_URL"
else
    echo "::warning::weather-service route not found"
fi

# Run tests from kagenti subdirectory
if [ -d "kagenti/tests/e2e" ]; then
    cd kagenti
    pip install -e .
    pytest tests/e2e/common tests/e2e/kagenti_operator -v --timeout=300 --tb=short || {
        echo "::error::E2E tests failed"
        exit 1
    }
else
    echo "::warning::E2E tests directory not found at kagenti/tests/e2e, skipping tests"
fi

echo "E2E tests complete"
