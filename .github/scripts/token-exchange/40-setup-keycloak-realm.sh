#!/usr/bin/env bash
# Create Keycloak realm with test clients and users for token exchange E2E.
#
# Creates:
#   - Realm (TX_REALM, default: tx-e2e)
#   - Client (TX_CLIENT_ID, default: tx-e2e-app) — public, direct access grant
#   - Audience mapper on the client
#   - Admin role
#   - Users: alice (user), bob (admin)
set -euo pipefail
source "$(dirname "$0")/lib.sh"

log_step "40" "Setup Keycloak realm for token exchange E2E"

KC_URL=$(get_keycloak_url)
TOKEN=$(get_admin_token "$KC_URL")
if [[ -z "$TOKEN" ]]; then
  log_error "Could not get Keycloak admin token (URL: $KC_URL)"
  exit 1
fi
log_info "Admin token acquired (realm: $TX_REALM, client: $TX_CLIENT_ID)"

# --- Create realm ---
log_info "Creating realm '$TX_REALM'"
kc_api POST "$KC_URL" "" "$TOKEN" \
  -d "{\"realm\":\"$TX_REALM\",\"enabled\":true,\"registrationAllowed\":false}" 2>/dev/null || \
  log_info "Realm '$TX_REALM' already exists"

# --- Create client ---
log_info "Creating client '$TX_CLIENT_ID'"
kc_api POST "$KC_URL" "/$TX_REALM/clients" "$TOKEN" \
  -d "{
    \"clientId\":\"$TX_CLIENT_ID\",
    \"enabled\":true,
    \"publicClient\":true,
    \"directAccessGrantsEnabled\":true,
    \"standardFlowEnabled\":true,
    \"redirectUris\":[\"*\"],
    \"webOrigins\":[\"*\"],
    \"protocol\":\"openid-connect\"
  }" 2>/dev/null || log_info "Client '$TX_CLIENT_ID' already exists"

# --- Audience mapper ---
log_info "Adding audience mapper"
TOKEN=$(get_admin_token "$KC_URL")
CLIENT_UUID=$(kc_api GET "$KC_URL" "/$TX_REALM/clients?clientId=$TX_CLIENT_ID" "$TOKEN" | jq -r '.[0].id')
if [[ -n "$CLIENT_UUID" && "$CLIENT_UUID" != "null" ]]; then
  kc_api POST "$KC_URL" "/$TX_REALM/clients/$CLIENT_UUID/protocol-mappers/models" "$TOKEN" \
    -d "{
      \"name\":\"tx-e2e-audience\",
      \"protocol\":\"openid-connect\",
      \"protocolMapper\":\"oidc-audience-mapper\",
      \"config\":{
        \"included.custom.audience\":\"$TX_CLIENT_ID\",
        \"id.token.claim\":\"false\",
        \"access.token.claim\":\"true\"
      }
    }" 2>/dev/null || log_info "Audience mapper already exists"
fi

# --- Create roles ---
log_info "Creating realm role 'admin'"
TOKEN=$(get_admin_token "$KC_URL")
kc_api POST "$KC_URL" "/$TX_REALM/roles" "$TOKEN" \
  -d '{"name":"admin","description":"Full access for e2e testing"}' 2>/dev/null || \
  log_info "Role 'admin' already exists"

# --- Create users ---
create_user() {
  local username="$1" email="$2" password="$3" first="$4" last="$5"
  log_info "Creating user '$username'"
  TOKEN=$(get_admin_token "$KC_URL")
  kc_api POST "$KC_URL" "/$TX_REALM/users" "$TOKEN" \
    -d "{
      \"username\":\"$username\",
      \"email\":\"$email\",
      \"emailVerified\":true,
      \"enabled\":true,
      \"firstName\":\"$first\",
      \"lastName\":\"$last\",
      \"credentials\":[{\"type\":\"password\",\"value\":\"$password\",\"temporary\":false}]
    }" 2>/dev/null || log_info "User '$username' already exists"
}

create_user "alice" "alice@tx-e2e.test" "alice123" "Alice" "User"
create_user "bob"   "bob@tx-e2e.test"   "bob123"   "Bob"   "Admin"

# --- Assign admin role to bob ---
log_info "Assigning 'admin' role to bob"
TOKEN=$(get_admin_token "$KC_URL")
BOB_ID=$(kc_api GET "$KC_URL" "/$TX_REALM/users?username=bob&exact=true" "$TOKEN" | jq -r '.[0].id')
ADMIN_ROLE=$(kc_api GET "$KC_URL" "/$TX_REALM/roles/admin" "$TOKEN")
if [[ -n "$BOB_ID" && "$BOB_ID" != "null" ]]; then
  kc_api POST "$KC_URL" "/$TX_REALM/users/$BOB_ID/role-mappings/realm" "$TOKEN" \
    -d "[$ADMIN_ROLE]" 2>/dev/null || log_info "Role already assigned"
fi

# --- Verify user tokens ---
log_info "Verifying user tokens..."
ALICE_TOKEN=$(curl -sk "$KC_URL/realms/$TX_REALM/protocol/openid-connect/token" \
  -d "grant_type=password" -d "client_id=$TX_CLIENT_ID" \
  -d "username=alice" -d "password=alice123" | jq -r '.access_token // empty')
if [[ -n "$ALICE_TOKEN" ]]; then
  log_success "Token for alice acquired"
else
  log_warn "Could not get token for alice"
fi

log_success "Keycloak realm '$TX_REALM' configured"
