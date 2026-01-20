#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../lib/env-detect.sh"
source "$SCRIPT_DIR/../lib/logging.sh"

log_step "90" "Running E2E tests (Kagenti Operator)"

cd "$REPO_ROOT/kagenti"

# Use environment variables if set, otherwise default
export AGENT_URL="${AGENT_URL:-http://localhost:8000}"
export KAGENTI_CONFIG_FILE="${KAGENTI_CONFIG_FILE:-deployments/envs/dev_kagenti_operator_values.yaml}"

echo "AGENT_URL: $AGENT_URL"
echo "KAGENTI_CONFIG_FILE: $KAGENTI_CONFIG_FILE"

mkdir -p "$REPO_ROOT/test-results"

pytest tests/e2e/common tests/e2e/kagenti_operator -v \
    --timeout=300 \
    --tb=short \
    --junit-xml=../test-results/e2e-results.xml || {
    log_error "E2E tests failed"
    exit 1
}

log_success "E2E tests passed"
