#!/usr/bin/env bash
#
# Deploy LiteLLM Proxy
#
# Deploys LiteLLM as a centralized model gateway in kagenti-system.
# Reads model credentials from .env.maas and creates:
#   - litellm-config ConfigMap (model routing config)
#   - litellm-model-keys Secret (MAAS API keys as env vars)
#   - litellm-proxy-secret Secret (master key + DB URL)
#   - litellm-proxy Deployment + Service
#
# Prerequisites:
#   - postgres-otel StatefulSet running in kagenti-system
#   - .env.maas file in main repo root (or MAIN_REPO_ROOT)
#
# Usage:
#   ./.github/scripts/kagenti-operator/38-deploy-litellm.sh
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
source "$SCRIPT_DIR/../lib/env-detect.sh"
source "$SCRIPT_DIR/../lib/logging.sh"
source "$SCRIPT_DIR/../lib/k8s-utils.sh"

log_step "38" "Deploying LiteLLM Proxy"

NAMESPACE="kagenti-system"
LITELLM_DIR="$REPO_ROOT/deployments/litellm"
LITELLM_DB_NAME="${LITELLM_DB_NAME:-litellm}"
LITELLM_DB_SECRET="${LITELLM_DB_SECRET:-otel-db-secret}"
LITELLM_DB_HOST="${LITELLM_DB_HOST:-postgres.${NAMESPACE}.svc}"
LITELLM_DB_PORT="${LITELLM_DB_PORT:-5432}"

# ============================================================================
# Step 0: Create ServiceAccount and grant anyuid SCC
# ============================================================================
# TODO: Remove anyuid SCC requirement by building a custom LiteLLM image
# that relocates Prisma binaries from /root/.cache to a non-root path.
# The upstream litellm-database image bakes Prisma query engine binaries
# under /root/.cache during docker build (as root). On OpenShift, pods
# run with an arbitrary UID from the restricted SCC range, which cannot
# read root-owned files. Options to eliminate this:
#   1. Custom Dockerfile: RUN chmod -R a+rX /root/.cache
#   2. Upstream PR to use non-root user in LiteLLM Dockerfile
#   3. Init container that copies binaries to emptyDir with world-read

log_info "Creating ServiceAccount for litellm-proxy..."
kubectl create serviceaccount litellm-proxy -n "$NAMESPACE" 2>/dev/null || true

if [ "$IS_OPENSHIFT" = "true" ]; then
    log_info "Granting anyuid SCC to litellm-proxy ServiceAccount..."
    oc adm policy add-scc-to-user anyuid -z litellm-proxy -n "$NAMESPACE" 2>/dev/null || true
    log_success "anyuid SCC granted"
fi

# ============================================================================
# Step 1: Load model credentials from .env.maas
# ============================================================================

MAAS_ENV="$MAIN_REPO_ROOT/.env.maas"
if [ ! -f "$MAAS_ENV" ]; then
    log_error ".env.maas not found at $MAAS_ENV"
    log_info "Create .env.maas with MAAS_*_API_BASE, MAAS_*_API_KEY, MAAS_*_MODEL vars"
    exit 1
fi

log_info "Loading model credentials from $MAAS_ENV..."
# Source in subshell to capture without polluting this shell
eval "$(grep -E '^export MAAS_' "$MAAS_ENV")"

# Validate required vars
for var in MAAS_LLAMA4_API_BASE MAAS_LLAMA4_API_KEY MAAS_LLAMA4_MODEL \
           MAAS_MISTRAL_API_BASE MAAS_MISTRAL_API_KEY MAAS_MISTRAL_MODEL \
           MAAS_DEEPSEEK_API_BASE MAAS_DEEPSEEK_API_KEY MAAS_DEEPSEEK_MODEL; do
    if [ -z "${!var:-}" ]; then
        log_error "Missing $var in .env.maas"
        exit 1
    fi
done
log_success "MAAS model credentials loaded (3 models)"

# ============================================================================
# Step 1b: Load OpenAI credentials (optional)
# ============================================================================
# Try sources in order: env var > K8s secret (team1) > K8s secret (kagenti-system)
OPENAI_API_KEY="${OPENAI_API_KEY:-}"
OPENAI_ENABLED=false

if [ -n "$OPENAI_API_KEY" ]; then
    log_info "OpenAI key loaded from env var"
    OPENAI_ENABLED=true
else
    for ns in team1 "$NAMESPACE"; do
        KEY=$(kubectl get secret openai-secret -n "$ns" \
            -o jsonpath='{.data.apikey}' 2>/dev/null | base64 -d 2>/dev/null || echo "")
        if [ -n "$KEY" ]; then
            OPENAI_API_KEY="$KEY"
            OPENAI_ENABLED=true
            log_info "OpenAI key loaded from openai-secret in $ns"
            break
        fi
    done
fi

if [ "$OPENAI_ENABLED" = "true" ]; then
    log_success "OpenAI credentials loaded (gpt-4o-mini, gpt-4o)"
