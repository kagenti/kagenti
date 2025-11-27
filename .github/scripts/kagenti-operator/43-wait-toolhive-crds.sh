#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../lib/env-detect.sh"
source "$SCRIPT_DIR/../lib/logging.sh"
source "$SCRIPT_DIR/../lib/k8s-utils.sh"

log_step "43" "Waiting for Toolhive CRDs"

wait_for_crd "mcpservers.toolhive.stacklok.dev" || {
    log_error "Toolhive MCPServer CRD not found"
    kubectl get crds | grep -E 'toolhive|mcp' || echo "No toolhive/mcp CRDs found"
    kubectl get pods -n toolhive-system || echo "No toolhive-system namespace"
    exit 1
}

log_success "Toolhive CRDs established"
