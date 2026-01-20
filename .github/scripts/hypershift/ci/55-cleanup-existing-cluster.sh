#!/usr/bin/env bash
# Cleanup any existing cluster from cancelled runs
set -euo pipefail

CLUSTER_NAME="${MANAGED_BY_TAG}-${CLUSTER_SUFFIX}"
echo "Checking for existing cluster: $CLUSTER_NAME"

# Check if HostedCluster exists
if oc get hostedcluster "$CLUSTER_NAME" -n clusters &>/dev/null; then
    echo "Found existing cluster, destroying it first..."
    cd /tmp/hypershift-automation

    ansible-playbook site.yml \
        -e '{"destroy": true, "create_iam": false}' \
        -e '{"iam": {"hcp_role_name": "'"$HCP_ROLE_NAME"'"}}' \
        -e '{"clusters": [{"name": "'"$CLUSTER_NAME"'", "region": "'"$AWS_REGION"'"}]}' || true

    # Wait for cleanup to complete
    echo "Waiting for cluster to be fully destroyed..."
    for i in {1..30}; do
        if ! oc get hostedcluster "$CLUSTER_NAME" -n clusters &>/dev/null; then
            echo "Cluster destroyed successfully"
            break
        fi
        echo "Waiting... ($i/30)"
        sleep 10
    done
else
    echo "No existing cluster found, proceeding with creation"
fi
