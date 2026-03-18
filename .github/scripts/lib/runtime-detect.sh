#!/usr/bin/env bash
# Runtime Detection Library
# Detects the local Kubernetes runtime (Kind, K3s/Rancher Desktop, Minikube, etc.)
#
# Exports:
#   K8S_RUNTIME    - kind | rancher-desktop | k3s | minikube | existing | none
#   K8S_CONTEXT    - kubectl context name for the detected runtime
#
# Usage:
#   source "$SCRIPT_DIR/../lib/runtime-detect.sh"

# Don't use set -euo pipefail in sourced library

detect_k8s_runtime() {
    # User override takes priority
    if [ -n "${K8S_RUNTIME:-}" ]; then
        echo "$K8S_RUNTIME"
        return
    fi

    local ctx
    ctx=$(kubectl config current-context 2>/dev/null || echo "")

    if echo "$ctx" | grep -q "^kind-"; then
        echo "kind"
    elif echo "$ctx" | grep -q "rancher-desktop"; then
        echo "rancher-desktop"
    elif echo "$ctx" | grep -q "minikube"; then
        echo "minikube"
    elif [ -n "$ctx" ] && kubectl get nodes &>/dev/null; then
        echo "existing"
    else
        echo "none"
    fi
}

# Get the kubectl context for a runtime
get_runtime_context() {
    local runtime="${1:-$(detect_k8s_runtime)}"
    case "$runtime" in
        kind)
            echo "kind-${CLUSTER_NAME:-kagenti}"
            ;;
        rancher-desktop)
            echo "rancher-desktop"
            ;;
        minikube)
            echo "minikube"
            ;;
        existing)
            kubectl config current-context 2>/dev/null || echo ""
            ;;
        *)
            echo ""
            ;;
    esac
}

# Get the host IP reachable from inside pods (for Ollama/dockerhost)
get_host_ip_for_runtime() {
    local runtime="${1:-$(detect_k8s_runtime)}"
    case "$runtime" in
        kind)
            # Kind: use Docker network gateway
            docker network inspect kind 2>/dev/null | \
                jq -r '.[].IPAM.Config[] | select(.Gateway != null) | .Gateway' | \
                grep -E '^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$' | head -1
            ;;
        rancher-desktop)
            # Rancher Desktop with moby: host.docker.internal resolves inside pods
            # But for EndpointSlice we need an actual IP.
            # The node's default gateway points to the host via Lima networking.
            # Strategy: use the node's InternalIP gateway or known Lima host IP.
            local node_ip
            node_ip=$(kubectl get nodes -o jsonpath='{.items[0].status.addresses[?(@.type=="InternalIP")].address}' 2>/dev/null)
            if [ -n "$node_ip" ]; then
                # The Lima VM's gateway (host) is typically on the same subnet
                # For vz/virtiofs VMs, the host is reachable via the gateway
                local gateway
                gateway=$(kubectl run --rm -i --restart=Never --image=busybox:1.36 detect-gw --timeout=30s -- \
                    sh -c "ip route | grep default | awk '{print \$3}'" 2>/dev/null | tr -d '[:space:]')
                if [ -n "$gateway" ] && echo "$gateway" | grep -qE '^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$'; then
                    echo "$gateway"
                else
                    # Fallback: use the external IP if available (Lima VM host-facing IP)
                    local ext_ip
                    ext_ip=$(kubectl get nodes -o jsonpath='{.items[0].status.addresses[?(@.type=="ExternalIP")].address}' 2>/dev/null)
                    if [ -n "$ext_ip" ]; then
                        echo "$ext_ip"
                    else
                        echo "$node_ip"
                    fi
                fi
            else
                echo ""
            fi
            ;;
        minikube)
            minikube ip 2>/dev/null || echo ""
            ;;
        *)
            echo ""
            ;;
    esac
}

# Check if the runtime's cluster is ready
is_cluster_ready() {
    local runtime="${1:-$(detect_k8s_runtime)}"
    local ctx
    ctx=$(get_runtime_context "$runtime")

    if [ -z "$ctx" ]; then
        return 1
    fi

    kubectl --context "$ctx" get nodes &>/dev/null 2>&1
}

# Export detected values
export K8S_RUNTIME="${K8S_RUNTIME:-$(detect_k8s_runtime)}"
export K8S_CONTEXT="$(get_runtime_context "$K8S_RUNTIME")"

echo "Detected K8s runtime: $K8S_RUNTIME (context: $K8S_CONTEXT)"
