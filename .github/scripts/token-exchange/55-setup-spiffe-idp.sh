#!/usr/bin/env bash
# Setup SPIFFE Identity Provider in Keycloak.
#
# Creates the spiffe-type IDP so agents can authenticate with JWT-SVIDs
# instead of client secrets. Adapted from redbank-demo-2/scripts/setup-keycloak-spiffe.sh.
set -euo pipefail
source "$(dirname "$0")/lib.sh"

log_step "55" "Setup SPIFFE Identity Provider in Keycloak"

PLATFORM="${PLATFORM:-$(detect_platform)}"
KC_URL=$(get_keycloak_url)
IDP_ALIAS="${SPIFFE_IDP_ALIAS:-spire-spiffe}"

# Detect SPIRE namespace
SPIRE_NS=$(kubectl get ns zero-trust-workload-identity-manager -o name 2>/dev/null | sed 's|namespace/||' || true)
if [[ -z "$SPIRE_NS" ]]; then
  SPIRE_NS=$(kubectl get ns spire-server -o name 2>/dev/null | sed 's|namespace/||' || true)
fi
if [[ -z "$SPIRE_NS" ]]; then
  SPIRE_NS="spire-mgmt"
fi

# Detect trust domain from operator
TRUST_DOMAIN=$(kubectl get deploy kagenti-controller-manager -n kagenti-system -o json 2>/dev/null | \
  jq -r '.spec.template.spec.containers[0].args[]? | select(startswith("--spire-trust-domain=")) | split("=")[1]' 2>/dev/null || true)
if [[ -z "$TRUST_DOMAIN" ]]; then
  if [[ "$PLATFORM" == "ocp" ]]; then
    TRUST_DOMAIN=$(kubectl get route -n "$KC_NAMESPACE" -o jsonpath='{.items[0].spec.host}' 2>/dev/null | sed 's/^keycloak-keycloak\.//')
  else
    TRUST_DOMAIN="localtest.me"
  fi
  log_warn "Could not read trust domain from operator, using: $TRUST_DOMAIN"
fi

BUNDLE_ENDPOINT="https://spire-spiffe-oidc-discovery-provider.${SPIRE_NS}.svc.cluster.local/keys"

log_info "Realm:           $TX_REALM"
log_info "IDP Alias:       $IDP_ALIAS"
log_info "Trust Domain:    $TRUST_DOMAIN"
log_info "Bundle Endpoint: $BUNDLE_ENDPOINT"

# --- OCP: Configure SPIRE CA truststore + proxy headers ---
if [[ "$PLATFORM" == "ocp" ]]; then
  log_info "Creating SPIRE CA secret for Keycloak truststore"
  if kubectl get configmap openshift-service-ca.crt -n "$KC_NAMESPACE" -o jsonpath='{.data.service-ca\.crt}' > /tmp/service-ca.crt 2>/dev/null && [[ -s /tmp/service-ca.crt ]]; then
    kubectl create secret generic spire-oidc-ca -n "$KC_NAMESPACE" --from-file=ca.crt=/tmp/service-ca.crt --dry-run=client -o yaml | kubectl apply -f - > /dev/null 2>&1
  fi

  kubectl patch keycloak keycloak -n "$KC_NAMESPACE" --type=merge \
    -p '{"spec":{"proxy":{"headers":"xforwarded"},"features":{"enabled":["preview","token-exchange","admin-fine-grained-authz:v1","client-auth-federated:v1","spiffe:v1"]},"truststores":{"spire-oidc":{"secret":{"name":"spire-oidc-ca"}}}}}' 2>/dev/null || true

  # Wait for Keycloak if restart needed
  KC_READY=$(kubectl get pod keycloak-0 -n "$KC_NAMESPACE" -o jsonpath='{.status.containerStatuses[0].ready}' 2>/dev/null || true)
  if [[ "$KC_READY" != "true" ]]; then
    kubectl rollout status statefulset/keycloak -n "$KC_NAMESPACE" --timeout=5m 2>/dev/null || true
  fi
fi

# --- Enable CREATE_ONLY_MODE on ZTWIM operator ---
ZTWIM_SUB=$(kubectl get subscription -n "${SPIRE_NS}" -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || true)
if [[ -n "$ZTWIM_SUB" ]]; then
  HAS_COM=$(kubectl get subscription "$ZTWIM_SUB" -n "${SPIRE_NS}" -o json 2>/dev/null | jq -r '.spec.config.env[]? | select(.name=="CREATE_ONLY_MODE") | .value' 2>/dev/null || true)
  if [[ "$HAS_COM" != "true" ]]; then
    kubectl patch subscription "$ZTWIM_SUB" -n "${SPIRE_NS}" --type=merge \
      -p '{"spec":{"config":{"env":[{"name":"CREATE_ONLY_MODE","value":"true"}]}}}' 2>/dev/null || true
    log_info "CREATE_ONLY_MODE enabled on ZTWIM"
    sleep 15
  fi
