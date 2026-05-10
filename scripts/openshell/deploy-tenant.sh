#!/usr/bin/env bash
# ============================================================================
# OPENSHELL PER-TENANT DEPLOYMENT
# ============================================================================
# Deploys one tenant's OpenShell gateway stack using the charts/openshell/
# Helm chart, with auto-detection of platform (Kind vs OCP).
#
# Usage:
#   scripts/openshell/deploy-tenant.sh <team>
#   scripts/openshell/deploy-tenant.sh team1
#   scripts/openshell/deploy-tenant.sh team2 --dry-run
#   scripts/openshell/deploy-tenant.sh --help
#
# Prerequisites: helm, kubectl, Keycloak running, cert-manager installed,
#                shared infra deployed (deploy-shared.sh)
# ============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

# ── Defaults ────────────────────────────────────────────────────────────────
KEYCLOAK_NS="${KEYCLOAK_NS:-keycloak}"
CHART_DIR="$REPO_ROOT/charts/openshell"
HELM_RELEASE_PREFIX="openshell"
KIND_DOMAIN="localtest.me"
KIND_TLS_NODEPORT=30443
IMAGE_TAG="${OPENSHELL_IMAGE_TAG:-}"
DRY_RUN=false
TIMEOUT=900
DEPLOY_AGENTS=false
EXTRA_HELM_SETS=()  # Additional --set arguments

# ── Colors & logging ────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'; NC='\033[0m'
log_info()    { echo -e "${BLUE}→${NC} $1"; }
log_success() { echo -e "${GREEN}✓${NC} $1"; }
log_warn()    { echo -e "${YELLOW}⚠${NC} $1"; }
log_error()   { echo -e "${RED}✗${NC} $1"; }

run_cmd() {
  if $DRY_RUN; then echo "  [dry-run] $*"; else "$@"; fi
}

usage() {
  cat <<EOF
Usage: $(basename "$0") <team> [OPTIONS]

Deploy a tenant's OpenShell gateway stack via Helm (idempotent).

Arguments:
  team                  Tenant name (e.g., team1, team2)

Options:
  --help               Show this help message
  --dry-run            Print helm commands without executing
  --chart-dir <path>   Helm chart directory (default: $CHART_DIR)
  --keycloak-ns <ns>   Keycloak namespace (default: keycloak)
  --image-tag <tag>    Image tag for all containers (default: latest)
  --set <key=val>      Extra helm --set values (repeatable)
  --timeout <secs>     Timeout for wait operations (default: 120)
  --agents             Also deploy agent manifests + platform setup for this tenant
EOF
  exit 0
}

# ── Argument parsing ────────────────────────────────────────────────────────
TENANT=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --help)          usage ;;
    --dry-run)       DRY_RUN=true; shift ;;
    --chart-dir)     CHART_DIR="$2"; shift 2 ;;
    --keycloak-ns)   KEYCLOAK_NS="$2"; shift 2 ;;
    --image-tag)     IMAGE_TAG="$2"; shift 2 ;;
    --set)           EXTRA_HELM_SETS+=("$2"); shift 2 ;;
    --timeout)       TIMEOUT="$2"; shift 2 ;;
    --agents)        DEPLOY_AGENTS=true; shift ;;
    -*)
      log_error "Unknown option: $1"
      usage
      ;;
    *)
      if [[ -z "$TENANT" ]]; then
        TENANT="$1"; shift
      else
        log_error "Unexpected argument: $1"
        usage
      fi
      ;;
  esac
done

if [[ -z "$TENANT" ]]; then
  log_error "Tenant name is required. Usage: $(basename "$0") <team> [OPTIONS]"
  exit 1
fi

# ── Helper: detect OpenShift ────────────────────────────────────────────────
is_openshift() {
  kubectl get clusterversion &>/dev/null
}

# ── Helper: get OpenShift base domain ───────────────────────────────────────
get_ocp_base_domain() {
  kubectl get ingresses.config.openshift.io cluster -o jsonpath='{.spec.domain}' 2>/dev/null
}

