#!/usr/bin/env bash
# ============================================================================
# OPENSHELL PER-TENANT CLEANUP
# ============================================================================
# Removes a single tenant's OpenShell resources deployed by deploy-tenant.sh.
#
# Usage:
#   scripts/openshell/cleanup-tenant.sh <team>
#   scripts/openshell/cleanup-tenant.sh team1
#   scripts/openshell/cleanup-tenant.sh team1 --delete-namespace
#   scripts/openshell/cleanup-tenant.sh team1 --dry-run
#   scripts/openshell/cleanup-tenant.sh --help
#
# Idempotent: safe to re-run if resources are already gone.
# ============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

# ── Defaults ────────────────────────────────────────────────────────────────
DRY_RUN=false
DELETE_NAMESPACE=false
HELM_RELEASE_PREFIX="openshell"

# ── Colors & logging ────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'; NC='\033[0m'
log_info()    { echo -e "${BLUE}→${NC} $1"; }
log_success() { echo -e "${GREEN}✓${NC} $1"; }
log_warn()    { echo -e "${YELLOW}⚠${NC} $1"; }
log_error()   { echo -e "${RED}✗${NC} $1"; }

run_cmd() {
  if $DRY_RUN; then echo "  [dry-run] $*"; else "$@"; fi
}

usage() {
  cat <<EOF
Usage: $(basename "$0") <team> [OPTIONS]

Remove a tenant's OpenShell resources (idempotent).

Arguments:
  team                  Tenant name (e.g., team1, team2)

Options:
  --help               Show this help message
  --dry-run            Print commands without executing
  --delete-namespace   Also delete the tenant namespace (DESTRUCTIVE)
EOF
  exit 0
}

# ── Argument parsing ────────────────────────────────────────────────────────
TENANT=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --help)             usage ;;
    --dry-run)          DRY_RUN=true; shift ;;
    --delete-namespace) DELETE_NAMESPACE=true; shift ;;
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
  log_error "Tenant name is required. Usage: $(basename "$0") <team> [OPTIONS]"
  exit 1
fi

# ── Helper: detect OpenShift ────────────────────────────────────────────────
is_openshift() {
  kubectl get clusterversion &>/dev/null
}

echo ""
echo "╔════════════════════════════════════════════════════════════════╗"
echo "║  OpenShell Tenant Cleanup: $TENANT"
echo "╚════════════════════════════════════════════════════════════════╝"
echo ""
echo "  Tenant:           $TENANT"
echo "  Delete namespace: $DELETE_NAMESPACE"
echo "  Dry run:          $DRY_RUN"
echo ""

# ============================================================================
# Step 1: Remove agent deployments and related resources
# ============================================================================
log_info "Step 1: Removing agent resources in namespace $TENANT..."

