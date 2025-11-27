#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../lib/env-detect.sh"
source "$SCRIPT_DIR/../lib/logging.sh"

log_step "90" "Running E2E tests (Platform Operator)"

cd "$REPO_ROOT/kagenti"

export AGENT_URL=http://localhost:8000
export KAGENTI_CONFIG_FILE=deployments/envs/dev_values.yaml

mkdir -p "$REPO_ROOT/test-results"

pytest tests/e2e/common tests/e2e/platform_operator -v \
    --timeout=300 \
    --tb=short \
    --junit-xml=../test-results/e2e-results.xml || {
    log_error "E2E tests failed"
    exit 1
}

log_success "E2E tests passed"
