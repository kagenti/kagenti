#!/bin/bash
set -euo pipefail

IMAGE="${ROSSCORTEX_IMAGE:-quay.io/aslomnet/rosscortex:latest}"

echo "Pushing: $IMAGE"
docker push "$IMAGE"

echo ""
echo "Pushed: $IMAGE"
echo ""
echo "IMPORTANT: Make the image public at:"
echo "  https://quay.io/repository/aslomnet/rosscortex?tab=settings"
echo "  → Change Repository Visibility to 'Public'"
