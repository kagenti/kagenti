#!/usr/bin/env bash
# Collect cluster info on failure for debugging
set -euo pipefail

echo "=== Cluster Status ==="
oc get nodes || true
oc get clusterversion || true

echo ""
echo "=== Pods in kagenti-system ==="
oc get pods -n kagenti-system || true

echo ""
echo "=== Recent Events ==="
oc get events -A --sort-by='.lastTimestamp' | tail -50 || true
