#!/usr/bin/env bash
# ============================================================================
# KAGENTI PLATFORM SETUP FOR KIND
# ============================================================================
# Installs the Kagenti stack on a local Kind cluster. Composable: core
# components are always installed, optional layers enabled via --with-* flags.
#
# Core (always):   cert-manager, Gateway API CRDs, Istio Gateway controller
#                  (istio-base + istiod), Keycloak, kagenti-operator, kagenti-webhook
# Optional:        --with-istio (ambient mesh), --with-spire, --with-backend,
#                  --with-ui, --with-mcp-gateway, --with-kuadrant, --with-otel,
#                  --with-mlflow, --with-builds, --with-kiali,
#                  --with-agent-sandbox, --with-skills, --with-all
#
# Idempotent: safe to re-run. Uses helm upgrade --install and kubectl apply.
# Re-running with additional --with-* flags adds components incrementally.
#
# Usage:
#   scripts/kind/setup-kagenti.sh                          # Core only
#   scripts/kind/setup-kagenti.sh --with-all               # Everything
#   scripts/kind/setup-kagenti.sh --with-istio --with-ui   # Core + Istio + UI
#   scripts/kind/setup-kagenti.sh --with-all --skip-mlflow --skip-kuadrant  # Lightweight
#   scripts/kind/setup-kagenti.sh --skip-cluster           # Reuse existing cluster
#   scripts/kind/setup-kagenti.sh --cluster-name my-test   # Custom cluster name
#
# Prerequisites: kind, helm (v3), kubectl
# ============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

# ── Defaults ─────────────────────────────────────────────────────────────────
CLUSTER_NAME="${CLUSTER_NAME:-kagenti}"
KIND_CONFIG="${KIND_CONFIG:-$REPO_ROOT/scripts/kind/kind-config-registry.yaml}"
DOMAIN="localtest.me"

# Component flags (core is always true)
WITH_ISTIO=false
WITH_SPIRE=false
WITH_BACKEND=false
WITH_UI=false
WITH_MCP_GATEWAY=false
WITH_OTEL=false
WITH_MLFLOW=false
WITH_BUILDS=false
WITH_KIALI=false
WITH_KUADRANT=false
WITH_AGENT_SANDBOX=false
WITH_SKILLS=false
SKILL_REGISTRY_ALLOWED_HOSTS=""
WITH_ALL=false
SKIP_CLUSTER=false
SKIP_MLFLOW=false
SKIP_KUADRANT=false
BUILD_IMAGES=false
PRELOAD_IMAGES=false
INSTALL_EXAMPLES=false
DRY_RUN=false
SECRETS_FILE_ARG=""
CONTAINER_ENGINE="${CONTAINER_ENGINE:-docker}"

# Versions
CERT_MANAGER_VERSION="v1.17.2"
ISTIO_VERSION="1.28.0"
SPIRE_CRD_VERSION="0.5.0"
SPIRE_VERSION="0.27.0"
GATEWAY_API_VERSION="v1.4.0"
TEKTON_VERSION="v0.66.0"
SHIPWRIGHT_VERSION="v0.14.0"
MCP_GATEWAY_VERSION="0.6.0"
KUADRANT_VERSION="1.4.2"
AGENT_SANDBOX_VERSION="v0.4.6"

# Recommended container-runtime resources for a full (--with-all) install.
# Keep in sync with the `podman machine init` command in docs/install.md.
RECOMMENDED_MEMORY_MB=18432   # 18 GB
RECOMMENDED_CPUS=6

KAGENTI_DEPS_VALUES_FILES=()
KAGENTI_VALUES_FILES=()

# ── Colors & logging ────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'; NC='\033[0m'
log_info()    { echo -e "${BLUE}→${NC} $1"; }
log_success() { echo -e "${GREEN}✓${NC} $1"; }
log_warn()    { echo -e "${YELLOW}⚠${NC} $1"; }
log_error()   { echo -e "${RED}✗${NC} $1"; }

run_cmd() {
  if $DRY_RUN; then echo "  [dry-run] $*"; else "$@"; fi
}

# Pre-flight check for Podman-backed Kind clusters (chiefly macOS).
#
# Two problems this catches early, before the opaque downstream failure:
#   1. Rootless Podman — Kind's rootless provider needs the systemd property
#      `Delegate=yes`, which a fresh `podman machine init` does NOT configure,
#      so `kind create cluster` aborts. We hard-fail here (unless --skip-cluster)
#      with the exact `--rootful` remedy instead of letting Kind fail cryptically.
#   2. Under-resourced machine — a full `--with-all` install needs ample
#      memory/CPU; warn (never fail) when below the recommended thresholds.
#
# Only runs when the container engine is Podman. Read-only (inspect only), so it
# is safe in --dry-run; the rootless case warns instead of exiting under dry-run.
_check_podman() {
  # Detect Podman whether CONTAINER_ENGINE=podman or a docker->podman alias.
  case "$($CONTAINER_ENGINE --version 2>/dev/null)" in
    *podman*|*Podman*) ;;
    *) return 0 ;;
  esac

  if ! command -v python3 &>/dev/null; then
    log_warn "python3 not found; skipping Podman rootful/resource pre-flight checks"
    return 0
  fi

  local inspect
  if ! inspect="$(podman machine inspect 2>/dev/null)" || [ -z "$inspect" ]; then
    log_warn "Could not inspect Podman machine; skipping rootful/resource checks"
    return 0
  fi

  # Emit: "<rootful> <memoryMB> <cpus>" (rootful = true/false). Empty on parse error.
  local parsed rootful mem cpus
  parsed="$(printf '%s' "$inspect" | python3 -c '
import sys, json
try:
    d = json.load(sys.stdin)
    m = d[0] if isinstance(d, list) else d
    r = m.get("Rootful", False)
    res = m.get("Resources", {}) or {}
    print(str(bool(r)).lower(), res.get("Memory", 0), res.get("CPUs", 0))
except Exception:
    pass
' 2>/dev/null)"

  if [ -z "$parsed" ]; then
    log_warn "Could not parse Podman machine info; skipping rootful/resource checks"
    return 0
  fi
  read -r rootful mem cpus <<<"$parsed"

  # ── Rootful check ──────────────────────────────────────────────────────────
  if [ "$rootful" != "true" ]; then
    if $SKIP_CLUSTER; then
      log_warn "Podman machine is running rootless. Kind needs rootful mode (rootless requires systemd Delegate=yes)."
      log_warn "  Reusing an existing cluster, so continuing — but new Kind clusters will fail under rootless."
    else
      log_error "Podman machine is running rootless — Kind cannot create a cluster (its rootless"
      log_error "  provider requires the systemd property \"Delegate=yes\"). Switch to rootful:"
      log_error ""
      log_error "    podman machine stop"
      log_error "    podman machine set --rootful"
      log_error "    podman machine start"
      log_error ""
      log_error "  Or recreate it: podman machine rm -f && \\"
      log_error "    podman machine init --rootful --memory $RECOMMENDED_MEMORY_MB --cpus $RECOMMENDED_CPUS && podman machine start"
      log_error "  (Note: rootful and rootless use separate image storage; preloaded images re-pull.)"
      if $DRY_RUN; then
        log_warn "[dry-run] would exit here due to rootless Podman"
      else
        exit 1
      fi
    fi
  else
    log_success "Podman machine is rootful"
  fi

  # ── Resource check (only for the heaviest profile: --with-all) ──────────────
  if $WITH_ALL; then
    local low=false
    if [ "${mem:-0}" -lt "$RECOMMENDED_MEMORY_MB" ] 2>/dev/null; then low=true; fi
    if [ "${cpus:-0}" -lt "$RECOMMENDED_CPUS" ] 2>/dev/null; then low=true; fi
    if $low; then
      log_warn "Podman machine resources are below the recommended values for --with-all:"
      log_warn "  detected: ${mem} MB / ${cpus} CPUs   recommended: ${RECOMMENDED_MEMORY_MB} MB / ${RECOMMENDED_CPUS} CPUs"
      log_warn "  Increase with: podman machine stop && \\"
      log_warn "    podman machine set --memory $RECOMMENDED_MEMORY_MB --cpus $RECOMMENDED_CPUS && podman machine start"
      log_warn "  The install may be slow or unstable with fewer resources."
    else
      log_success "Podman machine resources OK (${mem} MB / ${cpus} CPUs)"
    fi
  fi
}

# ── Shared dependency installers (Tekton, Shipwright, build strategies) ─────
# Sourced after log_*/run_cmd are defined; the lib reads DRY_RUN from this
# scope and uses the helpers above.
. "$REPO_ROOT/scripts/lib/install-deps.sh"

