#!/usr/bin/env bash
set -euo pipefail

# Setup script for operator SPIFFE authentication E2E test
# This script installs Kagenti with:
# - SPIRE for workload identity
# - Local operator image (localhost/kagenti-operator:spiffe-test)
# - Local bootstrap image (ghcr.io/kagenti/kagenti/operator-spiffe-bootstrap:latest)
# - Operator component enabled (components.agentOperator.enabled: true)
# - Operator SPIFFE auth enabled (spiffe.operatorAuth.enabled: true)
#
# Prerequisites:
# - Kind cluster running
# - Custom images loaded: kind load image-archive <operator.tar> <bootstrap.tar> --name kagenti
# - kubectl configured for the Kind cluster
# - Helm 3 installed
#
# Expected time: 15-20 minutes (helm --wait installs can be slow)
# Output: All logs to stdout with colored status indicators

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log_info() { echo -e "${GREEN}→${NC} $*"; }
log_success() { echo -e "${GREEN}✓${NC} $*"; }
log_warn() { echo -e "${YELLOW}⚠${NC} $*"; }
log_error() { echo -e "${RED}✗${NC} $*"; }

# Verify prerequisites
log_info "Checking prerequisites..."

if ! command -v kubectl &>/dev/null; then
  log_error "kubectl not found"
  exit 1
fi

if ! command -v helm &>/dev/null; then
  log_error "helm not found"
  exit 1
fi

if ! kubectl cluster-info &>/dev/null; then
  log_error "No Kubernetes cluster access"
  exit 1
fi

# Note: Image verification skipped - the setup will proceed and pods will use imagePullPolicy: Never
# which will fail if images aren't loaded. Verify manually with:
# docker exec -i kagenti-control-plane crictl images | grep -E "kagenti-operator|bootstrap"
log_info "Assuming custom images are loaded (verify manually if pods fail)"

# Install cert-manager
log_info "Installing cert-manager..."
kubectl apply -f https://github.com/cert-manager/cert-manager/releases/download/v1.17.2/cert-manager.yaml
kubectl wait --for=condition=ready pod -l app.kubernetes.io/instance=cert-manager -n cert-manager --timeout=300s
log_success "cert-manager installed"

# Install Istio
log_info "Installing Istio..."
helm upgrade --install istio-base istio/base --version 1.28.0 -n istio-system --create-namespace --wait
helm upgrade --install istiod istio/istiod --version 1.28.0 -n istio-system --wait
log_success "Istio installed"

# Skip Gateway API CRDs - kagenti-deps chart will install them
log_info "Skipping Gateway API CRDs (kagenti-deps will install them)"

# Install SPIRE
log_info "Installing SPIRE..."
helm upgrade --install spire-crds spire-crds \
  --repo https://spiffe.github.io/helm-charts-hardened/ \
  --version 0.5.0 \
  -n spire-mgmt --create-namespace --wait

helm upgrade --install spire spire \
  --repo https://spiffe.github.io/helm-charts-hardened/ \
  --version 0.27.0 \
  -n spire-mgmt --create-namespace \
  --set global.spire.recommendations.enabled=true \
  --set global.spire.namespaces.create=true \
  --set global.spire.namespaces.server.name=zero-trust-workload-identity-manager \
  --set global.spire.namespaces.server.create=true \
  --set-string "global.spire.namespaces.server.labels.shared-gateway-access=true" \
  --set global.spire.ingressControllerType="" \
  --set global.spire.clusterName=agent-platform \
  --set "global.spire.trustDomain=localtest.me" \
  --set "global.spire.caSubject.country=US" \
  --set "global.spire.caSubject.organization=AgenticPlatformDemo" \
  --set "global.spire.caSubject.commonName=localtest.me" \
  --set spire-server.tornjak.enabled=true \
  --set "spire-server.controllerManager.ignoreNamespaces={kube-system,kube-public}" \
  --set spire-server.controllerManager.identities.clusterSPIFFEIDs.default.autoPopulateDNSNames=true \
  --set spire-server.controllerManager.identities.clusterSPIFFEIDs.default.jwtTTL=5m \
  --set spiffe-oidc-discovery-provider.enabled=true \
  --set spiffe-oidc-discovery-provider.config.set_key_use=true \
  --set spiffe-oidc-discovery-provider.tls.spire.enabled=false

kubectl wait --for=condition=ready pod -l app.kubernetes.io/name=server -n zero-trust-workload-identity-manager --timeout=300s
log_success "SPIRE installed"

# Install kagenti-deps (Keycloak, etc) without IdP setup
log_info "Installing kagenti-deps (Keycloak, etc)..."
helm upgrade --install kagenti-deps charts/kagenti-deps/ \
  -n kagenti-system --create-namespace --wait --timeout 20m \
  --set components.keycloak.enabled=true \
  --set components.spire.enabled=true \
  --set components.ingressGateway.enabled=true \
  --set domain=localtest.me \
  --set openshift=false

kubectl wait --for=condition=ready pod -l app=keycloak -n keycloak --timeout=300s
log_success "kagenti-deps installed"

