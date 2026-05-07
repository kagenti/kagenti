#!/usr/bin/env bash
# Ensure a test user and a service-account client exist in the Keycloak
# kagenti realm.  Runs AFTER the platform is deployed and Keycloak is
# reachable, BEFORE E2E tests start.
#
# Creates:
#   1. Test user "admin" in the kagenti realm (for agent AuthBridge auth)
#   2. Confidential client "kagenti-e2e-tests" with client_credentials
#      grant (for backend API tests that need a service account)
#
# Outputs (exported to GITHUB_ENV on CI):
#   KAGENTI_TEST_USER        – username
#   KAGENTI_TEST_PASSWORD    – password
#   KAGENTI_E2E_CLIENT_ID    – service account client id
#   KAGENTI_E2E_CLIENT_SECRET – service account client secret
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../lib/env-detect.sh"
source "$SCRIPT_DIR/../lib/logging.sh"

log_step "87" "Setting up test credentials in Keycloak"

# ============================================================================
# Resolve Keycloak URL and credentials
# ============================================================================

KEYCLOAK_URL="${KEYCLOAK_URL:-http://localhost:8081}"

# Read admin credentials from K8s secret
ADMIN_USER=$(kubectl get secret keycloak-initial-admin -n keycloak \
    -o jsonpath='{.data.username}' | base64 -d)
ADMIN_PASS=$(kubectl get secret keycloak-initial-admin -n keycloak \
    -o jsonpath='{.data.password}' | base64 -d)

# Read realm from kagenti-test-user secret (if it exists), else default
REALM=$(kubectl get secret kagenti-test-user -n keycloak \
    -o jsonpath='{.data.realm}' 2>/dev/null | base64 -d 2>/dev/null || echo "kagenti")

log_info "Keycloak URL: $KEYCLOAK_URL"
log_info "Target realm: $REALM"

# Helper: Keycloak Admin API call with error reporting
kc_api() {
    local method="$1" url="$2"
    shift 2
    local resp http_code
    resp=$(curl -sk -w "\n%{http_code}" -X "$method" \
        -H "Authorization: Bearer $ADMIN_TOKEN" \
        -H "Content-Type: application/json" \
        "$url" "$@" 2>&1)
    http_code=$(echo "$resp" | tail -1)
    echo "$resp" | sed '$d'
    return 0
}

# ============================================================================
# Get admin token (master realm)
# ============================================================================

ADMIN_TOKEN=$(curl -sk -X POST \
    "$KEYCLOAK_URL/realms/master/protocol/openid-connect/token" \
    -d "grant_type=password&client_id=admin-cli&username=$ADMIN_USER&password=$ADMIN_PASS" \
    | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])" 2>/dev/null || echo "")

if [ -z "$ADMIN_TOKEN" ]; then
    log_error "Failed to get Keycloak admin token"
    exit 1
fi
log_success "Got admin token"

# ============================================================================
# 1. Ensure realm exists
# ============================================================================

REALM_STATUS=$(curl -sk -o /dev/null -w "%{http_code}" \
    -H "Authorization: Bearer $ADMIN_TOKEN" \
    "$KEYCLOAK_URL/admin/realms/$REALM" 2>/dev/null || echo "000")

if [ "$REALM_STATUS" = "404" ]; then
    log_info "Creating realm '$REALM'..."
    kc_api POST "$KEYCLOAK_URL/admin/realms" \
        -d "{\"realm\": \"$REALM\", \"enabled\": true}" >/dev/null
    log_success "Realm '$REALM' created"
elif [ "$REALM_STATUS" = "200" ]; then
    log_info "Realm '$REALM' exists"
else
    log_error "Could not check realm (HTTP $REALM_STATUS)"
    exit 1
fi

# ============================================================================
# 2. Enable Direct Access Grants on admin-cli (GET-modify-PUT)
#    Keycloak PUT /clients/{id} requires FULL client representation.
# ============================================================================

ADMIN_CLI_JSON=$(kc_api GET "$KEYCLOAK_URL/admin/realms/$REALM/clients?clientId=admin-cli")
ADMIN_CLI_ID=$(echo "$ADMIN_CLI_JSON" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d[0]['id'] if d else '')" 2>/dev/null || echo "")

