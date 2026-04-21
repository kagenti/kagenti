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
c['fullScopeAllowed'] = True
print(json.dumps(c))
" 2>/dev/null || echo "")
    if [ -n "$UPDATED_CLIENT" ]; then
        kc_api PUT "$KEYCLOAK_URL/admin/realms/$REALM/clients/$ADMIN_CLI_ID" \
            -d "$UPDATED_CLIENT" >/dev/null
        log_success "Enabled Direct Access Grants and Full Scope on admin-cli"
    fi

    # Add realm roles protocol mapper so realm roles appear in access tokens
    MAPPER_EXISTS=$(kc_api GET "$KEYCLOAK_URL/admin/realms/$REALM/clients/$ADMIN_CLI_ID/protocol-mappers/models" \
        | python3 -c "import sys,json; print(any(m.get('name')=='realm roles' for m in json.load(sys.stdin)))" 2>/dev/null || echo "False")
    if [ "$MAPPER_EXISTS" = "False" ]; then
        kc_api POST "$KEYCLOAK_URL/admin/realms/$REALM/clients/$ADMIN_CLI_ID/protocol-mappers/models" \
            -d '{
                "name": "realm roles",
                "protocol": "openid-connect",
                "protocolMapper": "oidc-usermodel-realm-role-mapper",
                "config": {
                    "multivalued": "true",
                    "claim.name": "realm_access.roles",
                    "jsonType.label": "String",
                    "id.token.claim": "true",
                    "access.token.claim": "true",
                    "userinfo.token.claim": "true"
                }
            }' >/dev/null
        log_success "Added realm roles mapper to admin-cli"
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

# ============================================================================
# 3b. Assign kagenti-viewer realm role (required for backend API access)
# ============================================================================

if [ -n "$USER_ID" ]; then
    # Get the kagenti-viewer role ID
    VIEWER_ROLE_JSON=$(kc_api GET "$KEYCLOAK_URL/admin/realms/$REALM/roles/kagenti-viewer")
    VIEWER_ROLE_ID=$(echo "$VIEWER_ROLE_JSON" | python3 -c "import sys,json; print(json.load(sys.stdin).get('id',''))" 2>/dev/null || echo "")
    if [ -n "$VIEWER_ROLE_ID" ]; then
        kc_api POST "$KEYCLOAK_URL/admin/realms/$REALM/users/$USER_ID/role-mappings/realm" \
            -d "[{\"id\": \"$VIEWER_ROLE_ID\", \"name\": \"kagenti-viewer\"}]" >/dev/null
        log_success "Assigned kagenti-viewer role to test user"
    else
        log_info "kagenti-viewer role not found in realm — creating it"
        kc_api POST "$KEYCLOAK_URL/admin/realms/$REALM/roles" \
            -d '{"name": "kagenti-viewer", "description": "Read-only access to Kagenti APIs"}' >/dev/null
        VIEWER_ROLE_JSON=$(kc_api GET "$KEYCLOAK_URL/admin/realms/$REALM/roles/kagenti-viewer")
        VIEWER_ROLE_ID=$(echo "$VIEWER_ROLE_JSON" | python3 -c "import sys,json; print(json.load(sys.stdin).get('id',''))" 2>/dev/null || echo "")
        if [ -n "$VIEWER_ROLE_ID" ]; then
            kc_api POST "$KEYCLOAK_URL/admin/realms/$REALM/users/$USER_ID/role-mappings/realm" \
                -d "[{\"id\": \"$VIEWER_ROLE_ID\", \"name\": \"kagenti-viewer\"}]" >/dev/null
            log_success "Created and assigned kagenti-viewer role"
        fi
    fi
fi

# ============================================================================
# 3c. Assign kagenti-operator realm role (required for sandbox chat/stream API)
# ============================================================================

if [ -n "$USER_ID" ]; then
    # Get the kagenti-operator role ID
    OPERATOR_ROLE_JSON=$(kc_api GET "$KEYCLOAK_URL/admin/realms/$REALM/roles/kagenti-operator")
    OPERATOR_ROLE_ID=$(echo "$OPERATOR_ROLE_JSON" | python3 -c "import sys,json; print(json.load(sys.stdin).get('id',''))" 2>/dev/null || echo "")
    if [ -n "$OPERATOR_ROLE_ID" ]; then
        kc_api POST "$KEYCLOAK_URL/admin/realms/$REALM/users/$USER_ID/role-mappings/realm" \
            -d "[{\"id\": \"$OPERATOR_ROLE_ID\", \"name\": \"kagenti-operator\"}]" >/dev/null
        log_success "Assigned kagenti-operator role to test user"
    else
        log_info "kagenti-operator role not found in realm — creating it"
        kc_api POST "$KEYCLOAK_URL/admin/realms/$REALM/roles" \
            -d '{"name": "kagenti-operator", "description": "Operator access to Kagenti sandbox APIs"}' >/dev/null
        OPERATOR_ROLE_JSON=$(kc_api GET "$KEYCLOAK_URL/admin/realms/$REALM/roles/kagenti-operator")
        OPERATOR_ROLE_ID=$(echo "$OPERATOR_ROLE_JSON" | python3 -c "import sys,json; print(json.load(sys.stdin).get('id',''))" 2>/dev/null || echo "")
        if [ -n "$OPERATOR_ROLE_ID" ]; then
            kc_api POST "$KEYCLOAK_URL/admin/realms/$REALM/users/$USER_ID/role-mappings/realm" \
                -d "[{\"id\": \"$OPERATOR_ROLE_ID\", \"name\": \"kagenti-operator\"}]" >/dev/null
            log_success "Created and assigned kagenti-operator role to test user"
        fi
    fi
