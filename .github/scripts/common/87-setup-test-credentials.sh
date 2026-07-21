#!/usr/bin/env bash
# Ensure a test user and a service-account client exist in the Keycloak
# rossoctl realm.  Runs AFTER the platform is deployed and Keycloak is
# reachable, BEFORE E2E tests start.
#
# Creates:
#   1. Test user "admin" in the rossoctl realm (for agent AuthBridge auth)
#   2. Confidential client "rossoctl-e2e-tests" with client_credentials
#      grant (for backend API tests that need a service account)
#
# Outputs (exported to GITHUB_ENV on CI):
#   ROSSOCTL_TEST_USER        – username
#   ROSSOCTL_TEST_PASSWORD    – password
#   ROSSOCTL_E2E_CLIENT_ID    – service account client id
#   ROSSOCTL_E2E_CLIENT_SECRET – service account client secret
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

# Read realm from rossoctl-test-user secret (if it exists), else default
REALM=$(kubectl get secret rossoctl-test-user -n keycloak \
    -o jsonpath='{.data.realm}' 2>/dev/null | base64 -d 2>/dev/null || echo "rossoctl")

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

# Factored out so the scope-existence poll below can refresh the admin
# token. The master-realm admin access token lives ~60s; a 5-minute wait
# loop would otherwise fire API calls with an expired bearer.
refresh_admin_token() {
    ADMIN_TOKEN=$(curl -sk -X POST \
        "$KEYCLOAK_URL/realms/master/protocol/openid-connect/token" \
        -d "grant_type=password&client_id=admin-cli&username=$ADMIN_USER&password=$ADMIN_PASS" \
        | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])" 2>/dev/null || echo "")
}

refresh_admin_token

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
            \"email\": \"$TEST_USER@rossoctl.dev\",
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

E2E_CLIENT_ID="rossoctl-e2e-tests"

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

