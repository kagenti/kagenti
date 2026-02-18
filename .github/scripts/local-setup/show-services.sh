#!/usr/bin/env bash
# Show Services Script - Display all Kagenti services, URLs, and credentials
#
# Usage:
#   ./.github/scripts/local-setup/show-services.sh [--verbose] [cluster-suffix]
#
# Default: compact view with clickable links
# --verbose: full detailed view with pod status, logs commands, infrastructure
#
# Examples:
#   # HyperShift - source .env file first to set MANAGED_BY_TAG
#   source .env.$MANAGED_BY_TAG && ./.github/scripts/local-setup/show-services.sh
#   source .env.$MANAGED_BY_TAG && ./.github/scripts/local-setup/show-services.sh --verbose
#   source .env.$MANAGED_BY_TAG && ./.github/scripts/local-setup/show-services.sh mlflow
#
#   # Kind - no env file needed
#   ./.github/scripts/local-setup/show-services.sh

set -euo pipefail

# Parse flags
VERBOSE=false
for arg in "$@"; do
    case "$arg" in
        --verbose|-v) VERBOSE=true ;;
        *) CLUSTER_SUFFIX="$arg" ;;
    esac
done

# Colors
RED=$'\033[0;31m'
GREEN=$'\033[0;32m'
YELLOW=$'\033[1;33m'
BLUE=$'\033[0;34m'
CYAN=$'\033[0;36m'
MAGENTA=$'\033[0;35m'
DIM=$'\033[2m'
NC=$'\033[0m'

# Clickable terminal links (OSC 8)
link() {
    local url="$1"
    local text="${2:-$url}"
    printf '\e]8;;%s\e\\%s\e]8;;\e\\' "$url" "$text"
}

# Detect environment
detect_environment() {
    if [ -n "${MANAGED_BY_TAG:-}" ]; then
        echo "hypershift"
    elif kubectl config current-context 2>/dev/null | grep -q "^kind-"; then
        echo "kind"
    elif command -v oc &>/dev/null && oc whoami &>/dev/null 2>&1; then
        echo "openshift"
    else
        echo "unknown"
    fi
}

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
        return 1
    fi
}

get_cluster_name() {
    local managed_by_tag="${MANAGED_BY_TAG:-kagenti-hypershift-custom}"
    local cluster_suffix="${CLUSTER_SUFFIX:-$USER}"
    echo "${managed_by_tag}-${cluster_suffix}"
}

# Setup
CLI="kubectl"
ENV_TYPE=$(detect_environment)
case "$ENV_TYPE" in
    hypershift|openshift) CLI="oc" ;;
esac

# Environment setup
case "$ENV_TYPE" in
    hypershift)
        CLUSTER_NAME=$(get_cluster_name)
        if ! setup_hypershift_kubeconfig; then exit 1; fi
        ;;
    kind) CLUSTER_NAME="kind-local" ;;
    openshift) CLUSTER_NAME="openshift" ;;
    *)
        echo -e "${RED}Error: Unable to detect environment${NC}"
        exit 1
        ;;
esac

# Check platform
if ! $CLI get namespace kagenti-system &> /dev/null; then
    echo -e "${RED}Error: Platform not deployed (kagenti-system namespace not found)${NC}"
    exit 1
fi

# =============================================================================
# Fetch all route hostnames up front
# =============================================================================
if [ "$ENV_TYPE" = "kind" ]; then
    DOMAIN_NAME="${DOMAIN_NAME:-localtest.me}"
    KEYCLOAK_URL="http://keycloak.${DOMAIN_NAME}:8080"
    UI_URL="http://kagenti-ui.${DOMAIN_NAME}:8080"
    MLFLOW_URL="http://mlflow.${DOMAIN_NAME}:8080"
    PHOENIX_URL="http://phoenix.${DOMAIN_NAME}:8080"
    KIALI_URL="http://kiali.${DOMAIN_NAME}:8080"
    API_URL="http://kagenti-api.${DOMAIN_NAME}:8080"
    AGENT_URL=""
    CONSOLE_URL=""
