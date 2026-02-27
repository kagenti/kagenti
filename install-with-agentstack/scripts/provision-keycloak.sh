#!/bin/bash
set -euo pipefail

# Provision Keycloak for AgentStack via the Admin REST API.
# Creates: realm, roles, clients (server/ui/cli), audience scopes, and a seed user.

KEYCLOAK_URL="${KEYCLOAK_URL:-http://keycloak.localtest.me:8080}"
KC_ADMIN_USER="${KC_ADMIN_USER:-admin}"
KC_ADMIN_PASSWORD="${KC_ADMIN_PASSWORD:-admin}"

# Predictable client secrets
SERVER_CLIENT_SECRET="${SERVER_CLIENT_SECRET:-agentstack-server-secret}"
UI_CLIENT_SECRET="${UI_CLIENT_SECRET:-agentstack-ui-secret}"

# Audience URLs
UI_URL="${UI_URL:-http://agentstack.localtest.me:8080}"
API_URL="${API_URL:-http://agentstack-api.localtest.me:8080}"

# Seed user
SEED_USERNAME="${SEED_USERNAME:-admin}"
SEED_PASSWORD="${SEED_PASSWORD:-admin}"
SEED_EMAIL="${SEED_EMAIL:-admin@beeai.dev}"
SEED_FIRST_NAME="${SEED_FIRST_NAME:-Admin}"
SEED_LAST_NAME="${SEED_LAST_NAME:-User}"

REALM="agentstack"

# ─── Helpers ────────────────────────────────────────────────────────────────────

kc_api() {
  # Usage: kc_api METHOD path [curl-args...]
  local method="$1" path="$2"; shift 2
  curl -sf -X "$method" \
    -H "Authorization: Bearer $ACCESS_TOKEN" \
    -H "Content-Type: application/json" \
    "${KEYCLOAK_URL}${path}" "$@"
}

kc_api_status() {
  # Same as kc_api but returns HTTP status code
  local method="$1" path="$2"; shift 2
  curl -s -o /dev/null -w "%{http_code}" -X "$method" \
    -H "Authorization: Bearer $ACCESS_TOKEN" \
    -H "Content-Type: application/json" \
    "${KEYCLOAK_URL}${path}" "$@"
}

get_client_id() {
  # Get the internal UUID of a client by clientId
  kc_api GET "/admin/realms/${REALM}/clients?clientId=$1" | python3 -c "import sys,json; clients=json.load(sys.stdin); print(clients[0]['id'] if clients else '')"
}

get_client_scope_id() {
  # Get the internal UUID of a client scope by name
  kc_api GET "/admin/realms/${REALM}/client-scopes" | python3 -c "import sys,json; scopes=json.load(sys.stdin); matches=[s['id'] for s in scopes if s['name']=='$1']; print(matches[0] if matches else '')"
}

# ─── Wait for Keycloak ──────────────────────────────────────────────────────────

echo "⏳ Waiting for Keycloak at ${KEYCLOAK_URL}..."
until curl -sf "${KEYCLOAK_URL}/realms/master" > /dev/null 2>&1; do
  echo "  Not ready... retrying in 3s"
  sleep 3
done
echo "✅ Keycloak is reachable."

# ─── Get Admin Token ────────────────────────────────────────────────────────────

echo "🔑 Obtaining admin access token..."
TOKEN_RESPONSE=$(curl -s -X POST \
  "${KEYCLOAK_URL}/realms/master/protocol/openid-connect/token" \
  -d "grant_type=password&client_id=admin-cli&username=${KC_ADMIN_USER}&password=${KC_ADMIN_PASSWORD}")

ACCESS_TOKEN=$(echo "$TOKEN_RESPONSE" | python3 -c "import sys,json; data=json.load(sys.stdin); print(data.get('access_token',''))" 2>/dev/null || true)

if [ -z "$ACCESS_TOKEN" ]; then
  echo "❌ Failed to obtain admin token. Response:"
  echo "$TOKEN_RESPONSE"
  exit 1
fi

# ─── Create Realm ───────────────────────────────────────────────────────────────

echo "🏠 Creating realm '${REALM}'..."
STATUS=$(kc_api_status GET "/admin/realms/${REALM}")
if [ "$STATUS" = "200" ]; then
  echo "  Realm already exists."
else
  kc_api POST "/admin/realms" -d "{
    \"realm\": \"${REALM}\",
    \"enabled\": true
  }"
  echo "  Realm created."
fi

# ─── Create Roles ───────────────────────────────────────────────────────────────

echo "👤 Creating roles..."
for ROLE_NAME in agentstack-admin agentstack-developer; do
  STATUS=$(kc_api_status GET "/admin/realms/${REALM}/roles/${ROLE_NAME}")
  if [ "$STATUS" = "200" ]; then
    echo "  Role '${ROLE_NAME}' exists."
  else
    kc_api POST "/admin/realms/${REALM}/roles" -d "{\"name\": \"${ROLE_NAME}\"}"
    echo "  Role '${ROLE_NAME}' created."
  fi
