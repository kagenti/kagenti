#!/usr/bin/env bash
# Shared library for token-exchange E2E scripts.
# Source this file: source "$(dirname "$0")/lib.sh"

set -euo pipefail

# Inherit from CI lib if available, otherwise define locally
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"

if [[ -f "$SCRIPT_DIR/../lib/logging.sh" ]]; then
  # shellcheck source=/dev/null
  source "$SCRIPT_DIR/../lib/logging.sh"
else
  log_info()    { echo "$(date +'%H:%M:%S') [INFO]  $*"; }
  log_success() { echo "$(date +'%H:%M:%S') [OK]    $*"; }
  log_error()   { echo "$(date +'%H:%M:%S') [ERROR] $*" >&2; }
  log_warn()    { echo "$(date +'%H:%M:%S') [WARN]  $*"; }
  log_step()    { echo ""; echo "=== [$1] $2 ==="; }
fi

# Defaults
export TX_NAMESPACE="${TX_NAMESPACE:-tx-e2e}"
export TX_REALM="${TX_REALM:-tx-e2e}"
export TX_CLIENT_ID="${TX_CLIENT_ID:-tx-e2e-app}"
export KC_NAMESPACE="${KC_NAMESPACE:-keycloak}"

# Detect platform (kind vs ocp)
detect_platform() {
  if kubectl get nodes -o jsonpath='{.items[0].metadata.labels.node\.kubernetes\.io/instance-type}' 2>/dev/null | grep -q .; then
    echo "ocp"
  elif kubectl get nodes -o jsonpath='{.items[0].spec.providerID}' 2>/dev/null | grep -q kind; then
    echo "kind"
  else
    echo "unknown"
  fi
}

# Get Keycloak URL (internal or external)
get_keycloak_url() {
  local platform
  platform=$(detect_platform)
  if [[ "$platform" == "ocp" ]]; then
    local host
    host=$(kubectl get route -n "$KC_NAMESPACE" -o jsonpath='{.items[0].spec.host}' 2>/dev/null || true)
    if [[ -n "$host" ]]; then
      echo "https://${host}"
      return
    fi
  fi
  # Kind or fallback: use port-forward URL
  echo "${KEYCLOAK_URL:-http://keycloak-service.${KC_NAMESPACE}.svc:8080}"
}

# Resolve the Keycloak CR external hostname.
# On OCP, derive it from the ingress domain via `oc`. On Kind (or any cluster
# without `oc`), fall back to an in-cluster hostname so the install does not
# abort under `set -e` when `oc` is absent (the Keycloak CR uses strict: false).
resolve_kc_host() {
  if [[ -n "${KEYCLOAK_HOST:-}" ]]; then
    echo "$KEYCLOAK_HOST"
    return
  fi
  local domain=""
  if command -v oc &>/dev/null; then
    domain=$(oc get ingresses.config/cluster -o jsonpath='{.spec.domain}' 2>/dev/null || true)
  fi
  if [[ -n "$domain" ]]; then
    echo "keycloak-keycloak.${domain}"
  else
    echo "keycloak-service.${KC_NAMESPACE}.svc.cluster.local"
  fi
}

# Get Keycloak admin credentials
get_kc_admin_creds() {
  local user pass
  user=$(kubectl get secret keycloak-initial-admin -n "$KC_NAMESPACE" -o go-template='{{.data.username | base64decode}}' 2>/dev/null || echo "admin")
  pass=$(kubectl get secret keycloak-initial-admin -n "$KC_NAMESPACE" -o go-template='{{.data.password | base64decode}}' 2>/dev/null || echo "admin")
  echo "$user:$pass"
}

# Get admin token from Keycloak
get_admin_token() {
  local kc_url="$1"
  local creds
  creds=$(get_kc_admin_creds)
  local user="${creds%%:*}"
  local pass="${creds#*:}"
  curl -sk "$kc_url/realms/master/protocol/openid-connect/token" \
    -d "grant_type=password" -d "client_id=admin-cli" \
    -d "username=$user" -d "password=$pass" | jq -r '.access_token // empty'
}

# Keycloak admin API helper
kc_api() {
  local method="$1" kc_url="$2" path="$3" token="$4"
  shift 4
  curl -sk -X "$method" "${kc_url}/admin/realms${path}" \
    -H "Authorization: Bearer $token" \
    -H "Content-Type: application/json" \
    "$@"
}

# Wait for deployment rollout
wait_rollout() {
  local name="$1" ns="$2" timeout="${3:-300s}"
  log_info "Waiting for deployment/$name in $ns (timeout: $timeout)"
  kubectl rollout status "deployment/$name" -n "$ns" --timeout="$timeout"
}

# Decode JWT payload
decode_jwt() {
  local payload
  payload=$(echo "$1" | cut -d'.' -f2 | tr '_-' '/+')
  local pad=$(( 4 - ${#payload} % 4 ))
  [ "$pad" -lt 4 ] && payload="${payload}$(printf '%0.s=' $(seq 1 "$pad"))"
  echo "$payload" | base64 -d 2>/dev/null | jq '.'
}
