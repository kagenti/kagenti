#!/usr/bin/env bash
#
# Test operator SPIFFE authentication with Podman
#
# This script tests the operator SPIFFE authentication feature using Podman
# instead of Docker. It builds images locally, loads them into Kind via tar
# archives, and deploys Kagenti with SPIFFE auth enabled.
#
# REQUIREMENTS:
# - Podman installed and running
# - Kind cluster already created (use kind create cluster --name kagenti)
# - kubectl configured to access the cluster
#
# USAGE:
#   ./test-operator-spiffe-auth-podman.sh
#
# This script is provided as a testing aid for the operator SPIFFE auth feature.
# For production deployments, use the standard setup-kagenti.sh script with Docker.

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
  echo -e "\033[0;34m→ Step $1: $2\033[0m"
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

# Build images with Podman
log_step "1" "Building images with Podman"

log_info "Building operator-spiffe-bootstrap image..."
cd "$BUILD_CONTEXT"
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

# Load images into Kind via tar archives
log_step "2" "Loading images into Kind cluster"

IMAGES=(
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

log_success "Images loaded into Kind"

# Install Kagenti with SPIFFE auth enabled
log_step "3" "Installing Kagenti with operator SPIFFE authentication"

cd "$REPO_ROOT"

log_info "Installing via Helm..."
helm upgrade --install kagenti ./charts/kagenti/ \
  -n kagenti-system --create-namespace --wait --timeout 15m \
  --set "openshift=false" \
  --set "domain=localtest.me" \
  --set "keycloak.publicUrl=http://keycloak.localtest.me:8080" \
  --set "components.agentOperator.enabled=true" \
  --set "components.mcpGateway.enabled=false" \
  --set "components.mlflow.enabled=true" \
  --set "featureFlags.agentSandbox=false" \
  --set "featureFlags.skills=false" \
  --set "kagenti-operator-chart.spiffe.enabled=true" \
  --set "kagenti-operator-chart.spiffe.operatorAuth.enabled=true" \
  --set "kagenti-operator-chart.spiffe.operatorAuth.bootstrapImage=ghcr.io/kagenti/kagenti/operator-spiffe-bootstrap:latest" \
  --set "agentOAuthSecret.tag=latest" \
  --set "ui.backend.tag=latest" \
  --set "mlflowOAuthSecret.tag=latest" \
  --values ./deployments/envs/kind_values.yaml

log_success "Kagenti installed"

# Verify operator deployment
log_step "4" "Verifying operator SPIFFE authentication"

log_info "Waiting for operator pod to be ready..."
kubectl wait --for=condition=ready pod \
  -l control-plane=controller-manager \
  -n kagenti-system \
  --timeout=120s

OPERATOR_POD=$(kubectl get pod -n kagenti-system -l control-plane=controller-manager -o jsonpath='{.items[0].metadata.name}')
CONTAINER_COUNT=$(kubectl get pod "$OPERATOR_POD" -n kagenti-system -o jsonpath='{.spec.containers[*].name}' | wc -w | tr -d ' ')

if [ "$CONTAINER_COUNT" -eq 2 ]; then
  log_success "Operator pod has 2 containers (manager + spiffe-helper)"
  kubectl get pod "$OPERATOR_POD" -n kagenti-system -o jsonpath='{.spec.containers[*].name}' | tr ' ' '\n' | sed 's/^/  - /'
else
  log_error "Expected 2 containers, found $CONTAINER_COUNT"
  exit 1
fi

log_info "Checking operator logs for SPIFFE auth..."
if kubectl logs "$OPERATOR_POD" -n kagenti-system -c manager | grep -q "useSpiffeAuth"; then
  USE_SPIFFE=$(kubectl logs "$OPERATOR_POD" -n kagenti-system -c manager | grep "useSpiffeAuth" | tail -1)
  echo "  $USE_SPIFFE"

  if echo "$USE_SPIFFE" | grep -q "true"; then
    log_success "Operator is using SPIFFE authentication"
  else
    log_error "Operator useSpiffeAuth is not true"
    exit 1
  fi
else
  log_error "Could not find useSpiffeAuth in operator logs"
  exit 1
fi

log_info "Checking JWT-SVID token..."
if kubectl exec "$OPERATOR_POD" -n kagenti-system -c spiffe-helper -- cat /opt/jwt_svid.token > /dev/null 2>&1; then
  JWT_AUD=$(kubectl exec "$OPERATOR_POD" -n kagenti-system -c spiffe-helper -- cat /opt/jwt_svid.token | cut -d. -f2 | base64 -d 2>/dev/null | jq -r '.aud' 2>/dev/null || echo "")
  if [ -n "$JWT_AUD" ]; then
    log_success "JWT-SVID token exists with audience: $JWT_AUD"
    if [ "$JWT_AUD" = "http://keycloak.localtest.me:8080/realms/kagenti" ]; then
      log_success "JWT audience matches Keycloak realm issuer"
    else
      log_error "JWT audience mismatch. Expected: http://keycloak.localtest.me:8080/realms/kagenti"
    fi
  else
    log_error "Could not parse JWT-SVID token"
  fi
else
  log_error "JWT-SVID token file not found"
  exit 1
fi

# Verify bootstrap job completed
log_info "Checking bootstrap job..."
if kubectl get job -n keycloak kagenti-operator-client-bootstrap &> /dev/null; then
  JOB_STATUS=$(kubectl get job -n keycloak kagenti-operator-client-bootstrap -o jsonpath='{.status.conditions[?(@.type=="Complete")].status}')
  if [ "$JOB_STATUS" = "True" ]; then
    log_success "Bootstrap job completed successfully"
  else
    log_error "Bootstrap job did not complete"
    kubectl get job -n keycloak kagenti-operator-client-bootstrap
    exit 1
  fi
else
  log_error "Bootstrap job not found"
  exit 1
fi

echo ""
log_success "Operator SPIFFE authentication verification complete!"
echo ""
echo "Next steps:"
echo "  1. Check Keycloak SPIFFE IdP:"
echo "     kubectl port-forward -n keycloak svc/keycloak-service 8080:8080"
echo "     curl -s http://keycloak.localtest.me:8080/admin/realms/kagenti/identity-provider/instances/spire-spiffe | jq '.providerId'"
echo ""
echo "  2. Deploy a test agent and verify client registration:"
echo "     kubectl create deployment test-agent --image=busybox --namespace=team1 -- sleep 3600"
echo "     kubectl logs -n kagenti-system deployment/kagenti-controller-manager -c manager | grep test-agent"
echo ""
