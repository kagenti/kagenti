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

DEP_BUILDS="${KAGENTI_DEP_BUILDS:-}"
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

log_success "All dependency builds complete"
