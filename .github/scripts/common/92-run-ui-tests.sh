#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../lib/env-detect.sh"
source "$SCRIPT_DIR/../lib/logging.sh"

log_step "92" "Running UI E2E tests (Playwright)"

# Check Node.js is available
if ! command -v node &>/dev/null; then
    log_info "Node.js not available, skipping UI tests"
    exit 0
fi
log_info "Using Node.js $(node --version)"

cd "$REPO_ROOT/kagenti/ui-v2"

# Install npm dependencies
log_info "Installing npm dependencies..."
npm ci

# Install Playwright browsers (chromium only for CI)
log_info "Installing Playwright browsers..."
npx playwright install --with-deps chromium

# Auto-detect UI URL based on environment
if [ -z "${KAGENTI_UI_URL:-}" ]; then
    if [ "$IS_OPENSHIFT" = "true" ]; then
        # OpenShift/HyperShift: use the route
        KAGENTI_UI_URL="https://$(oc get route kagenti-ui -n kagenti-system -o jsonpath='{.spec.host}' 2>/dev/null)"
        log_info "Detected OpenShift UI URL: $KAGENTI_UI_URL"
    else
        # Kind: build URL from DOMAIN_NAME configmap (not hardcoded)
        DOMAIN=$(kubectl get configmap kagenti-ui-config -n kagenti-system -o jsonpath='{.data.DOMAIN_NAME}' 2>/dev/null || echo "localtest.me")
        KAGENTI_UI_URL="http://kagenti-ui.${DOMAIN}:8080"
        log_info "Detected Kind UI URL: $KAGENTI_UI_URL"
    fi
fi
export KAGENTI_UI_URL

# Auto-detect Keycloak credentials from cluster secret
if [ -z "${KEYCLOAK_USER:-}" ]; then
    KC_USER=$(kubectl get secret keycloak-initial-admin -n keycloak -o jsonpath='{.data.username}' 2>/dev/null | base64 -d 2>/dev/null || echo "admin")
    export KEYCLOAK_USER="$KC_USER"
    log_info "Keycloak user: $KC_USER"
fi
if [ -z "${KEYCLOAK_PASSWORD:-}" ]; then
    # Try demo realm test user password first (kagenti-test-users secret)
    # then fall back to master realm admin (keycloak-initial-admin secret)
    KC_PASS=$(kubectl get secret kagenti-test-users -n keycloak -o jsonpath='{.data.admin-password}' 2>/dev/null | base64 -d 2>/dev/null || \
              kubectl get secret keycloak-initial-admin -n keycloak -o jsonpath='{.data.password}' 2>/dev/null | base64 -d 2>/dev/null || echo "admin")
    export KEYCLOAK_PASSWORD="$KC_PASS"
    log_info "Keycloak password: ${KC_PASS:0:4}..."
fi

# Tag-based test filtering:
#   PLAYWRIGHT_GREP       — only run tests matching this tag (e.g. "@extended")
#   PLAYWRIGHT_GREP_INVERT — exclude tests matching this tag (e.g. "@extended")
# Set these in the workflow env to control which tests run per environment.
# Default: exclude @extended tests (they require specific mock/state setup
# that doesn't work reliably against a live cluster).
PLAYWRIGHT_GREP_INVERT="${PLAYWRIGHT_GREP_INVERT:-@extended}"
GREP_ARGS=()
if [ -n "${PLAYWRIGHT_GREP:-}" ]; then
    GREP_ARGS+=(--grep "$PLAYWRIGHT_GREP")
    log_info "Playwright tag filter: --grep '$PLAYWRIGHT_GREP'"
fi
if [ -n "${PLAYWRIGHT_GREP_INVERT:-}" ]; then
    GREP_ARGS+=(--grep-invert "$PLAYWRIGHT_GREP_INVERT")
    log_info "Playwright tag filter: --grep-invert '$PLAYWRIGHT_GREP_INVERT'"
fi

# Determine which test suites to run.
# Start with agent-chat (always present). Add sandbox tests if the sandbox
# spec exists (only in the sandbox-agent branch).
TEST_SPECS="agent-chat"
if [ -f "e2e/sandbox.spec.ts" ]; then
    TEST_SPECS="$TEST_SPECS sandbox"
    log_info "Sandbox tests detected — including sandbox.spec.ts"
fi
if [ -f "e2e/sandbox-sidecars.spec.ts" ]; then
    TEST_SPECS="$TEST_SPECS sandbox-sidecars"
    log_info "Sidecar tests detected — including sandbox-sidecars.spec.ts"
fi

# Run Playwright tests
log_info "Running Playwright E2E tests: $TEST_SPECS"
CI=true npx playwright test $TEST_SPECS --reporter=list,html "${GREP_ARGS[@]}" 2>&1 || {
    log_error "Playwright UI tests failed"

    if [ -d playwright-report ]; then
        log_info "Playwright report available in kagenti/ui-v2/playwright-report/"
    fi
    exit 1
}

log_success "UI E2E tests passed"