if kubectl get namespace "$TENANT" &>/dev/null; then
  # Delete agent deployments (label matches deploy-tenant.sh)
  AGENT_DEPLOYMENTS=$(kubectl get deployments -n "$TENANT" -l "rossoctl.io/type=agent" -o name 2>/dev/null || true)
  if [[ -n "$AGENT_DEPLOYMENTS" ]]; then
    for dep in $AGENT_DEPLOYMENTS; do
      log_info "  Deleting $dep"
      run_cmd kubectl delete "$dep" -n "$TENANT" --ignore-not-found
    done
  fi

  # Delete agent policy configmaps (named ${agent_name}-policy by deploy-tenant.sh)
  AGENT_DIR="$REPO_ROOT/deployments/openshell/agents"
  if [[ -d "$AGENT_DIR" ]]; then
    for agent_dir in "$AGENT_DIR"/*/; do
      agent_name=$(basename "$agent_dir")
      run_cmd kubectl delete configmap "${agent_name}-policy" -n "$TENANT" --ignore-not-found
    done
  fi

  # Delete skills configmap
  run_cmd kubectl delete configmap rossoctl-skills -n "$TENANT" --ignore-not-found

  # Delete openshell-supervisor ServiceAccount
  run_cmd kubectl delete serviceaccount openshell-supervisor -n "$TENANT" --ignore-not-found

  log_success "Agent resources cleaned up"
else
  log_warn "Namespace $TENANT does not exist, skipping agent cleanup"
fi

# ============================================================================
# Step 2: Remove OpenShift SCCs (if applicable)
# ============================================================================
if is_openshift; then
  log_info "Step 2: Removing OpenShift SCC bindings..."

  # Remove ClusterRoleBinding for sandbox SCC
  CRB_NAME="${HELM_RELEASE_PREFIX}-sandbox-scc-${TENANT}"
  if kubectl get clusterrolebinding "$CRB_NAME" &>/dev/null; then
    log_info "  Deleting clusterrolebinding/$CRB_NAME"
    run_cmd kubectl delete clusterrolebinding "$CRB_NAME" --ignore-not-found
  fi

  # Remove SCC policies granted during agent deployment
  # deploy-tenant.sh grants anyuid to openshell-gateway in openshell-system,
  # and privileged to openshell-supervisor in the tenant namespace
  run_cmd oc adm policy remove-scc-from-user anyuid \
    -z openshell-gateway -n openshell-system 2>/dev/null || true
  run_cmd oc adm policy remove-scc-from-user privileged \
    -z openshell-supervisor -n "$TENANT" 2>/dev/null || true

  log_success "OpenShift SCCs cleaned up"
else
  log_info "Step 2: Not OpenShift, skipping SCC cleanup"
fi

# ============================================================================
# Step 3: Remove non-Helm resources that deploy-tenant.sh applies directly
# ============================================================================
if kubectl get namespace "$TENANT" &>/dev/null; then
  # OpenShift trusted CA bundle ConfigMap (created via kubectl apply, not Helm)
  if is_openshift; then
    log_info "Step 3a: Removing openshell-trusted-ca ConfigMap..."
    run_cmd kubectl delete configmap openshell-trusted-ca -n "$TENANT" --ignore-not-found
  fi
fi

# ============================================================================
# Step 4: Helm uninstall
# ============================================================================
RELEASE_NAME="${HELM_RELEASE_PREFIX}-${TENANT}"
log_info "Step 4: Uninstalling Helm release $RELEASE_NAME..."

if helm status "$RELEASE_NAME" -n "$TENANT" &>/dev/null; then
  run_cmd helm uninstall "$RELEASE_NAME" -n "$TENANT" --wait
  log_success "Helm release $RELEASE_NAME uninstalled"
else
  log_warn "Helm release $RELEASE_NAME not found, skipping"
fi

# ============================================================================
# Step 5: Remove namespace labels
# ============================================================================
if kubectl get namespace "$TENANT" &>/dev/null; then
  log_info "Step 5: Removing namespace labels..."
  run_cmd kubectl label namespace "$TENANT" shared-gateway-access- --overwrite 2>/dev/null || true
  run_cmd kubectl label namespace "$TENANT" openshell.ai/tenant- --overwrite 2>/dev/null || true
  log_success "Namespace labels removed"
else
  log_warn "Step 5: Namespace $TENANT does not exist, skipping label removal"
fi

# ============================================================================
# Step 6: Delete namespace (optional)
# ============================================================================
if $DELETE_NAMESPACE; then
  if kubectl get namespace "$TENANT" &>/dev/null; then
    log_warn "Step 6: Deleting namespace $TENANT (this will remove ALL resources in it)..."
    run_cmd kubectl delete namespace "$TENANT" --wait=true --timeout=120s
    log_success "Namespace $TENANT deleted"
  else
    log_warn "Step 6: Namespace $TENANT already gone"
  fi
else
  log_info "Step 6: Skipping namespace deletion (use --delete-namespace to remove)"
fi

echo ""
log_success "Tenant cleanup complete for: $TENANT"