# ── Helper: discover Keycloak issuer URL ────────────────────────────────────
get_keycloak_issuer() {
  local kc_svc kc_url
  if is_openshift; then
    kc_url=$(kubectl get route keycloak -n "$KEYCLOAK_NS" -o jsonpath='{.spec.host}' 2>/dev/null || echo "")
    if [[ -n "$kc_url" ]]; then
      echo "https://$kc_url/realms/openshell"
      return
    fi
  fi
  # Kind: Keycloak advertises http://keycloak.localtest.me:8080 as its issuer.
  # The gateway must use this URL so issuer validation passes. We resolve
  # in-cluster connectivity via hostAliases (see keycloakClusterIP helm value).
  echo "http://keycloak.${KIND_DOMAIN}:8080/realms/openshell"
}

# ── Helper: generate ingress hostname ───────────────────────────────────────
get_ingress_host() {
  if is_openshift; then
    local base_domain
    base_domain=$(get_ocp_base_domain)
    echo "openshell-${TENANT}.${base_domain}"
  else
    echo "openshell-${TENANT}.${KIND_DOMAIN}"
  fi
}

# ── Helper: determine ingress type ──────────────────────────────────────────
get_ingress_type() {
  if is_openshift; then
    echo "route"
  else
    echo "istio"
  fi
}

# ============================================================================
# Main
# ============================================================================
RELEASE_NAME="${HELM_RELEASE_PREFIX}-${TENANT}"
INGRESS_TYPE=$(get_ingress_type)
INGRESS_HOST=$(get_ingress_host)
OIDC_ISSUER=$(get_keycloak_issuer)

# Kind: resolve Keycloak ClusterIP so we can inject hostAliases into the pod
# (localtest.me resolves to 127.0.0.1 which is loopback inside the pod)
KEYCLOAK_CLUSTER_IP=""
if ! is_openshift; then
  KEYCLOAK_CLUSTER_IP=$(kubectl get svc keycloak-service -n "$KEYCLOAK_NS" \
    -o jsonpath='{.spec.clusterIP}' 2>/dev/null || echo "")
  if [[ -n "$KEYCLOAK_CLUSTER_IP" ]]; then
    EXTRA_HELM_SETS+=("keycloakClusterIP=$KEYCLOAK_CLUSTER_IP")
  fi
else
  # OpenShift: build a combined CA bundle (system CAs + ingress CA) so the
  # gateway can verify TLS to the Keycloak route (edge-terminated).
  log_info "Creating combined trusted CA bundle (system + ingress CA)..."
  COMBINED_CA_CM="openshell-trusted-ca"
  (
    kubectl get configmap config-trusted-cabundle -n "$TENANT" -o jsonpath='{.data.ca-bundle\.crt}' 2>/dev/null
    echo
    kubectl get secret router-ca -n openshift-ingress-operator -o jsonpath='{.data.tls\.crt}' 2>/dev/null | base64 -d
  ) | kubectl create configmap "$COMBINED_CA_CM" -n "$TENANT" \
        --from-file=ca-bundle.crt=/dev/stdin --dry-run=client -o yaml | kubectl apply -f - >/dev/null
  EXTRA_HELM_SETS+=("trustedCABundle=$COMBINED_CA_CM")
fi

# Override image tags only when explicitly requested (otherwise use values.yaml defaults)
if [[ -n "$IMAGE_TAG" ]]; then
  EXTRA_HELM_SETS+=("images.gateway.tag=$IMAGE_TAG")
  EXTRA_HELM_SETS+=("images.computeDriver.tag=$IMAGE_TAG")
  EXTRA_HELM_SETS+=("images.credentialsDriver.tag=$IMAGE_TAG")
fi

echo ""
echo "╔════════════════════════════════════════════════════════════════╗"
echo "║  OpenShell Tenant Deployment                                 ║"
echo "╚════════════════════════════════════════════════════════════════╝"
echo ""
echo "  Tenant:         $TENANT"
echo "  Release:        $RELEASE_NAME"
echo "  Namespace:      $TENANT"
echo "  Ingress type:   $INGRESS_TYPE"
echo "  Ingress host:   $INGRESS_HOST"
echo "  OIDC issuer:    $OIDC_ISSUER"
echo "  Image tag:      ${IMAGE_TAG:-(from values.yaml)}"
echo "  Chart:          $CHART_DIR"
echo "  Dry run:        $DRY_RUN"
echo ""

# ── Step 1: Create namespace with labels ────────────────────────────────────
log_info "Step 1: Namespace $TENANT"

if kubectl get namespace "$TENANT" &>/dev/null; then
  log_success "Namespace $TENANT already exists"
