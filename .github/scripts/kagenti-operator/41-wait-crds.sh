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
#
# MCP gateway v0.6.0 renamed the CRD group from mcp.kuadrant.io to
# mcp.kagenti.com. Kind CI still uses the old version; HyperShift uses the new.
# Detect which domain is present, then wait for those CRDs.
MCP_RESOURCES=(
    "mcpserverregistrations"
    "mcpvirtualservers"
    "mcpgatewayextensions"
)

# Detect which MCP CRD domain is installed.
# Retry up to 60s since operators may still be registering CRDs.
MCP_DOMAIN=""
for i in $(seq 1 12); do
    if kubectl get crd "mcpserverregistrations.mcp.kagenti.com" &>/dev/null; then
        MCP_DOMAIN="mcp.kagenti.com"
        break
    elif kubectl get crd "mcpserverregistrations.mcp.kuadrant.io" &>/dev/null; then
        MCP_DOMAIN="mcp.kuadrant.io"
        break
    fi
    log_info "MCP CRDs not yet available, retrying ($i/12)..."
    sleep 5
done
if [ -z "$MCP_DOMAIN" ]; then
    MCP_DOMAIN="mcp.kagenti.com"
    log_info "Defaulting to $MCP_DOMAIN (neither domain detected after 60s)"
fi
log_info "MCP CRD domain: $MCP_DOMAIN"

for resource in "${MCP_RESOURCES[@]}"; do
    crd="${resource}.${MCP_DOMAIN}"
    log_info "Waiting for CRD: $crd"
    wait_for_crd "$crd" || {
        log_error "CRD $crd not found"
        kubectl get crds | grep -E 'kagenti|mcp' || echo "No kagenti/mcp CRDs found"
        kubectl get pods -n kagenti-system
        exit 1
    }
done

log_success "All Kagenti Operator CRDs established"
