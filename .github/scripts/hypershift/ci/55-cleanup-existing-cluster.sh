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
            # Show what's blocking VPC deletion and try to clean up
            echo "Checking for resources blocking VPC deletion:"
            for vpc in $REMAINING_VPCS; do
                echo "  VPC: $vpc"
                echo "  - Tags:"
                aws ec2 describe-vpcs --region "$AWS_REGION" \
                    --vpc-ids "$vpc" \
                    --query 'Vpcs[*].Tags' \
                    --output table 2>/dev/null || true

                # FIRST: Terminate any EC2 instances in the VPC
                # This must happen before ENI/SG/subnet cleanup as instances hold these resources
                echo "  - EC2 Instances:"
                INSTANCES=$(aws ec2 describe-instances --region "$AWS_REGION" \
                    --filters "Name=vpc-id,Values=$vpc" "Name=instance-state-name,Values=pending,running,stopping,stopped" \
                    --query 'Reservations[*].Instances[*].InstanceId' \
                    --output text 2>/dev/null || echo "")
                if [ -n "$INSTANCES" ] && [ "$INSTANCES" != "None" ]; then
                    echo "    Found running/stopped instances: $INSTANCES"
                    echo "    Terminating instances..."
                    aws ec2 terminate-instances --region "$AWS_REGION" \
                        --instance-ids $INSTANCES 2>&1 || true
                    # Wait for instances to terminate (up to 3 minutes)
                    echo "    Waiting for instances to terminate..."
                    for term_attempt in {1..18}; do
                        REMAINING=$(aws ec2 describe-instances --region "$AWS_REGION" \
                            --instance-ids $INSTANCES \
                            --query 'Reservations[*].Instances[?State.Name!=`terminated`].InstanceId' \
                            --output text 2>/dev/null || echo "")
                        if [ -z "$REMAINING" ] || [ "$REMAINING" = "None" ]; then
                            echo "    All instances terminated"
                            break
                        fi
                        echo "    [$term_attempt/18] Waiting for termination: $REMAINING"
                        sleep 10
                    done
                else
                    echo "    None found"
                fi

                # ============================================================
                # CLEANUP ORDER (respecting AWS resource dependencies):
                # 1. NAT Gateways (use ENIs, must delete first and wait)
                # 2. Internet Gateways (attached to VPC)
                # 3. VPC Endpoints (use ENIs and subnets)
                # 4. ENIs (attached to instances/services, block SG/subnet deletion)
                # 5. Security Groups (referenced by ENIs)
                # 6. Route Tables (associated with subnets)
                # 7. Subnets (contain ENIs, must be last before VPC)
                # 8. VPC
                # ============================================================

                # 1. Delete NAT gateways (they use ENIs and EIPs)
                echo "  - NAT Gateways:"
                NATGWS=$(aws ec2 describe-nat-gateways --region "$AWS_REGION" \
                    --filter "Name=vpc-id,Values=$vpc" "Name=state,Values=available,pending,deleting" \
                    --query 'NatGateways[*].NatGatewayId' \
                    --output text 2>/dev/null || echo "")
                if [ -n "$NATGWS" ] && [ "$NATGWS" != "None" ]; then
                    echo "    Found: $NATGWS"
                    for natgw in $NATGWS; do
                        echo "    Deleting NAT Gateway: $natgw"
                        aws ec2 delete-nat-gateway --region "$AWS_REGION" \
                            --nat-gateway-id "$natgw" 2>&1 || true
                    done
                    echo "    Waiting for NAT Gateway deletion (up to 2 min)..."
                    for nat_wait in {1..12}; do
                        REMAINING_NAT=$(aws ec2 describe-nat-gateways --region "$AWS_REGION" \
                            --filter "Name=vpc-id,Values=$vpc" "Name=state,Values=available,pending,deleting" \
                            --query 'NatGateways[*].NatGatewayId' \
                            --output text 2>/dev/null || echo "")
                        if [ -z "$REMAINING_NAT" ] || [ "$REMAINING_NAT" = "None" ]; then
                            echo "    NAT Gateways deleted"
                            break
                        fi
                        echo "    [$nat_wait/12] Still deleting: $REMAINING_NAT"
                        sleep 10
                    done
                else
                    echo "    None found"
                fi

                # 2. Detach and delete internet gateways
                echo "  - Internet Gateways:"
                IGWS=$(aws ec2 describe-internet-gateways --region "$AWS_REGION" \
                    --filters "Name=attachment.vpc-id,Values=$vpc" \
                    --query 'InternetGateways[*].InternetGatewayId' \
                    --output text 2>/dev/null || echo "")
                if [ -n "$IGWS" ] && [ "$IGWS" != "None" ]; then
                    echo "    Found: $IGWS"
                    for igw in $IGWS; do
                        echo "    Detaching and deleting IGW: $igw"
                        aws ec2 detach-internet-gateway --region "$AWS_REGION" \
                            --internet-gateway-id "$igw" --vpc-id "$vpc" 2>&1 || true
                        aws ec2 delete-internet-gateway --region "$AWS_REGION" \
                            --internet-gateway-id "$igw" 2>&1 || true
                    done
                else
                    echo "    None found"
                fi

                # 3. Delete VPC endpoints (they use ENIs)
                echo "  - VPC Endpoints:"
                ENDPOINTS=$(aws ec2 describe-vpc-endpoints --region "$AWS_REGION" \
                    --filters "Name=vpc-id,Values=$vpc" \
                    --query 'VpcEndpoints[*].VpcEndpointId' \
                    --output text 2>/dev/null || echo "")
                if [ -n "$ENDPOINTS" ] && [ "$ENDPOINTS" != "None" ]; then
                    echo "    Found: $ENDPOINTS"
                    for ep in $ENDPOINTS; do
                        echo "    Deleting VPC endpoint: $ep"
                        aws ec2 delete-vpc-endpoints --region "$AWS_REGION" \
                            --vpc-endpoint-ids "$ep" 2>&1 || true
                    done
                    sleep 5  # Brief wait for endpoint ENIs to be released
                else
                    echo "    None found"
                fi

                # 4. Delete ENIs (should be mostly gone after instance termination)
                echo "  - ENIs:"
                ENIS=$(aws ec2 describe-network-interfaces --region "$AWS_REGION" \
                    --filters "Name=vpc-id,Values=$vpc" \
                    --query 'NetworkInterfaces[*].NetworkInterfaceId' \
                    --output text 2>/dev/null || echo "")
                if [ -n "$ENIS" ] && [ "$ENIS" != "None" ]; then
                    echo "    Found: $ENIS"
                    for eni in $ENIS; do
                        # Check if attached and detach first
                        ATTACHMENT=$(aws ec2 describe-network-interfaces --region "$AWS_REGION" \
                            --network-interface-ids "$eni" \
                            --query 'NetworkInterfaces[0].Attachment.AttachmentId' \
                            --output text 2>/dev/null || echo "")
                        if [ -n "$ATTACHMENT" ] && [ "$ATTACHMENT" != "None" ]; then
                            echo "    Detaching ENI: $eni (attachment: $ATTACHMENT)"
                            aws ec2 detach-network-interface --region "$AWS_REGION" \
                                --attachment-id "$ATTACHMENT" --force 2>&1 || true
                            sleep 3
                        fi
                        echo "    Deleting ENI: $eni"
                        aws ec2 delete-network-interface --region "$AWS_REGION" \
                            --network-interface-id "$eni" 2>&1 || true
                    done
                else
                    echo "    None found"
                fi

                # 5. Delete security groups (non-default, after ENIs are gone)
                echo "  - Security Groups (non-default):"
                SGS=$(aws ec2 describe-security-groups --region "$AWS_REGION" \
                    --filters "Name=vpc-id,Values=$vpc" \
                    --query 'SecurityGroups[?GroupName!=`default`].GroupId' \
                    --output text 2>/dev/null || echo "")
                if [ -n "$SGS" ] && [ "$SGS" != "None" ]; then
                    echo "    Found: $SGS"
                    # First, remove all ingress/egress rules that reference other SGs
                    for sg in $SGS; do
                        echo "    Revoking rules for: $sg"
                        aws ec2 revoke-security-group-ingress --region "$AWS_REGION" \
                            --group-id "$sg" --source-group "$sg" 2>/dev/null || true
                        aws ec2 revoke-security-group-egress --region "$AWS_REGION" \
                            --group-id "$sg" --source-group "$sg" 2>/dev/null || true
                    done
                    # Now delete the security groups
                    for sg in $SGS; do
                        echo "    Deleting security group: $sg"
                        aws ec2 delete-security-group --region "$AWS_REGION" \
                            --group-id "$sg" 2>&1 || true
                    done
                else
                    echo "    None found"
                fi

                # 6. Delete route tables (non-main, disassociate first)
                echo "  - Route Tables:"
                RTS=$(aws ec2 describe-route-tables --region "$AWS_REGION" \
                    --filters "Name=vpc-id,Values=$vpc" \
                    --query 'RouteTables[?!Associations[?Main==`true`]].RouteTableId' \
                    --output text 2>/dev/null || echo "")
                if [ -n "$RTS" ] && [ "$RTS" != "None" ]; then
                    echo "    Found non-main: $RTS"
                    for rt in $RTS; do
                        # First, disassociate from all subnets
                        ASSOCS=$(aws ec2 describe-route-tables --region "$AWS_REGION" \
                            --route-table-ids "$rt" \
                            --query 'RouteTables[0].Associations[?!Main].RouteTableAssociationId' \
                            --output text 2>/dev/null || echo "")
                        if [ -n "$ASSOCS" ] && [ "$ASSOCS" != "None" ]; then
                            for assoc in $ASSOCS; do
                                echo "    Disassociating $assoc from $rt"
                                aws ec2 disassociate-route-table --region "$AWS_REGION" \
                                    --association-id "$assoc" 2>&1 || true
                            done
                        fi
                        echo "    Deleting route table: $rt"
                        aws ec2 delete-route-table --region "$AWS_REGION" \
                            --route-table-id "$rt" 2>&1 || true
                    done
                else
                    echo "    None found (or only main)"
                fi

                # 7. Delete subnets (LAST before VPC - they contain ENIs)
                echo "  - Subnets:"
                SUBNETS=$(aws ec2 describe-subnets --region "$AWS_REGION" \
                    --filters "Name=vpc-id,Values=$vpc" \
                    --query 'Subnets[*].SubnetId' \
                    --output text 2>/dev/null || echo "")
                if [ -n "$SUBNETS" ] && [ "$SUBNETS" != "None" ]; then
                    echo "    Found: $SUBNETS"
                    for subnet in $SUBNETS; do
                        echo "    Deleting subnet: $subnet"
                        aws ec2 delete-subnet --region "$AWS_REGION" --subnet-id "$subnet" 2>&1 || true
                    done
                else
                    echo "    None found"
                fi

                echo "  - Attempting manual VPC delete:"
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
