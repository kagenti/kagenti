#!/usr/bin/env bash
# ============================================================================
# Shared Rossoctl dependency installers
# ============================================================================
# Library of bash functions used by the Kind and vanilla-Kubernetes entry
# points (scripts/kind/setup-rossoctl.sh and scripts/k8s/setup-rossoctl.sh).
#
# Functions install upstream third-party components onto an existing
# Kubernetes cluster using kubectl/helm against the caller's KUBECONFIG.
# They are NOT cluster-creators — Kind cluster bring-up stays in the Kind
# entry point.
#
# The sourcing entry point is expected to provide:
#   - log_info, log_success, log_warn, log_error  (output helpers)
#   - run_cmd                                     (dry-run wrapper)
#   - _wait_deployment_ready                      (rollout wait helper)
#   - DRY_RUN                                     (boolean variable)
#
# Each install_* function declares its required pinned version constants
# locally (with caller-overridable defaults) so this lib can be sourced
# standalone without depending on a particular caller's variable layout.
# ============================================================================

# Guard against double-sourcing.
if [[ "${__ROSSOCTL_INSTALL_DEPS_SH_SOURCED:-}" == "1" ]]; then
  return 0
fi
__ROSSOCTL_INSTALL_DEPS_SH_SOURCED=1

# ----------------------------------------------------------------------------
# install_tekton
# ----------------------------------------------------------------------------
# Installs Tekton Pipelines from the upstream release manifest at a pinned
# version. Idempotent — kubectl apply --server-side handles re-runs.
#
# Usage: install_tekton [version]
#   version: Tekton release tag (default: $TEKTON_VERSION env, then v0.66.0)
# ----------------------------------------------------------------------------
install_tekton() {
  local version="${1:-${TEKTON_VERSION:-v0.66.0}}"
  log_info "Installing Tekton ${version}..."
  run_cmd kubectl apply --server-side \
    -f "https://storage.googleapis.com/tekton-releases/pipeline/previous/${version}/release.yaml"
  log_success "Tekton applied"
}

# ----------------------------------------------------------------------------
# install_shipwright
# ----------------------------------------------------------------------------
# Installs Shipwright Build Controller from the upstream release manifest at
# a pinned version, configures cert-manager-issued TLS for the admission
# webhook, and applies sample build strategies plus the buildah-insecure-push
# strategy used for in-cluster registries.
#
# Prerequisites:
#   - cert-manager installed and ready (a ClusterIssuer/Issuer is created
#     by this function; cert-manager itself must already be running)
#   - Tekton installed (Shipwright depends on Tekton)
#
# Usage: install_shipwright [version]
#   version: Shipwright release tag (default: $SHIPWRIGHT_VERSION env, then v0.14.0)
# ----------------------------------------------------------------------------
install_shipwright() {
  local version="${1:-${SHIPWRIGHT_VERSION:-v0.14.0}}"

  log_info "Installing Shipwright ${version}..."
  run_cmd kubectl apply --server-side \
    -f "https://github.com/shipwright-io/build/releases/download/${version}/release.yaml"

  if $DRY_RUN; then
    log_success "Shipwright applied (dry-run)"
    return 0
  fi

  kubectl wait --for=jsonpath='{.status.phase}'=Active namespace/shipwright-build --timeout=30s 2>/dev/null || true

  configure_shipwright_webhook_tls

  # Sample build strategies (best-effort).
  kubectl apply --server-side \
    -f "https://github.com/shipwright-io/build/releases/download/${version}/sample-strategies.yaml" \
    2>/dev/null || true

  install_buildah_insecure_push_strategy

  log_success "Shipwright installed"
}

