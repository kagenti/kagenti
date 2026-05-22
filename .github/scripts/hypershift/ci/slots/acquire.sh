#!/usr/bin/env bash
# .github/scripts/hypershift/ci/slots/acquire.sh
#
# Acquires a CI slot using Kubernetes Lease objects.
# Uses two-phase approach to avoid race conditions:
#   Phase 1: Try to create leases (atomic, no checking)
#   Phase 2: If all fail, scan for expired leases and cleanup
#
# Exit 0: Slot acquired, SLOT_ID written to GITHUB_OUTPUT
# Exit 1: Timeout waiting for slot
#
# Environment:
#   MAX_SLOTS       - Maximum parallel runs (default: 6)
#   SLOT_TIMEOUT    - Minutes to wait for slot (default: 60)
#   CLUSTER_SUFFIX  - Unique identifier for this run

set -euo pipefail

# Source shared utilities
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../../../lib/logging.sh"

MAX_SLOTS="${MAX_SLOTS:-6}"
SLOT_TIMEOUT="${SLOT_TIMEOUT:-60}"  # Wait up to 60 min for a slot (CI run timeout is 120 min)
LEASE_DURATION_SECONDS="${LEASE_DURATION_SECONDS:-7200}"  # 2 hours TTL for stale cleanup
NAMESPACE="clusters"
LEASE_PREFIX="kagenti-ci-slot"  # Namespaced prefix to avoid conflicts

# Identifiers
RUN_ID="${GITHUB_RUN_ID:-local-$$}"
CLUSTER_SUFFIX="${CLUSTER_SUFFIX:-unknown}"
HOLDER_IDENTITY="${CLUSTER_SUFFIX}:${RUN_ID}"

# Track acquired slot for cleanup
ACQUIRED_SLOT=""

cleanup_lease() {
    if [[ -n "$ACQUIRED_SLOT" ]]; then
        echo "Releasing slot $ACQUIRED_SLOT on exit..."
        oc delete lease "${LEASE_PREFIX}-${ACQUIRED_SLOT}" -n "$NAMESPACE" --ignore-not-found 2>/dev/null || true
    fi
}
trap cleanup_lease EXIT SIGINT SIGTERM

create_lease() {
    local slot=$1
    local lease_name="${LEASE_PREFIX}-${slot}"

    # Attempt to create lease (fails atomically if exists)
    # Note: acquireTime and renewTime are read-only fields set by the API
    cat <<EOF | oc create -f - 2>/dev/null
apiVersion: coordination.k8s.io/v1
kind: Lease
metadata:
  name: ${lease_name}
  namespace: ${NAMESPACE}
  labels:
    app: kagenti-ci
    slot: "${slot}"
spec:
  holderIdentity: "${HOLDER_IDENTITY}"
  leaseDurationSeconds: ${LEASE_DURATION_SECONDS}
EOF
}

# Phase 1: Try to create any available slot (pure atomic creates, no checking)
try_create_any_slot() {
    for slot in $(seq 0 $((MAX_SLOTS - 1))); do
        if create_lease "$slot"; then
            ACQUIRED_SLOT="$slot"
            echo "Acquired slot $slot"
            return 0
        fi
    done
    return 1
}

# Phase 2: Cleanup expired leases (only called after all creates fail)
cleanup_expired_leases() {
    local now_epoch
    now_epoch=$(date +%s)
    local cleaned=0

    for slot in $(seq 0 $((MAX_SLOTS - 1))); do
        local lease_name="${LEASE_PREFIX}-${slot}"

        # Get lease info (use creationTimestamp as fallback if acquireTime not set)
        local lease_info
        lease_info=$(oc get lease "$lease_name" -n "$NAMESPACE" \
            -o jsonpath='{.spec.acquireTime}|{.spec.leaseDurationSeconds}|{.metadata.creationTimestamp}' 2>/dev/null || echo "")

        [[ -z "$lease_info" ]] && continue

        local acquire_time duration creation_time
        acquire_time=$(echo "$lease_info" | cut -d'|' -f1)
        duration=$(echo "$lease_info" | cut -d'|' -f2)
        creation_time=$(echo "$lease_info" | cut -d'|' -f3)

        # Use acquireTime if set, otherwise fall back to creationTimestamp
        [[ -z "$acquire_time" ]] && acquire_time="$creation_time"
        [[ -z "$acquire_time" ]] && continue

        local acquire_epoch max_age age
        acquire_epoch=$(parse_iso_date "$acquire_time")
        max_age=${duration:-$LEASE_DURATION_SECONDS}
        age=$((now_epoch - acquire_epoch))

        if [[ $age -gt $max_age ]]; then
            echo "Found expired lease $lease_name (age: ${age}s > max: ${max_age}s)"
            # Delete with resourceVersion to ensure we delete the same lease we checked
            # This prevents deleting a lease that was just created by another job
            if oc delete lease "$lease_name" -n "$NAMESPACE" 2>/dev/null; then
                echo "  Deleted expired lease"
                ((cleaned++))
            else
                echo "  Lease was modified, skipping (another job may have taken it)"
            fi
        fi
    done

    return $((cleaned > 0 ? 0 : 1))
}

