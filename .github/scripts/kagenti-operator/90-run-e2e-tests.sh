#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../lib/env-detect.sh"
source "$SCRIPT_DIR/../lib/logging.sh"

log_step "90" "Running E2E tests (Kagenti Operator)"

cd "$REPO_ROOT/kagenti"

# Use environment variables if set, otherwise default
export AGENT_URL="${AGENT_URL:-http://localhost:8000}"
export KAGENTI_CONFIG_FILE="${KAGENTI_CONFIG_FILE:-deployments/envs/dev_values.yaml}"
export PHOENIX_URL="${PHOENIX_URL:-http://localhost:6006}"
export KEYCLOAK_URL="${KEYCLOAK_URL:-http://localhost:8081}"

echo "AGENT_URL: $AGENT_URL"
echo "KAGENTI_CONFIG_FILE: $KAGENTI_CONFIG_FILE"
echo "PHOENIX_URL: $PHOENIX_URL"
echo "KEYCLOAK_URL: $KEYCLOAK_URL"

mkdir -p "$REPO_ROOT/test-results"

# ============================================================================
# Pre-test: Wait for OTEL → MLflow pipeline to be ready
# The pipeline needs time after deployment: MLflow DB init (~100s),
# OTEL collector retry/queue, first trace export.
#
# ============================================================================
if kubectl get deployment mlflow -n kagenti-system &>/dev/null; then
    log_info "Waiting for OTEL → MLflow pipeline to be ready..."

    MAX_WAIT=15  # 15 iterations × 10s = 150s
    PIPELINE_READY=false
    OTEL_RESTARTS=0

    for i in $(seq 1 $MAX_WAIT); do
        ISSUES=""

        # Check MLflow pod
        MLFLOW_READY=$(kubectl get deployment mlflow -n kagenti-system -o jsonpath='{.status.readyReplicas}' 2>/dev/null || echo "0")
        if [ "${MLFLOW_READY:-0}" = "0" ]; then
            MLFLOW_PHASE=$(kubectl get pods -n kagenti-system -l app=mlflow -o jsonpath='{.items[0].status.phase}' 2>/dev/null || echo "unknown")
            ISSUES="$ISSUES\n  MLflow: pod not ready (phase: $MLFLOW_PHASE)"
        fi

        # Check OTEL collector pod
        OTEL_READY=$(kubectl get deployment otel-collector -n kagenti-system -o jsonpath='{.status.readyReplicas}' 2>/dev/null || echo "0")
        if [ "${OTEL_READY:-0}" = "0" ]; then
            ISSUES="$ISSUES\n  OTEL collector: pod not ready"
        fi

        # Check MLflow DB init (experiment + user exist)
        DB_EXP=$(kubectl exec -n kagenti-system postgres-otel-0 -- \
            psql -U testuser -d mlflow -t -A -c \
            "SELECT COUNT(*) FROM experiments WHERE experiment_id = 0;" 2>/dev/null | tr -d '[:space:]' || echo "0")
        DB_USER=$(kubectl exec -n kagenti-system postgres-otel-0 -- \
            psql -U testuser -d mlflow -t -A -c \
            "SELECT COUNT(*) FROM users WHERE username = 'service-account-mlflow';" 2>/dev/null | tr -d '[:space:]' || echo "0")
        if [ "$DB_EXP" != "1" ] || [ "$DB_USER" != "1" ]; then
            ISSUES="$ISSUES\n  MLflow DB: experiment=$DB_EXP user=$DB_USER (need both = 1)"
        fi

        # Check OTEL collector for export errors — restart if dropping (max 2 restarts)
        OTEL_DROPS=$(kubectl logs -n kagenti-system deployment/otel-collector --tail=30 2>/dev/null | grep -c "Dropping data" 2>/dev/null || echo "0")
        OTEL_DROPS=$(echo "$OTEL_DROPS" | tr -d '[:space:]')
        if [ "$OTEL_DROPS" -gt 0 ]; then
            if [ "$OTEL_RESTARTS" -lt 2 ]; then
                OTEL_RESTARTS=$((OTEL_RESTARTS + 1))
                log_info "OTEL collector dropping traces — restarting ($OTEL_RESTARTS/2)..."
                kubectl rollout restart deployment/otel-collector -n kagenti-system 2>/dev/null || true
                sleep 5
                kubectl wait --for=condition=available --timeout=30s deployment/otel-collector -n kagenti-system 2>/dev/null || true
                ISSUES="$ISSUES\n  OTEL collector: restarted to clear error state"
            else
                ISSUES="$ISSUES\n  OTEL collector: still dropping after 2 restarts"
            fi
        fi

        # All healthy?
        if [ -z "$ISSUES" ]; then
            log_success "OTEL → MLflow pipeline ready (${i}0s)"
            PIPELINE_READY=true
            break
        fi

        echo -e "  [$i/$MAX_WAIT] Pipeline not ready (${i}0s):$ISSUES"
        sleep 10
    done

    if [ "$PIPELINE_READY" != "true" ]; then
        log_error "OTEL → MLflow pipeline not ready after 150s"
        echo "Diagnostics:"
        echo "  MLflow pods:"
        kubectl get pods -n kagenti-system -l app=mlflow 2>/dev/null || true
        echo "  MLflow init logs:"
        kubectl logs -n kagenti-system deployment/mlflow -c mlflow --tail=15 2>/dev/null | grep -iE "init|error|Warning|Created|attempt" || true
        echo "  OTEL collector errors:"
        kubectl logs -n kagenti-system deployment/otel-collector --tail=10 2>/dev/null | grep -iE "error|drop|fail" || true
        # Don't exit — let tests run and fail with specific errors
        log_info "Proceeding with tests despite pipeline issues..."
    fi
