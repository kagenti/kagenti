#!/usr/bin/env bash
#
# Run Full HyperShift Test
#
# Creates a HyperShift cluster, deploys Kagenti, deploys test agents, and runs E2E tests.
# Supports both whitelist (--include-*) and blacklist (--skip-*) modes.
#
# USAGE:
#   ./.github/scripts/local-setup/hypershift-full-test.sh [options] [cluster-suffix]
#
# MODES:
#   Whitelist mode: If ANY include flag (--create, --install, etc.) is used,
#                   only explicitly enabled phases run (default all OFF)
#   Blacklist mode: If only --skip-X flags are used,
#                   all phases run except those skipped (default all ON)
#
# OPTIONS:
#   Include flags (whitelist mode - only run specified phases):
#     --include-create   Include cluster creation phase
#     --include-install  Include Kagenti platform installation phase
#     --include-agents   Include building/deploying test agents phase
#     --include-test     Include E2E test phase
#     --include-destroy  Include cluster destruction phase
#
#   Skip flags (blacklist mode - run all except specified):
#     --skip-create      Skip cluster creation (reuse existing cluster)
#     --skip-install     Skip Kagenti platform installation
#     --skip-agents      Skip building/deploying test agents
#     --skip-test        Skip running E2E tests
#     --skip-destroy     Skip cluster destruction (keep cluster after tests)
#
#   Other options:
#     --clean-kagenti    Uninstall Kagenti before installing (fresh install)
#     --env ENV          Environment for Kagenti installer (default: ocp)
#
# EXAMPLES:
#   # Full run (default - everything)
#   ./.github/scripts/local-setup/hypershift-full-test.sh
#
#   # First dev run - everything except destroy (blacklist mode)
#   ./.github/scripts/local-setup/hypershift-full-test.sh --skip-destroy
#
#   # CI deploy step - only install + agents (whitelist mode)
#   ./.github/scripts/local-setup/hypershift-full-test.sh --include-install --include-agents
#
#   # CI test step - only tests (whitelist mode)
#   ./.github/scripts/local-setup/hypershift-full-test.sh --include-test
#
#   # Iterate on existing cluster (blacklist mode)
#   ./.github/scripts/local-setup/hypershift-full-test.sh --skip-create --skip-destroy
#
#   # Fresh kagenti on existing cluster (whitelist mode)
#   ./.github/scripts/local-setup/hypershift-full-test.sh --include-install --include-agents --include-test --clean-kagenti
#
#   # Final cleanup - only destroy (whitelist mode)
#   ./.github/scripts/local-setup/hypershift-full-test.sh --include-destroy
#

set -euo pipefail

# Handle Ctrl+C properly - kill child processes only (not the terminal!)
cleanup() {
    echo ""
    echo -e "\033[0;31m✗ Interrupted! Killing child processes...\033[0m"
    # Kill only direct child processes, not the entire process group
    # Using pkill -P is safer than kill -$$ which can kill the terminal
    pkill -P $$ 2>/dev/null || true
    sleep 1
    pkill -9 -P $$ 2>/dev/null || true
    exit 130
}
trap cleanup SIGINT SIGTERM

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="${GITHUB_WORKSPACE:-$(cd "$SCRIPT_DIR/../../.." && pwd)}"

# Parse arguments - track both include and skip flags
INCLUDE_CREATE=false
INCLUDE_INSTALL=false
INCLUDE_AGENTS=false
INCLUDE_TEST=false
INCLUDE_DESTROY=false
SKIP_CREATE=false
SKIP_INSTALL=false
SKIP_AGENTS=false
SKIP_TEST=false
SKIP_KAGENTI_UNINSTALL=false
SKIP_DESTROY=false
INCLUDE_KAGENTI_UNINSTALL=false
CLEAN_KAGENTI=false
KAGENTI_ENV="${KAGENTI_ENV:-ocp}"
CLUSTER_SUFFIX=""
WHITELIST_MODE=false

