#!/usr/bin/env bash
# AuthBridge Weather (advanced) E2E — Keycloak token exchange + MCP inbound JWT
#
# Runs the verify flow from rossocortex (authbridge/demos/weather-agent):
#   deploy_and_verify_advanced.sh
#
# Prerequisites (same as platform E2E):
#   - Kind cluster with Rossoctl, Keycloak, team1, webhook + AuthBridge sidecars
#   - jq, curl, python3, git
#
# Source tree:
#   - Set ROSSOCTL_EXTENSIONS_ROOT to a local clone (faster, offline dev, or optional
#     companion rossocortex PR checkout in CI), or
#   - Leave unset: this script shallow-clones rossoctl/rossocortex (see refs below).
#
# Environment:
#   ROSSOCTL_EXTENSIONS_ROOT   Path to rossocortex repo (optional)
#   ROSSOCTL_EXTENSIONS_GIT_URL  Clone URL (default: https://github.com/rossoctl/rossocortex.git)
#   ROSSOCTL_EXTENSIONS_GIT_REF  Branch or tag (default: main). Pin in CI to a release tag once
#     authbridge/demos/weather-agent is included; verify with: git ls-remote --tags URL
#   NAMESPACE                 K8s namespace (default: team1)
#   OPERATOR_NAMESPACE        Operator namespace where keycloak-admin-secret is located (default: rossoctl-system)
#   SKIP_DEPLOY                 If 1, only run in-cluster verify (default: 0 = full deploy)
#   WEATHER_TOOL_ROLLOUT_TIMEOUT / WEATHER_AGENT_ROLLOUT_TIMEOUT / WEATHER_TOOL_KC_CLIENT_SEC
#   WEATHER_ADVANCED_PRUNE_LEGACY   Passed to deploy (default: 1 here — scale down wave-90 weather)
#
# Usage (called from run-e2e-tests.sh when RUN_AUTHBRIDGE_WEATHER_E2E=1):
#   ./.github/scripts/kind/91-run-authbridge-weather-e2e.sh
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
# shellcheck source=/dev/null
source "$SCRIPT_DIR/../lib/env-detect.sh"
# shellcheck source=/dev/null
source "$SCRIPT_DIR/../lib/logging.sh"

log_step "91" "AuthBridge Weather (advanced) E2E (rossocortex)"

if ! command -v jq &>/dev/null; then
    log_error "jq is required. Install jq or run from an environment with test deps."
    exit 1
fi

if ! command -v git &>/dev/null; then
    log_error "git is required to fetch rossocortex when ROSSOCTL_EXTENSIONS_ROOT is unset."
    exit 1
fi

export NAMESPACE="${NAMESPACE:-team1}"
export OPERATOR_NAMESPACE="${OPERATOR_NAMESPACE:-rossoctl-system}"

if ! kubectl get namespace "$NAMESPACE" &>/dev/null; then
    log_error "Namespace $NAMESPACE not found. Deploy the platform first."
    exit 1
fi

# Preflight: Keycloak admin credentials for setup_keycloak_weather_advanced.py / token exchange
# Note: keycloak-admin-secret is now in the operator namespace for security
if ! kubectl get secret keycloak-admin-secret -n "$OPERATOR_NAMESPACE" &>/dev/null; then
    log_error "Secret 'keycloak-admin-secret' not found in namespace '$OPERATOR_NAMESPACE'."
    log_error "The installer creates it in the operator namespace. Re-run platform deploy or create it (AuthBridge / Keycloak docs) before AuthBridge E2E."
    exit 1
fi
log_info "Preflight OK: keycloak-admin-secret present in $OPERATOR_NAMESPACE"

# Sync keycloak-admin-secret to the agent namespace.
# The client-registration sidecar (injected by the webhook) mounts this secret
# from the pod's namespace. Since operator#321 the secret lives only in
# rossoctl-system, so we replicate it for sidecar compatibility.
if ! kubectl get secret keycloak-admin-secret -n "$NAMESPACE" &>/dev/null; then
    log_info "Syncing keycloak-admin-secret to $NAMESPACE for client-registration sidecar..."
    kubectl get secret keycloak-admin-secret -n "$OPERATOR_NAMESPACE" -o json \
        | jq --arg ns "$NAMESPACE" '.metadata.namespace = $ns | del(.metadata.resourceVersion, .metadata.uid, .metadata.creationTimestamp, .metadata.ownerReferences)' \
        | kubectl apply -f -
    log_info "keycloak-admin-secret synced to $NAMESPACE"
fi

EXT_ROOT="${ROSSOCTL_EXTENSIONS_ROOT:-}"
# Trim trailing slash so path joins are never authbridge//...
if [[ -n "$EXT_ROOT" ]]; then
    EXT_ROOT="${EXT_ROOT%/}"
fi
CLONE_DIR=""