done

# ─── Create/Update Server Client ────────────────────────────────────────────────

echo "🖥️  Configuring server client 'agentstack-server'..."
CID=$(get_client_id "agentstack-server")
if [ -z "$CID" ]; then
  kc_api POST "/admin/realms/${REALM}/clients" -d "{
    \"clientId\": \"agentstack-server\",
    \"enabled\": true,
    \"clientAuthenticatorType\": \"client-secret\",
    \"secret\": \"${SERVER_CLIENT_SECRET}\",
    \"serviceAccountsEnabled\": true,
    \"directAccessGrantsEnabled\": true,
    \"standardFlowEnabled\": false,
    \"publicClient\": false
  }"
  echo "  Server client created."
else
  kc_api PUT "/admin/realms/${REALM}/clients/${CID}" -d "{
    \"id\": \"${CID}\",
    \"clientId\": \"agentstack-server\",
    \"secret\": \"${SERVER_CLIENT_SECRET}\",
    \"enabled\": true
  }"
  echo "  Server client updated."
fi

# ─── Create/Update UI Client ────────────────────────────────────────────────────

echo "🌐 Configuring UI client 'agentstack-ui'..."
CID=$(get_client_id "agentstack-ui")
if [ -z "$CID" ]; then
  kc_api POST "/admin/realms/${REALM}/clients" -d "{
    \"clientId\": \"agentstack-ui\",
    \"enabled\": true,
    \"clientAuthenticatorType\": \"client-secret\",
    \"secret\": \"${UI_CLIENT_SECRET}\",
    \"serviceAccountsEnabled\": false,
    \"directAccessGrantsEnabled\": true,
    \"standardFlowEnabled\": true,
    \"publicClient\": false,
    \"redirectUris\": [\"*\", \"${UI_URL}/*\"],
    \"webOrigins\": [\"*\"]
  }"
  echo "  UI client created."
else
  kc_api PUT "/admin/realms/${REALM}/clients/${CID}" -d "{
    \"id\": \"${CID}\",
    \"clientId\": \"agentstack-ui\",
    \"secret\": \"${UI_CLIENT_SECRET}\",
    \"enabled\": true,
    \"redirectUris\": [\"*\", \"${UI_URL}/*\"]
  }"
  echo "  UI client updated."
fi

# ─── Create/Update CLI Client ───────────────────────────────────────────────────

echo "💻 Configuring CLI client 'agentstack-cli'..."
CID=$(get_client_id "agentstack-cli")
if [ -z "$CID" ]; then
  kc_api POST "/admin/realms/${REALM}/clients" -d "{
    \"clientId\": \"agentstack-cli\",
    \"enabled\": true,
    \"publicClient\": true,
    \"standardFlowEnabled\": true,
    \"directAccessGrantsEnabled\": true,
    \"redirectUris\": [\"http://localhost:9001/callback\"],
    \"webOrigins\": [\"+\"]
  }"
  echo "  CLI client created."
else
  kc_api PUT "/admin/realms/${REALM}/clients/${CID}" -d "{
    \"id\": \"${CID}\",
    \"clientId\": \"agentstack-cli\",
    \"enabled\": true,
    \"publicClient\": true,
    \"redirectUris\": [\"http://localhost:9001/callback\"]
  }"
  echo "  CLI client updated."
fi

# ─── Configure Audience Scopes & Mappers ────────────────────────────────────────

echo "🎯 Configuring audience scopes..."

declare -a AUDIENCES=(
  "agentstack-ui|agentstack-ui-audience|${UI_URL}"
  "agentstack-cli|agentstack-cli-audience|${API_URL}"
  "agentstack-server|agentstack-server-audience|${API_URL}"
)

