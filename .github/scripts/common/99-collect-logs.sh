#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../lib/env-detect.sh"
source "$SCRIPT_DIR/../lib/logging.sh"

log_step "99" "Collecting logs on failure"

echo "=== Failed Pods ==="
kubectl get pods --all-namespaces --field-selector=status.phase!=Running,status.phase!=Succeeded || true

echo ""
echo "=== Recent Events (last 30) ==="
kubectl get events --all-namespaces --sort-by='.lastTimestamp' | tail -30 || true

echo ""
echo "=== Team1 Namespace Status ==="
kubectl get all -n team1 || true

echo ""
echo "=== Weather Service Logs ==="
kubectl logs -n team1 deployment/weather-service --tail=50 --all-containers=true || true

echo ""
echo "=== Shipwright Build Status ==="
kubectl get builds -n team1 || true
kubectl get buildruns -n team1 || true

echo ""
echo "=== Shipwright Build Logs (if exists) ==="
BUILD_POD=$(kubectl get pods -n team1 -l build.shipwright.io/name=weather-service --sort-by=.metadata.creationTimestamp -o jsonpath='{.items[-1].metadata.name}' 2>/dev/null || echo "")
if [ -n "$BUILD_POD" ]; then
    kubectl logs -n team1 "$BUILD_POD" --all-containers=true --tail=100 || true
fi

echo ""
echo "=== Keycloak Logs (if exists) ==="
kubectl logs -n keycloak deployment/keycloak --tail=30 || kubectl logs -n keycloak statefulset/keycloak --tail=30 || true

log_info "Logs collected"