if [ -n "$ADMIN_CLI_ID" ]; then
    # GET full client, set directAccessGrantsEnabled, PUT back
    FULL_CLIENT=$(kc_api GET "$KEYCLOAK_URL/admin/realms/$REALM/clients/$ADMIN_CLI_ID")
    UPDATED_CLIENT=$(echo "$FULL_CLIENT" | python3 -c "
import sys, json
c = json.load(sys.stdin)
c['directAccessGrantsEnabled'] = True
print(json.dumps(c))
" 2>/dev/null || echo "")
    if [ -n "$UPDATED_CLIENT" ]; then
        kc_api PUT "$KEYCLOAK_URL/admin/realms/$REALM/clients/$ADMIN_CLI_ID" \
            -d "$UPDATED_CLIENT" >/dev/null
        log_success "Enabled Direct Access Grants on admin-cli"
    fi
fi

# ============================================================================
# 3. Create test user (or reset password if exists)
# ============================================================================

TEST_USER="admin"
TEST_PASS=$(python3 -c "import secrets; print(secrets.token_urlsafe(16))")

USER_JSON=$(kc_api GET "$KEYCLOAK_URL/admin/realms/$REALM/users?username=$TEST_USER&exact=true")
USER_COUNT=$(echo "$USER_JSON" | python3 -c "import sys,json; print(len(json.load(sys.stdin)))" 2>/dev/null || echo "0")

if [ "$USER_COUNT" = "0" ]; then
    log_info "Creating test user '$TEST_USER' in realm '$REALM'..."
    CREATE_RESP=$(kc_api POST "$KEYCLOAK_URL/admin/realms/$REALM/users" \
        -d "{
            \"username\": \"$TEST_USER\",
            \"firstName\": \"$TEST_USER\",
            \"lastName\": \"Test\",
            \"email\": \"$TEST_USER@kagenti.dev\",
            \"emailVerified\": true,
            \"enabled\": true,
            \"requiredActions\": [],
            \"credentials\": [{\"type\": \"password\", \"value\": \"$TEST_PASS\", \"temporary\": false}]
        }")
    log_success "Test user '$TEST_USER' created"

    # Re-fetch user to get ID
    USER_JSON=$(kc_api GET "$KEYCLOAK_URL/admin/realms/$REALM/users?username=$TEST_USER&exact=true")
fi

USER_ID=$(echo "$USER_JSON" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d[0]['id'] if d else '')" 2>/dev/null || echo "")

if [ -n "$USER_ID" ]; then
    # GET full user, clear requiredActions, PUT back (full representation)
    FULL_USER=$(kc_api GET "$KEYCLOAK_URL/admin/realms/$REALM/users/$USER_ID")
    UPDATED_USER=$(echo "$FULL_USER" | python3 -c "
import sys, json
u = json.load(sys.stdin)
u['requiredActions'] = []
u['emailVerified'] = True
u['enabled'] = True
print(json.dumps(u))
" 2>/dev/null || echo "")
    if [ -n "$UPDATED_USER" ]; then
        kc_api PUT "$KEYCLOAK_URL/admin/realms/$REALM/users/$USER_ID" \
            -d "$UPDATED_USER" >/dev/null
    fi

    # Use dedicated reset-password endpoint (not user PUT)
    kc_api PUT "$KEYCLOAK_URL/admin/realms/$REALM/users/$USER_ID/reset-password" \
        -d "{\"type\": \"password\", \"value\": \"$TEST_PASS\", \"temporary\": false}" >/dev/null

    # Verify final state
    FINAL_USER=$(kc_api GET "$KEYCLOAK_URL/admin/realms/$REALM/users/$USER_ID")
    FINAL_ACTIONS=$(echo "$FINAL_USER" | python3 -c "import sys,json; print(json.load(sys.stdin).get('requiredActions', []))" 2>/dev/null || echo "?")
    FINAL_EMAIL_V=$(echo "$FINAL_USER" | python3 -c "import sys,json; print(json.load(sys.stdin).get('emailVerified', '?'))" 2>/dev/null || echo "?")
    log_info "User state: requiredActions=$FINAL_ACTIONS emailVerified=$FINAL_EMAIL_V"
fi

# Verify: get a token for the test user
TOKEN_RESP=$(curl -sk -X POST \
    "$KEYCLOAK_URL/realms/$REALM/protocol/openid-connect/token" \
    -d "grant_type=password&client_id=admin-cli&username=$TEST_USER&password=$TEST_PASS" 2>&1)
TEST_TOKEN=$(echo "$TOKEN_RESP" | python3 -c "import sys,json; print(json.load(sys.stdin).get('access_token',''))" 2>/dev/null || echo "")

if [ -z "$TEST_TOKEN" ]; then
    log_error "Could not acquire token for test user"
    log_error "Response: $TOKEN_RESP"
    exit 1
fi
log_success "Test user token verified (length=${#TEST_TOKEN})"

# ============================================================================
# 4. Create service account client for API tests
# ============================================================================

E2E_CLIENT_ID="kagenti-e2e-tests"

CLIENT_JSON=$(kc_api GET "$KEYCLOAK_URL/admin/realms/$REALM/clients?clientId=$E2E_CLIENT_ID")
CLIENT_COUNT=$(echo "$CLIENT_JSON" | python3 -c "import sys,json; print(len(json.load(sys.stdin)))" 2>/dev/null || echo "0")

if [ "$CLIENT_COUNT" = "0" ]; then
    log_info "Creating service account client '$E2E_CLIENT_ID'..."
    kc_api POST "$KEYCLOAK_URL/admin/realms/$REALM/clients" \
        -d "{
            \"clientId\": \"$E2E_CLIENT_ID\",
            \"enabled\": true,
            \"publicClient\": false,
            \"serviceAccountsEnabled\": true,
            \"standardFlowEnabled\": false,
            \"directAccessGrantsEnabled\": true
        }" >/dev/null
    log_success "Service account client '$E2E_CLIENT_ID' created"
fi

# Get the client's internal ID and secret
CLIENT_INTERNAL_ID=$(kc_api GET "$KEYCLOAK_URL/admin/realms/$REALM/clients?clientId=$E2E_CLIENT_ID" \
    | python3 -c "import sys,json; print(json.load(sys.stdin)[0]['id'])")

E2E_CLIENT_SECRET=$(kc_api GET "$KEYCLOAK_URL/admin/realms/$REALM/clients/$CLIENT_INTERNAL_ID/client-secret" \
    | python3 -c "import sys,json; print(json.load(sys.stdin)['value'])")

log_success "Service account client ready (client_id=$E2E_CLIENT_ID)"

# ============================================================================
# 4b. Attach agent audience scopes to the E2E test client
#     Client-registration creates agent-*-aud scopes as realm defaults, but
#     realm defaults don't retroactively apply to existing clients. We need
#     to explicitly add them so the E2E test token contains the aud claim
#     that AuthBridge requires for inbound JWT validation.
# ============================================================================

log_info "Attaching agent audience scopes to $E2E_CLIENT_ID..."
# Agent audience scopes (agent-*-aud) are created asynchronously by the
# kagenti-operator ClientRegistrationReconciler (or legacy sidecar).
# Wait for them before minting the test token, otherwise AuthBridge rejects
# every request with 401 "audience is required".
AGENT_COUNT=$(kubectl get deployment -n team1 -l kagenti.io/type=agent \
    -o name 2>/dev/null | wc -l | tr -d ' ')
SCOPE_WAIT_TIMEOUT="${SCOPE_WAIT_TIMEOUT:-300}"
AGENT_SCOPE_IDS=""

if [ "${AGENT_COUNT:-0}" -gt 0 ]; then
    _elapsed=0
    while [ $_elapsed -lt "$SCOPE_WAIT_TIMEOUT" ]; do
        REALM_DEFAULT_SCOPES=$(kc_api GET "$KEYCLOAK_URL/admin/realms/$REALM/default-default-client-scopes")
        AGENT_SCOPE_IDS=$(echo "$REALM_DEFAULT_SCOPES" | python3 -c "
import sys, json
scopes = json.load(sys.stdin)
for s in scopes:
    if s['name'].startswith('agent-') and s['name'].endswith('-aud'):
        print(s['id'], s['name'])
" 2>/dev/null || echo "")
        if [ -n "$AGENT_SCOPE_IDS" ]; then
            break
        fi
        log_info "  No agent audience scopes yet, waiting... (${_elapsed}s/${SCOPE_WAIT_TIMEOUT}s)"
        sleep 10
        _elapsed=$((_elapsed + 10))
    done
else
    log_info "  No agent deployments in team1 — skipping audience scope wait"
fi

if [ -n "$AGENT_SCOPE_IDS" ]; then
    while IFS=' ' read -r scope_id scope_name; do
        kc_api PUT "$KEYCLOAK_URL/admin/realms/$REALM/clients/$CLIENT_INTERNAL_ID/default-client-scopes/$scope_id" >/dev/null
        log_info "  Added scope '$scope_name' to $E2E_CLIENT_ID"
    done <<< "$AGENT_SCOPE_IDS"
else
    # Fallback: create a platform-level audience scope so the test token
    # includes the aud claim that AuthBridge requires. This covers the case
    # where neither the sidecar nor the operator controller has created
    # agent-specific scopes yet.
    log_warn "No agent audience scopes found — adding audience mapper directly to test client"
    # Refresh admin token (the original likely expired during the 5-minute scope wait)
    ADMIN_TOKEN=$(curl -sk -X POST \
        "$KEYCLOAK_URL/realms/master/protocol/openid-connect/token" \
        -d "grant_type=password&client_id=admin-cli&username=$ADMIN_USER&password=$ADMIN_PASS" \
        | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])" 2>/dev/null || echo "")
    KEYCLOAK_PUBLIC_URL=$(kubectl get configmap authbridge-config -n team1 \
        -o jsonpath='{.data.EXPECTED_AUDIENCE}' 2>/dev/null || echo "")
    if [ -n "$KEYCLOAK_PUBLIC_URL" ]; then
        # Add audience mapper directly to the test client (more reliable than client scopes)
        MAPPER_PAYLOAD=$(python3 -c "
import json, sys
print(json.dumps({
    'name': 'kagenti-platform-audience',
    'protocol': 'openid-connect',
    'protocolMapper': 'oidc-audience-mapper',
    'consentRequired': False,
    'config': {
        'included.custom.audience': sys.argv[1],
        'id.token.claim': 'false',
        'access.token.claim': 'true',
        'introspection.token.claim': 'true'
    }
}))
" "$KEYCLOAK_PUBLIC_URL")
        kc_api POST "$KEYCLOAK_URL/admin/realms/$REALM/clients/$CLIENT_INTERNAL_ID/protocol-mappers/models" \
            -d "$MAPPER_PAYLOAD" >/dev/null 2>&1 || true
        # Verify the mapper was added
        MAPPER_CHECK=$(kc_api GET "$KEYCLOAK_URL/admin/realms/$REALM/clients/$CLIENT_INTERNAL_ID/protocol-mappers/models" | \
            python3 -c "import sys,json; mappers=json.load(sys.stdin); print('yes' if any(m['name']=='kagenti-platform-audience' for m in mappers) else 'no')" 2>/dev/null || echo "no")
        if [ "$MAPPER_CHECK" = "yes" ]; then
            log_success "Added audience mapper to $E2E_CLIENT_ID (aud=$KEYCLOAK_PUBLIC_URL)"
        else
            log_warn "Failed to add audience mapper — agent tests may fail with 401"
        fi
    else
        log_warn "Could not determine EXPECTED_AUDIENCE from authbridge-config — agent tests may fail with 401"
    fi
fi

# ============================================================================
# 5. Update kagenti-test-user secret with verified credentials
# ============================================================================

log_info "Updating kagenti-test-user secret with verified credentials..."
kubectl create secret generic kagenti-test-user \
    --namespace keycloak \
    --from-literal=username="$TEST_USER" \
    --from-literal=password="$TEST_PASS" \
    --from-literal=realm="$REALM" \
    --from-literal=client_id="$E2E_CLIENT_ID" \
    --from-literal=client_secret="$E2E_CLIENT_SECRET" \
    --dry-run=client -o yaml | kubectl apply -f - >/dev/null 2>&1

# ============================================================================
# 6. Export to environment (CI and local)
# ============================================================================

if [ "$IS_CI" = true ]; then
    {
        echo "KAGENTI_TEST_USER=$TEST_USER"
        echo "KAGENTI_TEST_PASSWORD=$TEST_PASS"
        echo "KAGENTI_E2E_CLIENT_ID=$E2E_CLIENT_ID"
        echo "KAGENTI_E2E_CLIENT_SECRET=$E2E_CLIENT_SECRET"
    } >> "$GITHUB_ENV"
else
    export KAGENTI_TEST_USER="$TEST_USER"
    export KAGENTI_TEST_PASSWORD="$TEST_PASS"
    export KAGENTI_E2E_CLIENT_ID="$E2E_CLIENT_ID"
    export KAGENTI_E2E_CLIENT_SECRET="$E2E_CLIENT_SECRET"
fi

log_success "Test credentials ready"
log_info "  Test user: $TEST_USER (realm: $REALM)"
log_info "  Service account: $E2E_CLIENT_ID"
log_info "  Run ./.github/scripts/local-setup/show-services.sh to see login credentials"
