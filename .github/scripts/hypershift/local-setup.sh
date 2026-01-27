#!/usr/bin/env bash
#
# Local Setup for HyperShift Testing
#
# Sets up the local environment for manual cluster provisioning:
# - Installs hcp CLI from OpenShift console (to ~/.local/bin, no sudo needed)
# - Clones hypershift-automation fork (if needed)
# - Installs ansible collections
# - Extracts pull secret to expected location
# - Creates management cluster kubeconfig
#
# PREREQUISITES:
#   - ansible: pip install ansible-core
#   - Credentials: .env.hypershift-ci (from setup-hypershift-ci-credentials.sh)
#
# USAGE:
#   ./.github/scripts/hypershift/local-setup.sh
#

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
PARENT_DIR="$(cd "$REPO_ROOT/.." && pwd)"
HYPERSHIFT_AUTOMATION_DIR="$PARENT_DIR/hypershift-automation"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m'

log_info() { echo -e "${BLUE}→${NC} $1"; }
log_success() { echo -e "${GREEN}✓${NC} $1"; }
log_error() { echo -e "${RED}✗${NC} $1"; }

echo ""
echo "╔════════════════════════════════════════════════════════════════╗"
echo "║           Local HyperShift Testing Setup                       ║"
echo "╚════════════════════════════════════════════════════════════════╝"
echo ""

# ============================================================================
# 1. Load credentials
# ============================================================================

# Find .env file - priority: 1) .env.${MANAGED_BY_TAG}, 2) legacy .env.hypershift-ci, 3) any .env.kagenti-*
MANAGED_BY_TAG="${MANAGED_BY_TAG:-kagenti-hypershift-custom}"
find_env_file() {
    if [ -f "$REPO_ROOT/.env.${MANAGED_BY_TAG}" ]; then
        echo "$REPO_ROOT/.env.${MANAGED_BY_TAG}"
    elif [ -f "$REPO_ROOT/.env.hypershift-ci" ]; then
        echo "$REPO_ROOT/.env.hypershift-ci"
    else
        # Find any .env.kagenti-* file
        local found
        found=$(ls "$REPO_ROOT"/.env.kagenti-* 2>/dev/null | head -1)
        echo "${found:-}"
    fi
}

ENV_FILE=$(find_env_file)
if [ -z "$ENV_FILE" ] || [ ! -f "$ENV_FILE" ]; then
    log_error "No .env file found. Run setup-hypershift-ci-credentials.sh first."
    echo "  Expected: .env.${MANAGED_BY_TAG} or .env.hypershift-ci" >&2
    exit 1
fi

# shellcheck source=/dev/null
source "$ENV_FILE"
log_success "Loaded credentials from $(basename "$ENV_FILE")"

# ============================================================================
# 2. Install hcp CLI if missing
# ============================================================================

# Ensure ~/.local/bin exists and is in PATH
mkdir -p "$HOME/.local/bin"
if [[ ":$PATH:" != *":$HOME/.local/bin:"* ]]; then
    export PATH="$HOME/.local/bin:$PATH"
    log_info "Added ~/.local/bin to PATH (add to your shell profile for persistence)"
fi

if command -v hcp &>/dev/null; then
    HCP_VERSION=$(hcp version 2>/dev/null | head -1 || echo "installed")
    log_success "hcp CLI already installed: $HCP_VERSION"
else
    log_info "Installing hcp CLI..."

    # Use KUBECONFIG from .env.hypershift-ci (already sourced)
    if [ -z "${KUBECONFIG:-}" ] || [ ! -f "$KUBECONFIG" ]; then
        log_error "KUBECONFIG not available. Re-run setup-hypershift-ci-credentials.sh"
        exit 1
    fi

    # Detect platform
    case "$(uname -s)-$(uname -m)" in
        Darwin-arm64)  HCP_PLATFORM="Download hcp CLI for Mac for ARM 64" ;;
        Darwin-x86_64) HCP_PLATFORM="Download hcp CLI for Mac for x86_64" ;;
        Linux-x86_64)  HCP_PLATFORM="Download hcp CLI for Linux for x86_64" ;;
        Linux-aarch64) HCP_PLATFORM="Download hcp CLI for Linux for ARM 64" ;;
        *) log_error "Unsupported platform: $(uname -s)-$(uname -m)"; exit 1 ;;
    esac

    # Get download URL from consoleclidownloads
    HCP_DOWNLOAD_URL=$(oc get consoleclidownloads hcp-cli-download \
        -o jsonpath="{.spec.links[?(@.text==\"$HCP_PLATFORM\")].href}" 2>/dev/null || echo "")

    # Get bearer token for authentication
    TOKEN=$(oc whoami -t 2>/dev/null || echo "")

    if [ -z "$HCP_DOWNLOAD_URL" ]; then
        log_error "Could not find hcp CLI download URL from OpenShift console."
        echo ""
        echo "Please download manually:"
        echo "  1. Open management cluster console → ? → Command Line Tools"
        echo "  2. Click 'Download hcp CLI' for your platform"
        echo "  3. Extract: tar -xzf hcp-*.tar.gz && mv hcp ~/.local/bin/"
        echo ""
        exit 1
    fi

    log_info "Downloading from: $HCP_DOWNLOAD_URL"

    # Download with auth token and skip SSL verification (self-signed certs)
    if [ -n "$TOKEN" ]; then
        curl -fsSLk -H "Authorization: Bearer $TOKEN" "$HCP_DOWNLOAD_URL" -o /tmp/hcp-$$.tar.gz
    else
        curl -fsSLk "$HCP_DOWNLOAD_URL" -o /tmp/hcp-$$.tar.gz
    fi

    # Extract to ~/.local/bin (no sudo needed)
    tar -xzf /tmp/hcp-$$.tar.gz -C "$HOME/.local/bin" hcp
    chmod +x "$HOME/.local/bin/hcp"
    rm -f /tmp/hcp-$$.tar.gz

    log_success "hcp CLI installed to ~/.local/bin: $(hcp version 2>/dev/null | head -1)"
