#!/usr/bin/env bash
# Show Services Script - Display all Kagenti services, URLs, and credentials
#
# Usage:
#   ./.github/scripts/local-setup/show-services.sh [cluster-suffix]
#   source .env.kagenti-hypershift-custom && ./.github/scripts/local-setup/show-services.sh
#   source .env.kagenti-hypershift-ci && ./.github/scripts/local-setup/show-services.sh pr529
#
# For HyperShift:
#   - Source .env file first to set MANAGED_BY_TAG
#   - Pass cluster suffix as argument (defaults to $USER)
#   - Script will load the hosted cluster kubeconfig automatically
#
# Environment detection:
#   - HyperShift: Uses MANAGED_BY_TAG and CLUSTER_SUFFIX, loads hosted cluster kubeconfig
#   - Kind: Uses kubectl with localtest.me URLs

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="${GITHUB_WORKSPACE:-$(cd "$SCRIPT_DIR/../../.." && pwd)}"

# Accept cluster suffix as argument
if [ $# -ge 1 ]; then
    CLUSTER_SUFFIX="$1"
fi

# Colors for output (use $'...' for proper escape interpretation)
RED=$'\033[0;31m'
GREEN=$'\033[0;32m'
YELLOW=$'\033[1;33m'
BLUE=$'\033[0;34m'
CYAN=$'\033[0;36m'
MAGENTA=$'\033[0;35m'
NC=$'\033[0m' # No Color

# Detect environment
detect_environment() {
    # Check if MANAGED_BY_TAG is set (HyperShift mode - set kubeconfig first)
    if [ -n "${MANAGED_BY_TAG:-}" ]; then
        echo "hypershift"
    # Check if we're on OpenShift (regular OCP)
    elif command -v oc &>/dev/null && oc whoami &>/dev/null 2>&1; then
        echo "openshift"
    elif command -v kubectl &>/dev/null && kubectl get namespace default &>/dev/null 2>&1; then
        echo "kind"
    else
        echo "unknown"
    fi
}

# Set KUBECONFIG for HyperShift hosted cluster
setup_hypershift_kubeconfig() {
    local managed_by_tag="${MANAGED_BY_TAG:-kagenti-hypershift-custom}"
    local cluster_suffix="${CLUSTER_SUFFIX:-$USER}"
    local cluster_name="${managed_by_tag}-${cluster_suffix}"
    local kubeconfig_path="$HOME/clusters/hcp/${cluster_name}/auth/kubeconfig"

    if [ -f "$kubeconfig_path" ]; then
        export KUBECONFIG="$kubeconfig_path"
        return 0
    else
        echo -e "${RED}Error: Kubeconfig not found at ${kubeconfig_path}${NC}" >&2
        echo "  The cluster may not exist or was not created locally." >&2
        echo "  Create it with: ./.github/scripts/local-setup/hypershift-full-test.sh ${cluster_suffix} --skip-cluster-destroy" >&2
        return 1
    fi
}

# Find and load .env file for HyperShift
load_env_file() {
    local managed_by_tag="${MANAGED_BY_TAG:-kagenti-hypershift-custom}"

    if [ -f "$REPO_ROOT/.env.${managed_by_tag}" ]; then
        # shellcheck source=/dev/null
        source "$REPO_ROOT/.env.${managed_by_tag}"
        echo "$REPO_ROOT/.env.${managed_by_tag}"
    elif [ -f "$REPO_ROOT/.env.hypershift-ci" ]; then
        # shellcheck source=/dev/null
        source "$REPO_ROOT/.env.hypershift-ci"
        echo "$REPO_ROOT/.env.hypershift-ci"
    else
        # Find any .env.kagenti-* file
        local env_file
        env_file=$(ls "$REPO_ROOT"/.env.kagenti-* 2>/dev/null | head -1 || true)
        if [ -n "$env_file" ] && [ -f "$env_file" ]; then
            # shellcheck source=/dev/null
            source "$env_file"
            echo "$env_file"
        fi
    fi
}

# Get cluster name for HyperShift
get_cluster_name() {
    local managed_by_tag="${MANAGED_BY_TAG:-kagenti-hypershift-custom}"
    local cluster_suffix="${CLUSTER_SUFFIX:-$USER}"
    echo "${managed_by_tag}-${cluster_suffix}"
}

# CLI command (oc for OpenShift, kubectl for Kind)
CLI="kubectl"
ENV_TYPE=$(detect_environment)

case "$ENV_TYPE" in
    hypershift|openshift)
        CLI="oc"
        ;;
