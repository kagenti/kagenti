#!/usr/bin/env bash
# ============================================================================
# KAGENTI PLATFORM SETUP
# ============================================================================
# Installs the Kagenti stack (SPIRE, cert-manager, Keycloak, operator, webhook,
# MCP Gateway) on an OpenShift cluster. Run this BEFORE setup.sh --with-a2a.
# Prometheus/Kiali are disabled. UI/backend installed by default (use --skip-ui to disable).
# Shipwright disabled by default.
#
# MLflow: provisions an MLflow instance via RHOAI's DSC mlflowoperator
# and wires the OTEL collector to export traces to it.
#
# Usage:
#   ./scripts/ocp/setup-kagenti.sh                              # Auto-clones kagenti main to ~/.cache/kagenti
#   ./scripts/ocp/setup-kagenti.sh --kagenti-repo /path/to/kagenti  # Use local clone
#   ./scripts/ocp/setup-kagenti.sh --kagenti-repo https://github.com/org/kagenti.git  # Clone from URL
#   ./scripts/ocp/setup-kagenti.sh --realm nerc                 # Custom Keycloak realm (default: kagenti)
#   ./scripts/ocp/setup-kagenti.sh --skip-ovn-patch             # Skip OVN gateway patch
#   ./scripts/ocp/setup-kagenti.sh --skip-mcp-gateway           # Skip MCP Gateway install
#   ./scripts/ocp/setup-kagenti.sh --skip-mlflow                # Disable Kagenti-Operator <-> MLflow integration
#   ./scripts/ocp/setup-kagenti.sh --operator-repo ~/kagenti-operator  # Use local operator chart
#   ./scripts/ocp/setup-kagenti.sh --operator-image quay.io/user/kagenti-operator:dev  # Custom operator image
#   ./scripts/ocp/setup-kagenti.sh --operator-repo ~/kagenti-operator --operator-image quay.io/user/op:dev  # Both
#
# Prerequisites:
#   - oc / kubectl with cluster-admin
#   - helm >= 3.18.0 < 4
#
# Tested on: OCP 4.19+ (ROSA)
#
# Before running:
#   - Add agent namespaces to the agentNamespaces list in charts/kagenti/values.yaml (defaults: team1, team2)
# ============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

# Defaults
KAGENTI_REPO="${KAGENTI_REPO:-}"
KAGENTI_CACHE_DIR="${HOME}/.cache/kagenti"
KAGENTI_GITHUB_URL="https://github.com/kagenti/kagenti.git"
KC_REALM="${KEYCLOAK_REALM:-kagenti}"
KC_NAMESPACE="${KEYCLOAK_NAMESPACE:-keycloak}"
SKIP_OVN_PATCH=false
SKIP_MCP_GATEWAY=false
SKIP_UI=false
SKIP_MLFLOW=false
SHOW_SECRETS=false
MCP_GATEWAY_VERSION="0.5.1"
OPERATOR_REPO=""
OPERATOR_IMAGE=""
DRY_RUN=false
MLFLOW_NAMESPACE="redhat-ods-applications"
MLFLOW_INSTANCE_NAME="mlflow"
MLFLOW_TRACES_ENDPOINT=""

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log_info()    { echo -e "${BLUE}→${NC} $1"; }
log_success() { echo -e "${GREEN}✓${NC} $1"; }
log_warn()    { echo -e "${YELLOW}⚠${NC} $1"; }
log_error()   { echo -e "${RED}✗${NC} $1"; }

# Parse arguments
while [[ $# -gt 0 ]]; do
  case "$1" in
    --kagenti-repo)       KAGENTI_REPO="$2"; shift 2 ;;
    --realm)              KC_REALM="$2"; shift 2 ;;
    --keycloak-namespace) KC_NAMESPACE="$2"; shift 2 ;;
    --skip-ovn-patch)     SKIP_OVN_PATCH=true; shift ;;
    --skip-mcp-gateway)   SKIP_MCP_GATEWAY=true; shift ;;
    --skip-ui)            SKIP_UI=true; shift ;;
    --skip-mlflow)        SKIP_MLFLOW=true; shift ;;
    --show-secrets)       SHOW_SECRETS=true; shift ;;
    --operator-repo)      OPERATOR_REPO="$2"; shift 2 ;;
    --operator-image)     OPERATOR_IMAGE="$2"; shift 2 ;;
    --mcp-gateway-version) MCP_GATEWAY_VERSION="$2"; shift 2 ;;
    --dry-run)            DRY_RUN=true; shift ;;
    -h|--help)
      echo "Usage: $0 [OPTIONS]"
      echo ""
      echo "Options:"
      echo "  --kagenti-repo PATH|URL   Local path or GitHub URL to kagenti repo (default: clone main to ~/.cache/kagenti)"
      echo "  --realm REALM             Keycloak realm (default: kagenti, or \$KEYCLOAK_REALM)"
      echo "  --keycloak-namespace NS   Keycloak namespace (default: keycloak, or \$KEYCLOAK_NAMESPACE)"
      echo "  --skip-ovn-patch          Skip OVN gateway routing patch"
      echo "  --skip-mcp-gateway        Skip MCP Gateway installation"
      echo "  --skip-ui                 Skip Kagenti UI and backend installation"
      echo "  --skip-mlflow             Skip MLflow integration (OTel traces + operator auto-config)"
      echo "  --show-secrets            Print Keycloak admin credentials to stdout (omitted by default for CI safety)"
      echo "  --operator-repo PATH      Local path to kagenti-operator repo (overrides Chart.yaml dependency)"
      echo "  --operator-image IMG:TAG  Custom operator image (e.g. quay.io/user/kagenti-operator:dev)"
      echo "  --mcp-gateway-version VER MCP Gateway chart version (default: $MCP_GATEWAY_VERSION)"
      echo "  --dry-run                 Show commands without executing"
      echo "  -h, --help                Show this help"
      exit 0
      ;;
    *) log_error "Unknown option: $1"; exit 1 ;;
  esac
done

run_cmd() {
  if $DRY_RUN; then
    echo "  [dry-run] $*"
  else
    "$@"
  fi
}

# ============================================================================
# Pre-flight checks
# ============================================================================
START_SECONDS=$SECONDS

echo ""
echo "============================================"
echo "  Kagenti Platform Setup"
echo "============================================"
echo ""

# Check for kubectl/oc
if command -v oc &>/dev/null; then
  KUBECTL=oc
