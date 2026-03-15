#!/usr/bin/env bash
# Build kagenti-webhook image from a custom kagenti-extensions branch.
#
# Usage:
#   KAGENTI_EXTENSIONS_REF=fix/proxy-init-drop-privileged ./30-build-webhook-image.sh
#
# On OpenShift: uses BuildConfig + internal registry
# On Kind: uses docker build + kind load
#
# After building, performs helm upgrade to override the webhook image tag
# and restarts the webhook deployment.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../lib/env-detect.sh"
source "$SCRIPT_DIR/../lib/logging.sh"

EXTENSIONS_REF="${KAGENTI_EXTENSIONS_REF:-}"
if [ -z "$EXTENSIONS_REF" ]; then
    log_info "KAGENTI_EXTENSIONS_REF not set, skipping custom webhook build"
    exit 0
fi

log_step "30" "Building kagenti-webhook from kagenti-extensions@${EXTENSIONS_REF}"

EXTENSIONS_DIR="/tmp/kagenti-extensions-build"
BUILD_NAME="kagenti-webhook"
NAMESPACE="kagenti-webhook-system"

# Clone kagenti-extensions at the specified ref
rm -rf "$EXTENSIONS_DIR"
log_info "Cloning kagenti-extensions@${EXTENSIONS_REF}..."
git clone --depth 1 --branch "$EXTENSIONS_REF" \
    https://github.com/kagenti/kagenti-extensions.git "$EXTENSIONS_DIR" 2>&1 || {
    log_error "Failed to clone kagenti-extensions at ref: $EXTENSIONS_REF"
    exit 1
}

if [ "$IS_OPENSHIFT" = "true" ]; then
    # ── OpenShift: use BuildConfig with binary source ──
    source "$SCRIPT_DIR/../lib/k8s-utils.sh"

    BUILD_NS="$NAMESPACE"

    log_info "Creating ImageStream and BuildConfig for ${BUILD_NAME}..."
    oc apply -f - <<EOF
apiVersion: image.openshift.io/v1
kind: ImageStream
metadata:
  name: ${BUILD_NAME}
  namespace: ${BUILD_NS}
---
apiVersion: build.openshift.io/v1
kind: BuildConfig
metadata:
  name: ${BUILD_NAME}
  namespace: ${BUILD_NS}
spec:
  output:
    to:
      kind: ImageStreamTag
      name: ${BUILD_NAME}:latest
  source:
    type: Binary
    binary: {}
  strategy:
    type: Docker
    dockerStrategy:
      dockerfilePath: kagenti-webhook/Dockerfile
EOF

    run_with_timeout 60 "until oc get buildconfig ${BUILD_NAME} -n ${BUILD_NS} &>/dev/null; do sleep 2; done" || {
        log_error "BuildConfig not created after 60s"
        exit 1
    }

    log_info "Starting OpenShift binary build from source..."
    OC_BUILD=$(oc start-build "$BUILD_NAME" -n "$BUILD_NS" \
        --from-dir="$EXTENSIONS_DIR" --follow=false -o name 2>/dev/null || echo "")
    if [ -z "$OC_BUILD" ]; then
        log_error "Failed to start webhook build"
        exit 1
    fi
    log_info "Build started: $OC_BUILD"

    phase="Unknown"
    for _ in {1..120}; do
        phase=$(oc get "$OC_BUILD" -n "$BUILD_NS" -o jsonpath='{.status.phase}' 2>/dev/null || echo "Unknown")
        if [ "$phase" = "Complete" ]; then
            log_success "OpenShift build completed"
            break
        elif [ "$phase" = "Failed" ] || [ "$phase" = "Error" ] || [ "$phase" = "Cancelled" ]; then
            log_error "Build failed with phase: $phase"
            oc logs "$OC_BUILD" -n "$BUILD_NS" || true
            exit 1
        fi
        sleep 5
    done
    if [ "$phase" != "Complete" ]; then
        log_error "Build timed out after 600s (phase: $phase)"
        oc logs "$OC_BUILD" -n "$BUILD_NS" || true
        exit 1
    fi

    INTERNAL_REGISTRY="image-registry.openshift-image-registry.svc:5000"
    INTERNAL_IMAGE="${INTERNAL_REGISTRY}/${BUILD_NS}/${BUILD_NAME}"
    log_info "Image available at: ${INTERNAL_IMAGE}:latest"

    # Helm upgrade to override the webhook subchart image
    log_info "Updating webhook deployment with custom image..."
    helm upgrade kagenti "$REPO_ROOT/charts/kagenti" -n kagenti-system \
        --reuse-values --no-hooks \
        --set "kagenti-webhook-chart.image.repository=${INTERNAL_IMAGE}" \
        --set "kagenti-webhook-chart.image.tag=latest" \
        --set "kagenti-webhook-chart.image.pullPolicy=Always" || true

else
    # ── Kind / vanilla Kubernetes: local build + kind load ──
    FULL_IMAGE="ghcr.io/kagenti/kagenti-extensions/${BUILD_NAME}:local"

    log_info "Building image: ${FULL_IMAGE}"
    docker build -t "${FULL_IMAGE}" \
        -f "$EXTENSIONS_DIR/kagenti-webhook/Dockerfile" \
        "$EXTENSIONS_DIR/kagenti-webhook/"

    CLUSTER_NAME="${KIND_CLUSTER_NAME:-kagenti}"
    log_info "Loading image into Kind cluster '${CLUSTER_NAME}'..."
    kind load docker-image "${FULL_IMAGE}" --name "${CLUSTER_NAME}"

    log_info "Updating webhook deployment with custom image..."
    helm upgrade kagenti "$REPO_ROOT/charts/kagenti" -n kagenti-system \
        --reuse-values --no-hooks \
        --set "kagenti-webhook-chart.image.repository=ghcr.io/kagenti/kagenti-extensions/${BUILD_NAME}" \
        --set "kagenti-webhook-chart.image.tag=local" \
        --set "kagenti-webhook-chart.image.pullPolicy=Never" || true
fi

# Restart the webhook deployment to pick up the new image
log_info "Restarting webhook deployment..."
kubectl rollout restart deployment/kagenti-webhook -n "$NAMESPACE"
kubectl rollout status deployment/kagenti-webhook -n "$NAMESPACE" --timeout=120s

# Clean up
rm -rf "$EXTENSIONS_DIR"

log_success "kagenti-webhook built from ${EXTENSIONS_REF} and deployed"