else
    _route() { $CLI get route -n "$1" "$2" -o jsonpath='{.spec.host}' 2>/dev/null || echo ""; }
    KEYCLOAK_HOST=$(_route keycloak keycloak)
    UI_HOST=$(_route kagenti-system kagenti-ui)
    MLFLOW_HOST=$(_route kagenti-system mlflow)
    PHOENIX_HOST=$(_route kagenti-system phoenix)
    KIALI_HOST=$(_route istio-system kiali)
    API_HOST=$(_route kagenti-system kagenti-api)
    AGENT_HOST=$(_route team1 weather-service)
    CONSOLE_HOST=$(_route openshift-console console)

    KEYCLOAK_URL="${KEYCLOAK_HOST:+https://$KEYCLOAK_HOST}"
    UI_URL="${UI_HOST:+https://$UI_HOST}"
    MLFLOW_URL="${MLFLOW_HOST:+https://$MLFLOW_HOST}"
    PHOENIX_URL="${PHOENIX_HOST:+https://$PHOENIX_HOST}"
    KIALI_URL="${KIALI_HOST:+https://$KIALI_HOST}"
    API_URL="${API_HOST:+https://$API_HOST}"
    AGENT_URL="${AGENT_HOST:+https://$AGENT_HOST}"
    CONSOLE_URL="${CONSOLE_HOST:+https://$CONSOLE_HOST}"
fi

# =============================================================================
# Fetch credentials
# =============================================================================
# Keycloak admin (master realm) - for Keycloak admin console
KC_ADMIN_USER=$($CLI get secret -n keycloak keycloak-initial-admin -o jsonpath='{.data.username}' 2>/dev/null | base64 -d 2>/dev/null || echo "N/A")
KC_ADMIN_PASS=$($CLI get secret -n keycloak keycloak-initial-admin -o jsonpath='{.data.password}' 2>/dev/null | base64 -d 2>/dev/null || echo "N/A")

# App user (master realm) - same as Keycloak admin for master realm login
APP_USER="$KC_ADMIN_USER"
APP_PASS="$KC_ADMIN_PASS"

KUBEADMIN_PASS=""
if [ "$ENV_TYPE" = "hypershift" ]; then
    KUBEADMIN_PASS_FILE="$(dirname "$KUBECONFIG")/kubeadmin-password"
    [ -f "$KUBEADMIN_PASS_FILE" ] && KUBEADMIN_PASS=$(cat "$KUBEADMIN_PASS_FILE")
elif [ "$ENV_TYPE" = "openshift" ]; then
    KUBEADMIN_PASS=$($CLI get secret -n kube-system kubeadmin -o jsonpath='{.data.password}' 2>/dev/null | base64 -d 2>/dev/null || echo "")
fi

