#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
IMAGE="${ROSSCORTEX_IMAGE:-quay.io/aslomnet/rosscortex:latest}"
EXT_DIR="${KAGENTI_EXTENSIONS_DIR:-$(cd "$SCRIPT_DIR/../../.." && pwd)/kagenti-extensions}"

echo "Building rosscortex container image: $IMAGE"

# Step 1: Build authbridge-proxy binary for Linux using local Go
echo "--- Step 1: Building authbridge-proxy binary ---"

if [ ! -d "$EXT_DIR/authbridge/cmd/authbridge-proxy" ]; then
    echo "ERROR: kagenti-extensions not found at $EXT_DIR"
    echo "Set KAGENTI_EXTENSIONS_DIR or clone it next to this repo."
    exit 1
fi

# Check for placeholderresolve plugin
if [ ! -d "$EXT_DIR/authbridge/authlib/plugins/placeholderresolve" ]; then
    echo "Fetching placeholderresolve plugin from huang195 fork..."
    (cd "$EXT_DIR" && \
     git remote add huang195 https://github.com/huang195/kagenti-extensions.git 2>/dev/null || true && \
     git fetch huang195 feat/placeholder-resolve-plugin && \
     git checkout huang195/feat/placeholder-resolve-plugin -- \
       authbridge/authlib/plugins/placeholderresolve \
       authbridge/authlib/credinject \
       authbridge/authlib/openshell \
       authbridge/cmd/authbridge-proxy/plugins_placeholderresolve.go)
fi

GOARCH="$(uname -m | sed 's/x86_64/amd64/' | sed 's/arm64/arm64/' | sed 's/aarch64/arm64/')"
COMMIT="$(git -C "$EXT_DIR" rev-parse --short HEAD)"

mkdir -p "$SCRIPT_DIR/bin"
echo "  Source: $EXT_DIR (commit $COMMIT)"
echo "  Target: linux/$GOARCH"

CGO_ENABLED=0 GOOS=linux GOARCH="$GOARCH" \
  go build -C "$EXT_DIR/authbridge" \
  -ldflags="-s -w -X main.version=rosscortex-$COMMIT" \
  -o "$SCRIPT_DIR/bin/authbridge-proxy-linux" \
  ./cmd/authbridge-proxy

echo "  Binary: $SCRIPT_DIR/bin/authbridge-proxy-linux"

# Step 2: Build container image
echo "--- Step 2: Building container image ---"
docker build -t "$IMAGE" "$SCRIPT_DIR"

echo ""
echo "Built: $IMAGE"
echo "  authbridge commit: $COMMIT"
echo ""
echo "Run:"
echo "  docker run --rm -p 3128:3128 -p 8080:8080 \\"
echo "    -e ANTHROPIC_AUTH_TOKEN=sk-ant-... \\"
echo "    $IMAGE"
