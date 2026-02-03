#!/usr/bin/env bash
#
# Run Full OpenShift Test (wrapper for hypershift-full-test.sh)
#
# Deploys Kagenti to an existing OpenShift cluster, deploys test agents, and runs E2E tests.
# This is a thin wrapper around hypershift-full-test.sh with cluster create/destroy disabled.
#
# USAGE:
#   oc login https://api.your-cluster.example.com:6443 -u kubeadmin -p <password>
#   ./.github/scripts/local-setup/openshift-full-test.sh [options]
#
# PREREQUISITES:
#   - oc CLI installed and logged in with cluster-admin access
#   - No AWS credentials or .env file needed
#
# EXAMPLES:
#   # Full kagenti test cycle
#   ./.github/scripts/local-setup/openshift-full-test.sh
#
#   # Iterate on existing deployment (skip reinstall)
#   ./.github/scripts/local-setup/openshift-full-test.sh --skip-kagenti-install
#
#   # Run only tests
#   ./.github/scripts/local-setup/openshift-full-test.sh --include-test
#

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Override script name and description for help text
export SCRIPT_NAME="openshift-full-test.sh"
export SCRIPT_DESCRIPTION="Run full OpenShift test cycle: deploy Kagenti, run tests. (No cluster create/destroy)"

# Call the main script with cluster phases disabled
exec "$SCRIPT_DIR/hypershift-full-test.sh" \
    --skip-cluster-create \
    --skip-cluster-destroy \
    "$@"
