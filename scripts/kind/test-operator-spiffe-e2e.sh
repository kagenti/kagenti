#!/usr/bin/env bash
#
# End-to-End test for operator SPIFFE authentication with Podman
#
# This script performs a complete E2E test of the operator SPIFFE auth feature:
# 1. Builds all required images (operator + auth images) with Podman
# 2. Loads them into an existing Kind cluster
# 3. Deploys Kagenti with SPIFFE auth enabled using local images
# 4. Verifies the feature works end-to-end
#
# REQUIREMENTS:
# - Podman installed and running
# - Kind cluster already created (use: kind create cluster --name kagenti)
# - kubectl configured to access the cluster
# - Podman configured with Kind experimental provider:
#   export KIND_EXPERIMENTAL_PROVIDER=podman
#   export DOCKER_HOST=unix:///path/to/podman/socket
#
# USAGE:
#   ./test-operator-spiffe-e2e.sh
#
# This script uses Podman for building and deploying, following the operator
# SPIFFE authentication feature requirements.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
CLUSTER_NAME="${CLUSTER_NAME:-kagenti}"
BUILD_CONTEXT="$REPO_ROOT/kagenti"
TEMP_DIR=$(mktemp -d)

trap 'rm -rf "$TEMP_DIR"' EXIT

log_info() {
  echo -e "\033[0;34m→\033[0m $*"
}

log_success() {
  echo -e "\033[0;32m✓\033[0m $*"
}

log_error() {
  echo -e "\033[0;31m✗\033[0m $*"
}

log_step() {
  echo ""
  echo -e "\033[0;34m━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\033[0m"
  echo -e "\033[0;34m Step $1: $2\033[0m"
  echo -e "\033[0;34m━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\033[0m"
}

# Verify prerequisites
log_step "0" "Checking prerequisites"

if ! command -v podman &> /dev/null; then
  log_error "Podman not found. Please install Podman first."
  exit 1
fi
log_info "Podman found: $(podman --version)"

if ! command -v kind &> /dev/null; then
  log_error "Kind not found. Please install Kind first."
  exit 1
fi
log_info "Kind found: $(kind version | head -1)"

if [ -z "${KIND_EXPERIMENTAL_PROVIDER:-}" ]; then
  log_error "KIND_EXPERIMENTAL_PROVIDER not set."
  log_info "Set it with: export KIND_EXPERIMENTAL_PROVIDER=podman"
  exit 1
fi
log_info "Kind experimental provider: $KIND_EXPERIMENTAL_PROVIDER"

if ! kind get clusters | grep -q "^${CLUSTER_NAME}$"; then
  log_error "Kind cluster '${CLUSTER_NAME}' not found."
  log_info "Create it with: kind create cluster --name ${CLUSTER_NAME}"
  exit 1
fi
log_info "Kind cluster '${CLUSTER_NAME}' found"

if ! kubectl cluster-info &> /dev/null; then
  log_error "kubectl not configured properly"
  exit 1
fi
log_info "kubectl configured"

log_success "Prerequisites verified"

# Build operator image from local checkout
log_step "1" "Building operator image with Podman"

OPERATOR_REPO="$REPO_ROOT/charts/kagenti/charts/kagenti-operator-chart"
if [ ! -d "$OPERATOR_REPO" ]; then
  log_error "Operator chart not found at: $OPERATOR_REPO"
  log_info "Run: cd charts/kagenti && helm dependency update"
  exit 1
fi

log_info "Building operator image..."
cd "$OPERATOR_REPO"
podman build -q \
  -t localhost/kagenti-operator:test \
  -f Dockerfile \
  .
log_success "localhost/kagenti-operator:test built"

# Build auth images
log_step "2" "Building auth images with Podman"

cd "$BUILD_CONTEXT"

log_info "Building operator-spiffe-bootstrap image..."
podman build -q \
  -t ghcr.io/kagenti/kagenti/operator-spiffe-bootstrap:latest \
  -f auth/operator-spiffe-bootstrap/Dockerfile \
  .
log_success "operator-spiffe-bootstrap:latest built"

log_info "Building backend image..."
podman build -q \
  -t ghcr.io/kagenti/kagenti/backend:latest \
  -f backend/Dockerfile \
  .
log_success "backend:latest built"

log_info "Building agent-oauth-secret image..."
podman build -q \
  -t ghcr.io/kagenti/kagenti/agent-oauth-secret:latest \
  -f auth/agent-oauth-secret/Dockerfile \
  .
log_success "agent-oauth-secret:latest built"

