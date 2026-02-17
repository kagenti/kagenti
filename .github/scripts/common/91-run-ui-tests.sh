#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../lib/env-detect.sh"
source "$SCRIPT_DIR/../lib/logging.sh"

log_step "91" "Running UI E2E tests (Playwright)"

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
    KC_PASS=$(kubectl get secret keycloak-initial-admin -n keycloak -o jsonpath='{.data.password}' 2>/dev/null | base64 -d 2>/dev/null || echo "admin")
    export KEYCLOAK_PASSWORD="$KC_PASS"
    log_info "Keycloak password: ${KC_PASS:0:4}..."
fi

# Run all Playwright E2E tests (all specs handle Keycloak login)
log_info "Running Playwright E2E tests..."
CI=true npx playwright test --reporter=list,html 2>&1 || {
    log_error "Playwright UI tests failed"

    if [ -d playwright-report ]; then
        log_info "Playwright report available in kagenti/ui-v2/playwright-report/"
    fi
    exit 1
}

log_success "UI E2E tests passed"
