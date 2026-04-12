#!/usr/bin/env bash
#
# Push HyperShift CI Secrets to GitHub
#
# This script reads credentials from .env.kagenti-hypershift-ci,
# tests them locally, and pushes all secrets to GitHub Actions.
#
# USAGE:
#   ./.github/scripts/hypershift/generate-gh-secrets.sh
#

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
ENV_FILE="$REPO_ROOT/.env.kagenti-hypershift-ci"

# Check if .env file exists
if [ ! -f "$ENV_FILE" ]; then
    echo "ERROR: $ENV_FILE not found" >&2
    echo "Run: ./.github/scripts/hypershift/setup-hypershift-ci-credentials.sh --rotate" >&2
    exit 1
fi

# Source the environment file
# shellcheck disable=SC1090
source "$ENV_FILE"

# Validate required variables
REQUIRED_VARS=(
    "AWS_ACCESS_KEY_ID"
    "AWS_SECRET_ACCESS_KEY"
    "AWS_REGION"
    "HYPERSHIFT_MGMT_KUBECONFIG_BASE64"
    "HCP_ROLE_NAME"
    "BASE_DOMAIN"
    "MANAGED_BY_TAG"
    "PULL_SECRET"
)

for var in "${REQUIRED_VARS[@]}"; do
    if [ -z "${!var:-}" ]; then
        echo "ERROR: $var is not set in $ENV_FILE" >&2
        exit 1
    fi
done

echo "╔════════════════════════════════════════════════════════════════╗"
echo "║     Pushing GitHub Secrets for HyperShift CI                  ║"
echo "╚════════════════════════════════════════════════════════════════╝"
echo ""

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "Step 1: Testing AWS credentials locally..."
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

if ! aws sts get-caller-identity; then
    echo ""
    echo "❌ AWS credentials are INVALID"
    echo "   Please verify the credentials in .env.kagenti-hypershift-ci"
    exit 1
fi

echo ""
echo "✅ AWS credentials verified successfully"
echo ""

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "Step 2: Pushing secrets to GitHub..."
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

gh secret set AWS_ACCESS_KEY_ID -b"$AWS_ACCESS_KEY_ID"
gh secret set AWS_SECRET_ACCESS_KEY -b"$AWS_SECRET_ACCESS_KEY"
gh secret set AWS_REGION -b"$AWS_REGION"
gh secret set HCP_ROLE_NAME -b"$HCP_ROLE_NAME"
gh secret set BASE_DOMAIN -b"$BASE_DOMAIN"
gh secret set MANAGED_BY_TAG -b"$MANAGED_BY_TAG"
gh secret set PULL_SECRET -b"$PULL_SECRET"
gh secret set HYPERSHIFT_MGMT_KUBECONFIG_BASE64 -b"$HYPERSHIFT_MGMT_KUBECONFIG_BASE64"

echo ""
echo "✅ All secrets pushed to GitHub"
echo ""

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "Verification:"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "GitHub Secrets set:"
gh secret list | grep -E 'AWS_ACCESS_KEY_ID|AWS_SECRET_ACCESS_KEY|AWS_REGION|HCP_ROLE_NAME|BASE_DOMAIN|MANAGED_BY_TAG|PULL_SECRET|HYPERSHIFT_MGMT_KUBECONFIG_BASE64'

echo ""
echo "╔════════════════════════════════════════════════════════════════╗"
echo "║                    Setup Complete!                             ║"
echo "╚════════════════════════════════════════════════════════════════╝"
echo ""
echo "Next steps:"
echo "  1. Trigger a CI workflow to test the new credentials"
echo "  2. Monitor the cluster creation in GitHub Actions"
echo ""
