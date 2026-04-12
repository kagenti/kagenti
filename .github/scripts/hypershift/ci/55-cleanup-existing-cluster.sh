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
# Cleanup Orphaned AWS Resources
# Uses hypershift-automation playbook with cluster_exists=true to force cleanup
# ============================================================================

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
    # NAT Gateways can take 2-3 minutes to delete, so allow up to 5 minutes total
    echo "Verifying VPC cleanup..."
    MAX_VPC_ATTEMPTS=10
    for attempt in $(seq 1 $MAX_VPC_ATTEMPTS); do
        # Use tag-key filter to find VPCs with the cluster tag (any value)
        # This is more robust than requiring tag value to be exactly "owned"
        REMAINING_VPCS=$(aws ec2 describe-vpcs \
            --region "$AWS_REGION" \
            --filters "Name=tag-key,Values=${CLUSTER_TAG}" \
            --query 'Vpcs[*].VpcId' \
            --output text 2>/dev/null || echo "")

        if [ -z "$REMAINING_VPCS" ] || [ "$REMAINING_VPCS" = "None" ]; then
            echo "VPC cleanup verified - no orphaned VPCs remain"
            break
        fi

        echo "  Attempt $attempt/$MAX_VPC_ATTEMPTS - VPCs still exist: $REMAINING_VPCS"

        # On each attempt (not just the last), try to clean up blocking resources
        echo "  Cleaning up resources blocking VPC deletion..."
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
                # Based on hypershift-automation proven approach
                # 1. NAT Gateways (use ENIs, must delete first and wait)
                # 2. Internet Gateways (attached to VPC)
                # 3. VPC Endpoints (use ENIs and subnets)
                # 4. ENIs (attached to instances/services, block SG/subnet deletion)
                # 5. Security Groups (referenced by ENIs)
                # 6. Subnets (delete FIRST - removes route table associations automatically)
                # 7. Route Tables (after subnets - no associations to worry about)
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

                # 3. Delete VPC endpoints (they use ENIs) - WITH PROPER WAITING
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

                    # Wait for VPC endpoints to fully delete (including their ENIs)
                    # VPC endpoint ENIs can take 30-90 seconds to release
                    echo "    Waiting for VPC endpoint ENIs to be released (up to 90s)..."
                    for ep_wait in {1..9}; do
                        REMAINING_EPS=$(aws ec2 describe-vpc-endpoints --region "$AWS_REGION" \
                            --filters "Name=vpc-id,Values=$vpc" \
                            --query 'VpcEndpoints[*].VpcEndpointId' \
                            --output text 2>/dev/null || echo "")
                        if [ -z "$REMAINING_EPS" ] || [ "$REMAINING_EPS" = "None" ]; then
                            echo "    All VPC endpoints deleted"
                            break
                        fi
                        echo "    [$ep_wait/9] Still deleting: $REMAINING_EPS"
                        sleep 10
                    done
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
                    # Wait for ENI deletions to propagate before proceeding
                    echo "    Waiting 5s for ENI deletions to propagate..."
                    sleep 5
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

                # 6. Delete subnets FIRST (this removes route table associations automatically)
                # Following hypershift-automation proven approach: subnets before route tables
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
                    # Brief wait for subnet deletion to propagate
                    echo "    Waiting 5s for subnet deletion to propagate..."
                    sleep 5
                else
                    echo "    None found"
                fi

                # 7. Delete route tables (after subnets - associations already removed)
                # Note: Main route table cannot be deleted (auto-deleted with VPC)
                # Query catches both orphaned route tables (no associations) and non-main ones
                # Fixed query: length() == 0 matches both empty Associations and non-main route tables
                echo "  - Route Tables (non-main):"
                RTS=$(aws ec2 describe-route-tables --region "$AWS_REGION" \
                    --filters "Name=vpc-id,Values=$vpc" \
                    --query 'RouteTables[?length(Associations[?Main==`true`]) == `0`].RouteTableId' \
                    --output text 2>/dev/null || echo "")
                if [ -n "$RTS" ] && [ "$RTS" != "None" ]; then
                    echo "    Found non-main: $RTS"
                    for rt in $RTS; do
                        echo "    Deleting route table: $rt"
                        # Show any remaining associations for debugging
                        REMAINING_ASSOCS=$(aws ec2 describe-route-tables --region "$AWS_REGION" \
                            --route-table-ids "$rt" \
                            --query 'RouteTables[0].Associations[*].RouteTableAssociationId' \
                            --output text 2>/dev/null || echo "")
                        if [ -n "$REMAINING_ASSOCS" ] && [ "$REMAINING_ASSOCS" != "None" ]; then
                            echo "      Warning: Still has associations: $REMAINING_ASSOCS"
                            # Try to disassociate any non-main associations
                            for assoc in $REMAINING_ASSOCS; do
                                aws ec2 disassociate-route-table --region "$AWS_REGION" \
                                    --association-id "$assoc" 2>/dev/null || true
                            done
                        fi
                        aws ec2 delete-route-table --region "$AWS_REGION" \
                            --route-table-id "$rt" 2>&1 || true
                    done
                else
                    echo "    None found (or only main route table)"
                fi

                echo "  - Attempting manual VPC delete:"
                VPC_DELETE_OUTPUT=$(aws ec2 delete-vpc --region "$AWS_REGION" --vpc-id "$vpc" 2>&1)
                VPC_DELETE_EXIT=$?

                if [ $VPC_DELETE_EXIT -eq 0 ]; then
                    echo "    Successfully deleted VPC: $vpc"
                else
                    echo "    Failed to delete VPC: $vpc"
                    echo "    Error: $VPC_DELETE_OUTPUT"

                    # Show remaining dependencies blocking deletion
                    echo "    Checking for remaining dependencies..."

                    # Check for remaining ENIs (most common blocker)
                    REMAINING_ENIS=$(aws ec2 describe-network-interfaces --region "$AWS_REGION" \
                        --filters "Name=vpc-id,Values=$vpc" \
                        --query 'NetworkInterfaces[*].[NetworkInterfaceId,Status,Description]' \
                        --output text 2>/dev/null || echo "")
                    if [ -n "$REMAINING_ENIS" ] && [ "$REMAINING_ENIS" != "None" ]; then
                        echo "    - Network Interfaces still attached:"
                        echo "$REMAINING_ENIS" | sed 's/^/      /'
                    fi

                    # Check for remaining subnets
                    REMAINING_SUBNETS=$(aws ec2 describe-subnets --region "$AWS_REGION" \
                        --filters "Name=vpc-id,Values=$vpc" \
                        --query 'Subnets[*].SubnetId' \
                        --output text 2>/dev/null || echo "")
                    if [ -n "$REMAINING_SUBNETS" ] && [ "$REMAINING_SUBNETS" != "None" ]; then
                        echo "    - Subnets: $REMAINING_SUBNETS"
                    fi

                    # Check for remaining route table associations
                    REMAINING_RT_ASSOCS=$(aws ec2 describe-route-tables --region "$AWS_REGION" \
                        --filters "Name=vpc-id,Values=$vpc" \
                        --query 'RouteTables[*].Associations[?!Main].RouteTableAssociationId' \
                        --output text 2>/dev/null || echo "")
                    if [ -n "$REMAINING_RT_ASSOCS" ] && [ "$REMAINING_RT_ASSOCS" != "None" ]; then
                        echo "    - Route table associations: $REMAINING_RT_ASSOCS"
                    fi
                fi
            done

        # Check if this was the last attempt
        if [ "$attempt" -eq "$MAX_VPC_ATTEMPTS" ]; then
            # Final check after cleanup (use tag-key filter for consistency)
            FINAL_CHECK=$(aws ec2 describe-vpcs \
                --region "$AWS_REGION" \
                --filters "Name=tag-key,Values=${CLUSTER_TAG}" \
                --query 'Vpcs[*].VpcId' \
                --output text 2>/dev/null || echo "")
            if [ -n "$FINAL_CHECK" ] && [ "$FINAL_CHECK" != "None" ]; then
                echo "::error::Failed to delete orphaned VPCs after $MAX_VPC_ATTEMPTS attempts: $FINAL_CHECK"
                echo "Cannot proceed with cluster creation while old VPC exists."
                exit 1
            fi
        fi

        echo "  Waiting 60s before next check..."
        sleep 60
    done

    # ============================================================
    # Clean up non-VPC resources (Elastic IPs, IAM, OIDC, Route53)
    # These should be cleaned by ansible but often aren't
    # ============================================================
    echo ""
    echo "=== Cleaning up non-VPC AWS resources ==="

    # 1. Release Elastic IPs (orphaned from NAT gateways)
    echo "  - Elastic IPs:"
    EIPS=$(aws ec2 describe-addresses --region "$AWS_REGION" \
        --filters "Name=tag-key,Values=${CLUSTER_TAG}" \
        --query 'Addresses[*].AllocationId' \
        --output text 2>/dev/null || echo "")
    if [ -n "$EIPS" ] && [ "$EIPS" != "None" ]; then
        echo "    Found: $EIPS"
        for eip in $EIPS; do
            echo "    Releasing Elastic IP: $eip"
            aws ec2 release-address --region "$AWS_REGION" \
                --allocation-id "$eip" 2>&1 || true
        done
    else
        echo "    None found"
    fi

    # 2. Delete Route53 hosted zones
    echo "  - Route53 Hosted Zones:"
    ZONES=$(aws route53 list-hosted-zones --query "HostedZones[?contains(Name, '${CLUSTER_NAME}')].Id" \
        --output text 2>/dev/null || echo "")
    if [ -n "$ZONES" ] && [ "$ZONES" != "None" ]; then
        echo "    Found: $ZONES"
        for zone_id in $ZONES; do
            # Extract zone ID (remove /hostedzone/ prefix)
            zone_id_clean="${zone_id##*/}"
            echo "    Deleting hosted zone: $zone_id_clean"

            # First delete all record sets except NS and SOA
            RECORD_SETS=$(aws route53 list-resource-record-sets \
                --hosted-zone-id "$zone_id_clean" \
                --query "ResourceRecordSets[?Type != 'NS' && Type != 'SOA'].[Name,Type]" \
                --output text 2>/dev/null || echo "")

            if [ -n "$RECORD_SETS" ] && [ "$RECORD_SETS" != "None" ]; then
                echo "      Deleting record sets in zone $zone_id_clean"
                while IFS=$'\t' read -r name type; do
                    [ -z "$name" ] && continue
                    echo "        Deleting $type record: $name"
                    # Get the full record set
                    CHANGE_BATCH=$(aws route53 list-resource-record-sets \
                        --hosted-zone-id "$zone_id_clean" \
                        --query "ResourceRecordSets[?Name=='${name}' && Type=='${type}']" \
                        --output json 2>/dev/null)

                    if [ -n "$CHANGE_BATCH" ] && [ "$CHANGE_BATCH" != "[]" ]; then
                        # Delete the record set
                        aws route53 change-resource-record-sets \
                            --hosted-zone-id "$zone_id_clean" \
                            --change-batch "{\"Changes\":[{\"Action\":\"DELETE\",\"ResourceRecordSet\":$(echo "$CHANGE_BATCH" | jq '.[0]')}]}" \
                            2>&1 || true
                    fi
                done <<< "$RECORD_SETS"
            fi

            # Now delete the hosted zone
            aws route53 delete-hosted-zone --id "$zone_id_clean" 2>&1 || true
        done
    else
        echo "    None found"
    fi

    # 3. Delete OIDC providers
    echo "  - OIDC Providers:"
    OIDC_PROVIDERS=$(aws iam list-open-id-connect-providers --query "OpenIDConnectProviderList[?contains(Arn, '${CLUSTER_NAME}')].Arn" \
        --output text 2>/dev/null || echo "")
    if [ -n "$OIDC_PROVIDERS" ] && [ "$OIDC_PROVIDERS" != "None" ]; then
        echo "    Found: $OIDC_PROVIDERS"
        for oidc_arn in $OIDC_PROVIDERS; do
            echo "    Deleting OIDC provider: $oidc_arn"
            aws iam delete-open-id-connect-provider --open-id-connect-provider-arn "$oidc_arn" 2>&1 || true
        done
    else
        echo "    None found"
    fi

    # 4. Delete IAM roles and instance profiles
    echo "  - IAM Roles and Instance Profiles:"
    IAM_ROLES=$(aws iam list-roles --query "Roles[?contains(RoleName, '${CLUSTER_NAME}')].RoleName" \
        --output text 2>/dev/null || echo "")
    if [ -n "$IAM_ROLES" ] && [ "$IAM_ROLES" != "None" ]; then
        echo "    Found roles: $IAM_ROLES"
        for role in $IAM_ROLES; do
            echo "    Processing role: $role"

            # Detach all managed policies
            ATTACHED_POLICIES=$(aws iam list-attached-role-policies --role-name "$role" \
                --query 'AttachedPolicies[*].PolicyArn' --output text 2>/dev/null || echo "")
            if [ -n "$ATTACHED_POLICIES" ] && [ "$ATTACHED_POLICIES" != "None" ]; then
                for policy_arn in $ATTACHED_POLICIES; do
                    echo "      Detaching policy: $policy_arn"
                    aws iam detach-role-policy --role-name "$role" --policy-arn "$policy_arn" 2>&1 || true
                done
            fi

            # Delete all inline policies
            INLINE_POLICIES=$(aws iam list-role-policies --role-name "$role" \
                --query 'PolicyNames[*]' --output text 2>/dev/null || echo "")
            if [ -n "$INLINE_POLICIES" ] && [ "$INLINE_POLICIES" != "None" ]; then
                for policy_name in $INLINE_POLICIES; do
                    echo "      Deleting inline policy: $policy_name"
                    aws iam delete-role-policy --role-name "$role" --policy-name "$policy_name" 2>&1 || true
                done
            fi

            # Remove from instance profiles
            INSTANCE_PROFILES=$(aws iam list-instance-profiles-for-role --role-name "$role" \
                --query 'InstanceProfiles[*].InstanceProfileName' --output text 2>/dev/null || echo "")
            if [ -n "$INSTANCE_PROFILES" ] && [ "$INSTANCE_PROFILES" != "None" ]; then
                for profile in $INSTANCE_PROFILES; do
                    echo "      Removing from instance profile: $profile"
                    aws iam remove-role-from-instance-profile \
                        --instance-profile-name "$profile" --role-name "$role" 2>&1 || true
                    # Delete the instance profile
                    echo "      Deleting instance profile: $profile"
                    aws iam delete-instance-profile --instance-profile-name "$profile" 2>&1 || true
                done
            fi

            # Delete the role
            echo "      Deleting role: $role"
            aws iam delete-role --role-name "$role" 2>&1 || true
        done
    else
        echo "    None found"
    fi

    # 5. Delete S3 buckets (if any)
    echo "  - S3 Buckets:"
    S3_BUCKETS=$(aws s3api list-buckets --query "Buckets[?contains(Name, '${CLUSTER_NAME}')].Name" \
        --output text 2>/dev/null || echo "")
    if [ -n "$S3_BUCKETS" ] && [ "$S3_BUCKETS" != "None" ]; then
        echo "    Found: $S3_BUCKETS"
        for bucket in $S3_BUCKETS; do
            echo "    Deleting S3 bucket: $bucket"
            # Empty the bucket first
            aws s3 rm "s3://$bucket" --recursive 2>&1 || true
            # Delete the bucket
            aws s3api delete-bucket --bucket "$bucket" --region "$AWS_REGION" 2>&1 || true
        done
    else
        echo "    None found"
    fi

    echo "AWS orphaned resource cleanup complete"
}

