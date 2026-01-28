#!/usr/bin/env bash
# Show Services Script - Display all Kagenti services, URLs, and credentials
#
# Usage:
#   ./.github/scripts/local-setup/show-services.sh [cluster-suffix]
#
# Examples:
#   # HyperShift - source .env file first to set MANAGED_BY_TAG
#   source .env.$MANAGED_BY_TAG && ./.github/scripts/local-setup/show-services.sh
#   source .env.$MANAGED_BY_TAG && ./.github/scripts/local-setup/show-services.sh pr529
#
#   # Kind - no env file needed
#   ./.github/scripts/local-setup/show-services.sh
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

# =============================================================================
#                     KEYCLOAK AUTHENTICATION
#        Services using Keycloak for authentication (use creds below)
# =============================================================================

echo "##########################################################################"
echo -e "${CYAN}                    KEYCLOAK AUTHENTICATION                           ${NC}"
echo -e "${CYAN}        (Services using Keycloak - use credentials below)             ${NC}"
echo "##########################################################################"
echo ""

# Get Keycloak credentials first (shared by services below)
KEYCLOAK_ADMIN_USER=$($CLI get secret -n keycloak keycloak-initial-admin -o jsonpath='{.data.username}' 2>/dev/null | base64 -d 2>/dev/null || echo "N/A")
KEYCLOAK_ADMIN_PASS=$($CLI get secret -n keycloak keycloak-initial-admin -o jsonpath='{.data.password}' 2>/dev/null | base64 -d 2>/dev/null || echo "N/A")

echo -e "${GREEN}Credentials:${NC} ${YELLOW}(sensitive - do not share)${NC}"
echo "  Username: ${KEYCLOAK_ADMIN_USER}"
echo "  Password: ${KEYCLOAK_ADMIN_PASS}"
echo ""

echo "---------------------------------------------------------------------------"
echo -e "${MAGENTA}Keycloak (Identity Provider)${NC}"
echo "---------------------------------------------------------------------------"
KEYCLOAK_STATUS=$($CLI get pods -n keycloak -l app=keycloak -o jsonpath='{.items[0].status.phase}' 2>/dev/null || echo "Not Found")
echo -e "${BLUE}Status:${NC}       $KEYCLOAK_STATUS"
if [ "$ENV_TYPE" = "kind" ]; then
    echo -e "${BLUE}Admin URL:${NC}    http://keycloak.localtest.me:8080/admin"
else
    KEYCLOAK_ROUTE=$($CLI get route -n keycloak keycloak -o jsonpath='{.spec.host}' 2>/dev/null || echo "")
    if [ -n "$KEYCLOAK_ROUTE" ]; then
        echo -e "${BLUE}Admin URL:${NC}    https://$KEYCLOAK_ROUTE/admin"
    fi
fi
echo -e "${BLUE}Realm:${NC}        kagenti"
echo ""

echo "---------------------------------------------------------------------------"
echo -e "${MAGENTA}Kagenti UI (Web Dashboard)${NC}"
echo "---------------------------------------------------------------------------"
UI_STATUS=$($CLI get pods -n kagenti-system -l app.kubernetes.io/name=kagenti-ui -o jsonpath='{.items[0].status.phase}' 2>/dev/null || echo "Not Found")
echo -e "${BLUE}Status:${NC}       $UI_STATUS"
if [ "$ENV_TYPE" = "kind" ]; then
    echo -e "${BLUE}URL:${NC}          http://kagenti-ui.localtest.me:8080"
else
    UI_ROUTE=$($CLI get route -n kagenti-system kagenti-ui -o jsonpath='{.spec.host}' 2>/dev/null || echo "")
    if [ -n "$UI_ROUTE" ]; then
        echo -e "${BLUE}URL:${NC}          https://$UI_ROUTE"
    fi
fi
echo -e "${BLUE}Auth:${NC}         Click 'Login' → use Keycloak credentials above"
echo ""

# =============================================================================
#                     OPENSHIFT CLUSTER ACCESS
#        Services using OpenShift OAuth (use kubeadmin credentials)
# =============================================================================