while [[ $# -gt 0 ]]; do
    case $1 in
        # Include flags
        --include-cluster-create)
            INCLUDE_CREATE=true
            WHITELIST_MODE=true
            shift
            ;;
        --include-kagenti-install)
            INCLUDE_INSTALL=true
            WHITELIST_MODE=true
            shift
            ;;
        --include-agents)
            INCLUDE_AGENTS=true
            WHITELIST_MODE=true
            shift
            ;;
        --include-test)
            INCLUDE_TEST=true
            WHITELIST_MODE=true
            shift
            ;;
        --include-kagenti-uninstall)
            INCLUDE_KAGENTI_UNINSTALL=true
            WHITELIST_MODE=true
            shift
            ;;
        --include-cluster-destroy)
            INCLUDE_DESTROY=true
            WHITELIST_MODE=true
            shift
            ;;
        # Skip flags
        --skip-cluster-create)
            SKIP_CREATE=true
            shift
            ;;
        --skip-kagenti-install)
            SKIP_INSTALL=true
            shift
            ;;
        --skip-agents)
            SKIP_AGENTS=true
            shift
            ;;
        --skip-test)
            SKIP_TEST=true
            shift
            ;;
        --skip-kagenti-uninstall)
            SKIP_KAGENTI_UNINSTALL=true
            shift
            ;;
        --skip-cluster-destroy)
            SKIP_DESTROY=true
            shift
            ;;
        --clean-kagenti)
            CLEAN_KAGENTI=true
            shift
            ;;
        --env)
            KAGENTI_ENV="$2"
            shift 2
            ;;
        *)
            CLUSTER_SUFFIX="$1"
            shift
            ;;
    esac
done

# Resolve final phase settings based on mode
# Whitelist mode: only run phases explicitly included
# Blacklist mode: run all phases except those skipped
if [ "$WHITELIST_MODE" = "true" ]; then
    RUN_CREATE=$INCLUDE_CREATE
    RUN_INSTALL=$INCLUDE_INSTALL
    RUN_AGENTS=$INCLUDE_AGENTS
    RUN_TEST=$INCLUDE_TEST
    RUN_KAGENTI_UNINSTALL=$INCLUDE_KAGENTI_UNINSTALL
    RUN_DESTROY=$INCLUDE_DESTROY
else
    # Blacklist mode - default all to true, then apply skips
    # Note: kagenti-uninstall defaults to false in blacklist mode (opt-in)
    RUN_CREATE=true
    RUN_INSTALL=true
    RUN_AGENTS=true
    RUN_TEST=true
    RUN_KAGENTI_UNINSTALL=false
    RUN_DESTROY=true
    [ "$SKIP_CREATE" = "true" ] && RUN_CREATE=false
    [ "$SKIP_INSTALL" = "true" ] && RUN_INSTALL=false
    [ "$SKIP_AGENTS" = "true" ] && RUN_AGENTS=false
    [ "$SKIP_TEST" = "true" ] && RUN_TEST=false
    [ "$SKIP_KAGENTI_UNINSTALL" = "true" ] && RUN_KAGENTI_UNINSTALL=false
    [ "$SKIP_DESTROY" = "true" ] && RUN_DESTROY=false
fi

# Default suffix - use sanitized username for local development
SANITIZED_USER=$(echo "${USER:-local}" | tr '[:upper:]' '[:lower:]' | sed 's/[^a-z0-9]/-/g' | cut -c1-10)
CLUSTER_SUFFIX="${CLUSTER_SUFFIX:-$SANITIZED_USER}"

# Validate cluster suffix for RFC1123 compliance (lowercase, alphanumeric, hyphens only)
if ! [[ "$CLUSTER_SUFFIX" =~ ^[a-z0-9]([a-z0-9-]*[a-z0-9])?$ ]]; then
    echo -e "\033[0;31m✗\033[0m Error: Invalid cluster suffix '$CLUSTER_SUFFIX'" >&2
    echo "" >&2
    echo "Cluster names must be valid RFC1123 labels:" >&2
    echo "  - Only lowercase letters (a-z), numbers (0-9), and hyphens (-)" >&2
    echo "  - Must start and end with an alphanumeric character" >&2
    echo "  - No underscores, uppercase letters, or special characters" >&2
    echo "" >&2
    echo "Examples of valid suffixes: pr529, test-1, my-cluster" >&2
    echo "Examples of invalid suffixes: PR529, test_1, -cluster-, my.cluster" >&2
    exit 1
fi

# Colors
GREEN='\033[0;32m'
BLUE='\033[0;34m'
RED='\033[0;31m'
NC='\033[0m'

log_phase() { echo -e "\n${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"; echo -e "${BLUE}┃${NC} $1"; echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}\n"; }
log_step() { echo -e "${GREEN}▶${NC} $1"; }
log_error() { echo -e "${RED}✗${NC} $1" >&2; }