else
  log_info "Creating namespace $TENANT..."
  if ! $DRY_RUN; then
    kubectl create namespace "$TENANT"
  else
    echo "  [dry-run] kubectl create namespace $TENANT"
  fi
fi

if ! $DRY_RUN; then
  kubectl label namespace "$TENANT" \
    shared-gateway-access=true \
    openshell.ai/tenant="$TENANT" \
    --overwrite
fi
echo ""

# ── Step 2: Helm install/upgrade ────────────────────────────────────────────
log_info "Step 2: Helm install/upgrade $RELEASE_NAME"

HELM_ARGS=(
  upgrade "$RELEASE_NAME" "$CHART_DIR"
  --install
  --namespace "$TENANT"
  --set "tenant=$TENANT"
  --set "oidc.issuer=$OIDC_ISSUER"
  --set "oidc.audience=$TENANT"
  --set "driver.namespace=$TENANT"
  --set "ingress.type=$INGRESS_TYPE"
  --set "ingress.host=$INGRESS_HOST"
  --wait
  --timeout "${TIMEOUT}s"
)

for extra in "${EXTRA_HELM_SETS[@]}"; do
  HELM_ARGS+=(--set "$extra")
done

if $DRY_RUN; then
  echo "  [dry-run] helm ${HELM_ARGS[*]}"
else
  helm "${HELM_ARGS[@]}"
fi
echo ""

# ── Step 3: Wait for certificates ──────────────────────────────────────────
log_info "Step 3: Waiting for cert-manager certificates"

if $DRY_RUN; then
  echo "  [dry-run] kubectl wait --for=condition=Ready certificate -n $TENANT --all --timeout=${TIMEOUT}s"
else
  if kubectl get certificate -n "$TENANT" --no-headers 2>/dev/null | grep -q .; then
    kubectl wait --for=condition=Ready certificate --all \
      -n "$TENANT" --timeout="${TIMEOUT}s"
    log_success "All certificates ready"
  else
    log_warn "No certificates found in namespace $TENANT (may be handled by Helm --wait)"
  fi
fi
echo ""

# ── Step 4: Wait for gateway pod ────────────────────────────────────────────
log_info "Step 4: Waiting for gateway pod rollout"

if $DRY_RUN; then
  echo "  [dry-run] kubectl rollout status statefulset/openshell-server -n $TENANT --timeout=${TIMEOUT}s"
else
  kubectl rollout status statefulset/openshell-server \
    -n "$TENANT" --timeout="${TIMEOUT}s"
  log_success "Gateway pod ready"
fi
echo ""

