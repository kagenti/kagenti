#!/usr/bin/env bash
# Run token exchange E2E tests (pytest).
#
# Environment:
#   TX_NAMESPACE       Test namespace (default: tx-e2e)
#   TX_REALM           Keycloak realm (default: tx-e2e)
#   TX_CLIENT_ID       Keycloak client (default: tx-e2e-app)
#   KEYCLOAK_PROVIDER  "community" or "rhbk" — controls test fatality
#   KEYCLOAK_URL       Keycloak base URL (auto-detected)
set -euo pipefail
source "$(dirname "$0")/lib.sh"

log_step "80" "Run token exchange E2E tests"

PLATFORM="${PLATFORM:-$(detect_platform)}"
KEYCLOAK_PROVIDER="${KEYCLOAK_PROVIDER:-community}"

# Export environment for pytest
export TX_NAMESPACE
export TX_REALM
export TX_CLIENT_ID
export KEYCLOAK_PROVIDER
export KEYCLOAK_URL="${KEYCLOAK_URL:-$(get_keycloak_url)}"

# Determine Keycloak host for port-forward on Kind
if [[ "$PLATFORM" == "kind" ]]; then
  # Start port-forward if keycloak is not externally accessible
  KC_PF_PID=""
  if ! curl -sk "$KEYCLOAK_URL/realms/master" -o /dev/null 2>/dev/null; then
    log_info "Starting Keycloak port-forward..."
    kubectl port-forward svc/keycloak-service -n "$KC_NAMESPACE" 8081:8080 &>/dev/null &
    KC_PF_PID=$!
    export KEYCLOAK_URL="http://localhost:8081"
    sleep 3
  fi

  # Start agent port-forward
  log_info "Starting agent port-forward..."
  kubectl port-forward svc/tx-e2e-agent -n "$TX_NAMESPACE" 8082:8080 &>/dev/null &
  AGENT_PF_PID=$!
  export TX_AGENT_URL="http://localhost:8082"
  sleep 2

  cleanup_pf() {
    kill "$KC_PF_PID" 2>/dev/null || true
    kill "$AGENT_PF_PID" 2>/dev/null || true
  }
  trap cleanup_pf EXIT
fi

# Test dependencies (pytest, requests, pyjwt, kubernetes) are installed by
# the CI workflow before this script runs. See e2e-kind.yaml / e2e-hypershift.yaml.

# Determine test strictness based on provider
TEST_DIR="$REPO_ROOT/rossoctl/tests/e2e/token_exchange"
PYTEST_ARGS=(-v --tb=short --junitxml="$REPO_ROOT/test-results/token-exchange-${KEYCLOAK_PROVIDER}.xml")

if [[ "$KEYCLOAK_PROVIDER" == "rhbk" ]]; then
  log_info "Running tests against RHBK (non-fatal)"
  # --no-header to reduce noise; failures are warnings not errors
  uv run pytest "$TEST_DIR" "${PYTEST_ARGS[@]}" || {
    RC=$?
    log_warn "RHBK tests failed (exit code $RC) — non-fatal as per policy"
    exit 0  # Non-fatal
  }
else
  log_info "Running tests against community Keycloak (fatal)"
  uv run pytest "$TEST_DIR" "${PYTEST_ARGS[@]}"
fi

log_success "Token exchange E2E tests passed ($KEYCLOAK_PROVIDER)"
