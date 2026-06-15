#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../lib/env-detect.sh"
source "$SCRIPT_DIR/../lib/logging.sh"

log_step "25" "Building ui-oauth-secret image from source"

IMAGE_NAME="$(grep -A5 'uiOAuthSecret:' "$REPO_ROOT/charts/kagenti/values.yaml" | grep 'image:' | grep -v '#' | awk '{print $2}')"
IMAGE_TAG="$(grep -A5 'uiOAuthSecret:' "$REPO_ROOT/charts/kagenti/values.yaml" | grep 'tag:' | awk '{print $2}')"
FULL_IMAGE="${IMAGE_NAME}:${IMAGE_TAG}"

NAMESPACE="kagenti-system"
JOB_NAME="kagenti-ui-oauth-secret-job"

if [ "$IS_OPENSHIFT" = "true" ]; then
    # ── OpenShift: use BuildConfig with binary source ──
    source "$SCRIPT_DIR/../lib/k8s-utils.sh"

    BUILD_NAME="ui-oauth-secret"
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
      dockerfilePath: auth/ui-oauth-secret/Dockerfile
EOF

    run_with_timeout 60 "until oc get buildconfig ${BUILD_NAME} -n ${BUILD_NS} &>/dev/null; do sleep 2; done" || {
        log_error "BuildConfig not created after 60s"
        exit 1
    }

    log_info "Starting OpenShift binary build from source..."
    OC_BUILD=$(oc start-build "$BUILD_NAME" -n "$BUILD_NS" \
        --from-dir="$REPO_ROOT/kagenti/" --follow=false -o name 2>/dev/null || echo "")
    if [ -z "$OC_BUILD" ]; then
        log_error "Failed to start build"
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
    INTERNAL_IMAGE="${INTERNAL_REGISTRY}/${BUILD_NS}/${BUILD_NAME}:latest"
    log_info "Image available at: ${INTERNAL_IMAGE}"

    # Restart the job with the freshly-built internal image
    log_info "Restarting oauth-secret job with updated image..."
    kubectl delete job "$JOB_NAME" -n "$NAMESPACE" --ignore-not-found
    sleep 2

    helm upgrade kagenti "$REPO_ROOT/charts/kagenti" -n "$NAMESPACE" \
        --reuse-values --no-hooks \
        --set "uiOAuthSecret.image=${INTERNAL_REGISTRY}/${BUILD_NS}/${BUILD_NAME}" \
        --set "uiOAuthSecret.tag=latest" \
        --set "uiOAuthSecret.imagePullPolicy=Always" || true

    log_info "Waiting for oauth-secret job to complete..."
    kubectl wait --for=condition=complete "job/$JOB_NAME" \
        -n "$NAMESPACE" --timeout=120s || {
        log_error "OAuth secret job did not complete"
        kubectl logs "job/$JOB_NAME" -n "$NAMESPACE" || true
        exit 1
    }

    log_info "Restarting kagenti-ui to pick up the new secret..."
    kubectl rollout restart deployment/kagenti-ui -n "$NAMESPACE"
    kubectl rollout status deployment/kagenti-ui -n "$NAMESPACE" --timeout=120s

else
    # ── Kind / vanilla Kubernetes: local build + kind load ──
    log_info "Building image: ${FULL_IMAGE}"
    docker build -t "${FULL_IMAGE}" \
        -f "$REPO_ROOT/kagenti/auth/ui-oauth-secret/Dockerfile" \
        "$REPO_ROOT/kagenti/"

    CLUSTER_NAME="${KIND_CLUSTER_NAME:-kagenti}"
    log_info "Loading image into Kind cluster '${CLUSTER_NAME}'..."
    kind load docker-image "${FULL_IMAGE}" --name "${CLUSTER_NAME}"

    # Always restart the job so it runs with the freshly-built PR image.
    # The Helm install may have already completed the job using the old
    # registry image, which lacks PR changes (e.g. realm bootstrap/user creation).
    log_info "Restarting oauth-secret job with updated image..."
    kubectl delete job "$JOB_NAME" -n "$NAMESPACE" --ignore-not-found
    sleep 2

    helm upgrade kagenti "$REPO_ROOT/charts/kagenti" -n "$NAMESPACE" \
        --reuse-values --no-hooks || true

    log_info "Waiting for oauth-secret job to complete..."
    kubectl wait --for=condition=complete "job/$JOB_NAME" \
        -n "$NAMESPACE" --timeout=120s || {
        log_error "OAuth secret job did not complete"
        kubectl logs "job/$JOB_NAME" -n "$NAMESPACE" || true
        exit 1
    }

    log_info "Restarting kagenti-ui to pick up the new secret..."
    kubectl rollout restart deployment/kagenti-ui -n "$NAMESPACE"
    kubectl rollout status deployment/kagenti-ui -n "$NAMESPACE" --timeout=120s
fi

log_success "ui-oauth-secret image built and loaded"

# Build mlflow-oauth-secret image if the script exists (added in PR,
# workflow step only available after merge to main)
MLFLOW_SCRIPT="$SCRIPT_DIR/26-build-mlflow-oauth-secret-image.sh"
if [ -x "$MLFLOW_SCRIPT" ]; then
    bash "$MLFLOW_SCRIPT"
fi
