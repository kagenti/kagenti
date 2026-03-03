#!/usr/bin/env bash
#
# Create Test Users in Keycloak
#
# Creates dev-user and ns-admin test users in the master realm (or the realm
# where the kagenti OAuth client is registered). Idempotent — safe to run
# multiple times.
#
# Prerequisites:
#   - kubectl/oc access to the cluster
#   - Keycloak pod running in the keycloak namespace
#   - keycloak-initial-admin secret exists
#
# Usage:
#   # From the repository root:
#   ./kagenti/auth/create-test-users.sh
#
#   # With custom realm (default: master):
#   KEYCLOAK_REALM=demo ./kagenti/auth/create-test-users.sh
#
#   # With custom namespace:
#   KEYCLOAK_NAMESPACE=my-keycloak ./kagenti/auth/create-test-users.sh
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../../.github/scripts/lib/logging.sh" 2>/dev/null || {
    log_step() { echo "==> [$1] $2"; }
    log_info() { echo "  INFO: $*"; }
    log_success() { echo "  OK: $*"; }
    log_warn() { echo "  WARN: $*"; }
    log_error() { echo "  ERROR: $*"; }
}

log_step "D" "Create test users in Keycloak"

KC_NS="${KEYCLOAK_NAMESPACE:-keycloak}"
KC_POD="keycloak-0"
KCADM="/opt/keycloak/bin/kcadm.sh"
REALM="${KEYCLOAK_REALM:-master}"

# ── Step 1: Wait for Keycloak pod ─────────────────────────────────────────
log_info "Waiting for Keycloak pod to be ready..."
kubectl wait --for=condition=Ready pod/$KC_POD -n "$KC_NS" --timeout=120s

# ── Step 2: Login to Keycloak ─────────────────────────────────────────────
log_info "Reading credentials from keycloak-initial-admin secret..."
KC_USER=$(kubectl get secret keycloak-initial-admin -n "$KC_NS" \
    -o jsonpath='{.data.username}' 2>/dev/null | base64 -d 2>/dev/null || echo "")
KC_PASS=$(kubectl get secret keycloak-initial-admin -n "$KC_NS" \
    -o jsonpath='{.data.password}' 2>/dev/null | base64 -d 2>/dev/null || echo "")

if [ -z "$KC_USER" ] || [ -z "$KC_PASS" ]; then
    log_error "Could not read keycloak-initial-admin secret"
    exit 1
fi

log_info "Logging in as $KC_USER..."
kubectl exec -n "$KC_NS" "$KC_POD" -- bash -c \
    "$KCADM config credentials --server http://localhost:8080 --realm master \
     --user '$KC_USER' --password '$KC_PASS' --config /tmp/kc/kcadm.config" \
    >/dev/null 2>&1

# ── Step 3: Create test users ─────────────────────────────────────────────
create_user() {
    local username=$1
    local password=$2
    local email=$3
    local first=$4
    local last=$5

    log_info "Creating user: $username (realm: $REALM)"
    kubectl exec -n "$KC_NS" "$KC_POD" -- bash -c "
$KCADM create users --config /tmp/kc/kcadm.config -r $REALM \
    -s username=$username -s enabled=true -s emailVerified=true \
    -s email=$email -s firstName='$first' -s lastName='$last' \
    2>/dev/null && echo 'Created' || echo 'Exists'

$KCADM set-password --config /tmp/kc/kcadm.config -r $REALM \
    --username $username --new-password $password \
    2>/dev/null && echo 'Password set' || echo 'Password unchanged'
"
}

# Generate random passwords if not provided via env vars.
# If the kagenti-test-users secret already exists, reuse those passwords
# so repeated runs don't break existing sessions.
_existing_admin=$(kubectl get secret kagenti-test-users -n "$KC_NS" \
    -o jsonpath='{.data.admin-password}' 2>/dev/null | base64 -d 2>/dev/null || echo "")
_existing_dev=$(kubectl get secret kagenti-test-users -n "$KC_NS" \
    -o jsonpath='{.data.dev-user-password}' 2>/dev/null | base64 -d 2>/dev/null || echo "")
_existing_ns=$(kubectl get secret kagenti-test-users -n "$KC_NS" \
    -o jsonpath='{.data.ns-admin-password}' 2>/dev/null | base64 -d 2>/dev/null || echo "")

_rand() { LC_ALL=C tr -dc 'A-Za-z0-9' </dev/urandom | head -c 15; }

ADMIN_PASS="${ADMIN_PASSWORD:-${_existing_admin:-$(_rand)}}"
DEV_PASS="${DEV_USER_PASSWORD:-${_existing_dev:-$(_rand)}}"
NS_PASS="${NS_ADMIN_PASSWORD:-${_existing_ns:-$(_rand)}}"

create_user "admin"     "$ADMIN_PASS" "admin@kagenti.local"    "Admin"     "User"
create_user "dev-user"  "$DEV_PASS"   "dev-user@kagenti.local" "Dev"       "User"
create_user "ns-admin"  "$NS_PASS"    "ns-admin@kagenti.local" "Namespace" "Admin"

# ── Step 4: Store passwords in a secret for show-services.sh ──────────────
log_info "Storing test user passwords in kagenti-test-users secret..."
kubectl create secret generic kagenti-test-users -n "$KC_NS" \
    --from-literal=admin-password="$ADMIN_PASS" \
    --from-literal=dev-user-password="$DEV_PASS" \
    --from-literal=ns-admin-password="$NS_PASS" \
    --dry-run=client -o yaml | kubectl apply -f -
log_success "kagenti-test-users secret updated"

# ── Step 5: Summary ──────────────────────────────────────────────────────
log_success "Test users created in realm: $REALM"
echo ""
echo "  Users:"
echo "    admin     / $ADMIN_PASS   (admin)"
echo "    dev-user  / $DEV_PASS   (developer)"
echo "    ns-admin  / $NS_PASS   (namespace admin)"
echo ""
echo "  These users can log in to the Kagenti UI."
echo "  Run show-services.sh --reveal to see all credentials."