fi

# ============================================================================
# 3. Clone hypershift-automation repository
# ============================================================================

# Note: We use the upstream repo. No fork needed since we rely on HyperShift's
# built-in tagging (kubernetes.io/cluster/<cluster-name>=owned) for IAM scoping.
HYPERSHIFT_AUTOMATION_REPO="https://github.com/validatedpatterns-sandbox/hypershift-automation.git"
HYPERSHIFT_AUTOMATION_BRANCH="main"

log_info "Checking hypershift-automation..."

if [ -d "$HYPERSHIFT_AUTOMATION_DIR" ]; then
    log_success "hypershift-automation already exists at $HYPERSHIFT_AUTOMATION_DIR"
    cd "$HYPERSHIFT_AUTOMATION_DIR"
    log_info "Pulling latest changes..."
    git pull --rebase origin "$HYPERSHIFT_AUTOMATION_BRANCH" 2>/dev/null || log_info "Could not pull updates"
else
    log_info "Cloning hypershift-automation..."
    git clone -b "$HYPERSHIFT_AUTOMATION_BRANCH" "$HYPERSHIFT_AUTOMATION_REPO" "$HYPERSHIFT_AUTOMATION_DIR"
    log_success "Cloned to $HYPERSHIFT_AUTOMATION_DIR"
fi

# ============================================================================
# 4. Install ansible collections and Python dependencies
# ============================================================================

log_info "Installing ansible collections..."
cd "$HYPERSHIFT_AUTOMATION_DIR"

if command -v ansible-galaxy &>/dev/null; then
    ansible-galaxy collection install kubernetes.core amazon.aws community.general --force-with-deps 2>/dev/null || \
    ansible-galaxy collection install kubernetes.core amazon.aws community.general
    log_success "Ansible collections installed"
else
    log_error "ansible-galaxy not found. Install ansible first: pip install ansible-core"
    exit 1
fi

log_info "Installing Python dependencies for AWS..."
pip install --quiet boto3 botocore kubernetes openshift PyYAML
log_success "Python dependencies installed (boto3, botocore, kubernetes, openshift)"

# ============================================================================
# 5. Setup pull secret
# ============================================================================

log_info "Setting up pull secret..."

PULL_SECRET_PATH="$HOME/.pullsecret.json"
echo "$PULL_SECRET" > "$PULL_SECRET_PATH"
chmod 600 "$PULL_SECRET_PATH"
log_success "Pull secret saved to $PULL_SECRET_PATH"

# ============================================================================
# 6. Verify management cluster kubeconfig
# ============================================================================

log_info "Verifying management cluster kubeconfig..."

# KUBECONFIG is already set by sourcing .env.hypershift-ci
if [ -z "${KUBECONFIG:-}" ]; then
    log_error "KUBECONFIG not set. Re-run setup-hypershift-ci-credentials.sh"
    exit 1
fi

if [ ! -f "$KUBECONFIG" ]; then
    log_error "KUBECONFIG file not found at $KUBECONFIG. Re-run setup-hypershift-ci-credentials.sh"
    exit 1
fi

log_success "Management kubeconfig: $KUBECONFIG"

# ============================================================================
# Summary
# ============================================================================

echo ""
echo "╔════════════════════════════════════════════════════════════════╗"
echo "║                    Setup Complete                              ║"
echo "╚════════════════════════════════════════════════════════════════╝"
echo ""
echo "MANAGED_BY_TAG: ${MANAGED_BY_TAG}"
echo ""
echo "Next steps:"
echo ""
echo "  # Full test run (creates cluster → deploys → tests → keeps cluster)"
echo "  ./.github/scripts/local-setup/hypershift-full-test.sh --skip-cluster-destroy"
echo ""
echo "  # With custom cluster suffix (creates ${MANAGED_BY_TAG}-pr123)"
echo "  ./.github/scripts/local-setup/hypershift-full-test.sh pr123 --skip-cluster-destroy"
echo ""
echo "  # Destroy cluster when done"
echo "  ./.github/scripts/local-setup/hypershift-full-test.sh --include-cluster-destroy"
echo ""
echo "For all options, see: .github/scripts/local-setup/README.md"
echo ""
