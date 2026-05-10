#!/usr/bin/env bash
# Install Keycloak on OpenShift for token exchange E2E.
#
# Supports two modes:
#   community  — Keycloak community 26.6.0 (full SPIFFE + token exchange support)
#   rhbk       — RHBK operator via OperatorHub (stable-v26.4)
#
# Usage:
#   bash 35-install-keycloak-ocp.sh community
#   bash 35-install-keycloak-ocp.sh rhbk
#
# This script is only needed on OCP. On Kind, Keycloak is installed by setup-kagenti.sh.
set -euo pipefail
source "$(dirname "$0")/lib.sh"

MODE="${1:-community}"
KC_VERSION="${KC_VERSION:-26.6.0}"
FORCE="${FORCE:-false}"

log_step "35" "Install Keycloak on OCP (mode: $MODE)"

# Check for existing installation
if kubectl get keycloak keycloak -n "$KC_NAMESPACE" &>/dev/null; then
  if [[ "$FORCE" != "true" ]]; then
    log_warn "Keycloak already installed in $KC_NAMESPACE. Use FORCE=true to reinstall."
    exit 0
  fi
  log_warn "FORCE=true — removing existing Keycloak"
  kubectl delete keycloak keycloak -n "$KC_NAMESPACE" --ignore-not-found
  kubectl delete statefulset keycloak -n "$KC_NAMESPACE" --ignore-not-found
  kubectl delete statefulset postgres-kc -n "$KC_NAMESPACE" --ignore-not-found
  sleep 10
fi

kubectl create namespace "$KC_NAMESPACE" 2>/dev/null || true

if [[ "$MODE" == "community" ]]; then
  log_info "Installing community Keycloak $KC_VERSION"

  # Install CRDs and operator
  kubectl apply -f "https://raw.githubusercontent.com/keycloak/keycloak-k8s-resources/refs/tags/${KC_VERSION}/kubernetes/keycloaks.k8s.keycloak.org-v1.yml" -n "$KC_NAMESPACE" 2>/dev/null || true
  kubectl apply -f "https://raw.githubusercontent.com/keycloak/keycloak-k8s-resources/refs/tags/${KC_VERSION}/kubernetes/keycloakrealmimports.k8s.keycloak.org-v1.yml" -n "$KC_NAMESPACE" 2>/dev/null || true
  kubectl apply -f "https://raw.githubusercontent.com/keycloak/keycloak-k8s-resources/refs/tags/${KC_VERSION}/kubernetes/kubernetes.yml" -n "$KC_NAMESPACE"

  # PostgreSQL
  log_info "Deploying PostgreSQL for Keycloak"
  kubectl create secret generic keycloak-db-secret -n "$KC_NAMESPACE" \
    --from-literal=username=keycloak --from-literal=password=keycloak123 \
    --dry-run=client -o yaml | kubectl apply -f -

  cat <<EOF | kubectl apply -n "$KC_NAMESPACE" -f -
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: postgres-kc
spec:
  serviceName: postgres-kc
  replicas: 1
  selector:
    matchLabels:
      app: postgres-kc
  template:
    metadata:
      labels:
        app: postgres-kc
    spec:
      containers:
      - name: postgres
        image: mirror.gcr.io/postgres:17
        ports:
        - containerPort: 5432
        env:
        - name: POSTGRES_DB
          value: keycloak
        - name: POSTGRES_USER
          value: keycloak
        - name: POSTGRES_PASSWORD
          value: keycloak123
        - name: PGDATA
          value: /var/lib/postgresql/data/pgdata
        volumeMounts:
        - name: data
          mountPath: /var/lib/postgresql/data
  volumeClaimTemplates:
  - metadata:
      name: data
    spec:
      accessModes: ["ReadWriteOnce"]
      resources:
        requests:
          storage: 1Gi
---
apiVersion: v1
kind: Service
metadata:
  name: postgres-kc
spec:
  selector:
    app: postgres-kc
  ports:
  - port: 5432
    targetPort: 5432
EOF

  kubectl rollout status statefulset/postgres-kc -n "$KC_NAMESPACE" --timeout=2m 2>/dev/null || true

  # Determine hostname
  KC_HOST="${KEYCLOAK_HOST:-keycloak-keycloak.$(oc get ingresses.config/cluster -o jsonpath='{.spec.domain}' 2>/dev/null)}"

  # Deploy Keycloak CR
  log_info "Deploying Keycloak CR (community)"
  cat <<EOF | kubectl apply -n "$KC_NAMESPACE" -f -
apiVersion: k8s.keycloak.org/v2alpha1
kind: Keycloak
metadata:
  name: keycloak
spec:
  instances: 1
  hostname:
    hostname: ${KC_HOST}
    strict: false
    strictBackchannel: false
  proxy:
    headers: xforwarded
  features:
    enabled:
      - preview
      - token-exchange
      - admin-fine-grained-authz:v1
      - client-auth-federated:v1
      - spiffe:v1
  http:
    httpEnabled: true
  db:
    vendor: postgres
    host: postgres-kc
    port: 5432
    database: keycloak
    usernameSecret:
      name: keycloak-db-secret
      key: username
    passwordSecret:
      name: keycloak-db-secret
      key: password
EOF

elif [[ "$MODE" == "rhbk" ]]; then
  log_info "Installing RHBK operator via OperatorHub"

  cat <<EOF | kubectl apply -f -
apiVersion: operators.coreos.com/v1alpha1
kind: Subscription
metadata:
  name: rhbk-operator
  namespace: ${KC_NAMESPACE}
spec:
  channel: stable-v26.4
  name: rhbk-operator
  source: redhat-operators
  sourceNamespace: openshift-marketplace
  installPlanApproval: Automatic
EOF

  log_info "Waiting for RHBK operator..."
  for i in $(seq 1 30); do
    CSV=$(kubectl get csv -n "$KC_NAMESPACE" -o jsonpath='{.items[0].status.phase}' 2>/dev/null || true)
    if [[ "$CSV" == "Succeeded" ]]; then break; fi
    sleep 10
  done

  KC_HOST="${KEYCLOAK_HOST:-keycloak-keycloak.$(oc get ingresses.config/cluster -o jsonpath='{.spec.domain}' 2>/dev/null)}"

  log_info "Deploying Keycloak CR (RHBK)"
  cat <<EOF | kubectl apply -n "$KC_NAMESPACE" -f -
apiVersion: k8s.keycloak.org/v2alpha1
kind: Keycloak
metadata:
  name: keycloak
spec:
  instances: 1
  hostname:
    hostname: ${KC_HOST}
    strict: false
    strictBackchannel: false
  features:
    enabled:
      - preview
      - token-exchange
      - admin-fine-grained-authz:v1
      - client-auth-federated:v1
      - spiffe:v1
  unsupported:
    podTemplate:
      spec:
        containers:
          - name: keycloak
            env:
              - name: KC_HOSTNAME_URL
                value: "https://${KC_HOST}"
EOF
fi

# Wait for Keycloak readiness
log_info "Waiting for Keycloak to be ready..."
kubectl rollout status statefulset/keycloak -n "$KC_NAMESPACE" --timeout=5m 2>/dev/null || true

KC_READY=$(kubectl get pod keycloak-0 -n "$KC_NAMESPACE" -o jsonpath='{.status.containerStatuses[0].ready}' 2>/dev/null || true)
if [[ "$KC_READY" == "true" ]]; then
  log_success "Keycloak ($MODE) installed and ready"
else
  log_warn "Keycloak not ready yet — check: kubectl get pods -n $KC_NAMESPACE"
fi