else
    log_info "MLflow not deployed, skipping pipeline readiness check"
fi

# Ensure test dependencies are installed
if command -v uv &>/dev/null; then
    # Check if test extras are installed by trying to import a test-only dependency
    if ! uv run python -c "import mlflow" &>/dev/null; then
        log_info "Test dependencies not installed. Running: uv sync --extra test"
        (cd "$REPO_ROOT" && uv sync --extra test)
    fi
    PYTEST_CMD="uv run pytest"
else
    if ! python -c "import mlflow" &>/dev/null; then
        log_error "Test dependencies missing. Run: uv sync --extra test"
        exit 1
    fi
    PYTEST_CMD="pytest"
fi

# Support filtering tests via PYTEST_FILTER or PYTEST_ARGS
# PYTEST_FILTER: pytest -k filter expression (e.g., "test_mlflow" or "TestGenAI")
# PYTEST_ARGS: additional pytest arguments (e.g., "-x" for stop on first failure)
PYTEST_TARGETS="${PYTEST_TARGETS:-tests/e2e/common tests/e2e/kagenti_operator}"
PYTEST_OPTS="-v --timeout=300 --tb=short --junit-xml=../test-results/e2e-results.xml"

if [ -n "${PYTEST_FILTER:-}" ]; then
    PYTEST_OPTS="$PYTEST_OPTS -k \"$PYTEST_FILTER\""
    echo "Filtering tests with: -k \"$PYTEST_FILTER\""
fi

if [ -n "${PYTEST_ARGS:-}" ]; then
    PYTEST_OPTS="$PYTEST_OPTS $PYTEST_ARGS"
    echo "Additional pytest args: $PYTEST_ARGS"
fi

echo "Running: $PYTEST_CMD $PYTEST_TARGETS $PYTEST_OPTS"
eval "$PYTEST_CMD $PYTEST_TARGETS $PYTEST_OPTS" || {
    log_error "E2E tests failed"
    exit 1
}

log_success "E2E tests passed"

# ============================================================================
# Run Playwright UI E2E tests
# ============================================================================
UI_TEST_SCRIPT="$SCRIPT_DIR/../common/91-run-ui-tests.sh"
if [ -f "$UI_TEST_SCRIPT" ]; then
    log_step "91" "Running UI E2E tests (Playwright)"
    bash "$UI_TEST_SCRIPT" || {
        log_error "UI E2E tests failed"
        exit 1
    }
else
    log_info "UI test script not found, skipping Playwright tests"
fi
