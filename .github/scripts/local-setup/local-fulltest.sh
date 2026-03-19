#!/usr/bin/env bash
#
# Run Local Full Test - Unified entry point for Kind, K3s, Rancher Desktop, etc.
#
# Auto-detects the local Kubernetes runtime and runs the full Kagenti test cycle.
# Reuses the same phases as kind-full-test.sh but adapts cluster lifecycle and
# networking for the detected runtime.
#
# USAGE:
#   ./.github/scripts/local-setup/local-fulltest.sh [options]
#
# RUNTIMES:
#   Auto-detected from kubectl context, or set explicitly:
#     --runtime kind              Use Kind (creates/destroys cluster)
#     --runtime rancher-desktop   Use Rancher Desktop K3s (cluster already running)
#     --runtime k3s               Alias for rancher-desktop
#     --runtime existing          Use whatever cluster is currently active
#
# OPTIONS:
#   Include flags (whitelist mode - only run specified phases):
#     --include-cluster-create     Include cluster creation phase (Kind only)
#     --include-kagenti-install    Include Kagenti platform installation phase
#     --include-agents             Include building/deploying test agents phase
#     --include-test               Include E2E test phase
#     --include-kagenti-uninstall  Include Kagenti platform uninstall phase
#     --include-cluster-destroy    Include cluster destruction phase (Kind only)
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
#     --env ENV          Environment for Kagenti installer (auto-detected per runtime)
#     --cluster-name N   Cluster name (Kind only, default: kagenti)
#     --save-kubeconfig  Save kubeconfig to ~/clusters/local/<runtime>/auth/kubeconfig
#
# EXAMPLES:
#   # Auto-detect runtime, full run
#   ./.github/scripts/local-setup/local-fulltest.sh
#
#   # Explicit K3s runtime, skip destroy (no-op for K3s anyway)
#   ./.github/scripts/local-setup/local-fulltest.sh --runtime k3s --skip-cluster-destroy
#
#   # Kind runtime, keep cluster for debugging
#   ./.github/scripts/local-setup/local-fulltest.sh --runtime kind --skip-cluster-destroy
#
#   # Iterate on existing K3s cluster (skip create/destroy)
#   ./.github/scripts/local-setup/local-fulltest.sh --runtime k3s --skip-cluster-create
#

set -euo pipefail

# Handle Ctrl+C properly
cleanup() {
    echo ""
    echo -e "\033[0;31m✗ Interrupted! Killing child processes...\033[0m"
    pkill -P $$ 2>/dev/null || true
    sleep 1
    pkill -9 -P $$ 2>/dev/null || true
    exit 130
}
trap cleanup SIGINT SIGTERM

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="${GITHUB_WORKSPACE:-$(cd "$SCRIPT_DIR/../../.." && pwd)}"

# Parse arguments
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
SAVE_KUBECONFIG=false
KAGENTI_ENV=""  # Auto-detected if not set
CLUSTER_NAME="${CLUSTER_NAME:-kagenti}"
RUNTIME_OVERRIDE=""
WHITELIST_MODE=false

while [[ $# -gt 0 ]]; do
    case $1 in
        --runtime)
            RUNTIME_OVERRIDE="$2"
            shift 2
            ;;
        --include-cluster-create)
            INCLUDE_CREATE=true; WHITELIST_MODE=true; shift ;;
        --include-kagenti-install)
            INCLUDE_INSTALL=true; WHITELIST_MODE=true; shift ;;
        --include-agents)
            INCLUDE_AGENTS=true; WHITELIST_MODE=true; shift ;;
        --include-test)
            INCLUDE_TEST=true; WHITELIST_MODE=true; shift ;;
        --include-kagenti-uninstall)
            INCLUDE_KAGENTI_UNINSTALL=true; WHITELIST_MODE=true; shift ;;
        --include-cluster-destroy)
            INCLUDE_DESTROY=true; WHITELIST_MODE=true; shift ;;
        --skip-cluster-create)
            SKIP_CREATE=true; shift ;;
        --skip-kagenti-install)
            SKIP_INSTALL=true; shift ;;
        --skip-agents)
            SKIP_AGENTS=true; shift ;;
        --skip-test)
            SKIP_TEST=true; shift ;;
        --skip-kagenti-uninstall)
            SKIP_KAGENTI_UNINSTALL=true; shift ;;
        --skip-cluster-destroy)
            SKIP_DESTROY=true; shift ;;
        --clean-kagenti)
            CLEAN_KAGENTI=true; shift ;;
        --save-kubeconfig)
            SAVE_KUBECONFIG=true; shift ;;
        --env)
            KAGENTI_ENV="$2"; shift 2 ;;
        --cluster-name)
            CLUSTER_NAME="$2"; shift 2 ;;
        *)
            echo "Unknown option: $1"
            echo "Run with --help for usage"
            exit 1
            ;;
    esac
done

