#!/usr/bin/env bash
# After pytest (wave 90), scale down the baseline weather-service and weather-tool
# Deployments so single-node Kind can schedule weather-tool-advanced and
# weather-service-advanced (AuthBridge-injected, multi-container pods).
#
# Without this, wave 91 often fails with: FailedScheduling ... Insufficient cpu
# and kubectl rollout status times out for weather-service-advanced.
#
# This runs in CI only (invoked from e2e-kind*.yaml before 91). Local runs can
# call it manually with NAMESPACE=team1 if needed.
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
# shellcheck source=/dev/null
source "$SCRIPT_DIR/../lib/env-detect.sh"
# shellcheck source=/dev/null
source "$SCRIPT_DIR/../lib/logging.sh"

NAMESPACE="${NAMESPACE:-team1}"

log_step "90b" "Free cluster capacity (scale down baseline weather for advanced AuthBridge)"

if ! kubectl get namespace "$NAMESPACE" &>/dev/null; then
  log_error "Namespace $NAMESPACE not found"
  exit 1
fi

for deploy in weather-service weather-tool; do
  if kubectl get "deployment/${deploy}" -n "$NAMESPACE" &>/dev/null; then
    log_info "Scaling down deployment/${deploy} in ${NAMESPACE}..."
    kubectl scale "deployment/${deploy}" -n "$NAMESPACE" --replicas=0
  else
    log_info "deployment/${deploy} not found (skipping)"
  fi
done

# Wait for pods to terminate (up to ~5 min)
for _ in $(seq 1 60); do
  c1=$(kubectl get pods -n "$NAMESPACE" -l app.kubernetes.io/name=weather-service --no-headers 2>/dev/null | wc -l | tr -d ' ' || echo 0)
  c2=$(kubectl get pods -n "$NAMESPACE" -l app.kubernetes.io/name=weather-tool --no-headers 2>/dev/null | wc -l | tr -d ' ' || echo 0)
  c1=${c1:-0}
  c2=${c2:-0}
  if [[ "$c1" -eq 0 && "$c2" -eq 0 ]]; then
    log_success "Baseline weather-service and weather-tool pods are gone"
    exit 0
  fi
  sleep 5
done

log_warn "Timed out waiting for baseline weather pods to terminate; continuing (wave 91 may still see CPU pressure)"