esac

echo ""
echo "========================================================================="
echo "             Kagenti Platform Services & Credentials                    "
echo "========================================================================="
echo ""

# Check environment and display info
case "$ENV_TYPE" in
    hypershift)
        CLUSTER_NAME=$(get_cluster_name)
        # Set KUBECONFIG for the hosted cluster
        if ! setup_hypershift_kubeconfig; then
            exit 1
        fi
        echo -e "${CYAN}Environment:${NC}  HyperShift"
        echo -e "${CYAN}Cluster:${NC}      $CLUSTER_NAME"
        echo -e "${CYAN}Kubeconfig:${NC}   $KUBECONFIG"
        echo ""
        ;;
    openshift)
        echo -e "${CYAN}Environment:${NC}  OpenShift"
        echo -e "${CYAN}API Server:${NC}  $(oc whoami --show-server 2>/dev/null || echo 'unknown')"
        echo ""
        ;;
    kind)
        echo -e "${CYAN}Environment:${NC}  Kind (local Docker)"
        echo ""
        ;;
    *)
        echo -e "${RED}Error: Unable to detect environment${NC}"
        echo "  - For Kind: ensure kubectl is configured"
        echo "  - For HyperShift: set MANAGED_BY_TAG and CLUSTER_SUFFIX, or load .env file"
        echo "  - For OpenShift: ensure oc is logged in"
        exit 1
        ;;
esac

# Check if platform is running
if ! $CLI get namespace kagenti-system &> /dev/null; then
    echo -e "${RED}Error: Platform not deployed (kagenti-system namespace not found)${NC}"
    echo "  Run: ./.github/scripts/local-setup/hypershift-full-test.sh --skip-cluster-destroy"
    exit 1
fi

echo "==========================================================================="
echo -e "${MAGENTA}1. Keycloak (Identity & Access Management)${NC}"
echo "==========================================================================="

KEYCLOAK_STATUS=$($CLI get pods -n keycloak -l app.kubernetes.io/name=keycloak -o jsonpath='{.items[0].status.phase}' 2>/dev/null || echo "Not Found")
echo -e "${BLUE}Status:${NC}      $KEYCLOAK_STATUS"

# Get Keycloak URL based on environment
if [ "$ENV_TYPE" = "kind" ]; then
    echo -e "${BLUE}Access URL:${NC}  http://keycloak.localtest.me:8080"
    echo ""
    echo -e "${YELLOW}Port-forward command:${NC}"
    echo "  kubectl port-forward -n keycloak svc/keycloak 8080:8080"
else
    KEYCLOAK_ROUTE=$($CLI get route -n keycloak keycloak -o jsonpath='{.spec.host}' 2>/dev/null || echo "")
    if [ -n "$KEYCLOAK_ROUTE" ]; then
        echo -e "${BLUE}Access URL:${NC}  https://$KEYCLOAK_ROUTE"
    else
        echo -e "${BLUE}Access URL:${NC}  (no route found - create one or use port-forward)"
        echo ""
        echo -e "${YELLOW}Port-forward command:${NC}"
        echo "  oc port-forward -n keycloak svc/keycloak 8080:8080"
    fi
fi
echo ""
echo -e "${GREEN}Credentials:${NC} ${YELLOW}(sensitive - do not share this output)${NC}"

# Try to get admin credentials from secret
KEYCLOAK_ADMIN_USER=$($CLI get secret -n keycloak keycloak-admin-credentials -o jsonpath='{.data.username}' 2>/dev/null | base64 -d 2>/dev/null || echo "admin")
KEYCLOAK_ADMIN_PASS=$($CLI get secret -n keycloak keycloak-admin-credentials -o jsonpath='{.data.password}' 2>/dev/null | base64 -d 2>/dev/null || echo "admin")

