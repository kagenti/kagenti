#!/bin/bash
# Cleanup script for Kagenti installer
# This script uninstalls all helm releases and namespaces created by the installer
# Usage: ./cleanup-install.sh

set -e

echo "============================================"
echo "Kagenti Installer Cleanup Script"
echo "============================================"
echo ""

# Team namespaces to clean up
TEAM_NAMESPACES=("team1" "team2")

# Platform namespaces
PLATFORM_NAMESPACES=("kagenti-system" "kagenti-webhook-system" "mcp-system" "spire-mgmt" "spire-server" "spire-system" "gateway-system")

# OpenShift operator namespaces (managed by OLM, may have finalizers)
OPENSHIFT_OPERATOR_NAMESPACES=("openshift-builds" "cert-manager-operator" "zero-trust-workload-identity-manager")

# ==============================================================================
# 1. Delete CRs in team namespaces BEFORE uninstalling operators
# ==============================================================================
# This allows operators to properly handle finalizers during deletion.
# If we uninstall operators first, CRs get stuck with unremovable finalizers.

echo "Deleting CRs in team namespaces (before operator uninstall)..."
for ns in "${TEAM_NAMESPACES[@]}"; do
  if kubectl get ns "$ns" &>/dev/null; then
    echo "Cleaning up CRs in $ns..."
    # Delete Agent CRs (kagenti-operator)
    kubectl delete agents.agent.kagenti.dev --all -n "$ns" --ignore-not-found 2>/dev/null || true
    kubectl delete agentbuilds.agent.kagenti.dev --all -n "$ns" --ignore-not-found 2>/dev/null || true
    kubectl delete agentcards.agent.kagenti.dev --all -n "$ns" --ignore-not-found 2>/dev/null || true
    # Delete MCP Gateway CRs
    kubectl delete mcpservers.mcp.kagenti.com --all -n "$ns" --ignore-not-found 2>/dev/null || true
  fi
done
echo ""

# ==============================================================================
# 2. Uninstall Helm releases
# ==============================================================================

# Helm releases created by the installer (in reverse order of installation)
# Format: "release-name:namespace"
HELM_RELEASES=(
  "kagenti:kagenti-system"
  "mcp-gateway:mcp-system"
  "kagenti-deps:kagenti-system"
  "spire:spire-mgmt"
  "spire-crds:spire-mgmt"
  # The following are only installed on non-OpenShift (Kind) clusters
  "ztunnel:istio-system"
  "istio-cni:istio-system"
  "istiod:istio-system"
  "istio-base:istio-system"
)

# Delete Istio CRs first (OpenShift only) - these are created by helm post-install hooks
echo "Deleting Istio CRs (if present)..."
kubectl delete istio default --ignore-not-found 2>/dev/null || true
kubectl delete istiocni default --ignore-not-found 2>/dev/null || true
kubectl delete ztunnel default --ignore-not-found 2>/dev/null || true
echo ""

echo "Uninstalling Helm releases..."
echo ""

for release_info in "${HELM_RELEASES[@]}"; do
  release_name="${release_info%%:*}"
  namespace="${release_info##*:}"

  # Check if release exists
  if helm status "$release_name" -n "$namespace" &>/dev/null; then
    echo "Uninstalling: $release_name from $namespace"
    helm uninstall "$release_name" -n "$namespace" || true
  else
    echo "Not found: $release_name in $namespace (skipping)"
  fi
done

echo ""
echo "Deleting PVCs to ensure clean state on reinstall..."
# PVCs are not deleted by helm uninstall, so we need to delete them manually
# to prevent corrupt data from being reused on reinstall
NAMESPACES_WITH_PVCS=("kagenti-system" "mcp-system" "keycloak")
for ns in "${NAMESPACES_WITH_PVCS[@]}"; do
  if kubectl get ns "$ns" &>/dev/null; then
    echo "Deleting PVCs in $ns..."
    kubectl delete pvc --all -n "$ns" --ignore-not-found 2>/dev/null || true
  fi
