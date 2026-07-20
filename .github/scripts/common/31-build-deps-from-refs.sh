#!/usr/bin/env bash
# Build dependency images from custom refs.
#
# Reads ROSSOCTL_DEP_BUILDS env var (JSON array) and builds each dependency.
# Called from 70-deploy-rossoctl.sh between platform install and agent deploy.
#
# Format: ROSSOCTL_DEP_BUILDS='[{"repo":"rossoctl/rossocortex","ref":"fix/branch"}]'
#
# Supported dependencies (add new ones to the registry below):
#   rossoctl/rossocortex  — webhook + AuthBridge images
#   rossoctl/operator    — operator image
#
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../lib/env-detect.sh"
source "$SCRIPT_DIR/../lib/logging.sh"
# Note that we set SCRIPT_DIR again *after* running the above scripts,
# as env-detect.sh overrides SCRIPT_DIR.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# No hardcoded defaults — chart deps are up-to-date (webhook v0.4.0-alpha.9).
# Use /run-e2e --build org/repo=ref to override ad-hoc.

DEP_BUILDS="${ROSSOCTL_DEP_BUILDS:-}"
if [ -z "$DEP_BUILDS" ] || [ "$DEP_BUILDS" = "[]" ]; then
    log_info "No dependency builds requested (ROSSOCTL_DEP_BUILDS empty)"
    exit 0
fi

log_step "31" "Building dependencies from custom refs"

# ─────────────────────────────────────────────────────────────────────────────
# Dependency registry: maps org/repo to build configuration
# Add new dependencies here.
# ─────────────────────────────────────────────────────────────────────────────
build_dep() {
    local repo="$1"
    local ref="$2"

    case "$repo" in
        rossoctl/rossocortex)
            # Build the proxy-init image from rossocortex.
            # (The sidecar-injection webhook formerly built here moved to
            # rossoctl/operator — see that case below. The only
            # image still built from rossocortex is proxy-init.)
            # DEP_SKIP_PATCH=true because proxy-init is an init container
            # image, not a deployment.
            log_info "Building proxy-init from ${repo}@${ref}"
            DEP_REPO="$repo" \
            DEP_REF="$ref" \
            DEP_CONTEXT="AuthBridge/AuthProxy" \
            DEP_IMAGE_NAME="proxy-init" \
            DEP_DEPLOY_NS="rossoctl-webhook-system" \
            DEP_DOCKERFILE="Dockerfile.init" \
            DEP_SKIP_PATCH="true" \
            bash "$SCRIPT_DIR/30-build-dep-image.sh"
            ;;
        rossoctl/operator)
            log_info "Building rossoctl-operator from ${repo}@${ref}"
            DEP_REPO="$repo" \
            DEP_REF="$ref" \
            DEP_CONTEXT="." \
            DEP_IMAGE_NAME="rossoctl-operator" \
            DEP_DEPLOY_NS="rossoctl-system" \
            DEP_HELM_SET="operator-chart.controllerManager.container.image" \
            bash "$SCRIPT_DIR/30-build-dep-image.sh"
            ;;
        *)
            log_error "Unknown dependency repo: ${repo}"
            log_error "Add it to the registry in 31-build-deps-from-refs.sh"
            exit 1
            ;;
    esac
}