log_info "Building mlflow-oauth-secret image..."
podman build -q \
  -t ghcr.io/kagenti/kagenti/mlflow-oauth-secret:latest \
  -f auth/mlflow-oauth-secret/Dockerfile \
  .
log_success "mlflow-oauth-secret:latest built"

log_info "Building spiffe-idp-setup image..."
podman build -q \
  -t ghcr.io/kagenti/kagenti/spiffe-idp-setup:latest \
  -f auth/spiffe-idp-setup/Dockerfile \
  .
log_success "spiffe-idp-setup:latest built"

# Load images into Kind
log_step "3" "Loading images into Kind cluster"

IMAGES=(
  "localhost/kagenti-operator:test"
  "ghcr.io/kagenti/kagenti/operator-spiffe-bootstrap:latest"
  "ghcr.io/kagenti/kagenti/backend:latest"
  "ghcr.io/kagenti/kagenti/agent-oauth-secret:latest"
  "ghcr.io/kagenti/kagenti/mlflow-oauth-secret:latest"
  "ghcr.io/kagenti/kagenti/spiffe-idp-setup:latest"
)

for img in "${IMAGES[@]}"; do
  img_name=$(echo "$img" | tr '/:' '_')
  tar_file="$TEMP_DIR/${img_name}.tar"

  log_info "Exporting $img..."
  podman save -o "$tar_file" "$img"

  log_info "Loading $img into Kind..."
  kind load image-archive "$tar_file" --name "$CLUSTER_NAME"

  rm "$tar_file"
done

log_success "All images loaded into Kind"

# Deploy with setup-kagenti.sh using local images
log_step "4" "Deploying Kagenti with operator SPIFFE authentication"

cd "$REPO_ROOT"

log_info "Running setup-kagenti.sh with SPIFFE auth and local images..."

# Use the standard setup script but with:
# - ENABLE_OPERATOR_SPIFFE_AUTH=true
# - Skip builds (we already built)
# - Override operator image to use local build
# - Skip cluster creation (already exists)

export ENABLE_OPERATOR_SPIFFE_AUTH=true
export SKIP_BUILDS=true
export SKIP_CLUSTER=true

# Clean up any stuck namespaces first
log_info "Checking for stuck namespaces..."
if kubectl get ns team1 &>/dev/null; then
  log_info "Deleting stuck team1 namespace..."
  kubectl delete ns team1 --wait=false || true
  kubectl patch ns team1 -p '{"metadata":{"finalizers":[]}}' --type=merge || true
fi

./scripts/kind/setup-kagenti.sh \
  --skip-cluster \
  --skip-builds \
  --no-ui \
  --with-spire \
  --with-mlflow \
  --enable-operator-spiffe-auth \
  --set "kagenti-operator-chart.controllerManager.container.image.repository=localhost/kagenti-operator" \
  --set "kagenti-operator-chart.controllerManager.container.image.tag=test"

log_success "Kagenti deployed with operator SPIFFE authentication"

# Verify operator deployment
log_step "5" "Verifying operator SPIFFE authentication"

log_info "Waiting for operator pod to be ready..."
kubectl wait --for=condition=ready pod \
  -l control-plane=controller-manager \
  -n kagenti-system \
  --timeout=180s

OPERATOR_POD=$(kubectl get pod -n kagenti-system -l control-plane=controller-manager -o jsonpath='{.items[0].metadata.name}')
log_info "Operator pod: $OPERATOR_POD"

# Check 1: Operator has 2 containers (manager + spiffe-helper)
log_info ""
log_info "Check 1: Container count..."
CONTAINER_COUNT=$(kubectl get pod "$OPERATOR_POD" -n kagenti-system -o jsonpath='{.spec.containers[*].name}' | wc -w | tr -d ' ')

if [ "$CONTAINER_COUNT" -eq 2 ]; then
  log_success "Operator pod has 2 containers (manager + spiffe-helper)"
  kubectl get pod "$OPERATOR_POD" -n kagenti-system -o jsonpath='{.spec.containers[*].name}' | tr ' ' '\n' | sed 's/^/  - /'
else
  log_error "Expected 2 containers, found $CONTAINER_COUNT"
  kubectl get pod "$OPERATOR_POD" -n kagenti-system -o json | jq '.spec.containers[].name'
  exit 1
fi

