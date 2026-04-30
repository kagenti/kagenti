#!/usr/bin/env bash
#
# OpenShell Full Test — Thin Orchestrator
#
# Deploys and tests OpenShell + Kagenti on Kind or HyperShift (OCP).
# Delegates all work to layered sub-scripts in scripts/openshell/.
#
# USAGE:
#   # Kind (default) — full run, keep cluster for debugging
#   ./.github/scripts/local-setup/openshell-full-test.sh --skip-cluster-destroy
#
#   # Kind — iterate on existing cluster (skip create)
#   ./.github/scripts/local-setup/openshell-full-test.sh --skip-cluster-create --skip-cluster-destroy
#
#   # HyperShift — create new cluster, deploy, test, keep cluster
#   source .env.kagenti-hypershift-custom
#   ./.github/scripts/local-setup/openshell-full-test.sh --platform ocp --skip-cluster-destroy ostest
#
#   # HyperShift — iterate on existing cluster
#   export KUBECONFIG=~/clusters/hcp/<cluster>/auth/kubeconfig
#   ./.github/scripts/local-setup/openshell-full-test.sh --platform ocp --skip-cluster-create --skip-cluster-destroy
#
# OPTIONS:
#   --platform kind|ocp     Platform (default: auto-detect from KUBECONFIG)
#   --skip-cluster-create   Reuse existing cluster
#   --skip-cluster-destroy  Keep cluster after test
#   --skip-install          Skip Kagenti platform installation
#   --skip-images           Skip image builds (Phase 3)
#   --skip-agents           Skip agent deployment within tenants
#   --skip-test             Skip E2E test phase
#   --cluster-name NAME     Kind cluster name (default: kagenti)
#   [positional]            HyperShift cluster suffix (e.g., "ostest")
#

set -euo pipefail

cleanup() {
    echo ""
    echo -e "\033[0;31mInterrupted — killing child processes...\033[0m"
    pkill -P $$ 2>/dev/null || true
    sleep 1
    pkill -9 -P $$ 2>/dev/null || true
    exit 130
}
trap cleanup SIGINT SIGTERM

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="${GITHUB_WORKSPACE:-$(cd "$SCRIPT_DIR/../../.." && pwd)}"

# ── Defaults ──────────────────────────────────────────────────────
KAGENTI_ENV="openshell"
PLATFORM=""
CLUSTER_NAME="${CLUSTER_NAME:-kagenti}"
CLUSTER_SUFFIX=""
SKIP_CREATE=false
SKIP_DESTROY=false
SKIP_TEST=false
SKIP_AGENTS=false
SKIP_INSTALL=false
SKIP_IMAGES=false

# ── Parse arguments ──────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
    case $1 in
        --platform)             PLATFORM="$2"; shift 2 ;;
        --skip-cluster-create)  SKIP_CREATE=true;  shift ;;
        --skip-cluster-destroy) SKIP_DESTROY=true; shift ;;
        --skip-test)            SKIP_TEST=true;    shift ;;
        --skip-agents)          SKIP_AGENTS=true;  shift ;;
        --skip-install)         SKIP_INSTALL=true; shift ;;
        --skip-images)          SKIP_IMAGES=true;  shift ;;
        --cluster-name)         CLUSTER_NAME="$2"; shift 2 ;;
        -*)
            echo "Unknown option: $1" >&2
            exit 1
            ;;
        *)
            CLUSTER_SUFFIX="$1"; shift ;;
    esac
done

# ── Colors / logging ────────────────────────────────────────────
GREEN='\033[0;32m'
BLUE='\033[0;34m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m'

log_phase() {
    echo -e "\n${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${BLUE}┃${NC} $1"
    echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}\n"
}
log_step()  { echo -e "${GREEN}>>>${NC} $1"; }
log_warn()  { echo -e "${YELLOW}⚠${NC}  $1"; }
log_error() { echo -e "${RED}ERROR:${NC} $1" >&2; }

cd "$REPO_ROOT"

# ── Ensure Helm v3 ──────────────────────────────────────────────
if command -v helm >/dev/null 2>&1; then
    HELM_VERSION=$(helm version --short 2>/dev/null | grep -oE '^v[0-9]+' || echo "unknown")
    if [[ "$HELM_VERSION" == "v4" ]]; then
        if [ -x "/opt/homebrew/opt/helm@3/bin/helm" ]; then
            export PATH="/opt/homebrew/opt/helm@3/bin:$PATH"
            log_step "Helm v4 detected — prepending Helm v3 from brew to PATH"
        else
            log_error "Helm v4 detected but Helm v3 not found. Install: brew install helm@3"
            exit 1
        fi
    fi
fi

# ── Auto-detect platform ────────────────────────────────────────
if [ -z "$PLATFORM" ]; then
    if kubectl api-resources 2>/dev/null | grep -q "routes.route.openshift.io"; then
        PLATFORM="ocp"
    else
        PLATFORM="kind"
    fi
fi
export PLATFORM

# ── HyperShift-specific setup ───────────────────────────────────
MANAGED_BY_TAG="${MANAGED_BY_TAG:-kagenti-hypershift-custom}"