# =============================================================================
# COMPACT VIEW (default)
# =============================================================================
if [ "$VERBOSE" = "false" ]; then

    echo ""
    echo -e "${CYAN}Kagenti Services${NC} - ${CLUSTER_NAME}"
    echo ""

    # Credentials
    echo -e "${GREEN}Kagenti UI & MLflow:${NC}  ${APP_USER} / ${APP_PASS}  ${DIM}(master realm)${NC}"
    echo -e "${GREEN}Keycloak Admin:${NC}       ${KC_ADMIN_USER} / ${KC_ADMIN_PASS}  ${DIM}(master realm)${NC}"
    if [ -n "$KUBEADMIN_PASS" ]; then
        echo -e "${GREEN}kubeadmin:${NC}            kubeadmin / ${KUBEADMIN_PASS}"
    fi
    echo ""

    # Kagenti UI
    if [ -n "$UI_URL" ]; then
        echo -e "${MAGENTA}Kagenti UI${NC}"
        echo -e "  $(link "$UI_URL")"
        echo -e "  $(link "$UI_URL/agents/team1/weather-service" "$UI_URL/agents/team1/weather-service")  ${DIM}Chat with Weather Agent${NC}"
    fi

    # Backend API
    if [ -n "${API_URL:-}" ]; then
        echo -e "${MAGENTA}Backend API${NC}"
        echo -e "  $(link "$API_URL" "$API_URL")  ${DIM}Direct API access (requires JWT)${NC}"
    fi

    # Keycloak
    if [ -n "$KEYCLOAK_URL" ]; then
        echo -e "${MAGENTA}Keycloak${NC}"
        echo -e "  $(link "$KEYCLOAK_URL/admin" "$KEYCLOAK_URL/admin")  ${DIM}Admin Console${NC}"
    fi

    # MLflow
    if [ -n "$MLFLOW_URL" ]; then
        echo -e "${MAGENTA}MLflow${NC}"
        echo -e "  $(link "$MLFLOW_URL/#/experiments/0/overview" "$MLFLOW_URL/#/experiments/0/overview")  ${DIM}Experiment Overview${NC}"
        echo -e "  $(link "$MLFLOW_URL/#/experiments/0/traces" "$MLFLOW_URL/#/experiments/0/traces")  ${DIM}LLM Traces${NC}"
        echo -e "  $(link "$MLFLOW_URL/#/experiments/0/chat-sessions" "$MLFLOW_URL/#/experiments/0/chat-sessions")  ${DIM}Chat Sessions${NC}"
    fi

    # Phoenix
    if [ -n "$PHOENIX_URL" ]; then
        echo -e "${MAGENTA}Phoenix${NC}"
        echo -e "  $(link "$PHOENIX_URL/projects/UHJvamVjdDox/spans" "$PHOENIX_URL/projects/UHJvamVjdDox/spans")  ${DIM}Trace Spans${NC}"
        echo -e "  $(link "$PHOENIX_URL/projects/UHJvamVjdDox/sessions" "$PHOENIX_URL/projects/UHJvamVjdDox/sessions")  ${DIM}Chat Sessions${NC}"
    fi

    # Kiali
    if [ -n "$KIALI_URL" ]; then
        KIALI_GRAPH="traffic=ambient%2CambientTotal%2Cgrpc%2CgrpcRequest%2Chttp%2ChttpRequest%2Ctcp%2CtcpSent&graphType=versionedApp&duration=10800&refresh=60000&layout=dagre&badgeSecurity=true&animation=true&waypoints=true"
        KIALI_NS="kagenti-system%2Cteam1%2Cteam2%2Ckeycloak%2Cistio-system%2Cistio-cni%2Cistio-ztunnel%2Ccert-manager%2Cgateway-system%2Cmcp-system%2Cdefault"
        KIALI_TRAFFIC_URL="$KIALI_URL/console/graph/namespaces?${KIALI_GRAPH}&namespaces=${KIALI_NS}"
        echo -e "${MAGENTA}Kiali${NC}"
        echo -e "  $(link "$KIALI_URL" "$KIALI_URL")  ${DIM}Dashboard${NC}"
        echo -e "  $(link "$KIALI_TRAFFIC_URL" "$KIALI_TRAFFIC_URL")  ${DIM}Traffic Graph${NC}"
    fi

    # OpenShift Console
    if [ -n "${CONSOLE_URL:-}" ]; then
        echo -e "${MAGENTA}OpenShift Console${NC}"
        echo -e "  $(link "$CONSOLE_URL" "$CONSOLE_URL")"
    fi

    # Weather Agent
    if [ "$ENV_TYPE" = "kind" ]; then
        echo -e "${MAGENTA}Weather Agent${NC}"
        echo "  http://weather-service.team1.svc.cluster.local:8000"
    elif [ -n "${AGENT_URL:-}" ]; then
        echo -e "${MAGENTA}Weather Agent${NC}"
        echo -e "  $(link "$AGENT_URL" "$AGENT_URL")"
    fi

    echo ""
    echo -e "${DIM}Run with --verbose for full details (status, logs, infrastructure)${NC}"
    echo ""
    exit 0
fi

# =============================================================================
# VERBOSE VIEW (--verbose)
# =============================================================================

echo ""
echo "========================================================================="
echo "             Kagenti Platform Services & Credentials                    "
echo "========================================================================="
echo ""

# Environment info
case "$ENV_TYPE" in
    hypershift)
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
esac

# =============================================================================
# KEYCLOAK AUTHENTICATION
# =============================================================================

echo "##########################################################################"
echo -e "${CYAN}                    KEYCLOAK AUTHENTICATION                           ${NC}"
echo -e "${CYAN}        (Services using Keycloak - use credentials below)             ${NC}"
echo "##########################################################################"
echo ""

echo -e "${GREEN}App Login (Kagenti UI & MLflow):${NC} ${YELLOW}(master realm)${NC}"
echo "  Username: ${APP_USER}"
echo "  Password: ${APP_PASS}"
echo ""
echo -e "${GREEN}Keycloak Admin:${NC} ${YELLOW}(master realm - admin console only)${NC}"
echo "  Username: ${KC_ADMIN_USER}"
echo "  Password: ${KC_ADMIN_PASS}"
echo ""

