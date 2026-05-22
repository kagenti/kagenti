#!/usr/bin/env bash
# Setup credentials for CI
set -euo pipefail

echo "Setting up credentials..."

# Validate required environment variables
if [[ -z "${HYPERSHIFT_MGMT_KUBECONFIG:-}" ]]; then
    echo "ERROR: HYPERSHIFT_MGMT_KUBECONFIG is not set"
    exit 1
fi
if [[ -z "${MANAGED_BY_TAG:-}" ]]; then
    echo "ERROR: MANAGED_BY_TAG is not set"
    exit 1
fi
if [[ -z "${PULL_SECRET:-}" ]]; then
    echo "ERROR: PULL_SECRET is not set"
    exit 1
fi

# Management cluster kubeconfig
mkdir -p ~/.kube
if ! echo "$HYPERSHIFT_MGMT_KUBECONFIG" | base64 -d > ~/.kube/${MANAGED_BY_TAG}-mgmt.kubeconfig 2>/dev/null; then
    echo "ERROR: Failed to decode HYPERSHIFT_MGMT_KUBECONFIG (invalid base64)"
    exit 1
fi

# Validate the decoded kubeconfig is valid YAML with expected structure
if ! grep -q "clusters:" ~/.kube/${MANAGED_BY_TAG}-mgmt.kubeconfig 2>/dev/null; then
    echo "ERROR: Decoded kubeconfig does not appear to be valid (missing 'clusters:' key)"
    rm -f ~/.kube/${MANAGED_BY_TAG}-mgmt.kubeconfig
    exit 1
fi
chmod 600 ~/.kube/${MANAGED_BY_TAG}-mgmt.kubeconfig

# Export KUBECONFIG for subsequent steps (and MGMT_KUBECONFIG for failure diagnostics)
echo "KUBECONFIG=$HOME/.kube/${MANAGED_BY_TAG}-mgmt.kubeconfig" >> "$GITHUB_ENV"
echo "MGMT_KUBECONFIG=$HOME/.kube/${MANAGED_BY_TAG}-mgmt.kubeconfig" >> "$GITHUB_ENV"

# Pull secret
mkdir -p ~/.docker
echo "$PULL_SECRET" > ~/.pullsecret.json
# Validate the pull secret is valid JSON
if ! python3 -c "import json; json.load(open('$HOME/.pullsecret.json'))" 2>/dev/null; then
    echo "ERROR: PULL_SECRET is not valid JSON"
    rm -f ~/.pullsecret.json
    exit 1
fi
chmod 600 ~/.pullsecret.json

echo "Credentials configured"
