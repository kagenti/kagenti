#!/usr/bin/env bash
# Destroy Kind Cluster Script - Deletes Kind cluster for Kagenti testing
# Usage: ./.github/scripts/kind/destroy-cluster.sh [cluster-name]

set -euo pipefail

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

CLUSTER_NAME="${1:-${CLUSTER_NAME:-kagenti}}"

echo ""
echo "╔════════════════════════════════════════════════════════════════╗"
echo "║         Kagenti Kind Cluster Cleanup                          ║"
echo "╚════════════════════════════════════════════════════════════════╝"
echo ""
echo -e "${BLUE}Cluster: ${CLUSTER_NAME}${NC}"
echo ""

# Check if cluster exists
if kind get clusters 2>/dev/null | grep -q "^${CLUSTER_NAME}$"; then
    echo -e "${YELLOW}→ Deleting Kind cluster '${CLUSTER_NAME}'...${NC}"
    kind delete cluster --name "${CLUSTER_NAME}"
    echo -e "${GREEN}✓ Cluster deleted${NC}"
else
    echo -e "${BLUE}ℹ️  Cluster '${CLUSTER_NAME}' does not exist${NC}"
fi

# Clean up any orphaned Docker volumes/networks
echo ""
echo -e "${YELLOW}→ Cleaning up Docker resources...${NC}"
docker system prune -f --volumes 2>/dev/null || true
echo -e "${GREEN}✓ Docker cleanup complete${NC}"

echo ""
echo -e "${GREEN}✨ Cleanup complete!${NC}"
echo ""
echo "Next steps:"
echo "  1. Create cluster:  ./.github/scripts/kind/create-cluster.sh"
echo "  2. Deploy platform: ./.github/scripts/kind/deploy-platform.sh"
echo "  3. Run E2E tests:   ./.github/scripts/kind/run-e2e-tests.sh"
echo ""
