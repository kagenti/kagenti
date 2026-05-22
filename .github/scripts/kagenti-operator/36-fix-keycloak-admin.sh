#!/usr/bin/env bash
#
# Fix Keycloak Admin After RHBK Operator Deploy
#
# The RHBK operator creates keycloak-initial-admin with temp-admin + random
# password. This script:
#   1. Reads the operator-generated credentials from the secret
#   2. Logs in with those credentials
#   3. Creates a permanent admin user with generated password (if not exists)
#   4. Creates the demo realm (if not exists)
#   5. Updates the keycloak-initial-admin secret to generated credentials
#
# Idempotent — safe to run multiple times.
#
# Usage:
#   ./.github/scripts/kagenti-operator/36-fix-keycloak-admin.sh
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../lib/logging.sh" 2>/dev/null || {
    log_step() { echo "==> [$1] $2"; }
    log_info() { echo "  INFO: $*"; }
    log_success() { echo "  OK: $*"; }
    log_warn() { echo "  WARN: $*"; }
    log_error() { echo "  ERROR: $*"; }
}

log_step "36" "Fix Keycloak Admin (RHBK operator workaround)"

KC_NS="${KEYCLOAK_NAMESPACE:-keycloak}"
KC_POD="keycloak-0"
KCADM="/opt/keycloak/bin/kcadm.sh"
DESIRED_USER="admin"
# Generate random password unless KEYCLOAK_ADMIN_PASSWORD is set
# The password is stored in the keycloak-initial-admin K8s secret
# and displayed by show-services.sh — NEVER hardcode admin/admin
DESIRED_PASS="${KEYCLOAK_ADMIN_PASSWORD:-$(openssl rand -base64 12 | tr -dc 'a-zA-Z0-9' | head -c 16)}"

# ── Step 1: Wait for Keycloak pod ────────────────────────────────────────────
log_info "Waiting for Keycloak pod to be ready..."
kubectl wait --for=condition=Ready pod/$KC_POD -n "$KC_NS" --timeout=120s

# ── Step 2: Read current credentials from secret ────────────────────────────
log_info "Reading current credentials from keycloak-initial-admin secret..."
CURRENT_USER=$(kubectl get secret keycloak-initial-admin -n "$KC_NS" \
    -o jsonpath='{.data.username}' 2>/dev/null | base64 -d 2>/dev/null || echo "")
CURRENT_PASS=$(kubectl get secret keycloak-initial-admin -n "$KC_NS" \
    -o jsonpath='{.data.password}' 2>/dev/null | base64 -d 2>/dev/null || echo "")

if [ -z "$CURRENT_USER" ] || [ -z "$CURRENT_PASS" ]; then
    log_error "Could not read keycloak-initial-admin secret"
    exit 1
fi
log_info "Current admin: $CURRENT_USER"

# ── Step 3: Try logging in ───────────────────────────────────────────────────
# Try desired credentials first (idempotent case), then current secret
LOGIN_OK=false
for TRY_USER in "$DESIRED_USER" "$CURRENT_USER"; do
    for TRY_PASS in "$DESIRED_PASS" "$CURRENT_PASS"; do
        if kubectl exec -n "$KC_NS" "$KC_POD" -- bash -c \
            "$KCADM config credentials --server http://localhost:8080 --realm master \
             --user '$TRY_USER' --password '$TRY_PASS' --config /tmp/kc/kcadm.config" \
            >/dev/null 2>&1; then
            log_info "Logged in as $TRY_USER"
            LOGIN_OK=true
            break 2
        fi
    done
done

if [ "$LOGIN_OK" != "true" ]; then
    log_error "Could not login to Keycloak with any known credentials"
    exit 1
fi

# ── Step 4: Create permanent admin user ──────────────────────────────────────
log_info "Ensuring permanent admin user exists..."
kubectl exec -n "$KC_NS" "$KC_POD" -- bash -c "
$KCADM create users --config /tmp/kc/kcadm.config -r master \
    -s username=$DESIRED_USER -s enabled=true 2>/dev/null && echo 'Created user' || echo 'User exists'

$KCADM set-password --config /tmp/kc/kcadm.config -r master \
    --username $DESIRED_USER --new-password $DESIRED_PASS 2>/dev/null && echo 'Password set'

# Grant admin role
ADMIN_ROLE_ID=\$($KCADM get roles --config /tmp/kc/kcadm.config -r master \
    -q name=admin --fields id --format csv --noquotes 2>/dev/null || echo '')
USER_ID=\$($KCADM get users --config /tmp/kc/kcadm.config -r master \
    -q username=$DESIRED_USER --fields id --format csv --noquotes 2>/dev/null || echo '')
if [ -n \"\$ADMIN_ROLE_ID\" ] && [ -n \"\$USER_ID\" ]; then
    $KCADM add-roles --config /tmp/kc/kcadm.config -r master \
        --username $DESIRED_USER --rolename admin 2>/dev/null && echo 'Admin role assigned' || echo 'Role already assigned'
fi
"
log_success "Permanent admin user ensured: $DESIRED_USER/$DESIRED_PASS"

# ── Step 5: Create demo realm ────────────────────────────────────────────────
log_info "Ensuring demo realm exists..."
kubectl exec -n "$KC_NS" "$KC_POD" -- bash -c "
$KCADM create realms --config /tmp/kc/kcadm.config \
    -s realm=demo -s enabled=true 2>/dev/null && echo 'Created demo realm' || echo 'Demo realm exists'
"
log_success "Demo realm ensured"

# ── Step 6: Update secret to known credentials ──────────────────────────────
if [ "$CURRENT_USER" != "$DESIRED_USER" ] || [ "$CURRENT_PASS" != "$DESIRED_PASS" ]; then
    log_info "Updating keycloak-initial-admin secret to $DESIRED_USER/$DESIRED_PASS..."
    kubectl patch secret keycloak-initial-admin -n "$KC_NS" --type merge \
        -p "{\"data\":{\"username\":\"$(echo -n $DESIRED_USER | base64)\",\"password\":\"$(echo -n $DESIRED_PASS | base64)\"}}"
    log_success "Secret updated"
else
    log_info "Secret already has correct credentials"
fi

log_success "Keycloak admin fix complete"
