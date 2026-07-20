#!/usr/bin/env bash
# Build rossoctl-operator image from source.
#
# Environment:
#   ROSSOCTL_OPERATOR_ROOT   Local clone (optional; clones from GitHub if unset)
#   ROSSOCTL_OPERATOR_REF    Git ref to clone (default: main)
#   PLATFORM                "kind" or "ocp" (auto-detected if unset)
set -euo pipefail
source "$(dirname "$0")/lib.sh"

log_step "20" "Build rossoctl-operator image"

PLATFORM="${PLATFORM:-$(detect_platform)}"
OPERATOR_REF="${ROSSOCTL_OPERATOR_REF:-main}"
OP_ROOT="${ROSSOCTL_OPERATOR_ROOT:-}"
CLONE_DIR=""

if [[ -z "$OP_ROOT" ]]; then
  CLONE_DIR="${TMPDIR:-/tmp}/rossoctl-operator-tx-e2e-$$"
  log_info "Cloning rossoctl-operator (ref: $OPERATOR_REF)"
  git clone --depth 1 --single-branch --branch "$OPERATOR_REF" \
    "https://github.com/rossoctl/operator.git" "$CLONE_DIR" 2>/dev/null || \
  git clone "https://github.com/rossoctl/operator.git" "$CLONE_DIR" && \
    (cd "$CLONE_DIR" && git checkout "$OPERATOR_REF")
  OP_ROOT="$CLONE_DIR"
fi

REGISTRY="ghcr.io/rossoctl/operator"
IMG_NAME="rossoctl-operator"

log_info "Building $IMG_NAME from $OP_ROOT"

if [[ "$PLATFORM" == "kind" ]]; then
  docker build -t "${REGISTRY}/${IMG_NAME}:latest" \
    -f "$OP_ROOT/Dockerfile" "$OP_ROOT"

  # Tag with pinned version from Chart.yaml subchart
  PINNED_VER=$(grep -A5 'operator-chart' "$REPO_ROOT/charts/rossoctl/Chart.yaml" | grep 'version:' | head -1 | awk '{print $2}')
  if [[ -n "$PINNED_VER" ]]; then
    docker tag "${REGISTRY}/${IMG_NAME}:latest" "${REGISTRY}/${IMG_NAME}:v${PINNED_VER}"
    kind load docker-image "${REGISTRY}/${IMG_NAME}:v${PINNED_VER}" --name "${KIND_CLUSTER_NAME:-kind}" 2>/dev/null || true
  fi
  kind load docker-image "${REGISTRY}/${IMG_NAME}:latest" --name "${KIND_CLUSTER_NAME:-kind}" 2>/dev/null || true

elif [[ "$PLATFORM" == "ocp" ]]; then
  BUILD_NS="rossoctl-system"
  oc new-build --name "tx-${IMG_NAME}" --binary --strategy docker \
    --to="image-registry.openshift-image-registry.svc:5000/${BUILD_NS}/${IMG_NAME}:latest" \
    -n "$BUILD_NS" 2>/dev/null || true
  oc start-build "tx-${IMG_NAME}" --from-dir="$OP_ROOT" \
    --follow -n "$BUILD_NS"
fi

# Cleanup
if [[ -n "$CLONE_DIR" && -d "$CLONE_DIR" ]]; then
  rm -rf "$CLONE_DIR"
fi

log_success "rossoctl-operator image built"