for AUDIENCE_MAPPING in "${AUDIENCES[@]}"; do
  IFS='|' read -r CLIENT_ID_NAME SCOPE_NAME AUDIENCE_URL <<< "$AUDIENCE_MAPPING"

  echo "  Scope '${SCOPE_NAME}' for client '${CLIENT_ID_NAME}' → ${AUDIENCE_URL}"

  # Create client scope if not exists
  SCOPE_ID=$(get_client_scope_id "$SCOPE_NAME")
  if [ -z "$SCOPE_ID" ]; then
    kc_api POST "/admin/realms/${REALM}/client-scopes" -d "{
      \"name\": \"${SCOPE_NAME}\",
      \"protocol\": \"openid-connect\"
    }"
    SCOPE_ID=$(get_client_scope_id "$SCOPE_NAME")
    echo "    Scope created (${SCOPE_ID})."
  else
    echo "    Scope exists (${SCOPE_ID})."
  fi

  # Check if audience mapper exists
  MAPPERS=$(kc_api GET "/admin/realms/${REALM}/client-scopes/${SCOPE_ID}/protocol-mappers/models")
  MAPPER_ID=$(echo "$MAPPERS" | python3 -c "import sys,json; mappers=json.load(sys.stdin); matches=[m['id'] for m in mappers if m['name']=='audience-mapper']; print(matches[0] if matches else '')" 2>/dev/null || true)

  if [ -z "$MAPPER_ID" ]; then
    kc_api POST "/admin/realms/${REALM}/client-scopes/${SCOPE_ID}/protocol-mappers/models" -d "{
      \"name\": \"audience-mapper\",
      \"protocol\": \"openid-connect\",
      \"protocolMapper\": \"oidc-audience-mapper\",
      \"config\": {
        \"included.custom.audience\": \"${AUDIENCE_URL}\",
        \"id.token.claim\": \"false\",
        \"access.token.claim\": \"true\"
      }
    }"
    echo "    Mapper created."
  else
    kc_api PUT "/admin/realms/${REALM}/client-scopes/${SCOPE_ID}/protocol-mappers/models/${MAPPER_ID}" -d "{
      \"id\": \"${MAPPER_ID}\",
      \"name\": \"audience-mapper\",
      \"protocol\": \"openid-connect\",
      \"protocolMapper\": \"oidc-audience-mapper\",
      \"config\": {
        \"included.custom.audience\": \"${AUDIENCE_URL}\",
        \"id.token.claim\": \"false\",
        \"access.token.claim\": \"true\"
      }
    }"
    echo "    Mapper updated."
  fi

  # Assign scope to client as default
  CID=$(get_client_id "$CLIENT_ID_NAME")
  if [ -n "$CID" ]; then
    kc_api PUT "/admin/realms/${REALM}/clients/${CID}/default-client-scopes/${SCOPE_ID}" || true
    echo "    Scope assigned to client."
  else
    echo "    ⚠️  Client '${CLIENT_ID_NAME}' not found, skipping scope assignment."
  fi
done

# ─── Seed User ──────────────────────────────────────────────────────────────────

echo "🌱 Seeding user '${SEED_USERNAME}'..."
USERS=$(kc_api GET "/admin/realms/${REALM}/users?username=${SEED_USERNAME}&exact=true")
USER_ID=$(echo "$USERS" | python3 -c "import sys,json; users=json.load(sys.stdin); print(users[0]['id'] if users else '')" 2>/dev/null || true)

if [ -z "$USER_ID" ]; then
  kc_api POST "/admin/realms/${REALM}/users" -d "{
    \"username\": \"${SEED_USERNAME}\",
    \"enabled\": true,
    \"email\": \"${SEED_EMAIL}\",
    \"firstName\": \"${SEED_FIRST_NAME}\",
    \"lastName\": \"${SEED_LAST_NAME}\",
    \"emailVerified\": true
  }"
  USER_ID=$(kc_api GET "/admin/realms/${REALM}/users?username=${SEED_USERNAME}&exact=true" | python3 -c "import sys,json; print(json.load(sys.stdin)[0]['id'])")
  echo "  User created (${USER_ID})."
else
  kc_api PUT "/admin/realms/${REALM}/users/${USER_ID}" -d "{
    \"id\": \"${USER_ID}\",
    \"username\": \"${SEED_USERNAME}\",
    \"enabled\": true,
    \"email\": \"${SEED_EMAIL}\",
    \"firstName\": \"${SEED_FIRST_NAME}\",
    \"lastName\": \"${SEED_LAST_NAME}\",
    \"emailVerified\": true
  }"
  echo "  User updated (${USER_ID})."
fi

# Set password
kc_api PUT "/admin/realms/${REALM}/users/${USER_ID}/reset-password" -d "{
  \"type\": \"password\",
  \"value\": \"${SEED_PASSWORD}\",
  \"temporary\": false
}"
echo "  Password set."

# Assign roles
for ROLE_NAME in agentstack-admin agentstack-developer; do
  ROLE_JSON=$(kc_api GET "/admin/realms/${REALM}/roles/${ROLE_NAME}")
  ROLE_ID=$(echo "$ROLE_JSON" | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])" 2>/dev/null || true)
  if [ -n "$ROLE_ID" ]; then
    kc_api POST "/admin/realms/${REALM}/users/${USER_ID}/role-mappings/realm" -d "[${ROLE_JSON}]" || true
    echo "  Role '${ROLE_NAME}' assigned."
  else
    echo "  ⚠️  Role '${ROLE_NAME}' not found."
  fi
done

echo ""
echo "✅ Keycloak provisioning complete!"
echo ""
echo "  Realm:          ${REALM}"
echo "  Issuer URL:     ${KEYCLOAK_URL}/realms/${REALM}"
echo "  Server Client:  agentstack-server (secret: ${SERVER_CLIENT_SECRET})"
echo "  UI Client:      agentstack-ui     (secret: ${UI_CLIENT_SECRET})"
echo "  CLI Client:     agentstack-cli    (public)"
echo "  Seed User:      ${SEED_USERNAME}  (password: ${SEED_PASSWORD})"
