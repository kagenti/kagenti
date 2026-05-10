#!/usr/bin/env bash
# ============================================================================
# OPENSHELL SHARED INFRASTRUCTURE
# ============================================================================
# Deploys cluster-wide shared infrastructure for the OpenShell MVP:
#   1. agent-sandbox-controller (kubernetes-sigs, upstream image)
#   2. Gateway API experimental CRDs (TCPRoute/TLSRoute, Kind only)
#   3. cert-manager CA chain (ClusterIssuer + CA Certificate)
#   4. Keycloak realm (openshell realm, PKCE client, test users)
#   5. LiteLLM model proxy (optional, when --litellm is passed)
#   6. Base sandbox image pre-pull (optional, when --pre-pull is passed)
#
# Idempotent: safe to re-run. Checks existing state before each step.
#
# Usage:
#   scripts/openshell/deploy-shared.sh                  # Deploy everything
#   scripts/openshell/deploy-shared.sh --skip-sandbox   # Skip agent-sandbox
#   scripts/openshell/deploy-shared.sh --litellm        # Also deploy LiteLLM proxy
#   scripts/openshell/deploy-shared.sh --pre-pull       # Pre-pull base sandbox image
#   scripts/openshell/deploy-shared.sh --dry-run        # Print commands only
#   scripts/openshell/deploy-shared.sh --help           # Show usage
#
# Prerequisites: kubectl, cert-manager installed, Keycloak running
# ============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

# ── Versions (keep in sync with scripts/kind/setup-kagenti.sh) ──────────────
AGENT_SANDBOX_VERSION="v0.3.10"
GATEWAY_API_VERSION="v1.4.0"

# ── Defaults ────────────────────────────────────────────────────────────────
KEYCLOAK_NS="${KEYCLOAK_NS:-keycloak}"
KEYCLOAK_POD="keycloak-0"
KCADM="/opt/keycloak/bin/kcadm.sh"
KC_CONFIG="/tmp/kc/kcadm.config"

STEP_SANDBOX=true
STEP_GATEWAY_API=true
STEP_TLS=true
STEP_KEYCLOAK=true
STEP_LITELLM=false
STEP_PREPULL=false
KIND_CLUSTER="${CLUSTER_NAME:-kagenti}"
DRY_RUN=false

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
Usage: $(basename "$0") [OPTIONS]

Deploy OpenShell shared infrastructure (idempotent).

Options:
  --help              Show this help message
  --skip-sandbox      Skip agent-sandbox-controller installation
  --skip-gateway-api  Skip experimental Gateway API CRDs
  --skip-tls          Skip cert-manager CA chain
  --skip-keycloak     Skip Keycloak realm setup
  --litellm           Deploy LiteLLM model proxy (requires MAAS_* env vars)
  --pre-pull          Pre-pull base sandbox image into the cluster
  --kind-cluster NAME Kind cluster name for pre-pull (default: kagenti)
  --keycloak-ns NS    Keycloak namespace (default: keycloak)
  --dry-run           Print commands without executing
EOF
  exit 0
}

# ── Argument parsing ────────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
  case "$1" in
    --help)             usage ;;
    --skip-sandbox)     STEP_SANDBOX=false; shift ;;
    --skip-gateway-api) STEP_GATEWAY_API=false; shift ;;
    --skip-tls)         STEP_TLS=false; shift ;;
    --skip-keycloak)    STEP_KEYCLOAK=false; shift ;;
    --keycloak-ns)      KEYCLOAK_NS="$2"; shift 2 ;;
    --litellm)          STEP_LITELLM=true; shift ;;
    --pre-pull)         STEP_PREPULL=true; shift ;;
    --kind-cluster)     KIND_CLUSTER="$2"; shift 2 ;;
    --dry-run)          DRY_RUN=true; shift ;;
    *)
      log_error "Unknown option: $1"
      usage
      ;;
  esac
done