# ── Step 5: Deploy agents (optional) ────────────────────────────────────────
if $DEPLOY_AGENTS; then
  log_info "Step 5: Deploying agents for tenant $TENANT"

  # Platform-specific setup
  if is_openshift; then
    log_info "Granting SCCs for OpenShell agents..."
    run_cmd oc adm policy add-scc-to-user anyuid -z openshell-gateway -n openshell-system 2>/dev/null || true
    run_cmd oc adm policy add-scc-to-user privileged -z openshell-supervisor -n "$TENANT" 2>/dev/null || true
  else
    # Kind: Set webhook to Ignore so agents deploy without AuthBridge
    log_warn "PoC: Setting webhook failurePolicy=Ignore (Kind only)"
    kubectl get mutatingwebhookconfiguration -o name 2>/dev/null | grep kagenti | while read -r webhook; do
      kubectl patch "$webhook" --type='json' \
        -p='[{"op":"replace","path":"/webhooks/0/failurePolicy","value":"Ignore"}]' 2>/dev/null || true
    done
  fi

  # Create supervisor ServiceAccount
  run_cmd kubectl create serviceaccount openshell-supervisor -n "$TENANT" \
    --dry-run=client -o yaml | kubectl apply -f - 2>/dev/null || true

  # Create kagenti-skills ConfigMap
  run_cmd kubectl create configmap kagenti-skills -n "$TENANT" \
    --from-literal=skills.json='{"version":"1.0","source":"kagenti/.claude/skills/","skills":[{"name":"review","type":"claude-code-skill"},{"name":"rca","type":"claude-code-skill"},{"name":"k8s:health","type":"claude-code-skill"},{"name":"k8s:pods","type":"claude-code-skill"},{"name":"k8s:logs","type":"claude-code-skill"},{"name":"tdd:kind","type":"claude-code-skill"},{"name":"tdd:hypershift","type":"claude-code-skill"},{"name":"github:pr-review","type":"claude-code-skill"},{"name":"security-review","type":"claude-code-skill"}]}' \
    --dry-run=client -o yaml | kubectl apply -f - 2>&1 | grep -v "^Warning:" || true

  # Apply agent manifests and policy ConfigMaps
  AGENTS_DIR="$REPO_ROOT/deployments/openshell/agents"
  if [ -d "$AGENTS_DIR" ]; then
    for agent_dir in "$AGENTS_DIR"/*/; do
      agent_name=$(basename "$agent_dir")
      manifest="$agent_dir/deployment.yaml"
      [ -f "$manifest" ] || continue
      log_info "Applying: $agent_name"
      run_cmd kubectl apply -f "$manifest" 2>&1 | grep -v "ensure CRDs" || true

      # Create/update policy ConfigMap and restart agent to pick up changes
      if [[ -f "$agent_dir/policy-data.yaml" ]]; then
        cm_args=("--from-file=policy.yaml=$agent_dir/policy-data.yaml")
        if [[ -f "$agent_dir/sandbox-policy.rego" ]]; then
          cm_args+=("--from-file=sandbox-policy.rego=$agent_dir/sandbox-policy.rego")
        fi
        kubectl create configmap "${agent_name}-policy" -n "$TENANT" "${cm_args[@]}" \
            --dry-run=client -o yaml | kubectl apply -f - 2>&1 | grep -v "^Warning:" || true
        kubectl rollout restart "deploy/$agent_name" -n "$TENANT" 2>/dev/null || true
      fi
    done
  fi

  # Patch agents to use LiteLLM proxy (if available)
  LITELLM_PROXY_NAME="litellm-model-proxy"
  if kubectl get svc "$LITELLM_PROXY_NAME" -n "$TENANT" &>/dev/null; then
    LITELLM_URL="http://$LITELLM_PROXY_NAME.$TENANT.svc:4000/v1"
    LITEMAAS_MODEL="${MAAS_LLAMA4_MODEL:-llama-scout-17b}"
    log_info "Patching agents to use LiteLLM proxy at $LITELLM_URL"

    kubectl set env deploy/claude-sdk-agent -n "$TENANT" \
      "ANTHROPIC_BASE_URL=$LITELLM_URL" \
      "ANTHROPIC_MODEL=$LITEMAAS_MODEL" 2>/dev/null || true
  fi

  # Wait for agent rollouts
  if ! $DRY_RUN; then
    sleep 5
    log_info "Waiting for agent rollouts..."
    for deploy in $(kubectl get deploy -n "$TENANT" -l kagenti.io/type=agent -o name 2>/dev/null); do
      case "$deploy" in
        *nemoclaw*) kubectl rollout status "$deploy" -n "$TENANT" --timeout=60s 2>/dev/null || \
                      log_warn "$deploy not ready (NemoClaw image pending)" ;;
        *) kubectl rollout status "$deploy" -n "$TENANT" --timeout=180s 2>/dev/null || \
               log_warn "$deploy rollout not complete" ;;
      esac
    done
  fi

  log_success "Agents deployed for tenant $TENANT"
  echo ""
fi

# ── Summary ─────────────────────────────────────────────────────────────────
echo "╔════════════════════════════════════════════════════════════════╗"
echo "║  Tenant $TENANT — Deployment Complete                        ║"
echo "╚════════════════════════════════════════════════════════════════╝"
echo ""
if ! $DRY_RUN; then
  echo "  Verify:"
  echo "    kubectl get pods -n $TENANT"
  echo "    kubectl get certificate -n $TENANT"
  if [[ "$INGRESS_TYPE" == "istio" ]]; then
    echo "    kubectl get tlsroute -n $TENANT"
  else
    echo "    kubectl get route -n $TENANT"
  fi
  echo ""
  echo "  Connect:"
  if [[ "$INGRESS_TYPE" == "istio" ]]; then
    echo "    openshell gateway set --url https://${INGRESS_HOST}:${KIND_TLS_NODEPORT}"
  else
    echo "    openshell gateway set --url https://${INGRESS_HOST}"
  fi
  echo "    openshell login"
  echo ""
fi
