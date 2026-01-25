#!/usr/bin/env bash
# .github/scripts/hypershift/ci/slots/release.sh
#
# Releases a CI slot by deleting the Lease.
# Always succeeds (idempotent).
#
# Usage:
#   release.sh <slot_id>              - Release specific slot by ID
#   release.sh                        - Find and release slot by CLUSTER_SUFFIX
#   CLUSTER_SUFFIX=foo release.sh     - Find and release slot for cluster "foo"

set -uo pipefail

SLOT_ID="${1:-}"
NAMESPACE="clusters"
LEASE_PREFIX="kagenti-ci-slot"  # Namespaced prefix to avoid conflicts
CLUSTER_SUFFIX="${CLUSTER_SUFFIX:-}"

# If no slot_id provided, try to find slot by CLUSTER_SUFFIX
if [[ -z "$SLOT_ID" ]] && [[ -n "$CLUSTER_SUFFIX" ]]; then
    echo "No slot ID provided, searching for slot with CLUSTER_SUFFIX: $CLUSTER_SUFFIX"

    # Find lease with matching holderIdentity (format: CLUSTER_SUFFIX:RUN_ID)
    MATCHING_LEASE=$(oc get leases -n "$NAMESPACE" -l app=kagenti-ci \
        -o jsonpath='{range .items[*]}{.metadata.name}|{.spec.holderIdentity}{"\n"}{end}' 2>/dev/null | \
        grep "^${LEASE_PREFIX}-.*|${CLUSTER_SUFFIX}:" | head -1 | cut -d'|' -f1 || echo "")

    if [[ -n "$MATCHING_LEASE" ]]; then
        echo "Found matching lease: $MATCHING_LEASE"
        if oc delete lease "$MATCHING_LEASE" -n "$NAMESPACE" --ignore-not-found 2>/dev/null; then
            echo "Released slot (lease: $MATCHING_LEASE)"
        fi
    else
        echo "No slot found for CLUSTER_SUFFIX: $CLUSTER_SUFFIX"
    fi
    exit 0
fi

if [[ -z "$SLOT_ID" ]]; then
    echo "No slot ID or CLUSTER_SUFFIX provided, nothing to release"
    exit 0
fi

LEASE_NAME="${LEASE_PREFIX}-${SLOT_ID}"

if oc delete lease "$LEASE_NAME" -n "$NAMESPACE" --ignore-not-found 2>/dev/null; then
    echo "Released slot $SLOT_ID (lease: $LEASE_NAME)"
else
    echo "Slot $SLOT_ID already released or never acquired"
fi

exit 0
