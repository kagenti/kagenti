#!/usr/bin/env bash
# Enable SPIFFE identity for workloads in the test namespace.
#
# Switches from client-secret to federated-jwt authentication,
# ensuring each workload has a dedicated ServiceAccount and
# re-registering Keycloak clients with SPIFFE IDs.
set -euo pipefail
source "$(dirname "$0")/lib.sh"

log_step "56" "Enable SPIFFE identity in $TX_NAMESPACE"

KC_URL=$(get_keycloak_url)
PLATFORM="${PLATFORM:-$(detect_platform)}"

if [[ "$PLATFORM" == "ocp" ]]; then
  KC_HOST="${KEYCLOAK_HOST:-$(kubectl get route -n "$KC_NAMESPACE" -o jsonpath='{.items[0].spec.host}' 2>/dev/null)}"
else
  KC_HOST="${KEYCLOAK_HOST:-keycloak.localtest.me}"
fi

# --- Detect SPIFFE IDP ---
TOKEN=$(get_admin_token "$KC_URL")
AUTH_TYPE="client-secret"
if [[ -n "$TOKEN" ]]; then
  HAS_SPIFFE_IDP=$(curl -sk "$KC_URL/admin/realms/$TX_REALM/identity-provider/instances" \
    -H "Authorization: Bearer $TOKEN" 2>/dev/null | jq -r '.[] | select(.providerId == "spiffe") | .alias' 2>/dev/null || true)
  if [[ -n "$HAS_SPIFFE_IDP" ]]; then
    AUTH_TYPE="federated-jwt"
    log_info "SPIFFE IDP '$HAS_SPIFFE_IDP' found — using federated-jwt"
  else
    log_warn "No SPIFFE IDP found — falling back to client-secret"
  fi
fi

# --- Update authbridge-config ---
log_info "Updating authbridge-config (SPIRE_ENABLED=true, CLIENT_AUTH_TYPE=$AUTH_TYPE)"
kubectl patch configmap authbridge-config -n "$TX_NAMESPACE" --type=merge \
  -p "{\"data\":{\"SPIRE_ENABLED\":\"true\",\"CLIENT_AUTH_TYPE\":\"$AUTH_TYPE\"}}"

