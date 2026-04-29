#!/usr/bin/env bash
#
# OpenShell PoC Full Test — Kind and HyperShift (OCP)
#
# Single command to deploy and test OpenShell + Kagenti on either platform.
# Auto-detects Kind vs OCP, handles Helm v3, credentials, and cluster lifecycle.
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
#   --skip-test             Skip E2E test phase
#   --skip-agents           Skip agent deployment
#   --skip-install          Skip Kagenti platform installation
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

# ── Parse arguments ──────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
    case $1 in
        --platform)             PLATFORM="$2"; shift 2 ;;
        --skip-cluster-create)  SKIP_CREATE=true;  shift ;;
        --skip-cluster-destroy) SKIP_DESTROY=true; shift ;;
        --skip-test)            SKIP_TEST=true;    shift ;;
        --skip-agents)          SKIP_AGENTS=true;  shift ;;
        --skip-install)         SKIP_INSTALL=true; shift ;;
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
# Rancher Desktop ships Helm v4 in ~/.rd/bin. The Kagenti installer
# requires Helm v3. Prefer brew's helm@3 if available.
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
    elif kind get clusters 2>/dev/null | grep -q .; then
        PLATFORM="kind"
    else
        PLATFORM="kind"
    fi
fi

# ── HyperShift-specific setup ───────────────────────────────────
MANAGED_BY_TAG="${MANAGED_BY_TAG:-kagenti-hypershift-custom}"

if [ "$PLATFORM" = "ocp" ]; then
    KAGENTI_ENV="openshell"

    if [ -z "$CLUSTER_SUFFIX" ]; then
        CLUSTER_SUFFIX="os$(echo "$USER" | cut -c1-3)$(date +%d)"
    fi
    HCP_CLUSTER_NAME="${MANAGED_BY_TAG}-${CLUSTER_SUFFIX}"
    HOSTED_KUBECONFIG="$HOME/clusters/hcp/$HCP_CLUSTER_NAME/auth/kubeconfig"

    # Load .env if not already sourced
    if [ -z "${AWS_ACCESS_KEY_ID:-}" ] && [ "$SKIP_CREATE" = "false" ]; then
        ENV_FILE="$REPO_ROOT/.env.${MANAGED_BY_TAG}"
        if [ -f "$ENV_FILE" ]; then
            # shellcheck source=/dev/null
            source "$ENV_FILE"
            log_step "Loaded credentials from $(basename "$ENV_FILE")"
        else
            log_error "No .env file found at $ENV_FILE"
            log_error "Run: source .env.${MANAGED_BY_TAG} before this script"
            exit 1
        fi
    fi
fi

# ── Summary ─────────────────────────────────────────────────────
echo ""
echo "OpenShell PoC Full Test"
echo "  Platform:  $PLATFORM"
if [ "$PLATFORM" = "ocp" ]; then
    echo "  Cluster:   $HCP_CLUSTER_NAME"
else
    echo "  Cluster:   $CLUSTER_NAME (Kind)"
