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

# Use environment variables if set, otherwise auto-detect
if [ -z "${AGENT_URL:-}" ]; then
    # Try OpenShift route first
    ROUTE_URL=$(kubectl get route weather-service -n team1 -o jsonpath='{.spec.host}' 2>/dev/null || true)
    if [ -n "$ROUTE_URL" ]; then
        export AGENT_URL="https://$ROUTE_URL"
    else
        export AGENT_URL="http://localhost:8000"
    fi
fi

# Auto-detect OpenShift/HyperShift clusters
if [ -z "${IS_OPENSHIFT:-}" ]; then
    # Method 1: check route.openshift.io API (may fail with pipefail on some shells)
    if kubectl api-resources --api-group=route.openshift.io 2>/dev/null | grep routes > /dev/null 2>&1; then
        export IS_OPENSHIFT=true
        log_info "Auto-detected OpenShift cluster (route.openshift.io API present)"
    # Method 2: check if oc command exists and can get routes
    elif oc get routes -A --no-headers 2>/dev/null | head -1 > /dev/null 2>&1; then
        export IS_OPENSHIFT=true
        log_info "Auto-detected OpenShift cluster (oc get routes works)"
    # Method 3: check KAGENTI_CONFIG_FILE for ocp
    elif [[ "${KAGENTI_CONFIG_FILE:-}" == *"ocp"* ]]; then
        export IS_OPENSHIFT=true
        log_info "Auto-detected OpenShift from KAGENTI_CONFIG_FILE=${KAGENTI_CONFIG_FILE}"
    else
        export IS_OPENSHIFT=false
    fi
fi

# Auto-detect config file: ocp for OpenShift/HyperShift, dev for Kind
if [ -z "${KAGENTI_CONFIG_FILE:-}" ]; then
    if [ "${IS_OPENSHIFT:-false}" = "true" ]; then
        export KAGENTI_CONFIG_FILE="deployments/envs/ocp_values.yaml"
    else
        export KAGENTI_CONFIG_FILE="deployments/envs/dev_values.yaml"
    fi
fi

# Enable sandbox tests if sandbox feature flag is set in config
if [ -z "${ENABLE_SANDBOX_TESTS:-}" ] && [ -f "$REPO_ROOT/$KAGENTI_CONFIG_FILE" ]; then
    # Use grep to check for sandbox: true in featureFlags section (no pyyaml dependency)
    if grep -A5 'featureFlags:' "$REPO_ROOT/$KAGENTI_CONFIG_FILE" 2>/dev/null | grep -q 'sandbox: true'; then
        export ENABLE_SANDBOX_TESTS=true
        log_info "Auto-enabled sandbox tests from config featureFlags"
    fi
fi

# Fallback: detect sandbox from actual cluster state (deployment exists)
if [ -z "${ENABLE_SANDBOX_TESTS:-}" ]; then
    if kubectl get deployment sandbox-legion -n team1 &>/dev/null; then
        export ENABLE_SANDBOX_TESTS=true
        log_info "Auto-enabled sandbox tests (sandbox-legion deployment found in team1)"
    fi
fi

# Auto-detect sandbox-legion URL for tests (route on OpenShift, in-cluster DNS on Kind)
if [ -z "${SANDBOX_LEGION_URL:-}" ] && [ "${ENABLE_SANDBOX_TESTS:-}" = "true" ]; then
    if [ "${IS_OPENSHIFT:-false}" = "true" ]; then
        SL_HOST=$(kubectl get route sandbox-legion -n team1 -o jsonpath='{.spec.host}' 2>/dev/null || echo "")
        if [ -n "$SL_HOST" ]; then
            export SANDBOX_LEGION_URL="https://$SL_HOST"
            log_info "Auto-detected sandbox-legion URL: $SANDBOX_LEGION_URL"
        fi
    else
        export SANDBOX_LEGION_URL="http://sandbox-legion.team1.svc.cluster.local:8000"
        log_info "Using Kind sandbox-legion URL: $SANDBOX_LEGION_URL"
    fi
fi

