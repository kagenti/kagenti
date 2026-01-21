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

        # Remove finalizers from resources in the namespace
        # Include HyperShift-specific resources that can block deletion
        for resource in clusters.cluster.x-k8s.io deployments hostedcontrolplane etcd secret configmap pvc; do
            resources=$(oc get "$resource" -n "$CONTROL_PLANE_NS" -o name 2>/dev/null || true)
            if [ -n "$resources" ]; then
                echo "$resources" | while read -r name; do
                    echo "  Removing finalizers from $name"
                    oc patch "$name" -n "$CONTROL_PLANE_NS" -p '{"metadata":{"finalizers":null}}' --type=merge 2>/dev/null || true
                done
            fi
        done

        oc delete ns "$CONTROL_PLANE_NS" --wait=false 2>/dev/null || true
        oc patch ns "$CONTROL_PLANE_NS" -p '{"metadata":{"finalizers":null}}' --type=merge 2>/dev/null || true

        # Wait for namespace deletion (up to 5 minutes)
        NS_DELETED=false
        for i in {1..60}; do
            if ! oc get ns "$CONTROL_PLANE_NS" &>/dev/null; then
                echo "Namespace deleted"
                NS_DELETED=true
                break
            fi
            echo "Waiting for namespace deletion... ($i/60)"
            sleep 5
        done

        # Warn if namespace still exists but continue - create step will fail if there's a real conflict
        if [ "$NS_DELETED" = "false" ]; then
            echo "::warning::Namespace $CONTROL_PLANE_NS still exists after 5 minutes - continuing anyway"
            echo "The create step may fail if there's a resource conflict."
        fi
    fi

    echo "Cleanup complete"
else
    echo "No existing cluster or namespace found, proceeding with creation"
fi
