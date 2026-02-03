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

echo "AGENT_URL: $AGENT_URL"
echo "KAGENTI_CONFIG_FILE: $KAGENTI_CONFIG_FILE"

mkdir -p "$REPO_ROOT/test-results"

# Support filtering tests via PYTEST_FILTER or PYTEST_ARGS
# PYTEST_FILTER: pytest -k filter expression (e.g., "test_mlflow" or "TestGenAI")
# PYTEST_ARGS: additional pytest arguments (e.g., "-x" for stop on first failure)
# Use uv run to ensure we use the project's virtual environment
PYTEST_CMD="uv run pytest"
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
