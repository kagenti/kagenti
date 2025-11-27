#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../lib/env-detect.sh"
source "$SCRIPT_DIR/../lib/logging.sh"
source "$SCRIPT_DIR/../lib/k8s-utils.sh"

log_step "71" "Building weather-tool image"

kubectl apply -f "$REPO_ROOT/kagenti/examples/agents/weather_tool_build.yaml"

# Wait for AgentBuild to exist
run_with_timeout 300 'until kubectl get agentbuild weather-tool-build -n team1 &> /dev/null; do sleep 2; done' || {
    log_error "AgentBuild not created after 300s"
    kubectl get agentbuilds -n team1
    exit 1
}

# Wait for build to succeed
for i in {1..60}; do
    phase=$(kubectl get agentbuild weather-tool-build -n team1 -o jsonpath='{.status.phase}' 2>/dev/null || echo "Unknown")
    log_info "AgentBuild phase: $phase"
    if [ "$phase" = "Succeeded" ]; then
        log_success "AgentBuild completed successfully"
        exit 0
    elif [ "$phase" = "Failed" ]; then
        log_error "AgentBuild failed"
        kubectl describe agentbuild weather-tool-build -n team1
        exit 1
    fi
    sleep 5
done

log_error "AgentBuild timeout"
exit 1
