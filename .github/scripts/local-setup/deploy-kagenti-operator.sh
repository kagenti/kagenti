#!/usr/bin/env bash
# Convenience script to deploy with Kagenti Operator
# Mirrors GitHub Actions: pr-kind-deployment-kagenti-operator.yaml

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "$SCRIPT_DIR/deploy-platform.sh" --mode kagenti "$@"
