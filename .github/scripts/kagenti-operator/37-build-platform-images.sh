#!/usr/bin/env bash
#
# Build Kagenti backend and UI images from source
#
# Builds backend and UI container images on-cluster using OpenShift BuildConfig,
# then patches the deployments to use the freshly built images. This ensures
# E2E tests run against the actual code from the current branch, not stock images.
#
# Prerequisites:
#   - OpenShift cluster with Build API available
#   - KUBECONFIG set to the hosted cluster
#
# Usage:
#   ./.github/scripts/kagenti-operator/37-build-platform-images.sh
#
# Environment:
#   GIT_REPO_URL:    Git repo URL (default: auto-detect from git remote)
#   GIT_BRANCH:      Branch to build (default: auto-detect from current branch)
#   SKIP_BUILD:      Set to "true" to skip (uses stock images)
#
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
source "$SCRIPT_DIR/../lib/env-detect.sh"
source "$SCRIPT_DIR/../lib/logging.sh"
source "$SCRIPT_DIR/../lib/k8s-utils.sh"

log_step "37" "Building platform images from source"

if [ "${SKIP_BUILD:-false}" = "true" ]; then
    log_info "SKIP_BUILD=true — using stock images"
    exit 0
fi

if [ "$IS_OPENSHIFT" != "true" ]; then
    log_info "Not OpenShift — skipping on-cluster build (use stock images)"
    exit 0
fi

NS="kagenti-system"
REGISTRY="image-registry.openshift-image-registry.svc:5000/$NS"

# Auto-detect git repo and branch
GIT_REPO_URL="${GIT_REPO_URL:-}"
GIT_BRANCH="${GIT_BRANCH:-}"

if [ -z "$GIT_REPO_URL" ]; then
    # Try to get the push URL from git remote
    GIT_REPO_URL=$(git -C "$REPO_ROOT" remote get-url origin 2>/dev/null | sed 's|git@github.com:|https://github.com/|' || echo "")
    if [ -z "$GIT_REPO_URL" ]; then
        log_info "Could not detect git remote — skipping source build"
        exit 0
    fi
fi

if [ -z "$GIT_BRANCH" ]; then
    GIT_BRANCH=$(git -C "$REPO_ROOT" branch --show-current 2>/dev/null || echo "main")
fi

log_info "Building from: $GIT_REPO_URL @ $GIT_BRANCH"

# Components to build: name:dockerfile:tag
# Dockerfiles expect context=kagenti/ (e.g. COPY backend/pyproject.toml)
CONTEXT_DIR="kagenti"
COMPONENTS=(
    "kagenti-backend:backend/Dockerfile:worktree"
    "kagenti-ui:ui-v2/Dockerfile:worktree"
)

for COMPONENT_SPEC in "${COMPONENTS[@]}"; do
    IFS=: read -r NAME DOCKERFILE TAG <<< "$COMPONENT_SPEC"

    log_info "Building $NAME..."

    # Create ImageStream if needed
    oc create imagestream "$NAME" -n "$NS" 2>/dev/null || true

    # Create/update BuildConfig
    cat <<EOF | kubectl apply -f -
apiVersion: build.openshift.io/v1
kind: BuildConfig
metadata:
  name: $NAME
  namespace: $NS
spec:
  output:
    to:
      kind: ImageStreamTag
      name: $NAME:$TAG
  source:
    type: Git
    git:
      uri: $GIT_REPO_URL
      ref: $GIT_BRANCH
    contextDir: $CONTEXT_DIR
  strategy:
    type: Docker
    dockerStrategy:
      dockerfilePath: $DOCKERFILE
EOF

    # Start build
    BUILD_NAME=$(oc start-build "$NAME" -n "$NS" -o name 2>&1)
    log_info "$BUILD_NAME started"

    # Wait for build to complete
    run_with_timeout 600 "oc wait --for=jsonpath='{.status.phase}'=Complete $BUILD_NAME -n $NS --timeout=600s" || {
        log_error "$NAME build failed"
        oc logs "$BUILD_NAME" -n "$NS" 2>&1 | tail -30 || true
        exit 1
    }
    log_success "$NAME image built"

    # Patch deployment to use the new image
    CONTAINER_NAME=$(kubectl get deployment "$NAME" -n "$NS" -o jsonpath='{.spec.template.spec.containers[0].name}' 2>/dev/null || echo "")
    if [ -n "$CONTAINER_NAME" ]; then
        kubectl set image "deployment/$NAME" -n "$NS" "$CONTAINER_NAME=$REGISTRY/$NAME:$TAG"
        log_info "Patched $NAME deployment → $REGISTRY/$NAME:$TAG"
    else
        log_warn "Deployment $NAME not found — skipping patch"
    fi
done

# Restart and wait for rollouts
for COMPONENT_SPEC in "${COMPONENTS[@]}"; do
    IFS=: read -r NAME _ _ <<< "$COMPONENT_SPEC"
    if kubectl get deployment "$NAME" -n "$NS" &>/dev/null; then
        kubectl rollout restart "deployment/$NAME" -n "$NS"
    fi
done

for COMPONENT_SPEC in "${COMPONENTS[@]}"; do
    IFS=: read -r NAME _ _ <<< "$COMPONENT_SPEC"
    if kubectl get deployment "$NAME" -n "$NS" &>/dev/null; then
        kubectl rollout status "deployment/$NAME" -n "$NS" --timeout=120s || {
            log_error "$NAME rollout failed"
            kubectl get pods -n "$NS" -l "app.kubernetes.io/name=$NAME" 2>&1
            exit 1
        }
    fi
done

log_success "Platform images built and deployed from source"