show_slot_status() {
    echo "Current slot status:"
    for slot in $(seq 0 $((MAX_SLOTS - 1))); do
        local info
        info=$(oc get lease "${LEASE_PREFIX}-${slot}" -n "$NAMESPACE" \
            -o jsonpath='{.spec.holderIdentity}|{.metadata.creationTimestamp}' 2>/dev/null || echo "")
        if [[ -z "$info" ]]; then
            echo "  slot-${slot}: (available)"
        else
            local holder acquired
            holder=$(echo "$info" | cut -d'|' -f1)
            acquired=$(echo "$info" | cut -d'|' -f2 | cut -d'T' -f1,2 | tr 'T' ' ')
            echo "  slot-${slot}: ${holder} (since ${acquired})"
        fi
    done
}

# Check if we already have a slot (idempotency)
check_existing_slot() {
    local existing_lease
    existing_lease=$(oc get leases -n "$NAMESPACE" -l app=kagenti-ci \
        -o jsonpath='{range .items[*]}{.metadata.name}|{.spec.holderIdentity}{"\n"}{end}' 2>/dev/null | \
        grep "|${CLUSTER_SUFFIX}:" | head -1 | cut -d'|' -f1 || echo "")

    if [[ -n "$existing_lease" ]]; then
        # Extract slot number from lease name (e.g., "kagenti-ci-slot-0" -> "0")
        local slot_num="${existing_lease##*-}"
        echo "Already have slot $slot_num (lease: $existing_lease)"
        ACQUIRED_SLOT="$slot_num"
        return 0
    fi
    return 1
}

# Main acquisition loop
echo "Attempting to acquire CI slot (max: $MAX_SLOTS, timeout: ${SLOT_TIMEOUT}m)..."
echo "Holder identity: $HOLDER_IDENTITY"
echo "Lease prefix: $LEASE_PREFIX"
echo ""

# Check if we already have a slot (idempotency for re-runs)
if check_existing_slot; then
    if [[ -n "${GITHUB_OUTPUT:-}" ]]; then
        echo "slot_id=$ACQUIRED_SLOT" >> "$GITHUB_OUTPUT"
    fi
    exit 0
fi

end_time=$(($(date +%s) + SLOT_TIMEOUT * 60))
attempt=0

while [[ $(date +%s) -lt $end_time ]]; do
    ((++attempt))

    # Phase 1: Try to create a slot (atomic, fast)
    if try_create_any_slot; then
        # Write to GitHub output
        if [[ -n "${GITHUB_OUTPUT:-}" ]]; then
            echo "slot_id=$ACQUIRED_SLOT" >> "$GITHUB_OUTPUT"
        fi

        # Clear trap (slot should not be released on normal exit from this script)
        trap - EXIT
        exit 0
    fi

    # Phase 2: All slots occupied - check for expired leases
    if cleanup_expired_leases; then
        echo "Cleaned up expired leases, retrying immediately..."
        continue  # Retry without waiting
    fi

    # No expired leases found, wait before retry
    remaining=$(( (end_time - $(date +%s)) / 60 ))
    echo ""
    echo "Attempt $attempt: All slots occupied, waiting 30s... (timeout in ${remaining}m)"
    show_slot_status
    echo ""

    # Add jitter to prevent thundering herd (15-45 seconds)
    sleep $((15 + RANDOM % 30))
done

echo ""
echo "ERROR: Timeout waiting for CI slot after ${SLOT_TIMEOUT} minutes"
show_slot_status
exit 1