fi
echo "  Env:       $KAGENTI_ENV"
echo "  Helm:      $(helm version --short 2>/dev/null)"
echo "  Phases:"
echo "    cluster-create:   $([ "$SKIP_CREATE"  = "true" ] && echo SKIP || echo RUN)"
echo "    kagenti-install:  $([ "$SKIP_INSTALL" = "true" ] && echo SKIP || echo RUN)"
echo "    openshell-deploy: RUN"
echo "    agents-deploy:    $([ "$SKIP_AGENTS"  = "true" ] && echo SKIP || echo RUN)"
echo "    test:             $([ "$SKIP_TEST"    = "true" ] && echo SKIP || echo RUN)"
echo "    cluster-destroy:  $([ "$SKIP_DESTROY" = "true" ] && echo SKIP || echo RUN)"
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
        log_step "Creating cluster: $CLUSTER_NAME"
        CLUSTER_NAME="$CLUSTER_NAME" ./.github/scripts/kind/create-cluster.sh
    else
        log_phase "PHASE 1: Create HyperShift Cluster"
        log_step "Creating cluster: $HCP_CLUSTER_NAME"
        export KUBECONFIG="${MGMT_KUBECONFIG:-$HOME/.kube/kagenti-team-mgmt.kubeconfig}"
        ./.github/scripts/hypershift/create-cluster.sh "$CLUSTER_SUFFIX"
        # Switch to hosted cluster kubeconfig
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
# PHASE 2: Install Kagenti Platform (headless — no UI, no backend)
# ============================================================================
if [ "$SKIP_INSTALL" = "false" ]; then
    log_phase "PHASE 2: Install Kagenti Platform (OpenShell profile)"

    if [ "$PLATFORM" = "ocp" ]; then
        # OCP: Use the Helm-based installer (scripts/ocp/setup-kagenti.sh)
        # This handles cert-manager, Keycloak, SPIRE, Istio, and the operator
        # without Ansible. Skip UI/MLflow/MCP Gateway for OpenShell PoC.
        log_step "Running Helm-based OCP installer..."
        "$REPO_ROOT/scripts/ocp/setup-kagenti.sh" \
            --kagenti-repo "$REPO_ROOT" \
            --skip-ui \
            --skip-mlflow \
            --skip-mcp-gateway \
            --skip-ovn-patch
    else
        # Kind: Use the Ansible installer with the openshell env profile
        log_step "Creating secrets..."
        ./.github/scripts/common/20-create-secrets.sh

        log_step "Running Ansible installer (--env $KAGENTI_ENV)..."
        ./.github/scripts/kagenti-operator/30-run-installer.sh --env "$KAGENTI_ENV"

        log_step "Waiting for platform to be ready..."
        ./.github/scripts/common/40-wait-platform-ready.sh

        log_step "Configuring dockerhost..."
        ./.github/scripts/common/70-configure-dockerhost.sh
    fi

    log_step "Waiting for Kagenti Operator CRDs (AgentRuntime only)..."
    kubectl wait --for=condition=established crd/agentruntimes.agent.kagenti.dev --timeout=120s 2>/dev/null || {
        log_step "AgentRuntime CRD not found — operator may not include it. Continuing."
    }
else
    log_phase "PHASE 2: Skipping Kagenti Installation"
fi

# ============================================================================
# PHASE 3: Deploy OpenShell Gateway
# ============================================================================
log_phase "PHASE 3: Deploy OpenShell Gateway"

log_step "Applying OpenShell manifests (kubectl apply -k)..."
kubectl apply -k deployments/openshell/ --server-side --force-conflicts 2>&1 | grep -v "^Warning:" || {
    log_warn "Server-side apply failed, retrying with --validate=false..."
    kubectl apply -k deployments/openshell/ --validate=false 2>&1 | grep -v "^Warning:"
}

log_step "Waiting for openshell-system pods to be ready..."
kubectl wait --for=condition=ready pod --all -n openshell-system --timeout=180s 2>/dev/null || {
    log_warn "Gateway pods not fully ready. Checking status..."
    kubectl get pods -n openshell-system
}

log_step "OpenShell Gateway status:"
kubectl get pods -n openshell-system

# ── Configure gateway LLM providers (idempotent) ────────────────
# The OpenShell gateway auto-discovers LLM providers from env vars.
# Setting OPENAI_API_KEY + OPENAI_BASE_URL enables builtin sandboxes
# (OpenCode, Claude) to use LiteMaaS for inference.
if [ "${MAAS_SOURCED:-false}" = "true" ]; then
    LITEMAAS_URL="${MAAS_LLAMA4_API_BASE:-https://litellm-prod.apps.maas.redhatworkshops.io/v1}"
    LITEMAAS_KEY="${MAAS_LLAMA4_API_KEY:-}"
    LITEMAAS_MODEL="${MAAS_LLAMA4_MODEL:-llama-scout-17b}"
    if [ -n "$LITEMAAS_KEY" ]; then
        log_step "Configuring gateway with LiteMaaS provider credentials"
        kubectl set env statefulset/openshell-gateway -n openshell-system \
            "OPENAI_API_KEY=$LITEMAAS_KEY" \
            "OPENAI_BASE_URL=$LITEMAAS_URL" \
            "OPENAI_MODEL=$LITEMAAS_MODEL" 2>/dev/null || true
        kubectl rollout status statefulset/openshell-gateway -n openshell-system --timeout=120s 2>/dev/null || {
            log_warn "Gateway rollout not complete after provider config"
        }
    fi