else
    log_warn "No OpenAI key found — OpenAI models will not be available"
    log_info "To enable: kubectl create secret generic openai-secret -n team1 --from-literal=apikey=sk-..."
fi

# ============================================================================
# Step 2: Get postgres credentials from existing otel-db-secret
# ============================================================================

log_info "Reading postgres credentials from $LITELLM_DB_SECRET..."
DB_USER=$(kubectl get secret "$LITELLM_DB_SECRET" -n "$NAMESPACE" \
    -o jsonpath='{.data.username}' | base64 -d)
DB_PASS=$(kubectl get secret "$LITELLM_DB_SECRET" -n "$NAMESPACE" \
    -o jsonpath='{.data.password}' | base64 -d)

if [ -z "$DB_USER" ] || [ -z "$DB_PASS" ]; then
    log_error "Could not read $LITELLM_DB_SECRET credentials"
    exit 1
fi

# Create litellm database if it doesn't exist
# Uses postgres superuser for CREATE DATABASE (application user may lack CREATEDB)
log_info "Ensuring $LITELLM_DB_NAME database exists..."
POSTGRES_POD=$(kubectl get pod -n "$NAMESPACE" -l app.kubernetes.io/name=postgres-otel \
    -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || echo "postgres-otel-0")
kubectl exec -n "$NAMESPACE" "$POSTGRES_POD" -- bash -c \
    "psql -U postgres -d postgres -tc \"SELECT 1 FROM pg_database WHERE datname='$LITELLM_DB_NAME'\" | grep -q 1 || \
     psql -U postgres -d postgres -c 'CREATE DATABASE $LITELLM_DB_NAME OWNER $DB_USER'" 2>/dev/null || {
    log_warn "Could not create $LITELLM_DB_NAME DB (may already exist or psql not available)"
}

DATABASE_URL="postgresql://${DB_USER}:${DB_PASS}@${LITELLM_DB_HOST}:${LITELLM_DB_PORT}/${LITELLM_DB_NAME}"
log_success "Database URL configured"

# ============================================================================
# Step 3: Generate master key
# ============================================================================

# Use existing master key if secret exists, otherwise generate new one
EXISTING_KEY=$(kubectl get secret litellm-proxy-secret -n "$NAMESPACE" \
    -o jsonpath='{.data.master-key}' 2>/dev/null | base64 -d 2>/dev/null || echo "")

if [ -n "$EXISTING_KEY" ]; then
    MASTER_KEY="$EXISTING_KEY"
    log_info "Using existing master key from litellm-proxy-secret"
else
    MASTER_KEY="sk-kagenti-$(openssl rand -hex 16)"
    log_info "Generated new master key"
fi

# ============================================================================
# Step 4: Create secrets
# ============================================================================

log_info "Creating litellm-proxy-secret..."
kubectl create secret generic litellm-proxy-secret \
    -n "$NAMESPACE" \
    --from-literal=master-key="$MASTER_KEY" \
    --from-literal=database-url="$DATABASE_URL" \
    --dry-run=client -o yaml | kubectl apply -f -

log_info "Creating litellm-model-keys secret (API keys)..."
MODEL_KEY_ARGS=(
    --from-literal=MAAS_LLAMA4_API_KEY="$MAAS_LLAMA4_API_KEY"
    --from-literal=MAAS_MISTRAL_API_KEY="$MAAS_MISTRAL_API_KEY"
    --from-literal=MAAS_DEEPSEEK_API_KEY="$MAAS_DEEPSEEK_API_KEY"
)
if [ "$OPENAI_ENABLED" = "true" ]; then
    MODEL_KEY_ARGS+=(--from-literal=OPENAI_API_KEY="$OPENAI_API_KEY")
fi
kubectl create secret generic litellm-model-keys \
    -n "$NAMESPACE" \
    "${MODEL_KEY_ARGS[@]}" \
    --dry-run=client -o yaml | kubectl apply -f -

log_success "Secrets created"

# ============================================================================
# Step 5: Generate and apply ConfigMap
# ============================================================================

log_info "Generating LiteLLM config..."

# Build OpenAI model entries if key is available
OPENAI_MODEL_ENTRIES=""
if [ "$OPENAI_ENABLED" = "true" ]; then
    OPENAI_MODEL_ENTRIES="
      - model_name: gpt-4o-mini
        litellm_params:
          model: gpt-4o-mini
          api_key: os.environ/OPENAI_API_KEY

      - model_name: gpt-4o
        litellm_params:
          model: gpt-4o
          api_key: os.environ/OPENAI_API_KEY"
fi

cat <<EOF | kubectl apply -f -
apiVersion: v1
kind: ConfigMap
metadata:
  name: litellm-config
  namespace: $NAMESPACE
  labels:
    app.kubernetes.io/name: litellm-proxy
    app.kubernetes.io/part-of: kagenti