# --- Update authbridge-runtime-config ---
log_info "Updating authbridge-runtime-config (identity type + jwt_svid_path)"
RUNTIME_YAML=$(kubectl get configmap authbridge-runtime-config -n "$TX_NAMESPACE" -o jsonpath='{.data.config\.yaml}')
UPDATED_YAML=$(echo "$RUNTIME_YAML" | python3 -c "
import sys
lines = []
has_svid = False
for line in sys.stdin:
    stripped = line.rstrip()
    if 'jwt_svid_path' in stripped:
        has_svid = True
    lines.append(stripped)
result = []
for line in lines:
    if 'type: \"client-secret\"' in line:
        result.append(line.replace('client-secret', 'spiffe'))
    else:
        result.append(line)
    if 'client_secret_file' in line and not has_svid:
        indent = len(line) - len(line.lstrip())
        result.append(' ' * indent + 'jwt_svid_path: \"/opt/jwt_svid.token\"')
print('\n'.join(result))
")
kubectl patch configmap authbridge-runtime-config -n "$TX_NAMESPACE" --type=merge \
  -p "{\"data\":{\"config.yaml\":$(echo "$UPDATED_YAML" | jq -Rs .)}}"

# --- Fix JWT audience to match Keycloak issuer ---
log_info "Checking Keycloak issuer for JWT audience"
KC_ISSUER=$(curl -sk "${KC_URL}/realms/${TX_REALM}/.well-known/openid-configuration" 2>/dev/null | jq -r '.issuer // empty')
if [[ -n "$KC_ISSUER" ]]; then
  CURRENT_AUD=$(kubectl get configmap spiffe-helper-config -n "$TX_NAMESPACE" -o jsonpath='{.data.helper\.conf}' 2>/dev/null | grep -o 'jwt_audience="[^"]*"' | sed 's/jwt_audience="//' | sed 's/"//')
  if [[ -n "$CURRENT_AUD" && "$KC_ISSUER" != "$CURRENT_AUD" ]]; then
    log_info "Updating JWT audience: $CURRENT_AUD -> $KC_ISSUER"
    HELPER_CONF=$(kubectl get configmap spiffe-helper-config -n "$TX_NAMESPACE" -o jsonpath='{.data.helper\.conf}')
    UPDATED_CONF=$(echo "$HELPER_CONF" | sed "s|jwt_audience=\"${CURRENT_AUD}\"|jwt_audience=\"${KC_ISSUER}\"|")
    kubectl patch configmap spiffe-helper-config -n "$TX_NAMESPACE" --type=merge \
      -p "{\"data\":{\"helper.conf\":$(echo "$UPDATED_CONF" | jq -Rs .)}}"
  fi
fi

# --- Ensure dedicated ServiceAccounts ---
log_info "Ensuring dedicated ServiceAccounts"
WORKLOADS=$(kubectl get deploy -n "$TX_NAMESPACE" -l 'kagenti.io/type in (agent,tool)' -o jsonpath='{range .items[*]}{.metadata.name}{"\n"}{end}' 2>/dev/null || true)
if [[ -z "$WORKLOADS" ]]; then
  WORKLOADS=$(kubectl get deploy -n "$TX_NAMESPACE" -o jsonpath='{range .items[*]}{.metadata.name}{"\n"}{end}' 2>/dev/null | grep -E "tx-e2e-" || true)
fi

for DEPLOY in $WORKLOADS; do
  CURRENT_SA=$(kubectl get deploy "$DEPLOY" -n "$TX_NAMESPACE" -o jsonpath='{.spec.template.spec.serviceAccountName}' 2>/dev/null || true)
  if [[ -z "$CURRENT_SA" || "$CURRENT_SA" == "default" ]]; then
    kubectl create sa "$DEPLOY" -n "$TX_NAMESPACE" 2>/dev/null || true
    kubectl patch deploy "$DEPLOY" -n "$TX_NAMESPACE" --type=json \
      -p="[{\"op\":\"add\",\"path\":\"/spec/template/spec/serviceAccountName\",\"value\":\"${DEPLOY}\"}]"
    log_info "  $DEPLOY: created SA and updated deployment"
  fi
done

# --- Delete old credentials for re-registration ---
log_info "Deleting old Keycloak clients for re-registration"
if [[ -n "$TOKEN" ]]; then
  TOKEN=$(get_admin_token "$KC_URL")
  CLIENT_UUIDS=$(curl -sk "$KC_URL/admin/realms/$TX_REALM/clients?max=100" \
    -H "Authorization: Bearer $TOKEN" 2>/dev/null | \
    jq -r ".[] | select(.clientId | contains(\"/ns/${TX_NAMESPACE}/sa/\") or startswith(\"${TX_NAMESPACE}/\")) | .id" 2>/dev/null || true)
  for UUID in $CLIENT_UUIDS; do
    TOKEN=$(get_admin_token "$KC_URL")
    curl -sk -X DELETE "$KC_URL/admin/realms/$TX_REALM/clients/$UUID" \
      -H "Authorization: Bearer $TOKEN" -o /dev/null 2>/dev/null || true
  done
fi

log_info "Deleting old credential secrets"
for SECRET in $(kubectl get secrets -n "$TX_NAMESPACE" -o name 2>/dev/null | grep kagenti-keycloak-client-credentials); do
  kubectl delete "$SECRET" -n "$TX_NAMESPACE" 2>/dev/null || true
done

# --- Restart workloads ---
log_info "Restarting workloads to pick up SPIFFE identity"
for DEPLOY in $WORKLOADS; do
  kubectl rollout restart "deploy/$DEPLOY" -n "$TX_NAMESPACE" 2>/dev/null || true
done

log_success "SPIFFE identity enabled in $TX_NAMESPACE"
