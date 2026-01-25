#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../lib/env-detect.sh"
source "$SCRIPT_DIR/../lib/logging.sh"
source "$SCRIPT_DIR/../lib/k8s-utils.sh"

log_step "71" "Building weather-tool image"

# IS_OPENSHIFT is set by env-detect.sh (sourced above)
# It checks for OpenShift-specific APIs, not just "oc whoami" which works on any cluster
if [ "$IS_OPENSHIFT" = "true" ]; then
    log_info "Using OpenShift BuildConfig"
else
    log_info "Using Kind/Kubernetes AgentBuild"
fi

if [ "$IS_OPENSHIFT" = "true" ]; then
    # OpenShift: Use BuildConfig (native OpenShift builds)
    # This avoids Tekton pipeline issues on OpenShift

    kubectl apply -f "$REPO_ROOT/kagenti/examples/mcpservers/weather_tool_buildconfig.yaml"

    # Wait for BuildConfig to exist
    run_with_timeout 60 'until kubectl get buildconfig weather-tool -n team1 &> /dev/null; do sleep 2; done' || {
        log_error "BuildConfig not created after 60s"
        kubectl get buildconfigs -n team1
        exit 1
    }

    # Start a build
    log_info "Starting OpenShift build..."
    BUILD_NAME=$(oc start-build weather-tool -n team1 --follow=false -o name 2>/dev/null || echo "")
    if [ -z "$BUILD_NAME" ]; then
        log_error "Failed to start build"
        exit 1
    fi
    log_info "Build started: $BUILD_NAME"

    # Wait for build to complete
    for i in {1..120}; do
        phase=$(kubectl get "$BUILD_NAME" -n team1 -o jsonpath='{.status.phase}' 2>/dev/null || echo "Unknown")
        log_info "Build phase: $phase"
        if [ "$phase" = "Complete" ]; then
            log_success "OpenShift build completed successfully"
            exit 0
        elif [ "$phase" = "Failed" ] || [ "$phase" = "Error" ] || [ "$phase" = "Cancelled" ]; then
            log_error "Build failed with phase: $phase"
            kubectl describe "$BUILD_NAME" -n team1
            kubectl logs "$BUILD_NAME" -n team1 || true
            exit 1
        fi
        sleep 5
    done

    log_error "Build timeout after 600s"
    kubectl describe "$BUILD_NAME" -n team1
    exit 1
else
    # Kind/vanilla Kubernetes: Use AgentBuild (Tekton pipelines)

    kubectl apply -f "$REPO_ROOT/kagenti/examples/agents/weather_tool_build.yaml"

    # Wait for AgentBuild to exist
    run_with_timeout 300 'until kubectl get agentbuild weather-tool-build -n team1 &> /dev/null; do sleep 2; done' || {
        log_error "AgentBuild not created after 300s"
        kubectl get agentbuilds -n team1
        exit 1
    }

    # Wait for build to succeed
    for i in {1..60}; do
        phase=$(kubectl get agentbuild weather-tool-build -n team1 -o jsonpath='{.status.phase}' 2>/dev/null || echo "Unknown")
        log_info "AgentBuild phase: $phase"
        if [ "$phase" = "Succeeded" ]; then
            log_success "AgentBuild completed successfully"
            exit 0
        elif [ "$phase" = "Failed" ]; then
            log_error "AgentBuild failed"
            kubectl describe agentbuild weather-tool-build -n team1
            exit 1
        fi
        sleep 5
    done

    log_error "AgentBuild timeout"
    exit 1
fi
