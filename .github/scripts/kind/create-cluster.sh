#!/usr/bin/env bash
# Create Kind Cluster Script - Creates a Kind cluster for Kagenti testing
# Usage: ./kind/create-cluster.sh [cluster-name]

set -euo pipefail

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"

CLUSTER_NAME="${1:-${CLUSTER_NAME:-kagenti}}"
KIND_CONFIG="${KIND_CONFIG:-$REPO_ROOT/deployments/ansible/kind/kind-config-registry.yaml}"

echo ""
echo "======================================================================="
echo "              Kagenti Kind Cluster Creation                            "
echo "======================================================================="
echo ""
echo -e "${BLUE}Cluster Name: ${CLUSTER_NAME}${NC}"
echo -e "${BLUE}Kind Config:  ${KIND_CONFIG}${NC}"
echo ""

# Check if cluster already exists
if kind get clusters 2>/dev/null | grep -q "^${CLUSTER_NAME}$"; then
    echo -e "${YELLOW}Cluster '${CLUSTER_NAME}' already exists${NC}"
    echo ""
    echo "Options:"
    echo "  1. Use existing cluster (continue)"
    echo "  2. Delete and recreate: ./.github/scripts/kind/destroy-cluster.sh && ./.github/scripts/kind/create-cluster.sh"
    echo ""
    exit 0
fi

# Check if Kind config exists
if [ ! -f "$KIND_CONFIG" ]; then
    echo -e "${RED}Kind config not found: ${KIND_CONFIG}${NC}"
    exit 1
fi

# Create cluster
echo -e "${YELLOW}-> Creating Kind cluster '${CLUSTER_NAME}'...${NC}"
kind create cluster --name "${CLUSTER_NAME}" --config "${KIND_CONFIG}"

echo ""
echo -e "${GREEN}Cluster created successfully!${NC}"
echo ""

# Verify cluster
echo -e "${BLUE}Verifying cluster...${NC}"
kubectl cluster-info --context "kind-${CLUSTER_NAME}"

echo ""
echo -e "${GREEN}Cluster '${CLUSTER_NAME}' is ready!${NC}"
echo ""
echo "Next steps:"
echo "  1. Deploy platform: ./.github/scripts/kind/deploy-platform.sh"
echo "  2. Run E2E tests:   ./.github/scripts/kind/run-e2e-tests.sh"
echo ""