# Parse JSON array and build each dependency
# Format: [{"repo":"org/name","ref":"branch-or-pr/123"}, ...]
echo "$DEP_BUILDS" | python3 -c "
import json, sys
builds = json.load(sys.stdin)
for b in builds:
    print(f\"{b['repo']} {b['ref']}\")
" | while read -r repo ref; do
    build_dep "$repo" "$ref"
done

# On OpenShift: patch the webhook ConfigMap to use internal registry images.
# The ConfigMap stores image refs that the webhook uses for sidecar injection.
# Without this, the webhook would reference GHCR images instead of our builds.
if [ "$IS_OPENSHIFT" = "true" ]; then
    INTERNAL_REGISTRY="image-registry.openshift-image-registry.svc:5000"
    WH_NS="rossoctl-webhook-system"
    CM_NAME=$(kubectl get configmap -n "$WH_NS" -l app.kubernetes.io/component=platform-defaults -o name 2>/dev/null | head -1)
    if [ -n "$CM_NAME" ]; then
        # Override individual sidecar images via env vars (default: only proxy-init from local build)
        # Set ROSSOCTL_PROXY_INIT_IMAGE, ROSSOCTL_ENVOY_PROXY_IMAGE, etc. to override
        # TODO: Build all sidecar images from source (envoy-with-processor, client-registration,
        # spiffe-helper) and default their overrides to the local builds. Currently only
        # proxy-init is built; other images use GHCR versions from the chart.
        PROXY_INIT_IMAGE="${ROSSOCTL_PROXY_INIT_IMAGE:-${INTERNAL_REGISTRY}/${WH_NS}/proxy-init:latest}"
        ENVOY_PROXY_IMAGE="${ROSSOCTL_ENVOY_PROXY_IMAGE:-}"
        CLIENT_REG_IMAGE="${ROSSOCTL_CLIENT_REG_IMAGE:-}"
        SPIFFE_HELPER_IMAGE="${ROSSOCTL_SPIFFE_HELPER_IMAGE:-}"

        log_info "Patching webhook ConfigMap with sidecar image overrides..."
        log_info "  proxyInit: ${PROXY_INIT_IMAGE}"
        [ -n "$ENVOY_PROXY_IMAGE" ] && log_info "  envoyProxy: ${ENVOY_PROXY_IMAGE}"
        [ -n "$CLIENT_REG_IMAGE" ] && log_info "  clientRegistration: ${CLIENT_REG_IMAGE}"
        [ -n "$SPIFFE_HELPER_IMAGE" ] && log_info "  spiffeHelper: ${SPIFFE_HELPER_IMAGE}"

        kubectl get "$CM_NAME" -n "$WH_NS" -o json | python3 -c "
import json, sys, yaml, os
cm = json.load(sys.stdin)
config = yaml.safe_load(cm['data'].get('config.yaml', '{}')) or {}
images = config.setdefault('images', {})
overrides = {
    'proxyInit': '${PROXY_INIT_IMAGE}',
    'envoyProxy': '${ENVOY_PROXY_IMAGE}',
    'clientRegistration': '${CLIENT_REG_IMAGE}',
    'spiffeHelper': '${SPIFFE_HELPER_IMAGE}',
}
for key, val in overrides.items():
    if val:  # only override if set
        images[key] = val
cm['data']['config.yaml'] = yaml.dump(config, default_flow_style=False)
print(json.dumps(cm))
" | kubectl apply -f - 2>/dev/null && log_success "ConfigMap patched" || log_info "ConfigMap patch skipped (not found or not applicable)"
        # Restart webhook to pick up new config
        kubectl rollout restart deployment -n "$WH_NS" 2>/dev/null || true
        kubectl rollout status deployment -n "$WH_NS" --timeout=120s 2>/dev/null || true

        # Grant agent namespaces pull access to webhook-system images.
        # The webhook injects sidecar images (proxy-init, envoy) from the webhook
        # namespace. Without cross-namespace pull access, pods get ImagePullBackOff.
        log_info "Granting agent namespaces pull access to ${WH_NS} images..."
        for NS in $(kubectl get namespaces -l rossoctl-enabled=true -o jsonpath='{.items[*].metadata.name}' 2>/dev/null); do
            # Allow the default SA in each agent namespace to pull from webhook-system
            oc policy add-role-to-user system:image-puller "system:serviceaccount:${NS}:default" \
                -n "$WH_NS" 2>/dev/null || true
            # Also the specific agent SA if it exists
            for SA in $(kubectl get sa -n "$NS" -o jsonpath='{.items[*].metadata.name}' 2>/dev/null | tr ' ' '\n' | grep -v "^builder$\|^deployer$\|^default$\|^pipeline$"); do
                oc policy add-role-to-user system:image-puller "system:serviceaccount:${NS}:${SA}" \
                    -n "$WH_NS" 2>/dev/null || true
            done
            log_info "  ${NS}: pull access granted"
        done
    else
        log_info "No webhook ConfigMap found — webhook will use compiled defaults"
    fi
fi

log_success "All dependency builds complete"
