#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../lib/env-detect.sh"
source "$SCRIPT_DIR/../lib/logging.sh"

log_step "85" "Starting port-forward"

# ============================================================================
# Port-forward weather-service (agent) to localhost:8000
# ============================================================================

# Get pod name
POD_NAME=$(kubectl get pod -n team1 -l app.kubernetes.io/name=weather-service -o jsonpath='{.items[0].metadata.name}')

if [ -z "$POD_NAME" ]; then
    log_error "No weather-service pod found"
    kubectl get pods -n team1
    exit 1
fi

log_info "Port-forwarding weather-service pod: $POD_NAME -> localhost:8000"

# Start port-forward in background
kubectl port-forward -n team1 pod/$POD_NAME 8000:8000 > /tmp/port-forward-agent.log 2>&1 &
AGENT_PORT_FORWARD_PID=$!

if [ "$IS_CI" = true ]; then
    echo "AGENT_PORT_FORWARD_PID=$AGENT_PORT_FORWARD_PID" >> $GITHUB_ENV
else
    echo $AGENT_PORT_FORWARD_PID > /tmp/port-forward-agent.pid
fi

# Wait for agent port-forward to be ready
for _ in {1..10}; do
    if curl -s http://localhost:8000/health >/dev/null 2>&1 || curl -s http://localhost:8000/ >/dev/null 2>&1; then
        log_success "Agent port-forward is ready (localhost:8000)"
        break
    fi
    sleep 1
done

# ============================================================================
# Port-forward Keycloak to localhost:8081
# ============================================================================

log_info "Port-forwarding Keycloak service -> localhost:8081"

# Start Keycloak port-forward in background
kubectl port-forward -n keycloak svc/keycloak-service 8081:8080 > /tmp/port-forward-keycloak.log 2>&1 &
KEYCLOAK_PORT_FORWARD_PID=$!

if [ "$IS_CI" = true ]; then
    echo "KEYCLOAK_PORT_FORWARD_PID=$KEYCLOAK_PORT_FORWARD_PID" >> $GITHUB_ENV
else
    echo $KEYCLOAK_PORT_FORWARD_PID > /tmp/port-forward-keycloak.pid
fi

# Wait for Keycloak port-forward to be ready
for _ in {1..10}; do
    if curl -s http://localhost:8081/health >/dev/null 2>&1 || curl -s http://localhost:8081/ >/dev/null 2>&1; then
        log_success "Keycloak port-forward is ready (localhost:8081)"
        break
    fi
    sleep 1
done

log_success "All port-forwards started"