# Auto-detect Keycloak URL for tests
if [ -z "${KEYCLOAK_URL:-}" ]; then
    if [ "${IS_OPENSHIFT:-false}" = "true" ]; then
        KC_HOST=$(kubectl get route keycloak -n keycloak -o jsonpath='{.spec.host}' 2>/dev/null || echo "")
        if [ -n "$KC_HOST" ]; then
            export KEYCLOAK_URL="https://$KC_HOST"
            log_info "Auto-detected Keycloak URL: $KEYCLOAK_URL"
        fi
    else
        DOMAIN=$(kubectl get configmap kagenti-ui-config -n kagenti-system -o jsonpath='{.data.DOMAIN_NAME}' 2>/dev/null || echo "localtest.me")
        export KEYCLOAK_URL="http://keycloak.${DOMAIN}:8080"
        log_info "Using Kind Keycloak URL: $KEYCLOAK_URL"
    fi
fi

# Auto-detect sandbox variant URLs (hardened, basic, restricted)
if [ "${ENABLE_SANDBOX_TESTS:-}" = "true" ]; then
    for variant in hardened basic restricted; do
        VAR_UPPER=$(echo "$variant" | tr '[:lower:]' '[:upper:]')
        VAR_NAME="SANDBOX_${VAR_UPPER}_URL"
        if [ -z "${!VAR_NAME:-}" ]; then
            if [ "${IS_OPENSHIFT:-false}" = "true" ]; then
                VAR_HOST=$(kubectl get route "sandbox-${variant}" -n team1 -o jsonpath='{.spec.host}' 2>/dev/null || echo "")
                if [ -n "$VAR_HOST" ]; then
                    export "${VAR_NAME}=https://${VAR_HOST}"
                    log_info "Auto-detected sandbox-${variant} URL: https://${VAR_HOST}"
                fi
            else
                # Kind: use in-cluster DNS (same pattern as sandbox-legion)
                if kubectl get deployment "sandbox-${variant}" -n team1 &>/dev/null; then
                    export "${VAR_NAME}=http://sandbox-${variant}.team1.svc.cluster.local:8000"
                    log_info "Using Kind sandbox-${variant} URL: http://sandbox-${variant}.team1.svc.cluster.local:8000"
                fi
            fi
        fi
    done
fi

# Auto-detect LiteLLM master key for proxy tests
if [ -z "${LITELLM_MASTER_KEY:-}" ]; then
    LMK=$(kubectl get secret litellm-proxy-secret -n kagenti-system \
        -o jsonpath='{.data.master-key}' 2>/dev/null | base64 -d 2>/dev/null || echo "")
    if [ -n "$LMK" ]; then
        export LITELLM_MASTER_KEY="$LMK"
        log_info "Auto-detected LiteLLM master key"
    fi
fi

# Auto-detect LiteLLM virtual key from team1 secret
if [ -z "${LITELLM_VIRTUAL_KEY:-}" ]; then
    LVK=$(kubectl get secret litellm-virtual-keys -n team1 \
        -o jsonpath='{.data.api-key}' 2>/dev/null | base64 -d 2>/dev/null || echo "")
    if [ -n "$LVK" ]; then
        export LITELLM_VIRTUAL_KEY="$LVK"
        log_info "Auto-detected LiteLLM virtual key from team1"
    fi
fi

# Auto-detect LiteLLM proxy URL for proxy tests
if [ -z "${LITELLM_PROXY_URL:-}" ]; then
    if [ "${IS_OPENSHIFT:-false}" = "true" ]; then
        LL_HOST=$(kubectl get route litellm-proxy -n kagenti-system -o jsonpath='{.spec.host}' 2>/dev/null || echo "")
        if [ -n "$LL_HOST" ]; then
            export LITELLM_PROXY_URL="https://$LL_HOST"
            log_info "Auto-detected LiteLLM proxy URL: $LITELLM_PROXY_URL"
        fi
    fi
    # Fallback: try in-cluster service
    if [ -z "${LITELLM_PROXY_URL:-}" ]; then
        LL_SVC=$(kubectl get svc litellm-proxy -n kagenti-system -o jsonpath='{.spec.clusterIP}' 2>/dev/null || echo "")
        if [ -n "$LL_SVC" ]; then
            export LITELLM_PROXY_URL="http://$LL_SVC:4000"
            log_info "Using in-cluster LiteLLM URL: $LITELLM_PROXY_URL"
        fi
    fi
