#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../lib/env-detect.sh"
source "$SCRIPT_DIR/../lib/logging.sh"
source "$SCRIPT_DIR/../lib/k8s-utils.sh"

# This script is no longer needed. The weather-tool Deployment manifest
# (applied by 72-deploy-weather-tool.sh) already includes writable /tmp
# and cache volumes. Previously, Toolhive created the Deployment and
# StatefulSet without these volumes, requiring post-deploy patching.
#
# This script is kept as a no-op for backward compatibility with workflows
# that still reference it. It simply verifies the deployment is available.

log_step "73" "Verifying weather-tool deployment is ready (no patching needed)"

wait_for_deployment "weather-tool" "team1" 300 || {
    log_error "Weather-tool deployment not available"
    kubectl get deployment weather-tool -n team1
    kubectl describe deployment weather-tool -n team1
    kubectl get pods -n team1 -l app.kubernetes.io/name=weather-tool
    exit 1
}

log_success "Weather-tool deployment verified"
