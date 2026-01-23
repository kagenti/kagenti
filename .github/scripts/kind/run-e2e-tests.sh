#!/usr/bin/env bash
# Run E2E Tests Script - Runs Kagenti E2E tests locally
# Mirrors GitHub Actions test execution by calling the same scripts
# Usage:
#   ./.github/scripts/kind/run-e2e-tests.sh
#   KAGENTI_CONFIG_FILE=deployments/envs/dev_values.yaml ./.github/scripts/kind/run-e2e-tests.sh

set -euo pipefail

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"

echo ""
echo "======================================================================="
echo "              Kagenti E2E Tests (Local)                                "
echo "======================================================================="
echo ""

# Check if platform is running
echo -e "${BLUE}Checking platform status...${NC}"
if ! kubectl get namespace kagenti-system &> /dev/null; then
    echo -e "${RED}Platform not deployed${NC}"
    echo "  Run: ./.github/scripts/kind/deploy-platform.sh"
    exit 1
fi
echo -e "${GREEN}Platform is deployed${NC}"
echo ""

# Set config file if not provided
if [ -z "${KAGENTI_CONFIG_FILE:-}" ]; then
    KAGENTI_CONFIG_FILE="$REPO_ROOT/deployments/envs/dev_values.yaml"
    export KAGENTI_CONFIG_FILE
    echo -e "${BLUE}Using config: ${KAGENTI_CONFIG_FILE}${NC}"
else
    echo -e "${BLUE}Using provided KAGENTI_CONFIG_FILE: ${KAGENTI_CONFIG_FILE}${NC}"
    export KAGENTI_CONFIG_FILE
fi
echo ""

cd "$REPO_ROOT"

# ============================================================================
# TEST PREPARATION (mirrors CI workflow order)
# ============================================================================

# Step 1: Install test dependencies (wave 80)
echo -e "${BLUE}[1/3] Installing test dependencies...${NC}"
bash .github/scripts/common/80-install-test-deps.sh
echo ""

# Step 2: Start port-forward (wave 85)
echo -e "${BLUE}[2/3] Starting port-forward...${NC}"
bash .github/scripts/common/85-start-port-forward.sh
echo ""

# Step 3: Run E2E tests (wave 90)
echo -e "${BLUE}[3/3] Running E2E tests...${NC}"
echo ""

bash .github/scripts/kagenti-operator/90-run-e2e-tests.sh

TEST_RESULT=$?

# ============================================================================
# CLEANUP AND RESULTS
# ============================================================================

echo ""
if [ $TEST_RESULT -eq 0 ]; then
    echo -e "${GREEN}All tests passed!${NC}"
else
    echo -e "${RED}Some tests failed${NC}"
    echo ""
    echo "Debugging tips:"
    echo "  1. Check agent logs:"
    echo "     kubectl logs -n team1 deployment/weather-service --tail=100"
    echo ""
    echo "  2. Check tool logs:"
    echo "     kubectl logs -n team1 deployment/weather-tool --tail=100"
    echo ""
    echo "  3. Check pod status:"
    echo "     kubectl get pods -n team1"
    echo ""
    echo "  4. View events:"
    echo "     kubectl get events -n team1 --sort-by='.lastTimestamp' | tail -30"
    echo ""
fi

exit $TEST_RESULT
