#!/usr/bin/env bash
# Install rossoctl platform via Helm (operator + deps including Keycloak).
#
# On Kind:  Uses scripts/kind/setup-rossoctl.sh --with-all --build-images
# On OCP:  Uses scripts/ocp/setup-rossoctl.sh with appropriate flags
#
# Environment:
#   PLATFORM       "kind" or "ocp" (auto-detected)
#   SKIP_PLATFORM  Set to 1 to skip if platform is already installed
set -euo pipefail
source "$(dirname "$0")/lib.sh"

log_step "30" "Install rossoctl platform via Helm"

PLATFORM="${PLATFORM:-$(detect_platform)}"

if [[ "${SKIP_PLATFORM:-0}" == "1" ]]; then
  log_info "SKIP_PLATFORM=1 — skipping platform install"
  exit 0
fi

if [[ "$PLATFORM" == "kind" ]]; then
  log_info "Installing platform on Kind cluster"
  bash "$REPO_ROOT/scripts/kind/setup-rossoctl.sh" --with-all --build-images
elif [[ "$PLATFORM" == "ocp" ]]; then
  log_info "Installing platform on OpenShift"
  bash "$REPO_ROOT/scripts/ocp/setup-rossoctl.sh"
else
  log_error "Unknown platform: $PLATFORM"
  exit 1
fi

# Wait for core components
log_info "Waiting for rossoctl-system components..."
kubectl wait --for=condition=available deployment -n rossoctl-system --all --timeout=300s 2>/dev/null || true

log_info "Waiting for keycloak..."
kubectl rollout status statefulset/keycloak -n "$KC_NAMESPACE" --timeout=300s 2>/dev/null || true

log_success "Platform installed"