echo ""
echo "╔════════════════════════════════════════════════════════════════╗"
echo "║  OpenShell Shared Infrastructure                             ║"
echo "╚════════════════════════════════════════════════════════════════╝"
echo ""
echo "  Sandbox controller: $STEP_SANDBOX"
echo "  Gateway API CRDs:   $STEP_GATEWAY_API"
echo "  cert-manager CA:    $STEP_TLS"
echo "  Keycloak realm:     $STEP_KEYCLOAK"
echo "  LiteLLM proxy:      $STEP_LITELLM"
echo "  Base image pre-pull: $STEP_PREPULL"
echo "  Keycloak namespace: $KEYCLOAK_NS"
echo "  Dry run:            $DRY_RUN"
echo ""

# ── Helper: wait for deployment ─────────────────────────────────────────────
wait_deployment_ready() {
  local name=$1 namespace=$2 timeout=${3:-300}
  if $DRY_RUN; then return 0; fi
  log_info "Waiting for deployment $name in $namespace (timeout: ${timeout}s)..."
  kubectl wait --for=condition=Available deployment/"$name" \
    -n "$namespace" --timeout="${timeout}s"
}

# ── Helper: detect OpenShift ────────────────────────────────────────────────
is_openshift() {
  kubectl get clusterversion &>/dev/null
}

# ============================================================================
# Step 1: agent-sandbox-controller
# ============================================================================
if $STEP_SANDBOX; then
  log_info "Step 1: agent-sandbox-controller (${AGENT_SANDBOX_VERSION})"

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
      kubectl wait --for=condition=Established crd \
        sandboxes.agents.x-k8s.io \
        --timeout=60s
    fi
    wait_deployment_ready agent-sandbox-controller agent-sandbox-system
    log_success "agent-sandbox installed"
  fi
  echo ""
fi

# ============================================================================
# Step 2: Gateway API experimental CRDs (Kind only)
# ============================================================================
if $STEP_GATEWAY_API; then
  log_info "Step 2: Gateway API experimental CRDs (${GATEWAY_API_VERSION})"

  if is_openshift; then
    log_info "OpenShift detected — skipping experimental Gateway API CRDs (OCP uses Routes)"
  elif kubectl get crd tcproutes.gateway.networking.k8s.io &>/dev/null; then
    log_success "Experimental Gateway API CRDs already installed — skipping"
  else
    log_info "Installing Gateway API ${GATEWAY_API_VERSION} (experimental bundle)..."
    run_cmd kubectl apply --server-side --force-conflicts -f \
      "https://github.com/kubernetes-sigs/gateway-api/releases/download/${GATEWAY_API_VERSION}/experimental-install.yaml"

    if ! $DRY_RUN; then
      log_info "Waiting for experimental CRDs to become established..."
      kubectl wait --for=condition=Established crd \
        tcproutes.gateway.networking.k8s.io \
        tlsroutes.gateway.networking.k8s.io \
        --timeout=60s
    fi
    log_success "Experimental Gateway API CRDs installed"
  fi
  echo ""
fi

# ============================================================================
# Step 2b: Shared TLS passthrough Gateway (Kind only)
# ============================================================================
if $STEP_GATEWAY_API && ! is_openshift; then
  log_info "Step 2b: Shared TLS passthrough Gateway (kagenti-system)"

  if kubectl get gateway tls-passthrough -n kagenti-system &>/dev/null; then
    log_success "Shared tls-passthrough Gateway already exists — skipping"
  else
    log_info "Creating shared TLS passthrough Gateway..."
    run_cmd kubectl apply -f - <<'EOF'
apiVersion: gateway.networking.k8s.io/v1
kind: Gateway
metadata:
  name: tls-passthrough
  namespace: kagenti-system
  annotations:
    networking.istio.io/service-type: NodePort
spec:
  gatewayClassName: istio
  listeners:
    - name: tls-passthrough
      port: 443
      protocol: TLS
      tls:
        mode: Passthrough
      allowedRoutes:
        namespaces:
          from: All