# Create RBAC for manual IdP setup job
log_info "Creating RBAC for IdP setup..."
cat <<EOF | kubectl apply -f -
apiVersion: v1
kind: ServiceAccount
metadata:
  name: kagenti-spiffe-idp-setup
  namespace: kagenti-system
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: kagenti-spiffe-idp-reader
rules:
- apiGroups: [""]
  resources: ["secrets"]
  resourceNames: ["keycloak-initial-admin"]
  verbs: ["get"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: kagenti-spiffe-idp-keycloak-reader
  namespace: keycloak
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: ClusterRole
  name: kagenti-spiffe-idp-reader
subjects:
- kind: ServiceAccount
  name: kagenti-spiffe-idp-setup
  namespace: kagenti-system
---
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: kagenti-spiffe-idp-pod-reader
  namespace: kagenti-system
rules:
- apiGroups: [""]
  resources: ["pods"]
  verbs: ["get", "list"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: kagenti-spiffe-idp-pod-reader
  namespace: kagenti-system
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: Role
  name: kagenti-spiffe-idp-pod-reader
subjects:
- kind: ServiceAccount
  name: kagenti-spiffe-idp-setup
  namespace: kagenti-system
EOF

# Run IdP setup with local bootstrap image
log_info "Running SPIFFE IdP setup with local bootstrap image..."
cat <<EOF | kubectl apply -f -
apiVersion: batch/v1
kind: Job
metadata:
  name: kagenti-spiffe-idp-setup-job
  namespace: kagenti-system
spec:
  ttlSecondsAfterFinished: 300
  template:
    metadata:
      labels:
        app: kagenti-spiffe-idp-setup
    spec:
      restartPolicy: OnFailure
      serviceAccountName: kagenti-spiffe-idp-setup
      containers:
        - name: setup-spiffe-idp
          image: ghcr.io/kagenti/kagenti/operator-spiffe-bootstrap:latest
          imagePullPolicy: Never
          env:
            - name: KEYCLOAK_BASE_URL
              value: "http://keycloak-service.keycloak.svc:8080"
            - name: KEYCLOAK_REALM
              value: "kagenti"
            - name: KEYCLOAK_NAMESPACE
              value: "keycloak"
            - name: KEYCLOAK_ADMIN_SECRET_NAME
              value: "keycloak-initial-admin"
            - name: KEYCLOAK_ADMIN_USERNAME_KEY
              value: "username"
            - name: KEYCLOAK_ADMIN_PASSWORD_KEY
              value: "password"
            - name: SPIRE_OIDC_URL
              value: "http://spire-spiffe-oidc-discovery-provider.zero-trust-workload-identity-manager.svc.cluster.local"
            - name: SPIFFE_TRUST_DOMAIN
              value: "localtest.me"
            - name: SPIFFE_IDP_ALIAS
              value: "spire-spiffe"
            - name: OPERATOR_NAMESPACE
              value: "kagenti-system"
            - name: OPERATOR_SERVICE_ACCOUNT
              value: "controller-manager"
EOF

kubectl wait --for=condition=complete job/kagenti-spiffe-idp-setup-job -n kagenti-system --timeout=180s
log_success "SPIFFE IdP setup completed"

# Install kagenti with operator SPIFFE auth enabled
log_info "Installing kagenti with operator SPIFFE auth..."

# Run helm dependency update to pull other chart dependencies, then remove the
# OCI operator tarball and Chart.lock so helm uses the committed
# charts/kagenti/charts/kagenti-operator-chart/ directory (which contains the
# spiffe-helper sidecar template required for SPIFFE auth). The published OCI
# chart does not include these changes.
helm dependency update charts/kagenti
rm -f charts/kagenti/charts/kagenti-operator-chart-*.tgz
rm -f charts/kagenti/Chart.lock
log_info "Using committed operator subchart with spiffe-helper support"

cat > /tmp/kagenti-spiffe-test-values.yaml <<EOF
# Use local operator image
kagenti-operator-chart:
  controllerManager:
    container:
      image:
        repository: localhost/kagenti-operator
        tag: spiffe-test
        pullPolicy: Never
  spiffe:
    enabled: true
    operatorAuth:
      enabled: true
      spiffeHelper:
        jwtAudience: "http://keycloak.localtest.me:8080/realms/kagenti"

# Kind/Kubernetes overrides
openshift: false
components:
  agentOperator:
    enabled: true
  ui:
    route:
      enabled: false
securityContextConstraints:
  enabled: false
mcpGateway:
  openshiftDomain: dummy.local
  route:
    enabled: false
EOF

helm upgrade --install kagenti charts/kagenti/ \
  -n kagenti-system \
  --values deployments/envs/dev_values.yaml \
  --values /tmp/kagenti-spiffe-test-values.yaml \
  --timeout 15m \
  --wait

log_success "kagenti installed"

# Verify deployment
log_info "Verifying deployment..."
kubectl get pod -n kagenti-system -l control-plane=controller-manager
kubectl wait --for=condition=ready pod -l control-plane=controller-manager -n kagenti-system --timeout=300s
log_success "Operator is ready"

echo ""
log_success "✓ Setup complete!"
echo ""
echo "Operator pod:"
kubectl get pod -n kagenti-system -l control-plane=controller-manager
echo ""
echo "Check operator logs:"
echo "  kubectl logs -n kagenti-system -l control-plane=controller-manager -c manager | grep -i spiffe"
