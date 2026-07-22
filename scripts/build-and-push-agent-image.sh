#!/usr/bin/env bash
# Build the AI-agents image from Dockerfile-agent and push it to quay.io.
# Uses docker if available, otherwise falls back to podman.
#
#   ./build-and-push-agent-image.sh                 # build + push quay.io/aslomnet/agents:test
#   IMAGE=quay.io/you/agents:dev ./build-and-push-agent-image.sh
#   RUNTIME=podman ./build-and-push-agent-image.sh  # force a runtime
#   ./build-and-push-agent-image.sh --no-push       # build only
set -euo pipefail
cd "$(dirname "$0")"

IMAGE="${IMAGE:-quay.io/aslomnet/agents:test}"
DOCKERFILE="${DOCKERFILE:-Dockerfile-agent}"
PUSH=1
[ "${1:-}" = "--no-push" ] && PUSH=0

# Pick a container runtime: explicit RUNTIME wins, else prefer docker, else podman.
if [ -n "${RUNTIME:-}" ]; then
  command -v "$RUNTIME" >/dev/null 2>&1 || { echo "ERROR: RUNTIME=$RUNTIME not found on PATH" >&2; exit 1; }
elif command -v docker >/dev/null 2>&1; then
  RUNTIME=docker
elif command -v podman >/dev/null 2>&1; then
  RUNTIME=podman
else
  echo "ERROR: neither docker nor podman found on PATH" >&2
  exit 1
fi

echo "==> runtime: $RUNTIME"
echo "==> image:   $IMAGE"
echo "==> build:   $DOCKERFILE"

"$RUNTIME" build -f "$DOCKERFILE" -t "$IMAGE" .

if [ "$PUSH" -eq 1 ]; then
  echo "==> pushing $IMAGE"
  "$RUNTIME" push "$IMAGE"
  echo "OK: pushed $IMAGE"
else
  echo "OK: built $IMAGE (skipped push)"
fi
