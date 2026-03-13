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

# Auto-detect Keycloak URL on OpenShift (via route) if not already set
if [ -z "${KEYCLOAK_URL:-}" ] && [ "$IS_OPENSHIFT" = "true" ]; then
    KC_HOST=$(oc get route -n keycloak keycloak -o jsonpath='{.spec.host}' 2>/dev/null || echo "")
    if [ -n "$KC_HOST" ]; then
        export KEYCLOAK_URL="https://$KC_HOST"
        export KEYCLOAK_VERIFY_SSL="${KEYCLOAK_VERIFY_SSL:-false}"
        log_info "Auto-detected KEYCLOAK_URL: $KEYCLOAK_URL (verify_ssl=$KEYCLOAK_VERIFY_SSL)"
    fi
fi

echo "AGENT_URL: $AGENT_URL"
echo "KAGENTI_CONFIG_FILE: $KAGENTI_CONFIG_FILE"
echo "KEYCLOAK_URL: ${KEYCLOAK_URL:-not set (default: localhost:8081)}"

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
    log_error "Backend E2E tests failed"
    exit 1
}

log_success "Backend E2E tests passed"