# ============================================================================
# STEP 1: Delete HostedCluster if exists (let operator do graceful cleanup)
# ============================================================================
# This must happen FIRST so the operator can clean up AWS resources properly.
# If we delete AWS resources while HostedCluster exists, operator may recreate them.

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
    echo "Cleaning up existing cluster resources via operator..."

    # Use hypershift-full-test.sh --include-cluster-destroy for consistent cleanup logic
    # hypershift-full-test.sh now detects CI mode (GITHUB_ACTIONS env var) and skips .env loading
    "$REPO_ROOT/.github/scripts/local-setup/hypershift-full-test.sh" \
        --include-cluster-destroy \
        "$CLUSTER_SUFFIX" || true

    # Verify HostedCluster cleanup completed
    if oc get hostedcluster "$CLUSTER_NAME" -n clusters &>/dev/null; then
        echo "::warning::HostedCluster still exists after cleanup"
    fi

    if oc get ns "$CONTROL_PLANE_NS" &>/dev/null; then
        echo "::warning::Control plane namespace still exists after cleanup"
        # Force delete namespace as last resort
        echo "Force-deleting orphaned namespace..."

        # Remove finalizers from ALL resources in the namespace
        # Include HyperShift-specific and Cluster API resources that can block deletion
        echo "Removing finalizers from remaining resources..."
        for resource in hostedcontrolplane hostedcluster \
                        clusters.cluster.x-k8s.io \
                        machinedeployments.cluster.x-k8s.io \
                        machinepools machinesets machines \
                        awsmachines.infrastructure.cluster.x-k8s.io \
                        awsclusters.infrastructure.cluster.x-k8s.io \
                        awsmachinetemplates.infrastructure.cluster.x-k8s.io \
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

        # Warn if namespace still exists — proceed anyway since the cluster name
        # is unique per PR and the HyperShift operator will handle the stale
        # namespace eventually. Blocking here causes CI deadlocks when multiple
        # E2E runs overlap.
        if [ "$NS_DELETED" = "false" ]; then
            echo "::warning::Namespace $CONTROL_PLANE_NS still exists after 5 minutes — proceeding anyway"
            echo "The HyperShift operator will clean it up asynchronously."
            echo ""
            echo "Remaining resources (for debugging):"
            oc get pods -n "$CONTROL_PLANE_NS" 2>/dev/null || true
        fi
    fi

    echo "Kubernetes cleanup complete"