fi

# --- Enable set_key_use on SPIRE OIDC discovery provider ---
OIDC_CONF=$(kubectl get configmap spire-spiffe-oidc-discovery-provider -n "${SPIRE_NS}" -o jsonpath='{.data.oidc-discovery-provider\.conf}' 2>/dev/null || true)
if [[ -n "$OIDC_CONF" ]]; then
  HAS_KEY_USE=$(echo "$OIDC_CONF" | jq '.set_key_use // false' 2>/dev/null || echo "false")
  if [[ "$HAS_KEY_USE" != "true" ]]; then
    PATCHED=$(echo "$OIDC_CONF" | jq '. + {"set_key_use": true}')
    kubectl patch configmap spire-spiffe-oidc-discovery-provider -n "${SPIRE_NS}" \
      --type=merge -p "{\"data\":{\"oidc-discovery-provider.conf\":$(echo "$PATCHED" | jq -Rs .)}}" 2>/dev/null || true
    OIDC_POD=$(kubectl get pods -n "${SPIRE_NS}" -o name 2>/dev/null | grep oidc | head -1 | sed 's|pod/||')
    if [[ -n "$OIDC_POD" ]]; then
      kubectl delete pod "$OIDC_POD" -n "${SPIRE_NS}" 2>/dev/null || true
      sleep 15
    fi
    log_info "set_key_use enabled on OIDC discovery provider"
  fi
fi

# --- Create/update SPIFFE Identity Provider ---
TOKEN=$(get_admin_token "$KC_URL")
if [[ -z "$TOKEN" ]]; then
  log_error "Could not get admin token — skipping IDP creation"
  exit 1
fi

EXISTING=$(curl -sk "$KC_URL/admin/realms/$TX_REALM/identity-provider/instances" \
  -H "Authorization: Bearer $TOKEN" 2>/dev/null | jq -r ".[] | select(.alias == \"$IDP_ALIAS\") | .alias" 2>/dev/null || true)

IDP_PAYLOAD="{
  \"alias\":\"$IDP_ALIAS\",
  \"providerId\":\"spiffe\",
  \"enabled\":true,
  \"hideOnLogin\":true,
  \"config\":{
    \"syncMode\":\"LEGACY\",
    \"allowCreate\":\"true\",
    \"bundleEndpoint\":\"$BUNDLE_ENDPOINT\",
    \"issuer\":\"spiffe://$TRUST_DOMAIN\",
    \"trustDomain\":\"spiffe://$TRUST_DOMAIN\",
    \"showInAccountConsole\":\"NEVER\"
  }
}"

TOKEN=$(get_admin_token "$KC_URL")
if [[ "$EXISTING" == "$IDP_ALIAS" ]]; then
  HTTP_CODE=$(curl -sk -X PUT "$KC_URL/admin/realms/$TX_REALM/identity-provider/instances/$IDP_ALIAS" \
    -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
    -d "$IDP_PAYLOAD" -o /dev/null -w "%{http_code}")
  log_info "Updated SPIFFE IDP (HTTP $HTTP_CODE)"
else
  HTTP_CODE=$(curl -sk -X POST "$KC_URL/admin/realms/$TX_REALM/identity-provider/instances" \
    -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
    -d "$IDP_PAYLOAD" -o /dev/null -w "%{http_code}")
  log_info "Created SPIFFE IDP (HTTP $HTTP_CODE)"
fi

# Enable management permissions on SPIFFE IDP
TOKEN=$(get_admin_token "$KC_URL")
curl -sk -X PUT "$KC_URL/admin/realms/$TX_REALM/identity-provider/instances/$IDP_ALIAS/management/permissions" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"enabled":true}' > /dev/null 2>&1 || true

# Update authbridge-config
kubectl patch configmap authbridge-config -n "$TX_NAMESPACE" --type=merge \
  -p "{\"data\":{\"SPIFFE_IDP_ALIAS\":\"$IDP_ALIAS\"}}" 2>/dev/null || true

log_success "SPIFFE Identity Provider '$IDP_ALIAS' configured in realm '$TX_REALM'"
