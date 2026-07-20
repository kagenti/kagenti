#!/usr/bin/env bash
# Configure FGAP (Fine-Grained Authorization Policy) token exchange
# for all agent/tool clients in the test realm.
#
# For each rossoctl-registered client:
#   1. Enables authorizationServicesEnabled
#   2. Creates token-exchange scope permission
#   3. Enables management permissions
#   4. Creates FGAP policy linking all clients
#
# Also updates authproxy-routes so authbridge triggers token exchange.
set -euo pipefail
source "$(dirname "$0")/lib.sh"

log_step "60" "Configure FGAP token exchange"

KC_URL=$(get_keycloak_url)
TOKEN=$(get_admin_token "$KC_URL")
if [[ -z "$TOKEN" ]]; then
  log_error "Could not get admin token"; exit 1
fi

# --- Discover clients ---
log_info "Discovering clients in realm $TX_REALM"
ALL_CLIENTS=$(kc_api GET "$KC_URL" "/$TX_REALM/clients?max=100" "$TOKEN" | \
  jq "[.[] | select(.clientId | startswith(\"${TX_NAMESPACE}/\") or contains(\"/ns/${TX_NAMESPACE}/sa/\") or . == \"${TX_CLIENT_ID}\")]")
CLIENT_COUNT=$(echo "$ALL_CLIENTS" | jq length)
log_info "Found $CLIENT_COUNT clients"

if [[ "$CLIENT_COUNT" -eq 0 ]]; then
  log_error "No rossoctl clients found. Has the operator registered them?"
  exit 1
fi

ALL_UUIDS_JSON=$(echo "$ALL_CLIENTS" | jq '[.[].id]')
REALM_MGMT_UUID=$(kc_api GET "$KC_URL" "/$TX_REALM/clients?clientId=realm-management" "$TOKEN" | jq -r '.[0].id')

# --- Make tx-e2e-app confidential ---
TX_APP_UUID=$(echo "$ALL_CLIENTS" | jq -r ".[] | select(.clientId == \"$TX_CLIENT_ID\") | .id")
if [[ -n "$TX_APP_UUID" ]]; then
  TOKEN=$(get_admin_token "$KC_URL")
  IS_PUBLIC=$(kc_api GET "$KC_URL" "/$TX_REALM/clients/$TX_APP_UUID" "$TOKEN" | jq -r '.publicClient')
  if [[ "$IS_PUBLIC" == "true" ]]; then
    log_info "Making $TX_CLIENT_ID confidential (required for token exchange)"
    CLIENT_JSON=$(kc_api GET "$KC_URL" "/$TX_REALM/clients/$TX_APP_UUID" "$TOKEN")
    UPDATED=$(echo "$CLIENT_JSON" | jq '.publicClient = false | .serviceAccountsEnabled = true')
    TOKEN=$(get_admin_token "$KC_URL")
    kc_api PUT "$KC_URL" "/$TX_REALM/clients/$TX_APP_UUID" "$TOKEN" -d "$UPDATED" > /dev/null
  fi
fi

# --- First pass: enable FGAP on all clients ---
for ROW in $(echo "$ALL_CLIENTS" | jq -r '.[] | @base64'); do
  CLIENT_UUID=$(echo "$ROW" | base64 -d | jq -r '.id')
  SHORT_NAME=$(echo "$ROW" | base64 -d | jq -r '.clientId' | sed "s|${TX_NAMESPACE}/||" | sed 's|.*/sa/||')

  TOKEN=$(get_admin_token "$KC_URL")
  log_info "Enabling FGAP on $SHORT_NAME"

  kc_api PUT "$KC_URL" "/$TX_REALM/clients/$CLIENT_UUID" "$TOKEN" \
    -d '{"authorizationServicesEnabled": true}' > /dev/null 2>&1 || true

  EXISTING=$(kc_api GET "$KC_URL" "/$TX_REALM/clients/$CLIENT_UUID/authz/resource-server/permission?name=token-exchange-permission" "$TOKEN" 2>/dev/null | jq -r '.[0].id // empty' 2>/dev/null || true)
  if [[ -z "$EXISTING" ]]; then
    kc_api POST "$KC_URL" "/$TX_REALM/clients/$CLIENT_UUID/authz/resource-server/permission/scope" "$TOKEN" \
      -d '{"name":"token-exchange-permission","type":"scope","logic":"POSITIVE","decisionStrategy":"UNANIMOUS","resourceType":"token-exchange"}' > /dev/null 2>&1 || true
  fi

  kc_api PUT "$KC_URL" "/$TX_REALM/clients/$CLIENT_UUID/management/permissions" "$TOKEN" \
    -d '{"enabled": true}' > /dev/null 2>&1 || true

  kc_api PUT "$KC_URL" "/$TX_REALM/clients/$CLIENT_UUID" "$TOKEN" \
    -d '{"attributes":{"standard.token.exchange.enabled":"false"}}' > /dev/null 2>&1 || true
