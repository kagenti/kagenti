#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../lib/env-detect.sh"
source "$SCRIPT_DIR/../lib/logging.sh"
source "$SCRIPT_DIR/../lib/k8s-utils.sh"

log_step "73" "Patching weather-tool for writable /tmp"

# Wait for both Deployment and StatefulSet to exist (can take time for Toolhive to create StatefulSet)
run_with_timeout 300 'until kubectl get deployment weather-tool -n team1 &> /dev/null && kubectl get statefulset weather-tool -n team1 &> /dev/null; do sleep 2; done' || {
    log_error "Deployment or StatefulSet not created after 300s"
    kubectl get deployment,statefulset -n team1
    exit 1
}

# Patch Deployment (Toolhive proxy runner)
log_info "Patching Deployment for writable /tmp"
kubectl patch deployment weather-tool -n team1 -p '{"spec":{"template":{"spec":{"volumes":[{"name":"tmp","emptyDir":{}}],"containers":[{"name":"toolhive","volumeMounts":[{"name":"tmp","mountPath":"/tmp"}]}]}}}}'

# Patch StatefulSet (MCP server)
log_info "Patching StatefulSet for writable /tmp"
kubectl patch statefulset weather-tool -n team1 -p '{"spec":{"template":{"spec":{"volumes":[{"name":"tmp","emptyDir":{}}],"containers":[{"name":"mcp","volumeMounts":[{"name":"tmp","mountPath":"/tmp"}]}]}}}}'

# Delete pods to force recreation
log_info "Deleting pods to force recreation with new volume mounts"
kubectl delete pod -n team1 -l app=weather-tool --wait=false || true
kubectl delete pod -n team1 -l app=mcpserver --wait=false || true

# Wait for new pod
kubectl wait --for=condition=ready --timeout=300s pod -n team1 -l app=weather-tool || {
    log_error "Pod not ready after patch"
    kubectl get pods -n team1 -l app=weather-tool
    kubectl logs -n team1 -l app=weather-tool --tail=50 || true
    exit 1
}

# Also wait for deployment to be available
kubectl wait --for=condition=available --timeout=300s deployment/weather-tool -n team1 || {
    log_error "Deployment not available after patch"
    kubectl get events -n team1 --sort-by='.lastTimestamp' | tail -20
    kubectl describe deployment weather-tool -n team1
    exit 1
}

log_success "Weather-tool patched and ready"
