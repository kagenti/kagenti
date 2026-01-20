#!/usr/bin/env bash
# Verify management cluster access
set -euo pipefail

echo "Verifying management cluster access..."
echo "Using KUBECONFIG: $KUBECONFIG"

oc whoami

# Verify we can access the HyperShift API (list hostedclusters in clusters namespace)
# This doesn't require cluster-wide CRD read access
oc get hostedclusters -n clusters --no-headers 2>/dev/null || echo "(no clusters yet)"

# Verify we have permission to create hostedclusters
if ! oc auth can-i create hostedclusters -n clusters; then
    echo "Error: Service account cannot create hostedclusters"
    exit 1
fi

echo "Management cluster access verified"
