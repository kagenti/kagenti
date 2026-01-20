#!/usr/bin/env bash
# Deploy Kagenti to HyperShift cluster
set -euo pipefail

echo "Deploying Kagenti to cluster..."

# Check if deployments/ansible exists
if [ -d "deployments/ansible" ]; then
    cd deployments/ansible
    pip install -r requirements.txt 2>/dev/null || true
    ./run-install.sh --env ocp --no-kind
else
    echo "::warning::deployments/ansible not found, skipping Kagenti deployment"
fi

echo "Kagenti deployment complete"
