#!/usr/bin/env bash
# ============================================================================
# OPENSHELL CLI CONFIGURATION
# ============================================================================
# Registers a deployed OpenShell gateway with the local CLI using
# `openshell gateway add`, including OIDC authentication parameters.
#
# Usage:
#   scripts/openshell/configure-cli.sh <team>
#   scripts/openshell/configure-cli.sh team1
#   scripts/openshell/configure-cli.sh team1 --dry-run
#   scripts/openshell/configure-cli.sh --help
#
# Prerequisites: openshell CLI installed, kubectl, deploy-shared.sh and
#                deploy-tenant.sh already run
# ============================================================================

set -euo pipefail

# ── Defaults ────────────────────────────────────────────────────────────────
KEYCLOAK_NS="${KEYCLOAK_NS:-keycloak}"
KIND_DOMAIN="localtest.me"
GATEWAY_PORT=9443
OIDC_CLIENT_ID="openshell-cli"
DRY_RUN=false
TENANT=""

# ── Colors & logging ────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'; NC='\033[0m'
log_info()    { echo -e "${BLUE}→${NC} $1"; }
log_success() { echo -e "${GREEN}✓${NC} $1"; }
log_warn()    { echo -e "${YELLOW}⚠${NC} $1"; }
log_error()   { echo -e "${RED}✗${NC} $1"; }

usage() {
  cat <<EOF
Usage: $(basename "$0") <team> [OPTIONS]

Register a deployed OpenShell gateway with the local CLI, including
OIDC authentication. Dev-only, not needed in CI.

Arguments:
  team                  Tenant name (e.g., team1, team2)

Options:
  --help               Show this help message
  --dry-run            Print actions without executing
                       (note: platform detection still requires a live cluster context)

After running this script:
  openshell gateway login   # authenticate with Keycloak
  openshell status          # verify gateway connection
EOF
  exit 0
}

# ── Argument parsing ────────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
  case "$1" in
    --help)        usage ;;
    --dry-run)     DRY_RUN=true; shift ;;
    -*)
      log_error "Unknown option: $1"
      usage
      ;;
    *)
      if [[ -z "$TENANT" ]]; then
        TENANT="$1"; shift
      else
        log_error "Unexpected argument: $1"
        usage
      fi
      ;;
  esac
done

if [[ -z "$TENANT" ]]; then
  log_error "Tenant name required. Usage: $(basename "$0") <team>"
  exit 1
fi

# ── Preflight ────────────────────────────────────────────────────────────────
if ! command -v openshell &>/dev/null; then
  log_error "openshell CLI not found in PATH"
  log_error "Build from https://github.com/kagenti/OpenShell (mvp branch):"
  log_error "  cargo build --release -p openshell-cli && cp target/release/openshell ~/.local/bin/"
  exit 1
fi

# ── Platform detection ───────────────────────────────────────────────────────
is_openshift() {
  kubectl get clusterversion &>/dev/null
}

get_ocp_base_domain() {
  kubectl get ingresses.config.openshift.io cluster \
    -o jsonpath='{.spec.domain}' 2>/dev/null
}

# ── Derived values ───────────────────────────────────────────────────────────
GATEWAY_NAME="openshell-${TENANT}"

if is_openshift; then
  BASE_DOMAIN=$(get_ocp_base_domain)
  if [[ -z "$BASE_DOMAIN" ]]; then
    log_error "Could not detect OCP base domain (kubectl get ingresses.config.openshift.io cluster)"
    exit 1
  fi
  GATEWAY_ENDPOINT="https://openshell-${TENANT}.${BASE_DOMAIN}"
  # OCP Keycloak uses the Route hostname
  KC_HOST=$(kubectl get route keycloak -n "$KEYCLOAK_NS" -o jsonpath='{.spec.host}' 2>/dev/null || echo "")
  OIDC_ISSUER="https://${KC_HOST}/realms/openshell"
else
  GATEWAY_ENDPOINT="https://openshell-${TENANT}.${KIND_DOMAIN}:${GATEWAY_PORT}"
  OIDC_ISSUER="http://keycloak.${KIND_DOMAIN}:8080/realms/openshell"
fi

echo ""
echo "╔════════════════════════════════════════════════════════════════╗"
echo "║  OpenShell CLI Configuration                                 ║"
echo "╚════════════════════════════════════════════════════════════════╝"
echo ""
echo "  Tenant:          $TENANT"
echo "  Gateway name:    $GATEWAY_NAME"
echo "  Gateway URL:     $GATEWAY_ENDPOINT"
echo "  OIDC issuer:     $OIDC_ISSUER"
echo "  OIDC audience:   $TENANT"
echo "  Dry run:         $DRY_RUN"
echo ""

# ── Register gateway with CLI ────────────────────────────────────────────────
log_info "Registering gateway with openshell CLI"

ADD_ARGS=(
  gateway add "$GATEWAY_ENDPOINT"
  --name "$GATEWAY_NAME"
  --oidc-issuer "$OIDC_ISSUER"
  --oidc-audience "$TENANT"
  --oidc-client-id "$OIDC_CLIENT_ID"
)

if $DRY_RUN; then
  echo "  [dry-run] openshell ${ADD_ARGS[*]}"
else
  if openshell gateway info --gateway "$GATEWAY_NAME" &>/dev/null; then
    log_warn "Gateway $GATEWAY_NAME already exists — removing to re-register"
    openshell gateway destroy --name "$GATEWAY_NAME" 2>/dev/null || true
  fi
  openshell "${ADD_ARGS[@]}"
  log_success "Gateway registered"
fi
echo ""

# ── Extract mTLS certificates ────────────────────────────────────────────────
# The CLI requires the CA cert (for server verification) and client cert/key
# (for mTLS handshake) in the gateway's mtls directory.
MTLS_DIR="${HOME}/.config/openshell/gateways/${GATEWAY_NAME}/mtls"

log_info "Extracting mTLS certificates from cluster"

if $DRY_RUN; then
  echo "  [dry-run] kubectl get secret openshell-server-tls -n $TENANT → $MTLS_DIR/ca.crt"
  echo "  [dry-run] kubectl get secret openshell-client-tls -n $TENANT → $MTLS_DIR/tls.{crt,key}"
else
  mkdir -p "$MTLS_DIR"
  kubectl get secret openshell-server-tls -n "$TENANT" \
    -o jsonpath='{.data.ca\.crt}' | base64 -d > "$MTLS_DIR/ca.crt"
  kubectl get secret openshell-client-tls -n "$TENANT" \
    -o jsonpath='{.data.tls\.crt}' | base64 -d > "$MTLS_DIR/tls.crt"
  kubectl get secret openshell-client-tls -n "$TENANT" \
    -o jsonpath='{.data.tls\.key}' | base64 -d > "$MTLS_DIR/tls.key"
  chmod 600 "$MTLS_DIR"/{ca.crt,tls.crt,tls.key}
  log_success "mTLS certificates extracted to $MTLS_DIR"
fi
echo ""

# ── Summary ───────────────────────────────────────────────────────────────────
echo "╔════════════════════════════════════════════════════════════════╗"
echo "║  Done — CLI configured for tenant: $TENANT"
echo "╚════════════════════════════════════════════════════════════════╝"
echo ""
echo "  Next steps:"
echo "    openshell gateway login   # authenticate with Keycloak"
echo "    openshell status          # verify gateway connection"
echo ""
