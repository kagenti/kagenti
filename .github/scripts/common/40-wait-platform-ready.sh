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

# On Kind, reduce Kuadrant operator resource requests to fit within the
# 4-vCPU CI runner limit. Kuadrant defaults consume 860m CPU across 5
# deployments — reduce to ~200m total to leave room for agent pods.
if [ "$IS_OPENSHIFT" != "true" ] && kubectl get namespace kuadrant-system &>/dev/null 2>&1; then
    log_info "Reducing Kuadrant resource requests for Kind..."
    for deploy in kuadrant-operator-controller-manager authorino-operator limitador-operator dns-operator-controller-manager; do
        kubectl patch deployment "$deploy" -n kuadrant-system --type=json \
            -p '[{"op":"replace","path":"/spec/template/spec/containers/0/resources/requests/cpu","value":"25m"},
                 {"op":"replace","path":"/spec/template/spec/containers/0/resources/requests/memory","value":"64Mi"}]' 2>/dev/null || true
    done
    # Limitador is a data-plane component, reduce but keep functional
    kubectl patch deployment limitador-limitador -n kuadrant-system --type=json \
        -p '[{"op":"replace","path":"/spec/template/spec/containers/0/resources/requests/cpu","value":"50m"},
             {"op":"replace","path":"/spec/template/spec/containers/0/resources/requests/memory","value":"64Mi"}]' 2>/dev/null || true
    log_info "Waiting for Kuadrant rollouts..."
    kubectl rollout status deployment -n kuadrant-system --timeout=120s 2>/dev/null || true
    log_success "Kuadrant resources reduced for Kind"
fi