fi

# ============================================================================
# 3d. Create additional test users for multi-user identity tests
# ============================================================================

EXTRA_USERS_ARGS=()
for EXTRA_USER in dev-user ns-admin; do
    EXTRA_PASS=$(python3 -c "import secrets; print(secrets.token_urlsafe(16))" 2>/dev/null || echo "test-pass-${EXTRA_USER}")
    EXISTING=$(kc_api GET "$KEYCLOAK_URL/admin/realms/$REALM/users?username=$EXTRA_USER&exact=true")
    EXISTING_COUNT=$(echo "$EXISTING" | python3 -c "import sys,json; print(len(json.load(sys.stdin)))" 2>/dev/null || echo "0")

    if [ "$EXISTING_COUNT" = "0" ]; then
        kc_api POST "$KEYCLOAK_URL/admin/realms/$REALM/users" \
            -d "{
                \"username\": \"$EXTRA_USER\",
                \"firstName\": \"$EXTRA_USER\",
                \"lastName\": \"Test\",
                \"email\": \"${EXTRA_USER}@kagenti.dev\",
                \"enabled\": true,
                \"emailVerified\": true
            }" >/dev/null || true
        log_info "Created test user '$EXTRA_USER'"
    fi

    # Get user ID
    EXTRA_USER_JSON=$(kc_api GET "$KEYCLOAK_URL/admin/realms/$REALM/users?username=$EXTRA_USER&exact=true")
    EXTRA_USER_ID=$(echo "$EXTRA_USER_JSON" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d[0]['id'] if d else '')" 2>/dev/null || echo "")

    if [ -n "$EXTRA_USER_ID" ]; then
        # Reset password
        kc_api PUT "$KEYCLOAK_URL/admin/realms/$REALM/users/$EXTRA_USER_ID/reset-password" \
            -d "{\"type\": \"password\", \"value\": \"$EXTRA_PASS\", \"temporary\": false}" >/dev/null || true

        # Assign viewer role to all extra users
        if [ -n "${VIEWER_ROLE_ID:-}" ]; then
            kc_api POST "$KEYCLOAK_URL/admin/realms/$REALM/users/$EXTRA_USER_ID/role-mappings/realm" \
                -d "[{\"id\": \"$VIEWER_ROLE_ID\", \"name\": \"kagenti-viewer\"}]" >/dev/null || true
        fi

        # ns-admin gets operator role too
        if [ "$EXTRA_USER" = "ns-admin" ] && [ -n "${OPERATOR_ROLE_ID:-}" ]; then
            kc_api POST "$KEYCLOAK_URL/admin/realms/$REALM/users/$EXTRA_USER_ID/role-mappings/realm" \
                -d "[{\"id\": \"$OPERATOR_ROLE_ID\", \"name\": \"kagenti-operator\"}]" >/dev/null || true
        fi

        # Store credentials in K8s secret for tests (keycloak namespace for Playwright, team1 for pytest)
        kubectl create secret generic "${EXTRA_USER}-password" -n team1 \
            --from-literal=password="$EXTRA_PASS" --dry-run=client -o yaml | kubectl apply -f - >/dev/null 2>&1 || true
        # Accumulate for combined secret
        EXTRA_USERS_ARGS+=(--from-literal="${EXTRA_USER}-password=$EXTRA_PASS")

        log_success "Test user '$EXTRA_USER' ready (password in secret ${EXTRA_USER}-password)"
    fi
done

# Create combined secret in keycloak namespace (Playwright tests look here)
if [ ${#EXTRA_USERS_ARGS[@]} -gt 0 ]; then
    kubectl create secret generic kagenti-test-users -n keycloak \
        "${EXTRA_USERS_ARGS[@]}" \
        --dry-run=client -o yaml | kubectl apply -f - >/dev/null 2>&1 || true
    log_success "Combined test user passwords stored in keycloak/kagenti-test-users"
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
# 5. Update kagenti-test-user secret with verified credentials
# ============================================================================

# Assign kagenti-viewer role to the service account of kagenti-e2e-tests
SA_USER_ID=$(kc_api GET "$KEYCLOAK_URL/admin/realms/$REALM/clients/$CLIENT_INTERNAL_ID/service-account-user" \
    | python3 -c "import sys,json; print(json.load(sys.stdin).get('id',''))" 2>/dev/null || echo "")
if [ -n "$SA_USER_ID" ] && [ -n "${VIEWER_ROLE_ID:-}" ]; then
    kc_api POST "$KEYCLOAK_URL/admin/realms/$REALM/users/$SA_USER_ID/role-mappings/realm" \
        -d "[{\"id\": \"$VIEWER_ROLE_ID\", \"name\": \"kagenti-viewer\"}]" >/dev/null
    log_success "Assigned kagenti-viewer role to $E2E_CLIENT_ID service account"
fi
# Also assign kagenti-operator to the service account
if [ -n "$SA_USER_ID" ] && [ -n "${OPERATOR_ROLE_ID:-}" ]; then
    kc_api POST "$KEYCLOAK_URL/admin/realms/$REALM/users/$SA_USER_ID/role-mappings/realm" \
        -d "[{\"id\": \"$OPERATOR_ROLE_ID\", \"name\": \"kagenti-operator\"}]" >/dev/null
    log_success "Assigned kagenti-operator role to $E2E_CLIENT_ID service account"
fi

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
