#!/usr/bin/env bash
#
# Setup LLM Teams via Backend API
#
# Creates litellm teams + default virtual keys for agent namespaces
# by calling the kagenti backend API. Must run AFTER:
#   - 30-run-installer.sh (platform + keycloak)
#   - 38-deploy-litellm.sh (litellm proxy)
#   - 37-build-platform-images.sh (backend with llm_keys router)
#
# Usage:
#   ./.github/scripts/kagenti-operator/39-setup-llm-teams.sh
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../lib/env-detect.sh"
source "$SCRIPT_DIR/../lib/logging.sh"

log_step "39" "Setting up LLM teams via backend API"

NAMESPACES="${AGENT_NAMESPACES:-team1 team2}"
MAX_BUDGET="${LLM_TEAM_BUDGET:-500}"

# Get backend URL
if [ "$IS_OPENSHIFT" = "true" ]; then
    BACKEND_ROUTE=$(kubectl get route kagenti-ui -n kagenti-system -o jsonpath='{.spec.host}' 2>/dev/null || echo "")
    if [ -n "$BACKEND_ROUTE" ]; then
        BACKEND_URL="https://$BACKEND_ROUTE"
    fi
fi

if [ -z "${BACKEND_URL:-}" ]; then
    log_info "Using port-forward to backend..."
    BACKEND_PF_PORT=18099
    lsof -ti:${BACKEND_PF_PORT} 2>/dev/null | xargs kill 2>/dev/null || true
    sleep 1
    kubectl port-forward -n kagenti-system svc/kagenti-backend \
        "${BACKEND_PF_PORT}:8080" &>/tmp/kagenti-backend-pf.log &
    PF_PID=$!
    trap "kill $PF_PID 2>/dev/null || true" EXIT

    for i in $(seq 1 15); do
        if curl -s -o /dev/null -w "%{http_code}" "http://localhost:${BACKEND_PF_PORT}/health" 2>/dev/null | grep -q "200"; then
            break
        fi
        sleep 2
    done
    BACKEND_URL="http://localhost:${BACKEND_PF_PORT}"
fi

# Get auth token from Keycloak
KEYCLOAK_URL=$(kubectl get configmap kagenti-ui-config -n kagenti-system -o jsonpath='{.data.KEYCLOAK_CONSOLE_URL}' 2>/dev/null || echo "")
if [ -z "$KEYCLOAK_URL" ]; then
    KEYCLOAK_URL="http://keycloak-service.keycloak.svc:8080"
fi

CLIENT_SECRET=$(kubectl get secret kagenti-ui-oauth-secret -n kagenti-system \
    -o jsonpath='{.data.CLIENT_SECRET}' 2>/dev/null | base64 -d 2>/dev/null || echo "")

KEYCLOAK_PASSWORD="${KEYCLOAK_PASSWORD:-admin}"

TOKEN=$(curl -sk "$KEYCLOAK_URL/realms/master/protocol/openid-connect/token" \
    -d "client_id=kagenti" \
    -d "client_secret=$CLIENT_SECRET" \
    -d "username=admin" \
    -d "password=$KEYCLOAK_PASSWORD" \
    -d "grant_type=password" \
    -d "scope=openid" 2>/dev/null | jq -r '.access_token // empty' 2>/dev/null || echo "")

if [ -z "$TOKEN" ]; then
    log_warn "Could not get auth token — skipping team setup"
    log_info "Teams can be created manually: POST /api/v1/llm/teams"
    exit 0
fi

# Create teams
for ns in $NAMESPACES; do
    log_info "Creating LLM team for $ns..."
    RESULT=$(curl -sk -X POST "$BACKEND_URL/api/v1/llm/teams" \
        -H "Authorization: Bearer $TOKEN" \
        -H "Content-Type: application/json" \
        -d "{\"namespace\": \"$ns\", \"max_budget\": $MAX_BUDGET}" 2>/dev/null || echo '{"error": "request failed"}')

    if echo "$RESULT" | jq -e '.team_id // empty' >/dev/null 2>&1; then
        log_success "Team created for $ns"
    elif echo "$RESULT" | grep -q "503"; then
        log_warn "LiteLLM master key not configured — skipping"
        break
    else
        log_warn "Team setup for $ns: $RESULT"
    fi
done

log_success "LLM team setup complete"
