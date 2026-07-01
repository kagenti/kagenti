#!/usr/bin/env bash
# ============================================================================
# KAGENTI CLEANUP FOR VANILLA KUBERNETES
# ============================================================================
# Reverses the install performed by scripts/k8s/setup-kagenti.sh: uninstalls
# Helm releases, deletes namespaces, and clears stale Istio CA artifacts.
# Does NOT delete the underlying cluster — that's the operator's call.
#
# Usage:
#   scripts/k8s/cleanup-kagenti.sh
#
# Prerequisites: kubectl context pointing at the target cluster.
# ============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
KIND_CLEANUP="$REPO_ROOT/scripts/kind/cleanup-kagenti.sh"

if [[ ! -x "$KIND_CLEANUP" ]]; then
  echo "Error: $KIND_CLEANUP not found or not executable." >&2
  exit 1
fi

if ! command -v kubectl >/dev/null 2>&1; then
  echo "Error: kubectl not found in PATH." >&2
  exit 1
fi
if ! kubectl cluster-info >/dev/null 2>&1; then
  echo "Error: kubectl cannot reach a cluster." >&2
  exit 1
fi

# Reject the Kind-only flag explicitly so users don't get confused by silent
# passthrough.
for arg in "$@"; do
  if [[ "$arg" == "--destroy-cluster" ]]; then
    echo "Error: --destroy-cluster is Kind-only. Delete the cluster manually if needed." >&2
    exit 1
  fi
done

exec "$KIND_CLEANUP" "$@"