data:
  config.yaml: |
    model_list:
      - model_name: llama-4-scout
        litellm_params:
          model: openai/$MAAS_LLAMA4_MODEL
          api_base: $MAAS_LLAMA4_API_BASE
          api_key: os.environ/MAAS_LLAMA4_API_KEY

      - model_name: mistral-small
        litellm_params:
          model: openai/$MAAS_MISTRAL_MODEL
          api_base: $MAAS_MISTRAL_API_BASE
          api_key: os.environ/MAAS_MISTRAL_API_KEY

      - model_name: deepseek-r1
        litellm_params:
          model: openai/$MAAS_DEEPSEEK_MODEL
          api_base: $MAAS_DEEPSEEK_API_BASE
          api_key: os.environ/MAAS_DEEPSEEK_API_KEY
${OPENAI_MODEL_ENTRIES}

    general_settings:
      master_key: os.environ/LITELLM_MASTER_KEY
      database_url: os.environ/DATABASE_URL
EOF

log_success "ConfigMap created"

# ============================================================================
# Step 6: Apply deployment and service
# ============================================================================

log_info "Applying LiteLLM deployment and service..."
kubectl apply -f "$LITELLM_DIR/deployment.yaml"
kubectl apply -f "$LITELLM_DIR/service.yaml"

# ============================================================================
# Step 7: Wait for rollout
# ============================================================================

log_info "Waiting for litellm-proxy deployment to be ready..."
if run_with_timeout 120 "kubectl rollout status deployment/litellm-proxy -n $NAMESPACE --timeout=120s"; then
    log_success "litellm-proxy is running"
else
    log_error "litellm-proxy did not become ready"
    kubectl get pods -n "$NAMESPACE" -l app.kubernetes.io/name=litellm-proxy
    kubectl logs -n "$NAMESPACE" -l app.kubernetes.io/name=litellm-proxy --tail=30 || true
    exit 1
fi

# ============================================================================
# Step 8: Verify health and create virtual keys
# ============================================================================

log_info "Verifying LiteLLM proxy health via port-forward..."

# Start temporary port-forward for health check and key generation
LITELLM_PF_PORT=14099
lsof -ti:${LITELLM_PF_PORT} 2>/dev/null | xargs kill 2>/dev/null || true
sleep 1
kubectl port-forward -n "$NAMESPACE" svc/litellm-proxy \
    "${LITELLM_PF_PORT}:4000" &>/tmp/litellm-deploy-pf.log &
PF_PID=$!
trap "kill $PF_PID 2>/dev/null || true" EXIT

# Wait for port-forward
for i in $(seq 1 15); do
    if curl -s -o /dev/null -w "%{http_code}" "http://localhost:${LITELLM_PF_PORT}/health/readiness" 2>/dev/null | grep -q "200"; then
        break
    fi
    sleep 2
done

HEALTH=$(curl -s -o /dev/null -w "%{http_code}" "http://localhost:${LITELLM_PF_PORT}/health/readiness" 2>/dev/null || echo "000")
if [ "$HEALTH" = "200" ]; then
    log_success "LiteLLM proxy health check passed"
else
    log_warn "Health check returned $HEALTH (proxy may still be starting)"
fi

# List available models
log_info "Available models:"
curl -s "http://localhost:${LITELLM_PF_PORT}/v1/models" \
    -H "Authorization: Bearer $MASTER_KEY" 2>/dev/null | \
    jq -r '.data[]?.id // empty' 2>/dev/null | sed 's/^/  - /' || \
    log_warn "Could not list models (proxy may still be initializing)"

# Create virtual key for team1 namespace
log_info "Creating virtual API key for team1..."
TEAM1_KEY_RESPONSE=$(curl -s "http://localhost:${LITELLM_PF_PORT}/key/generate" \
    -H "Authorization: Bearer $MASTER_KEY" \
    -H "Content-Type: application/json" \
    -d '{"key_alias": "team1-agents", "metadata": {"namespace": "team1"}, "max_budget": 100}' \
    2>/dev/null || echo '{}')

TEAM1_VIRTUAL_KEY=$(echo "$TEAM1_KEY_RESPONSE" | jq -r '.key // empty' 2>/dev/null || echo "")

if [ -n "$TEAM1_VIRTUAL_KEY" ]; then
    # Store virtual key in a secret for agent deployments to use
    kubectl create secret generic litellm-virtual-keys \
        -n team1 \
        --from-literal=api-key="$TEAM1_VIRTUAL_KEY" \
        --dry-run=client -o yaml | kubectl apply -f -
    log_success "Virtual key created for team1 and stored in litellm-virtual-keys secret"
else
    log_warn "Could not create virtual key (will retry on next deploy)"
fi

# Clean up port-forward
kill "$PF_PID" 2>/dev/null || true

log_success "LiteLLM proxy deployment complete"
log_info "Proxy endpoint: http://litellm-proxy.${NAMESPACE}.svc:4000/v1"
log_info "Master key stored in: litellm-proxy-secret (namespace: $NAMESPACE)"
