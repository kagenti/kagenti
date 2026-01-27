#!/usr/bin/env bash
# .github/scripts/hypershift/ci/slots/cleanup-stale.sh
#
# Cleans up stale CI slots (Leases older than their duration).
# Also checks for orphaned clusters.
#
# Run periodically or at the start of slot acquisition.

set -uo pipefail

# Source shared utilities
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../../../lib/logging.sh"

NAMESPACE="clusters"
MANAGED_BY_TAG="${MANAGED_BY_TAG:-kagenti-hypershift-ci}"
LEASE_PREFIX="kagenti-ci-slot"  # Namespaced prefix to avoid conflicts

echo "Checking for stale CI slots..."
echo "Lease prefix: $LEASE_PREFIX"
echo ""

# Get all CI slot leases
leases=$(oc get leases -n "$NAMESPACE" -l app=kagenti-ci \
    -o jsonpath='{range .items[*]}{.metadata.name}|{.spec.acquireTime}|{.spec.leaseDurationSeconds}|{.spec.holderIdentity}{"\n"}{end}' 2>/dev/null || echo "")

now_epoch=$(date +%s)
stale_count=0

while IFS='|' read -r name acquire_time duration holder; do
    [[ -z "$name" ]] && continue

    acquire_epoch=$(parse_iso_date "$acquire_time")
    age=$((now_epoch - acquire_epoch))
    max_age=${duration:-7200}

    if [[ $age -gt $max_age ]]; then
        echo "Stale lease found: $name (age: ${age}s, max: ${max_age}s, holder: $holder)"

        # Check if corresponding cluster still exists
        cluster_suffix=$(echo "$holder" | cut -d':' -f1)
        cluster_name="${MANAGED_BY_TAG}-${cluster_suffix}"

        if oc get hostedcluster "$cluster_name" -n clusters &>/dev/null; then
            echo "  WARNING: Cluster $cluster_name still exists! Manual cleanup may be needed."
            echo "  Run: ./.github/scripts/hypershift/destroy-cluster.sh $cluster_suffix"
        fi

        # Delete stale lease
        oc delete lease "$name" -n "$NAMESPACE" --ignore-not-found
        echo "  Deleted stale lease: $name"
        ((stale_count++))
    fi
done <<< "$leases"

if [[ $stale_count -eq 0 ]]; then
    echo "No stale slots found"
else
    echo "Cleaned up $stale_count stale slot(s)"
fi

# Also check for orphaned clusters (clusters without matching leases)
echo ""
echo "Checking for orphaned clusters..."

clusters=$(oc get hostedclusters -n clusters \
    -o jsonpath='{range .items[*]}{.metadata.name}{"\n"}{end}' 2>/dev/null || echo "")

orphan_count=0
while read -r cluster; do
    [[ -z "$cluster" ]] && continue
    [[ ! "$cluster" =~ ^${MANAGED_BY_TAG}- ]] && continue  # Skip non-CI clusters

    suffix=${cluster#${MANAGED_BY_TAG}-}

    # Check if any lease holds this cluster (simple grep instead of jsonpath regex)
    lease_holders=$(oc get leases -n "$NAMESPACE" -l app=kagenti-ci \
        -o jsonpath='{range .items[*]}{.spec.holderIdentity}{"\n"}{end}' 2>/dev/null || echo "")

    if ! echo "$lease_holders" | grep -q "^${suffix}:"; then
        # Check cluster age (only flag if older than 30 minutes)
        created=$(oc get hostedcluster "$cluster" -n clusters \
            -o jsonpath='{.metadata.creationTimestamp}' 2>/dev/null || echo "")
        created_epoch=$(parse_iso_date "$created")
        age_minutes=$(( (now_epoch - created_epoch) / 60 ))

        if [[ $age_minutes -gt 30 ]]; then
            echo "Orphaned cluster: $cluster (age: ${age_minutes}m, no matching lease)"
            ((orphan_count++))
        fi
    fi
done <<< "$clusters"

if [[ $orphan_count -eq 0 ]]; then
    echo "No orphaned clusters found"
else
    echo "Found $orphan_count orphaned cluster(s) - manual cleanup may be needed"
fi
