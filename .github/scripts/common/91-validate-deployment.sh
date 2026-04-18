#!/usr/bin/env bash
# Post-deploy validation — verifies platform is ready before running tests.
#
# Checks:
#   1. LiteLLM virtual key format (sk- prefix)
#   2. Sandbox agent pods (if sandbox feature flag enabled)
#   3. UI route reachable (HTTP 200)
#   4. Keycloak healthy
#
# Usage:
#   ./.github/scripts/common/91-validate-deployment.sh
#
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../lib/env-detect.sh"
source "$SCRIPT_DIR/../lib/logging.sh"

log_step "91" "Validating deployment before tests"

FAILURES=0

# --- Check 1: LiteLLM virtual key format ---
log_info "Checking LiteLLM virtual key..."
VKEY=$(kubectl get secret litellm-virtual-keys -n team1 \
    -o jsonpath='{.data.api-key}' 2>/dev/null | base64 -d 2>/dev/null || echo "")
if [ -z "$VKEY" ]; then
    log_warn "LiteLLM virtual key secret not found in team1 (agent conversation tests will fail)"
    FAILURES=$((FAILURES + 1))
elif [[ "$VKEY" != sk-* ]]; then
    log_error "LiteLLM virtual key has wrong format: '${VKEY:0:10}...' (expected sk-* prefix)"
    FAILURES=$((FAILURES + 1))
else
    log_success "LiteLLM virtual key OK (prefix: ${VKEY:0:6}...)"
fi

# --- Check 2: LiteLLM proxy pod ---
log_info "Checking LiteLLM proxy..."
LITELLM_STATUS=$(kubectl get pods -n kagenti-system -l app=litellm-proxy \
    --no-headers -o custom-columns=':status.phase' 2>/dev/null | head -1)
if [ "$LITELLM_STATUS" = "Running" ]; then
    log_success "LiteLLM proxy pod is Running"
else
    log_warn "LiteLLM proxy pod status: ${LITELLM_STATUS:-not found} (agent conversation tests may fail)"
    FAILURES=$((FAILURES + 1))
fi

# --- Check 3: Sandbox agent pods (if feature flag enabled) ---
SANDBOX_ENABLED="${ENABLE_SANDBOX_TESTS:-false}"
if [ -f "${KAGENTI_CONFIG_FILE:-}" ]; then
    SANDBOX_ENABLED=$(python3 -c "
import yaml
with open('${KAGENTI_CONFIG_FILE}') as f:
    c = yaml.safe_load(f)
ff = c.get('charts',{}).get('kagenti',{}).get('values',{}).get('featureFlags',{})
print('true' if ff.get('sandbox') else 'false')
" 2>/dev/null || echo "$SANDBOX_ENABLED")
fi

if [ "$SANDBOX_ENABLED" = "true" ]; then
    log_info "Checking sandbox agent pods..."
    SANDBOX_PODS=$(kubectl get pods -n team1 -l app=sandbox-legion \
        --no-headers 2>/dev/null | wc -l | tr -d ' ')
    if [ "$SANDBOX_PODS" -gt 0 ]; then
        log_success "Sandbox agent pods found ($SANDBOX_PODS)"
    else
        log_warn "No sandbox agent pods in team1 (sandbox tests will fail)"
        FAILURES=$((FAILURES + 1))
    fi
fi

# --- Check 4: UI route reachable ---
log_info "Checking UI route..."
if [ "$IS_OPENSHIFT" = "true" ]; then
    UI_HOST=$(kubectl get route kagenti-ui -n kagenti-system \
        -o jsonpath='{.spec.host}' 2>/dev/null || echo "")
    if [ -n "$UI_HOST" ]; then
        HTTP_CODE=$(curl -sk -o /dev/null -w '%{http_code}' "https://$UI_HOST" 2>/dev/null || echo "000")
        if [ "$HTTP_CODE" = "200" ] || [ "$HTTP_CODE" = "302" ]; then
            log_success "UI route reachable (HTTP $HTTP_CODE)"
        else
            log_warn "UI route returned HTTP $HTTP_CODE"
            FAILURES=$((FAILURES + 1))
        fi
    else
        log_warn "UI route not found"
        FAILURES=$((FAILURES + 1))
    fi
else
    log_info "Skipping UI route check (non-OpenShift)"
fi

# --- Check 5: Keycloak healthy ---
log_info "Checking Keycloak..."
KC_STATUS=$(kubectl get pods -n keycloak -l app=keycloak \
    --no-headers -o custom-columns=':status.phase' 2>/dev/null | head -1)
if [ "$KC_STATUS" = "Running" ]; then
    log_success "Keycloak is Running"
else
    log_warn "Keycloak status: ${KC_STATUS:-not found}"
    FAILURES=$((FAILURES + 1))
fi

# --- Summary ---
if [ "$FAILURES" -gt 0 ]; then
    log_warn "Deployment validation completed with $FAILURES warning(s)"
    log_warn "Tests will run but some may fail due to the above issues"
else
    log_success "All deployment validation checks passed"
fi

# Always exit 0 — validation is advisory, not blocking
exit 0
