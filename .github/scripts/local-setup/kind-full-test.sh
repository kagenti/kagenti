#!/usr/bin/env bash
#
# Run Full Kind Test
#
# Creates a Kind cluster, deploys Kagenti, deploys test agents, and runs E2E tests.
# Supports both whitelist (--include-*) and blacklist (--skip-*) modes.
#
# USAGE:
#   ./.github/scripts/local-setup/kind-full-test.sh [options]
#
# MODES:
#   Whitelist mode: If ANY include flag is used, only explicitly enabled phases run
#   Blacklist mode: If only --skip-X flags are used, all phases run except those skipped
#
# OPTIONS:
#   Include flags (whitelist mode - only run specified phases):
#     --include-cluster-create     Include Kind cluster creation phase
#     --include-kagenti-install    Include Kagenti platform installation phase
#     --include-agents             Include building/deploying test agents phase
#     --include-test               Include E2E test phase
#     --include-kagenti-uninstall  Include Kagenti platform uninstall phase
#     --include-cluster-destroy    Include Kind cluster destruction phase
#
#   Skip flags (blacklist mode - run all except specified):
#     --skip-cluster-create        Skip cluster creation (reuse existing)
#     --skip-kagenti-install       Skip Kagenti platform installation
#     --skip-agents                Skip building/deploying test agents
#     --skip-test                  Skip running E2E tests
#     --skip-kagenti-uninstall     Skip Kagenti uninstall (default: skipped)
#     --skip-cluster-destroy       Skip cluster destruction (keep for debugging)
#
#   Other options:
#     --clean-kagenti    Uninstall Kagenti before installing (fresh install)
#     --env ENV          Environment for Kagenti installer (default: dev)
#
# EXAMPLES:
#   # Full run (default - everything)
#   ./.github/scripts/local-setup/kind-full-test.sh
#
#   # Dev run - everything except destroy (keep cluster for debugging)
#   ./.github/scripts/local-setup/kind-full-test.sh --skip-cluster-destroy
#
#   # Iterate on existing cluster
#   ./.github/scripts/local-setup/kind-full-test.sh --skip-cluster-create --skip-cluster-destroy
#
#   # Fresh kagenti on existing cluster
#   ./.github/scripts/local-setup/kind-full-test.sh --skip-cluster-create --clean-kagenti --skip-cluster-destroy
#
#   # Final cleanup - only destroy
#   ./.github/scripts/local-setup/kind-full-test.sh --include-cluster-destroy
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
KAGENTI_ENV="${KAGENTI_ENV:-dev}"
CLUSTER_NAME="${CLUSTER_NAME:-kagenti}"
WHITELIST_MODE=false

while [[ $# -gt 0 ]]; do
    case $1 in
        # Include flags - new names (preferred) and legacy aliases
        --include-cluster-create|--include-create)
            INCLUDE_CREATE=true
            WHITELIST_MODE=true
            shift
            ;;
        --include-kagenti-install|--include-install)
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
        --include-cluster-destroy|--include-destroy)
            INCLUDE_DESTROY=true
            WHITELIST_MODE=true
            shift
            ;;
        # Skip flags - new names (preferred) and legacy aliases
        --skip-cluster-create|--skip-create)
            SKIP_CREATE=true
            shift
            ;;
        --skip-kagenti-install|--skip-install)
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
        --skip-cluster-destroy|--skip-destroy)
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
        --cluster-name)
            CLUSTER_NAME="$2"
            shift 2
            ;;
        *)
            echo "Unknown option: $1"
            echo "Run with --help for usage"
            exit 1
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

# Colors
GREEN='\033[0;32m'
BLUE='\033[0;34m'
RED='\033[0;31m'
NC='\033[0m'

log_phase() { echo -e "\n${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"; echo -e "${BLUE}┃${NC} $1"; echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}\n"; }
log_step() { echo -e "${GREEN}▶${NC} $1"; }
log_error() { echo -e "${RED}✗${NC} $1" >&2; }

cd "$REPO_ROOT"

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
# PHASE 1: Create Kind Cluster
# ============================================================================

if [ "$RUN_CREATE" = "true" ]; then
    log_phase "PHASE 1: Create Kind Cluster"
    log_step "Creating cluster: $CLUSTER_NAME"

    CLUSTER_NAME="$CLUSTER_NAME" ./.github/scripts/kind/create-cluster.sh
else
    log_phase "PHASE 1: Skipping Cluster Creation"
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

    log_step "Creating secrets..."
    ./.github/scripts/common/20-create-secrets.sh

    log_step "Running Ansible installer..."
    ./.github/scripts/kagenti-operator/30-run-installer.sh --env "$KAGENTI_ENV"

    log_step "Waiting for platform to be ready..."
    ./.github/scripts/common/40-wait-platform-ready.sh

    log_step "Installing Ollama..."
    ./.github/scripts/common/50-install-ollama.sh || true

    log_step "Pulling Ollama model..."
    ./.github/scripts/common/60-pull-ollama-model.sh || true

    log_step "Configuring dockerhost..."
    ./.github/scripts/common/70-configure-dockerhost.sh

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

    log_step "Installing test dependencies..."
    ./.github/scripts/common/80-install-test-deps.sh

    log_step "Starting port-forward..."
    ./.github/scripts/common/85-start-port-forward.sh

    # Set config file based on environment
    export KAGENTI_CONFIG_FILE="${KAGENTI_CONFIG_FILE:-deployments/envs/${KAGENTI_ENV}_values.yaml}"
    log_step "KAGENTI_CONFIG_FILE: $KAGENTI_CONFIG_FILE"

    log_step "Running E2E tests..."
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
# PHASE 6: Destroy Kind Cluster (optional)
# ============================================================================

if [ "$RUN_DESTROY" = "true" ]; then
    log_phase "PHASE 6: Destroy Kind Cluster"
    CLUSTER_NAME="$CLUSTER_NAME" ./.github/scripts/kind/destroy-cluster.sh
else
    log_phase "PHASE 6: Skipping Cluster Destruction"
    echo ""
    echo "Cluster kept for debugging. To destroy later:"
    echo "  ./.github/scripts/kind/destroy-cluster.sh"
    echo ""
fi

echo ""
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${GREEN}┃${NC} Full test completed successfully!"
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""