fi

# ── Pre-pull base sandbox image (idempotent) ─────────────────────
# The base image is ~1.1GB. Pre-pulling ensures test_base_image_cli_check
# doesn't time out waiting for the pull.
BASE_IMAGE="ghcr.io/nvidia/openshell-community/sandboxes/base:latest"
if [ "$PLATFORM" = "kind" ]; then
    if ! docker exec "${CLUSTER_NAME}-control-plane" crictl images 2>/dev/null | grep -q "sandboxes/base"; then
        log_step "Pre-pulling base sandbox image into Kind..."
        docker pull "$BASE_IMAGE" 2>/dev/null && \
            kind load docker-image "$BASE_IMAGE" --name "$CLUSTER_NAME" 2>/dev/null || \
            log_warn "Base image pre-pull failed (non-critical)"
    else
        log_step "Base sandbox image already loaded in Kind"
    fi
else
    # OCP: Start a pull Job in the background (non-blocking)
    if ! kubectl get job openshell-base-pull -n team1 >/dev/null 2>&1; then
        log_step "Starting base sandbox image pre-pull Job..."
        kubectl apply -f - <<EOJOB 2>/dev/null || true
apiVersion: batch/v1
kind: Job
metadata:
  name: openshell-base-pull
  namespace: team1
spec:
  ttlSecondsAfterFinished: 600
  template:
    spec:
      containers:
      - name: pull
        image: $BASE_IMAGE
        command: ["echo", "Image pulled successfully"]
      restartPolicy: Never
EOJOB
    else
        log_step "Base image pre-pull Job already exists"
    fi
fi

# ============================================================================
# PHASE 4: Deploy Agents
# ============================================================================
if [ "$SKIP_AGENTS" = "false" ]; then
    log_phase "PHASE 4: Build & Deploy Agents"

    # Ensure team1 namespace exists
    kubectl get ns team1 >/dev/null 2>&1 || kubectl create ns team1

    # ── Istio waypoint proxies (required for L7 traffic in ambient mode) ──
    # Namespaces with istio.io/use-waypoint label need a waypoint Gateway.
    # Without it, ztunnel resets all L7 (HTTP) connections.
    for NS in team1 team2; do
        if kubectl get ns "$NS" -o jsonpath='{.metadata.labels.istio\.io/use-waypoint}' 2>/dev/null | grep -q waypoint; then
            if ! kubectl get gateway waypoint -n "$NS" >/dev/null 2>&1; then
                log_step "Creating Istio waypoint for $NS"
                kubectl apply -f - <<EOWAYPOINT
apiVersion: gateway.networking.k8s.io/v1
kind: Gateway
metadata:
  name: waypoint
  namespace: $NS
  labels:
    istio.io/waypoint-for: all
spec:
  gatewayClassName: istio-waypoint
  listeners:
  - name: mesh
    port: 15008
    protocol: HBONE
    allowedRoutes:
      namespaces:
        from: Same
