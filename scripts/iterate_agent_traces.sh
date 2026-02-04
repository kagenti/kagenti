#!/bin/bash
#
# Iteration workflow for agent trace instrumentation testing.
#
# This script helps iterate on agent instrumentation to populate
# MLflow and Phoenix UI table columns.
#
# Usage:
#   ./scripts/iterate_agent_traces.sh [step]
#
# Steps:
#   rebuild   - Rebuild and redeploy the weather agent
#   traffic   - Generate agent traffic (run conversation test)
#   verify    - Verify UI columns are populated
#   all       - Run all steps in sequence
#

set -e

# Configuration
KUBECONFIG="${KUBECONFIG:-$HOME/clusters/hcp/kagenti-hypershift-custom-mlflow/auth/kubeconfig}"
export KUBECONFIG

AGENT_NAMESPACE="team1"
AGENT_BUILD="weather-service"

echo "=========================================="
echo "Agent Trace Iteration Workflow"
echo "=========================================="
echo "KUBECONFIG: $KUBECONFIG"
echo ""

step="${1:-all}"

# Step 1: Rebuild agent
rebuild_agent() {
    echo "----------------------------------------"
    echo "STEP 1: Rebuilding weather agent..."
    echo "----------------------------------------"

    # Delete existing buildrun to trigger new build
    echo "Deleting existing buildruns..."
    kubectl delete buildrun -n "$AGENT_NAMESPACE" -l build.shipwright.io/name="$AGENT_BUILD" --ignore-not-found

    # Wait for new build to start
    echo "Waiting for new buildrun to start..."
    for i in {1..30}; do
        buildrun=$(kubectl get buildrun -n "$AGENT_NAMESPACE" -l build.shipwright.io/name="$AGENT_BUILD" -o name 2>/dev/null | head -1)
        if [ -n "$buildrun" ]; then
            echo "New buildrun: $buildrun"
            break
        fi
        echo "Waiting for buildrun... ($i/30)"
        sleep 2
    done

    # Wait for build to complete
    echo "Waiting for build to complete..."
    kubectl wait --for=condition=Succeeded buildrun -n "$AGENT_NAMESPACE" -l build.shipwright.io/name="$AGENT_BUILD" --timeout=300s || {
        echo "Build may have failed. Checking status..."
        kubectl get buildrun -n "$AGENT_NAMESPACE" -l build.shipwright.io/name="$AGENT_BUILD"
        kubectl logs -n "$AGENT_NAMESPACE" -l build.shipwright.io/name="$AGENT_BUILD" --tail=50 || true
        return 1
    }

    # Restart deployment to pick up new image
    echo "Restarting deployment..."
    kubectl rollout restart deployment/"$AGENT_BUILD" -n "$AGENT_NAMESPACE"
    kubectl rollout status deployment/"$AGENT_BUILD" -n "$AGENT_NAMESPACE" --timeout=120s

    echo "Agent rebuilt and deployed successfully!"
}

# Step 2: Generate traffic
generate_traffic() {
    echo "----------------------------------------"
    echo "STEP 2: Generating agent traffic..."
    echo "----------------------------------------"

    # Run conversation test
    ./.github/scripts/local-setup/hypershift-full-test.sh mlflow --include-test --pytest-filter "test_agent_conversation"

    echo "Traffic generated successfully!"
}

# Step 3: Verify UI columns
verify_columns() {
    echo "----------------------------------------"
    echo "STEP 3: Verifying UI columns..."
    echo "----------------------------------------"

    # Wait for traces to propagate
    echo "Waiting 10s for traces to propagate..."
    sleep 10

    # Run verification script
    uv run python scripts/verify_ui_columns.py

    echo ""
    echo "Verification complete!"
}

# Run steps based on argument
case "$step" in
    rebuild)
        rebuild_agent
        ;;
    traffic)
        generate_traffic
        ;;
    verify)
        verify_columns
        ;;
    all)
        rebuild_agent
        generate_traffic
        verify_columns
        ;;
    *)
        echo "Usage: $0 [rebuild|traffic|verify|all]"
        exit 1
        ;;
esac

echo ""
echo "=========================================="
echo "Done!"
echo "=========================================="