# Load a single image into the Kind node via docker save piped to ctr import.
# Avoids 'kind load docker-image' failures (e.g. "failed to detect containerd
# snapshotter") on WSL2 and Rancher Desktop.
load_image_into_kind() {
  local img="$1"
  $CONTAINER_ENGINE save "$img" | \
    $CONTAINER_ENGINE exec -i "${CLUSTER_NAME}-control-plane" \
      ctr --namespace=k8s.io images import -
}

# ── Argument parsing ────────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
  case "$1" in
    --with-istio)       WITH_ISTIO=true; shift ;;
    --with-spire)       WITH_SPIRE=true; shift ;;
    --with-backend)     WITH_BACKEND=true; shift ;;
    --with-ui)          WITH_UI=true; shift ;;
    --with-mcp-gateway) WITH_MCP_GATEWAY=true; shift ;;
    --with-kuadrant)    WITH_KUADRANT=true; shift ;;
    --with-otel)        WITH_OTEL=true; shift ;;
    --with-mlflow)      WITH_MLFLOW=true; shift ;;
    --with-builds)      WITH_BUILDS=true; shift ;;
    --with-kiali)       WITH_KIALI=true; shift ;;
    --with-agent-sandbox) WITH_AGENT_SANDBOX=true; shift ;;
    --with-skills)      WITH_SKILLS=true; shift ;;
    --skill-registry-allowed-hosts) SKILL_REGISTRY_ALLOWED_HOSTS="$2"; shift 2 ;;
    --with-all)         WITH_ALL=true; shift ;;
    --skip-cluster)     SKIP_CLUSTER=true; shift ;;
    --skip-mlflow)      SKIP_MLFLOW=true; shift ;;
    --skip-kuadrant)    SKIP_KUADRANT=true; shift ;;
    --build-images)     BUILD_IMAGES=true; shift ;;
    --preload-images)   PRELOAD_IMAGES=true; shift ;;
    --secrets-file)     SECRETS_FILE_ARG="$2"; shift 2 ;;
    --cluster-name)     CLUSTER_NAME="$2"; shift 2 ;;
    --domain)           DOMAIN="$2"; shift 2 ;;
    --kagenti-values)   KAGENTI_VALUES_FILES+=("--values" "$2"); shift 2 ;;
    --kagenti-deps-values) KAGENTI_DEPS_VALUES_FILES+=("--values" "$2"); shift 2 ;;
    --with-examples)    INSTALL_EXAMPLES=true; shift ;;
    --dry-run)          DRY_RUN=true; shift ;;
    -h|--help)
      echo "Usage: $0 [OPTIONS]"
      echo ""
      echo "Component flags:"
      echo "  --with-istio        Enable full Istio ambient mesh (mTLS, waypoints)"
      echo "                      Gateway API controller is always installed as core"
      echo "  --with-spire        Install SPIRE + SPIFFE IdP setup"
      echo "  --with-backend      Install Kagenti backend API"
      echo "  --with-ui           Install Kagenti UI (auto-enables backend)"
      echo "  --with-mcp-gateway  Install MCP Gateway"
      echo "  --with-kuadrant     Install Kuadrant operator (auto-enables MCP Gateway)"
      echo "  --with-otel         Install OpenTelemetry collector"
      echo "  --with-mlflow       Install MLflow trace backend (auto-enables OTel)"
      echo "  --with-builds       Install Tekton + Shipwright"
      echo "  --with-kiali        Install Kiali + Prometheus (auto-enables Istio)"
      echo "  --with-agent-sandbox Install agent-sandbox controller (kubernetes-sigs)"
      echo "  --with-skills       Enable skills and external skill registries"
      echo "                      (enables featureFlags.skills and featureFlags.externalSkills;"
      echo "                      deploys an in-cluster skillberry-store and auto-enables"
      echo "                      autosync against it; auto-enables --with-backend and --with-ui)."
      echo "                      Override the store image with the SKILLBERRY_STORE_IMAGE /"
      echo "                      SKILLBERRY_STORE_TAG env vars (default tag 0.2.0)."
      echo "  --skill-registry-allowed-hosts HOSTS"
      echo "                      Comma-separated hosts/IPs/CIDRs allowed past the registry-URL"
      echo "                      SSRF block (e.g. \"192.168.50.16\" or \"192.168.0.0/16\")."
      echo "                      Needed only for EXTERNAL skill registries on private IPs;"
      echo "                      the in-cluster store needs no allow-listing."
      echo "  --with-all          Enable all optional components"
      echo ""
      echo "Skip flags (override --with-all for resource-constrained environments):"
      echo "  --skip-mlflow       Exclude MLflow even when --with-all is used (~2 GB saved)"
      echo "  --skip-kuadrant     Exclude Kuadrant even when --with-all is used (~1 GB saved)"
      echo ""
      echo "Other options:"
      echo "  --skip-cluster      Don't create Kind cluster (reuse existing)"
      echo "  --build-images      Build platform images from source and load into Kind"
      echo "                      (backend, ui-v2, agent-oauth-secret, mlflow-oauth-secret)"
      echo "  --preload-images    Pre-pull third-party images and load into Kind for"
      echo "                      faster pod startup (reads scripts/kind/preload-images.txt)"
      echo "  --secrets-file FILE YAML file with secrets (keys: githubUser, githubToken,"
      echo "                      openaiApiKey, slackBotToken, etc.)"
      echo "  --cluster-name NAME Kind cluster name (default: kagenti)"
      echo "  --domain DOMAIN     Domain for services (default: localtest.me)"
      echo "  --kagenti-values FILE"
      echo "                      Helm override file to apply to Kagenti chart"
      echo "  --kagenti-deps-values FILE"
      echo "                      Helm override file to apply to Kagenti-deps chart"
      echo "  --with-examples     Install weather agent and weather tool examples"
      echo "  --dry-run           Show commands without executing"
      echo "  -h, --help          Show this help"
      exit 0 ;;
    *) log_error "Unknown option: $1"; exit 1 ;;
  esac
done

# ── Expand --with-all (deferred so --skip-* flags are order-independent) ───
if $WITH_ALL; then
  WITH_ISTIO=true; WITH_SPIRE=true; WITH_BACKEND=true; WITH_UI=true
  WITH_MCP_GATEWAY=true; WITH_OTEL=true; WITH_BUILDS=true; WITH_KIALI=true
  WITH_AGENT_SANDBOX=true
  $SKIP_MLFLOW    || WITH_MLFLOW=true
  $SKIP_KUADRANT  || WITH_KUADRANT=true
  # Note that INSTALL_EXAMPLES isn't part of --with-all; it is not part of Kagenti
  # but exists for demos and tests.
fi

# ── Flag dependencies ──────────────────────────────────────────────────────
# UI requires backend API
if $WITH_UI && ! $WITH_BACKEND; then
  WITH_BACKEND=true
fi
# Skills requires UI (and transitively backend)
if $WITH_SKILLS && ! $WITH_UI; then
  WITH_UI=true
fi
# Kiali requires full ambient mesh for service mesh telemetry
if $WITH_KIALI && ! $WITH_ISTIO; then
  WITH_ISTIO=true
fi
# MLflow waypoint requires full ambient mesh (gatewayClassName: istio-waypoint)
if $WITH_MLFLOW && ! $WITH_ISTIO; then
  WITH_ISTIO=true
fi
# MLflow requires OTel collector to export traces
if $WITH_MLFLOW && ! $WITH_OTEL; then
  WITH_OTEL=true
fi
# Kuadrant provides AuthPolicy for MCP Gateway
if $WITH_KUADRANT && ! $WITH_MCP_GATEWAY; then
  WITH_MCP_GATEWAY=true
fi

# ── Pre-flight ──────────────────────────────────────────────────────────────
START_SECONDS=$SECONDS

echo ""
echo "============================================"
case "${KAGENTI_SETUP_FLAVOR:-kind}" in
  k8s) echo "  Kagenti Platform Setup (Kubernetes)" ;;
  *)   echo "  Kagenti Platform Setup (Kind)" ;;
esac
echo "============================================"
echo ""
echo "  Cluster:       $CLUSTER_NAME"
echo "  Domain:        $DOMAIN"
echo "  Components:"
echo "    Core:          cert-manager, Gateway API, Istio GW controller, Keycloak, operator, webhook"
echo "    Istio ambient: $WITH_ISTIO"
echo "    SPIRE:         $WITH_SPIRE"
echo "    Backend API:   $WITH_BACKEND"
echo "    UI:            $WITH_UI"
echo "    MCP Gateway:   $WITH_MCP_GATEWAY"
echo "    Kuadrant:      $WITH_KUADRANT"
echo "    OTel:          $WITH_OTEL"
echo "    MLflow:        $WITH_MLFLOW"
echo "    Builds:        $WITH_BUILDS"
echo "    Kiali:         $WITH_KIALI"
echo "    Agent Sandbox: $WITH_AGENT_SANDBOX"
echo "    Skills:        $WITH_SKILLS"
echo "    Skill reg allow: ${SKILL_REGISTRY_ALLOWED_HOSTS:-<none>}"
echo "    Skip cluster:  $SKIP_CLUSTER"
echo "    Build images:  $BUILD_IMAGES"
echo "    Preload imgs:  $PRELOAD_IMAGES"
echo "    Examples:      $INSTALL_EXAMPLES"
echo "    Kagenti helm --values overrides: ${KAGENTI_VALUES_FILES[*]:-}"
echo "    Kagenti-deps helm --values overrides: ${KAGENTI_DEPS_VALUES_FILES[*]:-}"
echo ""