EOWAYPOINT
            fi
        fi
    done

    # ── LLM secret (idempotent) ─────────────────────────────────────
    # Source .env.maas early — we need the keys for both the secret and env patching.
    # Check REPO_ROOT, CWD, and git main worktree (worktrees have .env in parent).
    MAAS_SOURCED=false
    MAAS_FILE=""
    GIT_MAIN_WORKTREE="$(git rev-parse --path-format=absolute --git-common-dir 2>/dev/null | sed 's|/\.git$||' || echo "")"
    for candidate in "$REPO_ROOT/.env.maas" "$PWD/.env.maas" "$GIT_MAIN_WORKTREE/.env.maas"; do
        if [ -n "$candidate" ] && [ -f "$candidate" ]; then
            MAAS_FILE="$candidate"
            break
        fi
    done
    if [ -n "$MAAS_FILE" ]; then
        # shellcheck source=/dev/null
        source "$MAAS_FILE"
        MAAS_SOURCED=true
        log_step "Loaded LiteMaaS credentials from $(basename "$MAAS_FILE")"
    fi

    kubectl create secret generic litellm-virtual-keys -n team1 \
        --from-literal=api-key="${MAAS_LLAMA4_API_KEY:-PLACEHOLDER-no-llm-key-set}" \
        --dry-run=client -o yaml | kubectl apply -f - 2>&1 | grep -v "^Warning:"

    # ── Skills ConfigMap (idempotent) ───────────────────────────────
    kubectl create configmap kagenti-skills -n team1 \
        --from-literal=skills.json='{"version":"1.0","source":"kagenti/.claude/skills/","skills":[{"name":"review","type":"claude-code-skill"},{"name":"rca","type":"claude-code-skill"},{"name":"k8s:health","type":"claude-code-skill"},{"name":"k8s:pods","type":"claude-code-skill"},{"name":"k8s:logs","type":"claude-code-skill"},{"name":"tdd:kind","type":"claude-code-skill"},{"name":"tdd:hypershift","type":"claude-code-skill"},{"name":"github:pr-review","type":"claude-code-skill"},{"name":"security-review","type":"claude-code-skill"}]}' \
        --dry-run=client -o yaml | kubectl apply -f - 2>&1 | grep -v "^Warning:"

    # ── Platform-specific setup ─────────────────────────────────────
    if [ "$PLATFORM" = "kind" ]; then
        # PoC ONLY: Set webhook to Ignore so agents deploy without AuthBridge.
        log_warn "PoC: Setting webhook failurePolicy=Ignore (Kind only)"
        kubectl get mutatingwebhookconfiguration -o name 2>/dev/null | grep kagenti | while read -r webhook; do
            kubectl patch "$webhook" --type='json' \
                -p='[{"op":"replace","path":"/webhooks/0/failurePolicy","value":"Ignore"}]' 2>/dev/null || true
        done
    fi

    # Create dedicated SA for supervised agents (all platforms)
    kubectl create serviceaccount openshell-supervisor -n team1 --dry-run=client -o yaml | kubectl apply -f - 2>/dev/null || true

    if [ "$PLATFORM" = "ocp" ]; then
        # Gateway needs UID 1000 (anyuid)
        log_step "Granting SCCs for OpenShell agents..."
        oc adm policy add-scc-to-user anyuid -z openshell-gateway -n openshell-system 2>/dev/null || true
        # Supervised agent needs privileged (Landlock + mount --make-shared)
        oc adm policy add-scc-to-user privileged -z openshell-supervisor -n team1 2>/dev/null || true
    fi

    # ── Apply agent manifests FIRST ────────────────────────────────
    # Manifests use local image names (e.g., adk-agent:latest).
    # The build script will patch these to internal registry refs on OCP.
    AGENTS_DIR="deployments/openshell/agents"
    if [ -d "$AGENTS_DIR" ]; then
        for manifest in "$AGENTS_DIR"/*.yaml "$AGENTS_DIR"/*/deployment.yaml; do
            [ -f "$manifest" ] || continue
            log_step "Applying: $manifest"
            kubectl apply -f "$manifest" 2>&1 | grep -v "ensure CRDs" || true
        done
    fi

    # ── Build custom agent images (idempotent) ──────────────────────
    # On Kind: docker build + kind load.
    # On OCP: oc binary build + patch deployment image to internal registry.
    log_step "Building agent images..."
    PLATFORM="$PLATFORM" CLUSTER_NAME="$CLUSTER_NAME" AGENT_NS="team1" \
        ./.github/scripts/local-setup/openshell-build-agents.sh

    # ── Deploy LiteLLM model proxy (idempotent) ──────────────────────
    # LiteLLM provides: model aliasing (gpt-4o-mini → llama-scout-17b),
    # virtual key isolation (agent never sees real LiteMaaS key),
    # and OpenAI-compatible endpoint for all agents including OpenCode.
    LITELLM_PROXY_NAME="litellm-model-proxy"
    if [ "$MAAS_SOURCED" = "true" ]; then
        LITEMAAS_URL="${MAAS_LLAMA4_API_BASE:-https://litellm-prod.apps.maas.redhatworkshops.io/v1}"
        LITEMAAS_KEY="${MAAS_LLAMA4_API_KEY:-}"
        LITEMAAS_MODEL="${MAAS_LLAMA4_MODEL:-llama-scout-17b}"

        if true; then
            log_step "Creating LiteMaaS credentials secret..."
            kubectl create secret generic litemaas-credentials -n team1 \
                --from-literal=api-key="$LITEMAAS_KEY" \
                --dry-run=client -o yaml | kubectl apply -f -

            log_step "Deploying LiteLLM model proxy with model aliases..."
            # hosted_vllm/ provider avoids LiteLLM's OpenAI Responses API bridge
            # which doesn't work with non-OpenAI backends (LiteMaaS).
            # use_chat_completions_url_for_anthropic_messages routes /v1/messages
            # through chat completions instead of the Responses API.
            kubectl apply -f - <<EOLITELLM
