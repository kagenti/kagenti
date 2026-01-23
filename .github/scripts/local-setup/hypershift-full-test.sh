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

# Handle Ctrl+C properly - kill all child processes
cleanup() {
    echo ""
    echo -e "\033[0;31m✗ Interrupted! Killing child processes...\033[0m"
    # Kill entire process group
    kill -TERM -$$ 2>/dev/null || true
    sleep 1
    kill -9 -$$ 2>/dev/null || true
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

# Default suffix
CLUSTER_SUFFIX="${CLUSTER_SUFFIX:-local}"

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

if [ "$CI_MODE" = "true" ]; then
    # CI mode: credentials are passed via environment variables from GitHub secrets
    # Required: MANAGED_BY_TAG, AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_REGION,
    #           HCP_ROLE_NAME, KUBECONFIG (already set in GITHUB_ENV)
    log_step "Using CI credentials from environment"
else
    # Local mode: load from .env file
    if [ ! -f ".env.hypershift-ci" ]; then
        log_error ".env.hypershift-ci not found. Run setup-hypershift-ci-credentials.sh first."
        exit 1
    fi
    # shellcheck source=/dev/null
    source .env.hypershift-ci
    log_step "Loaded credentials from .env.hypershift-ci"
fi

MANAGED_BY_TAG="${MANAGED_BY_TAG:-kagenti-hypershift-ci}"
CLUSTER_NAME="${MANAGED_BY_TAG}-${CLUSTER_SUFFIX}"

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

    # Reload CI creds (in case KUBECONFIG was changed)
    if [ "$CI_MODE" != "true" ]; then
        # shellcheck source=/dev/null
        source .env.hypershift-ci
    fi

    ./.github/scripts/hypershift/destroy-cluster.sh "$CLUSTER_SUFFIX"
else
    log_phase "PHASE 6: Skipping Cluster Destruction"
    echo ""
    echo "Cluster kept for debugging. To destroy later:"
    echo "  source .env.hypershift-ci"
    echo "  ./.github/scripts/hypershift/destroy-cluster.sh $CLUSTER_SUFFIX"
    echo ""
fi

echo ""
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${GREEN}┃${NC} Full test completed successfully!"
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""