for cmd in helm kubectl; do
  if ! command -v "$cmd" &>/dev/null; then
    log_error "$cmd not found in PATH"
    exit 1
  fi
done
log_success "helm found: $(helm version --short 2>/dev/null || echo unknown)"
log_success "kubectl found"

if ! $SKIP_CLUSTER; then
  if ! command -v kind &>/dev/null; then
    log_error "kind not found in PATH (use --skip-cluster to reuse existing cluster)"
    exit 1
  fi
  log_success "kind found"
fi

# Podman-specific pre-flight (rootful + resource checks); no-op for Docker.
_check_podman

# Validate chart directories exist
if [ ! -d "$REPO_ROOT/charts/kagenti-deps" ] || [ ! -d "$REPO_ROOT/charts/kagenti" ]; then
  log_error "Charts not found. Run this script from the kagenti repo root."
  exit 1
fi
echo ""

# ── Helpers ─────────────────────────────────────────────────────────────────
_wait_deployment_ready() {
  local deploy="$1" ns="$2" label="${3:-$1}" timeout="${4:-300s}"
  if $DRY_RUN; then return; fi
  if ! kubectl get deployment/"$deploy" -n "$ns" &>/dev/null; then
    log_info "Waiting for $label to appear..."
    local tries=0
    until kubectl get deployment/"$deploy" -n "$ns" &>/dev/null; do
      [ $((++tries)) -ge 60 ] && { log_warn "$label not found after 5m"; return 1; }
      sleep 5
    done
  fi
  log_info "Waiting for $label rollout..."
  kubectl rollout status deployment/"$deploy" -n "$ns" --timeout="$timeout" || \
    log_warn "$label rollout not ready within timeout"
}

_wait_crds_established() {
  # kubectl wait --for=condition=Established can fail with a nil accessor error
  # if .status.conditions hasn't been populated yet on a freshly-applied CRD.
  # Retry the wait to handle this race condition.
  local timeout="${1:-60s}"; shift
  local attempts=0 max_attempts=5
  while true; do
    if kubectl wait --for=condition=Established crd "$@" --timeout="$timeout" 2>/dev/null; then
      return 0
    fi
    if [ $((++attempts)) -ge $max_attempts ]; then
      # Last attempt: let stderr through for diagnostics
      kubectl wait --for=condition=Established crd "$@" --timeout="$timeout"
      return $?
    fi
    sleep 2
  done
}

# ============================================================================
# Step 1: Create Kind Cluster
# ============================================================================
log_info "Step 1: Kind Cluster"

if $SKIP_CLUSTER; then
  log_info "Skipped (--skip-cluster)"
  if ! kubectl cluster-info &>/dev/null; then
    log_error "Cannot connect to cluster. Set KUBECONFIG or create a cluster first."
    exit 1
  fi
else
  if kind get clusters 2>/dev/null | grep -q "^${CLUSTER_NAME}$"; then
    log_success "Cluster '$CLUSTER_NAME' already exists — reusing"
  else
    log_info "Creating Kind cluster '$CLUSTER_NAME'..."
    run_cmd kind create cluster --name "$CLUSTER_NAME" --config "$KIND_CONFIG"
    log_success "Cluster created"
  fi
fi

kubectl cluster-info --context "kind-${CLUSTER_NAME}" &>/dev/null || true
echo ""

