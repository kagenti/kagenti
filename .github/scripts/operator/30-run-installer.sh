#!/usr/bin/env bash
#
# Run Rossoctl Platform Installer
#
# USAGE:
#   ./.github/scripts/operator/30-run-installer.sh [--env <dev|ocp>] [extra-args...]
#
# EXAMPLES:
#   ./.github/scripts/operator/30-run-installer.sh              # Default: --env dev
#   ./.github/scripts/operator/30-run-installer.sh --env ocp    # OpenShift/HyperShift
#   ./.github/scripts/operator/30-run-installer.sh --env dev --preload
#
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../lib/env-detect.sh"
source "$SCRIPT_DIR/../lib/logging.sh"

# Default environment
ENV="dev"
EXTRA_ARGS=()

# Parse arguments (--env is accepted for backwards compatibility but not forwarded)
while [[ $# -gt 0 ]]; do
    case "$1" in
        --env)
            shift
            ENV="${1:-dev}"
            shift
            log_warn "--env is deprecated and ignored; setup-rossoctl.sh does not use it"
            ;;
        *)
            EXTRA_ARGS+=("$1")
            shift
            ;;
    esac
done

log_step "30" "Running platform installer (Rossoctl Operator)"

"$REPO_ROOT/scripts/kind/setup-rossoctl.sh" "${EXTRA_ARGS[@]+"${EXTRA_ARGS[@]}"}"

log_success "Platform installer complete"
