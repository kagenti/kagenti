#!/usr/bin/env bash
# Collect cluster info on failure for debugging
set -euo pipefail

# Required environment variables:
# - CLUSTER_NAME or (MANAGED_BY_TAG + CLUSTER_SUFFIX): The cluster name
# - MGMT_KUBECONFIG: Management cluster kubeconfig (for HostedCluster/NodePool info)
# - KUBECONFIG: Hosted cluster kubeconfig (optional, for pod/event info)

CLUSTER_NAME="${CLUSTER_NAME:-${MANAGED_BY_TAG:-kagenti-hypershift-ci}-${CLUSTER_SUFFIX:-}}"
MGMT_KUBECONFIG="${MGMT_KUBECONFIG:-}"
AWS_REGION="${AWS_REGION:-us-east-1}"

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "DIAGNOSTIC INFO FOR CLUSTER: $CLUSTER_NAME"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# Management cluster diagnostics
if [ -n "$MGMT_KUBECONFIG" ] && [ -f "$MGMT_KUBECONFIG" ]; then
    echo ""
    echo "=== HostedCluster Status (Management Cluster) ==="
    KUBECONFIG="$MGMT_KUBECONFIG" oc get hostedcluster -n clusters "$CLUSTER_NAME" -o wide 2>/dev/null || echo "(not found)"

    echo ""
    echo "=== HostedCluster Conditions ==="
    KUBECONFIG="$MGMT_KUBECONFIG" oc get hostedcluster -n clusters "$CLUSTER_NAME" \
        -o jsonpath='{range .status.conditions[*]}{.type}{": "}{.status}{" - "}{.message}{"\n"}{end}' 2>/dev/null || echo "(not available)"

    echo ""
    echo "=== NodePool Status ==="
    KUBECONFIG="$MGMT_KUBECONFIG" oc get nodepool -n clusters "$CLUSTER_NAME" -o wide 2>/dev/null || echo "(not found)"

    echo ""
    echo "=== NodePool Conditions ==="
    KUBECONFIG="$MGMT_KUBECONFIG" oc get nodepool -n clusters "$CLUSTER_NAME" \
        -o jsonpath='{range .status.conditions[*]}{.type}{": "}{.status}{" - "}{.message}{"\n"}{end}' 2>/dev/null || echo "(not available)"

    echo ""
    echo "=== Machine Status ==="
    KUBECONFIG="$MGMT_KUBECONFIG" oc get machines -n "clusters-$CLUSTER_NAME" 2>/dev/null || echo "(not found)"
else
    echo ""
    echo "(Management cluster diagnostics skipped - MGMT_KUBECONFIG not set or file not found)"
fi

# AWS diagnostics
echo ""
echo "=== EC2 Instances ==="
aws ec2 describe-instances --region "$AWS_REGION" \
    --filters "Name=tag-key,Values=kubernetes.io/cluster/$CLUSTER_NAME" \
    --query 'Reservations[*].Instances[*].[InstanceId,State.Name,InstanceType,LaunchTime]' \
    --output table 2>/dev/null || echo "(AWS CLI not available or no instances found)"

# Hosted cluster diagnostics (only if KUBECONFIG is set and cluster is reachable)
if [ -n "${KUBECONFIG:-}" ] && [ -f "${KUBECONFIG:-}" ]; then
    echo ""
    echo "=== Hosted Cluster Status ==="
    oc get nodes 2>/dev/null || echo "(cluster not reachable)"
    oc get clusterversion 2>/dev/null || true

    echo ""
    echo "=== Pods in kagenti-system ==="
    oc get pods -n kagenti-system 2>/dev/null || echo "(namespace not found or cluster not reachable)"

    echo ""
    echo "=== Recent Events ==="
    oc get events -A --sort-by='.lastTimestamp' 2>/dev/null | tail -50 || echo "(events not available)"
else
    echo ""
    echo "(Hosted cluster diagnostics skipped - KUBECONFIG not set or cluster not reachable)"
fi

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