apiVersion: v1
kind: ConfigMap
metadata:
  name: litellm-config
  namespace: team1
data:
  config.yaml: |
    litellm_settings:
      use_chat_completions_url_for_anthropic_messages: true
      drop_params: true
    model_list:
      - model_name: "gpt-4o-mini"
        litellm_params:
          model: "hosted_vllm/$LITEMAAS_MODEL"
          api_base: "$LITEMAAS_URL"
          api_key: "os.environ/LITEMAAS_API_KEY"
      - model_name: "gpt-4o"
        litellm_params:
          model: "hosted_vllm/$LITEMAAS_MODEL"
          api_base: "$LITEMAAS_URL"
          api_key: "os.environ/LITEMAAS_API_KEY"
      - model_name: "gpt-4"
        litellm_params:
          model: "hosted_vllm/$LITEMAAS_MODEL"
          api_base: "$LITEMAAS_URL"
          api_key: "os.environ/LITEMAAS_API_KEY"
      - model_name: "gpt-5-nano"
        litellm_params:
          model: "hosted_vllm/$LITEMAAS_MODEL"
          api_base: "$LITEMAAS_URL"
          api_key: "os.environ/LITEMAAS_API_KEY"
      - model_name: "gpt-5"
        litellm_params:
          model: "hosted_vllm/$LITEMAAS_MODEL"
          api_base: "$LITEMAAS_URL"
          api_key: "os.environ/LITEMAAS_API_KEY"
      - model_name: "gpt-5-mini"
        litellm_params:
          model: "hosted_vllm/$LITEMAAS_MODEL"
          api_base: "$LITEMAAS_URL"
          api_key: "os.environ/LITEMAAS_API_KEY"
      - model_name: "$LITEMAAS_MODEL"
        litellm_params:
          model: "hosted_vllm/$LITEMAAS_MODEL"
          api_base: "$LITEMAAS_URL"
          api_key: "os.environ/LITEMAAS_API_KEY"
      - model_name: "claude-sonnet-4-20250514"
        litellm_params:
          model: "hosted_vllm/$LITEMAAS_MODEL"
          api_base: "$LITEMAAS_URL"
          api_key: "os.environ/LITEMAAS_API_KEY"
      - model_name: "claude-haiku-4-20250414"
        litellm_params:
          model: "hosted_vllm/$LITEMAAS_MODEL"
          api_base: "$LITEMAAS_URL"
          api_key: "os.environ/LITEMAAS_API_KEY"
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: $LITELLM_PROXY_NAME
  namespace: team1
  labels:
    app.kubernetes.io/name: $LITELLM_PROXY_NAME
    app.kubernetes.io/part-of: kagenti