if [[ -n "$EXT_ROOT" ]]; then
    if [[ ! -f "$EXT_ROOT/authbridge/demos/weather-agent/deploy_and_verify_advanced.sh" ]]; then
        log_error "ROSSOCTL_EXTENSIONS_ROOT is set but deploy_and_verify_advanced.sh not found at:"
        log_error "  $EXT_ROOT/authbridge/demos/weather-agent/"
        exit 1
    fi
    log_info "Using ROSSOCTL_EXTENSIONS_ROOT: $EXT_ROOT"
else
    ROSSOCTL_EXTENSIONS_GIT_URL="${ROSSOCTL_EXTENSIONS_GIT_URL:-https://github.com/rossoctl/rossocortex.git}"
    ROSSOCTL_EXTENSIONS_GIT_REF="${ROSSOCTL_EXTENSIONS_GIT_REF:-main}"
    CLONE_DIR="${TMPDIR:-/tmp}/rossocortex-authbridge-e2e-$$"
    log_info "Cloning rossocortex (ref: $ROSSOCTL_EXTENSIONS_GIT_REF) to $CLONE_DIR"
    if ! git clone --depth 1 --single-branch --branch "$ROSSOCTL_EXTENSIONS_GIT_REF" \
        "$ROSSOCTL_EXTENSIONS_GIT_URL" "$CLONE_DIR" 2>/dev/null; then
        log_info "Shallow single-branch clone failed; trying full clone + checkout ($ROSSOCTL_EXTENSIONS_GIT_REF)"
        git clone "$ROSSOCTL_EXTENSIONS_GIT_URL" "$CLONE_DIR" || {
            log_error "git clone failed: $ROSSOCTL_EXTENSIONS_GIT_URL"
            exit 1
        }
        (cd "$CLONE_DIR" && git checkout "$ROSSOCTL_EXTENSIONS_GIT_REF") || {
            log_error "Could not checkout ref: $ROSSOCTL_EXTENSIONS_GIT_REF (branch or tag must exist on the remote)."
            log_error "Fix: set ROSSOCTL_EXTENSIONS_GIT_REF to a valid ref (e.g. main), or ROSSOCTL_EXTENSIONS_ROOT to a local clone with authbridge/demos/weather-agent/."
            log_error "List tags: git ls-remote --tags $ROSSOCTL_EXTENSIONS_GIT_URL | tail -5"
            rm -rf "$CLONE_DIR"
            exit 1
        }
    fi
    EXT_ROOT="$CLONE_DIR"
fi

DEMO_DIR="$EXT_ROOT/authbridge/demos/weather-agent"
if [[ ! -f "$DEMO_DIR/deploy_and_verify_advanced.sh" ]]; then
    log_error "deploy_and_verify_advanced.sh not found at $DEMO_DIR/"
    log_error "This ref of rossocortex does not include the AuthBridge weather advanced demo yet."
    log_error "Use ROSSOCTL_EXTENSIONS_ROOT pointing at a tree that contains authbridge/demos/weather-agent/, or merge the demo to upstream and retry."
    exit 1
fi
if [[ ! -x "$DEMO_DIR/deploy_and_verify_advanced.sh" ]]; then
    chmod +x "$DEMO_DIR/deploy_and_verify_advanced.sh" 2>/dev/null || true
fi

export SKIP_DEPLOY="${SKIP_DEPLOY:-0}"
# See rossocortex authbridge/demos/weather-agent/deploy_and_verify_advanced.sh for defaults
# (align with spec.progressDeadlineSeconds: 1800 on the advanced Deployments).
export WEATHER_TOOL_ROLLOUT_TIMEOUT="${WEATHER_TOOL_ROLLOUT_TIMEOUT:-1800s}"
export WEATHER_AGENT_ROLLOUT_TIMEOUT="${WEATHER_AGENT_ROLLOUT_TIMEOUT:-1800s}"
export WEATHER_TOOL_KC_CLIENT_SEC="${WEATHER_TOOL_KC_CLIENT_SEC:-900}"
# One Kind node: pytest leaves weather-service + weather-tool; scale them down in deploy script.
export WEATHER_ADVANCED_PRUNE_LEGACY="${WEATHER_ADVANCED_PRUNE_LEGACY:-1}"

cleanup() {
    if [[ -n "$CLONE_DIR" && -d "$CLONE_DIR" ]]; then
        log_info "Removing temp clone: $CLONE_DIR"
        rm -rf "$CLONE_DIR"
    fi
}
trap cleanup EXIT

log_info "Running: $DEMO_DIR/deploy_and_verify_advanced.sh (NAMESPACE=$NAMESPACE SKIP_DEPLOY=$SKIP_DEPLOY)"
( cd "$DEMO_DIR" && ./deploy_and_verify_advanced.sh ) || {
    log_error "AuthBridge Weather (advanced) E2E failed"
    exit 1
}

log_success "AuthBridge Weather (advanced) E2E passed"
