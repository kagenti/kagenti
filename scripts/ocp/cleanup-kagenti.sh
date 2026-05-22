#!/usr/bin/env bash
# ============================================================================
# KAGENTI PLATFORM CLEANUP
# ============================================================================
# Removes the Kagenti platform: all 3 Helm charts, stuck namespaces,
# cert-manager namespace, and shared trust ClusterIssuer CRs.
#
# Uses parallel deletion where possible for faster cleanup.
#
# Usage:
#   ./scripts/ocp/cleanup-kagenti.sh            # Interactive (prompts for confirmation)
#   ./scripts/ocp/cleanup-kagenti.sh --yes      # Skip confirmation prompt
#
# This script:
#   1. Uninstalls Helm releases (parallel): kagenti, mcp-gateway, kagenti-deps
#   2. Deletes namespaces (parallel, waits for clean deletion)
#   3. Force-deletes operator namespaces (openshift-builds, ZTWIM, mcp-system)
#   4. Deletes shared trust ClusterIssuers and Certificates
#   5. Removes cert-manager OLM operator + namespace (must be last)
# ============================================================================

set -euo pipefail

AUTO_YES=false

while [[ $# -gt 0 ]]; do
  case "$1" in
    --yes|-y) AUTO_YES=true; shift ;;
    -h|--help)
      echo "Usage: $0 [OPTIONS]"
      echo ""
      echo "Options:"
      echo "  --yes, -y    Skip confirmation prompt"
      echo "  -h, --help   Show this help"
      exit 0
      ;;
    *) echo "Unknown option: $1"; exit 1 ;;
  esac
done

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log_info()    { echo -e "${BLUE}→${NC} $1"; }
log_success() { echo -e "${GREEN}✓${NC} $1"; }
log_warn()    { echo -e "${YELLOW}⚠${NC} $1"; }
log_error()   { echo -e "${RED}✗${NC} $1"; }

# Check for kubectl/oc
if command -v oc &>/dev/null; then
  KUBECTL=oc
elif command -v kubectl &>/dev/null; then
  KUBECTL=kubectl
else
  log_error "Neither oc nor kubectl found in PATH"
  exit 1
fi

# Check cluster access
if ! $KUBECTL cluster-info &>/dev/null; then
  log_error "Cannot connect to cluster. Run 'oc login' first."
  exit 1
fi
log_success "Connected to cluster"

# Check python3
if ! command -v python3 &>/dev/null; then
  log_error "python3 not found in PATH. Install python3 >= 3.8"
  exit 1
fi
log_success "python3 found: $(python3 --version)"

echo ""
echo "============================================"
echo "  Kagenti Platform Cleanup"
echo "============================================"
echo ""
echo "This will remove:"
echo "  - Helm releases: kagenti, mcp-gateway, kagenti-deps"
echo "  - Namespaces: kagenti-system, mcp-system, gateway-system, keycloak, istio-cni,"
echo "    istio-system, istio-ztunnel, openshift-builds,"
echo "    zero-trust-workload-identity-manager, cert-manager-operator, cert-manager,"
echo "    team1, team2"
echo "  - ClusterIssuers: istio-mesh-root-selfsigned, istio-mesh-ca"
echo "  - Certificates: istio-mesh-root-ca, istio-cacerts-openshift-gateway"
echo ""

if ! $AUTO_YES; then
  read -p "Continue? (y/N): " -r
  if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    log_info "Cleanup cancelled"
    exit 0
  fi
  echo ""
fi

START_SECONDS=$SECONDS

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Wait for namespace to be fully deleted (no finalizer stripping).
_delete_ns() {
  local ns="$1"
  if ! $KUBECTL get namespace "$ns" &>/dev/null; then
    log_info "  $ns — not found, skipping"
    return 0
  fi
  log_info "  $ns — deleting..."
  $KUBECTL delete namespace "$ns" --timeout=120s 2>/dev/null && \
    log_success "  $ns deleted" || \
    log_error "  $ns deletion timed out — may need manual cleanup"
}

# Force-delete: strip finalizers if stuck after 10s.
_force_delete_ns() {
  local ns="$1"
  if ! $KUBECTL get namespace "$ns" &>/dev/null; then
    log_info "  $ns — not found, skipping"
    return 0
  fi
  if $KUBECTL delete namespace "$ns" --timeout=20s 2>/dev/null; then
    log_success "  $ns deleted"
    return 0
  fi
  log_warn "  $ns stuck — stripping finalizers..."
  $KUBECTL get namespace "$ns" -o json 2>/dev/null \
    | python3 -c "import sys,json; d=json.load(sys.stdin); d['spec']['finalizers']=[]; json.dump(d,sys.stdout)" \
    | $KUBECTL replace --raw "/api/v1/namespaces/$ns/finalize" -f - >/dev/null 2>&1 || true
  sleep 3
  if $KUBECTL get namespace "$ns" &>/dev/null; then
    log_error "  $ns still exists — may need manual cleanup"
  else
    log_success "  $ns deleted (finalizers stripped)"
  fi
}