# Detect runtime
if [ -n "$RUNTIME_OVERRIDE" ]; then
    # Normalize aliases
    case "$RUNTIME_OVERRIDE" in
        k3s) K8S_RUNTIME="rancher-desktop" ;;
        rd)  K8S_RUNTIME="rancher-desktop" ;;
        *)   K8S_RUNTIME="$RUNTIME_OVERRIDE" ;;
    esac
    export K8S_RUNTIME
fi

source "$SCRIPT_DIR/../lib/runtime-detect.sh"

# Auto-detect env if not specified
if [ -z "$KAGENTI_ENV" ]; then
    case "$K8S_RUNTIME" in
        kind)             KAGENTI_ENV="dev" ;;
        rancher-desktop)  KAGENTI_ENV="k3s" ;;
        *)                KAGENTI_ENV="dev" ;;
    esac
fi

# Resolve phase settings
if [ "$WHITELIST_MODE" = "true" ]; then
    RUN_CREATE=$INCLUDE_CREATE
    RUN_INSTALL=$INCLUDE_INSTALL
    RUN_AGENTS=$INCLUDE_AGENTS
    RUN_TEST=$INCLUDE_TEST
    RUN_KAGENTI_UNINSTALL=$INCLUDE_KAGENTI_UNINSTALL
    RUN_DESTROY=$INCLUDE_DESTROY
else
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

# For non-Kind runtimes, cluster create/destroy are no-ops
case "$K8S_RUNTIME" in
    rancher-desktop|minikube|existing)
        if [ "$RUN_CREATE" = "true" ] && [ "$WHITELIST_MODE" != "true" ]; then
            RUN_CREATE=false
            echo "Note: Cluster creation skipped for $K8S_RUNTIME (cluster managed externally)"
        fi
        if [ "$RUN_DESTROY" = "true" ] && [ "$WHITELIST_MODE" != "true" ]; then
            RUN_DESTROY=false
            echo "Note: Cluster destruction skipped for $K8S_RUNTIME (cluster managed externally)"
        fi
        ;;
esac

# Colors
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
log_step() { echo -e "${GREEN}▶${NC} $1"; }
log_error() { echo -e "${RED}✗${NC} $1" >&2; }

cd "$REPO_ROOT"

echo ""
echo "Configuration:"
echo "  Runtime:        $K8S_RUNTIME"
echo "  Context:        $K8S_CONTEXT"
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
# PHASE 1: Cluster Lifecycle (runtime-specific)
# ============================================================================

if [ "$RUN_CREATE" = "true" ]; then
    log_phase "PHASE 1: Create/Verify Cluster ($K8S_RUNTIME)"

    case "$K8S_RUNTIME" in
        kind)
            log_step "Creating Kind cluster: $CLUSTER_NAME"
            CLUSTER_NAME="$CLUSTER_NAME" ./.github/scripts/kind/create-cluster.sh
            ;;
        rancher-desktop)
            log_step "Verifying Rancher Desktop K3s cluster..."
            if ! kubectl --context rancher-desktop get nodes &>/dev/null; then
                log_error "Rancher Desktop K3s cluster not running. Start Rancher Desktop first."
                exit 1
            fi
            kubectl --context rancher-desktop get nodes

            log_step "Preparing Rancher Desktop VM for Istio..."
            # Istio CNI requires /run to have shared mount propagation.
            # Without this, the install-cni container fails with:
            #   "path /var/run/netns is mounted on /run but it is not a shared or slave mount"
            rdctl shell -- sudo mount --make-shared /run 2>/dev/null || true

            # Istio CNI uses inotify watchers for config files. The default Lima VM
            # limits are too low, causing "too many open files" errors.
            rdctl shell -- sudo sysctl -w fs.inotify.max_user_instances=1024 2>/dev/null || true
            rdctl shell -- sudo sysctl -w fs.inotify.max_user_watches=524288 2>/dev/null || true

            log_step "Disabling Traefik (we use Istio Gateway instead)..."
            # Traefik conflicts with our Istio ingress gateway on port 80/443.
            # Scale it down rather than uninstalling to allow easy re-enable.
            kubectl --context rancher-desktop -n kube-system scale deploy traefik --replicas=0 2>/dev/null || true

            log_step "Configuring in-cluster registry mirror..."
            # K3s kubelet resolves image registry DNS outside CoreDNS, so it can't
            # reach registry.cr-system.svc.cluster.local. We configure a K3s registry
            # mirror that maps the cluster DNS name to the registry's ClusterIP.
            # This requires a K3s restart to take effect, but we only do it if the
            # config doesn't already exist.
            if ! rdctl shell -- test -f /etc/rancher/k3s/registries.yaml 2>/dev/null; then
                log_step "Creating K3s registries.yaml (will restart K3s after platform install)..."
                export K3S_REGISTRY_NEEDS_RESTART=true
            fi

            log_step "Cluster ready"
            ;;
        minikube)
            log_step "Starting Minikube cluster..."
            minikube start --memory=8192 --cpus=4
            ;;
        existing)
            log_step "Using existing cluster (context: $K8S_CONTEXT)"
            kubectl get nodes
            ;;
        none)
            log_error "No Kubernetes cluster detected. Start Kind, Rancher Desktop, or Minikube first."
            exit 1
            ;;
    esac
