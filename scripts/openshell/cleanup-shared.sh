#!/usr/bin/env bash
# ============================================================================
# OPENSHELL SHARED INFRASTRUCTURE CLEANUP
# ============================================================================
# Removes cluster-wide shared infrastructure deployed by deploy-shared.sh:
#   1. rossoctl-backend + PostgreSQL sessions DB
#   2. LiteLLM model proxy
#   3. Keycloak realm (openshell)
#   4. cert-manager CA chain (ClusterIssuers + CA Certificate)
#   5. Shared TLS passthrough Gateway (Kind only)
#   6. Revert Istio alpha Gateway API env var
#   7. Gateway API experimental CRDs (Kind only)
#   8. agent-sandbox-controller
#
# Idempotent: safe to re-run if resources are already gone.
#
# Usage:
#   scripts/openshell/cleanup-shared.sh                  # Remove everything
#   scripts/openshell/cleanup-shared.sh --skip-keycloak  # Keep Keycloak realm
#   scripts/openshell/cleanup-shared.sh --dry-run        # Print commands only
#   scripts/openshell/cleanup-shared.sh --help           # Show usage
#
# Prerequisites: kubectl, helm (for status checks)
# ============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

# ── Versions (keep in sync with deploy-shared.sh) ─────────────────────────
AGENT_SANDBOX_VERSION="v0.4.6"
GATEWAY_API_VERSION="v1.4.0"

# ── Defaults ────────────────────────────────────────────────────────────────
KEYCLOAK_NS="${KEYCLOAK_NS:-keycloak}"
KEYCLOAK_POD="keycloak-0"
KCADM="/opt/keycloak/bin/kcadm.sh"
KC_CONFIG="/tmp/kc/kcadm.config"
BACKEND_NS="${BACKEND_NS:-team1}"

STEP_SANDBOX=true
STEP_GATEWAY_API=true
STEP_TLS=true
STEP_KEYCLOAK=true
STEP_LITELLM=true
STEP_BACKEND=true
STEP_ISTIO=true
DELETE_DATA=false
DRY_RUN=false
CONFIRM=false

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
Usage: $(basename "$0") [OPTIONS]

Remove OpenShell shared infrastructure (idempotent).

Options:
  --help              Show this help message
  --skip-sandbox      Skip agent-sandbox-controller removal
  --skip-gateway-api  Skip experimental Gateway API CRD removal
  --skip-tls          Skip cert-manager CA chain removal
  --skip-keycloak     Skip Keycloak realm removal
  --skip-litellm      Skip LiteLLM proxy removal
  --skip-backend      Skip rossoctl-backend + PostgreSQL removal
  --skip-istio        Skip Istio env var revert
  --delete-data       Also delete PostgreSQL PVC (data loss, default: keep)
  --keycloak-ns NS    Keycloak namespace (default: keycloak)
  --backend-ns NS     Backend namespace (default: team1)
  --yes               Skip confirmation prompt
  --dry-run           Print commands without executing
EOF
  exit 0
}

# ── Argument parsing ────────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
  case "$1" in
    --help)             usage ;;
    --yes)              CONFIRM=true; shift ;;
    --delete-data)      DELETE_DATA=true; shift ;;
    --skip-sandbox)     STEP_SANDBOX=false; shift ;;
    --skip-gateway-api) STEP_GATEWAY_API=false; shift ;;
    --skip-tls)         STEP_TLS=false; shift ;;
    --skip-keycloak)    STEP_KEYCLOAK=false; shift ;;
    --skip-litellm)     STEP_LITELLM=false; shift ;;
    --skip-backend)     STEP_BACKEND=false; shift ;;
    --skip-istio)       STEP_ISTIO=false; shift ;;
    --keycloak-ns)      KEYCLOAK_NS="$2"; shift 2 ;;
    --backend-ns)       BACKEND_NS="$2"; shift 2 ;;
    --dry-run)          DRY_RUN=true; shift ;;
    *)
      log_error "Unknown option: $1"
      usage
      ;;
  esac
done

