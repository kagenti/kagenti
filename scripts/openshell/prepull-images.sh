#!/usr/bin/env bash
# ============================================================================
# OPENSHELL IMAGE PRE-PULL
# ============================================================================
# Pre-pulls critical container images into the cluster via Kubernetes Jobs.
# On fresh HyperShift nodes, image pulls take 20+ min due to cold caches.
# Running this early (before platform install) lets images cache in the
# background while other phases run.
#
# Defaults to the 'prepull-cache' namespace to avoid conflicts with Helm-managed
# namespaces (team1, team2). deploy-shared.sh passes --namespace team1 explicitly
# after the Kagenti Helm install has already created it with proper labels.
#
# Usage:
#   scripts/openshell/prepull-images.sh                    # Pull all images (ns: prepull-cache)
#   scripts/openshell/prepull-images.sh --namespace team1  # Custom namespace
#   scripts/openshell/prepull-images.sh --timeout 1200     # Custom wait (seconds)
#   scripts/openshell/prepull-images.sh --no-wait          # Start pulls, don't wait
#
# Prerequisites: kubectl, target namespace must exist (auto-created if not)
# ============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

NS="${PREPULL_NS:-prepull-cache}"
TIMEOUT=1200
WAIT=true

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'; NC='\033[0m'
log_info()    { echo -e "${BLUE}→${NC} $1"; }
log_success() { echo -e "${GREEN}✓${NC} $1"; }
log_warn()    { echo -e "${YELLOW}⚠${NC} $1"; }

while [[ $# -gt 0 ]]; do
  case "$1" in
    --namespace) NS="$2"; shift 2 ;;
    --timeout)   TIMEOUT="$2"; shift 2 ;;
    --no-wait)   WAIT=false; shift ;;
    *)           shift ;;
  esac
done

# Read gateway/driver image tags from Helm values
CHART_DIR="$REPO_ROOT/charts/openshell"
GW_REPO=$(grep -A2 'gateway:' "$CHART_DIR/values.yaml" | grep 'repository:' | awk '{print $2}')
GW_TAG=$(grep -A3 'gateway:' "$CHART_DIR/values.yaml" | grep 'tag:' | awk '{print $2}')
CD_REPO=$(grep -A2 'computeDriver:' "$CHART_DIR/values.yaml" | grep 'repository:' | awk '{print $2}')
CD_TAG=$(grep -A3 'computeDriver:' "$CHART_DIR/values.yaml" | grep 'tag:' | awk '{print $2}')
CR_REPO=$(grep -A2 'credentialsDriver:' "$CHART_DIR/values.yaml" | grep 'repository:' | awk '{print $2}')
CR_TAG=$(grep -A3 'credentialsDriver:' "$CHART_DIR/values.yaml" | grep 'tag:' | awk '{print $2}')

IMAGES=(
  "ghcr.io/nvidia/openshell-community/sandboxes/base:latest"
  "${GW_REPO}:${GW_TAG}"
  "${CD_REPO}:${CD_TAG}"
  "${CR_REPO}:${CR_TAG}"
  "ghcr.io/berriai/litellm:main-v1.83.10-stable"
  "postgres:16-alpine"
)

# Ensure namespace exists
kubectl get ns "$NS" &>/dev/null || kubectl create ns "$NS" 2>/dev/null || true

JOBS_CREATED=0
for img in "${IMAGES[@]}"; do
  job_name="pull-$(echo "$img" | sed 's|[/:.@]|-|g' | tail -c 58)"

  if kubectl get job "$job_name" -n "$NS" &>/dev/null; then
    continue
  fi

  log_info "Pre-pulling $img..."
  kubectl apply -f - <<EOJOB 2>/dev/null || true
apiVersion: batch/v1
kind: Job
metadata:
  name: $job_name
  namespace: $NS
spec:
  ttlSecondsAfterFinished: 600
  backoffLimit: 3
  template:
    spec:
      containers:
      - name: pull
        image: $img
        imagePullPolicy: Always
        command: ["echo", "pulled"]
      restartPolicy: Never
EOJOB
  JOBS_CREATED=$((JOBS_CREATED + 1))
done

if [ "$JOBS_CREATED" -eq 0 ]; then
  log_success "All images already pre-pulled"
  exit 0
fi

log_info "Started $JOBS_CREATED pre-pull Jobs in namespace $NS"

if $WAIT; then
  log_info "Waiting for pre-pull Jobs to complete (up to ${TIMEOUT}s)..."
  FAILED=0
  for img in "${IMAGES[@]}"; do
    job_name="pull-$(echo "$img" | sed 's|[/:.@]|-|g' | tail -c 58)"
    kubectl wait --for=condition=Complete "job/$job_name" \
      -n "$NS" --timeout="${TIMEOUT}s" 2>/dev/null || {
        log_warn "Pre-pull $job_name not complete after ${TIMEOUT}s"
        FAILED=$((FAILED + 1))
      }
  done

  if [ "$FAILED" -eq 0 ]; then
    log_success "All ${#IMAGES[@]} images pre-pulled successfully"
  else
    log_warn "$FAILED/${#IMAGES[@]} images still pulling (non-fatal)"
  fi
else
  log_info "Pre-pull Jobs running in background (--no-wait)"
fi
