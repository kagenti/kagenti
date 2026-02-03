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

# Script name for help text (allows wrapper scripts to override)
SCRIPT_NAME="${SCRIPT_NAME:-$(basename "$0")}"
SCRIPT_DESCRIPTION="${SCRIPT_DESCRIPTION:-Run full HyperShift test cycle: create cluster, deploy Kagenti, run tests, destroy cluster.}"

show_help() {
    cat << EOF
$SCRIPT_NAME - $SCRIPT_DESCRIPTION

USAGE:
    $SCRIPT_NAME [options] [cluster-suffix]

MODES:
    Whitelist mode: If ANY --include-* flag is used, only those phases run
    Blacklist mode: If only --skip-* flags are used, all phases run except skipped ones

PHASES:
    cluster-create    Create HyperShift cluster (~15 min)
    kagenti-install   Install Kagenti platform via Ansible
    agents            Build and deploy test agents (weather-tool, weather-agent)
    test              Run E2E tests
    kagenti-uninstall Uninstall Kagenti (opt-in, off by default)
    cluster-destroy   Destroy HyperShift cluster (~10 min)

OPTIONS:
    Include flags (whitelist mode):
        --include-cluster-create     Include cluster creation
        --include-kagenti-install    Include Kagenti installation
        --include-agents             Include agent deployment
        --include-test               Include E2E tests
        --include-kagenti-uninstall  Include Kagenti uninstall
        --include-cluster-destroy    Include cluster destruction

    Skip flags (blacklist mode):
        --skip-cluster-create        Skip cluster creation (use existing)
        --skip-kagenti-install       Skip Kagenti installation
        --skip-agents                Skip agent deployment
        --skip-test                  Skip E2E tests
        --skip-kagenti-uninstall     Skip Kagenti uninstall (default)
        --skip-cluster-destroy       Skip cluster destruction (keep cluster)

    Other options:
        --clean-kagenti              Uninstall Kagenti before installing
        --env ENV                    Environment for installer (default: ocp)
        -h, --help                   Show this help message

    Cluster suffix:
        Optional suffix for cluster name. Default: \$USER (truncated to 5 chars)
        Full cluster name: \${MANAGED_BY_TAG}-\${suffix}

EXAMPLES:
    # Full run (create -> deploy -> test -> destroy)
    $SCRIPT_NAME

    # Dev flow: run everything, keep cluster for debugging
    $SCRIPT_NAME --skip-cluster-destroy

    # Iterate on existing cluster
    $SCRIPT_NAME --skip-cluster-create --skip-cluster-destroy

    # Run only tests on existing deployment
    $SCRIPT_NAME --include-test

    # Fresh install on existing cluster
    $SCRIPT_NAME --skip-cluster-create --skip-cluster-destroy --clean-kagenti

    # Custom cluster suffix
    $SCRIPT_NAME pr529 --skip-cluster-destroy

CREDENTIALS:
    For cluster create/destroy: source .env.kagenti-hypershift-custom
    For middle phases only:     export HOSTED_KUBECONFIG=~/clusters/hcp/<name>/auth/kubeconfig

EOF
    exit 0
}

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
        -h|--help)
            show_help
            ;;
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
# Truncate to 5 chars to fit within AWS IAM role name limits with default MANAGED_BY_TAG
# (default prefix is 26 chars, max cluster name is 32, so 32-26-1=5 chars for suffix)
SANITIZED_USER=$(echo "${USER:-local}" | tr '[:upper:]' '[:lower:]' | sed 's/[^a-z0-9]/-/g' | cut -c1-5)
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
YELLOW='\033[1;33m'
NC='\033[0m'

log_phase() { echo -e "\n${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"; echo -e "${BLUE}┃${NC} $1"; echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}\n"; }
log_step() { echo -e "${GREEN}▶${NC} $1"; }
log_warn() { echo -e "${YELLOW}⚠${NC} $1"; }
log_error() { echo -e "${RED}✗${NC} $1" >&2; }

cd "$REPO_ROOT"

# ============================================================================
# Load credentials and determine cluster name
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

# Determine if we need management cluster credentials (create/destroy phases)
# This is computed early so we can skip .env loading if not needed
NEEDS_MGMT_CREDS_EARLY=false
[ "$INCLUDE_CREATE" = "true" ] && NEEDS_MGMT_CREDS_EARLY=true
[ "$INCLUDE_DESTROY" = "true" ] && NEEDS_MGMT_CREDS_EARLY=true
# In blacklist mode (no --include-* flags), default is to run create/destroy
if [ "$WHITELIST_MODE" = "false" ]; then
    [ "$SKIP_CREATE" = "false" ] && NEEDS_MGMT_CREDS_EARLY=true
    [ "$SKIP_DESTROY" = "false" ] && NEEDS_MGMT_CREDS_EARLY=true
