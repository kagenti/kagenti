#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../lib/env-detect.sh"
source "$SCRIPT_DIR/../lib/logging.sh"
source "$SCRIPT_DIR/../lib/k8s-utils.sh"

log_step "70" "Setting up team1 namespace"

# Create team1 namespace if it doesn't exist
if kubectl get namespace team1 &>/dev/null; then
    log_info "Namespace team1 already exists"
else
    log_info "Creating team1 namespace..."
    kubectl create namespace team1
    log_success "Namespace team1 created"
fi

# Label namespace for Kagenti
log_info "Labeling team1 namespace for Kagenti..."
kubectl label namespace team1 kagenti-enabled=true --overwrite

# IS_OPENSHIFT is set by env-detect.sh (sourced above)
# It checks for OpenShift-specific APIs, not just "oc whoami" which works on any cluster

# Label namespace for Istio ambient mode
log_info "Labeling team1 namespace for Istio ambient mode..."
kubectl label namespace team1 \
    istio-discovery=enabled \
    istio.io/dataplane-mode=ambient \
    --overwrite

if [ "$IS_OPENSHIFT" = "true" ]; then
    # Grant workloads access to pull images from internal registry
    log_info "Granting image pull access for OpenShift..."
    oc policy add-role-to-user system:image-puller system:serviceaccount:team1:default -n team1 || true
fi

log_success "team1 namespace is ready"

# Show namespace status
kubectl get namespace team1 --show-labels
