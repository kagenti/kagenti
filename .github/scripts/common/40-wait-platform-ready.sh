#!/usr/bin/env bash
# Wait for Platform to be Ready (Wave 40)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../lib/env-detect.sh"
source "$SCRIPT_DIR/../lib/logging.sh"

log_step "40" "Waiting for platform to be ready"

# Wait for core platform components to be ready
kubectl wait --for=condition=available --timeout=300s deployment -n kagenti-system --all || {
    log_error "Platform components not ready"
    kubectl get pods -A
    kubectl get events -A --sort-by='.lastTimestamp' | tail -30
    exit 1
}

log_success "Platform is ready"