fi

# Load credentials if not already in environment
if [ "$CI_MODE" = "true" ]; then
    # CI mode: credentials are passed via environment variables from GitHub secrets
    log_step "Using CI credentials from environment"
elif [ -n "${AWS_ACCESS_KEY_ID:-}" ] && [ -n "${AWS_SECRET_ACCESS_KEY:-}" ]; then
    # Credentials already in environment (user ran: source .env.xxx before script)
    log_step "Using pre-sourced credentials from environment"
elif [ "$NEEDS_MGMT_CREDS_EARLY" = "true" ]; then
    # Need management cluster credentials - try to load from .env file
    ENV_FILE=$(find_env_file)
    if [ -z "$ENV_FILE" ] || [ ! -f "$ENV_FILE" ]; then
        log_error "No .env file found. Either:"
        log_error "  1. Run: source .env.${MANAGED_BY_TAG} before this script"
        log_error "  2. Run setup-hypershift-ci-credentials.sh to create .env file"
        log_error "Expected: .env.${MANAGED_BY_TAG} or .env.hypershift-ci in repo root"
        exit 1
    fi
    # shellcheck source=/dev/null
    source "$ENV_FILE"
    log_step "Loaded credentials from $(basename "$ENV_FILE")"
    # Update MANAGED_BY_TAG from env file if it was set there
    MANAGED_BY_TAG="${MANAGED_BY_TAG:-kagenti-hypershift-custom}"
else
    # Only running middle phases - management cluster credentials not required
    # User can set HOSTED_KUBECONFIG directly
    log_step "Skipping .env loading (create/destroy not requested)"
fi

# Compute cluster name and kubeconfig paths
CLUSTER_NAME="${MANAGED_BY_TAG}-${CLUSTER_SUFFIX}"