EOF

    if ! $DRY_RUN; then
      log_info "Waiting for Gateway to be programmed..."
      kubectl wait --for=condition=Programmed gateway/tls-passthrough \
        -n kagenti-system --timeout=60s
    fi
    log_success "Shared TLS passthrough Gateway created"
  fi

  # Fix NodePort to 30443 so it matches Kind extraPortMappings (host 9443 → container 30443)
  KIND_TLS_NODEPORT=30443
  CURRENT_NODEPORT=$(kubectl get svc tls-passthrough-istio -n kagenti-system \
    -o jsonpath='{.spec.ports[?(@.port==443)].nodePort}' 2>/dev/null || echo "")
  if [[ -n "$CURRENT_NODEPORT" && "$CURRENT_NODEPORT" != "$KIND_TLS_NODEPORT" ]]; then
    log_info "Fixing TLS NodePort: $CURRENT_NODEPORT → $KIND_TLS_NODEPORT"
    if ! $DRY_RUN; then
      kubectl patch svc tls-passthrough-istio -n kagenti-system --type='json' \
        -p="[{\"op\": \"replace\", \"path\": \"/spec/ports/1/nodePort\", \"value\": $KIND_TLS_NODEPORT}]"
    else
      echo "  [dry-run] kubectl patch svc tls-passthrough-istio NodePort → $KIND_TLS_NODEPORT"
    fi
    log_success "TLS NodePort fixed to $KIND_TLS_NODEPORT"
  fi
  echo ""
fi

# ============================================================================
# Step 2c: Enable alpha Gateway API support in Istio (Kind only)
# ============================================================================
if $STEP_GATEWAY_API && ! is_openshift; then
  log_info "Step 2c: Enabling PILOT_ENABLE_ALPHA_GATEWAY_API on istiod"

  CURRENT_VAL=$(kubectl get deployment istiod -n istio-system \
    -o jsonpath='{.spec.template.spec.containers[0].env[?(@.name=="PILOT_ENABLE_ALPHA_GATEWAY_API")].value}' 2>/dev/null || echo "")

  if [[ "$CURRENT_VAL" == "true" ]]; then
    log_success "PILOT_ENABLE_ALPHA_GATEWAY_API already enabled — skipping"
  else
    run_cmd kubectl set env deployment/istiod -n istio-system \
      PILOT_ENABLE_ALPHA_GATEWAY_API=true

    if ! $DRY_RUN; then
      kubectl rollout status deployment/istiod -n istio-system --timeout=120s || {
        log_warn "istiod rollout slow — continuing (will settle during tenant deploy)"
      }
    fi
    log_success "Istio alpha Gateway API support enabled"
  fi
  echo ""
fi

# ============================================================================
# Step 3: cert-manager CA chain
# ============================================================================
if $STEP_TLS; then
  log_info "Step 3: cert-manager CA chain for OpenShell TLS"

  # Verify cert-manager is installed
  if ! kubectl get deployment cert-manager-webhook -n cert-manager &>/dev/null; then
    log_error "cert-manager is not installed. Install cert-manager first."
    exit 1
  fi

  # 3a: Bootstrap self-signed ClusterIssuer
  log_info "Applying ClusterIssuer openshell-selfsigned..."
  run_cmd kubectl apply -f - <<'EOF'
apiVersion: cert-manager.io/v1
kind: ClusterIssuer
metadata:
  name: openshell-selfsigned
spec:
  selfSigned: {}
EOF

  # 3b: CA certificate (self-signed, isCA)
  log_info "Applying CA Certificate openshell-ca..."
  run_cmd kubectl apply -f - <<'EOF'
apiVersion: cert-manager.io/v1
kind: Certificate
metadata:
  name: openshell-ca
  namespace: cert-manager
spec:
  isCA: true
  commonName: openshell-ca
  secretName: openshell-ca-secret
  duration: 87600h
  renewBefore: 720h
  privateKey:
    algorithm: ECDSA
    size: 256
  issuerRef:
    name: openshell-selfsigned
    kind: ClusterIssuer