# ── Helper: detect OpenShift ────────────────────────────────────────────────
is_openshift() {
  kubectl get clusterversion &>/dev/null
}

echo ""
echo "╔════════════════════════════════════════════════════════════════╗"
echo "║  OpenShell Shared Infrastructure Cleanup                     ║"
echo "╚════════════════════════════════════════════════════════════════╝"
echo ""
echo "  Backend + sessions: $STEP_BACKEND (namespace: $BACKEND_NS)"
echo "  LiteLLM proxy:      $STEP_LITELLM"
echo "  Keycloak realm:     $STEP_KEYCLOAK (namespace: $KEYCLOAK_NS)"
echo "  cert-manager CA:    $STEP_TLS"
echo "  Istio env var:      $STEP_ISTIO"
echo "  Gateway API CRDs:   $STEP_GATEWAY_API"
echo "  Sandbox controller: $STEP_SANDBOX"
echo "  Delete PVC data:    $DELETE_DATA"
echo "  Dry run:            $DRY_RUN"
echo ""

# ── Cluster context confirmation guard ──────────────────────────────────────
if ! $DRY_RUN && ! $CONFIRM; then
  CURRENT_CONTEXT=$(kubectl config current-context 2>/dev/null || echo "<unknown>")
  log_warn "Target cluster context: $CURRENT_CONTEXT"
  echo ""
  read -r -p "This will delete OpenShell shared infrastructure from the above cluster. Continue? [y/N] " response
  case "$response" in
    [yY][eE][sS]|[yY]) ;;
    *) log_error "Aborted."; exit 1 ;;
  esac
  echo ""
fi

# ============================================================================
# Step 1: Remove rossoctl-backend + PostgreSQL
# ============================================================================
if $STEP_BACKEND; then
  log_info "Step 1: Removing rossoctl-backend + PostgreSQL in namespace $BACKEND_NS..."

  if kubectl get namespace "$BACKEND_NS" &>/dev/null; then
    # Backend deployment and service
    run_cmd kubectl delete deployment rossoctl-backend -n "$BACKEND_NS" --ignore-not-found
    run_cmd kubectl delete service rossoctl-backend -n "$BACKEND_NS" --ignore-not-found
    run_cmd kubectl delete serviceaccount rossoctl-backend -n "$BACKEND_NS" --ignore-not-found

    # Backend RBAC
    run_cmd kubectl delete clusterrole rossoctl-backend --ignore-not-found
    run_cmd kubectl delete clusterrolebinding rossoctl-backend --ignore-not-found
    run_cmd kubectl delete role rossoctl-backend-secrets -n "$BACKEND_NS" --ignore-not-found
    run_cmd kubectl delete rolebinding rossoctl-backend-secrets -n "$BACKEND_NS" --ignore-not-found

    # PostgreSQL StatefulSet + PVC + Service + Secret
    run_cmd kubectl delete statefulset postgres-sessions -n "$BACKEND_NS" --ignore-not-found
    run_cmd kubectl delete service postgres-sessions -n "$BACKEND_NS" --ignore-not-found
    run_cmd kubectl delete secret postgres-sessions-secret -n "$BACKEND_NS" --ignore-not-found

    # PVC (only deleted with --delete-data)
    PVC_NAME="postgres-data-postgres-sessions-0"
    if kubectl get pvc "$PVC_NAME" -n "$BACKEND_NS" &>/dev/null; then
      if $DELETE_DATA; then
        log_warn "  Deleting PVC $PVC_NAME (PostgreSQL data will be lost)"
        run_cmd kubectl delete pvc "$PVC_NAME" -n "$BACKEND_NS" --ignore-not-found
      else
        log_warn "  Keeping PVC $PVC_NAME (use --delete-data to remove)"
      fi
    fi

    log_success "Backend + PostgreSQL removed"
  else
    log_warn "Namespace $BACKEND_NS does not exist, skipping backend cleanup"
  fi
else
  log_info "Step 1: Skipping backend cleanup (--skip-backend)"
fi