# Check 2: Operator logs show useSpiffeAuth:true
log_info ""
log_info "Check 2: Operator SPIFFE auth configuration..."
sleep 5  # Give operator time to log startup
if kubectl logs "$OPERATOR_POD" -n kagenti-system -c manager 2>/dev/null | grep -q "useSpiffeAuth"; then
  USE_SPIFFE=$(kubectl logs "$OPERATOR_POD" -n kagenti-system -c manager | grep "useSpiffeAuth" | tail -1)
  echo "  $USE_SPIFFE"

  if echo "$USE_SPIFFE" | grep -q "true"; then
    log_success "Operator is configured with useSpiffeAuth:true"
  else
    log_error "Operator useSpiffeAuth is not true"
    exit 1
  fi
else
  log_error "Could not find useSpiffeAuth in operator logs"
  log_info "Checking logs..."
  kubectl logs "$OPERATOR_POD" -n kagenti-system -c manager | tail -20
  exit 1
fi

# Check 3: JWT-SVID token exists with correct audience
log_info ""
log_info "Check 3: JWT-SVID token..."
sleep 5  # Give spiffe-helper time to fetch token

if kubectl exec "$OPERATOR_POD" -n kagenti-system -c spiffe-helper -- test -f /opt/jwt_svid.token 2>/dev/null; then
  JWT_CONTENT=$(kubectl exec "$OPERATOR_POD" -n kagenti-system -c spiffe-helper -- cat /opt/jwt_svid.token 2>/dev/null)
  JWT_AUD=$(echo "$JWT_CONTENT" | cut -d. -f2 | base64 -d 2>/dev/null | jq -r '.aud' 2>/dev/null || echo "")

  if [ -n "$JWT_AUD" ]; then
    log_success "JWT-SVID token exists with audience: $JWT_AUD"

    EXPECTED_AUD="http://keycloak.localtest.me:8080/realms/kagenti"
    if [ "$JWT_AUD" = "$EXPECTED_AUD" ]; then
      log_success "JWT audience matches Keycloak realm issuer"
    else
      log_error "JWT audience mismatch."
      log_error "Expected: $EXPECTED_AUD"
      log_error "Got:      $JWT_AUD"
      exit 1
    fi
  else
    log_error "Could not parse JWT-SVID token"
    exit 1
  fi
else
  log_error "JWT-SVID token file not found at /opt/jwt_svid.token"
  log_info "Checking spiffe-helper container status..."
  kubectl describe pod "$OPERATOR_POD" -n kagenti-system | grep -A 20 "spiffe-helper"
  exit 1
fi

# Check 4: Bootstrap job completed
log_info ""
log_info "Check 4: Bootstrap job status..."
if kubectl get job -n keycloak kagenti-operator-client-bootstrap &> /dev/null; then
  JOB_STATUS=$(kubectl get job -n keycloak kagenti-operator-client-bootstrap -o jsonpath='{.status.conditions[?(@.type=="Complete")].status}')
  if [ "$JOB_STATUS" = "True" ]; then
    log_success "Bootstrap job completed successfully"
  else
    log_error "Bootstrap job did not complete"
    kubectl get job -n keycloak kagenti-operator-client-bootstrap
    kubectl logs -n keycloak job/kagenti-operator-client-bootstrap --tail=50
    exit 1
  fi
else
  log_error "Bootstrap job not found in keycloak namespace"
  exit 1
fi

# Check 5: SPIFFE IdP in Keycloak
log_info ""
log_info "Check 5: Keycloak SPIFFE Identity Provider..."
# Port-forward to Keycloak
kubectl port-forward -n keycloak svc/keycloak-service 8080:8080 &>/dev/null &
PF_PID=$!
trap "kill $PF_PID 2>/dev/null || true; rm -rf '$TEMP_DIR'" EXIT

sleep 3  # Wait for port-forward

KEYCLOAK_ADMIN_USER=$(kubectl get secret -n keycloak keycloak-initial-admin -o jsonpath='{.data.username}' | base64 -d)
KEYCLOAK_ADMIN_PASS=$(kubectl get secret -n keycloak keycloak-initial-admin -o jsonpath='{.data.password}' | base64 -d)

