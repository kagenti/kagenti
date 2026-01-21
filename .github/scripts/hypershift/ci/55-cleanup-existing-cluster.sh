#!/usr/bin/env bash
# Cleanup any existing cluster from cancelled runs
# Uses run-full-test.sh --include-destroy to ensure CI and local use the same cleanup logic
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="${GITHUB_WORKSPACE:-$(cd "$SCRIPT_DIR/../../../.." && pwd)}"

CLUSTER_NAME="${MANAGED_BY_TAG}-${CLUSTER_SUFFIX}"
CONTROL_PLANE_NS="clusters-$CLUSTER_NAME"

echo "Checking for existing cluster: $CLUSTER_NAME"

# Check if HostedCluster OR its namespace exists (namespace can be orphaned)
HC_EXISTS=false
NS_EXISTS=false

if oc get hostedcluster "$CLUSTER_NAME" -n clusters &>/dev/null; then
    HC_EXISTS=true
    echo "Found existing HostedCluster"
fi

if oc get ns "$CONTROL_PLANE_NS" &>/dev/null; then
    NS_EXISTS=true
    echo "Found existing control plane namespace: $CONTROL_PLANE_NS"
fi

if [ "$HC_EXISTS" = "true" ] || [ "$NS_EXISTS" = "true" ]; then
    echo "Cleaning up existing cluster resources..."

    # Use run-full-test.sh --include-destroy for consistent cleanup logic
    # run-full-test.sh now detects CI mode (GITHUB_ACTIONS env var) and skips .env loading
    "$REPO_ROOT/.github/scripts/hypershift/run-full-test.sh" \
        --include-destroy \
        "$CLUSTER_SUFFIX" || true

    # Verify cleanup completed
    if oc get hostedcluster "$CLUSTER_NAME" -n clusters &>/dev/null; then
        echo "::warning::HostedCluster still exists after cleanup"
    fi

    if oc get ns "$CONTROL_PLANE_NS" &>/dev/null; then
        echo "::warning::Control plane namespace still exists after cleanup"
        # Force delete namespace as last resort
        echo "Force-deleting orphaned namespace..."
        oc delete ns "$CONTROL_PLANE_NS" --wait=false 2>/dev/null || true
        oc patch ns "$CONTROL_PLANE_NS" -p '{"metadata":{"finalizers":null}}' --type=merge 2>/dev/null || true

        # Wait for namespace deletion
        for i in {1..12}; do
            if ! oc get ns "$CONTROL_PLANE_NS" &>/dev/null; then
                echo "Namespace deleted"
                break
            fi
            echo "Waiting for namespace deletion... ($i/12)"
            sleep 5
        done
    fi

    echo "Cleanup complete"
else
    echo "No existing cluster or namespace found, proceeding with creation"
fi
