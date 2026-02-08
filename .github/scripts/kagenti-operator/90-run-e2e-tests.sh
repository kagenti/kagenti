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

# Phase 1: Run all tests EXCEPT observability (generates traffic)
# This runs standard E2E tests that exercise the platform and generate traffic patterns
log_step "90" "Phase 1: Running E2E tests (excluding observability)"
pytest tests/e2e/ -v \
    -m "not observability" \
    --timeout=300 \
    --tb=short \
    --junit-xml=../test-results/e2e-results.xml || {
    log_error "E2E tests (phase 1) failed"
    exit 1
}

# Phase 2: Run ONLY observability tests (validates traffic patterns from phase 1)
# These tests check Kiali for Istio config issues, traffic errors, and mTLS compliance
log_step "90" "Phase 2: Running observability tests (Kiali validation)"
pytest tests/e2e/ -v \
    -m "observability" \
    --timeout=300 \
    --tb=short \
    --junit-xml=../test-results/e2e-observability-results.xml || {
    log_error "Observability tests (phase 2) failed"
    exit 1
}

log_success "E2E tests passed (both phases)"
