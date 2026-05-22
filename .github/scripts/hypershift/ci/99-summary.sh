#!/usr/bin/env bash
# Output summary information
set -euo pipefail

echo "## E2E Test Summary"
echo ""
echo "| Property | Value |"
echo "|----------|-------|"
echo "| Cluster Name | ${CLUSTER_NAME:-${MANAGED_BY_TAG}-${CLUSTER_SUFFIX}} |"
echo "| OCP Version | ${OCP_VERSION} |"
echo "| Region | ${AWS_REGION} |"
echo "| Cluster Suffix | ${CLUSTER_SUFFIX} |"
echo "| Create Outcome | ${CREATE_OUTCOME:-N/A} |"
echo "| Skip Destroy | ${SKIP_DESTROY:-false} |"
echo ""
echo "Test run completed."