# ============================================================================
# Step 2: Remove LiteLLM proxy
# ============================================================================
if $STEP_LITELLM; then
  log_info "Step 2: Removing LiteLLM proxy in namespace $BACKEND_NS..."

  if kubectl get namespace "$BACKEND_NS" &>/dev/null; then
    run_cmd kubectl delete deployment litellm-model-proxy -n "$BACKEND_NS" --ignore-not-found
    run_cmd kubectl delete service litellm-model-proxy -n "$BACKEND_NS" --ignore-not-found
    run_cmd kubectl delete configmap litellm-config -n "$BACKEND_NS" --ignore-not-found
    run_cmd kubectl delete secret litemaas-credentials -n "$BACKEND_NS" --ignore-not-found
    run_cmd kubectl delete secret litellm-virtual-keys -n "$BACKEND_NS" --ignore-not-found
    log_success "LiteLLM proxy removed"
  else
    log_warn "Namespace $BACKEND_NS does not exist, skipping LiteLLM cleanup"
  fi
else
  log_info "Step 2: Skipping LiteLLM cleanup (--skip-litellm)"
fi

# ============================================================================
# Step 3: Remove Keycloak realm
# ============================================================================
if $STEP_KEYCLOAK; then
  log_info "Step 3: Removing Keycloak realm 'openshell'..."

  if kubectl get pod "$KEYCLOAK_POD" -n "$KEYCLOAK_NS" &>/dev/null; then
    # Read-only probe (not wrapped in run_cmd) — needs live Keycloak even in dry-run
    if kubectl exec "$KEYCLOAK_POD" -n "$KEYCLOAK_NS" -- \
         "$KCADM" get realms/openshell --config "$KC_CONFIG" >/dev/null 2>&1; then
      log_info "  Deleting realm 'openshell'..."
      run_cmd kubectl exec "$KEYCLOAK_POD" -n "$KEYCLOAK_NS" -- \
        "$KCADM" delete realms/openshell --config "$KC_CONFIG"
      log_success "Keycloak realm 'openshell' deleted"
    else
      log_warn "Keycloak realm 'openshell' does not exist or kcadm not configured, skipping"
    fi
  else
    log_warn "Keycloak pod not found in namespace $KEYCLOAK_NS, skipping realm deletion"
  fi
else
  log_info "Step 3: Skipping Keycloak cleanup (--skip-keycloak)"
fi

# ============================================================================
# Step 4: Remove cert-manager CA chain
# ============================================================================
if $STEP_TLS; then
  log_info "Step 4: Removing cert-manager CA chain..."

  # ClusterIssuers (cluster-scoped)
  run_cmd kubectl delete clusterissuer openshell-ca-issuer --ignore-not-found
  run_cmd kubectl delete clusterissuer openshell-selfsigned --ignore-not-found

  # CA Certificate and Secret in cert-manager namespace
  run_cmd kubectl delete certificate openshell-ca -n cert-manager --ignore-not-found
  run_cmd kubectl delete secret openshell-ca-secret -n cert-manager --ignore-not-found

  log_success "cert-manager CA chain removed"
else
  log_info "Step 4: Skipping TLS cleanup (--skip-tls)"
fi

# ============================================================================
# Step 5: Remove shared TLS passthrough Gateway (Kind only)
# ============================================================================
if ! is_openshift; then
  log_info "Step 5: Removing shared TLS passthrough Gateway..."

  run_cmd kubectl delete gateway tls-passthrough -n rossoctl-system --ignore-not-found
  # The gateway controller creates a service automatically
  run_cmd kubectl delete service tls-passthrough-istio -n rossoctl-system --ignore-not-found

  log_success "Shared Gateway removed"
else
  log_info "Step 5: OpenShift detected, no shared Gateway to remove"
fi