done
echo ""

echo "Deleting stale istio-ca-root-cert configmaps..."
# These configmaps are created by istiod and may contain stale CA certs
# from previous installations, causing certificate mismatch errors
ISTIO_NAMESPACES=("istio-system" "istio-ztunnel" "istio-cni" "kagenti-system" "mcp-system" "keycloak" "team1" "team2")
for ns in "${ISTIO_NAMESPACES[@]}"; do
  if kubectl get configmap istio-ca-root-cert -n "$ns" &>/dev/null 2>&1; then
    echo "Deleting istio-ca-root-cert in $ns..."
    kubectl delete configmap istio-ca-root-cert -n "$ns" --ignore-not-found 2>/dev/null || true
  fi
done
echo ""

echo "Deleting istio-ca-secret to force CA regeneration..."
# This secret contains the CA private key used by istiod
# Deleting it forces istiod to generate a new CA on next install
kubectl delete secret istio-ca-secret -n istio-system --ignore-not-found 2>/dev/null || true
echo ""

# ==============================================================================
# 3. Clean up OpenShift operator namespaces (OLM-managed)
# ==============================================================================
# These namespaces contain operators installed via OLM subscriptions.
# The operators create resources with finalizers that can only be removed
# by the operator controller. We must delete the operator properly first.

echo "Cleaning up OpenShift operator namespaces..."

# Function to remove finalizers from all resources in a namespace
remove_namespace_finalizers() {
  local ns=$1
  local finalizer_pattern=$2
  
  echo "Removing finalizers matching '$finalizer_pattern' from resources in $ns..."
  kubectl api-resources --verbs=list --namespaced -o name 2>/dev/null | \
    xargs -I {} kubectl get {} -n "$ns" -o json 2>/dev/null | \
    jq -r ".items[] | select(.metadata.finalizers != null and (.metadata.finalizers[] | contains(\"$finalizer_pattern\"))) | \"\(.kind | ascii_downcase)/\(.metadata.name)\"" 2>/dev/null | \
    while read resource; do
      if [ -n "$resource" ]; then
        echo "  Patching $resource..."
        kubectl patch "$resource" -n "$ns" -p '{"metadata":{"finalizers":null}}' --type=merge 2>/dev/null || true
      fi
    done
}

for ns in "${OPENSHIFT_OPERATOR_NAMESPACES[@]}"; do
  if kubectl get ns "$ns" &>/dev/null 2>&1; then
    echo "Processing OpenShift operator namespace: $ns"
    
    # Delete Subscription first (this triggers operator uninstall)
    echo "  Deleting Subscriptions in $ns..."
    kubectl delete subscription --all -n "$ns" --ignore-not-found 2>/dev/null || true
    
    # Wait a moment for OLM to process the subscription deletion
    sleep 2
    
    # Delete CSVs (ClusterServiceVersions)
    echo "  Deleting CSVs in $ns..."
    kubectl delete csv --all -n "$ns" --ignore-not-found 2>/dev/null || true
    
    # Delete OperatorGroups
    echo "  Deleting OperatorGroups in $ns..."
    kubectl delete operatorgroup --all -n "$ns" --ignore-not-found 2>/dev/null || true
    
    # Check if namespace is terminating and has stuck finalizers
    ns_phase=$(kubectl get ns "$ns" -o jsonpath='{.status.phase}' 2>/dev/null)
    if [ "$ns_phase" == "Terminating" ]; then
      echo "  Namespace $ns is stuck in Terminating state, removing finalizers..."
      case "$ns" in
        openshift-builds)
          remove_namespace_finalizers "$ns" "operator.openshift.io/openshiftbuilds"
          ;;
        cert-manager-operator)
          remove_namespace_finalizers "$ns" "operator.openshift.io"
          ;;
        zero-trust-workload-identity-manager)
          remove_namespace_finalizers "$ns" "operator.openshift.io"
          ;;
        *)
          remove_namespace_finalizers "$ns" "operator.openshift.io"
          ;;
      esac
    fi
    
    # Now delete the namespace
    echo "  Deleting namespace $ns..."
    kubectl delete ns "$ns" --ignore-not-found 2>/dev/null || true
  fi