if [ "$PLATFORM" = "ocp" ]; then
    if [ -z "$CLUSTER_SUFFIX" ]; then
        CLUSTER_SUFFIX="os$(echo "$USER" | cut -c1-3)$(date +%d)"
    fi
    HCP_CLUSTER_NAME="${MANAGED_BY_TAG}-${CLUSTER_SUFFIX}"
    HOSTED_KUBECONFIG="$HOME/clusters/hcp/$HCP_CLUSTER_NAME/auth/kubeconfig"

    if [ -z "${AWS_ACCESS_KEY_ID:-}" ] && [ "$SKIP_CREATE" = "false" ]; then
        ENV_FILE="$REPO_ROOT/.env.${MANAGED_BY_TAG}"
        if [ -f "$ENV_FILE" ]; then
            # shellcheck source=/dev/null
            source "$ENV_FILE"
            log_step "Loaded credentials from $(basename "$ENV_FILE")"
        else
            log_error "No .env file found at $ENV_FILE"
            exit 1
        fi
    fi
fi

# ── Source LLM credentials (.env.maas) ──────────────────────────
MAAS_SOURCED=false
GIT_MAIN_WORKTREE="$(git rev-parse --path-format=absolute --git-common-dir 2>/dev/null | sed 's|/\.git$||' || echo "")"
for candidate in "$REPO_ROOT/.env.maas" "$PWD/.env.maas" "$GIT_MAIN_WORKTREE/.env.maas"; do
    if [ -n "$candidate" ] && [ -f "$candidate" ]; then
        # shellcheck source=/dev/null
        source "$candidate"
        MAAS_SOURCED=true
        log_step "Loaded LiteMaaS credentials from $(basename "$candidate")"
        break
    fi
done
export MAAS_SOURCED

# ── Summary ─────────────────────────────────────────────────────
echo ""
echo "OpenShell Full Test"
echo "  Platform:  $PLATFORM"
if [ "$PLATFORM" = "ocp" ]; then
    echo "  Cluster:   $HCP_CLUSTER_NAME"
else
    echo "  Cluster:   $CLUSTER_NAME (Kind)"
fi
echo "  Env:       $KAGENTI_ENV"
echo "  Helm:      $(helm version --short 2>/dev/null)"
echo "  LLM:       $([ "$MAAS_SOURCED" = "true" ] && echo "available" || echo "none")"
echo "  Phases:"
echo "    1. cluster-create:  $([ "$SKIP_CREATE"  = "true" ] && echo SKIP || echo RUN)"
echo "    2. kagenti-install: $([ "$SKIP_INSTALL" = "true" ] && echo SKIP || echo RUN)"
echo "    3. build-images:    $([ "$SKIP_IMAGES"  = "true" ] && echo SKIP || echo RUN)"
echo "    4. deploy-shared:   RUN"
echo "    5. deploy-tenants:  RUN (agents: $([ "$SKIP_AGENTS" = "true" ] && echo SKIP || echo RUN))"
echo "    6. test:            $([ "$SKIP_TEST"    = "true" ] && echo SKIP || echo RUN)"
echo "    7. cluster-destroy: $([ "$SKIP_DESTROY" = "true" ] && echo SKIP || echo RUN)"
echo ""

# ── Ensure boto3 for Ansible AWS modules (HyperShift cluster lifecycle) ──
if [ "$PLATFORM" = "ocp" ]; then
    pip install boto3 botocore 2>/dev/null || true
fi

# ============================================================================
# PHASE 1: Create Cluster
# ============================================================================
if [ "$SKIP_CREATE" = "false" ]; then
    if [ "$PLATFORM" = "kind" ]; then
        log_phase "PHASE 1: Create Kind Cluster"
        CLUSTER_NAME="$CLUSTER_NAME" ./.github/scripts/kind/create-cluster.sh
    else
        log_phase "PHASE 1: Create HyperShift Cluster"
        export KUBECONFIG="${MGMT_KUBECONFIG:-$HOME/.kube/kagenti-team-mgmt.kubeconfig}"
        ./.github/scripts/hypershift/create-cluster.sh "$CLUSTER_SUFFIX"
        export KUBECONFIG="$HOSTED_KUBECONFIG"
        log_step "Switched to hosted cluster: $KUBECONFIG"
    fi
else
    log_phase "PHASE 1: Skipping Cluster Creation"
    if [ "$PLATFORM" = "ocp" ] && [ -f "${HOSTED_KUBECONFIG:-}" ]; then
        export KUBECONFIG="$HOSTED_KUBECONFIG"
        log_step "Using existing hosted cluster: $KUBECONFIG"
    fi
fi

