#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../lib/env-detect.sh"
source "$SCRIPT_DIR/../lib/logging.sh"

log_step "92" "Running UI E2E tests (Playwright)"

# Ensure Node.js >= 22 (required by mermaid/chevrotain)
MIN_NODE_MAJOR=22
if ! command -v node &>/dev/null; then
    log_error "Node.js not available — UI tests require Node.js >= v${MIN_NODE_MAJOR}"
    log_error "Install with: nvm install ${MIN_NODE_MAJOR} or brew install node@${MIN_NODE_MAJOR}"
    exit 1
fi
NODE_MAJOR=$(node --version | sed 's/v\([0-9]*\).*/\1/')
if [ "$NODE_MAJOR" -lt "$MIN_NODE_MAJOR" ]; then
    log_info "Node.js $(node --version) < v${MIN_NODE_MAJOR}, upgrading via nvm..."
    export NVM_DIR="${NVM_DIR:-$HOME/.nvm}"
    # shellcheck disable=SC1091
    [ -s "$NVM_DIR/nvm.sh" ] && . "$NVM_DIR/nvm.sh"
    if command -v nvm &>/dev/null; then
        nvm install "$MIN_NODE_MAJOR" && nvm use "$MIN_NODE_MAJOR"
    else
        log_info "nvm not available — falling back to npm ci with current Node"
    fi
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

# Auto-detect Keycloak credentials from cluster secret.
# Prefer kagenti-test-user (kagenti realm) over keycloak-initial-admin (master realm).
if [ -z "${KEYCLOAK_USER:-}" ]; then
    KC_USER=$(kubectl get secret kagenti-test-user -n keycloak -o jsonpath='{.data.username}' 2>/dev/null | base64 -d 2>/dev/null \
        || kubectl get secret keycloak-initial-admin -n keycloak -o jsonpath='{.data.username}' 2>/dev/null | base64 -d 2>/dev/null \
        || echo "admin")
    export KEYCLOAK_USER="$KC_USER"
    log_info "Keycloak user: $KC_USER"
fi
if [ -z "${KEYCLOAK_PASSWORD:-}" ]; then
    KC_PASS=$(kubectl get secret kagenti-test-user -n keycloak -o jsonpath='{.data.password}' 2>/dev/null | base64 -d 2>/dev/null \
        || kubectl get secret keycloak-initial-admin -n keycloak -o jsonpath='{.data.password}' 2>/dev/null | base64 -d 2>/dev/null \
        || echo "admin")
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

# Pass KUBECONFIG to Playwright so multi-user tests can read test-user secrets
export KUBECONFIG="${KUBECONFIG:-}"

# Export test user passwords if stored in K8s secrets
if [ -n "$KUBECONFIG" ]; then
    DEV_PASS=$(kubectl get secret kagenti-test-users -n keycloak -o jsonpath='{.data.dev-user-password}' 2>/dev/null | base64 -d 2>/dev/null || echo "")
    NS_PASS=$(kubectl get secret kagenti-test-users -n keycloak -o jsonpath='{.data.ns-admin-password}' 2>/dev/null | base64 -d 2>/dev/null || echo "")
    [ -n "$DEV_PASS" ] && export DEV_USER_PASSWORD="$DEV_PASS"
    [ -n "$NS_PASS" ] && export NS_ADMIN_PASSWORD="$NS_PASS"
fi

log_info "Running Playwright E2E tests..."
CI=true npx playwright test --reporter=list,html "${GREP_ARGS[@]}" 2>&1 || {
    log_error "Playwright UI tests failed"

    if [ -d playwright-report ]; then
        log_info "Playwright report available in kagenti/ui-v2/playwright-report/"
    fi
    exit 1
}

log_success "UI E2E tests passed"
