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

# Wait for the agent app to be ready inside the pod (not just pod Running)
# The pod may be Running but the Python app (uvicorn) needs time to start
log_info "Waiting for weather-service app to be ready in pod $POD_NAME..."
for i in {1..30}; do
    if kubectl exec -n team1 "$POD_NAME" -- curl -s http://localhost:8000/.well-known/agent-card.json >/dev/null 2>&1; then
        log_success "Weather-service app is ready"
        break
    fi
    if [ $i -eq 30 ]; then
        log_error "Weather-service app not ready after 30s"
        kubectl logs -n team1 "$POD_NAME" --tail=20
    fi
    sleep 1
done

log_info "Port-forwarding weather-service pod: $POD_NAME -> localhost:8000"

# Start port-forward in background
kubectl port-forward -n team1 pod/$POD_NAME 8000:8000 > /tmp/port-forward-agent.log 2>&1 &
AGENT_PORT_FORWARD_PID=$!

if [ "$IS_CI" = true ]; then
    echo "AGENT_PORT_FORWARD_PID=$AGENT_PORT_FORWARD_PID" >> $GITHUB_ENV
else
    echo $AGENT_PORT_FORWARD_PID > /tmp/port-forward-agent.pid
fi

# Wait for port-forward to be ready
for _ in {1..10}; do
    if curl -s http://localhost:8000/.well-known/agent-card.json >/dev/null 2>&1; then
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
# Port-forward Phoenix to localhost:6006
# Required for Phoenix observability E2E tests
# ============================================================================

log_info "Port-forwarding Phoenix service -> localhost:6006"

# Check if Phoenix is deployed
if kubectl get svc -n kagenti-system phoenix >/dev/null 2>&1; then
    kubectl port-forward -n kagenti-system svc/phoenix 6006:6006 > /tmp/port-forward-phoenix.log 2>&1 &
    PHOENIX_PORT_FORWARD_PID=$!

    if [ "$IS_CI" = true ]; then
        echo "PHOENIX_PORT_FORWARD_PID=$PHOENIX_PORT_FORWARD_PID" >> $GITHUB_ENV
        echo "PHOENIX_URL=http://localhost:6006" >> $GITHUB_ENV
    else
        echo $PHOENIX_PORT_FORWARD_PID > /tmp/port-forward-phoenix.pid
        export PHOENIX_URL="http://localhost:6006"
    fi

    # Wait for Phoenix port-forward to be ready
    for _ in {1..10}; do
        if curl -s http://localhost:6006/graphql >/dev/null 2>&1 || curl -s http://localhost:6006/ >/dev/null 2>&1; then
            log_success "Phoenix port-forward is ready (localhost:6006)"
            break
        fi
        sleep 1
    done
else
    log_info "Phoenix not deployed, skipping port-forward"
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