# ============================================================================
# Step 1b: Preload images (--preload-images)
# ============================================================================
PRELOAD_LOAD_PID=""
if $PRELOAD_IMAGES && ! $DRY_RUN; then
  PRELOAD_FILE="$SCRIPT_DIR/preload-images.txt"
  if [ ! -f "$PRELOAD_FILE" ]; then
    log_error "Preload images file not found: $PRELOAD_FILE"
    exit 1
  fi

  PRELOAD_LIST=()
  while IFS= read -r line; do
    PRELOAD_LIST+=("$line")
  done < <(grep -v '^[[:space:]]*#' "$PRELOAD_FILE" | grep -v '^[[:space:]]*$')
  if [ ${#PRELOAD_LIST[@]} -eq 0 ]; then
    log_warn "Preload images file is empty — skipping"
  else
    log_info "Pulling ${#PRELOAD_LIST[@]} images for preload..."

    if [ "$CONTAINER_ENGINE" = "podman" ]; then
      for img in "${PRELOAD_LIST[@]}"; do
        $CONTAINER_ENGINE pull "$img" 2>&1 | grep -E "^(Status:|Error|Trying to pull)" || true
      done
    else
      PULL_PIDS=""
      for img in "${PRELOAD_LIST[@]}"; do
        ($CONTAINER_ENGINE pull "$img" >/dev/null 2>&1) &
        PULL_PIDS="$PULL_PIDS $!"
      done
      PULL_FAIL=0
      for pid in $PULL_PIDS; do
        wait "$pid" || PULL_FAIL=1
      done
      if [ $PULL_FAIL -ne 0 ]; then
        log_warn "Some images failed to pull — continuing (pods will pull on demand)"
      fi
    fi
    log_success "Image pull complete"

    # Load into Kind node asynchronously using a single batched tar
    # (docker save + ctr import — avoids 'kind load docker-image' issues on
    # Rancher Desktop VZ and reduces IPC round-trips vs per-image loading)
    log_info "Loading ${#PRELOAD_LIST[@]} images into Kind node (background)..."
    (
      tmp=$(mktemp /tmp/kind-preload-XXXXXX.tar)
      trap 'rm -f "$tmp"' EXIT
      if $CONTAINER_ENGINE save "${PRELOAD_LIST[@]}" -o "$tmp" 2>/dev/null && \
         $CONTAINER_ENGINE cp "$tmp" "${CLUSTER_NAME}-control-plane:/preload-images.tar" 2>/dev/null && \
         $CONTAINER_ENGINE exec "${CLUSTER_NAME}-control-plane" \
           ctr --namespace=k8s.io images import /preload-images.tar >/dev/null 2>&1; then
        $CONTAINER_ENGINE exec "${CLUSTER_NAME}-control-plane" rm -f /preload-images.tar 2>/dev/null || true
        exit 0
      else
        $CONTAINER_ENGINE exec "${CLUSTER_NAME}-control-plane" rm -f /preload-images.tar 2>/dev/null || true
        exit 1
      fi
    ) &
    PRELOAD_LOAD_PID=$!
  fi
elif $PRELOAD_IMAGES && $DRY_RUN; then
  log_info "[dry-run] Would preload images from $SCRIPT_DIR/preload-images.txt"
fi

# ============================================================================
# Step 2: Install cert-manager (core — required by webhook TLS)
# ============================================================================
log_info "Step 2: cert-manager"

if kubectl get deployment cert-manager-webhook -n cert-manager &>/dev/null; then
  log_success "cert-manager already installed — skipping"
else
  log_info "Installing cert-manager ${CERT_MANAGER_VERSION}..."
  run_cmd kubectl apply -f \
    "https://github.com/cert-manager/cert-manager/releases/download/${CERT_MANAGER_VERSION}/cert-manager.yaml"
  _wait_deployment_ready cert-manager-webhook cert-manager cert-manager
  log_success "cert-manager installed"
fi
echo ""

# ============================================================================
# Step 3: Install Istio Gateway Controller (core — required for ingress)
# ============================================================================
log_info "Step 3: Istio Gateway Controller (core)"

ISTIO_REPO="https://istio-release.storage.googleapis.com/charts/"

log_info "Installing istio-base ${ISTIO_VERSION}..."
run_cmd helm upgrade --install istio-base base \
  --repo "$ISTIO_REPO" --version "$ISTIO_VERSION" \
  -n istio-system --create-namespace --wait

log_info "Installing istiod ${ISTIO_VERSION}..."
run_cmd helm upgrade --install istiod istiod \
  --repo "$ISTIO_REPO" --version "$ISTIO_VERSION" \
  -n istio-system --wait

kubectl label namespace istio-system shared-gateway-access=true --overwrite 2>/dev/null || true
log_success "Istio Gateway Controller installed"
echo ""

# ============================================================================
# Step 3a: Install Istio Ambient Mesh (optional — mTLS, waypoints)
# ============================================================================
if $WITH_ISTIO; then
  log_info "Step 3a: Istio Ambient Mesh"

  log_info "Upgrading istiod to ambient profile..."
  # Remove webhook managed by pilot-discovery to avoid Helm server-side apply conflict
  kubectl delete validatingwebhookconfiguration istio-validator-istio-system --ignore-not-found
  run_cmd helm upgrade --install istiod istiod \
    --repo "$ISTIO_REPO" --version "$ISTIO_VERSION" \
    -n istio-system --wait \
    --set profile=ambient

  log_info "Installing istio-cni..."
  run_cmd helm upgrade --install istio-cni cni \
    --repo "$ISTIO_REPO" --version "$ISTIO_VERSION" \
    -n istio-system --wait \
    --set profile=ambient

  log_info "Installing ztunnel..."
  run_cmd helm upgrade --install ztunnel ztunnel \
    --repo "$ISTIO_REPO" --version "$ISTIO_VERSION" \
    -n istio-system --wait

  log_success "Istio Ambient Mesh installed"
else
  log_info "Ambient mesh skipped (use --with-istio for mTLS + waypoints)"
fi
echo ""

# ============================================================================
# Step 3b: Install Kiali + Prometheus (optional, --with-kiali, requires Istio)
# ============================================================================
if $WITH_KIALI; then
  log_info "Step 3b: Kiali + Prometheus"
  ISTIO_BRANCH="release-${ISTIO_VERSION%.*}"
  log_info "Installing Prometheus (from Istio ${ISTIO_BRANCH} samples)..."
  run_cmd kubectl apply -f \
    "https://raw.githubusercontent.com/istio/istio/${ISTIO_BRANCH}/samples/addons/prometheus.yaml"
  log_info "Installing Kiali (from Istio ${ISTIO_BRANCH} samples)..."
  run_cmd kubectl apply -f \
    "https://raw.githubusercontent.com/istio/istio/${ISTIO_BRANCH}/samples/addons/kiali.yaml"
  log_success "Kiali + Prometheus installed"
  echo ""
fi

# ============================================================================
# Step 3c: Install Tekton (optional, --with-builds)
# ============================================================================
if $WITH_BUILDS; then
  log_info "Step 3b: Tekton"
  install_tekton "$TEKTON_VERSION"
  echo ""
fi

# ============================================================================
# Step 4: Install SPIRE (optional)
# ============================================================================
log_info "Step 4: SPIRE"

if $WITH_SPIRE; then
  SPIRE_REPO="https://spiffe.github.io/helm-charts-hardened/"

  log_info "Installing SPIRE CRDs ${SPIRE_CRD_VERSION}..."
  run_cmd helm upgrade --install spire-crds spire-crds \
    --repo "$SPIRE_REPO" --version "$SPIRE_CRD_VERSION" \
    -n spire-mgmt --create-namespace --wait

  log_info "Installing SPIRE ${SPIRE_VERSION}..."
  run_cmd helm upgrade --install spire spire \
    --repo "$SPIRE_REPO" --version "$SPIRE_VERSION" \
    -n spire-mgmt --create-namespace --wait --timeout=5m \
    --set global.spire.recommendations.enabled=true \
    --set global.spire.namespaces.create=true \
    --set global.spire.namespaces.server.name=zero-trust-workload-identity-manager \
    --set global.spire.namespaces.server.create=true \
    --set-string "global.spire.namespaces.server.labels.shared-gateway-access=true" \
    --set global.spire.ingressControllerType="" \
    --set global.spire.clusterName=agent-platform \
    --set "global.spire.trustDomain=${DOMAIN}" \
    --set "global.spire.caSubject.country=US" \
    --set "global.spire.caSubject.organization=AgenticPlatformDemo" \
    --set "global.spire.caSubject.commonName=${DOMAIN}" \
    --set spire-server.tornjak.enabled=true \
    --set "spire-server.controllerManager.ignoreNamespaces={kube-system,kube-public}" \
    --set spire-server.controllerManager.identities.clusterSPIFFEIDs.default.autoPopulateDNSNames=true \
    --set spire-server.controllerManager.identities.clusterSPIFFEIDs.default.jwtTTL=5m \
    --set spiffe-oidc-discovery-provider.enabled=true \
    --set spiffe-oidc-discovery-provider.config.set_key_use=true \
    --set spiffe-oidc-discovery-provider.tls.spire.enabled=false \
    --set tornjak-frontend.enabled=true \
    --set tornjak-frontend.image.tag=v2.0.0 \
    --set tornjak-frontend.ingress.enabled=true \
    --set "tornjak-frontend.apiServerURL=http://spire-tornjak-ui.${DOMAIN}:8080" \
    --set tornjak-frontend.service.type=ClusterIP \
    --set tornjak-frontend.service.port=3000

  log_success "SPIRE installed"
else
  log_info "Skipped (use --with-spire)"
fi
echo ""

# ============================================================================
# Step 5: Install Gateway API CRDs
# ============================================================================
# Always required: kagenti-deps chart creates HTTPRoute resources (e.g. Keycloak)
log_info "Step 5: Gateway API CRDs"
if kubectl get crd gateways.gateway.networking.k8s.io &>/dev/null; then
  log_success "Gateway API CRDs already installed"
else
  log_info "Installing Gateway API ${GATEWAY_API_VERSION}..."
  run_cmd kubectl apply -f \
    "https://github.com/kubernetes-sigs/gateway-api/releases/download/${GATEWAY_API_VERSION}/standard-install.yaml"
  if ! $DRY_RUN; then
    log_info "Waiting for Gateway API CRDs to become established..."
    _wait_crds_established 60s \
      httproutes.gateway.networking.k8s.io \
      gateways.gateway.networking.k8s.io
  fi
  log_success "Gateway API CRDs installed"
fi
echo ""

# ============================================================================
# Step 5b: Install agent-sandbox (optional, --with-agent-sandbox)
# ============================================================================
if $WITH_AGENT_SANDBOX; then
  log_info "Step 5b: agent-sandbox (kubernetes-sigs)"

  if kubectl get crd sandboxes.agents.x-k8s.io &>/dev/null \
     && kubectl get deployment agent-sandbox-controller -n agent-sandbox-system &>/dev/null; then
    log_success "agent-sandbox already installed — skipping"
  else
    log_info "Installing agent-sandbox ${AGENT_SANDBOX_VERSION} (controller)..."
    run_cmd kubectl apply -f \
      "https://github.com/kubernetes-sigs/agent-sandbox/releases/download/${AGENT_SANDBOX_VERSION}/manifest.yaml"

    log_info "Installing agent-sandbox ${AGENT_SANDBOX_VERSION} (extensions)..."
    run_cmd kubectl apply -f \
      "https://github.com/kubernetes-sigs/agent-sandbox/releases/download/${AGENT_SANDBOX_VERSION}/extensions.yaml"

    if ! $DRY_RUN; then
      log_info "Waiting for agent-sandbox CRDs to become established..."
      _wait_crds_established 60s \
        sandboxes.agents.x-k8s.io
    fi
    _wait_deployment_ready agent-sandbox-controller agent-sandbox-system agent-sandbox
    log_success "agent-sandbox installed"
  fi
  echo ""
fi

# ============================================================================
# Step 6: Install kagenti-deps chart (core: Keycloak + toggles)
# ============================================================================
log_info "Step 6: kagenti-deps"

log_info "Updating kagenti-deps chart dependencies..."
run_cmd helm dependency update "$REPO_ROOT/charts/kagenti-deps/"

DEPS_FLAGS=(
  --set "openshift=false"
  --set "domain=${DOMAIN}"
  # Core: Keycloak always on
  --set "components.keycloak.enabled=true"
  # cert-manager CRDs are installed in Step 2 — disable the subchart
  --set "components.certManager.enabled=false"
  # Components toggled by flags
  --set "components.istio.enabled=false"
  --set "components.spire.enabled=${WITH_SPIRE}"
  --set "components.otel.enabled=${WITH_OTEL}"
  --set "components.metricsServer.enabled=${WITH_BACKEND}"
  --set "components.containerRegistry.enabled=${WITH_BUILDS}"
  --set "components.ingressGateway.enabled=true"
  --set "components.mcpInspector.enabled=${WITH_MCP_GATEWAY}"
  --set "components.tekton.enabled=false"
  --set "components.shipwright.enabled=false"
  --set "components.kiali.enabled=${WITH_KIALI}"
  --set "components.mlflow.enabled=${WITH_MLFLOW}"
  --set "mlflow.auth.enabled=${WITH_MLFLOW}"
  --set "components.rhoai.enabled=false"
)
DEPS_FLAGS=( "${DEPS_FLAGS[@]}" ${KAGENTI_DEPS_VALUES_FILES[@]+"${KAGENTI_DEPS_VALUES_FILES[@]}"} )

log_info "Installing kagenti-deps..."
# --skip-crds: Gateway API CRDs already installed in Step 5 at a newer version;
# the bundled crds/ in the chart would conflict with the kubectl field manager.
run_cmd helm upgrade --install kagenti-deps "$REPO_ROOT/charts/kagenti-deps/" \
  -n kagenti-system --create-namespace --wait --timeout 20m \
  --skip-crds \
  "${DEPS_FLAGS[@]}"

# Label kagenti-system for shared gateway access
kubectl label namespace kagenti-system shared-gateway-access=true --overwrite 2>/dev/null || true

log_success "kagenti-deps installed"
echo ""

# ── Configure Kind node to reach in-cluster container registry ──────────────
# Kind-only: writes /etc/hosts and /etc/containerd/certs.d on the Kind
# control-plane container so kubelet can pull images from the in-cluster
# registry by its cluster-DNS hostname. Vanilla Kubernetes operators need
# to configure their nodes via the distribution's normal mechanism (e.g.
# /etc/rancher/k3s/registries.yaml on K3s, /etc/containerd/config.toml +
# restart on kubeadm); this script intentionally doesn't try to SSH into
# nodes or guess the distro. Skip the block under the k8s flavor.
if $WITH_BUILDS && [[ "${KAGENTI_SETUP_FLAVOR:-kind}" != "k8s" ]]; then
  REGISTRY_NAME="registry"
  REGISTRY_NS="cr-system"
  REGISTRY_HOST="${REGISTRY_NAME}.${REGISTRY_NS}.svc.cluster.local"
  REGISTRY_HOST_PORT="${REGISTRY_HOST}:5000"

  log_info "Configuring Kind node to reach in-cluster registry (${REGISTRY_HOST_PORT})..."

  if ! $DRY_RUN; then
    CLUSTER_IP=$(kubectl get svc "$REGISTRY_NAME" -n "$REGISTRY_NS" -o jsonpath='{.spec.clusterIP}' 2>/dev/null || true)
    if [ -n "$CLUSTER_IP" ]; then
      # Upsert registry DNS in Kind node's /etc/hosts (replace stale entry if present).
      # /etc/hosts is a bind mount so sed -i (rename) fails; use grep -v + cat > instead.
      $CONTAINER_ENGINE exec "${CLUSTER_NAME}-control-plane" \
        sh -c "{ grep -v '${REGISTRY_HOST}' /etc/hosts || true; } > /tmp/hosts.tmp && cat /tmp/hosts.tmp > /etc/hosts && echo '${CLUSTER_IP} ${REGISTRY_HOST}' >> /etc/hosts"

      # Configure containerd registry mirror for insecure in-cluster registry
      $CONTAINER_ENGINE exec "${CLUSTER_NAME}-control-plane" sh -c "
        mkdir -p /etc/containerd/certs.d/${REGISTRY_HOST_PORT}
        cat > /etc/containerd/certs.d/${REGISTRY_HOST_PORT}/hosts.toml <<TOML
server = \"http://${REGISTRY_HOST_PORT}\"

[host.\"http://${REGISTRY_HOST_PORT}\"]
  capabilities = [\"pull\", \"resolve\", \"push\"]
  skip_verify = true
TOML
      "
      log_success "Kind registry DNS configured (${CLUSTER_IP} -> ${REGISTRY_HOST})"
    else
      log_warn "Could not resolve registry ClusterIP — registry DNS not configured"
    fi
  fi
  echo ""
elif $WITH_BUILDS; then
  log_info "Skipping Kind registry-DNS step on vanilla Kubernetes."
  log_info "  To pull images from the in-cluster registry by its cluster-DNS"
  log_info "  hostname (registry.cr-system.svc.cluster.local:5000), configure"
  log_info "  containerd on each node via your distribution's mechanism:"
  log_info "    K3s:     /etc/rancher/k3s/registries.yaml + restart k3s/k3s-agent"
  log_info "    kubeadm: /etc/containerd/config.toml + systemctl restart containerd"
  echo ""
fi

# ============================================================================
# Step 6b: Install Shipwright (optional, --with-builds, after cert-manager)
# ============================================================================
if $WITH_BUILDS; then
  log_info "Step 6b: Shipwright"
  install_shipwright "$SHIPWRIGHT_VERSION"
  echo ""
fi

# ============================================================================
# Step 7: SPIRE post-install (OIDC patch + SPIFFE IdP setup job)
# ============================================================================
if $WITH_SPIRE && ! $DRY_RUN; then
  log_info "Step 7: SPIRE post-install"

  SPIRE_SERVER_NS="zero-trust-workload-identity-manager"
  KAGENTI_NS="kagenti-system"

  # 7a: Patch OIDC ConfigMap to enable set_key_use (required for Keycloak to accept JWKS keys)
  # The helm value spiffe-oidc-discovery-provider.config.set_key_use=true does not render into
  # the ConfigMap with the current chart version, so we patch it directly.
  log_info "Waiting for OIDC discovery provider to be ready..."
  kubectl wait --for=condition=Available deployment/spire-spiffe-oidc-discovery-provider \
    -n "$SPIRE_SERVER_NS" --timeout=300s 2>/dev/null \
    && log_success "OIDC discovery provider ready" \
    || log_warn "OIDC discovery provider not ready after 5m — IdP setup may fail"

  OIDC_CONF=$(kubectl get configmap spire-spiffe-oidc-discovery-provider \
    -n "$SPIRE_SERVER_NS" \
    -o jsonpath='{.data.oidc-discovery-provider\.conf}' 2>/dev/null || echo "")
  if [ -n "$OIDC_CONF" ] && ! echo "$OIDC_CONF" | python3 -c "import sys,json; d=json.load(sys.stdin); exit(0 if d.get('set_key_use') else 1)" 2>/dev/null; then
    log_info "Patching OIDC ConfigMap with set_key_use: true..."
    PATCHED=$(echo "$OIDC_CONF" | python3 -c "import sys,json; d=json.load(sys.stdin); d['set_key_use']=True; json.dump(d,sys.stdout)")
    kubectl get configmap spire-spiffe-oidc-discovery-provider -n "$SPIRE_SERVER_NS" -o json | \
      python3 -c "
import sys, json
cm = json.load(sys.stdin)
cm['data']['oidc-discovery-provider.conf'] = '''$PATCHED'''
json.dump(cm, sys.stdout)
" | kubectl apply -f -
    kubectl rollout restart deployment/spire-spiffe-oidc-discovery-provider -n "$SPIRE_SERVER_NS"
    kubectl rollout status deployment/spire-spiffe-oidc-discovery-provider \
      -n "$SPIRE_SERVER_NS" --timeout=120s || true
    log_success "OIDC ConfigMap patched with set_key_use: true"
  else
    log_success "OIDC ConfigMap already has set_key_use"
  fi

  # 7b: Run SPIFFE IdP setup job (configures Keycloak with SPIRE identity provider)
  log_info "Setting up SPIFFE IdP..."

  # Get kagenti-deps values for image/config references
  KC_URL=$(helm get values kagenti-deps -n "$KAGENTI_NS" --all -o json 2>/dev/null | \
    python3 -c "import sys,json; print(json.load(sys.stdin).get('keycloak',{}).get('url','http://keycloak-service.keycloak:8080'))" 2>/dev/null \
    || echo "http://keycloak-service.keycloak:8080")
  KC_REALM=$(helm get values kagenti-deps -n "$KAGENTI_NS" --all -o json 2>/dev/null | \
    python3 -c "import sys,json; print(json.load(sys.stdin).get('keycloak',{}).get('realm','kagenti'))" 2>/dev/null \
    || echo "kagenti")
  KC_NS=$(helm get values kagenti-deps -n "$KAGENTI_NS" --all -o json 2>/dev/null | \
    python3 -c "import sys,json; print(json.load(sys.stdin).get('keycloak',{}).get('namespace','keycloak'))" 2>/dev/null \
    || echo "keycloak")
  KC_ADMIN_SECRET=$(helm get values kagenti-deps -n "$KAGENTI_NS" --all -o json 2>/dev/null | \
    python3 -c "import sys,json; print(json.load(sys.stdin).get('keycloak',{}).get('adminSecretName','keycloak-initial-admin'))" 2>/dev/null \
    || echo "keycloak-initial-admin")
  SPIFFE_IDP_IMAGE=$(helm get values kagenti-deps -n "$KAGENTI_NS" --all -o json 2>/dev/null | \
    python3 -c "import sys,json; v=json.load(sys.stdin); print(v.get('spiffeIdp',{}).get('image',{}).get('repository','ghcr.io/kagenti/kagenti/spiffe-idp-setup') + ':' + str(v.get('spiffeIdp',{}).get('image',{}).get('tag','latest')))" 2>/dev/null \
    || echo "ghcr.io/kagenti/kagenti/spiffe-idp-setup:latest")
  KUBECTL_IMAGE=$(helm get values kagenti-deps -n "$KAGENTI_NS" --all -o json 2>/dev/null | \
    python3 -c "import sys,json; print(json.load(sys.stdin).get('common',{}).get('kubectlImage','quay.io/kubestellar/kubectl:1.30.14'))" 2>/dev/null \
    || echo "quay.io/kubestellar/kubectl:1.30.14")
  SPIFFE_IDP_ALIAS=$(helm get values kagenti-deps -n "$KAGENTI_NS" --all -o json 2>/dev/null | \
    python3 -c "import sys,json; print(json.load(sys.stdin).get('authBridge',{}).get('spiffeIdpAlias','spire-spiffe'))" 2>/dev/null \
    || echo "spire-spiffe")

  # Create RBAC for the setup job
  kubectl apply -f - <<EOF
apiVersion: v1
kind: ServiceAccount
metadata:
  name: kagenti-spiffe-idp-setup
  namespace: ${KAGENTI_NS}
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: kagenti-spiffe-idp-reader
rules:
  - apiGroups: [""]
    resources: ["secrets"]
    resourceNames: ["${KC_ADMIN_SECRET}"]
    verbs: ["get"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: kagenti-spiffe-idp-keycloak-reader
  namespace: ${KC_NS}
subjects:
  - kind: ServiceAccount
    name: kagenti-spiffe-idp-setup
    namespace: ${KAGENTI_NS}
roleRef:
  kind: ClusterRole
  name: kagenti-spiffe-idp-reader
  apiGroup: rbac.authorization.k8s.io
---
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: kagenti-spiffe-idp-pod-reader
  namespace: ${SPIRE_SERVER_NS}
rules:
  - apiGroups: [""]
    resources: ["pods"]
    verbs: ["get", "list", "watch"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: kagenti-spiffe-idp-pod-reader
  namespace: ${SPIRE_SERVER_NS}
subjects:
  - kind: ServiceAccount
    name: kagenti-spiffe-idp-setup
    namespace: ${KAGENTI_NS}
roleRef:
  kind: Role
  name: kagenti-spiffe-idp-pod-reader
  apiGroup: rbac.authorization.k8s.io
---
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: kagenti-spiffe-idp-pod-reader
  namespace: ${KC_NS}
rules:
  - apiGroups: [""]
    resources: ["pods"]
    verbs: ["get", "list", "watch"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: kagenti-spiffe-idp-pod-reader
  namespace: ${KC_NS}
subjects:
  - kind: ServiceAccount
    name: kagenti-spiffe-idp-setup
    namespace: ${KAGENTI_NS}
roleRef:
  kind: Role
  name: kagenti-spiffe-idp-pod-reader
  apiGroup: rbac.authorization.k8s.io
EOF

  # Build and load spiffe-idp-setup image to ensure correct arch for Kind
  if $BUILD_IMAGES; then
    log_info "Building spiffe-idp-setup image for Kind..."
    $CONTAINER_ENGINE buildx build --load \
      -t "$SPIFFE_IDP_IMAGE" \
      -f "$REPO_ROOT/kagenti/auth/spiffe-idp-setup/Dockerfile" \
      "$REPO_ROOT/kagenti"
    load_image_into_kind "$SPIFFE_IDP_IMAGE"
  fi

  # Delete existing job (jobs are immutable)
  kubectl delete job kagenti-spiffe-idp-setup-job -n "$KAGENTI_NS" --ignore-not-found 2>/dev/null || true

  # Create the setup job
  kubectl apply -f - <<EOF
apiVersion: batch/v1
kind: Job
metadata:
  name: kagenti-spiffe-idp-setup-job
  namespace: ${KAGENTI_NS}
spec:
  backoffLimit: 10
  template:
    metadata:
      labels:
        app: kagenti-spiffe-idp-setup
    spec:
      serviceAccountName: kagenti-spiffe-idp-setup
      restartPolicy: OnFailure
      initContainers:
        - name: wait-for-dependencies
          image: "${KUBECTL_IMAGE}"
          command: ["sh", "-c"]
          args:
            - |
              set -e
              echo "Waiting for SPIRE server..."
              kubectl wait --for=condition=ready pod \
                -l app.kubernetes.io/name=server \
                -n ${SPIRE_SERVER_NS} --timeout=300s
              echo "Waiting for SPIRE OIDC discovery provider..."
              kubectl wait --for=condition=ready pod \
                -l app.kubernetes.io/name=spiffe-oidc-discovery-provider \
                -n ${SPIRE_SERVER_NS} --timeout=300s
              echo "Waiting for Keycloak to be ready..."
              kubectl wait --for=condition=ready pod \
                -l app=keycloak -n ${KC_NS} --timeout=300s
              echo "Validating OIDC JWKS endpoint serves keys with 'use' field..."
              OIDC_URL="http://spire-spiffe-oidc-discovery-provider.${SPIRE_SERVER_NS}.svc.cluster.local/keys"
              for i in \$(seq 1 60); do
                if curl -sf "\$OIDC_URL" | grep -q '"use"'; then
                  echo "OIDC JWKS endpoint validated"
                  exit 0
                fi
                echo "  Attempt \$i/60: OIDC keys not ready, retrying in 5s..."
                sleep 5
              done
              echo "WARNING: OIDC keys validation timed out after 5m"
              exit 1
      containers:
        - name: setup-spiffe-idp
          image: "${SPIFFE_IDP_IMAGE}"
          env:
            - name: KEYCLOAK_BASE_URL
              value: "${KC_URL}"
            - name: KEYCLOAK_REALM
              value: "${KC_REALM}"
            - name: KEYCLOAK_NAMESPACE
              value: "${KC_NS}"
            - name: KEYCLOAK_ADMIN_SECRET_NAME
              value: "${KC_ADMIN_SECRET}"
            - name: KEYCLOAK_ADMIN_USERNAME_KEY
              value: "username"
            - name: KEYCLOAK_ADMIN_PASSWORD_KEY
              value: "password"
            - name: SPIFFE_TRUST_DOMAIN
              value: "spiffe://${DOMAIN}"
            - name: SPIFFE_BUNDLE_ENDPOINT
              value: "http://spire-spiffe-oidc-discovery-provider.${SPIRE_SERVER_NS}.svc.cluster.local/keys"
            - name: SPIFFE_IDP_ALIAS
              value: "${SPIFFE_IDP_ALIAS}"
EOF

  # Wait for job to complete (up to 10m — the job's wait_for_spire() retries
  # for up to 5m if OIDC keys aren't ready, plus container startup overhead)
  log_info "Waiting for SPIFFE IdP setup job..."
  if kubectl wait --for=condition=complete job/kagenti-spiffe-idp-setup-job \
       -n "$KAGENTI_NS" --timeout=600s 2>/dev/null; then
    log_success "SPIFFE IdP setup complete"
  else
    log_warn "SPIFFE IdP setup job did not complete in 10m — check logs:"
    log_warn "  kubectl logs -n $KAGENTI_NS job/kagenti-spiffe-idp-setup-job"
  fi
  echo ""
fi

# ============================================================================
# Step 8: Install kagenti chart (operator + webhook + optional UI)
# ============================================================================
log_info "Step 8: kagenti"

# Image tags come from charts/kagenti/values.yaml (pinned at release time by
# chore(release) commits — see docs/releasing.md). The only override is below
# in KAGENTI_FLAGS when --build-images is set, since locally-built images are
# tagged ":latest" and loaded into Kind.

# Secrets file resolution (checked in order of precedence):
#   1. --secrets-file CLI argument
#   2. charts/kagenti/.secrets.yaml (user-created)
#   3. Fall back to copying .secrets_template.yaml (empty defaults)
SECRETS_FLAGS=()
if [ -n "$SECRETS_FILE_ARG" ]; then
  if [ ! -f "$SECRETS_FILE_ARG" ]; then
    log_error "Secrets file not found: $SECRETS_FILE_ARG"
    exit 1
  fi
  log_info "Using secrets from $SECRETS_FILE_ARG"
  SECRETS_FLAGS=(-f "$SECRETS_FILE_ARG")
elif [ -f "$REPO_ROOT/charts/kagenti/.secrets.yaml" ]; then
  SECRETS_FLAGS=(-f "$REPO_ROOT/charts/kagenti/.secrets.yaml")
elif [ -f "$REPO_ROOT/charts/kagenti/.secrets_template.yaml" ]; then
  log_info "No secrets file found — using empty defaults from template"
  cp "$REPO_ROOT/charts/kagenti/.secrets_template.yaml" "$REPO_ROOT/charts/kagenti/.secrets.yaml"
  SECRETS_FLAGS=(-f "$REPO_ROOT/charts/kagenti/.secrets.yaml")
fi

log_info "Updating kagenti chart dependencies..."
run_cmd helm dependency update "$REPO_ROOT/charts/kagenti/"

# Delete old OAuth secret jobs (immutable — must delete before helm upgrade)
kubectl delete job kagenti-ui-oauth-secret-job -n kagenti-system --ignore-not-found 2>/dev/null || true
kubectl delete job kagenti-agent-oauth-secret-job -n kagenti-system --ignore-not-found 2>/dev/null || true
kubectl delete job mlflow-oauth-secret-job -n kagenti-system --ignore-not-found 2>/dev/null || true

# Delete ClusterRoleBindings whose roleRef changed between chart versions.
# Kubernetes forbids mutating roleRef — the binding must be deleted so Helm can
# recreate it with the new reference. (Fixes #1838)
_delete_stale_rolebinding() {
  local binding="$1" expected_role="$2"
  local current_role
  current_role=$(kubectl get clusterrolebinding "$binding" -o jsonpath='{.roleRef.name}' 2>/dev/null || echo "")
  if [ -n "$current_role" ] && [ "$current_role" != "$expected_role" ]; then
    log_info "Deleting ClusterRoleBinding/$binding (roleRef changed: $current_role → $expected_role)"
    kubectl delete clusterrolebinding "$binding" --ignore-not-found 2>/dev/null || true
  fi
}
_delete_stale_rolebinding "kagenti-operator-httproute-binding-kagenti" "kagenti-operator-httproute-kagenti"
_delete_stale_rolebinding "kagenti-manager-rolebinding" "kagenti-manager-role"
_delete_stale_rolebinding "kagenti-mlflow-integration-kagenti" "mlflow-operator-mlflow-integration"

# ── Wait for preload to finish (if running) ──
if [ -n "$PRELOAD_LOAD_PID" ]; then
  log_info "Waiting for image preload to complete..."
  if wait "$PRELOAD_LOAD_PID"; then
    log_success "All images preloaded into Kind"
  else
    log_warn "Some images failed to load — pods will pull on demand"
  fi
fi

# ── Build platform images from source (--build-images) ──
if $BUILD_IMAGES && ! $DRY_RUN; then
  log_info "Building platform images from source..."
  BUILD_CONTEXT="$REPO_ROOT/kagenti"

  # Always build agent-oauth-secret (kagenti chart always creates this job)
  _BUILD_IMAGES=(
    "ghcr.io/kagenti/kagenti/agent-oauth-secret:latest|auth/agent-oauth-secret/Dockerfile"
  )
  if $WITH_BACKEND; then
    _BUILD_IMAGES+=("ghcr.io/kagenti/kagenti/backend:latest|backend/Dockerfile")
  fi
  if $WITH_UI; then
    _BUILD_IMAGES+=("ghcr.io/kagenti/kagenti/ui-v2:latest|ui-v2/Dockerfile")
    _BUILD_IMAGES+=("ghcr.io/kagenti/kagenti/ui-oauth-secret:latest|auth/ui-oauth-secret/Dockerfile")
  fi
  if $WITH_MLFLOW; then
    _BUILD_IMAGES+=("ghcr.io/kagenti/kagenti/mlflow-oauth-secret:latest|auth/mlflow-oauth-secret/Dockerfile")
  fi

  for spec in "${_BUILD_IMAGES[@]}"; do
    IFS='|' read -r img dockerfile <<< "$spec"
    log_info "  Building ${img}..."
    $CONTAINER_ENGINE buildx build --load -t "$img" -f "$BUILD_CONTEXT/$dockerfile" "$BUILD_CONTEXT"
    load_image_into_kind "$img"
  done
  log_success "Platform images built and loaded into Kind"
fi

# Pre-create mcp-system namespace (kagenti chart creates resources there when mcpGateway is enabled)
if $WITH_MCP_GATEWAY; then
  kubectl create namespace mcp-system --dry-run=client -o yaml | kubectl apply -f - 2>/dev/null || true
fi

KAGENTI_FLAGS=(
  --set "openshift=false"
  --set "domain=${DOMAIN}"
  --set "keycloak.publicUrl=http://keycloak.${DOMAIN}:8080"
  --set "mlflow.url=http://mlflow.${DOMAIN}:8080"
  --set "components.agentNamespaces.enabled=true"
  --set "components.agentOperator.enabled=true"
  --set "components.ui.enabled=${WITH_BACKEND}"
  --set "ui.frontend.enabled=${WITH_UI}"
  --set "components.istio.enabled=${WITH_ISTIO}"
  --set "components.mcpGateway.enabled=${WITH_MCP_GATEWAY}"
  --set "featureFlags.agentSandbox=${WITH_AGENT_SANDBOX}"
  --set "featureFlags.skills=${WITH_SKILLS}"
  --set "featureFlags.externalSkills=${WITH_SKILLS}"
  --set "components.skillberryStore.enabled=${WITH_SKILLS}"
  --set "components.mlflow.enabled=${WITH_MLFLOW}"
  --set "ui.auth.enabled=$($WITH_SPIRE && echo true || echo false)"
  --set "mlflow.auth.enabled=${WITH_MLFLOW}"
  --set "kagenti-operator-chart.featureGates.injectTools=true"
  --set "kagenti-operator-chart.kuadrant.enable=${WITH_KUADRANT}"
)

# Allow-list hosts/IPs/CIDRs past the registry-URL SSRF block (for LAN / in-cluster
# skill registries on private IPs). Escape commas so Helm treats the value as a
# single string rather than a list.
if [[ -n "$SKILL_REGISTRY_ALLOWED_HOSTS" ]]; then
  KAGENTI_FLAGS+=(--set-string "ui.backend.skillRegistryAllowedHosts=${SKILL_REGISTRY_ALLOWED_HOSTS//,/\\,}")
fi

# Optional in-cluster skillberry-store image override (no dedicated flag).
# Defaults come from charts/kagenti/values.yaml (tag 0.2.0).
if $WITH_SKILLS; then
  [[ -n "${SKILLBERRY_STORE_IMAGE:-}" ]] && KAGENTI_FLAGS+=(--set "skillberryStore.image.repository=${SKILLBERRY_STORE_IMAGE}")
  [[ -n "${SKILLBERRY_STORE_TAG:-}" ]]   && KAGENTI_FLAGS+=(--set "skillberryStore.image.tag=${SKILLBERRY_STORE_TAG}")
fi

KAGENTI_FLAGS=( "${KAGENTI_FLAGS[@]}" ${KAGENTI_VALUES_FILES[@]+"${KAGENTI_VALUES_FILES[@]}"} )

# When --build-images is set, the build step tags images ":latest" and loads
# them into Kind (see list above). Override the chart's release-pinned tags
# for exactly those images so pods use the locally-built copies instead of
# pulling pinned tags from ghcr.io. Image selection mirrors _BUILD_IMAGES.
if $BUILD_IMAGES; then
  KAGENTI_FLAGS+=(--set "agentOAuthSecret.tag=latest")
  if $WITH_BACKEND; then
    KAGENTI_FLAGS+=(--set "ui.backend.tag=latest")
  fi
  if $WITH_UI; then
    KAGENTI_FLAGS+=(--set "ui.frontend.tag=latest")
    KAGENTI_FLAGS+=(--set "uiOAuthSecret.tag=latest")
  fi
  if $WITH_MLFLOW; then
    KAGENTI_FLAGS+=(--set "mlflowOAuthSecret.tag=latest")
  fi
fi

log_info "Installing kagenti..."
run_cmd helm upgrade --install kagenti "$REPO_ROOT/charts/kagenti/" \
  -n kagenti-system --wait --timeout 20m \
  "${SECRETS_FLAGS[@]+"${SECRETS_FLAGS[@]}"}" \
  "${KAGENTI_FLAGS[@]}"

log_success "kagenti installed"
echo ""

# ============================================================================
# Step 8b: Install Kuadrant operator (optional, --with-kuadrant)
# ============================================================================
log_info "Step 8b: Kuadrant"

if $WITH_KUADRANT; then
  KUADRANT_NS="kuadrant-system"

  log_info "Installing Kuadrant operator v${KUADRANT_VERSION}..."
  run_cmd helm upgrade --install kuadrant-operator kuadrant-operator \
    --repo "https://kuadrant.io/helm-charts/" \
    --version "$KUADRANT_VERSION" \
    -n "$KUADRANT_NS" --create-namespace --wait --timeout 5m

  if ! $DRY_RUN; then
    _wait_deployment_ready kuadrant-operator-controller-manager "$KUADRANT_NS" "Kuadrant operator"
    # Kuadrant CR is created by the kagenti-operator's Kuadrant operand controller
    # when --enable-kuadrant is set (see kagenti-operator chart values).
    # The operator was installed before the Kuadrant CRD existed, so restart it
    # to trigger KuadrantCRDExists() re-evaluation and controller registration.
    log_info "Restarting kagenti-operator to pick up Kuadrant CRD..."
    kubectl rollout restart deployment/kagenti-controller-manager -n kagenti-system
    _wait_deployment_ready kagenti-controller-manager kagenti-system "kagenti-operator"
  fi

  log_success "Kuadrant installed"
else
  log_info "Skipped (use --with-kuadrant)"
fi
echo ""

# ============================================================================
# Step 9: Install MCP Gateway (optional)
# ============================================================================
log_info "Step 9: MCP Gateway"

if $WITH_MCP_GATEWAY; then
  # Create gateway-system namespace (required by MCP Gateway, not created by its chart)
  kubectl create namespace mcp-system --dry-run=client -o yaml | kubectl apply -f - 2>/dev/null || true
  kubectl create namespace gateway-system --dry-run=client -o yaml | kubectl apply -f - 2>/dev/null || true

  # Clean up any MCPGatewayExtension stuck in deletion (e.g. leftover from a prior
  # version that used a different API group). A stuck finalizer prevents the controller
  # from creating the broker-router deployment on reinstall.
  for _crd_group in mcp.kuadrant.io mcp.kagenti.com; do
    _stuck=$(kubectl get mcpgatewayextensions.${_crd_group} -n mcp-system -o json 2>/dev/null \
      | python3 -c "
import sys, json
data = json.load(sys.stdin)
for item in data.get('items', []):
    if item.get('metadata', {}).get('deletionTimestamp'):
        print(item['metadata']['name'])
" 2>/dev/null || echo "")
    if [ -n "$_stuck" ]; then
      echo "$_stuck" | while read -r _name; do
        log_warn "Removing stuck finalizer from MCPGatewayExtension/${_name} (${_crd_group})"
        kubectl patch "mcpgatewayextensions.${_crd_group}/${_name}" -n mcp-system \
          --type=json -p '[{"op":"remove","path":"/metadata/finalizers"}]' 2>/dev/null || true
      done
      sleep 2
    fi
  done

  log_info "Installing MCP Gateway v${MCP_GATEWAY_VERSION}..."
  run_cmd helm upgrade --install mcp-gateway oci://ghcr.io/kuadrant/charts/mcp-gateway \
    -n mcp-system --create-namespace --version "$MCP_GATEWAY_VERSION" \
    --set "broker.create=true"
  log_success "MCP Gateway installed"

else
  log_info "Skipped (use --with-mcp-gateway)"
fi
echo ""

# ============================================================================
# Step 9b: Install Examples
# ============================================================================
log_info "Step 9b: Agent and tool examples (weather)"

if $INSTALL_EXAMPLES; then
  run_cmd ${REPO_ROOT}/.github/scripts/kagenti-operator/72-deploy-weather-tool.sh
  run_cmd ${REPO_ROOT}/.github/scripts/kagenti-operator/74-deploy-weather-agent.sh
  log_success "Agent and tool examples (weather) installed"

  if ! $DRY_RUN; then
    LLM_API_BASE=$(kubectl get deployment weather-service -n team1 -o jsonpath='{.spec.template.spec.containers[0].env[?(@.name=="LLM_API_BASE")].value}')
    log_info "  Weather Service using LLM at ${LLM_API_BASE}"
    log_info "  (override with kubectl -n team1 set env deployment/weather-service LLM_API_BASE=<your llm>)"
  fi
else
  log_info "Skipped (use --with-examples)"
fi
echo ""

# ============================================================================
# Step 10: Verify & show access info
# ============================================================================
log_info "Step 10: Verification"
echo ""

# Build list of expected Helm releases based on flags
EXPECTED_RELEASES=("istio-base:istio-system" "istiod:istio-system" "kagenti-deps:kagenti-system" "kagenti:kagenti-system")
if $WITH_ISTIO; then
  EXPECTED_RELEASES+=("istio-cni:istio-system" "ztunnel:istio-system")
fi
if $WITH_SPIRE; then
  EXPECTED_RELEASES+=("spire-crds:spire-mgmt" "spire:spire-mgmt")
fi
if $WITH_KUADRANT; then
  EXPECTED_RELEASES+=("kuadrant-operator:kuadrant-system")
fi
if $WITH_MCP_GATEWAY; then
  EXPECTED_RELEASES+=("mcp-gateway:mcp-system")
fi

VERIFY_FAILED=false
for release_info in "${EXPECTED_RELEASES[@]}"; do
  release="${release_info%%:*}"
  ns="${release_info##*:}"
  STATUS=$(helm status "$release" -n "$ns" -o json 2>/dev/null | \
    python3 -c "import sys,json; print(json.load(sys.stdin).get('info',{}).get('status',''))" 2>/dev/null || echo "")
  if [ "$STATUS" = "deployed" ]; then
    log_success "$release ($ns): deployed"
  else
    log_error "$release ($ns): status '${STATUS:-not found}'"
    VERIFY_FAILED=true
  fi
done

# Verify key deployments/pods for non-Helm components
_check_deploy() {
  local name="$1" ns="$2"
  if kubectl get deployment "$name" -n "$ns" &>/dev/null; then
    READY=$(kubectl get deployment "$name" -n "$ns" -o jsonpath='{.status.readyReplicas}' 2>/dev/null || echo "0")
    if [ "${READY:-0}" -gt 0 ]; then
      log_success "$name ($ns): ready"
    else
      log_warn "$name ($ns): not ready yet"
    fi
  else
    log_error "$name ($ns): deployment not found"
    VERIFY_FAILED=true
  fi
}

if $WITH_KIALI; then
  _check_deploy kiali istio-system
  _check_deploy prometheus istio-system
fi
if $WITH_MLFLOW; then
  _check_deploy mlflow kagenti-system
fi
if $WITH_BACKEND; then
  _check_deploy kagenti-backend kagenti-system
fi
if $WITH_UI; then
  _check_deploy kagenti-ui kagenti-system
fi

if $VERIFY_FAILED; then
  log_error "One or more releases failed verification"
fi

echo ""
log_info "Access info:"
echo ""
if $WITH_UI; then
  echo "  Kagenti UI:   http://kagenti-ui.${DOMAIN}:8080"
fi
if $WITH_BACKEND; then
  echo "  Kagenti API:  http://kagenti-api.${DOMAIN}:8080"
fi
echo "  Keycloak:     http://keycloak.${DOMAIN}:8080"
if $WITH_MLFLOW; then
  echo "  MLflow:       http://mlflow.${DOMAIN}:8080"
fi
if $WITH_SPIRE; then
  echo "  Tornjak:      http://spire-tornjak-ui.${DOMAIN}:8080"
fi
echo ""
echo "  Credentials:"
KC_ADMIN_USER=$(kubectl get secret keycloak-initial-admin -n keycloak -o jsonpath='{.data.username}' 2>/dev/null | base64 -d 2>/dev/null)
KC_ADMIN_PASS=$(kubectl get secret keycloak-initial-admin -n keycloak -o jsonpath='{.data.password}' 2>/dev/null | base64 -d 2>/dev/null)
if [ -n "$KC_ADMIN_PASS" ]; then
  echo "    Keycloak admin console: ${KC_ADMIN_USER} / ${KC_ADMIN_PASS}"
else
  echo "    Keycloak admin console: (pending — secret keycloak-initial-admin not ready)"
fi
echo ""
echo "  For service URLs and credentials (including UI login), run:"
echo "    .github/scripts/local-setup/show-services.sh"
echo ""

# ============================================================================
# Post-install patches (applied after controllers have stabilized)
# ============================================================================
if $WITH_MCP_GATEWAY && $WITH_OTEL; then
  # The mcp-gateway chart deploys the broker-router via its controller and does not
  # expose OTel config via Helm values. kubectl set env is the only injection point.
  # Patching here (after verification) reduces the likelihood of the controller
  # overwriting the patch during its initial reconcile.
  log_info "Patching MCP Gateway router with OTel exporter..."
  # Wait for the controller to create the deployment (up to 90s)
  waited=0
  while ! kubectl get deployment mcp-gateway -n mcp-system &>/dev/null; do
    if [ $waited -ge 90 ]; then
      log_warn "deployment/mcp-gateway not found in mcp-system after 90s — skipping OTel patch"
      break
    fi
    sleep 5
    waited=$((waited + 5))
  done
  if kubectl get deployment mcp-gateway -n mcp-system &>/dev/null; then
    kubectl rollout status deployment/mcp-gateway -n mcp-system --timeout=60s &>/dev/null || \
      log_warn "rollout not ready — patching anyway"
    run_cmd kubectl set env deployment/mcp-gateway -n mcp-system \
      OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector.kagenti-system.svc.cluster.local:8335 \
      OTEL_EXPORTER_OTLP_PROTOCOL=http/protobuf
    log_success "MCP Gateway OTel exporter configured"
  else
    log_warn "Skipping OTel patch (deployment not found after wait)"
  fi
fi

ELAPSED=$(( SECONDS - START_SECONDS ))
MINS=$(( ELAPSED / 60 ))
SECS=$(( ELAPSED % 60 ))

echo "============================================"
echo "  Kagenti platform is ready!  (${MINS}m ${SECS}s)"
echo "============================================"
echo ""