if [ "$ENV_TYPE" = "hypershift" ] || [ "$ENV_TYPE" = "openshift" ]; then
    echo "##########################################################################"
    echo -e "${CYAN}                    OPENSHIFT CLUSTER ACCESS                          ${NC}"
    echo -e "${CYAN}        (Services using OpenShift OAuth - use kubeadmin creds)        ${NC}"
    echo "##########################################################################"
    echo ""

    # Get kubeadmin credentials (for HyperShift, from kubeconfig directory)
    if [ "$ENV_TYPE" = "hypershift" ]; then
        KUBEADMIN_PASS_FILE="$(dirname "$KUBECONFIG")/kubeadmin-password"
        if [ -f "$KUBEADMIN_PASS_FILE" ]; then
            KUBEADMIN_PASS=$(cat "$KUBEADMIN_PASS_FILE")
        else
            KUBEADMIN_PASS="N/A (check $KUBEADMIN_PASS_FILE)"
        fi
    else
        KUBEADMIN_PASS=$($CLI get secret -n kube-system kubeadmin -o jsonpath='{.data.password}' 2>/dev/null | base64 -d 2>/dev/null || echo "N/A")
    fi

    echo -e "${GREEN}Credentials:${NC} ${YELLOW}(sensitive - do not share)${NC}"
    echo "  Username: kubeadmin"
    echo "  Password: ${KUBEADMIN_PASS}"
    echo ""

    echo "---------------------------------------------------------------------------"
    echo -e "${MAGENTA}OpenShift Console${NC}"
    echo "---------------------------------------------------------------------------"
    CONSOLE_ROUTE=$($CLI get route -n openshift-console console -o jsonpath='{.spec.host}' 2>/dev/null || echo "")
    if [ -n "$CONSOLE_ROUTE" ]; then
        echo -e "${BLUE}URL:${NC}          https://$CONSOLE_ROUTE"
    else
        echo -e "${BLUE}URL:${NC}          (no route found)"
    fi
    echo -e "${BLUE}Auth:${NC}         Use kubeadmin credentials above"
    echo ""

    echo "---------------------------------------------------------------------------"
    echo -e "${MAGENTA}Kiali (Service Mesh Observability)${NC}"
    echo "---------------------------------------------------------------------------"
    KIALI_STATUS=$($CLI get pods -n istio-system -l app=kiali -o jsonpath='{.items[0].status.phase}' 2>/dev/null || echo "Not Found")
    echo -e "${BLUE}Status:${NC}       $KIALI_STATUS"
    KIALI_ROUTE=$($CLI get route -n istio-system kiali -o jsonpath='{.spec.host}' 2>/dev/null || echo "")
    if [ -n "$KIALI_ROUTE" ]; then
        echo -e "${BLUE}URL:${NC}          https://$KIALI_ROUTE"
    else
        echo -e "${BLUE}URL:${NC}          (no route found)"
    fi
    echo -e "${BLUE}Auth:${NC}         Use kubeadmin credentials above"
    echo ""
fi

# =============================================================================
#                         OBSERVABILITY
#                    (No authentication required)
# =============================================================================

echo "##########################################################################"
echo -e "${CYAN}                         OBSERVABILITY                                ${NC}"
echo -e "${CYAN}                    (No authentication required)                      ${NC}"
echo "##########################################################################"
echo ""

echo "---------------------------------------------------------------------------"
echo -e "${MAGENTA}Phoenix (LLM Traces)${NC}"
echo "---------------------------------------------------------------------------"
PHOENIX_STATUS=$($CLI get pods -n kagenti-system -l app=phoenix -o jsonpath='{.items[0].status.phase}' 2>/dev/null || echo "Not Found")
echo -e "${BLUE}Status:${NC}       $PHOENIX_STATUS"
if [ "$ENV_TYPE" = "kind" ]; then
    echo -e "${BLUE}URL:${NC}          http://phoenix.localtest.me:8080"
else
    PHOENIX_ROUTE=$($CLI get route -n kagenti-system phoenix -o jsonpath='{.spec.host}' 2>/dev/null || echo "")
    if [ -n "$PHOENIX_ROUTE" ]; then
        echo -e "${BLUE}URL:${NC}          https://$PHOENIX_ROUTE"
    else
        echo -e "${BLUE}URL:${NC}          (no route found)"
    fi
fi
echo -e "${BLUE}Auth:${NC}         None required"
echo ""

# Kind environment - show Kiali here since no OpenShift OAuth
if [ "$ENV_TYPE" = "kind" ]; then
    echo "---------------------------------------------------------------------------"
    echo -e "${MAGENTA}Kiali (Service Mesh Observability)${NC}"
    echo "---------------------------------------------------------------------------"
    KIALI_STATUS=$($CLI get pods -n istio-system -l app=kiali -o jsonpath='{.items[0].status.phase}' 2>/dev/null || echo "Not Found")
    echo -e "${BLUE}Status:${NC}       $KIALI_STATUS"
    echo -e "${BLUE}URL:${NC}          http://kiali.localtest.me:8080"
    echo -e "${BLUE}Auth:${NC}         None required (Kind mode)"
    echo ""
fi

# =============================================================================
#                       EXAMPLE WORKLOADS
#                  (Weather Agent & Tool in team1)
# =============================================================================

echo "##########################################################################"
echo -e "${CYAN}                       EXAMPLE WORKLOADS                              ${NC}"
echo -e "${CYAN}                  (Weather Agent & Tool in team1)                     ${NC}"
echo "##########################################################################"
echo ""

