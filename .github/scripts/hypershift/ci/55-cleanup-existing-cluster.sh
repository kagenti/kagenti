#!/usr/bin/env bash
# Cleanup any existing cluster from cancelled runs
# Uses hypershift-automation ansible playbook for AWS cleanup
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="${GITHUB_WORKSPACE:-$(cd "$SCRIPT_DIR/../../../.." && pwd)}"

# In CI, hypershift-automation is cloned to /tmp; locally it's a sibling directory
CI_MODE="${GITHUB_ACTIONS:-false}"
if [ "$CI_MODE" = "true" ]; then
    HYPERSHIFT_AUTOMATION_DIR="/tmp/hypershift-automation"
else
    PARENT_DIR="$(cd "$REPO_ROOT/.." && pwd)"
    HYPERSHIFT_AUTOMATION_DIR="$PARENT_DIR/hypershift-automation"
fi

CLUSTER_NAME="${MANAGED_BY_TAG}-${CLUSTER_SUFFIX}"
CONTROL_PLANE_NS="clusters-$CLUSTER_NAME"
CLUSTER_TAG="kubernetes.io/cluster/${CLUSTER_NAME}"

echo "Checking for existing cluster: $CLUSTER_NAME"

# ============================================================================
# Check for Orphaned AWS Resources
# If found, use hypershift-automation playbook with cluster_exists=true to cleanup
# ============================================================================

check_orphaned_aws_resources() {
    echo "Checking for orphaned AWS resources tagged with: $CLUSTER_TAG"

    # Check for orphaned VPCs
    ORPHANED_VPCS=$(aws ec2 describe-vpcs \
        --region "$AWS_REGION" \
        --filters "Name=tag:${CLUSTER_TAG},Values=owned" \
        --query 'Vpcs[*].VpcId' \
        --output text 2>/dev/null || echo "")

    if [ -n "$ORPHANED_VPCS" ] && [ "$ORPHANED_VPCS" != "None" ]; then
        echo "Found orphaned VPCs: $ORPHANED_VPCS"
        return 0  # orphaned resources exist
    else
        echo "No orphaned AWS resources found"
        return 1  # no orphaned resources
    fi
}

cleanup_orphaned_aws_resources() {
    echo "Cleaning up orphaned AWS resources using hypershift-automation playbook..."

    if [ ! -d "$HYPERSHIFT_AUTOMATION_DIR" ]; then
        echo "::error::hypershift-automation not found at $HYPERSHIFT_AUTOMATION_DIR"
        echo "Cannot cleanup orphaned AWS resources without the automation playbook."
        exit 1
    fi

    cd "$HYPERSHIFT_AUTOMATION_DIR"

    # Use ansible destroy playbook with cluster_exists=true to force cleanup
    # even when HostedCluster doesn't exist in Kubernetes
    # Note: cluster_exists must be passed as JSON boolean, not string
    ansible-playbook site.yml \
        -e '{"create": false, "destroy": true, "create_iam": false, "cluster_exists": true}' \
        -e '{"iam": {"hcp_role_name": "'"$HCP_ROLE_NAME"'"}}' \
        -e '{"clusters": [{"name": "'"$CLUSTER_NAME"'", "region": "'"$AWS_REGION"'"}]}' || true

    cd "$REPO_ROOT"

    # Verify VPCs are deleted (with retries - VPC deletion can take time)
    echo "Verifying VPC cleanup..."
    for attempt in {1..6}; do
        REMAINING_VPCS=$(aws ec2 describe-vpcs \
            --region "$AWS_REGION" \
            --filters "Name=tag:${CLUSTER_TAG},Values=owned" \
            --query 'Vpcs[*].VpcId' \
            --output text 2>/dev/null || echo "")

        if [ -z "$REMAINING_VPCS" ] || [ "$REMAINING_VPCS" = "None" ]; then
            echo "VPC cleanup verified - no orphaned VPCs remain"
            break
        fi

        if [ "$attempt" -eq 6 ]; then
            echo "::error::Failed to delete orphaned VPCs after 60s: $REMAINING_VPCS"
            # Show what's blocking VPC deletion
            echo "Checking for resources blocking VPC deletion:"
            for vpc in $REMAINING_VPCS; do
                echo "  VPC: $vpc"
                echo "  - Tags (check for kagenti.io/managed-by):"
                aws ec2 describe-vpcs --region "$AWS_REGION" \
                    --vpc-ids "$vpc" \
                    --query 'Vpcs[*].Tags' \
                    --output table 2>/dev/null || true
                echo "  - ENIs:"
                aws ec2 describe-network-interfaces --region "$AWS_REGION" \
                    --filters "Name=vpc-id,Values=$vpc" \
                    --query 'NetworkInterfaces[*].[NetworkInterfaceId,Description,Status]' \
                    --output table 2>/dev/null || true
                echo "  - Security Groups:"
                aws ec2 describe-security-groups --region "$AWS_REGION" \
                    --filters "Name=vpc-id,Values=$vpc" \
                    --query 'SecurityGroups[*].[GroupId,GroupName]' \
                    --output table 2>/dev/null || true
                echo "  - VPC Endpoints:"
                aws ec2 describe-vpc-endpoints --region "$AWS_REGION" \
                    --filters "Name=vpc-id,Values=$vpc" \
                    --query 'VpcEndpoints[*].[VpcEndpointId,State,ServiceName]' \
                    --output table 2>/dev/null || true
                echo "  - Attempting manual delete:"
                aws ec2 delete-vpc --region "$AWS_REGION" --vpc-id "$vpc" 2>&1 || true
            done
            echo "Cannot proceed with cluster creation while old VPC exists."
            exit 1
        fi

        echo "  Attempt $attempt/6 - VPCs still exist: $REMAINING_VPCS (waiting 10s...)"
        sleep 10
    done

    echo "AWS orphaned resource cleanup complete"
}