EOF

  # Wait for the CA certificate to be issued
  if ! $DRY_RUN; then
    log_info "Waiting for CA certificate to be ready..."
    kubectl wait --for=condition=Ready certificate/openshell-ca \
      -n cert-manager --timeout=60s
  fi

  # 3c: CA issuer (signs tenant leaf certs)
  log_info "Applying ClusterIssuer openshell-ca-issuer..."
  run_cmd kubectl apply -f - <<'EOF'
apiVersion: cert-manager.io/v1
kind: ClusterIssuer
metadata:
  name: openshell-ca-issuer
spec:
  ca:
    secretName: openshell-ca-secret
EOF

  if ! $DRY_RUN; then
    log_info "Waiting for CA issuer to become ready..."
    kubectl wait --for=condition=Ready clusterissuer/openshell-ca-issuer \
      --timeout=60s
  fi

  log_success "cert-manager CA chain ready"
  echo ""
fi

# ============================================================================
# Step 4: Keycloak realm
# ============================================================================
if $STEP_KEYCLOAK; then
  log_info "Step 4: Keycloak realm (openshell)"

  # Verify Keycloak pod is running
  if ! kubectl get pod "$KEYCLOAK_POD" -n "$KEYCLOAK_NS" &>/dev/null; then
    log_error "Keycloak pod $KEYCLOAK_POD not found in namespace $KEYCLOAK_NS"
    exit 1
  fi

  if $DRY_RUN; then
    log_info "[dry-run] Would create openshell realm, client, users, roles, groups"
    echo ""
  else
    # Read Keycloak admin credentials
    KC_USER=$(kubectl get secret keycloak-initial-admin -n "$KEYCLOAK_NS" \
      -o jsonpath='{.data.username}' | base64 -d)
    KC_PASS=$(kubectl get secret keycloak-initial-admin -n "$KEYCLOAK_NS" \
      -o jsonpath='{.data.password}' | base64 -d)

    # Pass commands via stdin (bash -s) to keep credentials out of process args
    kc_exec() {
      kubectl exec -i -n "$KEYCLOAK_NS" "$KEYCLOAK_POD" -- bash -s <<< "$1"
    }

    # Login to Keycloak
    log_info "Logging in to Keycloak as $KC_USER..."
    kc_exec "$KCADM config credentials --server http://localhost:8080 \
      --realm master --user $KC_USER --password $KC_PASS \
      --config $KC_CONFIG" >/dev/null 2>&1

    # 4a: Create realm
    log_info "Creating realm: openshell"
    kc_exec "$KCADM create realms --config $KC_CONFIG \
      -s realm=openshell -s enabled=true 2>/dev/null" 2>/dev/null || true

    # 4b: Create PKCE client
    log_info "Creating client: openshell-cli (public, PKCE)"
    kc_exec "$KCADM create clients --config $KC_CONFIG -r openshell \
      -s clientId=openshell-cli \
      -s enabled=true \
      -s publicClient=true \
      -s 'redirectUris=[\"http://localhost:*\",\"http://127.0.0.1:*\"]' \
      -s 'webOrigins=[\"+\"]' \
      -s directAccessGrantsEnabled=true \
      -s 'attributes={\"pkce.code.challenge.method\":\"S256\"}' \
      2>/dev/null" 2>/dev/null || true

    # 4c: Create roles
    for role in openshell-admin openshell-user; do
      log_info "Creating role: $role"
      kc_exec "$KCADM create roles --config $KC_CONFIG -r openshell \
        -s name=$role 2>/dev/null" 2>/dev/null || true
    done

    # 4d: Create groups
    for group in team1 team2; do
      log_info "Creating group: /$group"
      kc_exec "$KCADM create groups --config $KC_CONFIG -r openshell \
        -s name=$group 2>/dev/null" 2>/dev/null || true
    done

    # Helper: create user, set password, assign role and group
    create_openshell_user() {
      local username=$1 password=$2 role=$3
      shift 3
      local groups=("$@")

      log_info "Creating user: $username"
      kc_exec "$KCADM create users --config $KC_CONFIG -r openshell \
        -s username=$username -s enabled=true -s emailVerified=true \
        -s email=${username}@openshell.local \
        2>/dev/null" 2>/dev/null || true

      kc_exec "$KCADM set-password --config $KC_CONFIG -r openshell \
        --username $username --new-password $password \
        2>/dev/null" 2>/dev/null || true

      kc_exec "$KCADM add-roles --config $KC_CONFIG -r openshell \
        --uusername $username --rolename $role \
        2>/dev/null" 2>/dev/null || true

      for grp in "${groups[@]}"; do
        local grp_id
        grp_id=$(kc_exec "$KCADM get groups --config $KC_CONFIG -r openshell \
          --fields id,name 2>/dev/null" | \
          grep -B1 "\"$grp\"" | grep '"id"' | sed 's/.*: "\(.*\)".*/\1/')
        if [[ -n "$grp_id" ]]; then
          local user_id
          user_id=$(kc_exec "$KCADM get users --config $KC_CONFIG -r openshell \
            -q username=$username --fields id 2>/dev/null" | \
            grep '"id"' | head -1 | sed 's/.*: "\(.*\)".*/\1/')
          if [[ -n "$user_id" ]]; then
            kc_exec "$KCADM update users/$user_id/groups/$grp_id --config $KC_CONFIG \
              -r openshell -s realm=openshell -s userId=$user_id -s groupId=$grp_id \
              --no-merge 2>/dev/null" 2>/dev/null || true
          fi
        fi
      done
    }

    # 4e: Create users
    create_openshell_user "alice" "alice123" "openshell-user" "team1"
    create_openshell_user "bob"   "bob123"   "openshell-user" "team2"
    create_openshell_user "admin" "admin123" "openshell-admin" "team1" "team2"

    # 4f: Create per-tenant client scopes with audience mappers
    # Each tenant gets a default client scope so the audience claim is always
    # present in tokens (the CLI does not request scopes explicitly).
    CLIENT_ID=$(kc_exec "$KCADM get clients --config $KC_CONFIG -r openshell \
      -q clientId=openshell-cli --fields id 2>/dev/null" | \
      grep '"id"' | head -1 | sed 's/.*: "\(.*\)".*/\1/')

    for tenant in team1 team2; do
      log_info "Creating client scope: ${tenant}-audience"
      kc_exec "$KCADM create client-scopes --config $KC_CONFIG -r openshell \
        -s name=${tenant}-audience \
        -s protocol=openid-connect \
        2>/dev/null" 2>/dev/null || true

      # Get the scope ID to add the audience mapper
      SCOPE_ID=$(kc_exec "$KCADM get client-scopes --config $KC_CONFIG -r openshell \
        --fields id,name 2>/dev/null" | \
        grep -B1 "\"${tenant}-audience\"" | grep '"id"' | sed 's/.*: "\(.*\)".*/\1/')

      if [[ -n "$SCOPE_ID" ]]; then
        log_info "Adding audience mapper to ${tenant}-audience scope"
        kc_exec "$KCADM create client-scopes/$SCOPE_ID/protocol-mappers/models \
          --config $KC_CONFIG -r openshell \
          -s name=audience-${tenant} \
          -s protocol=openid-connect \
          -s protocolMapper=oidc-audience-mapper \
          -s 'config={\"included.custom.audience\":\"${tenant}\",\"id.token.claim\":\"true\",\"access.token.claim\":\"true\"}' \
          2>/dev/null" 2>/dev/null || true

        # Assign as default scope so audience is always in the token
        if [[ -n "$CLIENT_ID" ]]; then
          kc_exec "$KCADM update clients/$CLIENT_ID/default-client-scopes/$SCOPE_ID \
            --config $KC_CONFIG -r openshell 2>/dev/null" 2>/dev/null || true
        fi
      fi
    done

    if [[ -z "$CLIENT_ID" ]]; then
      log_warn "Could not find openshell-cli client ID — audience scopes created but not linked"
    fi

    log_success "Keycloak openshell realm configured"
    echo ""
  fi