spec:
  replicas: 1
  selector:
    matchLabels:
      app.kubernetes.io/name: $LITELLM_PROXY_NAME
  template:
    metadata:
      labels:
        app.kubernetes.io/name: $LITELLM_PROXY_NAME
    spec:
      containers:
      - name: litellm
        image: ghcr.io/berriai/litellm:main-v1.83.10-stable
        args: ["--config", "/config/config.yaml", "--port", "4000"]
        ports:
        - containerPort: 4000
          name: http
        env:
        - name: LITEMAAS_API_KEY
          valueFrom:
            secretKeyRef:
              name: litemaas-credentials
              key: api-key
        resources:
          requests:
            cpu: 100m
            memory: 512Mi
          limits:
            cpu: 500m
            memory: 1Gi
        readinessProbe:
          tcpSocket:
            port: 4000
          initialDelaySeconds: 10
          periodSeconds: 5
        volumeMounts:
        - name: config
          mountPath: /config
      volumes:
      - name: config
        configMap:
          name: litellm-config
---
apiVersion: v1
kind: Service
metadata:
  name: $LITELLM_PROXY_NAME
  namespace: team1
  labels:
    app.kubernetes.io/name: $LITELLM_PROXY_NAME
spec:
  selector:
    app.kubernetes.io/name: $LITELLM_PROXY_NAME
  ports:
  - name: http
    port: 4000
    targetPort: 4000
EOLITELLM
            kubectl rollout status "deploy/$LITELLM_PROXY_NAME" -n team1 --timeout=120s 2>/dev/null || {
                log_warn "LiteLLM proxy rollout not complete"
            }
        fi

        # Patch agents to route through LiteLLM proxy
        LITELLM_URL="http://$LITELLM_PROXY_NAME.team1.svc:4000/v1"
        log_step "Patching agents to use LiteLLM proxy at $LITELLM_URL"

        kubectl set env deploy/claude-sdk-agent -n team1 \
            "ANTHROPIC_BASE_URL=$LITELLM_URL" \
            "ANTHROPIC_MODEL=$LITEMAAS_MODEL" 2>/dev/null || true
    else
        log_warn "No .env.maas — LLM tests will skip, no LiteLLM proxy deployed"
    fi

    # ── NemoClaw agents status ──────────────────────────────────────────
    # NemoClaw agents (hermes, openclaw) are deployed alongside other agents
    # via the manifest glob above. They use the OpenShell base image and will
    # CrashLoopBackOff until proper NemoClaw images are built.
    # TODO(nemoclaw-images): Build proper images — see deployment YAMLs for options.
    NEMOCLAW_HEALTHY=false
    if kubectl get deploy nemoclaw-hermes -n team1 >/dev/null 2>&1; then
        log_step "NemoClaw agents deployed (checking readiness)..."
        if kubectl rollout status deploy/nemoclaw-hermes -n team1 --timeout=60s 2>/dev/null && \
           kubectl rollout status deploy/nemoclaw-openclaw -n team1 --timeout=60s 2>/dev/null; then
            NEMOCLAW_HEALTHY=true
            log_step "NemoClaw agents are healthy — enabling NemoClaw tests"
        else
            log_warn "NemoClaw agents not ready (expected until proper images are built)"
            log_warn "Tests will skip NemoClaw-specific checks"
        fi
    fi

    # ── Wait for all rollouts to complete ─────────────────────────────
    # Brief delay to let K8s controller detect the env var changes
    # and start the rollout before we check status.
    sleep 5
    log_step "Waiting for agent rollouts to complete..."
    for deploy in $(kubectl get deploy -n team1 -l kagenti.io/type=agent -o name 2>/dev/null); do
        # NemoClaw agents may CrashLoopBackOff — don't block on them
        case "$deploy" in
            *nemoclaw*) kubectl rollout status "$deploy" -n team1 --timeout=60s 2>/dev/null || log_warn "$deploy not ready (NemoClaw image pending)" ;;
            *) kubectl rollout status "$deploy" -n team1 --timeout=180s 2>/dev/null || log_warn "$deploy rollout not complete" ;;
        esac
    done
    # Wait for all non-NemoClaw agent pods to be ready (CI needs more time)
    log_step "Waiting for non-NemoClaw agent pods to become ready..."
    for deploy in $(kubectl get deploy -n team1 -l kagenti.io/type=agent -o name 2>/dev/null); do
        case "$deploy" in
            *nemoclaw*) ;; # Skip — NemoClaw images may not be available
            *) kubectl wait --for=condition=available "$deploy" -n team1 --timeout=300s 2>/dev/null || \
                   log_warn "$deploy not available after 5 minutes" ;;
        esac
    done
    kubectl get pods -n team1 -l kagenti.io/type=agent
