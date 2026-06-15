#!/usr/bin/env bash
# After AuthBridge advanced E2E (91), bring back wave-90 weather-service and
# weather-tool so Playwright UI tests can reach the weather agent again.
# Pair with 90b-free-capacity-for-advanced-weather.sh which scales them to 0.
#
# Wave 91 leaves weather-service-advanced and weather-tool-advanced running on
# the single Kind node; scale those down first or baseline weather cannot schedule
# (kubectl rollout status for weather-service will time out).
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
# shellcheck source=/dev/null
source "$SCRIPT_DIR/../lib/env-detect.sh"
# shellcheck source=/dev/null
source "$SCRIPT_DIR/../lib/logging.sh"

NAMESPACE="${NAMESPACE:-team1}"
ROLLOUT_TIMEOUT="${BASELINE_WEATHER_ROLLOUT_TIMEOUT:-300s}"
ADV_DOWNSCALE_TIMEOUT="${WEATHER_ADVANCED_DOWNSCALE_ROLLOUT_TIMEOUT:-300s}"

log_step "90c" "Restore baseline weather deployments for UI E2E"

if ! kubectl get namespace "$NAMESPACE" &>/dev/null; then
  log_error "Namespace $NAMESPACE not found"
  exit 1
fi

# Free the same capacity 90b created for 91: advanced multi-container pods must go
# before baseline weather can run again.
for deploy in weather-service-advanced weather-tool-advanced; do
  if kubectl get "deployment/${deploy}" -n "$NAMESPACE" &>/dev/null; then
    log_info "Scaling down deployment/${deploy} in ${NAMESPACE} to free the node for baseline weather..."
    kubectl scale "deployment/${deploy}" -n "$NAMESPACE" --replicas=0
  fi
done
for deploy in weather-service-advanced weather-tool-advanced; do
  if kubectl get "deployment/${deploy}" -n "$NAMESPACE" &>/dev/null; then
    log_info "Waiting for advanced rollout to finish: ${deploy}..."
    kubectl rollout status "deployment/${deploy}" -n "$NAMESPACE" --timeout="$ADV_DOWNSCALE_TIMEOUT"
  fi
done

for deploy in weather-service weather-tool; do
  if kubectl get "deployment/${deploy}" -n "$NAMESPACE" &>/dev/null; then
    log_info "Scaling up deployment/${deploy} in ${NAMESPACE} to 1 replica..."
    kubectl scale "deployment/${deploy}" -n "$NAMESPACE" --replicas=1
  else
    log_warn "deployment/${deploy} not found (skipping)"
  fi
done

for deploy in weather-service weather-tool; do
  if kubectl get "deployment/${deploy}" -n "$NAMESPACE" &>/dev/null; then
    log_info "Waiting for rollout: ${deploy}..."
    kubectl rollout status "deployment/${deploy}" -n "$NAMESPACE" --timeout="$ROLLOUT_TIMEOUT"
  fi
done

log_success "Baseline weather deployments are ready for UI tests"