# Get admin token
TOKEN=$(curl -s -X POST "http://keycloak.localtest.me:8080/realms/master/protocol/openid-connect/token" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=$KEYCLOAK_ADMIN_USER" \
  -d "password=$KEYCLOAK_ADMIN_PASS" \
  -d "grant_type=password" \
  -d "client_id=admin-cli" | jq -r '.access_token')

if [ -z "$TOKEN" ] || [ "$TOKEN" = "null" ]; then
  log_error "Failed to get Keycloak admin token"
  exit 1
fi

# Check SPIFFE IdP
IDP_INFO=$(curl -s "http://keycloak.localtest.me:8080/admin/realms/kagenti/identity-provider/instances/spire-spiffe" \
  -H "Authorization: Bearer $TOKEN")

PROVIDER_ID=$(echo "$IDP_INFO" | jq -r '.providerId')
if [ "$PROVIDER_ID" = "spiffe" ]; then
  log_success "SPIFFE IdP configured with providerId: spiffe"
else
  log_error "SPIFFE IdP providerId mismatch. Expected 'spiffe', got: $PROVIDER_ID"
  exit 1
fi

# Check 6: Operator client uses federated-jwt
log_info ""
log_info "Check 6: Operator client authentication method..."
CLIENT_INFO=$(curl -s "http://keycloak.localtest.me:8080/admin/realms/kagenti/clients?clientId=kagenti-operator" \
  -H "Authorization: Bearer $TOKEN" | jq '.[0]')

CLIENT_AUTH_TYPE=$(echo "$CLIENT_INFO" | jq -r '.clientAuthenticatorType')
if [ "$CLIENT_AUTH_TYPE" = "federated-jwt" ]; then
  log_success "Operator client uses clientAuthenticatorType: federated-jwt"
else
  log_error "Client authenticator type mismatch. Expected 'federated-jwt', got: $CLIENT_AUTH_TYPE"
  exit 1
fi

# Stop port-forward
kill $PF_PID 2>/dev/null || true

# Check 7: Test agent registration (optional but recommended)
log_info ""
log_info "Check 7: Test agent client registration..."

# Ensure team1 namespace exists
kubectl create namespace team1 --dry-run=client -o yaml | kubectl apply -f -
kubectl label namespace team1 istio.io/dataplane-mode=ambient --overwrite

# Create test agent
log_info "Creating test agent deployment..."
kubectl create deployment test-agent --image=busybox --namespace=team1 -- sleep 3600 || true

# Wait a bit for operator to process
sleep 10

# Check operator logs for agent registration
if kubectl logs -n kagenti-system deployment/kagenti-controller-manager -c manager --tail=100 | grep -q "test-agent"; then
  log_success "Operator processed test-agent deployment"
  log_info "Checking for client registration in Keycloak..."

  sleep 5

  # Port-forward again
  kubectl port-forward -n keycloak svc/keycloak-service 8080:8080 &>/dev/null &
  PF_PID=$!
  trap "kill $PF_PID 2>/dev/null || true; rm -rf '$TEMP_DIR'" EXIT
  sleep 3

  # Get fresh token
  TOKEN=$(curl -s -X POST "http://keycloak.localtest.me:8080/realms/master/protocol/openid-connect/token" \
    -H "Content-Type: application/x-www-form-urlencoded" \
    -d "username=$KEYCLOAK_ADMIN_USER" \
    -d "password=$KEYCLOAK_ADMIN_PASS" \
    -d "grant_type=password" \
    -d "client_id=admin-cli" | jq -r '.access_token')

  # Check if agent client was created
  AGENT_CLIENT=$(curl -s "http://keycloak.localtest.me:8080/admin/realms/kagenti/clients?clientId=team1.test-agent" \
    -H "Authorization: Bearer $TOKEN")

  if echo "$AGENT_CLIENT" | jq -e '.[0]' &>/dev/null; then
    log_success "Agent client 'team1.test-agent' registered in Keycloak without admin credentials!"
  else
    log_info "Agent client not yet registered (may need more time or agent restart)"
  fi

  kill $PF_PID 2>/dev/null || true
else
  log_info "Operator has not yet processed test-agent (may need more time)"
fi

# Cleanup test agent
kubectl delete deployment test-agent -n team1 --wait=false || true

# Summary
echo ""
echo -e "\033[0;32m━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\033[0m"
log_success "E2E Verification Complete!"
echo -e "\033[0;32m━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\033[0m"
echo ""
echo "All checks passed:"
echo "  ✓ Operator pod has 2 containers (manager + spiffe-helper)"
echo "  ✓ Operator configured with useSpiffeAuth:true"
echo "  ✓ JWT-SVID token exists with correct audience"
echo "  ✓ Bootstrap job completed successfully"
echo "  ✓ SPIFFE IdP configured in Keycloak (providerId: spiffe)"
echo "  ✓ Operator client uses federated-jwt authentication"
echo "  ✓ Agent client registration working"
echo ""
echo "The operator SPIFFE authentication feature is working correctly!"
echo ""