elif command -v kubectl &>/dev/null; then
  KUBECTL=kubectl
else
  log_error "Neither oc nor kubectl found in PATH"
  exit 1
fi

# Check cluster access
if ! $KUBECTL cluster-info &>/dev/null; then
  log_error "Cannot connect to cluster. Run 'oc login' first."
  exit 1
fi
log_success "Connected to cluster"

# Check for stale APIServices that block namespace deletion.
# On some clusters (e.g. with removed kubevirt), stale APIServices cause namespace
# finalizers to hang on API discovery failures. Warn so the user can clean them up.
_stale_apis=$($KUBECTL get apiservices -o json 2>/dev/null | \
  python3 -c "
import sys, json
data = json.load(sys.stdin)
stale = []
for item in data.get('items', []):
    for cond in item.get('status', {}).get('conditions', []):
        if cond.get('type') == 'Available' and cond.get('status') != 'True':
            stale.append(item['metadata']['name'])
print('\n'.join(stale))
" 2>/dev/null || echo "")
if [ -n "$_stale_apis" ]; then
  log_warn "Stale APIServices detected (can cause namespace deletion hangs):"
  echo "$_stale_apis" | while read -r api; do echo "    $api"; done
  log_warn "Consider removing them: oc delete apiservice <name>"
fi

# Check helm
if ! command -v helm &>/dev/null; then
  log_error "helm not found in PATH. Install helm >= 3.18.0"
  exit 1
fi
log_success "helm found: $(helm version --short)"

# Check python3
if ! command -v python3 &>/dev/null; then
  log_error "python3 not found in PATH. Install python3 >= 3.8"
  exit 1
fi
log_success "python3 found: $(python3 --version)"

# Resolve kagenti repo: local path, GitHub URL, or auto-clone from main
_clone_kagenti() {
  local url="$1" dest="$2"
  log_info "Cloning kagenti from ${url} → ${dest}..."
  if $DRY_RUN; then
    echo "  [dry-run] rm -rf \"$dest\""
    echo "  [dry-run] git clone --depth=1 \"$url\" \"$dest\""
    return 0
  fi
  rm -rf "$dest"
  if ! git clone --depth=1 "$url" "$dest" 2>&1; then
    log_error "Failed to clone kagenti from $url"
    exit 1
  fi
  log_success "Cloned kagenti (main)"
}

KAGENTI_SOURCE=""
if [ -z "$KAGENTI_REPO" ]; then
  # No --kagenti-repo given: always clone fresh from upstream main
  KAGENTI_SOURCE="$KAGENTI_GITHUB_URL"
  _clone_kagenti "$KAGENTI_GITHUB_URL" "$KAGENTI_CACHE_DIR"
  KAGENTI_REPO="$KAGENTI_CACHE_DIR"
elif [[ "$KAGENTI_REPO" == http://* ]] || [[ "$KAGENTI_REPO" == https://* ]] || [[ "$KAGENTI_REPO" == git@* ]]; then
  # GitHub/git URL: clone into cache
  KAGENTI_SOURCE="$KAGENTI_REPO"
  _clone_kagenti "$KAGENTI_REPO" "$KAGENTI_CACHE_DIR"
  KAGENTI_REPO="$KAGENTI_CACHE_DIR"
else
  # Local path provided — use as-is
  KAGENTI_SOURCE="$KAGENTI_REPO (local)"
fi

if [ ! -d "$KAGENTI_REPO/charts/kagenti-deps" ] || [ ! -d "$KAGENTI_REPO/charts/kagenti" ]; then
  log_error "Invalid kagenti repo: $KAGENTI_REPO (missing charts/kagenti-deps or charts/kagenti)"
  exit 1
fi
log_success "Kagenti repo: $KAGENTI_SOURCE"

echo ""

# ============================================================================
# Step 1: OVN Gateway Patch
# ============================================================================
log_info "Step 1: OVN Gateway Patch"

if $SKIP_OVN_PATCH; then
  log_info "Skipped (--skip-ovn-patch)"
else
  # Check if this is an OVNKubernetes cluster
  NETWORK_TYPE=$($KUBECTL get network.operator.openshift.io cluster -o jsonpath='{.spec.defaultNetwork.type}' 2>/dev/null || echo "unknown")
  if [ "$NETWORK_TYPE" = "OVNKubernetes" ]; then
    log_info "OVNKubernetes detected — applying routingViaHost patch"
    run_cmd $KUBECTL patch network.operator.openshift.io cluster --type=merge \
      -p '{"spec":{"defaultNetwork":{"ovnKubernetesConfig":{"gatewayConfig":{"routingViaHost":true}}}}}'
    log_success "OVN gateway patch applied"
  else
    log_info "Network type: $NETWORK_TYPE — skipping OVN patch"
  fi
fi
echo ""

# ============================================================================
# Step 2: Detect Trust Domain
# ============================================================================
log_info "Step 2: Detect trust domain"

DOMAIN="apps.$($KUBECTL get dns cluster -o jsonpath='{ .spec.baseDomain }' 2>/dev/null || echo "")"
if [ "$DOMAIN" = "apps." ] || [ -z "$DOMAIN" ]; then
  log_warn "Could not auto-detect cluster domain"
  read -p "  Enter trust domain (e.g. apps.example.com): " DOMAIN
fi
export DOMAIN
log_success "Trust domain: $DOMAIN"
echo ""

# ============================================================================
# Step 2.5: MLflow via RHOAI DSC
# ============================================================================
#
# Verifies that RHOAI's DataScienceCluster has the mlflowoperator managed,
# creates an MLflow CR if one does not already exist, then waits for the
# Service and pod to be ready. Sets MLFLOW_TRACES_ENDPOINT for use by the
# kagenti-deps Helm install that follows.

_mlflow_check_dsc() {
  log_info "Checking RHOAI DSC mlflowoperator..."
  local state
  state=$($KUBECTL get datasciencecluster default-dsc \
    -o jsonpath='{.spec.components.mlflowoperator.managementState}' 2>/dev/null || echo "")
  if [ "$state" != "Managed" ]; then
    log_error "RHOAI DSC mlflowoperator is not Managed (got: '${state:-<not set>}')"
    log_error "Patch your DataScienceCluster:"
    log_error "  kubectl patch datasciencecluster default-dsc --type=merge \\"
    log_error "    -p '{\"spec\":{\"components\":{\"mlflowoperator\":{\"managementState\":\"Managed\"}}}}'"
    exit 1
  fi
  log_success "RHOAI DSC mlflowoperator is Managed"
}

_mlflow_create_cr() {
  if $KUBECTL get mlflow "$MLFLOW_INSTANCE_NAME" -n "$MLFLOW_NAMESPACE" &>/dev/null; then
    log_info "MLflow CR '$MLFLOW_INSTANCE_NAME' already exists in $MLFLOW_NAMESPACE — skipping creation"
    return 0
  fi
  log_info "Creating MLflow CR '$MLFLOW_INSTANCE_NAME' in $MLFLOW_NAMESPACE..."
  if $DRY_RUN; then
    echo "  [dry-run] kubectl apply MLflow CR $MLFLOW_INSTANCE_NAME -n $MLFLOW_NAMESPACE"
    return 0
  fi
  $KUBECTL apply -f - <<EOF
apiVersion: mlflow.opendatahub.io/v1
kind: MLflow
metadata:
  name: ${MLFLOW_INSTANCE_NAME}
  namespace: ${MLFLOW_NAMESPACE}
spec:
  storage:
    accessModes:
      - ReadWriteOnce
    resources:
      requests:
        storage: 10Gi
  backendStoreUri: "sqlite:////mlflow/mlflow.db"
  artifactsDestination: "file:///mlflow/artifacts"
  serveArtifacts: true
EOF
  log_success "MLflow CR created"
}

_mlflow_wait_ready() {
  if $DRY_RUN; then
    MLFLOW_TRACES_ENDPOINT="https://${MLFLOW_INSTANCE_NAME}.${MLFLOW_NAMESPACE}.svc.cluster.local:8443/v1/traces"
    echo "  [dry-run] would wait for MLflow Service and pod in $MLFLOW_NAMESPACE"
    return 0
  fi

  log_info "Waiting for MLflow Service to appear in $MLFLOW_NAMESPACE..."
  local tries=0
  while ! $KUBECTL get service "$MLFLOW_INSTANCE_NAME" -n "$MLFLOW_NAMESPACE" &>/dev/null; do
    tries=$((tries + 1))
    if [ $tries -ge 60 ]; then
      log_error "MLflow Service '$MLFLOW_INSTANCE_NAME' not found in $MLFLOW_NAMESPACE after 5m"
      log_error "Check that the mlflowoperator reconciled the CR: kubectl get mlflow -n $MLFLOW_NAMESPACE"
      exit 1
    fi
    sleep 5
  done
  log_success "MLflow Service found"

  MLFLOW_TRACES_ENDPOINT="https://${MLFLOW_INSTANCE_NAME}.${MLFLOW_NAMESPACE}.svc.cluster.local:8443/v1/traces"
  log_success "MLflow traces endpoint: $MLFLOW_TRACES_ENDPOINT"

  log_info "Waiting for MLflow pod to be Running..."
  tries=0
  while ! $KUBECTL get pods -n "$MLFLOW_NAMESPACE" \
      -l "app=${MLFLOW_INSTANCE_NAME}" \
      -o jsonpath='{.items[0].status.phase}' 2>/dev/null | grep -q "^Running$"; do
    tries=$((tries + 1))
    if [ $tries -ge 60 ]; then
      log_warn "MLflow pod not Running after 5m — proceeding anyway (OTEL will retry)"
      return 0
    fi
    sleep 5
  done

  # Verify the Service has at least one ready endpoint (pod is actually serving)
  tries=0
  while ! $KUBECTL get endpoints "$MLFLOW_INSTANCE_NAME" -n "$MLFLOW_NAMESPACE" \
      -o jsonpath='{.subsets[0].addresses[0].ip}' 2>/dev/null | grep -q .; do
    tries=$((tries + 1))
    if [ $tries -ge 12 ]; then
      log_warn "MLflow Service has no ready endpoints after 1m — proceeding anyway"
      return 0
    fi
    sleep 5
  done
  log_success "MLflow is ready"
}

_mlflow_grant_otel_rbac() {
  # The RHOAI MLflow operator creates the mlflow-operator-mlflow-integration ClusterRole
  # with pseudo-resources (mlflow.kubeflow.org/*) checked via SubjectAccessReview.
  # The otel-collector SA needs a RoleBinding in each agent namespace (workspace)
  # so the collector can send traces with the correct workspace context.
  local cr_name="mlflow-operator-mlflow-integration"
  if ! $KUBECTL get clusterrole "$cr_name" &>/dev/null; then
    log_error "ClusterRole '$cr_name' not found — is the RHOAI MLflow operator running?"
    log_error "The mlflowoperator should create this ClusterRole automatically."
    return 1
  fi
  log_success "ClusterRole $cr_name exists"

  local agent_ns
  agent_ns=$(python3 -c "
import yaml, sys
with open('$KAGENTI_REPO/charts/kagenti/values.yaml') as f:
    v = yaml.safe_load(f)
for ns in v.get('agentNamespaces', ['team1', 'team2']):
    print(ns)
" 2>/dev/null || echo -e "team1\nteam2")

  while IFS= read -r ns; do
    [ -z "$ns" ] && continue
    log_info "Creating MLflow RBAC for otel-collector in $ns..."
    if $DRY_RUN; then
      echo "  [dry-run] kubectl create rolebinding otel-collector-mlflow --clusterrole=$cr_name --serviceaccount=kagenti-system:otel-collector -n $ns"
    else
      $KUBECTL create rolebinding otel-collector-mlflow \
        --clusterrole="$cr_name" \
        --serviceaccount=kagenti-system:otel-collector \
        -n "$ns" \
        --dry-run=client -o yaml | $KUBECTL apply -f -
    fi
    log_success "RoleBinding otel-collector-mlflow created in $ns"
  done <<< "$agent_ns"
}

log_info "Step 2.5: MLflow DSC preflight + provisioning"
if [ "$SKIP_MLFLOW" = true ]; then
  log_success "Skipping MLflow DSC preflight (--skip-mlflow)"
elif ! $KUBECTL get crd datascienceclusters.datasciencecluster.opendatahub.io &>/dev/null; then
  log_warn "RHOAI not installed (DataScienceCluster CRD not found) — skipping MLflow provisioning"
else
  _mlflow_check_dsc
  _mlflow_create_cr
  _mlflow_wait_ready
fi
echo ""

# ============================================================================
# Step 3: Install kagenti-deps
# ============================================================================
log_info "Step 3: Install kagenti-deps"

# Pre-flight: ensure enableUserWorkload is set in cluster-monitoring-config.
# The kagenti-deps chart has a kiali-operand hook that tries to REPLACE the entire
# cluster-monitoring-config ConfigMap. On managed clusters this conflicts
# with the endpoint-monitoring-operator which already owns .data.config.yaml.
# We merge enableUserWorkload proactively so the hook failure is non-critical.
_ensure_user_workload_monitoring() {
  if $DRY_RUN; then return; fi
  local existing
  existing=$($KUBECTL get configmap cluster-monitoring-config -n openshift-monitoring \
    -o jsonpath='{.data.config\.yaml}' 2>/dev/null || echo "")
  if [ -z "$existing" ]; then
    # ConfigMap doesn't exist or is empty — the hook can create it from scratch
    return
  fi
  if echo "$existing" | grep -q "enableUserWorkload: true"; then
    log_success "User workload monitoring already enabled"
    return
  fi
  # Merge enableUserWorkload into existing config
  local merged
  merged="enableUserWorkload: true"$'\n'"$existing"
  $KUBECTL patch configmap cluster-monitoring-config -n openshift-monitoring \
    --type=merge -p "{\"data\":{\"config.yaml\":$(echo "$merged" | python3 -c "import sys,json; sys.stdout.write(json.dumps(sys.stdin.read()))")}}" >/dev/null
  log_success "Merged enableUserWorkload: true into cluster-monitoring-config"
}
_ensure_user_workload_monitoring

# Install or upgrade kagenti-deps.
# On managed clusters the kiali-operand post-install/post-upgrade hook
# fails because it tries to delete+recreate cluster-monitoring-config, which is owned
# by the endpoint-monitoring-operator. We handle this two ways:
#   - Upgrade: always skip hooks (operands are already running from the initial install)
#   - Fresh install: attempt with hooks; if the hook fails, recover with --no-hooks
#     and manually apply the safe operand CRs
# Wait for a namespace to finish terminating. If it's Active, that's fine — skip it.
# Only intervenes when the namespace is stuck in Terminating state (force-strips finalizers).
_wait_ns_gone() {
  local ns="$1" tries=0
  local phase
  phase=$($KUBECTL get ns "$ns" -o jsonpath='{.status.phase}' 2>/dev/null || echo "NotFound")
  if [ "$phase" != "Terminating" ]; then
    return 0  # Active or doesn't exist — nothing to wait for
  fi
  log_info "  Waiting for $ns to terminate..."
  while $KUBECTL get ns "$ns" &>/dev/null; do
    $KUBECTL get ns "$ns" -o json 2>/dev/null \
      | python3 -c "import sys,json; d=json.load(sys.stdin); d['spec']['finalizers']=[]; json.dump(d,sys.stdout)" \
      | $KUBECTL replace --raw "/api/v1/namespaces/$ns/finalize" -f - >/dev/null 2>&1 || true
    tries=$((tries + 1))
    if [ $tries -ge 30 ]; then log_error "  $ns still exists after 30s"; return 1; fi
    sleep 1
  done
  log_success "  $ns terminated"
}

# Wait for the components we need before proceeding to the kagenti chart.
# Skips MLflow (its oauth-secret is created by the kagenti chart's post-install hook).
_wait_deployment_ready() {
  local deploy="$1" ns="$2" label="${3:-$1}" kind="${4:-deployment}"
  local tries=0
  if ! $KUBECTL get "$kind"/"$deploy" -n "$ns" &>/dev/null; then
    log_info "Waiting for $label to appear..."
    until $KUBECTL get "$kind"/"$deploy" -n "$ns" &>/dev/null; do
      [ $((++tries)) -ge 60 ] && { log_warn "$label $kind not found after 5m"; return 1; }
      sleep 5
    done
  fi
  log_info "Checking $label rollout..."
  $KUBECTL rollout status "$kind"/"$deploy" -n "$ns" --timeout=300s || \
    log_warn "$label rollout not ready within 5m"
}

_wait_kagenti_deps_ready() {
  if $DRY_RUN; then return; fi

  # Parallel chains for cert-manager and Istio
  _wait_deployment_ready cert-manager-webhook cert-manager cert-manager &
  local pid_cm=$!
  _wait_deployment_ready istiod istio-system Istio &
  local pid_istio=$!

  # Keycloak chain — sequential (each step creates the next resource)
  _wait_deployment_ready rhbk-operator "$KC_NAMESPACE" "RHBK operator"
  _wait_deployment_ready postgres-kc "$KC_NAMESPACE" "Keycloak PostgreSQL" statefulset
  _wait_deployment_ready keycloak "$KC_NAMESPACE" Keycloak statefulset

  # Collect parallel results
  wait $pid_cm || log_warn "cert-manager readiness check failed"
  wait $pid_istio || log_warn "Istio readiness check failed"
}

# Apply operand CRs that --no-hooks skipped.
# Called on both fresh install AND upgrade so reruns fix missing CRs.
_apply_operand_crs() {
  if $DRY_RUN; then return; fi

  # Wait for the Keycloak CRD before applying — the operator subscription was
  # just installed and needs time to register the CRD.
  log_info "Waiting for Keycloak CRD..."
  local tries=0
  while ! $KUBECTL get crd keycloaks.k8s.keycloak.org &>/dev/null; do
    tries=$((tries + 1))
    if [ $tries -ge 60 ]; then
      log_error "Keycloak CRD not found after 5m — cannot proceed without Keycloak"
      return 1
    fi
    sleep 5
  done
  log_success "Keycloak CRD available"

  log_info "Applying operand CRs..."
  helm get hooks kagenti-deps -n kagenti-system 2>/dev/null | python3 -c "
import sys
content = sys.stdin.read()
docs = content.split('---')
for doc in docs:
    if not doc.strip():
        continue
    # Skip pre-install hooks (CRD waiter SA, Role, RoleBinding)
    if 'pre-install' in doc and 'post-install' not in doc:
        continue
    # Skip the cluster-monitoring-config ConfigMap (the conflict source)
    if 'kind: ConfigMap' in doc and 'cluster-monitoring-config' in doc:
        continue
    # Skip the CRD waiter Job
    if 'kind: Job' in doc:
        continue
    lines = [l for l in doc.strip().split('\n')
             if 'helm.sh/hook' not in l and 'helm.sh/hook-weight' not in l and 'helm.sh/hook-delete-policy' not in l]
    print('---')
    print('\n'.join(lines))
" | $KUBECTL apply -f - || true
}

_helm_kagenti_deps() {
  # Pre-flight: ensure namespaces managed by this chart are not stuck terminating
  # from a previous failed install/uninstall cycle
  for _ns in keycloak istio-cni istio-system istio-ztunnel; do
    _wait_ns_gone "$_ns"
  done

  # Build MLflow OTEL flags: enable the pipeline and point it at the DSC-managed endpoint.
  local _mlflow_vals_file=""
  if [ -n "$MLFLOW_TRACES_ENDPOINT" ]; then
    _mlflow_vals_file=$(mktemp /tmp/kagenti-mlflow-vals-XXXXXX.yaml)
    cat > "$_mlflow_vals_file" <<EOF
otel:
  mlflow:
    enabled: true
  collector:
    mlflowConfig:
      exporters:
        otlphttp/mlflow:
          traces_endpoint: "${MLFLOW_TRACES_ENDPOINT}"
EOF
    log_info "MLflow OTEL values: otel.mlflow.enabled=true, endpoint=${MLFLOW_TRACES_ENDPOINT}"
  fi

  # Keycloak public URL is needed by the realm-init audience mapper.
  # Construct from DOMAIN (known since Step 2) so it's correct on first install.
  local _kc_public_url="https://keycloak-${KC_NAMESPACE}.${DOMAIN}"

  if helm status kagenti-deps -n kagenti-system &>/dev/null; then
    # Upgrade path: skip hooks (the kiali hook will fail on any cluster where
    # cluster-monitoring-config is managed by another operator)
    log_info "kagenti-deps already installed — upgrading (hooks skipped)"
    run_cmd helm upgrade kagenti-deps "$KAGENTI_REPO/charts/kagenti-deps/" \
      -n kagenti-system \
      --set spire.trustDomain="${DOMAIN}" \
      --set "keycloak.publicUrl=${_kc_public_url}" \
      --set components.kiali.enabled=false \
      --set components.rhoai.enabled=true \
      --set components.mlflow.enabled=false \
      --set components.shipwright.enabled=false \
      --set mlflow.auth.enabled=false \
      ${_mlflow_vals_file:+-f "$_mlflow_vals_file"} \
      --no-hooks
    # Apply operand CRs on upgrade too — catches CRs missed by a previous
    # failed install (e.g. Keycloak CRD wasn't ready yet on first run)
    _apply_operand_crs
    [ -n "$_mlflow_vals_file" ] && rm -f "$_mlflow_vals_file"
    _wait_kagenti_deps_ready
    return $?
  fi

  # Fresh install: skip hooks (they commonly timeout or conflict with managed
  # operators like cluster-monitoring-config). Operand CRs are applied manually after.
  log_info "Installing kagenti-deps..."
  run_cmd helm dependency update "$KAGENTI_REPO/charts/kagenti-deps/"
  run_cmd helm install kagenti-deps "$KAGENTI_REPO/charts/kagenti-deps/" \
    -n kagenti-system --create-namespace \
    --set spire.trustDomain="${DOMAIN}" \
    --set "keycloak.publicUrl=${_kc_public_url}" \
    --set components.kiali.enabled=false \
    --set components.rhoai.enabled=true \
    --set components.mlflow.enabled=false \
    --set components.shipwright.enabled=false \
    --set mlflow.auth.enabled=false \
    ${_mlflow_vals_file:+-f "$_mlflow_vals_file"} \
    --no-hooks

  _apply_operand_crs
  [ -n "$_mlflow_vals_file" ] && rm -f "$_mlflow_vals_file"
  _wait_kagenti_deps_ready
}
_helm_kagenti_deps
log_success "kagenti-deps installed"
echo ""

# ============================================================================
# Step 3b: Istio multi-mesh shared trust via cert-manager
# ============================================================================
# Ported from kagenti Ansible installer (05_install_rhoai.yaml).
#
# When RHOAI is installed alongside Kagenti, two Istio control planes exist
# (default + openshift-gateway) with different self-signed CAs. We create a
# shared root CA via cert-manager so both istiods trust each other's workload
# certificates. Without this, ztunnel fails with BadSignature errors and
# pod-to-pod mTLS in ambient mode is broken.

_adopt_for_helm() {
  local kind="$1" name="$2" ns="${3:-}"
  local ns_flag=()
  if [ -n "$ns" ]; then ns_flag=(-n "$ns"); fi
  if $KUBECTL get "$kind" "$name" "${ns_flag[@]}" &>/dev/null; then
    $KUBECTL label "$kind" "$name" "${ns_flag[@]}" \
      app.kubernetes.io/managed-by=Helm --overwrite || true
    $KUBECTL annotate "$kind" "$name" "${ns_flag[@]}" \
      meta.helm.sh/release-name=kagenti-deps \
      meta.helm.sh/release-namespace=kagenti-system --overwrite || true
  fi
}

_wait_secret_ready() {
  local secret="$1" ns="$2" tries=0
  while ! $KUBECTL get secret "$secret" -n "$ns" -o jsonpath='{.data.tls\.crt}' 2>/dev/null | grep -q .; do
    tries=$((tries + 1))
    if [ $tries -ge 30 ]; then log_warn "$ns/$secret not ready after 5m"; return 1; fi
    sleep 10
  done
  return 0
}

_ensure_rhoai_shared_trust() {
  if $DRY_RUN; then return; fi

  # --- Wait for cert-manager ---
  log_info "Waiting for cert-manager CRDs..."
  local tries=0
  while ! $KUBECTL get crd certificates.cert-manager.io &>/dev/null; do
    tries=$((tries + 1))
    if [ $tries -ge 60 ]; then
      log_warn "cert-manager CRDs not found after 5m — shared trust may need manual setup"
      return 0
    fi
    sleep 5
  done

  log_info "Waiting for cert-manager webhook..."
  tries=0
  while ! $KUBECTL get deployment cert-manager-webhook -n cert-manager &>/dev/null; do
    tries=$((tries + 1))
    if [ $tries -ge 60 ]; then
      log_warn "cert-manager webhook not found after 5m"
      return 0
    fi
    sleep 5
  done
  $KUBECTL rollout status deployment/cert-manager-webhook -n cert-manager --timeout=180s || true

  log_info "Waiting for cert-manager webhook endpoints..."
  tries=0
  while ! $KUBECTL get endpoints cert-manager-webhook -n cert-manager -o jsonpath='{.subsets[0].addresses[0].ip}' 2>/dev/null | grep -q .; do
    tries=$((tries + 1))
    if [ $tries -ge 30 ]; then
      log_warn "cert-manager webhook endpoints not ready after 2.5m"
      break
    fi
    sleep 5
  done
  # Webhook endpoint has an IP but may still be bootstrapping TLS serving certs
  tries=0
  until $KUBECTL get secret cert-manager-webhook-ca -n cert-manager &>/dev/null; do
    [ $((++tries)) -ge 12 ] && break; sleep 5
  done
  log_success "cert-manager is ready"

  # --- Create shared trust resources (fallback if Helm lookup skipped them) ---
  log_info "Creating shared trust cert-manager resources..."
  $KUBECTL apply -f - <<'EOF'
apiVersion: cert-manager.io/v1
kind: ClusterIssuer
metadata:
  name: istio-mesh-root-selfsigned
spec:
  selfSigned: {}
---
apiVersion: cert-manager.io/v1
kind: Certificate
metadata:
  name: istio-mesh-root-ca
  namespace: cert-manager
spec:
  isCA: true
  commonName: istio-mesh-root-ca
  duration: 87600h
  renewBefore: 720h
  secretName: istio-mesh-root-ca-secret
  privateKey:
    algorithm: RSA
    size: 4096
  issuerRef:
    name: istio-mesh-root-selfsigned
    kind: ClusterIssuer
EOF

  log_info "Waiting for root CA secret..."
  if ! _wait_secret_ready istio-mesh-root-ca-secret cert-manager; then return 0; fi
  log_success "Root CA secret ready"

  $KUBECTL apply -f - <<'EOF'
apiVersion: cert-manager.io/v1
kind: ClusterIssuer
metadata:
  name: istio-mesh-ca
spec:
  ca:
    secretName: istio-mesh-root-ca-secret
---
apiVersion: cert-manager.io/v1
kind: Certificate
metadata:
  name: istio-cacerts-default
  namespace: istio-system
spec:
  isCA: true
  commonName: istio-ca-default
  duration: 8760h
  renewBefore: 720h
  secretName: istio-cacerts-default-cert
  privateKey:
    algorithm: RSA
    size: 2048
  issuerRef:
    name: istio-mesh-ca
    kind: ClusterIssuer
---
apiVersion: cert-manager.io/v1
kind: Certificate
metadata:
  name: istio-cacerts-openshift-gateway
  namespace: openshift-ingress
spec:
  isCA: true
  commonName: istio-ca-openshift-gateway
  duration: 8760h
  renewBefore: 720h
  secretName: istio-cacerts-og-cert
  privateKey:
    algorithm: RSA
    size: 2048
  issuerRef:
    name: istio-mesh-ca
    kind: ClusterIssuer
EOF

  log_info "Waiting for intermediate CA secrets..."
  _wait_secret_ready istio-cacerts-default-cert istio-system
  _wait_secret_ready istio-cacerts-og-cert openshift-ingress
  log_success "Intermediate CA secrets ready"

  # --- Detect stale intermediate CAs (root CA regenerated but intermediates not re-signed) ---
  log_info "Checking intermediate CA consistency..."
  local ROOT_FP CHANGED=false
  ROOT_FP=$($KUBECTL get secret istio-mesh-root-ca-secret -n cert-manager \
    -o jsonpath='{.data.tls\.crt}' | base64 -d | \
    openssl x509 -noout -fingerprint -sha256 2>/dev/null | sed 's/.*=//')

  for item in "istio-cacerts-default-cert:istio-system" "istio-cacerts-og-cert:openshift-ingress"; do
    local secret="${item%%:*}" ns="${item##*:}"
    local INTER_FP
    INTER_FP=$($KUBECTL get secret "$secret" -n "$ns" \
      -o jsonpath='{.data.ca\.crt}' | base64 -d | \
      openssl x509 -noout -fingerprint -sha256 2>/dev/null | sed 's/.*=//')
    if [ "$ROOT_FP" != "$INTER_FP" ]; then
      log_warn "Root CA mismatch in $ns/$secret — forcing re-issuance"
      $KUBECTL delete secret "$secret" -n "$ns"
      CHANGED=true
    fi
  done

  if $CHANGED; then
    log_info "Waiting for re-issued intermediate CAs..."
    _wait_secret_ready istio-cacerts-default-cert istio-system
    _wait_secret_ready istio-cacerts-og-cert openshift-ingress
    log_success "Intermediate CAs re-issued"
  else
    log_success "Intermediate CAs consistent with root"
  fi

  # --- Transform cert-manager secrets into Istio cacerts format ---
  log_info "Creating Istio cacerts secrets..."
  for item in "istio-cacerts-default-cert:istio-system" "istio-cacerts-og-cert:openshift-ingress"; do
    local secret="${item%%:*}" ns="${item##*:}"
    local CA_CERT CA_KEY ROOT_CERT CERT_CHAIN
    CA_CERT=$($KUBECTL get secret "$secret" -n "$ns" -o jsonpath='{.data.tls\.crt}' | base64 -d)
    CA_KEY=$($KUBECTL get secret "$secret" -n "$ns" -o jsonpath='{.data.tls\.key}' | base64 -d)
    ROOT_CERT=$($KUBECTL get secret "$secret" -n "$ns" -o jsonpath='{.data.ca\.crt}' | base64 -d)
    CERT_CHAIN="${CA_CERT}
${ROOT_CERT}"
    $KUBECTL create secret generic cacerts -n "$ns" \
      --from-literal=ca-cert.pem="${CA_CERT}" \
      --from-literal=ca-key.pem="${CA_KEY}" \
      --from-literal=root-cert.pem="${ROOT_CERT}" \
      --from-literal=cert-chain.pem="${CERT_CHAIN}" \
      --dry-run=client -o yaml | $KUBECTL apply -f -
  done
  log_success "Istio cacerts secrets created"

  # --- Restart istiods to pick up shared CA ---
  log_info "Restarting istiods..."
  if $KUBECTL get deployment/istiod -n istio-system &>/dev/null; then
    $KUBECTL rollout restart deployment/istiod -n istio-system
    $KUBECTL rollout status deployment/istiod -n istio-system --timeout=300s || true
  else
    log_warn "deployment/istiod not found in istio-system — check kagenti-deps hooks"
  fi
  $KUBECTL rollout restart deployment/istiod-openshift-gateway -n openshift-ingress 2>/dev/null || true
  $KUBECTL rollout status deployment/istiod-openshift-gateway -n openshift-ingress --timeout=300s || true

  # --- Delete stale istio-ca-root-cert ConfigMaps and restart ztunnel ---
  log_info "Cleaning up stale CA ConfigMaps and restarting ztunnel..."
  for ns in kagenti-system gateway-system keycloak mcp-system istio-system istio-ztunnel; do
    $KUBECTL delete configmap istio-ca-root-cert -n "$ns" --ignore-not-found || true
  done

  $KUBECTL rollout restart daemonset/ztunnel -n istio-ztunnel 2>/dev/null || true
  $KUBECTL rollout status daemonset/ztunnel -n istio-ztunnel --timeout=300s || true
  log_success "Shared trust reconciliation complete"
}
_ensure_rhoai_shared_trust
echo ""

# ============================================================================
# Step 4: Install Kagenti (operator + webhook + UI)
# ============================================================================
log_info "Step 4: Install Kagenti (operator + webhook + UI)"

# Secrets file
SECRETS_FILE="$KAGENTI_REPO/charts/kagenti/.secrets.yaml"
SECRETS_TEMPLATE="$KAGENTI_REPO/charts/kagenti/.secrets_template.yaml"
if [ ! -f "$SECRETS_FILE" ]; then
  if [ -f "$SECRETS_TEMPLATE" ]; then
    log_info "Creating .secrets.yaml from template"
    cp "$SECRETS_TEMPLATE" "$SECRETS_FILE"
    log_warn "Edit $SECRETS_FILE if you need custom secrets (e.g. Keycloak admin password)"
  else
    log_error "No .secrets_template.yaml found at $SECRETS_TEMPLATE"
    exit 1
  fi
fi

# Build UI helm flags
KAGENTI_UI_FLAGS=()
if $SKIP_UI; then
  log_info "Kagenti UI: skipped (--skip-ui)"
  KAGENTI_UI_FLAGS+=(--set components.ui.enabled=false)
else
  log_info "Detecting latest kagenti release tag..."
  LATEST_TAG=$(git ls-remote --tags --sort="v:refname" https://github.com/kagenti/kagenti.git | tail -n1 | sed 's|.*refs/tags/v||; s/\^{}//')
  if [ -z "$LATEST_TAG" ]; then
    log_warn "Could not detect latest tag — using 'latest'"
    LATEST_TAG="latest"
  fi
  log_success "Using tag: v${LATEST_TAG}"
  KAGENTI_UI_FLAGS+=(--set "ui.frontend.tag=v${LATEST_TAG}")
  KAGENTI_UI_FLAGS+=(--set "ui.backend.tag=v${LATEST_TAG}")
fi

# Override operator chart dependency with local repo if provided
if [ -n "$OPERATOR_REPO" ]; then
  OPERATOR_REPO="$(cd "$OPERATOR_REPO" && pwd)"
  if [ ! -f "$OPERATOR_REPO/charts/kagenti-operator/Chart.yaml" ]; then
    log_error "Invalid operator repo: $OPERATOR_REPO (missing charts/kagenti-operator/Chart.yaml)"
    exit 1
  fi
  log_info "Using local operator chart: $OPERATOR_REPO/charts/kagenti-operator"
  # Place local chart directly into Helm's charts/ subdir — bypasses OCI dependency.
  # Remove any existing tgz first — Helm prefers tgz over directory.
  mkdir -p "$KAGENTI_REPO/charts/kagenti/charts"
  rm -f "$KAGENTI_REPO/charts/kagenti/charts"/kagenti-operator-chart-*.tgz
  cp -r "$OPERATOR_REPO/charts/kagenti-operator" \
        "$KAGENTI_REPO/charts/kagenti/charts/kagenti-operator-chart"
  # Clean up the copied chart on exit so it doesn't pollute git state
  trap 'rm -rf "$KAGENTI_REPO/charts/kagenti/charts/kagenti-operator-chart"' EXIT
fi

if [ -z "$OPERATOR_REPO" ]; then
  run_cmd helm dependency update "$KAGENTI_REPO/charts/kagenti/"
fi

# Detect Keycloak public URL from route (for OIDC redirects in the browser).
# The internal URL (keycloak-service.KC_NAMESPACE:8080) is NOT reachable from outside the cluster.
KC_ROUTE=$($KUBECTL get route keycloak -n "$KC_NAMESPACE" -o jsonpath='{.spec.host}' 2>/dev/null || echo "")
if [ -n "$KC_ROUTE" ]; then
  KEYCLOAK_PUBLIC_URL="https://${KC_ROUTE}"
  log_success "Keycloak public URL: $KEYCLOAK_PUBLIC_URL"
else
  # Fallback: construct from cluster domain
  KEYCLOAK_PUBLIC_URL="https://keycloak-${KC_NAMESPACE}.${DOMAIN}"
  log_warn "Keycloak route not found — using constructed URL: $KEYCLOAK_PUBLIC_URL"
fi

log_info "Keycloak: realm=$KC_REALM namespace=$KC_NAMESPACE"

# Read the actual Keycloak admin credentials from the operator-managed secret.
# The RHBK operator creates keycloak-initial-admin with a random password.
# The kagenti chart creates keycloak-admin-secret in agent namespaces for the
# client-registration sidecar — these must match, otherwise client-registration
# can't authenticate to the master realm to register per-agent OAuth clients.
KC_ADMIN_FLAGS=()
_kc_admin_user=$($KUBECTL get secret keycloak-initial-admin -n "$KC_NAMESPACE" \
  -o jsonpath='{.data.username}' 2>/dev/null | base64 -d 2>/dev/null || echo "")
_kc_admin_pass=$($KUBECTL get secret keycloak-initial-admin -n "$KC_NAMESPACE" \
  -o jsonpath='{.data.password}' 2>/dev/null | base64 -d 2>/dev/null || echo "")
if [ -n "$_kc_admin_user" ] && [ -n "$_kc_admin_pass" ]; then
  KC_ADMIN_FLAGS+=(--set "keycloak.adminUsername=${_kc_admin_user}")
  KC_ADMIN_FLAGS+=(--set "keycloak.adminPassword=${_kc_admin_pass}")
  log_success "Keycloak admin credentials read from keycloak-initial-admin"
else
  log_warn "Could not read keycloak-initial-admin — agent client-registration may fail"
fi

# Build operator image override flags
OPERATOR_IMAGE_FLAGS=()
if [ -n "$OPERATOR_IMAGE" ]; then
  OP_TAG="${OPERATOR_IMAGE##*:}"
  OP_REPO="${OPERATOR_IMAGE%:*}"
  OPERATOR_IMAGE_FLAGS+=(--set "kagenti-operator-chart.controllerManager.container.image.repository=${OP_REPO}")
  OPERATOR_IMAGE_FLAGS+=(--set "kagenti-operator-chart.controllerManager.container.image.tag=${OP_TAG}")
  OPERATOR_IMAGE_FLAGS+=(--set "kagenti-operator-chart.controllerManager.container.image.pullPolicy=Always")
  log_info "Operator image: ${OPERATOR_IMAGE}"
fi

run_cmd $KUBECTL create namespace mcp-system --dry-run=client -o yaml | $KUBECTL apply -f -

run_cmd helm upgrade --install kagenti "$KAGENTI_REPO/charts/kagenti/" \
  -n kagenti-system --create-namespace \
  -f "$SECRETS_FILE" \
  ${KAGENTI_UI_FLAGS[@]+"${KAGENTI_UI_FLAGS[@]}"} \
  ${OPERATOR_IMAGE_FLAGS[@]+"${OPERATOR_IMAGE_FLAGS[@]}"} \
  ${KC_ADMIN_FLAGS[@]+"${KC_ADMIN_FLAGS[@]}"} \
  --set "agentOAuthSecret.spiffePrefix=spiffe://${DOMAIN}/sa" \
  --set uiOAuthSecret.useServiceAccountCA=false \
  --set agentOAuthSecret.useServiceAccountCA=false \
  --set mlflowOAuthSecret.useServiceAccountCA=false \
  --set mlflow.auth.enabled=false \
  --set "keycloak.publicUrl=${KEYCLOAK_PUBLIC_URL}" \
  --set "keycloak.realm=${KC_REALM}" \
  --set "kagenti-operator-chart.mlflow.enable=$([ "$SKIP_MLFLOW" = true ] && echo false || echo true)"

log_success "Kagenti installed"

# Grant otel-collector SA MLflow RBAC in agent namespaces (created by kagenti chart above)
if [ "$SKIP_MLFLOW" = true ]; then
  log_success "Skipping MLflow RBAC grant (--skip-mlflow)"
else
  _mlflow_grant_otel_rbac
fi
echo ""

# ============================================================================
# Step 5: Install MCP Gateway
# ============================================================================
log_info "Step 5: Install MCP Gateway"

if $SKIP_MCP_GATEWAY; then
  log_info "Skipped (--skip-mcp-gateway)"
elif helm status mcp-gateway -n mcp-system &>/dev/null; then
  log_info "MCP Gateway already installed — skipping"
else
  log_info "Installing MCP Gateway v${MCP_GATEWAY_VERSION}..."
  run_cmd helm install mcp-gateway oci://ghcr.io/kuadrant/charts/mcp-gateway \
    --create-namespace --namespace mcp-system --version "$MCP_GATEWAY_VERSION"
  log_success "MCP Gateway installed"
fi
echo ""

# ============================================================================
# Step 6: Verify Helm releases
# ============================================================================
log_info "Step 6: Verify Helm releases"
echo ""

_verify_release() {
  local release="$1" ns="$2" rc=0
  log_info "helm history $release -n $ns:"
  if ! helm history "$release" -n "$ns" --max 3 2>/dev/null; then
    log_error "$release: no release found in $ns"
    rc=1
  else
    local status
    status=$(helm status "$release" -n "$ns" -o json 2>/dev/null | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('info',{}).get('status',''), end='')" 2>/dev/null || echo "")
    if [ "$status" != "deployed" ]; then
      log_error "$release: status is '$status' (expected 'deployed')"
      rc=1
    else
      log_success "$release: deployed"
    fi
  fi
  echo ""
  return $rc
}

VERIFY_FAILED=false
_verify_release kagenti-deps kagenti-system    || VERIFY_FAILED=true
if ! $SKIP_MCP_GATEWAY; then
  _verify_release mcp-gateway mcp-system       || VERIFY_FAILED=true
fi
_verify_release kagenti kagenti-system         || VERIFY_FAILED=true

if $VERIFY_FAILED; then
  log_error "One or more Helm releases failed verification — check output above"
  exit 1
fi

# ============================================================================
# Step 7: Show access info
# ============================================================================
log_info "Step 7: Access info"
echo ""

log_info "Kagenti pods:"
$KUBECTL get pods -n kagenti-system 2>/dev/null || log_warn "No pods in kagenti-system"
echo ""

# Kagenti UI URL
if ! $SKIP_UI; then
  UI_HOST=$($KUBECTL get route kagenti-ui -n kagenti-system -o jsonpath='{.status.ingress[0].host}' 2>/dev/null || echo "")
  if [ -n "$UI_HOST" ]; then
    log_success "Kagenti UI: https://$UI_HOST"
  fi
fi

# Keycloak admin credentials (master realm — for admin console only)
if $SHOW_SECRETS; then
  KC_SECRET=$($KUBECTL get secret keycloak-initial-admin -n "$KC_NAMESPACE" -o go-template='Username: {{.data.username | base64decode}}  Password: {{.data.password | base64decode}}' 2>/dev/null || echo "")
  if [ -n "$KC_SECRET" ]; then
    log_success "Keycloak admin (master realm): $KC_SECRET"
  fi
else
  log_info "Keycloak admin credentials available in secret keycloak-initial-admin (use --show-secrets to print)"
fi

ELAPSED=$(( SECONDS - START_SECONDS ))
MINS=$(( ELAPSED / 60 ))
SECS=$(( ELAPSED % 60 ))

echo ""
echo "============================================"
echo "  Kagenti platform is ready!  (Time elapsed:${MINS}m ${SECS}s)"
echo ""
echo "  Note: Some pods (SPIRE agents, operator-managed workloads)"
echo "  may still be starting. Allow a few minutes for all components"
echo "  to become fully available."
echo "============================================"
echo ""