# TWO KUBECONFIGS:
#   MGMT_KUBECONFIG  - Management cluster kubeconfig (for create/destroy cluster operations)
#                      Set via .env file or CI secrets, points to the HyperShift management cluster
#   HOSTED_KUBECONFIG - Hosted cluster kubeconfig (for install/agents/test operations)
#                       Created by cluster creation at ~/clusters/hcp/<cluster-name>/auth/kubeconfig
#
# This separation prevents accidentally running kubectl commands against the wrong cluster.
#
# SIMPLIFIED USAGE:
#   If only running middle phases (install/agents/test), you can skip sourcing .env and just set:
#     export HOSTED_KUBECONFIG=~/clusters/hcp/<cluster-name>/auth/kubeconfig
#     ./hypershift-full-test.sh --skip-cluster-create --skip-cluster-destroy
#
MGMT_KUBECONFIG="${KUBECONFIG:-}"
# Allow override via HOSTED_KUBECONFIG env var, otherwise compute from cluster name
HOSTED_KUBECONFIG="${HOSTED_KUBECONFIG:-$HOME/clusters/hcp/$CLUSTER_NAME/auth/kubeconfig}"

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
    echo "WHY THIS LIMIT EXISTS:"
    echo "  AWS IAM role names have a 64-character limit."
    echo "  HyperShift creates roles with pattern: <cluster-name>-<role-suffix>"
    echo "  The longest role suffix is '$LONGEST_IAM_SUFFIX' (${#LONGEST_IAM_SUFFIX} chars)."
    echo ""
    echo "  Your cluster name: $CLUSTER_NAME_LENGTH chars"
    echo "  Longest role suffix: ${#LONGEST_IAM_SUFFIX} chars + 1 hyphen"
    echo "  Total: $((CLUSTER_NAME_LENGTH + ${#LONGEST_IAM_SUFFIX} + 1)) chars (exceeds 64)"
    echo ""
    MAX_SUFFIX_LENGTH=$((MAX_CLUSTER_NAME_LENGTH - ${#MANAGED_BY_TAG} - 1))
    echo "HOW TO FIX:"
    echo "  With your current MANAGED_BY_TAG '$MANAGED_BY_TAG' (${#MANAGED_BY_TAG} chars),"
    echo "  your cluster suffix can be at most $MAX_SUFFIX_LENGTH characters."
    echo ""
    echo "  Examples of valid suffixes: ci, dev, pr42, test1"
    echo ""
    echo "  Note: If you didn't specify a suffix, your username was used."
    echo "        Try passing an explicit short suffix as an argument."
    echo ""
    exit 1
fi

# ============================================================================
# PRE-FLIGHT CHECKS
# ============================================================================
# Validate required credentials BEFORE running any phases.
# Different phases require different credentials:
#   - cluster-create/destroy: AWS creds + Management cluster KUBECONFIG
#   - install/agents/test: Hosted cluster KUBECONFIG (created by cluster-create)

echo ""
echo "╔════════════════════════════════════════════════════════════════════════════╗"
echo "║                           PRE-FLIGHT CHECKS                                ║"
echo "╚════════════════════════════════════════════════════════════════════════════╝"
echo ""

PREFLIGHT_ERRORS=0

# Check if we need management cluster credentials (for create/destroy)
NEEDS_MGMT_CREDS=false
[ "$RUN_CREATE" = "true" ] && NEEDS_MGMT_CREDS=true
[ "$RUN_DESTROY" = "true" ] && NEEDS_MGMT_CREDS=true

# Check if we need hosted cluster kubeconfig (for install/agents/test)
NEEDS_HOSTED_KUBECONFIG=false
[ "$RUN_INSTALL" = "true" ] && NEEDS_HOSTED_KUBECONFIG=true
[ "$RUN_AGENTS" = "true" ] && NEEDS_HOSTED_KUBECONFIG=true
[ "$RUN_TEST" = "true" ] && NEEDS_HOSTED_KUBECONFIG=true
[ "$RUN_KAGENTI_UNINSTALL" = "true" ] && NEEDS_HOSTED_KUBECONFIG=true

echo "Cluster: $CLUSTER_NAME"
echo ""
echo "Phases to run:"
echo "  cluster-create:     $RUN_CREATE"
echo "  kagenti-install:    $RUN_INSTALL"
echo "  agents:             $RUN_AGENTS"
echo "  test:               $RUN_TEST"
echo "  kagenti-uninstall:  $RUN_KAGENTI_UNINSTALL"
echo "  cluster-destroy:    $RUN_DESTROY"
echo ""

# --- Check credentials for cluster create/destroy ---
if [ "$NEEDS_MGMT_CREDS" = "true" ]; then
    echo "Checking credentials for cluster-create/destroy phases..."

    # AWS credentials
    if [ -z "${AWS_ACCESS_KEY_ID:-}" ]; then
        log_error "AWS_ACCESS_KEY_ID not set (required for cluster operations)"
        PREFLIGHT_ERRORS=$((PREFLIGHT_ERRORS + 1))
    elif [ -z "${AWS_SECRET_ACCESS_KEY:-}" ]; then
        log_error "AWS_SECRET_ACCESS_KEY not set (required for cluster operations)"
        PREFLIGHT_ERRORS=$((PREFLIGHT_ERRORS + 1))
    else
        log_step "AWS credentials: configured"
    fi

    if [ -z "${AWS_REGION:-}" ]; then
        log_error "AWS_REGION not set (required for cluster operations)"
        PREFLIGHT_ERRORS=$((PREFLIGHT_ERRORS + 1))
    else
        log_step "AWS region: $AWS_REGION"
    fi

    # Management cluster kubeconfig
    if [ -z "$MGMT_KUBECONFIG" ]; then
        log_error "KUBECONFIG not set (required for cluster operations)"
        log_error "  This should point to the HyperShift management cluster"
        PREFLIGHT_ERRORS=$((PREFLIGHT_ERRORS + 1))
    elif [ ! -f "$MGMT_KUBECONFIG" ]; then
        log_error "Management cluster kubeconfig not found: $MGMT_KUBECONFIG"
        log_error "  Run setup-hypershift-ci-credentials.sh to create it"
        PREFLIGHT_ERRORS=$((PREFLIGHT_ERRORS + 1))
    else
        log_step "Management cluster kubeconfig: $MGMT_KUBECONFIG"
    fi
    echo ""
fi

# --- Check hosted cluster kubeconfig for install/agents/test ---
if [ "$NEEDS_HOSTED_KUBECONFIG" = "true" ]; then
    echo "Checking credentials for install/agents/test phases..."

    if [ "$RUN_CREATE" = "true" ]; then
        # Cluster will be created, kubeconfig will be generated
        log_step "Hosted cluster kubeconfig: will be created by cluster-create phase"
        log_step "  Expected path: $HOSTED_KUBECONFIG"
    else
        # Cluster creation is skipped, kubeconfig must already exist
        if [ ! -f "$HOSTED_KUBECONFIG" ]; then
            log_error "Hosted cluster kubeconfig not found: $HOSTED_KUBECONFIG"
            log_error ""
            log_error "  The hosted cluster kubeconfig is required for install/agents/test phases."
            log_error "  Since --skip-cluster-create was specified, the kubeconfig must already exist."
            log_error ""
            log_error "  Either:"
            log_error "    1. Remove --skip-cluster-create to create the cluster first"
            log_error "    2. Verify the cluster exists and kubeconfig is at the expected path"
            log_error "    3. Set KUBECONFIG to the correct path if using a non-default location"
            PREFLIGHT_ERRORS=$((PREFLIGHT_ERRORS + 1))
        else
            log_step "Hosted cluster kubeconfig: $HOSTED_KUBECONFIG"
            # Verify we can connect to the cluster
            if KUBECONFIG="$HOSTED_KUBECONFIG" kubectl cluster-info &>/dev/null; then
                log_step "Hosted cluster: reachable"
            else
                log_warn "Hosted cluster: not reachable (may be starting up)"
            fi
        fi
    fi
    echo ""
fi

# --- Summary ---
if [ $PREFLIGHT_ERRORS -gt 0 ]; then
    echo ""
    echo -e "${RED}╔════════════════════════════════════════════════════════════════════════════╗${NC}"
    echo -e "${RED}║   PRE-FLIGHT FAILED: $PREFLIGHT_ERRORS error(s) found                                      ║${NC}"
    echo -e "${RED}╚════════════════════════════════════════════════════════════════════════════╝${NC}"
    echo ""
    echo "To fix credential issues:"
    echo "  source .env.${MANAGED_BY_TAG}"
    echo ""
    echo "Or run setup script to create credentials:"
    echo "  ./.github/scripts/hypershift/setup-hypershift-ci-credentials.sh"
    echo ""
    exit 1
fi

echo -e "${GREEN}✓${NC} Pre-flight checks passed"
echo ""

# Print final configuration summary
echo "Configuration:"
echo "  Cluster Name:         $CLUSTER_NAME"
echo "  Environment:          $KAGENTI_ENV"
echo "  Mode:                 $([ "$WHITELIST_MODE" = "true" ] && echo "Whitelist (explicit)" || echo "Blacklist (full run)")"
echo "  Clean Kagenti:        $CLEAN_KAGENTI"
echo ""
echo "Kubeconfig usage:"
if [ "$NEEDS_MGMT_CREDS" = "true" ]; then
    echo "  Management cluster:   $MGMT_KUBECONFIG (for create/destroy)"
fi
if [ "$NEEDS_HOSTED_KUBECONFIG" = "true" ]; then
    echo "  Hosted cluster:       $HOSTED_KUBECONFIG (for install/agents/test)"
fi
echo ""

# ============================================================================
# PHASE 1: Create Cluster
# ============================================================================

if [ "$RUN_CREATE" = "true" ]; then
    log_phase "PHASE 1: Create HyperShift Cluster"
    log_step "Creating cluster: $CLUSTER_NAME"
    log_step "Using management cluster: $MGMT_KUBECONFIG"

    # Ensure create-cluster.sh uses the management cluster kubeconfig
    export KUBECONFIG="$MGMT_KUBECONFIG"
    ./.github/scripts/hypershift/create-cluster.sh "$CLUSTER_SUFFIX"
else
    log_phase "PHASE 1: Skipping Cluster Creation"
fi

# ============================================================================
# Switch to hosted cluster kubeconfig (for phases 2-5)
# ============================================================================

# For phases 2-5 (install, agents, test, uninstall), we need the hosted cluster kubeconfig.
# This is cluster-admin on the hosted cluster, NOT the management cluster.
if [ "$NEEDS_HOSTED_KUBECONFIG" = "true" ]; then
    # In CI, KUBECONFIG may be set by the workflow for each phase
    # Locally, we always use the hosted cluster kubeconfig
    if [ "$CI_MODE" != "true" ]; then
        export KUBECONFIG="$HOSTED_KUBECONFIG"
    fi

    # Verify the kubeconfig exists (should have been created by phase 1 or pre-existing)
    if [ ! -f "$KUBECONFIG" ]; then
        log_error "Hosted cluster kubeconfig not found at $KUBECONFIG"
        log_error "Cluster creation may have failed, or the cluster doesn't exist."
        exit 1
    fi

    log_step "Switched to hosted cluster: $KUBECONFIG"
    if ! oc get nodes 2>/dev/null && ! kubectl get nodes 2>/dev/null; then
        log_warn "Cannot connect to hosted cluster (it may still be initializing)"
    fi
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

    # Switch back to management cluster kubeconfig for destroy operations
    log_step "Switching to management cluster: $MGMT_KUBECONFIG"
    export KUBECONFIG="$MGMT_KUBECONFIG"

    ./.github/scripts/hypershift/destroy-cluster.sh "$CLUSTER_SUFFIX"
else
    log_phase "PHASE 6: Skipping Cluster Destruction"
    echo ""
    echo "Cluster kept for debugging."
    echo ""
    echo "To access the hosted cluster:"
    echo "  export KUBECONFIG=$HOSTED_KUBECONFIG"
    echo "  kubectl get nodes"
    echo ""
    echo "To destroy the cluster later:"
    echo "  source .env.${MANAGED_BY_TAG}  # Load management cluster credentials"
    echo "  ./.github/scripts/hypershift/destroy-cluster.sh $CLUSTER_SUFFIX"
    echo ""
fi

echo ""
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${GREEN}┃${NC} Full test completed successfully!"
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""
