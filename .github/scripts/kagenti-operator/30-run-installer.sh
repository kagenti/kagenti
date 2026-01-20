#!/usr/bin/env bash
#
# Run Kagenti Ansible Installer
#
# USAGE:
#   ./.github/scripts/kagenti-operator/30-run-installer.sh [--env <dev|ocp>] [extra-args...]
#
# EXAMPLES:
#   ./.github/scripts/kagenti-operator/30-run-installer.sh              # Default: --env dev
#   ./.github/scripts/kagenti-operator/30-run-installer.sh --env ocp    # OpenShift/HyperShift
#   ./.github/scripts/kagenti-operator/30-run-installer.sh --env dev --preload
#
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../lib/env-detect.sh"
source "$SCRIPT_DIR/../lib/logging.sh"

# Default environment
ENV="dev"
EXTRA_ARGS=()

# Parse arguments
while [[ $# -gt 0 ]]; do
    case "$1" in
        --env)
            shift
            ENV="${1:-dev}"
            shift
            ;;
        *)
            EXTRA_ARGS+=("$1")
            shift
            ;;
    esac
done

log_step "30" "Running Ansible installer (Kagenti Operator) with --env $ENV"

cd "$REPO_ROOT/deployments/ansible"
./run-install.sh --env "$ENV" "${EXTRA_ARGS[@]+"${EXTRA_ARGS[@]}"}"

log_success "Ansible installer complete"