fi

# Auto-detect RHOAI availability (check actual cluster state, not just config)
# The config file may say rhoai.enabled=true but the operator might not be installed.
if [ -z "${ENABLE_RHOAI_TESTS:-}" ]; then
    if kubectl get crd datascienceclusters.datasciencecluster.opendatahub.io &>/dev/null; then
        export ENABLE_RHOAI_TESTS=true
        log_info "RHOAI CRDs detected — enabling RHOAI tests"
    else
        export ENABLE_RHOAI_TESTS=false
        log_info "RHOAI CRDs not found — disabling RHOAI tests"
    fi
fi

# Auto-detect backend URL for UI/API tests
if [ -z "${KAGENTI_BACKEND_URL:-}" ]; then
    if [ "${IS_OPENSHIFT:-false}" = "true" ]; then
        BE_HOST=$(kubectl get route kagenti-api -n kagenti-system -o jsonpath='{.spec.host}' 2>/dev/null || echo "")
        if [ -n "$BE_HOST" ]; then
            export KAGENTI_BACKEND_URL="https://$BE_HOST"
            log_info "Auto-detected backend URL: $KAGENTI_BACKEND_URL"
        fi
    fi
fi

# Auto-detect RHOAI availability from CRDs
if [ -z "${ENABLE_RHOAI_TESTS:-}" ]; then
    if kubectl api-resources --api-group=datasciencecluster.opendatahub.io 2>/dev/null | grep -q datascienceclusters; then
        export ENABLE_RHOAI_TESTS=true
        log_info "RHOAI CRDs detected — enabling RHOAI tests"
    else
        export ENABLE_RHOAI_TESTS=false
        log_info "RHOAI CRDs not found — disabling RHOAI tests"
    fi
fi

echo "AGENT_URL: $AGENT_URL"
echo "KAGENTI_CONFIG_FILE: $KAGENTI_CONFIG_FILE"

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
PYTEST_OPTS="-v --timeout=300 --tb=short"

if [ -n "${PYTEST_FILTER:-}" ]; then
    PYTEST_OPTS="$PYTEST_OPTS -k \"$PYTEST_FILTER\""
    echo "Filtering tests with: -k \"$PYTEST_FILTER\""
fi

if [ -n "${PYTEST_ARGS:-}" ]; then
    PYTEST_OPTS="$PYTEST_OPTS $PYTEST_ARGS"
    echo "Additional pytest args: $PYTEST_ARGS"
fi

# Phase 1: Run all tests EXCEPT observability (generates traffic)
# This runs standard E2E tests that exercise the platform and generate traffic patterns
log_info "Phase 1: Running E2E tests (excluding observability)"
echo "Running: $PYTEST_CMD $PYTEST_TARGETS $PYTEST_OPTS -m \"not observability\" --junit-xml=../test-results/e2e-results.xml"
eval "$PYTEST_CMD $PYTEST_TARGETS $PYTEST_OPTS -m \"not observability\" --junit-xml=../test-results/e2e-results.xml" || {
    log_error "Backend E2E tests (phase 1) failed"
    exit 1
}

# Phase 2: Run ONLY observability tests (validates traffic patterns from phase 1)
# These tests require MLflow + Kiali which are only deployed on OpenShift clusters.
if [ "${IS_OPENSHIFT:-false}" = "true" ]; then
    log_info "Phase 2: Running observability tests (MLflow/Kiali validation)"
    eval "$PYTEST_CMD $PYTEST_TARGETS $PYTEST_OPTS -m \"observability\" --junit-xml=../test-results/e2e-observability-results.xml" || {
        log_error "Observability tests (phase 2) failed"
        exit 1
    }
else
    log_info "Phase 2: Skipping observability tests (not OpenShift — no MLflow/Kiali)"
fi

log_success "Backend E2E tests passed (both phases)"
