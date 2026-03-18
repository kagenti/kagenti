#!/usr/bin/env bash
# Build dependency images from custom refs.
#
# Reads KAGENTI_DEP_BUILDS env var (JSON array) and builds each dependency.
# Called from 70-deploy-kagenti.sh between platform install and agent deploy.
#
# Format: KAGENTI_DEP_BUILDS='[{"repo":"kagenti/kagenti-extensions","ref":"fix/branch"}]'
#
# Supported dependencies (add new ones to the registry below):
#   kagenti/kagenti-extensions  — webhook + AuthBridge images
#   kagenti/kagenti-operator    — operator image
#
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../lib/env-detect.sh"
source "$SCRIPT_DIR/../lib/logging.sh"

# Default: build webhook from extensions main (proxy-init fix not yet released)
# TODO: Remove this default after bumping kagenti-webhook-chart to >= v0.4.0-alpha.9
# SHADOW TEST: pin to extensions post-#242 but pre-#248
if [ -z "${KAGENTI_DEP_BUILDS:-}" ] || [ "${KAGENTI_DEP_BUILDS:-}" = "[]" ]; then
    export KAGENTI_DEP_BUILDS='[{"repo":"kagenti/kagenti-extensions","ref":"9eb014bc"}]'
fi

DEP_BUILDS="${KAGENTI_DEP_BUILDS}"
if [ -z "$DEP_BUILDS" ] || [ "$DEP_BUILDS" = "[]" ]; then
    log_info "No dependency builds requested (KAGENTI_DEP_BUILDS empty)"
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
        kagenti/kagenti-extensions)
            log_info "Building kagenti-webhook from ${repo}@${ref}"
            DEP_REPO="$repo" \
            DEP_REF="$ref" \
            DEP_CONTEXT="kagenti-webhook" \
            DEP_IMAGE_NAME="kagenti-webhook" \
            DEP_DEPLOY_NS="kagenti-webhook-system" \
            DEP_HELM_SET="kagenti-webhook-chart.image" \
            bash "$SCRIPT_DIR/30-build-dep-image.sh"

            # Also build the proxy-init image — the webhook references it
            # by tag (proxy-init:latest). We must build and load it so the
            # init container uses the version matching the webhook binary.
            # DEP_SKIP_PATCH=true because proxy-init is an init container
            # image, not a deployment.
            log_info "Building proxy-init from ${repo}@${ref}"
            DEP_REPO="$repo" \
            DEP_REF="$ref" \
            DEP_CONTEXT="AuthBridge/AuthProxy" \
            DEP_IMAGE_NAME="proxy-init" \
            DEP_DEPLOY_NS="kagenti-webhook-system" \
            DEP_DOCKERFILE="Dockerfile.init" \
            DEP_SKIP_PATCH="true" \
            bash "$SCRIPT_DIR/30-build-dep-image.sh"
            ;;
        kagenti/kagenti-operator)
            log_info "Building kagenti-operator from ${repo}@${ref}"
            DEP_REPO="$repo" \
            DEP_REF="$ref" \
            DEP_CONTEXT="." \
            DEP_IMAGE_NAME="kagenti-operator" \
            DEP_DEPLOY_NS="kagenti-system" \
            DEP_HELM_SET="kagenti-operator-chart.controllerManager.container.image" \
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
    WH_NS="kagenti-webhook-system"
    CM_NAME=$(kubectl get configmap -n "$WH_NS" -l app.kubernetes.io/component=platform-defaults -o name 2>/dev/null | head -1)
    if [ -n "$CM_NAME" ]; then
        log_info "Patching webhook ConfigMap with internal registry images..."
        kubectl get "$CM_NAME" -n "$WH_NS" -o json | python3 -c "
import json, sys, yaml
cm = json.load(sys.stdin)
config = yaml.safe_load(cm['data'].get('config.yaml', '{}')) or {}
images = config.setdefault('images', {})
reg = '${INTERNAL_REGISTRY}/${WH_NS}'
images['proxyInit'] = f'{reg}/proxy-init:latest'
images['envoyProxy'] = f'{reg}/kagenti-webhook:latest'
cm['data']['config.yaml'] = yaml.dump(config, default_flow_style=False)
print(json.dumps(cm))
" | kubectl apply -f - 2>/dev/null && log_success "ConfigMap patched" || log_info "ConfigMap patch skipped (not found or not applicable)"
        # Restart webhook to pick up new config
        kubectl rollout restart deployment -n "$WH_NS" 2>/dev/null || true
        kubectl rollout status deployment -n "$WH_NS" --timeout=120s 2>/dev/null || true
    else
        log_info "No webhook ConfigMap found — webhook will use compiled defaults"
    fi
fi

log_success "All dependency builds complete"