echo "---------------------------------------------------------------------------"
echo -e "${MAGENTA}Keycloak (Identity Provider)${NC}"
echo "---------------------------------------------------------------------------"
KEYCLOAK_STATUS=$($CLI get pods -n keycloak -l app=keycloak -o jsonpath='{.items[0].status.phase}' 2>/dev/null || echo "Not Found")
echo -e "${BLUE}Status:${NC}       $KEYCLOAK_STATUS"
if [ -n "$KEYCLOAK_URL" ]; then
    echo -e "${BLUE}Admin URL:${NC}    $(link "$KEYCLOAK_URL/admin")"
fi
echo -e "${BLUE}Realm:${NC}        kagenti"
echo ""

echo "---------------------------------------------------------------------------"
echo -e "${MAGENTA}Kagenti UI (Web Dashboard)${NC}"
echo "---------------------------------------------------------------------------"
UI_STATUS=$($CLI get pods -n kagenti-system -l app.kubernetes.io/name=kagenti-ui -o jsonpath='{.items[0].status.phase}' 2>/dev/null || echo "Not Found")
echo -e "${BLUE}Status:${NC}       $UI_STATUS"
if [ -n "$UI_URL" ]; then
    echo -e "${BLUE}URL:${NC}          $(link "$UI_URL")"
    echo -e "${BLUE}Quick links:${NC}"
    echo -e "  $(link "$UI_URL/agents/team1/weather-service" "Chat with Weather Agent")"
fi
echo -e "${BLUE}Auth:${NC}         Click 'Login' → use Keycloak credentials above"
echo ""

echo "---------------------------------------------------------------------------"
echo -e "${MAGENTA}Backend API (Direct API Access)${NC}"
echo "---------------------------------------------------------------------------"
BACKEND_STATUS=$($CLI get pods -n kagenti-system -l app.kubernetes.io/name=kagenti-backend -o jsonpath='{.items[0].status.phase}' 2>/dev/null || echo "Not Found")
echo -e "${BLUE}Status:${NC}       $BACKEND_STATUS"
if [ -n "${API_URL:-}" ]; then
    echo -e "${BLUE}URL:${NC}          $(link "$API_URL")"
else
    echo -e "${BLUE}URL:${NC}          (no route found)"
fi
echo -e "${BLUE}Auth:${NC}         JWT bearer token required"
echo ""

echo "---------------------------------------------------------------------------"
echo -e "${MAGENTA}MLflow (LLM Trace Backend)${NC}"
echo "---------------------------------------------------------------------------"
MLFLOW_STATUS=$($CLI get pods -n kagenti-system -l app=mlflow -o jsonpath='{.items[0].status.phase}' 2>/dev/null || echo "Not Found")
echo -e "${BLUE}Status:${NC}       $MLFLOW_STATUS"
if [ -n "$MLFLOW_URL" ]; then
    echo -e "${BLUE}URL:${NC}          $(link "$MLFLOW_URL")"
    echo -e "${BLUE}Quick links:${NC}"
    echo -e "  $(link "$MLFLOW_URL/#/experiments/0/overview" "Experiment Overview")"
    echo -e "  $(link "$MLFLOW_URL/#/experiments/0/traces" "LLM Traces")"
    echo -e "  $(link "$MLFLOW_URL/#/experiments/0/chat-sessions" "Chat Sessions")"
else
    echo -e "${BLUE}URL:${NC}          (no route found)"
fi
echo -e "${BLUE}Auth:${NC}         Keycloak SSO (same credentials as above)"
echo ""

# =============================================================================
# OPENSHIFT CLUSTER ACCESS
# =============================================================================

