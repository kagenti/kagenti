#!/usr/bin/env bash
# Cleanup any existing cluster from cancelled runs
# Uses run-full-test.sh --include-destroy to ensure CI and local use the same cleanup logic
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="${GITHUB_WORKSPACE:-$(cd "$SCRIPT_DIR/../../../.." && pwd)}"

CLUSTER_NAME="${MANAGED_BY_TAG}-${CLUSTER_SUFFIX}"
CONTROL_PLANE_NS="clusters-$CLUSTER_NAME"
CLUSTER_TAG="kubernetes.io/cluster/${CLUSTER_NAME}"

echo "Checking for existing cluster: $CLUSTER_NAME"

# ============================================================================
# AWS Orphaned Resource Cleanup
# Cleanup AWS resources tagged with the cluster name that may be orphaned
# from previous cancelled runs. This runs BEFORE k8s cleanup because ansible's
# cleanup only runs when cluster_exists=true, missing orphaned resources.
# ============================================================================

cleanup_orphaned_aws_resources() {
    echo "Checking for orphaned AWS resources tagged with: $CLUSTER_TAG"

    # Check for orphaned VPCs
    ORPHANED_VPCS=$(aws ec2 describe-vpcs \
        --region "$AWS_REGION" \
        --filters "Name=tag:${CLUSTER_TAG},Values=owned" \
        --query 'Vpcs[*].VpcId' \
        --output text 2>/dev/null || echo "")

    if [ -n "$ORPHANED_VPCS" ] && [ "$ORPHANED_VPCS" != "None" ]; then
        echo "Found orphaned VPCs: $ORPHANED_VPCS"

        for VPC_ID in $ORPHANED_VPCS; do
            echo "Cleaning up orphaned VPC: $VPC_ID"

            # 1. Delete NAT Gateways (must be deleted before subnets and EIPs)
            NAT_GWS=$(aws ec2 describe-nat-gateways \
                --region "$AWS_REGION" \
                --filter "Name=vpc-id,Values=$VPC_ID" "Name=state,Values=available,pending,deleting" \
                --query 'NatGateways[*].NatGatewayId' \
                --output text 2>/dev/null || echo "")
            for NGW in $NAT_GWS; do
                [ -z "$NGW" ] || [ "$NGW" = "None" ] && continue
                echo "  Deleting NAT Gateway: $NGW"
                aws ec2 delete-nat-gateway --region "$AWS_REGION" --nat-gateway-id "$NGW" 2>/dev/null || true
            done
            # Wait for NAT gateways to be deleted (they take time and block EIP release)
            if [ -n "$NAT_GWS" ] && [ "$NAT_GWS" != "None" ]; then
                echo "  Waiting for NAT Gateways to be deleted (up to 2 minutes)..."
                for i in {1..24}; do
                    REMAINING=$(aws ec2 describe-nat-gateways \
                        --region "$AWS_REGION" \
                        --filter "Name=vpc-id,Values=$VPC_ID" "Name=state,Values=available,pending,deleting" \
                        --query 'NatGateways[*].NatGatewayId' \
                        --output text 2>/dev/null || echo "")
                    if [ -z "$REMAINING" ] || [ "$REMAINING" = "None" ]; then
                        echo "  NAT Gateways deleted"
                        break
                    fi
                    sleep 5
                done
            fi

            # 2. Delete VPC Endpoints (must be deleted before subnets)
            VPCES=$(aws ec2 describe-vpc-endpoints \
                --region "$AWS_REGION" \
                --filters "Name=vpc-id,Values=$VPC_ID" \
                --query 'VpcEndpoints[*].VpcEndpointId' \
                --output text 2>/dev/null || echo "")
            for VPCE in $VPCES; do
                [ -z "$VPCE" ] || [ "$VPCE" = "None" ] && continue
                echo "  Deleting VPC Endpoint: $VPCE"
                aws ec2 delete-vpc-endpoints --region "$AWS_REGION" --vpc-endpoint-ids "$VPCE" 2>/dev/null || true
            done

            # 3. Delete Network Interfaces (ENIs) - these block subnet deletion
            ENIS=$(aws ec2 describe-network-interfaces \
                --region "$AWS_REGION" \
                --filters "Name=vpc-id,Values=$VPC_ID" \
                --query 'NetworkInterfaces[*].NetworkInterfaceId' \
                --output text 2>/dev/null || echo "")
            for ENI in $ENIS; do
                [ -z "$ENI" ] || [ "$ENI" = "None" ] && continue
                echo "  Deleting Network Interface: $ENI"
                # First try to detach if attached
                ATTACHMENT=$(aws ec2 describe-network-interfaces \
                    --region "$AWS_REGION" \
                    --network-interface-ids "$ENI" \
                    --query 'NetworkInterfaces[0].Attachment.AttachmentId' \
                    --output text 2>/dev/null || echo "")
                if [ -n "$ATTACHMENT" ] && [ "$ATTACHMENT" != "None" ]; then
                    echo "    Detaching ENI attachment: $ATTACHMENT"
                    aws ec2 detach-network-interface --region "$AWS_REGION" --attachment-id "$ATTACHMENT" --force 2>/dev/null || true
                    sleep 5
                fi
                aws ec2 delete-network-interface --region "$AWS_REGION" --network-interface-id "$ENI" 2>/dev/null || true
            done

            # 4. Release Elastic IPs associated with the cluster
            EIPS=$(aws ec2 describe-addresses \
                --region "$AWS_REGION" \
                --filters "Name=tag:${CLUSTER_TAG},Values=owned" \
                --query 'Addresses[*].AllocationId' \
                --output text 2>/dev/null || echo "")
            for EIP in $EIPS; do
                [ -z "$EIP" ] || [ "$EIP" = "None" ] && continue
                echo "  Releasing Elastic IP: $EIP"
                aws ec2 release-address --region "$AWS_REGION" --allocation-id "$EIP" 2>/dev/null || true
            done

            # 5. Detach and delete Internet Gateways
            IGWS=$(aws ec2 describe-internet-gateways \
                --region "$AWS_REGION" \
                --filters "Name=attachment.vpc-id,Values=$VPC_ID" \
                --query 'InternetGateways[*].InternetGatewayId' \
                --output text 2>/dev/null || echo "")
            for IGW in $IGWS; do
                [ -z "$IGW" ] || [ "$IGW" = "None" ] && continue
                echo "  Detaching Internet Gateway: $IGW"
                aws ec2 detach-internet-gateway --region "$AWS_REGION" --internet-gateway-id "$IGW" --vpc-id "$VPC_ID" 2>/dev/null || true
                echo "  Deleting Internet Gateway: $IGW"
                aws ec2 delete-internet-gateway --region "$AWS_REGION" --internet-gateway-id "$IGW" 2>/dev/null || true
            done

            # 6. Delete Subnets
            SUBNETS=$(aws ec2 describe-subnets \
                --region "$AWS_REGION" \
                --filters "Name=vpc-id,Values=$VPC_ID" \
                --query 'Subnets[*].SubnetId' \
                --output text 2>/dev/null || echo "")
            for SUBNET in $SUBNETS; do
                [ -z "$SUBNET" ] || [ "$SUBNET" = "None" ] && continue
                echo "  Deleting Subnet: $SUBNET"
                aws ec2 delete-subnet --region "$AWS_REGION" --subnet-id "$SUBNET" 2>/dev/null || true
            done

            # 7. Delete Route Tables (except main) - disassociate first
            RTBS=$(aws ec2 describe-route-tables \
                --region "$AWS_REGION" \
                --filters "Name=vpc-id,Values=$VPC_ID" \
                --query 'RouteTables[?Associations[0].Main!=`true`].[RouteTableId,Associations[*].RouteTableAssociationId]' \
                --output json 2>/dev/null || echo "[]")
            echo "$RTBS" | jq -r '.[] | "\(.[0]) \(.[1][]? // "")"' 2>/dev/null | while read -r RTB ASSOC; do
                [ -z "$RTB" ] || [ "$RTB" = "null" ] && continue
                if [ -n "$ASSOC" ] && [ "$ASSOC" != "null" ]; then
                    echo "  Disassociating Route Table: $RTB ($ASSOC)"
                    aws ec2 disassociate-route-table --region "$AWS_REGION" --association-id "$ASSOC" 2>/dev/null || true
                fi
                echo "  Deleting Route Table: $RTB"
                aws ec2 delete-route-table --region "$AWS_REGION" --route-table-id "$RTB" 2>/dev/null || true
            done

            # 8. Delete Security Groups (except default) - revoke rules first to handle cross-references
            SGS=$(aws ec2 describe-security-groups \
                --region "$AWS_REGION" \
                --filters "Name=vpc-id,Values=$VPC_ID" \
                --query 'SecurityGroups[?GroupName!=`default`].GroupId' \
                --output text 2>/dev/null || echo "")
            # First pass: revoke all ingress/egress rules
            for SG in $SGS; do
                [ -z "$SG" ] || [ "$SG" = "None" ] && continue
                echo "  Revoking rules from Security Group: $SG"
                # Revoke all ingress rules
                aws ec2 describe-security-groups --region "$AWS_REGION" --group-ids "$SG" \
                    --query 'SecurityGroups[0].IpPermissions' --output json 2>/dev/null | \
                    jq -c 'if . != null and length > 0 then . else empty end' | \
                    while read -r rules; do
                        aws ec2 revoke-security-group-ingress --region "$AWS_REGION" --group-id "$SG" --ip-permissions "$rules" 2>/dev/null || true
                    done
                # Revoke all egress rules
                aws ec2 describe-security-groups --region "$AWS_REGION" --group-ids "$SG" \
                    --query 'SecurityGroups[0].IpPermissionsEgress' --output json 2>/dev/null | \
                    jq -c 'if . != null and length > 0 then . else empty end' | \
                    while read -r rules; do
                        aws ec2 revoke-security-group-egress --region "$AWS_REGION" --group-id "$SG" --ip-permissions "$rules" 2>/dev/null || true
                    done
            done
            # Second pass: delete security groups
            for SG in $SGS; do
                [ -z "$SG" ] || [ "$SG" = "None" ] && continue
                echo "  Deleting Security Group: $SG"
                aws ec2 delete-security-group --region "$AWS_REGION" --group-id "$SG" 2>/dev/null || true
            done

            # 9. Delete VPC - with error checking
            echo "  Deleting VPC: $VPC_ID"
            if ! aws ec2 delete-vpc --region "$AWS_REGION" --vpc-id "$VPC_ID" 2>&1; then
                echo "::warning::Failed to delete VPC $VPC_ID - checking remaining dependencies"
                echo "  Remaining subnets:"
                aws ec2 describe-subnets --region "$AWS_REGION" --filters "Name=vpc-id,Values=$VPC_ID" \
                    --query 'Subnets[*].[SubnetId,State]' --output table 2>/dev/null || true
                echo "  Remaining ENIs:"
                aws ec2 describe-network-interfaces --region "$AWS_REGION" --filters "Name=vpc-id,Values=$VPC_ID" \
                    --query 'NetworkInterfaces[*].[NetworkInterfaceId,Status,Description]' --output table 2>/dev/null || true
                echo "  Remaining security groups:"
                aws ec2 describe-security-groups --region "$AWS_REGION" --filters "Name=vpc-id,Values=$VPC_ID" \
                    --query 'SecurityGroups[*].[GroupId,GroupName]' --output table 2>/dev/null || true
            fi
        done

        # Verify VPCs are deleted
        REMAINING_VPCS=$(aws ec2 describe-vpcs \
            --region "$AWS_REGION" \
            --filters "Name=tag:${CLUSTER_TAG},Values=owned" \
            --query 'Vpcs[*].VpcId' \
            --output text 2>/dev/null || echo "")
        if [ -n "$REMAINING_VPCS" ] && [ "$REMAINING_VPCS" != "None" ]; then
            echo "::error::Failed to delete orphaned VPCs: $REMAINING_VPCS"
            echo "Cannot proceed with cluster creation while old VPC exists."
            exit 1
        fi

        echo "AWS orphaned resource cleanup complete"
    else
        echo "No orphaned AWS resources found"
    fi
}

# Run AWS cleanup first (before k8s cleanup)
cleanup_orphaned_aws_resources

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
