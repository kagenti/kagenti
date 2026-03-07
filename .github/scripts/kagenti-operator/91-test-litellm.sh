#!/usr/bin/env bash
#
# Test LiteLLM Proxy
#
# Port-forwards to the LiteLLM proxy and runs E2E tests against it.
# Designed to run as part of the CI/fulltest pipeline or standalone.
#
# What it tests:
#   - LiteLLM health endpoints (readiness, liveliness)
#   - Model listing via /v1/models
#   - Chat completions through each configured model
#   - Virtual key authentication
#   - Spend tracking (if DB is enabled)
#
# Prerequisites:
#   - LiteLLM proxy deployed (38-deploy-litellm.sh)
#   - KUBECONFIG set to target cluster
#
# Usage:
#   ./.github/scripts/kagenti-operator/91-test-litellm.sh
#
#   # Run only specific tests:
#   PYTEST_FILTER="test_health" ./.github/scripts/kagenti-operator/91-test-litellm.sh
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
source "$SCRIPT_DIR/../lib/env-detect.sh"
source "$SCRIPT_DIR/../lib/logging.sh"
source "$SCRIPT_DIR/../lib/k8s-utils.sh"

log_step "91" "Testing LiteLLM Proxy"

NAMESPACE="kagenti-system"
LITELLM_LOCAL_PORT="${LITELLM_LOCAL_PORT:-14000}"

# ============================================================================
# Step 1: Verify LiteLLM is deployed
# ============================================================================

log_info "Checking LiteLLM proxy deployment..."
if ! kubectl get deployment litellm-proxy -n "$NAMESPACE" &>/dev/null; then
    log_error "litellm-proxy deployment not found in $NAMESPACE"
    log_info "Run 38-deploy-litellm.sh first"
    exit 1
fi

READY=$(kubectl get deployment litellm-proxy -n "$NAMESPACE" \
    -o jsonpath='{.status.readyReplicas}' 2>/dev/null || echo "0")
if [ "${READY:-0}" -lt 1 ]; then
    log_error "litellm-proxy has no ready replicas (ready: ${READY:-0})"
    kubectl get pods -n "$NAMESPACE" -l app.kubernetes.io/name=litellm-proxy
    exit 1
fi
log_success "litellm-proxy deployment ready"

# ============================================================================
# Step 2: Read secrets for test configuration
# ============================================================================

log_info "Reading LiteLLM master key..."
LITELLM_MASTER_KEY=$(kubectl get secret litellm-proxy-secret -n "$NAMESPACE" \
    -o jsonpath='{.data.master-key}' | base64 -d)

if [ -z "$LITELLM_MASTER_KEY" ]; then
    log_error "Could not read master key from litellm-proxy-secret"
    exit 1
fi

# Read virtual key for team1 (if exists)
LITELLM_VIRTUAL_KEY=$(kubectl get secret litellm-virtual-keys -n team1 \
    -o jsonpath='{.data.api-key}' 2>/dev/null | base64 -d 2>/dev/null || echo "")

log_success "Secrets loaded"

# ============================================================================
# Step 3: Start port-forward
# ============================================================================

log_info "Starting port-forward to litellm-proxy on localhost:${LITELLM_LOCAL_PORT}..."

# Kill any existing port-forward on this port
lsof -ti:${LITELLM_LOCAL_PORT} 2>/dev/null | xargs kill 2>/dev/null || true
sleep 1

kubectl port-forward -n "$NAMESPACE" svc/litellm-proxy \
    "${LITELLM_LOCAL_PORT}:4000" &>/tmp/litellm-pf.log &
PF_PID=$!

# Ensure port-forward is cleaned up on exit
cleanup_pf() {
    log_info "Cleaning up port-forward (PID: $PF_PID)..."
    kill "$PF_PID" 2>/dev/null || true
    wait "$PF_PID" 2>/dev/null || true
}
trap cleanup_pf EXIT

# Wait for port-forward to be ready
log_info "Waiting for port-forward..."
for i in $(seq 1 15); do
    if curl -s -o /dev/null -w "%{http_code}" "http://localhost:${LITELLM_LOCAL_PORT}/health/readiness" 2>/dev/null | grep -q "200"; then
        break
    fi
    if ! kill -0 "$PF_PID" 2>/dev/null; then
        log_error "Port-forward process died. Check /tmp/litellm-pf.log"
        cat /tmp/litellm-pf.log
        exit 1
    fi
    sleep 2
done

# Final health check
HEALTH_CODE=$(curl -s -o /dev/null -w "%{http_code}" "http://localhost:${LITELLM_LOCAL_PORT}/health/readiness" 2>/dev/null || echo "000")
if [ "$HEALTH_CODE" != "200" ]; then
    log_error "LiteLLM not healthy after port-forward (HTTP $HEALTH_CODE)"
    cat /tmp/litellm-pf.log
    exit 1
fi
log_success "Port-forward active, LiteLLM healthy"

# ============================================================================
# Step 4: Run pytest E2E tests
# ============================================================================

log_info "Running LiteLLM E2E tests..."

cd "$REPO_ROOT/kagenti"

# Export test configuration as env vars
export LITELLM_PROXY_URL="http://localhost:${LITELLM_LOCAL_PORT}"
export LITELLM_MASTER_KEY
export LITELLM_VIRTUAL_KEY

# Ensure test dependencies
if command -v uv &>/dev/null; then
    PYTEST_CMD="uv run pytest"
else
    PYTEST_CMD="pytest"
fi

PYTEST_TARGETS="tests/e2e/kagenti_operator/test_litellm_proxy.py"
PYTEST_OPTS="-v --timeout=120 --tb=short"

if [ -n "${PYTEST_FILTER:-}" ]; then
    PYTEST_OPTS="$PYTEST_OPTS -k \"$PYTEST_FILTER\""
fi

if [ -n "${PYTEST_ARGS:-}" ]; then
    PYTEST_OPTS="$PYTEST_OPTS $PYTEST_ARGS"
fi

log_info "Running: $PYTEST_CMD $PYTEST_TARGETS $PYTEST_OPTS"
eval "$PYTEST_CMD $PYTEST_TARGETS $PYTEST_OPTS" || {
    log_error "LiteLLM E2E tests failed"
    exit 1
}

log_success "LiteLLM E2E tests passed"
