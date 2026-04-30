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

# Strategy: resolve host.docker.internal from inside a pod. This is the standard
# Docker Desktop / Rancher Desktop DNS name that resolves to the host machine.
# On macOS, the Docker bridge gateway IP (172.18.0.1) is NOT reachable from pods
# because Docker runs in a VM — only host.docker.internal works reliably.
#
# Security note: We only expose port 11434 (Ollama) via the EndpointSlice.
# A NetworkPolicy should be applied to restrict which pods can access it.
# This pattern is for LOCAL DEV ONLY — production uses LiteLLM with API keys.

log_info "Resolving host IP via host.docker.internal..."
DOCKER_HOST_IP=$(kubectl run --rm -i --restart=Never --image=busybox:1.36 detect-host-$RANDOM \
    --timeout=30s -- sh -c "nslookup host.docker.internal 2>/dev/null | grep -A1 'Name:' | grep 'Address:' | awk '{print \$2}'" 2>/dev/null | tr -d '[:space:]' || true)

# Fallback strategies per runtime if host.docker.internal didn't resolve
if [ -z "$DOCKER_HOST_IP" ] || ! echo "$DOCKER_HOST_IP" | grep -qE '^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$'; then
    log_warn "host.docker.internal not available, trying runtime-specific fallback..."
    case "${K8S_RUNTIME:-kind}" in
        kind)
            DOCKER_HOST_IP=$(docker network inspect kind 2>/dev/null | jq -r '.[].IPAM.Config[] | select(.Gateway != null) | .Gateway' | grep -E '^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$' | head -1)
            ;;
        rancher-desktop)
            DOCKER_HOST_IP=$(kubectl get nodes -o jsonpath='{.items[0].status.addresses[?(@.type=="ExternalIP")].address}' 2>/dev/null)
            ;;
        minikube)
            DOCKER_HOST_IP=$(minikube ip 2>/dev/null)
            ;;
        *)
            DOCKER_HOST_IP=$(kubectl get nodes -o jsonpath='{.items[0].status.addresses[?(@.type=="InternalIP")].address}' 2>/dev/null || true)
            ;;
    esac
fi

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
---
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: dockerhost-egress
  namespace: team1
spec:
  podSelector: {}
  policyTypes:
  - Egress
  egress:
  - to:
    - ipBlock:
        cidr: ${DOCKER_HOST_IP}/32
    ports:
    - port: 11434
      protocol: TCP
EOF

kubectl get service dockerhost -n team1
kubectl get endpointslice dockerhost -n team1

log_success "Dockerhost configured (host IP: ${DOCKER_HOST_IP}, port 11434 only)"
