#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../lib/env-detect.sh"
source "$SCRIPT_DIR/../lib/logging.sh"
source "$SCRIPT_DIR/../lib/runtime-detect.sh"

log_step "70" "Configuring dockerhost service"

# Get Docker host IP based on the detected K8s runtime.
# The IP must be reachable from inside pods for Ollama access.
DOCKER_HOST_IP=""

case "${K8S_RUNTIME:-kind}" in
    kind)
        log_info "Kind runtime: using Docker 'kind' network gateway"
        DOCKER_HOST_IP=$(docker network inspect kind | jq -r '.[].IPAM.Config[] | select(.Gateway != null) | .Gateway' | grep -E '^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$' | head -1)
        ;;
    rancher-desktop)
        log_info "Rancher Desktop runtime: discovering host IP from pod network"
        # Rancher Desktop runs K3s in a Lima VM. Pods reach the macOS host
        # via the VM's default gateway. We probe it from inside a pod.
        DOCKER_HOST_IP=$(kubectl run --rm -i --restart=Never --image=busybox:1.36 detect-gw-$RANDOM \
            --timeout=30s -- sh -c "ip route | grep default | awk '{print \$3}'" 2>/dev/null | tr -d '[:space:]' || true)

        if [ -z "$DOCKER_HOST_IP" ] || ! echo "$DOCKER_HOST_IP" | grep -qE '^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$'; then
            log_warn "Gateway probe failed, trying node ExternalIP..."
            DOCKER_HOST_IP=$(kubectl get nodes -o jsonpath='{.items[0].status.addresses[?(@.type=="ExternalIP")].address}' 2>/dev/null)
        fi

        if [ -z "$DOCKER_HOST_IP" ] || ! echo "$DOCKER_HOST_IP" | grep -qE '^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$'; then
            log_warn "ExternalIP not found, using node InternalIP as fallback..."
            DOCKER_HOST_IP=$(kubectl get nodes -o jsonpath='{.items[0].status.addresses[?(@.type=="InternalIP")].address}' 2>/dev/null)
        fi
        ;;
    minikube)
        log_info "Minikube runtime: using minikube ip"
        DOCKER_HOST_IP=$(minikube ip 2>/dev/null)
        ;;
    *)
        log_info "Unknown runtime: trying Docker 'kind' network, then node IP"
        DOCKER_HOST_IP=$(docker network inspect kind 2>/dev/null | jq -r '.[].IPAM.Config[] | select(.Gateway != null) | .Gateway' | grep -E '^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$' | head -1 || true)
        if [ -z "$DOCKER_HOST_IP" ]; then
            DOCKER_HOST_IP=$(kubectl get nodes -o jsonpath='{.items[0].status.addresses[?(@.type=="InternalIP")].address}' 2>/dev/null || true)
        fi
        ;;
esac

if [ -z "$DOCKER_HOST_IP" ] || [ "$DOCKER_HOST_IP" = "null" ]; then
    log_error "Could not determine Docker host IP for runtime: ${K8S_RUNTIME:-unknown}"
    log_error "Set DOCKER_HOST_IP manually and re-run, or check cluster connectivity."
    exit 1
fi

log_info "Docker host IP: ${DOCKER_HOST_IP} (runtime: ${K8S_RUNTIME:-unknown})"

# Apply service configuration
cat <<EOF | kubectl apply -f -
apiVersion: discovery.k8s.io/v1
kind: EndpointSlice
metadata:
  name: dockerhost
  namespace: team1
  labels:
    kubernetes.io/service-name: dockerhost
addressType: IPv4
endpoints:
- addresses:
  - ${DOCKER_HOST_IP}
  conditions:
    ready: true
ports:
- name: ollama
  port: 11434
  protocol: TCP
---
apiVersion: v1
kind: Service
metadata:
  name: dockerhost
  namespace: team1
spec:
  clusterIP: None
EOF

kubectl get service dockerhost -n team1
kubectl get endpointslice dockerhost -n team1

log_success "Dockerhost configured"