# On scope-gate timeout, dump the state of every input the operator's
# ClientRegistrationReconciler depends on. Printed to the CI log so the
# next failed run is self-diagnostic — no need to re-run with extra
# debugging to figure out why the reconciler didn't create the scope.
dump_scope_timeout_diagnostics() {
    echo
    echo "=========================================================================="
    echo " DIAGNOSTICS: scope-gate timeout on ClientRegistrationReconciler"
    echo "=========================================================================="

    echo
    echo "--- Agent deployments in team1 (pod template labels + annotations) ---"
    kubectl get deployment -n team1 -l rossoctl.io/type=agent \
        -o 'custom-columns=NAME:.metadata.name,READY:.status.readyReplicas,AVAILABLE:.status.availableReplicas,AGE:.metadata.creationTimestamp' \
        2>&1 || echo "  (failed to list)"
    for dep in $(kubectl get deployment -n team1 -l rossoctl.io/type=agent -o name 2>/dev/null); do
        echo
        echo "  Deployment: $dep"
        echo "  Pod-template labels:"
        kubectl get "$dep" -n team1 -o jsonpath='{.spec.template.metadata.labels}' 2>&1 | python3 -m json.tool 2>/dev/null | sed 's/^/    /' || echo "    (failed)"
        echo "  Pod-template annotations (looking for rossoctl.io/keycloak-client-credentials-secret-name):"
        kubectl get "$dep" -n team1 -o jsonpath='{.spec.template.metadata.annotations}' 2>&1 | python3 -m json.tool 2>/dev/null | sed 's/^/    /' || echo "    (failed)"
    done

    echo
    echo "--- team1 authbridge-config ConfigMap (what the reconciler reads) ---"
    kubectl get configmap -n team1 authbridge-config -o yaml 2>&1 | \
        grep -E '^  [A-Z_]+:|^data:' | head -30 || echo "  (not found — reconciler will requeue forever on 'waiting for KEYCLOAK_URL/KEYCLOAK_REALM')"

    echo
    echo "--- keycloak-admin-secret (now in rossoctl-system, not team1) ---"
    kubectl get secret -n rossoctl-system keycloak-admin-secret \
        -o jsonpath='{"  keys: "}{.data}{"\n"}' 2>&1 | python3 -c "
import sys, json, re
s = sys.stdin.read().strip()
m = re.match(r'^\s*keys:\s*(\{.*\})\s*$', s, re.DOTALL)
if m:
    try:
        d = json.loads(m.group(1).replace(\"'\", '\"'))
        for k in d:
            print(f'    - {k}')
    except Exception:
        print(s)
else:
    print(s)
" 2>&1 || echo "  (not found — operator will be unable to register clients)"

    echo
    echo "--- rossoctl-operator controller pod status ---"
    kubectl get pods -n rossoctl-system -l app.kubernetes.io/name=rossoctl-operator \
        -o 'custom-columns=NAME:.metadata.name,READY:.status.containerStatuses[*].ready,RESTARTS:.status.containerStatuses[*].restartCount,PHASE:.status.phase,AGE:.metadata.creationTimestamp' \
        2>&1 | head -5 || echo "  (failed to list)"

    echo
    echo "--- rossoctl-operator recent logs (broader grep than 85-collect-failure-info.sh) ---"
    kubectl logs -n rossoctl-system deployment/rossoctl-controller-manager --tail=200 2>/dev/null | \
        grep -iE 'waiting for|cannot resolve|skip|reconcile|client.?regist|keycloak|credential|error|ERROR|audience' | \
        tail -50 || echo "  (no operator logs matched — broaden the grep or increase --tail)"

    echo
    echo "--- Keycloak realm clients (is weather-service registered?) ---"
    refresh_admin_token
    kc_api GET "$KEYCLOAK_URL/admin/realms/$REALM/clients?clientId=team1/weather-service" 2>&1 | \
        python3 -c "
import sys, json
try:
    clients = json.load(sys.stdin)
    if not clients:
        print('  NO CLIENT — reconciler never reached Keycloak admin API')
    else:
        for c in clients:
            print(f\"  clientId: {c.get('clientId')}, enabled: {c.get('enabled')}, defaultClientScopes: {c.get('defaultClientScopes', [])}\")
except Exception as e:
    print(f'  parse error: {e}')
" 2>&1 || echo "  (API call failed)"

    echo
    echo "--- Keycloak realm default-default client scopes (what we were polling for) ---"
    kc_api GET "$KEYCLOAK_URL/admin/realms/$REALM/default-default-client-scopes" 2>&1 | \
        python3 -c "
import sys, json
try:
    scopes = json.load(sys.stdin)
    for s in scopes:
        print(f\"  - {s['name']}\")
except Exception as e:
    print(f'  parse error: {e}')
" 2>&1 | head -30 || echo "  (API call failed)"

    echo "=========================================================================="
    echo
}

# Gate: wait for at least one agent-*-aud scope to appear in the realm
# before trying to attach them. These scopes are created asynchronously
# by rossoctl-operator's ClientRegistrationReconciler (default path) or
# by the legacy client-registration sidecar (opt-in). If we query before
# either path finishes, the test token is minted without an aud claim
# and AuthBridge rejects every request with 401
# "audience is required (prevents confused deputy attacks)".
#
# The wait is skipped when no agent deployments exist in team1 (dev runs
# with no agent under test). SCOPE_WAIT_TIMEOUT overrides the default 5
# minutes; in healthy runs the first iteration finds scopes immediately
# so the happy path pays effectively nothing.
AGENT_COUNT=$(kubectl get deployment -n team1 -l rossoctl.io/type=agent \
    -o name 2>/dev/null | wc -l | tr -d ' ')

if [ "$AGENT_COUNT" -gt 0 ]; then
    log_info "Waiting up to ${SCOPE_WAIT_TIMEOUT:-300}s for agent-*-aud scopes to appear in realm $REALM..."
    MAX_WAIT="${SCOPE_WAIT_TIMEOUT:-300}"
    SLEEP=5
    ELAPSED=0
    SCOPE_SEEN=false
    while [ $ELAPSED -lt $MAX_WAIT ]; do
        refresh_admin_token
        SCOPES_JSON=$(kc_api GET \
            "$KEYCLOAK_URL/admin/realms/$REALM/default-default-client-scopes")
        if echo "$SCOPES_JSON" | python3 -c "
import sys, json
scopes = json.load(sys.stdin)
if any(s['name'].startswith('agent-') and s['name'].endswith('-aud') for s in scopes):
    sys.exit(0)
sys.exit(1)
" 2>/dev/null; then
            log_info "  Agent audience scope(s) detected after ${ELAPSED}s"
            SCOPE_SEEN=true
            break
        fi
        sleep $SLEEP
        ELAPSED=$((ELAPSED + SLEEP))
    done
    if [ "$SCOPE_SEEN" = "false" ]; then
        log_warn "No agent-*-aud scopes appeared after ${MAX_WAIT}s; tests will likely fail with 401 (rossoctl-operator ClientRegistrationReconciler may be stuck)"
        log_warn "Dumping diagnostics so the next maintainer can debug the reconciler without a second CI run:"
        dump_scope_timeout_diagnostics
    fi
fi

log_info "Attaching agent audience scopes to $E2E_CLIENT_ID..."
refresh_admin_token
REALM_DEFAULT_SCOPES=$(kc_api GET "$KEYCLOAK_URL/admin/realms/$REALM/default-default-client-scopes")
AGENT_SCOPE_IDS=$(echo "$REALM_DEFAULT_SCOPES" | python3 -c "
import sys, json
scopes = json.load(sys.stdin)
for s in scopes:
    if s['name'].startswith('agent-') and s['name'].endswith('-aud'):
        print(s['id'], s['name'])
" 2>/dev/null || echo "")

if [ -n "$AGENT_SCOPE_IDS" ]; then
    while IFS=' ' read -r scope_id scope_name; do
        kc_api PUT "$KEYCLOAK_URL/admin/realms/$REALM/clients/$CLIENT_INTERNAL_ID/default-client-scopes/$scope_id" >/dev/null
        log_info "  Added scope '$scope_name' to $E2E_CLIENT_ID"
    done <<< "$AGENT_SCOPE_IDS"
else
    log_info "  No agent audience scopes found (agents may not be deployed yet)"
fi

# ============================================================================
# 5. Update rossoctl-test-user secret with verified credentials
# ============================================================================

log_info "Updating rossoctl-test-user secret with verified credentials..."
kubectl create secret generic rossoctl-test-user \
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
        echo "ROSSOCTL_TEST_USER=$TEST_USER"
        echo "ROSSOCTL_TEST_PASSWORD=$TEST_PASS"
        echo "ROSSOCTL_E2E_CLIENT_ID=$E2E_CLIENT_ID"
        echo "ROSSOCTL_E2E_CLIENT_SECRET=$E2E_CLIENT_SECRET"
    } >> "$GITHUB_ENV"
else
    export ROSSOCTL_TEST_USER="$TEST_USER"
    export ROSSOCTL_TEST_PASSWORD="$TEST_PASS"
    export ROSSOCTL_E2E_CLIENT_ID="$E2E_CLIENT_ID"
    export ROSSOCTL_E2E_CLIENT_SECRET="$E2E_CLIENT_SECRET"
fi

log_success "Test credentials ready"
log_info "  Test user: $TEST_USER (realm: $REALM)"
log_info "  Service account: $E2E_CLIENT_ID"
log_info "  Run ./.github/scripts/local-setup/show-services.sh to see login credentials"