else
    echo "No existing HostedCluster or namespace found"
fi

# ============================================================================
# STEP 2: Check for orphaned AWS resources and clean up if needed
# ============================================================================
# This runs AFTER HostedCluster deletion so we're only cleaning up true orphans,
# not fighting against the operator.

echo ""
echo "=== Checking for orphaned AWS resources ==="

DEBUG_SCRIPT="$REPO_ROOT/.github/scripts/hypershift/debug-aws-hypershift.sh"

# Check for orphaned VPCs (these block cluster creation)
# Other resources (IAM, S3, OIDC, Route53, Elastic IPs) are cleaned up after VPC deletion
check_orphaned_vpcs() {
    ORPHANED_VPCS=$(aws ec2 describe-vpcs \
        --region "$AWS_REGION" \
        --filters "Name=tag-key,Values=${CLUSTER_TAG}" \
        --query 'Vpcs[*].VpcId' \
        --output text 2>/dev/null || echo "")
    if [ -n "$ORPHANED_VPCS" ] && [ "$ORPHANED_VPCS" != "None" ]; then
        return 0  # VPCs exist (orphans found)
    else
        return 1  # No VPCs (clean)
    fi
}

# Use debug script to detect any orphans, but only fail on VPCs (they block cluster creation)
if ! "$DEBUG_SCRIPT" --check "$CLUSTER_NAME"; then
    echo "Orphaned AWS resources detected, running cleanup..."
    cleanup_orphaned_aws_resources

    # Final verification - check if VPCs still remain
    # All resources (VPC, IAM, S3, OIDC, Route53, Elastic IPs) are now cleaned
    echo ""
    echo "=== Final resource verification ==="
    if check_orphaned_vpcs; then
        echo "::error::VPCs still remain after cleanup - these block cluster creation"
        echo "Cannot proceed with cluster creation while old VPC exists."
        echo ""
        echo "Orphaned VPCs: $ORPHANED_VPCS"
        echo ""
        echo "Run the following for full details:"
        echo "  $DEBUG_SCRIPT $CLUSTER_NAME"
        exit 1
    fi
    echo "All AWS resources cleaned up successfully"
else
    echo "No orphaned AWS resources found"
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