cd "$REPO_ROOT"

# ============================================================================
# Load credentials
# ============================================================================

# Detect CI mode (GitHub Actions sets GITHUB_ACTIONS=true)
CI_MODE="${GITHUB_ACTIONS:-false}"

# MANAGED_BY_TAG controls cluster naming and IAM scoping:
#   - Local: defaults to kagenti-hypershift-custom (shared by all developers)
#   - CI: set via secrets (kagenti-hypershift-ci)
MANAGED_BY_TAG="${MANAGED_BY_TAG:-kagenti-hypershift-custom}"

# Find .env file - priority: 1) .env.${MANAGED_BY_TAG}, 2) legacy .env.hypershift-ci, 3) any .env.kagenti-*
find_env_file() {
    if [ -f "$REPO_ROOT/.env.${MANAGED_BY_TAG}" ]; then
        echo "$REPO_ROOT/.env.${MANAGED_BY_TAG}"
    elif [ -f "$REPO_ROOT/.env.hypershift-ci" ]; then
        echo "$REPO_ROOT/.env.hypershift-ci"
    else
        # Find any .env.kagenti-* file
        ls "$REPO_ROOT"/.env.kagenti-* 2>/dev/null | head -1
    fi
}

if [ "$CI_MODE" = "true" ]; then
    # CI mode: credentials are passed via environment variables from GitHub secrets
    # Required: MANAGED_BY_TAG, AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_REGION,
    #           HCP_ROLE_NAME, KUBECONFIG (already set in GITHUB_ENV)
    log_step "Using CI credentials from environment"
else
    # Local mode: load from .env file
    ENV_FILE=$(find_env_file)
    if [ -z "$ENV_FILE" ] || [ ! -f "$ENV_FILE" ]; then
        log_error "No .env file found. Run setup-hypershift-ci-credentials.sh first."
        log_error "Expected: .env.${MANAGED_BY_TAG} or .env.hypershift-ci"
        exit 1
    fi
    # shellcheck source=/dev/null
    source "$ENV_FILE"
    log_step "Loaded credentials from $(basename "$ENV_FILE")"
    # Update MANAGED_BY_TAG from env file if it was set there
    MANAGED_BY_TAG="${MANAGED_BY_TAG:-kagenti-hypershift-custom}"
fi
CLUSTER_NAME="${MANAGED_BY_TAG}-${CLUSTER_SUFFIX}"

