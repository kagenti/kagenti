#!/usr/bin/env bash
# Show Services Script - Display all Kagenti services, URLs, and credentials
# Usage: ./local-testing/show-services.sh

set -euo pipefail

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
MAGENTA='\033[0;35m'
NC='\033[0m' # No Color

echo ""
echo "╔════════════════════════════════════════════════════════════════╗"
echo "║           Kagenti Platform Services & Credentials             ║"
echo "╚════════════════════════════════════════════════════════════════╝"
echo ""

# Check if platform is running
if ! kubectl get namespace kagenti-system &> /dev/null; then
    echo -e "${RED}✗ Platform not deployed${NC}"
    echo "  Run: ./local-testing/deploy-platform.sh"
    exit 1
fi

echo -e "${CYAN}═══════════════════════════════════════════════════════════════${NC}"
echo -e "${MAGENTA}1. Keycloak (Identity & Access Management)${NC}"
echo -e "${CYAN}═══════════════════════════════════════════════════════════════${NC}"

KEYCLOAK_STATUS=$(kubectl get pods -n keycloak -l app.kubernetes.io/name=keycloak -o jsonpath='{.items[0].status.phase}' 2>/dev/null || echo "Not Found")
echo -e "${BLUE}Status:${NC}      $KEYCLOAK_STATUS"
echo -e "${BLUE}Access URL:${NC}  http://keycloak.localtest.me:8080"
echo ""
echo -e "${YELLOW}Port-forward command:${NC}"
echo "  kubectl port-forward -n keycloak svc/keycloak 8080:8080"
echo ""
echo -e "${GREEN}Credentials:${NC}"

# Try to get admin credentials from secret
KEYCLOAK_ADMIN_USER=$(kubectl get secret -n keycloak keycloak-admin-credentials -o jsonpath='{.data.username}' 2>/dev/null | base64 -d 2>/dev/null || echo "admin")
KEYCLOAK_ADMIN_PASS=$(kubectl get secret -n keycloak keycloak-admin-credentials -o jsonpath='{.data.password}' 2>/dev/null | base64 -d 2>/dev/null || echo "admin")

echo "  Username: ${KEYCLOAK_ADMIN_USER}"
echo "  Password: ${KEYCLOAK_ADMIN_PASS}"
echo ""
echo -e "${YELLOW}Admin Console:${NC}    http://keycloak.localtest.me:8080/admin"
echo -e "${YELLOW}Realm:${NC}            kagenti"
echo ""

echo -e "${CYAN}═══════════════════════════════════════════════════════════════${NC}"
echo -e "${MAGENTA}2. Kagenti UI (Web Dashboard)${NC}"
echo -e "${CYAN}═══════════════════════════════════════════════════════════════${NC}"

UI_STATUS=$(kubectl get pods -n kagenti-system -l app=kagenti-ui -o jsonpath='{.items[0].status.phase}' 2>/dev/null || echo "Not Found")
echo -e "${BLUE}Status:${NC}      $UI_STATUS"
echo -e "${BLUE}Access URL:${NC}  http://kagenti-ui.localtest.me:8080"
echo ""
echo -e "${YELLOW}Port-forward command:${NC}"
echo "  kubectl port-forward -n kagenti-system svc/http-istio 8080:80"
echo ""
echo -e "${GREEN}Authentication:${NC} Via Keycloak OAuth2"
echo "  Click 'Login' and use Keycloak credentials above"
echo ""

echo -e "${CYAN}═══════════════════════════════════════════════════════════════${NC}"
echo -e "${MAGENTA}3. Weather Agent (A2A Protocol)${NC}"
echo -e "${CYAN}═══════════════════════════════════════════════════════════════${NC}"

AGENT_STATUS=$(kubectl get pods -n team1 -l app.kubernetes.io/name=weather-service -o jsonpath='{.items[0].status.phase}' 2>/dev/null || echo "Not Found")
echo -e "${BLUE}Status:${NC}           $AGENT_STATUS"
echo -e "${BLUE}Namespace:${NC}        team1"
echo -e "${BLUE}Service URL:${NC}      http://weather-service.team1.svc.cluster.local:8000"
echo ""
echo -e "${YELLOW}Port-forward command:${NC}"
echo "  kubectl port-forward -n team1 svc/weather-service 8000:8000"
echo ""
echo -e "${YELLOW}Test with A2A client:${NC}"
echo "  AGENT_URL=http://localhost:8000 pytest kagenti/tests/e2e/test_agent_conversation.py -v"
echo ""
echo -e "${YELLOW}View logs:${NC}"
echo "  kubectl logs -n team1 deployment/weather-service --tail=100 -f"
echo ""

echo -e "${CYAN}═══════════════════════════════════════════════════════════════${NC}"
echo -e "${MAGENTA}4. Weather Tool (MCP Protocol)${NC}"
echo -e "${CYAN}═══════════════════════════════════════════════════════════════${NC}"