_uninstall_release() {
  local release="$1" ns="$2"
  if helm status "$release" -n "$ns" &>/dev/null; then
    helm uninstall "$release" -n "$ns" --no-hooks 2>/dev/null && \
      log_success "  $release uninstalled" || \
      log_warn "  $release uninstall returned non-zero"
  else
    log_info "  $release — not found, skipping"
  fi
}

# ---------------------------------------------------------------------------
# Step 1: Uninstall Helm releases (parallel)
# ---------------------------------------------------------------------------
log_info "Step 1: Uninstalling Helm releases..."

_uninstall_release kagenti     kagenti-system &
_uninstall_release mcp-gateway mcp-system     &
_uninstall_release kagenti-deps kagenti-system &
wait
echo ""

# ---------------------------------------------------------------------------
# Step 2: Delete namespaces (parallel, wait for clean deletion)
# ---------------------------------------------------------------------------
log_info "Step 2: Deleting namespaces..."

_delete_ns kagenti-system &
_delete_ns keycloak       &
_delete_ns istio-cni      &
_delete_ns istio-system   &
_delete_ns istio-ztunnel  &
wait
echo ""

# ---------------------------------------------------------------------------
# Step 3: Force-delete operator namespaces (commonly stuck on finalizers)
# ---------------------------------------------------------------------------
log_info "Step 3: Cleaning up operator namespaces..."

_force_delete_ns openshift-builds &
PID_OB=$!

$KUBECTL delete configmaps --all -n zero-trust-workload-identity-manager --timeout=10s 2>/dev/null || true
_force_delete_ns zero-trust-workload-identity-manager &
PID_ZT=$!

_force_delete_ns mcp-system &
PID_MS=$!

_force_delete_ns gateway-system &
PID_GS=$!

_force_delete_ns team1 &
PID_T1=$!

_force_delete_ns team2 &
PID_T2=$!

wait $PID_OB $PID_ZT $PID_MS $PID_GS $PID_T1 $PID_T2
echo ""

# ---------------------------------------------------------------------------
# Step 4: Delete shared trust ClusterIssuers + Certificates
# ---------------------------------------------------------------------------
log_info "Step 4: Deleting shared trust resources..."

for ci in istio-mesh-root-selfsigned istio-mesh-ca; do
  if $KUBECTL get clusterissuer "$ci" &>/dev/null; then
    $KUBECTL delete clusterissuer "$ci" 2>/dev/null && \
      log_success "  ClusterIssuer $ci deleted" || \
      log_warn "  Failed to delete ClusterIssuer $ci"
  else
    log_info "  ClusterIssuer $ci — not found, skipping"
  fi
done

for cert_ns in "istio-mesh-root-ca:cert-manager" "istio-cacerts-openshift-gateway:openshift-ingress"; do
  cert="${cert_ns%%:*}"
  ns="${cert_ns##*:}"
  if $KUBECTL get certificate "$cert" -n "$ns" &>/dev/null; then
    $KUBECTL delete certificate "$cert" -n "$ns" 2>/dev/null && \
      log_success "  Certificate $ns/$cert deleted" || \
      log_warn "  Failed to delete Certificate $ns/$cert"
  else
    log_info "  Certificate $ns/$cert — not found, skipping"
  fi
done
echo ""

# ---------------------------------------------------------------------------
# Step 5: Remove cert-manager OLM operator + namespaces (must be last)
# ---------------------------------------------------------------------------
log_info "Step 5: Removing cert-manager operator..."

$KUBECTL delete subscription --all -n cert-manager-operator --timeout=30s 2>/dev/null && \
  log_success "  cert-manager Subscription deleted" || \
  log_info "  No Subscription found in cert-manager-operator"

CSV=$($KUBECTL get csv -n cert-manager-operator -o name 2>/dev/null | head -1)
if [ -n "$CSV" ]; then
  $KUBECTL delete "$CSV" -n cert-manager-operator --timeout=30s 2>/dev/null && \
    log_success "  cert-manager CSV deleted" || \
    log_warn "  Failed to delete cert-manager CSV"
fi

_delete_ns cert-manager-operator &
_delete_ns cert-manager          &
wait
echo ""

ELAPSED=$(( SECONDS - START_SECONDS ))
MINS=$(( ELAPSED / 60 ))
SECS=$(( ELAPSED % 60 ))

echo "============================================"
echo "  Kagenti Cleanup Complete  (${MINS}m ${SECS}s)"
echo "============================================"
echo ""
echo "To redeploy, run: ./scripts/ocp/setup-kagenti.sh"
echo ""