# ============================================================================
# Step 6: Revert Istio alpha Gateway API env var
# ============================================================================
if $STEP_ISTIO; then
  if ! is_openshift; then
    log_info "Step 6: Reverting Istio PILOT_ENABLE_ALPHA_GATEWAY_API..."

    ISTIOD_NS="istio-system"
    if kubectl get deployment istiod -n "$ISTIOD_NS" &>/dev/null; then
      # Remove the env var from the discovery container
      CURRENT_ENV=$(kubectl get deployment istiod -n "$ISTIOD_NS" \
        -o jsonpath='{.spec.template.spec.containers[?(@.name=="discovery")].env[?(@.name=="PILOT_ENABLE_ALPHA_GATEWAY_API")].value}' 2>/dev/null || true)

      if [[ "$CURRENT_ENV" == "true" ]]; then
        log_info "  Removing PILOT_ENABLE_ALPHA_GATEWAY_API from istiod..."
        run_cmd kubectl set env deployment/istiod -n "$ISTIOD_NS" \
          -c discovery PILOT_ENABLE_ALPHA_GATEWAY_API-
        log_success "Istio env var reverted"
      else
        log_warn "PILOT_ENABLE_ALPHA_GATEWAY_API not set, skipping"
      fi
    else
      log_warn "istiod deployment not found, skipping"
    fi
  else
    log_info "Step 6: OpenShift detected, skipping Istio env var revert"
  fi
else
  log_info "Step 6: Skipping Istio cleanup (--skip-istio)"
fi

# ============================================================================
# Step 7: Remove Gateway API experimental CRDs (Kind only)
# ============================================================================
if $STEP_GATEWAY_API; then
  if ! is_openshift; then
    log_info "Step 7: Removing Gateway API experimental CRDs..."

    # Only remove if they exist — these are cluster-scoped and may affect other workloads
    if kubectl get crd tcproutes.gateway.networking.k8s.io &>/dev/null; then
      log_warn "  Removing CRD tcproutes.gateway.networking.k8s.io"
      run_cmd kubectl delete crd tcproutes.gateway.networking.k8s.io --ignore-not-found
    fi
    if kubectl get crd tlsroutes.gateway.networking.k8s.io &>/dev/null; then
      log_warn "  Removing CRD tlsroutes.gateway.networking.k8s.io"
      run_cmd kubectl delete crd tlsroutes.gateway.networking.k8s.io --ignore-not-found
    fi

    log_success "Gateway API experimental CRDs removed"
  else
    log_info "Step 7: OpenShift detected, no experimental CRDs to remove"
  fi
else
  log_info "Step 7: Skipping Gateway API CRD cleanup (--skip-gateway-api)"
fi

# ============================================================================
# Step 8: Remove agent-sandbox-controller
# ============================================================================
if $STEP_SANDBOX; then
  log_info "Step 8: Removing agent-sandbox-controller..."

  SANDBOX_BASE_URL="https://github.com/kubernetes-sigs/agent-sandbox/releases/download/${AGENT_SANDBOX_VERSION}"

  if kubectl get namespace agent-sandbox-system &>/dev/null; then
    # URL-based deletes use || true to tolerate network failures
    log_info "  Deleting extensions..."
    run_cmd kubectl delete -f "${SANDBOX_BASE_URL}/extensions.yaml" --ignore-not-found || true

    log_info "  Deleting controller..."
    run_cmd kubectl delete -f "${SANDBOX_BASE_URL}/manifest.yaml" --ignore-not-found || true

    log_success "agent-sandbox-controller removed"
  else
    # CRD might still exist even if namespace is gone
    if kubectl get crd sandboxes.agents.x-k8s.io &>/dev/null; then
      log_info "  Namespace gone but CRD remains, cleaning up..."
      run_cmd kubectl delete crd sandboxes.agents.x-k8s.io --ignore-not-found
      run_cmd kubectl delete crd sandboxclaims.agents.x-k8s.io --ignore-not-found
      run_cmd kubectl delete crd sandboxtemplates.agents.x-k8s.io --ignore-not-found
      log_success "Sandbox CRDs removed"
    else
      log_warn "agent-sandbox-controller not found, skipping"
    fi
  fi
else
  log_info "Step 8: Skipping sandbox controller cleanup (--skip-sandbox)"
fi

echo ""
log_success "Shared infrastructure cleanup complete"
