#!/usr/bin/env bash
# Deploy Platform Script - Deploys Kagenti to Kind cluster
# Mirrors GitHub Actions workflows by calling the same scripts
# Usage: ./.github/scripts/kind/deploy-platform.sh

set -euo pipefail

# Colors for output (some may be unused but kept for consistency)
# shellcheck disable=SC2034
GREEN='\033[0;32m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# Script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"

echo ""
echo "======================================================================="
echo "   Kagenti Platform Local Deployment (Kagenti Operator)               "
echo "======================================================================="
echo ""
echo -e "${CYAN}Calling the same scripts as CI workflow${NC}"
echo ""

cd "$REPO_ROOT"

# ============================================================================
# DEPLOYMENT STEPS (mirrors CI workflow order)
# ============================================================================

# Step 1: Create secrets (wave 20)
echo -e "${BLUE}[1/11] Creating secrets...${NC}"
bash .github/scripts/common/20-create-secrets.sh
echo ""

# Step 2: Run installer (wave 30)
echo -e "${BLUE}[2/11] Running Ansible installer...${NC}"
bash .github/scripts/kagenti-operator/30-run-installer.sh
echo ""

# Step 3: Wait for platform ready (wave 40)
echo -e "${BLUE}[3/11] Waiting for platform to be ready...${NC}"
bash .github/scripts/common/40-wait-platform-ready.sh
echo ""

# Step 4: Install Ollama (wave 50)
echo -e "${BLUE}[4/11] Installing Ollama...${NC}"
bash .github/scripts/common/50-install-ollama.sh
echo ""

# Step 5: Pull Ollama model (wave 60)
echo -e "${BLUE}[5/11] Pulling Ollama model...${NC}"
bash .github/scripts/common/60-pull-ollama-model.sh
echo ""

# Step 6: Configure dockerhost (wave 70)
echo -e "${BLUE}[6/11] Configuring dockerhost service...${NC}"
bash .github/scripts/common/70-configure-dockerhost.sh
echo ""

# ============================================================================
# KAGENTI OPERATOR SPECIFIC STEPS
# ============================================================================

echo -e "${BLUE}[7/11] Waiting for kagenti-operator CRDs...${NC}"
bash .github/scripts/kagenti-operator/41-wait-crds.sh
echo ""

echo -e "${BLUE}[8/11] Applying pipeline-template-dev ConfigMap...${NC}"
bash .github/scripts/kagenti-operator/42-apply-pipeline-template.sh
echo ""

echo -e "${BLUE}[9/11] Waiting for Toolhive CRDs...${NC}"
bash .github/scripts/kagenti-operator/43-wait-toolhive-crds.sh
echo ""

echo -e "${BLUE}[10/11] Building and deploying weather-tool...${NC}"
bash .github/scripts/kagenti-operator/71-build-weather-tool.sh
bash .github/scripts/kagenti-operator/72-deploy-weather-tool.sh
bash .github/scripts/kagenti-operator/73-patch-weather-tool.sh
echo ""

echo -e "${BLUE}[11/11] Deploying weather-service Agent...${NC}"
bash .github/scripts/kagenti-operator/74-deploy-weather-agent.sh
echo ""

# ============================================================================
# DEPLOYMENT COMPLETE
# ============================================================================

echo "======================================================================="
echo "                     Deployment Complete                               "
echo "======================================================================="
echo ""
kubectl get pods -A | grep -E "NAMESPACE|team1|kagenti-system|keycloak|ollama"
echo ""
echo -e "${GREEN}Platform deployed successfully!${NC}"
echo ""
echo "Next steps:"
echo "  1. Run E2E tests:  ./.github/scripts/kind/run-e2e-tests.sh"
echo "  2. Access UI:      ./.github/scripts/kind/access-ui.sh"
echo "  3. View logs:      kubectl logs -n team1 deployment/weather-service --tail=100"
echo ""
