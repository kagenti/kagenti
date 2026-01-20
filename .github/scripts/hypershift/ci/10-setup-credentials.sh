#!/usr/bin/env bash
# Setup credentials for CI
set -euo pipefail

echo "Setting up credentials..."

# Management cluster kubeconfig
mkdir -p ~/.kube
echo "$HYPERSHIFT_MGMT_KUBECONFIG" | base64 -d > ~/.kube/${MANAGED_BY_TAG}-mgmt.kubeconfig
chmod 600 ~/.kube/${MANAGED_BY_TAG}-mgmt.kubeconfig

# Export KUBECONFIG for subsequent steps
echo "KUBECONFIG=$HOME/.kube/${MANAGED_BY_TAG}-mgmt.kubeconfig" >> "$GITHUB_ENV"

# Pull secret
mkdir -p ~/.docker
echo "$PULL_SECRET" > ~/.pullsecret.json
chmod 600 ~/.pullsecret.json

echo "Credentials configured"
