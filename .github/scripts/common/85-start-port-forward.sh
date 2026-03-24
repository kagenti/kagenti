#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../lib/env-detect.sh"
source "$SCRIPT_DIR/../lib/logging.sh"

log_step "85" "Starting port-forward"

# ============================================================================
# Port-forward weather-service (agent) to localhost:8000
# ============================================================================

# Wait for weather-service deployment to be fully ready (no pending rollouts)
log_info "Waiting for weather-service deployment rollout to complete..."
kubectl rollout status deployment/weather-service -n team1 --timeout=120s || {
    log_error "Weather-service rollout not complete after 120s"
    kubectl get pods -n team1 -l app.kubernetes.io/name=weather-service
    kubectl get events -n team1 --sort-by='.lastTimestamp' --field-selector reason!=Pulling 2>/dev/null | tail -10
    exit 1
}

# Brief settle time — allow any cascading rollouts (webhook re-injection) to trigger
sleep 5

# Re-check rollout after settle (catches cascading rollouts from webhook restart)
kubectl rollout status deployment/weather-service -n team1 --timeout=60s 2>/dev/null || true

log_info "Port-forwarding weather-service service -> localhost:8000"

# Use service-based port-forward (follows selector to current pod)
# Service port is 8080 (targetPort: 8000 on agent container)
kubectl port-forward -n team1 svc/weather-service 8000:8080 > /tmp/port-forward-agent.log 2>&1 &
AGENT_PORT_FORWARD_PID=$!

if [ "$IS_CI" = true ]; then
    echo "AGENT_PORT_FORWARD_PID=$AGENT_PORT_FORWARD_PID" >> $GITHUB_ENV
else
    echo $AGENT_PORT_FORWARD_PID > /tmp/port-forward-agent.pid
fi

# Wait for port-forward to be ready (AuthBridge sidecars need time to initialize)
AGENT_READY=false
for i in {1..30}; do
    if curl -s --max-time 2 http://localhost:8000/.well-known/agent-card.json >/dev/null 2>&1; then
        log_success "Agent port-forward is ready (localhost:8000) after ${i}s"
        AGENT_READY=true
        break
    fi
    sleep 1
done
if [ "$AGENT_READY" = false ]; then
    log_error "Agent port-forward not ready after 30s — tests may fail"
    log_info "Pod status:"
    kubectl get pods -n team1 -l app.kubernetes.io/name=weather-service --no-headers 2>/dev/null || true
fi

# ============================================================================
# Port-forward Keycloak to localhost:8081
# ============================================================================

log_info "Port-forwarding Keycloak service -> localhost:8081"

# Start Keycloak port-forward in background
kubectl port-forward -n keycloak svc/keycloak-service 8081:8080 > /tmp/port-forward-keycloak.log 2>&1 &
KEYCLOAK_PORT_FORWARD_PID=$!

if [ "$IS_CI" = true ]; then
    echo "KEYCLOAK_PORT_FORWARD_PID=$KEYCLOAK_PORT_FORWARD_PID" >> $GITHUB_ENV
    echo "KEYCLOAK_URL=http://localhost:8081" >> $GITHUB_ENV
else
    echo $KEYCLOAK_PORT_FORWARD_PID > /tmp/port-forward-keycloak.pid
    export KEYCLOAK_URL="http://localhost:8081"
fi

# Wait for Keycloak port-forward to be ready
for _ in {1..10}; do
    if curl -s http://localhost:8081/health >/dev/null 2>&1 || curl -s http://localhost:8081/ >/dev/null 2>&1; then
        log_success "Keycloak port-forward is ready (localhost:8081)"
        break
    fi
    sleep 1
done

# ============================================================================
# Port-forward kagenti-backend to localhost:8002
# Required for UI agent/tool discovery E2E tests
# ============================================================================

log_info "Port-forwarding kagenti-backend service -> localhost:8002"

# Check if backend is deployed
if kubectl get svc -n kagenti-system kagenti-backend >/dev/null 2>&1; then
    kubectl port-forward -n kagenti-system svc/kagenti-backend 8002:8000 > /tmp/port-forward-backend.log 2>&1 &
    BACKEND_PORT_FORWARD_PID=$!

    if [ "$IS_CI" = true ]; then
        echo "BACKEND_PORT_FORWARD_PID=$BACKEND_PORT_FORWARD_PID" >> $GITHUB_ENV
        echo "KAGENTI_BACKEND_URL=http://localhost:8002" >> $GITHUB_ENV
    else
        echo $BACKEND_PORT_FORWARD_PID > /tmp/port-forward-backend.pid
    fi

    # Wait for backend port-forward to be ready
    for _ in {1..10}; do
        if curl -s http://localhost:8002/health >/dev/null 2>&1 || curl -s http://localhost:8002/api/v1/ >/dev/null 2>&1; then
            log_success "Backend port-forward is ready (localhost:8002)"
            break
        fi
        sleep 1
    done
else
    log_info "kagenti-backend not deployed, skipping port-forward"
fi

# ============================================================================
# Port-forward MLflow to localhost:5000
# Required for MLflow trace validation E2E tests
# ============================================================================

log_info "Port-forwarding MLflow service -> localhost:5000"

# Check if MLflow is deployed
if kubectl get svc -n kagenti-system mlflow >/dev/null 2>&1; then
    kubectl port-forward -n kagenti-system svc/mlflow 5000:5000 > /tmp/port-forward-mlflow.log 2>&1 &
    MLFLOW_PORT_FORWARD_PID=$!

    if [ "$IS_CI" = true ]; then
        echo "MLFLOW_PORT_FORWARD_PID=$MLFLOW_PORT_FORWARD_PID" >> $GITHUB_ENV
        echo "MLFLOW_URL=http://localhost:5000" >> $GITHUB_ENV
    else
        echo $MLFLOW_PORT_FORWARD_PID > /tmp/port-forward-mlflow.pid
        export MLFLOW_URL="http://localhost:5000"
    fi

    # Wait for MLflow port-forward to be ready
    for _ in {1..10}; do
        if curl -s http://localhost:5000/health >/dev/null 2>&1 || curl -s http://localhost:5000/version >/dev/null 2>&1; then
            log_success "MLflow port-forward is ready (localhost:5000)"
            break
        fi
        sleep 1
    done
else
    log_info "MLflow not deployed, skipping port-forward"
fi

log_success "All port-forwards started"