TOOL_STATUS=$(kubectl get pods -n team1 -l app.kubernetes.io/name=weather-tool -o jsonpath='{.items[0].status.phase}' 2>/dev/null || echo "Not Found")
echo -e "${BLUE}Status:${NC}           $TOOL_STATUS"
echo -e "${BLUE}Namespace:${NC}        team1"
echo -e "${BLUE}Service URL:${NC}      http://weather-tool.team1.svc.cluster.local:8000"
echo ""
echo -e "${YELLOW}Port-forward command:${NC}"
echo "  kubectl port-forward -n team1 svc/weather-tool 8001:8000"
echo ""
echo -e "${YELLOW}View logs:${NC}"
echo "  kubectl logs -n team1 deployment/weather-tool --tail=100 -f"
echo ""

echo -e "${CYAN}═══════════════════════════════════════════════════════════════${NC}"
echo -e "${MAGENTA}5. Ollama (Local LLM)${NC}"
echo -e "${CYAN}═══════════════════════════════════════════════════════════════${NC}"

if pgrep -x "ollama" > /dev/null; then
    echo -e "${BLUE}Status:${NC}           ${GREEN}Running${NC}"
    echo -e "${BLUE}Access URL:${NC}       http://localhost:11434"
    echo ""
    echo -e "${YELLOW}Available models:${NC}"
    ollama list 2>/dev/null || echo "  Unable to list models"
    echo ""
    echo -e "${YELLOW}Test API:${NC}"
    echo "  curl http://localhost:11434/api/tags"
else
    echo -e "${BLUE}Status:${NC}           ${RED}Not Running${NC}"
    echo ""
    echo -e "${YELLOW}Start Ollama:${NC}"
    echo "  ollama serve &"
    echo ""
    echo -e "${YELLOW}Pull model:${NC}"
    echo "  ollama pull qwen2.5:0.5b"
fi
echo ""

echo -e "${CYAN}═══════════════════════════════════════════════════════════════${NC}"
echo -e "${MAGENTA}6. Platform Operator${NC}"
echo -e "${CYAN}═══════════════════════════════════════════════════════════════${NC}"

OPERATOR_STATUS=$(kubectl get pods -n kagenti-system -l app.kubernetes.io/name=kagenti-platform-operator -o jsonpath='{.items[0].status.phase}' 2>/dev/null || echo "Not Found")
echo -e "${BLUE}Status:${NC}           $OPERATOR_STATUS"
echo -e "${BLUE}Namespace:${NC}        kagenti-system"
echo ""
echo -e "${YELLOW}View logs:${NC}"
echo "  kubectl logs -n kagenti-system deployment/kagenti-platform-operator --tail=100 -f"
echo ""
echo -e "${YELLOW}View managed components:${NC}"
echo "  kubectl get components -n team1"
echo ""

echo -e "${CYAN}═══════════════════════════════════════════════════════════════${NC}"
echo -e "${MAGENTA}7. PostgreSQL Database${NC}"
echo -e "${CYAN}═══════════════════════════════════════════════════════════════${NC}"

POSTGRES_STATUS=$(kubectl get pods -n keycloak -l app.kubernetes.io/name=postgresql -o jsonpath='{.items[0].status.phase}' 2>/dev/null || echo "Not Found")
echo -e "${BLUE}Status:${NC}           $POSTGRES_STATUS"
echo -e "${BLUE}Namespace:${NC}        keycloak"
echo -e "${BLUE}Service:${NC}          postgresql.keycloak.svc.cluster.local:5432"
echo ""
echo -e "${GREEN}Credentials:${NC}"
POSTGRES_PASS=$(kubectl get secret -n keycloak postgresql -o jsonpath='{.data.postgres-password}' 2>/dev/null | base64 -d 2>/dev/null || echo "N/A")
echo "  Username: postgres"
echo "  Password: ${POSTGRES_PASS}"
echo "  Database: keycloak"
echo ""
echo -e "${YELLOW}Connect from pod:${NC}"
echo "  kubectl run psql --rm -it --image=postgres:16 -n keycloak -- psql -h postgresql -U postgres -d keycloak"
echo ""

echo "╔════════════════════════════════════════════════════════════════╗"
echo "║                   Quick Reference Commands                     ║"
echo "╚════════════════════════════════════════════════════════════════╝"
echo ""
echo -e "${YELLOW}View all pods:${NC}"
echo "  kubectl get pods -A"
echo ""
echo -e "${YELLOW}View all services:${NC}"
echo "  kubectl get svc -A"
echo ""
echo -e "${YELLOW}Check deployment health:${NC}"
echo "  kubectl get deployments -A"
echo ""
echo -e "${YELLOW}View recent events:${NC}"
echo "  kubectl get events -A --sort-by='.lastTimestamp' | tail -30"
echo ""
echo -e "${YELLOW}Run E2E tests:${NC}"
echo "  ./local-testing/run-e2e-tests.sh"
echo ""
echo -e "${YELLOW}Access UI:${NC}"
echo "  kubectl port-forward -n kagenti-system svc/http-istio 8080:80"
echo "  Visit: http://kagenti-ui.localtest.me:8080"
echo ""