fi

# ============================================================================
# Step 5: LiteLLM model proxy (optional)
# ============================================================================
if $STEP_LITELLM; then
  log_info "Step 5: LiteLLM model proxy"

  LITEMAAS_URL="${MAAS_LLAMA4_API_BASE:-https://litellm-prod.apps.maas.redhatworkshops.io/v1}"
  LITEMAAS_KEY="${MAAS_LLAMA4_API_KEY:-}"
  LITEMAAS_MODEL="${MAAS_LLAMA4_MODEL:-llama-scout-17b}"
  LITELLM_NS="${LITELLM_NS:-team1}"
  LITELLM_PROXY_NAME="litellm-model-proxy"

  DEEPSEEK_MODEL="${MAAS_DEEPSEEK_MODEL:-deepseek-r1-distill-qwen-14b}"

  if [[ -z "$LITEMAAS_KEY" ]]; then
    log_warn "MAAS_LLAMA4_API_KEY not set — skipping LiteLLM proxy"
  elif kubectl get deployment "$LITELLM_PROXY_NAME" -n "$LITELLM_NS" &>/dev/null \
       && kubectl rollout status "deploy/$LITELLM_PROXY_NAME" -n "$LITELLM_NS" --timeout=5s &>/dev/null; then
    log_success "LiteLLM proxy already deployed and ready — skipping"
  else
    log_info "Deploying LiteLLM model proxy in namespace $LITELLM_NS..."
    kubectl get ns "$LITELLM_NS" &>/dev/null || run_cmd kubectl create ns "$LITELLM_NS"

    # Store API key in a Secret (not plaintext in ConfigMap)
    kubectl create secret generic litemaas-credentials -n "$LITELLM_NS" \
        --from-literal=api-key="$LITEMAAS_KEY" \
        --dry-run=client -o yaml | kubectl apply -f -

    # Also create litellm-virtual-keys for sandbox agents
    kubectl create secret generic litellm-virtual-keys -n "$LITELLM_NS" \
        --from-literal=api-key="$LITEMAAS_KEY" \
        --dry-run=client -o yaml | kubectl apply -f -

    # hosted_vllm/ provider avoids LiteLLM's OpenAI Responses API bridge
    run_cmd kubectl apply -f - <<EOLITELLM
