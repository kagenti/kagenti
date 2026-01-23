#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../lib/env-detect.sh"
source "$SCRIPT_DIR/../lib/logging.sh"
source "$SCRIPT_DIR/../lib/k8s-utils.sh"

log_step "41" "Waiting for Kagenti Operator CRDs"

# NOTE: agents.agent.kagenti.dev is NOT required for E2E tests since we now
# deploy agents using standard Kubernetes Deployments + Services directly.
# Only keeping CRDs that are still actively used in CI.
CRDS=(
    "mcpservers.mcp.kagenti.com"
    "mcpvirtualservers.mcp.kagenti.com"
)

for crd in "${CRDS[@]}"; do
    log_info "Waiting for CRD: $crd"
    wait_for_crd "$crd" || {
        log_error "CRD $crd not found"
        kubectl get crds | grep -E 'kagenti|mcp' || echo "No kagenti/mcp CRDs found"
        kubectl get pods -n kagenti-system
        exit 1
    }
done

log_success "All Kagenti Operator CRDs established"