# ============================================================================
# Validate cluster name length (AWS IAM role name limit)
# ============================================================================
# AWS IAM role names have a 64-character limit.
# HyperShift creates roles with pattern: <cluster-name>-<role-suffix>
# The longest suffix is "cloud-network-config-controller" (32 chars)
# So max cluster name = 64 - 32 = 32 characters
#
MAX_CLUSTER_NAME_LENGTH=32
LONGEST_IAM_SUFFIX="cloud-network-config-controller"
CLUSTER_NAME_LENGTH=${#CLUSTER_NAME}

if [ "$CLUSTER_NAME_LENGTH" -gt "$MAX_CLUSTER_NAME_LENGTH" ]; then
    echo ""
    echo -e "${RED}╔════════════════════════════════════════════════════════════════════════════╗${NC}"
    echo -e "${RED}║   ERROR: Cluster name too long for AWS IAM                                 ║${NC}"
    echo -e "${RED}╚════════════════════════════════════════════════════════════════════════════╝${NC}"
    echo ""
    echo "Cluster name: $CLUSTER_NAME"
    echo "Length: $CLUSTER_NAME_LENGTH characters (max: $MAX_CLUSTER_NAME_LENGTH)"
    echo ""
    echo "WHY: AWS IAM role names have a 64-character limit."
    echo "     HyperShift creates roles like: <cluster-name>-$LONGEST_IAM_SUFFIX"
    echo "     Your cluster name ($CLUSTER_NAME_LENGTH) + suffix (${#LONGEST_IAM_SUFFIX}) = $((CLUSTER_NAME_LENGTH + ${#LONGEST_IAM_SUFFIX} + 1)) chars > 64"
    echo ""
    echo "FIX: Use a shorter cluster suffix."
    MAX_SUFFIX_LENGTH=$((MAX_CLUSTER_NAME_LENGTH - ${#MANAGED_BY_TAG} - 1))
    echo "     With prefix '$MANAGED_BY_TAG' (${#MANAGED_BY_TAG} chars),"
    echo "     your suffix can be at most $MAX_SUFFIX_LENGTH characters."
    echo ""
    echo "Examples of valid suffixes:"
    echo "  - $SANITIZED_USER (your username, truncated to 10 chars)"
    echo "  - pr123"
    echo "  - test1"
    echo ""
    exit 1
fi

echo ""
echo "Configuration:"
echo "  Cluster Name:   $CLUSTER_NAME"
echo "  Environment:    $KAGENTI_ENV"
echo "  Mode:           $([ "$WHITELIST_MODE" = "true" ] && echo "Whitelist (explicit)" || echo "Blacklist (full run)")"
echo "  Phases:"
echo "    cluster-create:     $RUN_CREATE"
echo "    kagenti-install:    $RUN_INSTALL"
echo "    agents:             $RUN_AGENTS"
echo "    test:               $RUN_TEST"
echo "    kagenti-uninstall:  $RUN_KAGENTI_UNINSTALL"
echo "    cluster-destroy:    $RUN_DESTROY"
echo "  Clean Kagenti:  $CLEAN_KAGENTI"
echo ""

# ============================================================================
# PHASE 1: Create Cluster
# ============================================================================

if [ "$RUN_CREATE" = "true" ]; then
    log_phase "PHASE 1: Create HyperShift Cluster"
    log_step "Creating cluster: $CLUSTER_NAME"

    ./.github/scripts/hypershift/create-cluster.sh "$CLUSTER_SUFFIX"
else
    log_phase "PHASE 1: Skipping Cluster Creation"
fi

# ============================================================================
# Setup kubeconfig (needed for phases 2, 3, 4)
# ============================================================================

# For phases 2-4, we need the hosted cluster kubeconfig (cluster-admin on hosted cluster)
# This is different from the management cluster kubeconfig used for create/destroy
HOSTED_KUBECONFIG="$HOME/clusters/hcp/$CLUSTER_NAME/auth/kubeconfig"

# In CI, KUBECONFIG is set by the workflow for each phase
# Locally, we always use the hosted cluster kubeconfig for phases 2-4
if [ "$CI_MODE" != "true" ]; then
    if [ "$RUN_INSTALL" = "true" ] || [ "$RUN_AGENTS" = "true" ] || [ "$RUN_TEST" = "true" ]; then
        export KUBECONFIG="$HOSTED_KUBECONFIG"
    fi
fi

if [ ! -f "$KUBECONFIG" ]; then
    if [ "$RUN_INSTALL" = "true" ] || [ "$RUN_AGENTS" = "true" ] || [ "$RUN_TEST" = "true" ]; then
        log_error "Kubeconfig not found at $KUBECONFIG"
        log_error "Either cluster creation failed or cluster doesn't exist."
        exit 1
    fi
else
    log_step "Using kubeconfig: $KUBECONFIG"
    oc get nodes || kubectl get nodes
fi

# ============================================================================
# PHASE 2: Install Kagenti Platform
# ============================================================================

if [ "$RUN_INSTALL" = "true" ]; then
    log_phase "PHASE 2: Install Kagenti Platform"

    if [ "$CLEAN_KAGENTI" = "true" ]; then
        log_step "Uninstalling Kagenti (--clean-kagenti)..."
        ./deployments/ansible/cleanup-install.sh || true
    fi

    log_step "Installing Kagenti platform..."
    ./.github/scripts/kagenti-operator/30-run-installer.sh --env "$KAGENTI_ENV"

    log_step "Waiting for CRDs..."
    ./.github/scripts/kagenti-operator/41-wait-crds.sh

    log_step "Applying pipeline template..."
    ./.github/scripts/kagenti-operator/42-apply-pipeline-template.sh

    log_step "Waiting for Toolhive CRDs..."
    ./.github/scripts/kagenti-operator/43-wait-toolhive-crds.sh
else
    log_phase "PHASE 2: Skipping Kagenti Installation"
fi

# ============================================================================
# PHASE 3: Deploy Test Agents
# ============================================================================

if [ "$RUN_AGENTS" = "true" ]; then
    log_phase "PHASE 3: Deploy Test Agents"

    log_step "Building weather-tool..."
    ./.github/scripts/kagenti-operator/71-build-weather-tool.sh

    log_step "Deploying weather-tool..."
    ./.github/scripts/kagenti-operator/72-deploy-weather-tool.sh

    log_step "Patching weather-tool..."
    ./.github/scripts/kagenti-operator/73-patch-weather-tool.sh

    log_step "Deploying weather-agent..."
    ./.github/scripts/kagenti-operator/74-deploy-weather-agent.sh
else
    log_phase "PHASE 3: Skipping Agent Deployment"
fi

# ============================================================================
# PHASE 4: Run E2E Tests
# ============================================================================

if [ "$RUN_TEST" = "true" ]; then
    log_phase "PHASE 4: Run E2E Tests"

    log_step "Running E2E tests..."
    # Get agent URL from route (if not already set)
    # Wait for the route to be created by kagenti-operator (can take a few seconds after deployment is ready)
    if [ -z "${AGENT_URL:-}" ]; then
        log_step "Waiting for weather-service route..."
        for i in {1..30}; do
            ROUTE_HOST=$(oc get route -n team1 weather-service -o jsonpath='{.spec.host}' 2>/dev/null || echo "")
            if [ -n "$ROUTE_HOST" ]; then
                export AGENT_URL="https://$ROUTE_HOST"
                log_step "Found route: $AGENT_URL"
                break
            fi
            echo "[$i/30] Waiting for route to be created..."
            sleep 5
        done
        if [ -z "${AGENT_URL:-}" ]; then
            log_error "weather-service route not found after 150 seconds"
            # Show what routes exist in team1 namespace for debugging
            echo "Available routes in team1:"
            oc get routes -n team1 2>/dev/null || echo "  (none)"
            echo "Available httproutes in team1:"
            kubectl get httproutes -n team1 2>/dev/null || echo "  (none)"
            export AGENT_URL="http://localhost:8000"
        fi
    fi

    # Get Keycloak URL from route (if not already set)
    if [ -z "${KEYCLOAK_URL:-}" ]; then
        KEYCLOAK_HOST=$(oc get route -n keycloak keycloak -o jsonpath='{.spec.host}' 2>/dev/null || echo "")
        if [ -n "$KEYCLOAK_HOST" ]; then
            export KEYCLOAK_URL="https://$KEYCLOAK_HOST"
            # OpenShift routes use self-signed certs, disable SSL verification
            export KEYCLOAK_VERIFY_SSL="false"
        else
            log_error "keycloak route not found"
            export KEYCLOAK_URL="http://localhost:8081"
        fi
    fi

    # Set config file based on environment
    export KAGENTI_CONFIG_FILE="${KAGENTI_CONFIG_FILE:-deployments/envs/${KAGENTI_ENV}_values.yaml}"

    log_step "AGENT_URL: $AGENT_URL"
    log_step "KEYCLOAK_URL: $KEYCLOAK_URL"
    log_step "KAGENTI_CONFIG_FILE: $KAGENTI_CONFIG_FILE"

    ./.github/scripts/kagenti-operator/90-run-e2e-tests.sh
else
    log_phase "PHASE 4: Skipping E2E Tests"
fi

# ============================================================================
# PHASE 5: Kagenti Uninstall (optional)
# ============================================================================

if [ "$RUN_KAGENTI_UNINSTALL" = "true" ]; then
    log_phase "PHASE 5: Uninstall Kagenti Platform"
    log_step "Running cleanup-install.sh..."
    ./deployments/ansible/cleanup-install.sh || {
        log_error "Kagenti uninstall failed (non-fatal)"
    }
else
    log_phase "PHASE 5: Skipping Kagenti Uninstall"
fi

# ============================================================================
# PHASE 6: Destroy Cluster (optional)
# ============================================================================

if [ "$RUN_DESTROY" = "true" ]; then
    log_phase "PHASE 6: Destroy Cluster"

    # Reload credentials (in case KUBECONFIG was changed)
    if [ "$CI_MODE" != "true" ]; then
        ENV_FILE=$(find_env_file)
        if [ -n "$ENV_FILE" ] && [ -f "$ENV_FILE" ]; then
            # shellcheck source=/dev/null
            source "$ENV_FILE"
        fi
    fi

    ./.github/scripts/hypershift/destroy-cluster.sh "$CLUSTER_SUFFIX"
else
    log_phase "PHASE 6: Skipping Cluster Destruction"
    echo ""
    echo "Cluster kept for debugging. To destroy later:"
    echo "  ./.github/scripts/hypershift/destroy-cluster.sh $CLUSTER_SUFFIX"
    echo ""
fi

echo ""
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${GREEN}┃${NC} Full test completed successfully!"
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""
