#!/usr/bin/env bash
# Build a container image from a dependency repo's branch or PR.
#
# Supports both branch refs (on upstream) and PR numbers (works with forks).
#
# Usage:
#   DEP_REPO=kagenti/kagenti-extensions \
#   DEP_REF=fix/proxy-init-drop-privileged \
#   DEP_CONTEXT=kagenti-webhook \
#   DEP_IMAGE_NAME=kagenti-webhook \
#   DEP_DEPLOY_NS=kagenti-webhook-system \
#   DEP_HELM_SET="kagenti-webhook-chart.image" \
#   ./30-build-dep-image.sh
#
# Ref formats:
#   branch-name          — clone branch from upstream repo
#   pr/<number>          — fetch PR head ref (works with forks)
#
# Examples:
#   /run-e2e --build kagenti/kagenti-extensions=fix/my-branch
#   /run-e2e --build kagenti/kagenti-extensions=pr/234
#   /run-e2e --build kagenti/kagenti-operator=feat/new-crd
#   /run-e2e --build kagenti/kagenti-extensions=pr/234 --build kagenti/kagenti-operator=pr/100
#
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../lib/env-detect.sh"
source "$SCRIPT_DIR/../lib/logging.sh"

# Required env vars
: "${DEP_REPO:?DEP_REPO is required (e.g., kagenti/kagenti-extensions)}"
: "${DEP_REF:?DEP_REF is required (e.g., fix/my-branch or pr/234)}"
: "${DEP_CONTEXT:?DEP_CONTEXT is required (subdirectory with Dockerfile)}"
: "${DEP_IMAGE_NAME:?DEP_IMAGE_NAME is required (e.g., kagenti-webhook)}"
: "${DEP_DEPLOY_NS:?DEP_DEPLOY_NS is required (e.g., kagenti-webhook-system)}"
: "${DEP_HELM_SET:?DEP_HELM_SET is required (e.g., kagenti-webhook-chart.image)}"

log_step "30" "Building ${DEP_IMAGE_NAME} from ${DEP_REPO}@${DEP_REF}"

CLONE_DIR="/tmp/dep-build-${DEP_IMAGE_NAME}"
rm -rf "$CLONE_DIR"

# Clone or fetch based on ref format
if [[ "$DEP_REF" =~ ^pr/([0-9]+)$ ]]; then
    PR_NUM="${BASH_REMATCH[1]}"
    log_info "Fetching PR #${PR_NUM} from ${DEP_REPO}..."
    git clone --depth 1 "https://github.com/${DEP_REPO}.git" "$CLONE_DIR" 2>&1
    cd "$CLONE_DIR"
    git fetch origin "pull/${PR_NUM}/head:pr-${PR_NUM}" --depth 1 2>&1
    git checkout "pr-${PR_NUM}" 2>&1
    cd - > /dev/null
else
    log_info "Cloning ${DEP_REPO}@${DEP_REF}..."
    git clone --depth 1 --branch "$DEP_REF" \
        "https://github.com/${DEP_REPO}.git" "$CLONE_DIR" 2>&1 || {
        log_error "Failed to clone ${DEP_REPO} at ref: ${DEP_REF}"
        exit 1
    }
fi

BUILD_CONTEXT="${CLONE_DIR}/${DEP_CONTEXT}"
if [ ! -d "$BUILD_CONTEXT" ]; then
    log_error "Build context not found: ${BUILD_CONTEXT}"
    ls -la "$CLONE_DIR"
    exit 1
fi

if [ "$IS_OPENSHIFT" = "true" ]; then
    # ── OpenShift: use BuildConfig with binary source ──
    source "$SCRIPT_DIR/../lib/k8s-utils.sh"

    log_info "Creating ImageStream and BuildConfig for ${DEP_IMAGE_NAME}..."
    oc apply -f - <<EOF
apiVersion: image.openshift.io/v1
kind: ImageStream
metadata:
  name: ${DEP_IMAGE_NAME}
  namespace: ${DEP_DEPLOY_NS}
---
apiVersion: build.openshift.io/v1
kind: BuildConfig
metadata:
  name: ${DEP_IMAGE_NAME}
  namespace: ${DEP_DEPLOY_NS}
spec:
  output:
    to:
      kind: ImageStreamTag
      name: ${DEP_IMAGE_NAME}:latest
  source:
    type: Binary
    binary: {}
  strategy:
    type: Docker
    dockerStrategy:
      dockerfilePath: Dockerfile
