#!/usr/bin/env bash
# Access UI Script - Provides access information for Kagenti UI
# Usage: ./.github/scripts/kind/access-ui.sh

set -euo pipefail

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

echo ""
echo "╔════════════════════════════════════════════════════════════════╗"
echo "║              Kagenti UI Access Information                    ║"
echo "╚════════════════════════════════════════════════════════════════╝"
echo ""

# Check if platform is running
if ! kubectl get namespace kagenti-system &> /dev/null; then
    echo -e "${RED}✗ Platform not deployed${NC}"
    echo "  Run: ./.github/scripts/kind/deploy-platform.sh"
    exit 1
fi

# Check if UI is deployed
if ! kubectl get deployment -n kagenti-system kagenti-ui &> /dev/null; then
    echo -e "${YELLOW}⚠ Kagenti UI not deployed yet${NC}"
    echo ""
    echo "The UI is deployed as part of the platform but may take a few minutes."
    echo "Check status with:"
    echo "  kubectl get pods -n kagenti-system"
    echo ""
fi

echo -e "${GREEN}Platform Services:${NC}"
echo ""

# Get Keycloak status and credentials
KEYCLOAK_STATUS=$(kubectl get pods -n keycloak -l app.kubernetes.io/name=keycloak -o jsonpath='{.items[0].status.phase}' 2>/dev/null || echo "Not Found")
KEYCLOAK_USER=$(kubectl get secret -n keycloak keycloak-initial-admin -o jsonpath='{.data.username}' 2>/dev/null | base64 -d || echo "N/A")
KEYCLOAK_PASS=$(kubectl get secret -n keycloak keycloak-initial-admin -o jsonpath='{.data.password}' 2>/dev/null | base64 -d || echo "N/A")

echo -e "${BLUE}Keycloak Admin Console:${NC}"
echo "  Status:     $KEYCLOAK_STATUS"
echo -e "  Username:   ${GREEN}$KEYCLOAK_USER${NC}"
echo -e "  Password:   ${GREEN}$KEYCLOAK_PASS${NC}"
echo "  Admin URL:  http://keycloak.localtest.me:8080"
echo "  Port-forward: kubectl port-forward -n keycloak svc/keycloak-service 8080:8080"
echo ""

# Get UI status
UI_STATUS=$(kubectl get pods -n kagenti-system -l app=kagenti-ui -o jsonpath='{.items[0].status.phase}' 2>/dev/null || echo "Not Found")
echo -e "${BLUE}Kagenti UI:${NC}"
echo "  Status:   $UI_STATUS"
echo -e "  Login:    ${GREEN}Use Keycloak credentials above (admin/admin)${NC}"
echo "  URL:      http://kagenti-ui.localtest.me:8080"
echo "  Port-forward: kubectl port-forward -n kagenti-system svc/http-istio 8080:80"
echo ""

# Get agent status
AGENT_STATUS=$(kubectl get pods -n team1 -l app.kubernetes.io/name=weather-service -o jsonpath='{.items[0].status.phase}' 2>/dev/null || echo "Not Found")
echo -e "${BLUE}Weather Agent:${NC}"
echo "  Status:   $AGENT_STATUS"
echo "  Logs:     kubectl logs -n team1 deployment/weather-service --tail=100 -f"
echo ""

TOOL_STATUS=$(kubectl get pods -n team1 -l app.kubernetes.io/name=weather-tool -o jsonpath='{.items[0].status.phase}' 2>/dev/null || echo "Not Found")
echo -e "${BLUE}Weather Tool:${NC}"
echo "  Status:   $TOOL_STATUS"
echo "  Logs:     kubectl logs -n team1 deployment/weather-tool --tail=100 -f"
echo ""

# Ollama status
if pgrep -x "ollama" > /dev/null; then
    echo -e "${BLUE}Ollama:${NC}"
    echo "  Status:   Running"
    echo "  URL:      http://localhost:11434"
    echo "  Models:   $(ollama list | grep qwen2.5 | awk '{print $1}' || echo 'None')"
    echo ""
fi

echo "╔════════════════════════════════════════════════════════════════╗"
echo "║                  Port-Forward Status                          ║"
echo "╚════════════════════════════════════════════════════════════════╝"
echo ""

# Check for running port-forwards
UI_PF=$(pgrep -fl "port-forward.*http-istio.*8080" || echo "")
KEYCLOAK_PF=$(pgrep -fl "port-forward.*keycloak.*8080" || echo "")

if [ -n "$UI_PF" ]; then
    echo -e "${GREEN}✓ UI port-forward is running${NC}"
    echo "  $UI_PF"
else
    echo -e "${YELLOW}⚠ UI port-forward is NOT running${NC}"
    echo "  Start with: kubectl port-forward -n kagenti-system svc/http-istio 8080:80 &"
fi
echo ""

if [ -n "$KEYCLOAK_PF" ]; then
    echo -e "${GREEN}✓ Keycloak port-forward is running${NC}"
    echo "  $KEYCLOAK_PF"
else
    echo -e "${YELLOW}⚠ Keycloak port-forward is NOT running (optional)${NC}"
    echo "  Start with: kubectl port-forward -n keycloak svc/keycloak-service 8081:8080 &"
fi
echo ""

echo "╔════════════════════════════════════════════════════════════════╗"
echo "║                  Quick Actions                                ║"
echo "╚════════════════════════════════════════════════════════════════╝"
echo ""
echo "Start all port-forwards:"
echo "  kubectl port-forward -n kagenti-system svc/http-istio 8080:80 > /tmp/pf-ui.log 2>&1 &"
echo "  kubectl port-forward -n keycloak svc/keycloak-service 8081:8080 > /tmp/pf-keycloak.log 2>&1 &"
echo ""
echo "Access Kagenti UI:"
echo "  1. Ensure port-forward is running (see above)"
echo "  2. Visit: http://kagenti-ui.localtest.me:8080"
echo -e "  3. Login with: ${GREEN}admin / admin${NC}"
echo ""
echo "Troubleshooting 'Restart login cookie not found' error:"
echo "  - Make sure port-forward is running on port 8080"
echo "  - Try clearing browser cookies for localtest.me"
echo "  - Access http://kagenti-ui.localtest.me:8080 (not https)"
echo "  - Check UI logs: kubectl logs -n kagenti-system deployment/kagenti-ui --tail=50"
echo ""
echo "View all pods:"
echo "  kubectl get pods -A"
echo ""
echo "Run tests:"
echo "  ./.github/scripts/kind/run-e2e-tests.sh"
echo ""
