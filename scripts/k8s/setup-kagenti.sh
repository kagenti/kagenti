#!/usr/bin/env bash
# ============================================================================
# KAGENTI PLATFORM SETUP FOR VANILLA KUBERNETES
# ============================================================================
# Installs the Kagenti stack onto a pre-existing Kubernetes cluster (K3s,
# kubeadm, EKS, GKE, AKS, or any other distribution that exposes a working
# kubectl context).
#
# Same component set as scripts/kind/setup-kagenti.sh — the only difference
# is that cluster bring-up is the operator's responsibility, not this
# script's. The shared installer logic lives in scripts/lib/install-deps.sh.
#
# Usage:
#   scripts/k8s/setup-kagenti.sh                          # Core only
#   scripts/k8s/setup-kagenti.sh --with-all               # Everything
#   scripts/k8s/setup-kagenti.sh --with-builds            # Tekton + Shipwright
#   scripts/k8s/setup-kagenti.sh --domain example.com     # Custom hostname domain
#
# Prerequisites:
#   - kubectl context pointing at the target cluster
#   - helm v3
#   - cluster has enough capacity for the requested components
#
# Run scripts/k8s/setup-kagenti.sh --help for the full flag set.
# ============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
KIND_SETUP="$REPO_ROOT/scripts/kind/setup-kagenti.sh"

if [[ ! -x "$KIND_SETUP" ]]; then
  echo "Error: $KIND_SETUP not found or not executable." >&2
  echo "       The Kubernetes entry point delegates installation to the shared" >&2
  echo "       implementation in scripts/kind/setup-kagenti.sh + scripts/lib/install-deps.sh." >&2
  exit 1
fi

# Verify a usable kubectl context before delegating. Fail fast with a clear
# message rather than letting a missing kubeconfig bubble out of helm or
# kubectl partway through the install.
if ! command -v kubectl >/dev/null 2>&1; then
  echo "Error: kubectl not found in PATH." >&2
  exit 1
fi
if ! kubectl cluster-info >/dev/null 2>&1; then
  echo "Error: kubectl cannot reach a cluster." >&2
  echo "       Set KUBECONFIG or run 'kubectl config use-context <name>' to point at" >&2
  echo "       the target cluster, then re-run this script." >&2
  exit 1
fi

# Reject Kind-only flags with a clear error rather than letting them fail
# deep in the script when they hit a `docker exec <kind-container>` call.
for arg in "$@"; do
  case "$arg" in
    --build-images|--preload-images)
      echo "Error: $arg is Kind-only (loads images into the Kind node)." >&2
      echo "       On vanilla Kubernetes, push images to your cluster's" >&2
      echo "       registry and reference them by tag instead." >&2
      exit 1
      ;;
  esac
done

# Forward the user's flags to the shared setup, but force --skip-cluster so
# the Kind-specific create/preload steps are skipped. KAGENTI_SETUP_FLAVOR
# changes the banner from "(Kind)" to "(Kubernetes)" so users running this
# entry point see an accurate label, and gates the Kind-only registry-DNS
# configuration block.
KAGENTI_SETUP_FLAVOR=k8s exec "$KIND_SETUP" --skip-cluster "$@"