done
echo ""

# ==============================================================================
# 5. Remove stuck finalizers (fallback if operators are already gone)
# ==============================================================================
# If operators were uninstalled before CRs were deleted, CRs may be stuck
# with finalizers that can never be removed. This removes them forcefully.

echo "Removing stuck finalizers from CRs (if any)..."
for ns in "${TEAM_NAMESPACES[@]}"; do
  if kubectl get ns "$ns" &>/dev/null; then
    echo "Checking for stuck CRs in $ns..."
    # Remove finalizers from Agent CRs
    for resource in agents.agent.kagenti.dev agentbuilds.agent.kagenti.dev agentcards.agent.kagenti.dev; do
      for name in $(kubectl get $resource -n "$ns" -o name 2>/dev/null); do
        echo "Removing finalizers from $name..."
        kubectl patch $name -n "$ns" --type=json -p='[{"op": "remove", "path": "/metadata/finalizers"}]' 2>/dev/null || true
      done
    done
  fi
done
echo ""

# ==============================================================================
# 6. Delete team namespaces
# ==============================================================================

echo "Deleting team namespaces..."
for ns in "${TEAM_NAMESPACES[@]}"; do
  if kubectl get ns "$ns" &>/dev/null; then
    echo "Deleting namespace: $ns"
    kubectl delete ns "$ns" --ignore-not-found || true
  fi
done
echo ""

# ==============================================================================
# 7. Delete platform namespaces
# ==============================================================================

echo "Deleting platform namespaces..."
for ns in "${PLATFORM_NAMESPACES[@]}"; do
  if kubectl get ns "$ns" &>/dev/null; then
    echo "Deleting namespace: $ns"
    kubectl delete ns "$ns" --ignore-not-found || true
  fi
done
echo ""

# ==============================================================================
# 8. Wait for namespaces to terminate
# ==============================================================================

# Build list of namespaces to wait for
WAIT_NAMESPACES=("${TEAM_NAMESPACES[@]}" "${PLATFORM_NAMESPACES[@]}" "${OPENSHIFT_OPERATOR_NAMESPACES[@]}")

echo "Waiting for namespaces to terminate..."
MAX_WAIT=60
for ns in "${WAIT_NAMESPACES[@]}"; do
  if kubectl get ns "$ns" &>/dev/null 2>&1; then
    echo "Waiting for $ns to terminate (max ${MAX_WAIT}s)..."
    for i in $(seq 1 $MAX_WAIT); do
      if ! kubectl get ns "$ns" &>/dev/null 2>&1; then
        echo "$ns terminated"
        break
      fi
      if [ $i -eq $MAX_WAIT ]; then
        echo "WARNING: $ns still exists after ${MAX_WAIT}s"
        kubectl get ns "$ns" -o jsonpath='{.status.conditions}' 2>/dev/null | jq '.' || true
      fi
      sleep 1
    done
  fi
done
echo ""

echo "============================================"
echo "Cleanup complete!"
echo ""
echo "Note: The following resources may still exist and need manual cleanup:"
echo "  - OLM Subscriptions and operators (on OpenShift)"
echo "  - CRDs installed by operators"
echo "  - Istio namespaces (istio-system, istio-cni, istio-ztunnel) - managed by OLM on OpenShift"
echo ""
echo "To remove OLM subscriptions (OpenShift only):"
echo "  kubectl delete subscription servicemeshoperator3 kiali-ossm -n openshift-operators"
echo "  kubectl delete subscription openshift-pipelines-operator-rh -n openshift-operators"
echo "  kubectl delete subscription rhbk-operator -n keycloak"
echo "============================================"
