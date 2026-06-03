#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../lib/env-detect.sh"
source "$SCRIPT_DIR/../lib/logging.sh"
source "$SCRIPT_DIR/../lib/k8s-utils.sh"

log_step "41" "Waiting for Kagenti Operator CRDs"

# Check if MCP Gateway is installed before waiting for its CRDs.
# The mcp-gateway chart is optional (requires --with-mcp-gateway or --with-all
# on Kind, and is skipped by default on HyperShift/OCP).
MCP_GATEWAY_INSTALLED=false
if helm list -n mcp-system -q 2>/dev/null | grep -q "^mcp-gateway$"; then
    MCP_GATEWAY_INSTALLED=true
elif kubectl get namespace mcp-system &>/dev/null && \
     kubectl get crds 2>/dev/null | grep -q "mcp\.\(kuadrant\.io\|kagenti\.com\)"; then
    MCP_GATEWAY_INSTALLED=true
fi

if [ "$MCP_GATEWAY_INSTALLED" = "false" ]; then
    log_info "MCP Gateway not installed — skipping MCP CRD validation"
else
    MCP_RESOURCES=(
        "mcpserverregistrations"
        "mcpvirtualservers"
        "mcpgatewayextensions"
    )

    # Detect which MCP CRD domain is installed.
    # Retry up to 60s since operators may still be registering CRDs.
    MCP_DOMAIN=""
    for i in $(seq 1 12); do
        if kubectl get crd "mcpserverregistrations.mcp.kuadrant.io" &>/dev/null; then
            MCP_DOMAIN="mcp.kuadrant.io"
            break
        elif kubectl get crd "mcpserverregistrations.mcp.kagenti.com" &>/dev/null; then
            MCP_DOMAIN="mcp.kagenti.com"
            break
        fi
        log_info "MCP CRDs not yet available, retrying ($i/12)..."
        sleep 5
    done
    if [ -z "$MCP_DOMAIN" ]; then
        MCP_DOMAIN="mcp.kuadrant.io"
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
fi

log_success "All Kagenti Operator CRDs established"

# Wait for kagenti-operator deployment to be ready.
# The operator's ClientRegistrationReconciler creates per-workload credential
# secrets when agent pods are admitted by the webhook.  If the operator isn't
# Running/Ready by the time agents are deployed (scripts 70+), pods get stuck
# in ContainerCreating waiting for the secret volume.
log_info "Waiting for kagenti-operator deployment to be ready..."
wait_for_deployment "kagenti-operator" "kagenti-system" 120 || {
    log_error "kagenti-operator not ready — credential secrets won't be created for agent pods"
    exit 1
}
log_success "kagenti-operator is ready"
