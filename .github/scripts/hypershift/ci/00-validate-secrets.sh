#!/usr/bin/env bash
# Validate that all required secrets are configured
set -euo pipefail

echo "Validating secrets..."

missing=""
[ -z "${HYPERSHIFT_MGMT_KUBECONFIG:-}" ] && missing="$missing HYPERSHIFT_MGMT_KUBECONFIG"
[ -z "${AWS_ACCESS_KEY_ID:-}" ] && missing="$missing AWS_ACCESS_KEY_ID"
[ -z "${AWS_SECRET_ACCESS_KEY:-}" ] && missing="$missing AWS_SECRET_ACCESS_KEY"
[ -z "${AWS_REGION:-}" ] && missing="$missing AWS_REGION"
[ -z "${PULL_SECRET:-}" ] && missing="$missing PULL_SECRET"
[ -z "${BASE_DOMAIN:-}" ] && missing="$missing BASE_DOMAIN"
[ -z "${MANAGED_BY_TAG:-}" ] && missing="$missing MANAGED_BY_TAG"
[ -z "${HCP_ROLE_NAME:-}" ] && missing="$missing HCP_ROLE_NAME"

if [ -n "$missing" ]; then
    echo "::error::Missing required secrets:$missing"
    echo "Run setup-hypershift-ci-credentials.sh and add secrets to GitHub."
    exit 1
fi

echo "All required secrets are configured"
