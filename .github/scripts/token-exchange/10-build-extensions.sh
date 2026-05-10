#!/usr/bin/env bash
# Build kagenti-extensions images from source.
#
# Environment:
#   KAGENTI_EXTENSIONS_ROOT   Local clone (optional; clones from GitHub if unset)
#   KAGENTI_EXTENSIONS_REF    Git ref to clone (default: main)
#   PLATFORM                  "kind" or "ocp" (auto-detected if unset)
set -euo pipefail
source "$(dirname "$0")/lib.sh"

log_step "10" "Build kagenti-extensions images"

PLATFORM="${PLATFORM:-$(detect_platform)}"
EXTENSIONS_REF="${KAGENTI_EXTENSIONS_REF:-main}"
EXT_ROOT="${KAGENTI_EXTENSIONS_ROOT:-}"
CLONE_DIR=""

if [[ -z "$EXT_ROOT" ]]; then
  CLONE_DIR="${TMPDIR:-/tmp}/kagenti-extensions-tx-e2e-$$"
  log_info "Cloning kagenti-extensions (ref: $EXTENSIONS_REF)"
  git clone --depth 1 --single-branch --branch "$EXTENSIONS_REF" \
    "https://github.com/kagenti/kagenti-extensions.git" "$CLONE_DIR" 2>/dev/null || \
  git clone "https://github.com/kagenti/kagenti-extensions.git" "$CLONE_DIR" && \
    (cd "$CLONE_DIR" && git checkout "$EXTENSIONS_REF")
  EXT_ROOT="$CLONE_DIR"
fi

# Images to build
IMAGES=(
  "authbridge-envoy:authbridge:cmd/authbridge/Dockerfile"
  "authbridge-light:authbridge:cmd/authbridge/Dockerfile.light"
  "proxy-init:authbridge/authproxy:Dockerfile.init"
  "client-registration:authbridge/client-registration:Dockerfile"
  "spiffe-helper:authbridge/spiffe-helper:Dockerfile"
)

REGISTRY="ghcr.io/kagenti/kagenti-extensions"

# Extract pinned tags from values.yaml so locally-built images replace them
PINNED_TAGS=()
VALUES_FILE="$REPO_ROOT/charts/kagenti/values.yaml"
for tag in $(grep -oP '(?<=kagenti-extensions/)[^:]+:\S+' "$VALUES_FILE" 2>/dev/null | sort -u); do
  img="${tag%%:*}"
  ver="${tag#*:}"
  PINNED_TAGS+=("${img}:${ver}")
done

for entry in "${IMAGES[@]}"; do
  IFS=: read -r img_name context dockerfile <<< "$entry"
  log_info "Building $img_name from $EXT_ROOT/$context ($dockerfile)"

  if [[ "$PLATFORM" == "kind" ]]; then
    docker build -t "${REGISTRY}/${img_name}:latest" \
      -f "$EXT_ROOT/$context/$dockerfile" \
      "$EXT_ROOT/$context"

    # Tag with all pinned versions so helm uses the local image
    for ptag in "${PINNED_TAGS[@]}"; do
      pimg="${ptag%%:*}"
      pver="${ptag#*:}"
      if [[ "$pimg" == "$img_name" ]]; then
        docker tag "${REGISTRY}/${img_name}:latest" "${REGISTRY}/${img_name}:${pver}"
        kind load docker-image "${REGISTRY}/${img_name}:${pver}" --name "${KIND_CLUSTER_NAME:-kind}" 2>/dev/null || true
      fi
    done
    kind load docker-image "${REGISTRY}/${img_name}:latest" --name "${KIND_CLUSTER_NAME:-kind}" 2>/dev/null || true

  elif [[ "$PLATFORM" == "ocp" ]]; then
    BUILD_NS="kagenti-system"
    oc new-build --name "tx-${img_name}" --binary --strategy docker \
      --to="image-registry.openshift-image-registry.svc:5000/${BUILD_NS}/${img_name}:latest" \
      -n "$BUILD_NS" 2>/dev/null || true
    oc start-build "tx-${img_name}" --from-dir="$EXT_ROOT/$context" \
      --follow -n "$BUILD_NS"
  fi
  log_success "$img_name built"
done

# Cleanup
if [[ -n "$CLONE_DIR" && -d "$CLONE_DIR" ]]; then
  rm -rf "$CLONE_DIR"
fi

log_success "All kagenti-extensions images built"