# Check and cleanup orphaned AWS resources (before k8s cleanup)
if check_orphaned_aws_resources; then
    cleanup_orphaned_aws_resources
fi

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

    # Use hypershift-full-test.sh --include-cluster-destroy for consistent cleanup logic
    # hypershift-full-test.sh now detects CI mode (GITHUB_ACTIONS env var) and skips .env loading
    "$REPO_ROOT/.github/scripts/local-setup/hypershift-full-test.sh" \
        --include-cluster-destroy \
        "$CLUSTER_SUFFIX" || true

    # Verify cleanup completed
    if oc get hostedcluster "$CLUSTER_NAME" -n clusters &>/dev/null; then
        echo "::warning::HostedCluster still exists after cleanup"
    fi

    if oc get ns "$CONTROL_PLANE_NS" &>/dev/null; then
        echo "::warning::Control plane namespace still exists after cleanup"
        # Force delete namespace as last resort
        echo "Force-deleting orphaned namespace..."

        # Remove finalizers from ALL resources in the namespace
        # Include HyperShift-specific resources that can block deletion
        echo "Removing finalizers from remaining resources..."
        for resource in hostedcontrolplane clusters.cluster.x-k8s.io \
                        machinepools machinesets machines \
                        etcdclusters etcds \
                        deployments statefulsets replicasets pods \
                        services endpoints configmaps secrets pvc \
                        serviceaccounts roles rolebindings; do
            resources=$(oc get "$resource" -n "$CONTROL_PLANE_NS" -o name 2>/dev/null || true)
            if [ -n "$resources" ]; then
                echo "$resources" | while read -r name; do
                    echo "  Removing finalizers from $name"
                    oc patch "$name" -n "$CONTROL_PLANE_NS" -p '{"metadata":{"finalizers":null}}' --type=merge 2>/dev/null || true
                done
            fi
        done

        # Also remove finalizers from the HostedCluster in the 'clusters' namespace
        if oc get hostedcluster "$CLUSTER_NAME" -n clusters &>/dev/null; then
            echo "  Removing finalizers from HostedCluster $CLUSTER_NAME"
            oc patch hostedcluster "$CLUSTER_NAME" -n clusters -p '{"metadata":{"finalizers":null}}' --type=merge 2>/dev/null || true
            # Delete the HostedCluster
            oc delete hostedcluster "$CLUSTER_NAME" -n clusters --wait=false 2>/dev/null || true
        fi

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

        # Fail if namespace still exists - don't allow create step to run with conflicting resources
        # A namespace with leftover resources causes the new cluster to be in a broken state
        if [ "$NS_DELETED" = "false" ]; then
            echo "::error::Namespace $CONTROL_PLANE_NS still exists after 5 minutes"
            echo "Cannot proceed with cluster creation while old resources exist."
            echo ""
            echo "Debug info:"
            oc get all -n "$CONTROL_PLANE_NS" 2>/dev/null || true
            echo ""
            echo "Finalizers on remaining resources:"
            for resource in hostedcontrolplane clusters.cluster.x-k8s.io deployment statefulset secret; do
                oc get "$resource" -n "$CONTROL_PLANE_NS" -o jsonpath='{range .items[*]}{.kind}/{.metadata.name}: {.metadata.finalizers}{"\n"}{end}' 2>/dev/null || true
            done
            exit 1
        fi
    fi

    echo "Cleanup complete"
else
    echo "No existing cluster or namespace found, proceeding with creation"
fi

# ============================================================================
# Acquire CI Slot (for parallel run coordination)
# ============================================================================
# This runs after cleanup but before cluster creation to ensure we have a slot
# before consuming resources. The slot is released in destroy-cluster.sh.

SLOTS_DIR="$SCRIPT_DIR/slots"

if [[ -d "$SLOTS_DIR" ]]; then
    echo ""
    echo "=== CI Slot Management ==="

    # Cleanup stale slots first
    "$SLOTS_DIR/cleanup-stale.sh" || true

    # Acquire a slot
    if "$SLOTS_DIR/acquire.sh"; then
        echo "Slot acquired successfully"
    else
        echo "::error::Failed to acquire CI slot"
        exit 1
    fi

    # Check capacity
    "$SLOTS_DIR/check-capacity.sh" || {
        echo "::warning::Capacity check failed, proceeding anyway"
    }
else
    echo "Slot management not available (slots/ directory not found)"
fi