apiVersion: v1
kind: ConfigMap
metadata:
  name: litellm-config
  namespace: $LITELLM_NS
data:
  config.yaml: |
    litellm_settings:
      drop_params: true
      use_chat_completions_url_for_anthropic_messages: true
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
      - model_name: "deepseek-r1"
        litellm_params:
          model: "hosted_vllm/$DEEPSEEK_MODEL"
          api_base: "$LITEMAAS_URL"
          api_key: "os.environ/LITEMAAS_API_KEY"
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: $LITELLM_PROXY_NAME
  namespace: $LITELLM_NS
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
  namespace: $LITELLM_NS
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

    if ! $DRY_RUN; then
      kubectl rollout status "deploy/$LITELLM_PROXY_NAME" -n "$LITELLM_NS" --timeout=60s || {
        log_warn "LiteLLM proxy still pulling image — continuing (will be ready by test phase)"
      }
    fi
    log_success "LiteLLM model proxy deployed"
  fi

  # Create LLM virtual-keys secret (idempotent)
  log_info "Creating litellm-virtual-keys secret in $LITELLM_NS..."
  run_cmd kubectl create secret generic litellm-virtual-keys -n "$LITELLM_NS" \
    --from-literal=api-key="${LITEMAAS_KEY:-PLACEHOLDER}" \
    --dry-run=client -o yaml | kubectl apply -f - 2>&1 | grep -v "^Warning:" || true

  echo ""
fi