echo "---------------------------------------------------------------------------"
echo -e "${MAGENTA}Weather Agent (A2A Protocol)${NC}"
echo "---------------------------------------------------------------------------"
AGENT_STATUS=$($CLI get pods -n team1 -l app.kubernetes.io/name=weather-service -o jsonpath='{.items[0].status.phase}' 2>/dev/null \
    || $CLI get pods -n team1 -l app=weather-service -o jsonpath='{.items[0].status.phase}' 2>/dev/null \
    || echo "Not Found")
echo -e "${BLUE}Status:${NC}       $AGENT_STATUS"
if [ "$ENV_TYPE" = "kind" ]; then
    echo -e "${BLUE}URL:${NC}          http://weather-service.team1.svc.cluster.local:8000"
else
    AGENT_ROUTE=$($CLI get route -n team1 weather-service -o jsonpath='{.spec.host}' 2>/dev/null || echo "")
    if [ -n "$AGENT_ROUTE" ]; then
        echo -e "${BLUE}URL:${NC}          https://$AGENT_ROUTE"
    fi
fi
echo -e "${BLUE}Logs:${NC}         $CLI logs -n team1 -l app.kubernetes.io/name=weather-service -f"
echo ""

echo "---------------------------------------------------------------------------"
echo -e "${MAGENTA}Weather Tool (MCP Protocol)${NC}"
echo "---------------------------------------------------------------------------"
TOOL_STATUS=$($CLI get pods -n team1 -l app.kubernetes.io/name=weather-tool -o jsonpath='{.items[0].status.phase}' 2>/dev/null \
    || $CLI get pods -n team1 -l app=weather-tool -o jsonpath='{.items[0].status.phase}' 2>/dev/null \
    || echo "Not Found")
echo -e "${BLUE}Status:${NC}       $TOOL_STATUS"
if [ "$ENV_TYPE" = "kind" ]; then
    echo -e "${BLUE}URL:${NC}          http://weather-tool.team1.svc.cluster.local:8000"
else
    TOOL_ROUTE=$($CLI get route -n team1 weather-tool -o jsonpath='{.spec.host}' 2>/dev/null || echo "")
    if [ -n "$TOOL_ROUTE" ]; then
        echo -e "${BLUE}URL:${NC}          https://$TOOL_ROUTE"
    fi
fi
echo -e "${BLUE}Logs:${NC}         $CLI logs -n team1 -l app.kubernetes.io/name=weather-tool -f"
echo ""

# =============================================================================
#                        INFRASTRUCTURE
#                    (Operator and Database)
# =============================================================================

echo "##########################################################################"
echo -e "${CYAN}                        INFRASTRUCTURE                                ${NC}"
echo -e "${CYAN}                    (Operator and Database)                           ${NC}"
echo "##########################################################################"
echo ""

echo "---------------------------------------------------------------------------"
echo -e "${MAGENTA}Kagenti Operator${NC}"
echo "---------------------------------------------------------------------------"
OPERATOR_STATUS=$($CLI get pods -n kagenti-system -l control-plane=controller-manager -o jsonpath='{.items[0].status.phase}' 2>/dev/null || echo "Not Found")
echo -e "${BLUE}Status:${NC}       $OPERATOR_STATUS"
echo -e "${BLUE}Namespace:${NC}    kagenti-system"
echo -e "${BLUE}Agents:${NC}       $CLI get agents -A"
echo -e "${BLUE}Logs:${NC}         $CLI logs -n kagenti-system -l control-plane=controller-manager -f"
echo ""

echo "---------------------------------------------------------------------------"
echo -e "${MAGENTA}PostgreSQL (Keycloak DB)${NC}"
echo "---------------------------------------------------------------------------"
POSTGRES_STATUS=$($CLI get pods -n keycloak -l app=postgres-kc -o jsonpath='{.items[0].status.phase}' 2>/dev/null || echo "Not Found")
echo -e "${BLUE}Status:${NC}       $POSTGRES_STATUS"
echo -e "${BLUE}Service:${NC}      postgres-kc.keycloak.svc.cluster.local:5432"
POSTGRES_USER=$($CLI get secret -n keycloak keycloak-db-secret -o jsonpath='{.data.username}' 2>/dev/null | base64 -d 2>/dev/null || echo "N/A")
POSTGRES_PASS=$($CLI get secret -n keycloak keycloak-db-secret -o jsonpath='{.data.password}' 2>/dev/null | base64 -d 2>/dev/null || echo "N/A")
echo -e "${BLUE}Username:${NC}     ${POSTGRES_USER}"
echo -e "${BLUE}Password:${NC}     ${POSTGRES_PASS}"
echo -e "${BLUE}Database:${NC}     keycloak"
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
