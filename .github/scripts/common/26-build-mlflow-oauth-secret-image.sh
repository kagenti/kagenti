#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../lib/env-detect.sh"
source "$SCRIPT_DIR/../lib/logging.sh"

log_step "26" "Building mlflow-oauth-secret image from source"

IMAGE_NAME="$(grep -A5 'mlflowOAuthSecret:' "$REPO_ROOT/charts/kagenti/values.yaml" | grep 'image:' | grep -v '#' | awk '{print $2}')"
IMAGE_TAG="$(grep -A5 'mlflowOAuthSecret:' "$REPO_ROOT/charts/kagenti/values.yaml" | grep 'tag:' | awk '{print $2}')"
FULL_IMAGE="${IMAGE_NAME}:${IMAGE_TAG}"

NAMESPACE="kagenti-system"
JOB_NAME="mlflow-oauth-secret-job"

# Only run if MLflow auth is enabled
MLFLOW_AUTH_ENABLED=$(helm get values kagenti -n "$NAMESPACE" -o json 2>/dev/null | python3 -c "import sys,json; print(json.load(sys.stdin).get('mlflow',{}).get('auth',{}).get('enabled',False))" 2>/dev/null || echo "False")
if [ "$MLFLOW_AUTH_ENABLED" != "True" ]; then
    log_info "MLflow auth not enabled, skipping mlflow-oauth-secret image build"
    exit 0
fi

if [ "$IS_OPENSHIFT" = "true" ]; then
    # ── OpenShift: use BuildConfig with binary source ──
    source "$SCRIPT_DIR/../lib/k8s-utils.sh"

    BUILD_NAME="mlflow-oauth-secret"
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
      dockerfilePath: auth/mlflow-oauth-secret/Dockerfile
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
    NEW_IMAGE="${INTERNAL_REGISTRY}/${BUILD_NS}/${BUILD_NAME}:latest"
    log_info "Image available at: ${NEW_IMAGE}"

else
    # ── Kind / vanilla Kubernetes: local build + kind load ──
    log_info "Building image: ${FULL_IMAGE}"
    docker build -t "${FULL_IMAGE}" \
        -f "$REPO_ROOT/kagenti/auth/mlflow-oauth-secret/Dockerfile" \
        "$REPO_ROOT/kagenti/"

    CLUSTER_NAME="${KIND_CLUSTER_NAME:-kagenti}"
    log_info "Loading image into Kind cluster '${CLUSTER_NAME}'..."
    kind load docker-image "${FULL_IMAGE}" --name "${CLUSTER_NAME}"

    NEW_IMAGE="${FULL_IMAGE}"
fi

# The mlflow-oauth-secret-job is a Helm hook (post-install,post-upgrade).
# Helm hooks are NOT created by `helm upgrade --no-hooks`, so we render
# the job template and apply it directly with the updated image.
log_info "Restarting mlflow-oauth-secret job with updated image..."
kubectl delete job "$JOB_NAME" -n "$NAMESPACE" --ignore-not-found
sleep 2

# Render only the hook job template from the chart, patch the image,
# and apply it directly to the cluster.
helm template kagenti "$REPO_ROOT/charts/kagenti" -n "$NAMESPACE" \
    --show-only templates/mlflow-oauth-secret-job.yaml \
    -f <(helm get values kagenti -n "$NAMESPACE" -o yaml) \
    --set "mlflowOAuthSecret.image=$(echo "$NEW_IMAGE" | cut -d: -f1)" \
    --set "mlflowOAuthSecret.tag=$(echo "$NEW_IMAGE" | cut -d: -f2)" \
    --set "mlflowOAuthSecret.imagePullPolicy=Always" \
    | kubectl apply -f -

log_info "Waiting for mlflow-oauth-secret job to complete..."
kubectl wait --for=condition=complete "job/$JOB_NAME" \
    -n "$NAMESPACE" --timeout=180s || {
    log_error "MLflow OAuth secret job did not complete"
    kubectl logs "job/$JOB_NAME" -n "$NAMESPACE" || true
    exit 1
}

log_info "Restarting otel-collector and mlflow to pick up the new secret..."
kubectl rollout restart deployment/otel-collector -n "$NAMESPACE"
kubectl rollout status deployment/otel-collector -n "$NAMESPACE" --timeout=120s
kubectl rollout restart deployment/mlflow -n "$NAMESPACE"
kubectl rollout status deployment/mlflow -n "$NAMESPACE" --timeout=120s

log_success "mlflow-oauth-secret image built and loaded"