else
    log_phase "PHASE 1: Skipping Cluster Creation"
fi

# Ensure we're using the right context
if [ -n "$K8S_CONTEXT" ]; then
    kubectl config use-context "$K8S_CONTEXT" &>/dev/null || true
fi

# Save kubeconfig if requested
if [ "$SAVE_KUBECONFIG" = "true" ]; then
    KUBECONFIG_DIR="$HOME/clusters/local/$K8S_RUNTIME/auth"
    mkdir -p "$KUBECONFIG_DIR"
    kubectl config view --context "$K8S_CONTEXT" --minify --raw > "$KUBECONFIG_DIR/kubeconfig"
    log_step "Kubeconfig saved to $KUBECONFIG_DIR/kubeconfig"
fi

# ============================================================================
# PHASE 2: Install Kagenti Platform
# ============================================================================

if [ "$RUN_INSTALL" = "true" ]; then
    log_phase "PHASE 2: Install Kagenti Platform ($KAGENTI_ENV)"

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

    # K3s/Rancher Desktop with moby: configure Docker daemon to access the
    # in-cluster container registry. The Docker daemon runs on the VM host and
    # can't resolve cluster-internal DNS. We add /etc/hosts entry + insecure
    # registry config + K3s registries.yaml mirror.
    if [ "$K8S_RUNTIME" = "rancher-desktop" ]; then
        REGISTRY_IP=$(kubectl get svc -n cr-system registry -o jsonpath='{.spec.clusterIP}' 2>/dev/null || echo "")
        if [ -n "$REGISTRY_IP" ]; then
            log_step "Configuring K3s + Docker registry access (ClusterIP: $REGISTRY_IP)..."

            # 1. Add DNS entry so Docker daemon can resolve the registry hostname
            if ! rdctl shell -- grep -q "registry.cr-system.svc.cluster.local" /etc/hosts 2>/dev/null; then
                rdctl shell -- sudo sh -c "echo '${REGISTRY_IP} registry.cr-system.svc.cluster.local' >> /etc/hosts"
            fi

            # 2. Configure K3s containerd registry mirror
            rdctl shell -- sudo tee /etc/rancher/k3s/registries.yaml > /dev/null <<REGEOF
mirrors:
  "registry.cr-system.svc.cluster.local:5000":
    endpoint:
      - "http://${REGISTRY_IP}:5000"
configs:
  "registry.cr-system.svc.cluster.local:5000":
    tls:
      insecure_skip_verify: true
REGEOF

            # 3. Configure Docker daemon insecure registries
            rdctl shell -- sudo sh -c "cat > /etc/docker/daemon.json" <<DJEOF
{
  "min-api-version": "1.41",
  "features": { "containerd-snapshotter": true },
  "insecure-registries": ["registry.cr-system.svc.cluster.local:5000", "${REGISTRY_IP}:5000"]
}
DJEOF

            # 4. Restart Docker + K3s to apply all config
            log_step "Restarting Docker + K3s to apply registry config..."
            rdctl shell -- sudo rc-service docker restart 2>/dev/null || true
            sleep 3
            rdctl shell -- sudo rc-service k3s restart 2>/dev/null || true
            for i in {1..30}; do
                if kubectl get nodes &>/dev/null; then break; fi
                sleep 2
            done
            log_step "K3s + Docker restarted with registry config"
        fi
    fi

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
# PHASE 6: Cluster Cleanup (runtime-specific)
# ============================================================================

if [ "$RUN_DESTROY" = "true" ]; then
    log_phase "PHASE 6: Destroy Cluster ($K8S_RUNTIME)"

    case "$K8S_RUNTIME" in
        kind)
            CLUSTER_NAME="$CLUSTER_NAME" ./.github/scripts/kind/destroy-cluster.sh
            ;;
        rancher-desktop)
            echo -e "${YELLOW}To reset K3s: rdctl kubernetes reset${NC}"
            echo -e "${YELLOW}To re-enable Traefik: kubectl -n kube-system scale deploy traefik --replicas=1${NC}"
            ;;
        minikube)
            minikube delete
            ;;
    esac
else
    log_phase "PHASE 6: Skipping Cluster Destruction"
    echo ""
    case "$K8S_RUNTIME" in
        kind)
            echo "Cluster kept for debugging. To destroy later:"
            echo "  ./.github/scripts/kind/destroy-cluster.sh"
            ;;
        rancher-desktop)
            echo "K3s cluster managed by Rancher Desktop."
            echo "  Reset: rdctl kubernetes reset"
            echo "  Re-enable Traefik: kubectl -n kube-system scale deploy traefik --replicas=1"
            ;;
    esac
    echo ""
fi

# ============================================================================
# Show Services
# ============================================================================

log_phase "Services"
./.github/scripts/local-setup/show-services.sh || true

echo ""
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${GREEN}┃${NC} Local full test completed successfully! (runtime: $K8S_RUNTIME)"
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""