echo "  Username: ${KEYCLOAK_ADMIN_USER}"
echo "  Password: ${KEYCLOAK_ADMIN_PASS}"
echo ""
echo -e "${YELLOW}Realm:${NC}        kagenti"
echo ""

echo "==========================================================================="
echo -e "${MAGENTA}2. Kagenti UI (Web Dashboard)${NC}"
echo "==========================================================================="

UI_STATUS=$($CLI get pods -n kagenti-system -l app=kagenti-ui -o jsonpath='{.items[0].status.phase}' 2>/dev/null || echo "Not Found")
echo -e "${BLUE}Status:${NC}      $UI_STATUS"

# Get UI URL based on environment
if [ "$ENV_TYPE" = "kind" ]; then
    echo -e "${BLUE}Access URL:${NC}  http://kagenti-ui.localtest.me:8080"
    echo ""
    echo -e "${YELLOW}Port-forward command:${NC}"
    echo "  kubectl port-forward -n kagenti-system svc/http-istio 8080:80"
else
    UI_ROUTE=$($CLI get route -n kagenti-system kagenti-ui -o jsonpath='{.spec.host}' 2>/dev/null || echo "")
    if [ -n "$UI_ROUTE" ]; then
        echo -e "${BLUE}Access URL:${NC}  https://$UI_ROUTE"
    else
        echo -e "${BLUE}Access URL:${NC}  (no route found)"
    fi
fi
echo ""
echo -e "${GREEN}Authentication:${NC} Via Keycloak OAuth2"
echo "  Click 'Login' and use Keycloak credentials above"
echo ""

echo "==========================================================================="
echo -e "${MAGENTA}3. Weather Agent (A2A Protocol)${NC}"
echo "==========================================================================="

AGENT_STATUS=$($CLI get pods -n team1 -l app.kubernetes.io/name=weather-service -o jsonpath='{.items[0].status.phase}' 2>/dev/null || echo "Not Found")
echo -e "${BLUE}Status:${NC}           $AGENT_STATUS"
echo -e "${BLUE}Namespace:${NC}        team1"

if [ "$ENV_TYPE" = "kind" ]; then
    echo -e "${BLUE}Service URL:${NC}      http://weather-service.team1.svc.cluster.local:8000"
    echo ""
    echo -e "${YELLOW}Port-forward command:${NC}"
    echo "  kubectl port-forward -n team1 svc/weather-service 8000:8000"
else
    AGENT_ROUTE=$($CLI get route -n team1 weather-service -o jsonpath='{.spec.host}' 2>/dev/null || echo "")
    if [ -n "$AGENT_ROUTE" ]; then
        echo -e "${BLUE}External URL:${NC}     https://$AGENT_ROUTE"
    fi
fi
echo ""
echo -e "${YELLOW}Test with A2A client:${NC}"
if [ "$ENV_TYPE" != "kind" ] && [ -n "${AGENT_ROUTE:-}" ]; then
    echo "  AGENT_URL=https://$AGENT_ROUTE pytest kagenti/tests/e2e/test_agent_conversation.py -v"
else
    echo "  AGENT_URL=http://localhost:8000 pytest kagenti/tests/e2e/test_agent_conversation.py -v"
fi
echo ""
echo -e "${YELLOW}View logs:${NC}"
echo "  $CLI logs -n team1 deployment/weather-service --tail=100 -f"
echo ""

echo "==========================================================================="
echo -e "${MAGENTA}4. Weather Tool (MCP Protocol)${NC}"
echo "==========================================================================="

TOOL_STATUS=$($CLI get pods -n team1 -l app.kubernetes.io/name=weather-tool -o jsonpath='{.items[0].status.phase}' 2>/dev/null || echo "Not Found")
echo -e "${BLUE}Status:${NC}           $TOOL_STATUS"
echo -e "${BLUE}Namespace:${NC}        team1"

