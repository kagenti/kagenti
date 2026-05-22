#!/usr/bin/env bash
# Build platform images (backend, ui-v2, agent-oauth-secret) from source.
#
# Ensures E2E tests run against the actual code from the current branch,
# not pre-built images from the container registry.
#
# Kind: docker build + kind load + rollout restart
# OpenShift: delegates to 37-build-platform-images.sh (BuildConfig)
#
# Called after Helm install (30-run-installer.sh) and before tests.
#
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../lib/env-detect.sh"
source "$SCRIPT_DIR/../lib/logging.sh"
# Re-set SCRIPT_DIR after env-detect (it overrides SCRIPT_DIR)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

log_step "26" "Building platform images from source"

NAMESPACE="kagenti-system"

# ── Images to build ──
# Format: image_ref|dockerfile_path|workload_type|workload_name
# image_ref:      full image name:tag (parsed from values.yaml)
# dockerfile_path: relative to $REPO_ROOT/kagenti/
# workload_type:   deployment or job
# workload_name:   Kubernetes resource name
IMAGES=(
    "ghcr.io/kagenti/kagenti/ui-v2:latest|ui-v2/Dockerfile|deployment|kagenti-ui"
    "ghcr.io/kagenti/kagenti/backend:latest|backend/Dockerfile|deployment|kagenti-backend"
    "ghcr.io/kagenti/kagenti/agent-oauth-secret:latest|auth/agent-oauth-secret/Dockerfile|job|kagenti-agent-oauth-secret-job"
)

if [ "$IS_OPENSHIFT" = "true" ]; then
    # ── OpenShift: delegate to the on-cluster build script ──
    # 37-build-platform-images.sh uses BuildConfig to build on the cluster.
    log_info "OpenShift detected — delegating to 37-build-platform-images.sh"
    bash "$SCRIPT_DIR/../kagenti-operator/37-build-platform-images.sh"
    log_success "Platform images built via OpenShift BuildConfig"
    exit 0
fi

# ── Kind / vanilla Kubernetes: local build + kind load ──
CLUSTER_NAME="${KIND_CLUSTER_NAME:-kagenti}"
BUILD_CONTEXT="$REPO_ROOT/kagenti"

# Track deployments that need restart
DEPLOYMENTS_TO_RESTART=()

for SPEC in "${IMAGES[@]}"; do
    IFS='|' read -r IMAGE_REF DOCKERFILE WORKLOAD_TYPE WORKLOAD_NAME <<< "$SPEC"

    log_info "Building: ${IMAGE_REF}"
    docker build -t "${IMAGE_REF}" \
        -f "${BUILD_CONTEXT}/${DOCKERFILE}" \
        "${BUILD_CONTEXT}"

    log_info "Loading into Kind cluster '${CLUSTER_NAME}'..."
    kind load docker-image "${IMAGE_REF}" --name "${CLUSTER_NAME}"

    if [ "$WORKLOAD_TYPE" = "deployment" ]; then
        DEPLOYMENTS_TO_RESTART+=("$WORKLOAD_NAME")
    elif [ "$WORKLOAD_TYPE" = "job" ]; then
        # Jobs need delete + helm upgrade to re-trigger
        log_info "Restarting job ${WORKLOAD_NAME} with updated image..."
        kubectl delete job "$WORKLOAD_NAME" -n "$NAMESPACE" --ignore-not-found
        sleep 2
    fi

    log_success "${IMAGE_REF} built and loaded"
done

# Restart deployments to pick up freshly-loaded images
if [ ${#DEPLOYMENTS_TO_RESTART[@]} -gt 0 ]; then
    log_info "Restarting deployments: ${DEPLOYMENTS_TO_RESTART[*]}"
    for DEPLOY in "${DEPLOYMENTS_TO_RESTART[@]}"; do
        kubectl rollout restart "deployment/${DEPLOY}" -n "$NAMESPACE"
    done
    for DEPLOY in "${DEPLOYMENTS_TO_RESTART[@]}"; do
        kubectl rollout status "deployment/${DEPLOY}" -n "$NAMESPACE" --timeout=120s || {
            log_error "Rollout failed for ${DEPLOY}"
            kubectl get pods -n "$NAMESPACE" -l "app.kubernetes.io/name=${DEPLOY}" 2>&1 || true
            exit 1
        }
    done
    log_success "Deployments restarted with source-built images"
fi

# Re-trigger Jobs via Helm upgrade (recreates deleted jobs)
helm upgrade kagenti "$REPO_ROOT/charts/kagenti" -n "$NAMESPACE" \
    --reuse-values --no-hooks || { log_error "Helm upgrade failed"; exit 1; }

# Wait for agent-oauth-secret job to complete
JOB_NAME="kagenti-agent-oauth-secret-job"
if kubectl get job "$JOB_NAME" -n "$NAMESPACE" &>/dev/null; then
    log_info "Waiting for ${JOB_NAME} to complete..."
    kubectl wait --for=condition=complete "job/${JOB_NAME}" \
        -n "$NAMESPACE" --timeout=120s || {
        log_error "${JOB_NAME} did not complete"
        kubectl logs "job/${JOB_NAME}" -n "$NAMESPACE" || true
        exit 1
    }
    log_success "${JOB_NAME} completed with source-built image"
fi

log_success "All platform images built from source"
