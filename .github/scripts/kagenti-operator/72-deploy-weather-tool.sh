#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../lib/env-detect.sh"
source "$SCRIPT_DIR/../lib/logging.sh"
source "$SCRIPT_DIR/../lib/k8s-utils.sh"

log_step "72" "Deploying weather-tool via Toolhive"

# IS_OPENSHIFT is set by env-detect.sh (sourced above)
# It checks for OpenShift-specific APIs, not just "oc whoami" which works on any cluster
if [ "$IS_OPENSHIFT" = "true" ]; then
    log_info "Using OpenShift MCPServer with internal registry"
else
    log_info "Using Kind MCPServer"
fi

if [ "$IS_OPENSHIFT" = "true" ]; then
    # Use OpenShift-specific MCPServer that references the internal registry
    kubectl apply -f "$REPO_ROOT/kagenti/examples/mcpservers/weather_tool_ocp.yaml"
else
    # Use the standard MCPServer for Kind with internal registry
    kubectl apply -f "$REPO_ROOT/kagenti/examples/mcpservers/weather_tool.yaml"
fi

# Wait for deployment to exist (but don't wait for it to be ready yet - needs patch first)
run_with_timeout 300 'until kubectl get deployment weather-tool -n team1 &> /dev/null; do sleep 2; done' || {
    log_error "Deployment not created after 300s"
    kubectl get mcpservers -n team1
    kubectl describe mcpserver weather-tool -n team1
    kubectl logs -n toolhive-system deployment/toolhive-operator --tail=100 || true
    exit 1
}

log_success "Weather-tool deployment created (will be patched in next step)"