done

# Get token-exchange scope
TOKEN=$(get_admin_token "$KC_URL")
TX_SCOPE_ID=$(kc_api GET "$KC_URL" "/$TX_REALM/clients/$REALM_MGMT_UUID/authz/resource-server/scope?name=token-exchange" "$TOKEN" 2>/dev/null | jq -r '.[0].id // empty' 2>/dev/null || true)
if [[ -z "$TX_SCOPE_ID" ]]; then
  log_warn "token-exchange scope not found on realm-management"
fi

# --- Second pass: create FGAP policies ---
for ROW in $(echo "$ALL_CLIENTS" | jq -r '.[] | @base64'); do
  CLIENT_UUID=$(echo "$ROW" | base64 -d | jq -r '.id')
  SHORT_NAME=$(echo "$ROW" | base64 -d | jq -r '.clientId' | sed "s|${TX_NAMESPACE}/||" | sed 's|.*/sa/||')

  TOKEN=$(get_admin_token "$KC_URL")
  log_info "Creating FGAP policy for $SHORT_NAME"

  MGMT_INFO=$(kc_api GET "$KC_URL" "/$TX_REALM/clients/$CLIENT_UUID/management/permissions" "$TOKEN")
  TX_PERM_ID=$(echo "$MGMT_INFO" | jq -r '.scopePermissions["token-exchange"] // empty')
  RESOURCE_ID=$(echo "$MGMT_INFO" | jq -r '.resource // empty')

  if [[ -z "$TX_PERM_ID" || -z "$TX_SCOPE_ID" ]]; then
    log_warn "Skipping $SHORT_NAME — missing permission or scope ID"
    continue
  fi

  POLICY_NAME="all-agents-exchange-${SHORT_NAME}"
  EXISTING_POLICY=$(kc_api GET "$KC_URL" "/$TX_REALM/clients/$REALM_MGMT_UUID/authz/resource-server/policy?name=$POLICY_NAME" "$TOKEN" 2>/dev/null | jq -r '.[0].id // empty' 2>/dev/null || true)

  if [[ -z "$EXISTING_POLICY" ]]; then
    POLICY_ID=$(kc_api POST "$KC_URL" "/$TX_REALM/clients/$REALM_MGMT_UUID/authz/resource-server/policy/client" "$TOKEN" \
      -d "{\"name\":\"$POLICY_NAME\",\"type\":\"client\",\"logic\":\"POSITIVE\",\"decisionStrategy\":\"UNANIMOUS\",\"clients\":$ALL_UUIDS_JSON}" | jq -r '.id // empty')
  else
    POLICY_ID="$EXISTING_POLICY"
    kc_api PUT "$KC_URL" "/$TX_REALM/clients/$REALM_MGMT_UUID/authz/resource-server/policy/client/$POLICY_ID" "$TOKEN" \
      -d "{\"id\":\"$POLICY_ID\",\"name\":\"$POLICY_NAME\",\"type\":\"client\",\"logic\":\"POSITIVE\",\"decisionStrategy\":\"UNANIMOUS\",\"clients\":$ALL_UUIDS_JSON}" > /dev/null 2>&1 || true
  fi

  if [[ -n "$POLICY_ID" ]]; then
    kc_api PUT "$KC_URL" "/$TX_REALM/clients/$REALM_MGMT_UUID/authz/resource-server/permission/scope/$TX_PERM_ID" "$TOKEN" \
      -d "{\"id\":\"$TX_PERM_ID\",\"name\":\"token-exchange.permission.client.$CLIENT_UUID\",\"type\":\"scope\",\"logic\":\"POSITIVE\",\"decisionStrategy\":\"UNANIMOUS\",\"resources\":[\"$RESOURCE_ID\"],\"scopes\":[\"$TX_SCOPE_ID\"],\"policies\":[\"$POLICY_ID\"]}" > /dev/null 2>&1 || true
  fi
done

# --- Update authproxy-routes ---
log_info "Updating authproxy-routes for token exchange"
cat <<EOF | kubectl apply -n "$TX_NAMESPACE" -f -
apiVersion: v1
kind: ConfigMap
metadata:
  name: authproxy-routes
data:
  routes.yaml: |
    - host: "tx-e2e-tool"
      target_audience: "${TX_CLIENT_ID}"
      token_scopes: "openid"
EOF

# --- Restart agents ---
log_info "Restarting workloads to pick up FGAP routes..."
kubectl rollout restart deployment -n "$TX_NAMESPACE" 2>/dev/null || true

log_success "FGAP token exchange configured in realm '$TX_REALM'"
