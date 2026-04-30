#!/usr/bin/env bash
# Backend E2E tests only (pytest).
#
# Pre-flight checks (OTEL/MLflow readiness) are now in:
#   .github/scripts/common/90-preflight-checks.sh
#
# UI E2E tests (Playwright) are now in:
#   .github/scripts/common/92-run-ui-tests.sh
#
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../lib/env-detect.sh"
source "$SCRIPT_DIR/../lib/logging.sh"

log_step "90" "Running backend E2E tests (Kagenti Operator)"

cd "$REPO_ROOT/kagenti"

# Use environment variables if set, otherwise default
export AGENT_URL="${AGENT_URL:-http://localhost:8000}"
export KAGENTI_CONFIG_FILE="${KAGENTI_CONFIG_FILE:-deployments/envs/dev_values.yaml}"

echo "AGENT_URL: $AGENT_URL"
echo "KAGENTI_CONFIG_FILE: $KAGENTI_CONFIG_FILE"

mkdir -p "$REPO_ROOT/test-results"

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
PYTEST_OPTS="-v --timeout=300 --tb=short"

if [ -n "${PYTEST_FILTER:-}" ]; then
    PYTEST_OPTS="$PYTEST_OPTS -k \"$PYTEST_FILTER\""
    echo "Filtering tests with: -k \"$PYTEST_FILTER\""
fi

if [ -n "${PYTEST_ARGS:-}" ]; then
    PYTEST_OPTS="$PYTEST_OPTS $PYTEST_ARGS"
    echo "Additional pytest args: $PYTEST_ARGS"
fi

# Phase 1: Run all tests EXCEPT observability (generates traffic)
# This runs standard E2E tests that exercise the platform and generate traffic patterns
log_info "Phase 1: Running E2E tests (excluding observability)"
echo "Running: $PYTEST_CMD $PYTEST_TARGETS $PYTEST_OPTS -m \"not observability\" --junit-xml=../test-results/e2e-results.xml"
eval "$PYTEST_CMD $PYTEST_TARGETS $PYTEST_OPTS -m \"not observability\" --junit-xml=../test-results/e2e-results.xml" || {
    log_error "Backend E2E tests (phase 1) failed"
    exit 1
}

# Phase 2: Run ONLY observability tests (validates traffic patterns from phase 1)
# Skip if no observability components are deployed (Phoenix, MLflow, Kiali)
OBSERVABILITY_PODS=$(kubectl get pods -n kagenti-system -l "app in (phoenix,mlflow,kiali)" --no-headers 2>/dev/null | grep -c "Running" || echo "0")
if [ "$OBSERVABILITY_PODS" -gt 0 ]; then
    log_info "Phase 2: Running observability tests ($OBSERVABILITY_PODS observability pods found)"
    eval "$PYTEST_CMD $PYTEST_TARGETS $PYTEST_OPTS -m \"observability\" --junit-xml=../test-results/e2e-observability-results.xml" || {
        log_error "Observability tests (phase 2) failed"
        exit 1
    }
else
    log_info "Phase 2: Skipping observability tests (no Phoenix/MLflow/Kiali pods running)"
fi

log_success "Backend E2E tests passed (both phases)"