# ============================================================================
# PHASE 2: Install Kagenti Platform
# ============================================================================
if [ "$SKIP_INSTALL" = "false" ]; then
    log_phase "PHASE 2: Install Kagenti Platform (OpenShell profile)"

    if [ "$PLATFORM" = "ocp" ]; then
        log_step "Running Helm-based OCP installer..."
        "$REPO_ROOT/scripts/ocp/setup-kagenti.sh" \
            --kagenti-repo "$REPO_ROOT" \
            --skip-ui \
            --skip-mlflow \
            --skip-mcp-gateway \
            --skip-ovn-patch
    else
        ./.github/scripts/common/20-create-secrets.sh
        ./.github/scripts/kagenti-operator/30-run-installer.sh --env "$KAGENTI_ENV"
        ./.github/scripts/common/40-wait-platform-ready.sh
        ./.github/scripts/common/70-configure-dockerhost.sh
    fi

    log_step "Waiting for Kagenti Operator CRDs..."
    kubectl wait --for=condition=established crd/agentruntimes.agent.kagenti.dev --timeout=120s 2>/dev/null || {
        log_warn "AgentRuntime CRD not found — continuing."
    }
else
    log_phase "PHASE 2: Skipping Kagenti Installation"
fi

# ============================================================================
# PHASE 3: Build Images
# ============================================================================
if [ "$SKIP_IMAGES" = "false" ]; then
    log_phase "PHASE 3: Build Images"

    BUILD_ARGS=()
    if [ "$PLATFORM" = "kind" ]; then
        BUILD_ARGS+=(--kind "$CLUSTER_NAME")
    fi
    # Use prebuilt images when source repos are not available (e.g., CI)
    REPOS_DIR="${OPENSHELL_REPOS_DIR:-$REPO_ROOT/../}"
    if [ ! -d "$REPOS_DIR/OpenShell" ]; then
        BUILD_ARGS+=(--prebuilt)
        log_step "Source repos not found — using prebuilt images from ghcr.io"
    fi
    BUILD_ARGS+=(--agents)

    scripts/openshell/build-images.sh "${BUILD_ARGS[@]}"
else
    log_phase "PHASE 3: Skipping Image Builds"
fi

# ============================================================================
# PHASE 4: Deploy Shared Infrastructure
# ============================================================================
log_phase "PHASE 4: Deploy Shared Infrastructure"

SHARED_ARGS=()
if [ "$PLATFORM" = "kind" ]; then
    SHARED_ARGS+=(--pre-pull --kind-cluster "$CLUSTER_NAME")
fi
if [ "$MAAS_SOURCED" = "true" ]; then
    SHARED_ARGS+=(--litellm)
fi

scripts/openshell/deploy-shared.sh "${SHARED_ARGS[@]}"

# ============================================================================
# PHASE 5: Deploy Tenants
# ============================================================================
log_phase "PHASE 5: Deploy Tenants"

TENANT_ARGS=()
if [ "$SKIP_AGENTS" = "false" ]; then
    TENANT_ARGS+=(--agents)
fi

for tenant in team1 team2; do
    log_step "Deploying tenant: $tenant"
    scripts/openshell/deploy-tenant.sh "$tenant" "${TENANT_ARGS[@]}"
done

# ============================================================================
# PHASE 6: Run E2E Tests
# ============================================================================
if [ "$SKIP_TEST" = "false" ]; then
    log_phase "PHASE 6: Run E2E Tests"

    ./.github/scripts/common/80-install-test-deps.sh 2>/dev/null || true
    ./.github/scripts/common/87-setup-test-credentials.sh 2>/dev/null || true

    export KAGENTI_CONFIG_FILE="deployments/envs/dev_values_openshell.yaml"

    if [ "$MAAS_SOURCED" = "true" ]; then
        export OPENSHELL_LLM_AVAILABLE=true
    fi

    TEST_DIR="kagenti/tests/e2e/openshell"
    if [ -d "$TEST_DIR" ]; then
        log_step "Running OpenShell E2E tests..."
        uv run pytest "$TEST_DIR" -v --timeout=300
    else
        log_warn "No tests at $TEST_DIR — skipping."
    fi
else
    log_phase "PHASE 6: Skipping E2E Tests"
fi

# ============================================================================
# PHASE 7: Destroy Cluster
# ============================================================================
if [ "$SKIP_DESTROY" = "false" ]; then
    if [ "$PLATFORM" = "kind" ]; then
        log_phase "PHASE 7: Destroy Kind Cluster"
        CLUSTER_NAME="$CLUSTER_NAME" ./.github/scripts/kind/destroy-cluster.sh
    else
        log_phase "PHASE 7: Destroy HyperShift Cluster"
        export KUBECONFIG="${MGMT_KUBECONFIG:-$HOME/.kube/kagenti-team-mgmt.kubeconfig}"
        ./.github/scripts/hypershift/destroy-cluster.sh "$CLUSTER_SUFFIX"
    fi
else
    log_phase "PHASE 7: Skipping Cluster Destruction"
    echo ""
    if [ "$PLATFORM" = "kind" ]; then
        echo "  Cluster kept. To destroy: kind delete cluster --name $CLUSTER_NAME"
    else
        echo "  Cluster kept. To destroy: ./.github/scripts/hypershift/destroy-cluster.sh $CLUSTER_SUFFIX"
        echo "  KUBECONFIG: $HOSTED_KUBECONFIG"
    fi
    echo ""
fi

echo ""
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${GREEN}┃${NC} OpenShell full test completed! (platform: $PLATFORM)"
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""
