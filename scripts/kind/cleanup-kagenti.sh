#!/usr/bin/env bash
# ============================================================================
# KAGENTI CLEANUP FOR KIND
# ============================================================================
# Uninstalls all Kagenti components from a Kind cluster.
# Reverses the installation performed by setup-kagenti.sh.
#
# Usage:
#   scripts/kind/cleanup-kagenti.sh                    # Uninstall platform, keep cluster
#   scripts/kind/cleanup-kagenti.sh --destroy-cluster  # Also delete the Kind cluster
#   scripts/kind/cleanup-kagenti.sh --cluster-name X   # Specify cluster name
# ============================================================================

set -euo pipefail

CLUSTER_NAME="${CLUSTER_NAME:-kagenti}"
DESTROY_CLUSTER=false

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'; NC='\033[0m'
log_info()    { echo -e "${BLUE}→${NC} $1"; }
log_success() { echo -e "${GREEN}✓${NC} $1"; }
log_warn()    { echo -e "${YELLOW}⚠${NC} $1"; }

while [[ $# -gt 0 ]]; do
  case "$1" in
    --destroy-cluster) DESTROY_CLUSTER=true; shift ;;
    --cluster-name)    CLUSTER_NAME="$2"; shift 2 ;;
    -h|--help)
      echo "Usage: $0 [--destroy-cluster] [--cluster-name NAME]"
      exit 0 ;;
    *) echo "Unknown option: $1"; exit 1 ;;
  esac
done

echo ""
echo "============================================"
echo "  Kagenti Cleanup (Kind)"
echo "============================================"
echo ""

TEAM_NAMESPACES=("team1" "team2")

# ── 1. Delete CRs in team namespaces (before operator uninstall) ────────────
log_info "Deleting CRs in team namespaces..."
for ns in "${TEAM_NAMESPACES[@]}"; do
  if kubectl get ns "$ns" &>/dev/null; then
    kubectl delete agents.agent.kagenti.dev --all -n "$ns" --ignore-not-found 2>/dev/null || true
    kubectl delete agentcards.agent.kagenti.dev --all -n "$ns" --ignore-not-found 2>/dev/null || true
    kubectl delete mcpserverregistrations.mcp.kagenti.com --all -n "$ns" --ignore-not-found 2>/dev/null || true
  fi
done

# ── 1b. Delete Kuadrant CR (before operator uninstall) ─────────────────────
if kubectl get ns kuadrant-system &>/dev/null; then
  kubectl delete kuadrant kuadrant -n kuadrant-system --ignore-not-found 2>/dev/null || true
fi

# ── 2. Uninstall Helm releases (reverse install order) ──────────────────────
log_info "Uninstalling Helm releases..."

HELM_RELEASES=(
  "kagenti:kagenti-system"
  "mcp-gateway:mcp-system"
  "kuadrant-operator:kuadrant-system"
  "kagenti-deps:kagenti-system"
  "spire:spire-mgmt"
  "spire-crds:spire-mgmt"
  "ztunnel:istio-system"
  "istio-cni:istio-system"
  "istiod:istio-system"
  "istio-base:istio-system"
)

for release_info in "${HELM_RELEASES[@]}"; do
  release="${release_info%%:*}"
  ns="${release_info##*:}"
  if helm status "$release" -n "$ns" &>/dev/null; then
    log_info "Uninstalling $release from $ns"
    helm uninstall "$release" -n "$ns" || true
  fi
done

# ── 3. Delete PVCs ──────────────────────────────────────────────────────────
log_info "Deleting PVCs..."
for ns in kagenti-system mcp-system keycloak; do
  if kubectl get ns "$ns" &>/dev/null; then
    kubectl delete pvc --all -n "$ns" --ignore-not-found 2>/dev/null || true
  fi
done

# ── 4. Delete stale Istio CA ConfigMaps ─────────────────────────────────────
log_info "Cleaning up Istio CA artifacts..."
for ns in istio-system istio-ztunnel istio-cni kagenti-system mcp-system keycloak team1 team2; do
  kubectl delete configmap istio-ca-root-cert -n "$ns" --ignore-not-found 2>/dev/null || true
done
kubectl delete secret istio-ca-secret -n istio-system --ignore-not-found 2>/dev/null || true

# ── 5. Remove stuck finalizers from CRs ────────────────────────────────────
log_info "Removing stuck finalizers..."
for ns in "${TEAM_NAMESPACES[@]}"; do
  if kubectl get ns "$ns" &>/dev/null; then
    for resource in agents.agent.kagenti.dev agentcards.agent.kagenti.dev; do
      for name in $(kubectl get "$resource" -n "$ns" -o name 2>/dev/null); do
        kubectl patch "$name" -n "$ns" --type=json \
          -p='[{"op":"remove","path":"/metadata/finalizers"}]' 2>/dev/null || true
      done
    done
  fi
done

# ── 6. Delete namespaces ───────────────────────────────────────────────────
log_info "Deleting namespaces..."
ALL_NAMESPACES=(
  "${TEAM_NAMESPACES[@]}"
  kagenti-system kagenti-webhook-system mcp-system gateway-system
  kuadrant-system
  spire-mgmt zero-trust-workload-identity-manager spire-system
  shipwright-build tekton-pipelines cr-system
)
for ns in "${ALL_NAMESPACES[@]}"; do
  if kubectl get ns "$ns" &>/dev/null; then
    log_info "Deleting namespace $ns"
    kubectl delete ns "$ns" --ignore-not-found 2>/dev/null || true
  fi
done

# ── 7. Wait for namespace termination ──────────────────────────────────────
log_info "Waiting for namespaces to terminate..."
for ns in "${ALL_NAMESPACES[@]}"; do
  if kubectl get ns "$ns" &>/dev/null 2>&1; then
    tries=0
    while kubectl get ns "$ns" &>/dev/null 2>&1; do
      tries=$((tries + 1))
      [ $tries -ge 60 ] && { log_warn "$ns still exists after 60s"; break; }
      sleep 1
    done
  fi
done

# ── 8. Optionally destroy Kind cluster ─────────────────────────────────────
if $DESTROY_CLUSTER; then
  log_info "Destroying Kind cluster '$CLUSTER_NAME'..."
  kind delete cluster --name "$CLUSTER_NAME" 2>/dev/null || true
  log_success "Cluster destroyed"
fi

echo ""
echo "============================================"
echo "  Cleanup complete!"
echo "============================================"
echo ""