else
    log_phase "PHASE 4: Skipping Agent Deployment"
fi

# ============================================================================
# PHASE 5: Run E2E Tests
# ============================================================================
if [ "$SKIP_TEST" = "false" ]; then
    log_phase "PHASE 5: Run E2E Tests"

    log_step "Installing test dependencies..."
    ./.github/scripts/common/80-install-test-deps.sh 2>/dev/null || true

    log_step "Setting up test credentials..."
    ./.github/scripts/common/87-setup-test-credentials.sh 2>/dev/null || true

    export KAGENTI_CONFIG_FILE="deployments/envs/dev_values_openshell.yaml"

    # Enable LLM tests if .env.maas is available anywhere
    if [ "${MAAS_SOURCED:-false}" = "true" ]; then
        export OPENSHELL_LLM_AVAILABLE=true
        log_step "LiteMaaS available — LLM tests enabled"
    else
        # Agents phase may have been skipped — search for .env.maas independently
        _GIT_MAIN="$(git rev-parse --path-format=absolute --git-common-dir 2>/dev/null | sed 's|/\.git$||' || echo "")"
        for _c in "$REPO_ROOT/.env.maas" "$PWD/.env.maas" "$_GIT_MAIN/.env.maas"; do
            if [ -n "$_c" ] && [ -f "$_c" ]; then
                export OPENSHELL_LLM_AVAILABLE=true
                log_step "LiteMaaS available — LLM tests enabled"
                break
            fi
        done
    fi

    # Enable NemoClaw tests if agents are healthy
    if [ "${NEMOCLAW_HEALTHY:-false}" = "true" ]; then
        export OPENSHELL_NEMOCLAW_ENABLED=true
        log_step "NemoClaw tests enabled"
    fi

    TEST_DIR="kagenti/tests/e2e/openshell"
    if [ -d "$TEST_DIR" ]; then
        log_step "Running OpenShell E2E tests..."
        uv run pytest "$TEST_DIR" -v --timeout=300
    else
        log_step "No tests at $TEST_DIR. Skipping."
    fi
else
    log_phase "PHASE 5: Skipping E2E Tests"
fi

# ============================================================================
# PHASE 6: Destroy Cluster
# ============================================================================
if [ "$SKIP_DESTROY" = "false" ]; then
    if [ "$PLATFORM" = "kind" ]; then
        log_phase "PHASE 6: Destroy Kind Cluster"
        CLUSTER_NAME="$CLUSTER_NAME" ./.github/scripts/kind/destroy-cluster.sh
    else
        log_phase "PHASE 6: Destroy HyperShift Cluster"
        export KUBECONFIG="${MGMT_KUBECONFIG:-$HOME/.kube/kagenti-team-mgmt.kubeconfig}"
        ./.github/scripts/hypershift/destroy-cluster.sh "$CLUSTER_SUFFIX"
    fi
else
    log_phase "PHASE 6: Skipping Cluster Destruction"
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
echo -e "${GREEN}┃${NC} OpenShell PoC full test completed! (platform: $PLATFORM)"
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""