if [ "$ENV_TYPE" = "kind" ]; then
    echo -e "${BLUE}Service URL:${NC}      http://weather-tool.team1.svc.cluster.local:8000"
    echo ""
    echo -e "${YELLOW}Port-forward command:${NC}"
    echo "  kubectl port-forward -n team1 svc/weather-tool 8001:8000"
else
    TOOL_ROUTE=$($CLI get route -n team1 weather-tool -o jsonpath='{.spec.host}' 2>/dev/null || echo "")
    if [ -n "$TOOL_ROUTE" ]; then
        echo -e "${BLUE}External URL:${NC}     https://$TOOL_ROUTE"
    fi
fi
echo ""
echo -e "${YELLOW}View logs:${NC}"
echo "  $CLI logs -n team1 deployment/weather-tool --tail=100 -f"
echo ""

echo "==========================================================================="
echo -e "${MAGENTA}5. Ollama (Local LLM)${NC}"
echo "==========================================================================="

if pgrep -x "ollama" > /dev/null 2>&1; then
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

echo "==========================================================================="
echo -e "${MAGENTA}6. Kagenti Operator${NC}"
echo "==========================================================================="

OPERATOR_STATUS=$($CLI get pods -n kagenti-system -l app.kubernetes.io/name=kagenti-operator -o jsonpath='{.items[0].status.phase}' 2>/dev/null || echo "Not Found")
echo -e "${BLUE}Status:${NC}           $OPERATOR_STATUS"
echo -e "${BLUE}Namespace:${NC}        kagenti-system"
echo ""
echo -e "${YELLOW}View logs:${NC}"
echo "  $CLI logs -n kagenti-system deployment/kagenti-operator --tail=100 -f"
echo ""
echo -e "${YELLOW}View managed agents:${NC}"
echo "  $CLI get agents -A"
echo ""

echo "==========================================================================="
echo -e "${MAGENTA}7. PostgreSQL Database${NC}"
echo "==========================================================================="

POSTGRES_STATUS=$($CLI get pods -n keycloak -l app.kubernetes.io/name=postgresql -o jsonpath='{.items[0].status.phase}' 2>/dev/null || echo "Not Found")
echo -e "${BLUE}Status:${NC}           $POSTGRES_STATUS"
echo -e "${BLUE}Namespace:${NC}        keycloak"
echo -e "${BLUE}Service:${NC}          postgresql.keycloak.svc.cluster.local:5432"
echo ""
echo -e "${GREEN}Credentials:${NC} ${YELLOW}(sensitive - do not share this output)${NC}"
POSTGRES_PASS=$($CLI get secret -n keycloak postgresql -o jsonpath='{.data.postgres-password}' 2>/dev/null | base64 -d 2>/dev/null || echo "N/A")
echo "  Username: postgres"
echo "  Password: ${POSTGRES_PASS}"
echo "  Database: keycloak"
echo ""
echo -e "${YELLOW}Connect from pod:${NC}"
echo "  $CLI run psql --rm -it --image=postgres:16 -n keycloak -- psql -h postgresql -U postgres -d keycloak"
echo ""

echo "========================================================================="
echo "                    Quick Reference Commands                            "
echo "========================================================================="
echo ""
echo -e "${YELLOW}View all pods:${NC}"
echo "  $CLI get pods -A"
echo ""
echo -e "${YELLOW}View all services:${NC}"
echo "  $CLI get svc -A"
echo ""
echo -e "${YELLOW}Check deployment health:${NC}"
echo "  $CLI get deployments -A"
echo ""
echo -e "${YELLOW}View recent events:${NC}"
echo "  $CLI get events -A --sort-by='.lastTimestamp' | tail -30"
echo ""
echo -e "${YELLOW}Run E2E tests:${NC}"
if [ "$ENV_TYPE" = "kind" ]; then
    echo "  ./.github/scripts/local-setup/kind-full-test.sh --include-test"
else
    echo "  ./.github/scripts/local-setup/hypershift-full-test.sh --include-test"
fi
echo ""
