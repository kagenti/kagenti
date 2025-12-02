#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../lib/env-detect.sh"
source "$SCRIPT_DIR/../lib/logging.sh"

log_step "70" "Configuring dockerhost service"

# Get Docker host IP
# On macOS, we need to use host.docker.internal which is the host machine as seen from containers
# The Docker network gateway (172.18.0.1) doesn't work on macOS because Docker runs in a VM
if [[ "${IS_MACOS:-false}" == "true" ]]; then
    # Resolve host.docker.internal to get the actual IP from inside a Kind pod
    DOCKER_HOST_IP=$(kubectl run docker-host-lookup --image=busybox:1.28 --rm -it --restart=Never --quiet -- nslookup host.docker.internal 2>/dev/null | grep "Address" | tail -1 | awk '{print $NF}' || echo "")

    # Fallback: try from the Kind container if kubectl pod fails
    if [ -z "$DOCKER_HOST_IP" ] || [ "$DOCKER_HOST_IP" = "" ]; then
        DOCKER_HOST_IP=$(docker exec kagenti-control-plane getent hosts host.docker.internal 2>/dev/null | awk '{print $1}' || echo "")
    fi

    if [ -z "$DOCKER_HOST_IP" ] || [ "$DOCKER_HOST_IP" = "" ]; then
        log_error "Could not resolve host.docker.internal"
        exit 1
    fi
    log_info "macOS: Using host.docker.internal IP: ${DOCKER_HOST_IP}"
else
    # On Linux, use the Docker network gateway
    DOCKER_HOST_IP=$(docker network inspect kind | jq -r '.[].IPAM.Config[] | select(.Gateway != null) | .Gateway' | head -1)

    if [ -z "$DOCKER_HOST_IP" ] || [ "$DOCKER_HOST_IP" = "null" ]; then
        log_error "Could not determine Docker host IP"
        docker network inspect kind | jq '.[].IPAM.Config[]'
        exit 1
    fi
    log_info "Linux: Docker host IP: ${DOCKER_HOST_IP}"
fi

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