# ============================================================================
# Step 6: Base sandbox image pre-pull (optional)
# ============================================================================
if $STEP_PREPULL; then
  log_info "Step 6: Pre-pull base sandbox image"

  BASE_IMAGE="ghcr.io/nvidia/openshell-community/sandboxes/base:latest"

  # Read gateway image tags from values.yaml
  CHART_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)/charts/openshell"
  GW_REPO=$(grep -A2 'gateway:' "$CHART_DIR/values.yaml" | grep 'repository:' | awk '{print $2}')
  GW_TAG=$(grep -A3 'gateway:' "$CHART_DIR/values.yaml" | grep 'tag:' | awk '{print $2}')
  CD_REPO=$(grep -A2 'computeDriver:' "$CHART_DIR/values.yaml" | grep 'repository:' | awk '{print $2}')
  CD_TAG=$(grep -A3 'computeDriver:' "$CHART_DIR/values.yaml" | grep 'tag:' | awk '{print $2}')
  CR_REPO=$(grep -A2 'credentialsDriver:' "$CHART_DIR/values.yaml" | grep 'repository:' | awk '{print $2}')
  CR_TAG=$(grep -A3 'credentialsDriver:' "$CHART_DIR/values.yaml" | grep 'tag:' | awk '{print $2}')

  if is_openshift; then
    # OCP: Start pull Jobs for all images in parallel (non-blocking)
    PULL_IMAGES="$BASE_IMAGE ${GW_REPO}:${GW_TAG} ${CD_REPO}:${CD_TAG} ${CR_REPO}:${CR_TAG}"
    for img in $PULL_IMAGES; do
      job_name="pull-$(echo "$img" | sed 's|[/:.@]|-|g' | tail -c 58)"
      if kubectl get job "$job_name" -n team1 &>/dev/null; then
        continue
      fi
      log_info "Pre-pulling $img..."
      run_cmd kubectl apply -f - <<EOJOB
apiVersion: batch/v1
kind: Job
metadata:
  name: $job_name
  namespace: team1
spec:
  ttlSecondsAfterFinished: 300
  template:
    spec:
      containers:
      - name: pull
        image: $img
        imagePullPolicy: Always
        command: ["echo", "pulled"]
      restartPolicy: Never
EOJOB
    done
    log_info "Waiting for pre-pull Jobs to complete (up to 10 min)..."
    for jn in $PULL_IMAGES; do
      jname="pull-$(echo "$jn" | sed 's|[/:.@]|-|g' | tail -c 58)"
      kubectl wait --for=condition=Complete "job/$jname" \
        -n team1 --timeout=600s 2>/dev/null || log_warn "Pre-pull $jname not complete"
    done
  else
    # Kind: docker pull + kind load
    if docker exec "${KIND_CLUSTER}-control-plane" crictl images 2>/dev/null | grep -q "sandboxes/base"; then
      log_success "Base sandbox image already loaded in Kind — skipping"
    else
      log_info "Pre-pulling base sandbox image into Kind cluster '$KIND_CLUSTER'..."
      docker pull "$BASE_IMAGE" 2>/dev/null && \
        kind load docker-image "$BASE_IMAGE" --name "$KIND_CLUSTER" 2>/dev/null || \
        log_warn "Base image pre-pull failed (non-critical)"
    fi
  fi
  echo ""
fi

# ============================================================================
# Summary
# ============================================================================
echo "╔════════════════════════════════════════════════════════════════╗"
echo "║  OpenShell Shared Infrastructure — Complete                  ║"
echo "╚════════════════════════════════════════════════════════════════╝"
echo ""
if ! $DRY_RUN; then
  echo "  Verify:"
  echo "    kubectl get deployment agent-sandbox-controller -n agent-sandbox-system"
  echo "    kubectl get crd sandboxes.agents.x-k8s.io"
  echo "    kubectl get clusterissuer openshell-ca-issuer"
  echo "    kubectl get secret openshell-ca-secret -n cert-manager"
  if $STEP_LITELLM; then
    echo "    kubectl get deployment litellm-model-proxy -n ${LITELLM_NS:-team1}"
  fi
  echo ""
fi