EOF

    run_with_timeout 60 "until oc get buildconfig ${DEP_IMAGE_NAME} -n ${DEP_DEPLOY_NS} &>/dev/null; do sleep 2; done" || {
        log_error "BuildConfig not created after 60s"
        exit 1
    }

    log_info "Starting OpenShift binary build from ${BUILD_CONTEXT}..."
    OC_BUILD=$(oc start-build "$DEP_IMAGE_NAME" -n "$DEP_DEPLOY_NS" \
        --from-dir="$BUILD_CONTEXT" --follow=false -o name 2>/dev/null || echo "")
    if [ -z "$OC_BUILD" ]; then
        log_error "Failed to start build for ${DEP_IMAGE_NAME}"
        exit 1
    fi
    log_info "Build started: $OC_BUILD"

    phase="Unknown"
    for _ in {1..120}; do
        phase=$(oc get "$OC_BUILD" -n "$DEP_DEPLOY_NS" -o jsonpath='{.status.phase}' 2>/dev/null || echo "Unknown")
        if [ "$phase" = "Complete" ]; then
            log_success "OpenShift build completed"
            break
        elif [ "$phase" = "Failed" ] || [ "$phase" = "Error" ] || [ "$phase" = "Cancelled" ]; then
            log_error "Build failed with phase: $phase"
            oc logs "$OC_BUILD" -n "$DEP_DEPLOY_NS" || true
            exit 1
        fi
        sleep 5
    done
    if [ "$phase" != "Complete" ]; then
        log_error "Build timed out after 600s (phase: $phase)"
        oc logs "$OC_BUILD" -n "$DEP_DEPLOY_NS" || true
        exit 1
    fi

    INTERNAL_REGISTRY="image-registry.openshift-image-registry.svc:5000"
    INTERNAL_IMAGE="${INTERNAL_REGISTRY}/${DEP_DEPLOY_NS}/${DEP_IMAGE_NAME}"
    log_info "Image available at: ${INTERNAL_IMAGE}:latest"

    # Helm upgrade to override the image
    log_info "Updating deployment with custom image..."
    helm upgrade kagenti "$REPO_ROOT/charts/kagenti" -n kagenti-system \
        --reuse-values --no-hooks \
        --set "${DEP_HELM_SET}.repository=${INTERNAL_IMAGE}" \
        --set "${DEP_HELM_SET}.tag=latest" \
        --set "${DEP_HELM_SET}.pullPolicy=Always" || true

else
    # ── Kind / vanilla Kubernetes: local build + kind load ──
    FULL_IMAGE="ghcr.io/${DEP_REPO}/${DEP_IMAGE_NAME}:local"

    log_info "Building image: ${FULL_IMAGE}"
    docker build -t "${FULL_IMAGE}" \
        -f "${BUILD_CONTEXT}/Dockerfile" \
        "$BUILD_CONTEXT"

    CLUSTER_NAME="${KIND_CLUSTER_NAME:-kagenti}"
    log_info "Loading image into Kind cluster '${CLUSTER_NAME}'..."
    kind load docker-image "${FULL_IMAGE}" --name "${CLUSTER_NAME}"

    log_info "Updating deployment with custom image..."
    helm upgrade kagenti "$REPO_ROOT/charts/kagenti" -n kagenti-system \
        --reuse-values --no-hooks \
        --set "${DEP_HELM_SET}.repository=ghcr.io/${DEP_REPO}/${DEP_IMAGE_NAME}" \
        --set "${DEP_HELM_SET}.tag=local" \
        --set "${DEP_HELM_SET}.pullPolicy=Never" || true
fi

# Restart the deployment to pick up the new image.
# Try exact name first, then fall back to finding any deployment in the namespace.
DEPLOY_NAME="${DEP_IMAGE_NAME}"
if kubectl get deployment "$DEPLOY_NAME" -n "$DEP_DEPLOY_NS" &>/dev/null; then
    log_info "Restarting deployment ${DEPLOY_NAME}..."
    kubectl rollout restart deployment/"$DEPLOY_NAME" -n "$DEP_DEPLOY_NS"
    kubectl rollout status deployment/"$DEPLOY_NAME" -n "$DEP_DEPLOY_NS" --timeout=120s
else
    FOUND_DEPLOY=$(kubectl get deployments -n "$DEP_DEPLOY_NS" -o name 2>/dev/null | head -1)
    if [ -n "$FOUND_DEPLOY" ]; then
        log_info "Restarting ${FOUND_DEPLOY} in ${DEP_DEPLOY_NS}..."
        kubectl rollout restart "$FOUND_DEPLOY" -n "$DEP_DEPLOY_NS"
        kubectl rollout status "$FOUND_DEPLOY" -n "$DEP_DEPLOY_NS" --timeout=120s
    else
        log_info "No deployment found in ${DEP_DEPLOY_NS}, helm upgrade handles the rollout"
    fi
fi

# Clean up
rm -rf "$CLONE_DIR"

log_success "${DEP_IMAGE_NAME} built from ${DEP_REPO}@${DEP_REF} and deployed"
