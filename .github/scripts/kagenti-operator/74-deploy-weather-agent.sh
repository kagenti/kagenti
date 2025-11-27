#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../lib/env-detect.sh"
source "$SCRIPT_DIR/../lib/logging.sh"
source "$SCRIPT_DIR/../lib/k8s-utils.sh"

log_step "74" "Deploying weather-service agent"

kubectl apply -f "$REPO_ROOT/kagenti/examples/agents/weather_agent_build.yaml"
kubectl apply -f "$REPO_ROOT/kagenti/examples/agents/weather_agent.yaml"

# Wait for deployment
run_with_timeout 300 'until kubectl get deployment weather-service -n team1 &> /dev/null; do sleep 2; done' || {
    log_error "Deployment not created"
    kubectl logs -n kagenti-system deployment/kagenti-controller-manager --tail=100
    kubectl get agents -n team1
    kubectl describe agent weather-service -n team1
    exit 1
}

kubectl wait --for=condition=available --timeout=300s deployment/weather-service -n team1 || {
    log_error "Deployment not available"
    kubectl get events -n team1 --sort-by='.lastTimestamp'
    exit 1
}

log_success "Weather-service deployed"