# ----------------------------------------------------------------------------
# configure_shipwright_webhook_tls
# ----------------------------------------------------------------------------
# Wires up cert-manager to issue TLS for the Shipwright admission webhook:
#   1. Create a self-signed ClusterIssuer
#   2. Create a CA Certificate signed by the ClusterIssuer
#   3. Create an Issuer that uses the CA
#   4. Create a webhook Certificate with the right DNS SANs
#   5. Annotate Shipwright CRDs for CA injection
#   6. Restart the webhook to pick up the new TLS material
#
# Without this the Shipwright admission webhook will not have valid TLS and
# Build/BuildRun resources will be rejected.
# ----------------------------------------------------------------------------
configure_shipwright_webhook_tls() {
  if $DRY_RUN; then
    log_info "[dry-run] would configure cert-manager TLS for Shipwright webhook"
    return 0
  fi

  kubectl apply -f - <<'EOF'
apiVersion: cert-manager.io/v1
kind: ClusterIssuer
metadata:
  name: shipwright-selfsigned-issuer
spec:
  selfSigned: {}
EOF

  kubectl apply -f - <<EOF
apiVersion: cert-manager.io/v1
kind: Certificate
metadata:
  name: shipwright-ca
  namespace: shipwright-build
spec:
  isCA: true
  commonName: shipwright-ca
  secretName: shipwright-ca-secret
  duration: 26280h
  privateKey:
    algorithm: ECDSA
    size: 256
  issuerRef:
    name: shipwright-selfsigned-issuer
    kind: ClusterIssuer
EOF
  kubectl wait --for=condition=Ready certificate/shipwright-ca \
    -n shipwright-build --timeout=60s 2>/dev/null || true

  kubectl apply -f - <<'EOF'
apiVersion: cert-manager.io/v1
kind: Issuer
metadata:
  name: shipwright-ca-issuer
  namespace: shipwright-build
spec:
  ca:
    secretName: shipwright-ca-secret
---
apiVersion: cert-manager.io/v1
kind: Certificate
metadata:
  name: shipwright-build-webhook-cert
  namespace: shipwright-build
spec:
  secretName: shipwright-build-webhook-cert
  duration: 8760h
  renewBefore: 720h
  dnsNames:
    - shp-build-webhook
    - shp-build-webhook.shipwright-build
    - shp-build-webhook.shipwright-build.svc
    - shp-build-webhook.shipwright-build.svc.cluster.local
  issuerRef:
    name: shipwright-ca-issuer
    kind: Issuer
EOF
  kubectl wait --for=condition=Ready certificate/shipwright-build-webhook-cert \
    -n shipwright-build --timeout=60s 2>/dev/null || true

  for crd in clusterbuildstrategies.shipwright.io buildstrategies.shipwright.io \
             builds.shipwright.io buildruns.shipwright.io; do
    kubectl annotate crd "$crd" \
      cert-manager.io/inject-ca-from=shipwright-build/shipwright-build-webhook-cert \
      --overwrite 2>/dev/null || true
  done

  kubectl rollout restart deployment/shipwright-build-webhook -n shipwright-build 2>/dev/null || true
  _wait_deployment_ready shipwright-build-webhook shipwright-build "Shipwright webhook"
}

# ----------------------------------------------------------------------------
# install_buildah_insecure_push_strategy
# ----------------------------------------------------------------------------
# Applies the buildah-insecure-push ClusterBuildStrategy used for pushing to
# in-cluster HTTP registries (no TLS).
# ----------------------------------------------------------------------------
install_buildah_insecure_push_strategy() {
  log_info "Installing buildah-insecure-push ClusterBuildStrategy..."
  kubectl apply -f - <<'STRATEGY_EOF'
apiVersion: shipwright.io/v1beta1
kind: ClusterBuildStrategy
metadata:
  name: buildah-insecure-push
spec:
  parameters:
    - name: dockerfile
      description: Path to the Dockerfile
      type: string
      default: Dockerfile
    - name: build-args
      description: Build arguments in KEY=VALUE format
      type: array
      defaults: []
    - name: storage-driver
      description: The storage driver to use (overlay or vfs)
      type: string
      default: vfs
  securityContext:
    runAsUser: 0
    runAsGroup: 0
  steps:
    - name: build-and-push
      image: quay.io/containers/buildah:v1.37.5
      workingDir: $(params.shp-source-root)
      securityContext:
        capabilities:
          add:
            - SETFCAP
      command:
        - /bin/bash
      args:
        - -c
        - |
          set -euo pipefail

          BUILD_ARGS=()
          for arg in "$@"; do
            if [[ "$arg" == "--build-arg="* ]]; then
              BUILD_ARGS+=("--build-arg" "${arg#--build-arg=}")
            fi
          done

          echo "Building image..."
          buildah --storage-driver=$(params.storage-driver) bud \
            "${BUILD_ARGS[@]}" \
            -f "$(params.shp-source-context)/$(params.dockerfile)" \
            -t "$(params.shp-output-image)" \
            "$(params.shp-source-context)"

          echo "Pushing image to $(params.shp-output-image)..."
          buildah --storage-driver=$(params.storage-driver) push \
            --tls-verify=false \
            "$(params.shp-output-image)" \
            "docker://$(params.shp-output-image)"

          echo "Build and push completed successfully!"
        - --
        - $(params.build-args[*])
      resources:
        limits:
          cpu: "1"
          memory: 2Gi
        requests:
          cpu: 250m
          memory: 256Mi
STRATEGY_EOF
}