if [ "$ENV_TYPE" = "hypershift" ] || [ "$ENV_TYPE" = "openshift" ]; then
    echo "##########################################################################"
    echo -e "${CYAN}                    OPENSHIFT CLUSTER ACCESS                          ${NC}"
    echo -e "${CYAN}        (Services using OpenShift OAuth - use kubeadmin creds)        ${NC}"
    echo "##########################################################################"
    echo ""

    echo -e "${GREEN}Credentials:${NC} ${YELLOW}(sensitive - do not share)${NC}"
    echo "  Username: kubeadmin"
    echo "  Password: ${KUBEADMIN_PASS:-N/A}"
    echo ""

    echo "---------------------------------------------------------------------------"
    echo -e "${MAGENTA}OpenShift Console${NC}"
    echo "---------------------------------------------------------------------------"
    if [ -n "${CONSOLE_URL:-}" ]; then
        echo -e "${BLUE}URL:${NC}          $(link "$CONSOLE_URL")"
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
    if [ -n "$KIALI_URL" ]; then
        echo -e "${BLUE}URL:${NC}          $(link "$KIALI_URL")"
        KIALI_GRAPH="traffic=ambient%2CambientTotal%2Cgrpc%2CgrpcRequest%2Chttp%2ChttpRequest%2Ctcp%2CtcpSent&graphType=versionedApp&duration=10800&refresh=60000&layout=dagre&badgeSecurity=true&animation=true&waypoints=true"
        KIALI_NS="kagenti-system%2Cteam1%2Cteam2%2Ckeycloak%2Cistio-system%2Cistio-cni%2Cistio-ztunnel%2Ccert-manager%2Cgateway-system%2Cmcp-system%2Cdefault"
        echo -e "${BLUE}Quick links:${NC}"
        echo -e "  $(link "$KIALI_URL/console/graph/namespaces?${KIALI_GRAPH}&namespaces=${KIALI_NS}" "Traffic Graph (all namespaces)")"
    else
        echo -e "${BLUE}URL:${NC}          (no route found)"
    fi
    echo -e "${BLUE}Auth:${NC}         Use kubeadmin credentials above"
    echo ""
fi

# =============================================================================
# OBSERVABILITY
# =============================================================================

echo "##########################################################################"
echo -e "${CYAN}                         OBSERVABILITY                                ${NC}"
echo -e "${CYAN}                    (No authentication required)                      ${NC}"
echo "##########################################################################"
echo ""

echo "---------------------------------------------------------------------------"
echo -e "${MAGENTA}Phoenix (LLM Trace Visualization)${NC}"
echo "---------------------------------------------------------------------------"
PHOENIX_STATUS=$($CLI get pods -n kagenti-system -l app=phoenix -o jsonpath='{.items[0].status.phase}' 2>/dev/null || echo "Not Found")
echo -e "${BLUE}Status:${NC}       $PHOENIX_STATUS"
if [ -n "$PHOENIX_URL" ]; then
    echo -e "${BLUE}URL:${NC}          $(link "$PHOENIX_URL")"
    echo -e "${BLUE}Quick links:${NC}"
    echo -e "  $(link "$PHOENIX_URL/projects/UHJvamVjdDox/spans" "Trace Spans")"
    echo -e "  $(link "$PHOENIX_URL/projects/UHJvamVjdDox/sessions" "Chat Sessions")"
else
    echo -e "${BLUE}URL:${NC}          (no route found)"
fi
echo -e "${BLUE}Auth:${NC}         None required"
echo ""

# Kind: show Kiali here (no OpenShift OAuth)
if [ "$ENV_TYPE" = "kind" ]; then
    echo "---------------------------------------------------------------------------"
    echo -e "${MAGENTA}Kiali (Service Mesh Observability)${NC}"
    echo "---------------------------------------------------------------------------"
    KIALI_STATUS=$($CLI get pods -n istio-system -l app=kiali -o jsonpath='{.items[0].status.phase}' 2>/dev/null || echo "Not Found")
    echo -e "${BLUE}Status:${NC}       $KIALI_STATUS"
    echo -e "${BLUE}URL:${NC}          $(link "$KIALI_URL")"
    KIALI_GRAPH="traffic=http%2ChttpRequest%2Ctcp%2CtcpSent&graphType=versionedApp&duration=10800&refresh=60000&layout=dagre&animation=true"
    KIALI_NS="kagenti-system%2Cteam1%2Cteam2%2Ckeycloak%2Cistio-system%2Cgateway-system%2Cdefault"
    echo -e "${BLUE}Quick links:${NC}"
    echo -e "  $(link "$KIALI_URL/console/graph/namespaces?${KIALI_GRAPH}&namespaces=${KIALI_NS}" "Traffic Graph (all namespaces)")"
    echo -e "${BLUE}Auth:${NC}         None required (Kind mode)"
    echo ""
fi

# =============================================================================
# EXAMPLE WORKLOADS
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
elif [ -n "${AGENT_URL:-}" ]; then
    echo -e "${BLUE}URL:${NC}          $(link "$AGENT_URL")"
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
        echo -e "${BLUE}URL:${NC}          $(link "https://$TOOL_ROUTE")"
    fi
fi
echo -e "${BLUE}Logs:${NC}         $CLI logs -n team1 -l app.kubernetes.io/name=weather-tool -f"
echo ""

# =============================================================================
# INFRASTRUCTURE
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
