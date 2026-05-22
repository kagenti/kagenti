#!/usr/bin/env bash
# Kubernetes Utilities Library
# Provides helper functions for Kubernetes operations

# Cross-platform timeout wrapper
# On Linux: uses timeout command
# On macOS: uses perl-based timeout (timeout not available)
run_with_timeout() {
    local timeout_seconds="$1"
    shift
    local command="$*"

    if command -v timeout &> /dev/null; then
        # Linux/GNU timeout available
        timeout "$timeout_seconds" bash -c "$command"
    else
        # macOS fallback using perl
        perl -e "alarm $timeout_seconds; exec @ARGV" bash -c "$command"
    fi
}

# Wait for deployment to be available
wait_for_deployment() {
    local deployment="$1"
    local namespace="$2"
    local timeout="${3:-300}"

    kubectl wait --for=condition=available --timeout="${timeout}s" "deployment/$deployment" -n "$namespace" || {
        echo "ERROR: Deployment $deployment not ready in $namespace"
        kubectl describe "deployment/$deployment" -n "$namespace"
        kubectl get events -n "$namespace" --sort-by='.lastTimestamp' | tail -30
        return 1
    }
}

# Wait for pod to be ready
wait_for_pod() {
    local selector="$1"
    local namespace="$2"
    local timeout="${3:-300}"

    kubectl wait --for=condition=ready --timeout="${timeout}s" pod -l "$selector" -n "$namespace" || {
        echo "ERROR: Pod with selector $selector not ready in $namespace"
        kubectl get pods -l "$selector" -n "$namespace"
        kubectl logs -n "$namespace" -l "$selector" --tail=50 || true
        return 1
    }
}

# Wait for CRD to be established
wait_for_crd() {
    local crd="$1"
    local timeout="${2:-300}"

    kubectl wait --for condition=established --timeout="${timeout}s" "crd/$crd" || {
        echo "ERROR: CRD $crd not established"
        kubectl get crds | grep -E 'kagenti|mcp' || echo "No related CRDs found"
        return 1
    }
}

# Check if pod is ready
check_pod_ready() {
    local selector="$1"
    local namespace="$2"

    kubectl get pods -l "$selector" -n "$namespace" -o jsonpath='{.items[0].status.conditions[?(@.type=="Ready")].status}' | grep -q "True"
}

# Get pod logs with selector
get_pod_logs() {
    local selector="$1"
    local namespace="$2"
    local tail="${3:-50}"

    kubectl logs -n "$namespace" -l "$selector" --tail="$tail" --all-containers=true || true
}

# Wait for tool service to exist
# Tool services use the naming convention: {name}-mcp
wait_for_tool_service() {
    local tool_name="$1"
    local namespace="$2"
    local timeout="${3:-60}"
    local service_name="${tool_name}-mcp"

    local elapsed=0
    while [ $elapsed -lt $timeout ]; do
        if kubectl get service "$service_name" -n "$namespace" &> /dev/null; then
            return 0
        fi
        sleep 2
        elapsed=$((elapsed + 2))
    done

    echo "ERROR: Service $service_name not found in $namespace after ${timeout}s"
    return 1
}

# Start port-forward in background
port_forward_background() {
    local resource="$1"
    local namespace="$2"
    local local_port="$3"
    local remote_port="$4"
    local log_file="${5:-/tmp/port-forward.log}"

    kubectl port-forward -n "$namespace" "$resource" "${local_port}:${remote_port}" > "$log_file" 2>&1 &
    echo $!
}
