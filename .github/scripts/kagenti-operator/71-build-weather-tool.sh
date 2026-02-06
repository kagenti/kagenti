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
    log_info "Using Kind/Kubernetes Shipwright Build"
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
    for _ in {1..120}; do
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
    # Kind/vanilla Kubernetes: Use Shipwright Build + BuildRun

    # Clean up previous Build to avoid conflicts
    kubectl delete builds.shipwright.io weather-tool -n team1 --ignore-not-found 2>/dev/null || true
    sleep 2

    # Apply build manifest
    log_info "Creating Shipwright Build..."
    kubectl apply -f "$REPO_ROOT/kagenti/examples/tools/weather_tool_shipwright_build.yaml"

    # Wait for Shipwright Build to be registered
    run_with_timeout 60 'until kubectl get builds.shipwright.io weather-tool -n team1 &> /dev/null; do sleep 2; done' || {
        log_error "Shipwright Build not found after 60 seconds"
        log_info "Available Shipwright Builds in team1:"
        kubectl get builds.shipwright.io -n team1 2>&1 || echo "  (none or error)"
        log_info "Available ClusterBuildStrategies:"
        kubectl get clusterbuildstrategies.shipwright.io 2>&1 || echo "  (none or error)"
        log_info "Recent Events in team1:"
        kubectl get events -n team1 --sort-by='.lastTimestamp' 2>&1 | tail -20 || echo "  (none)"
        exit 1
    }
    log_info "Shipwright Build created"

    # Create BuildRun to trigger the build
    log_info "Triggering BuildRun..."
    BUILDRUN_NAME=$(kubectl create -f "$REPO_ROOT/kagenti/examples/tools/weather_tool_shipwright_buildrun.yaml" -o jsonpath='{.metadata.name}')
    log_info "BuildRun created: $BUILDRUN_NAME"

    # Wait for BuildRun to complete
    log_info "Waiting for BuildRun to complete (this may take a few minutes)..."
    run_with_timeout 600 "kubectl wait --for=condition=Succeeded --timeout=600s buildrun/$BUILDRUN_NAME -n team1" || {
        log_error "BuildRun did not succeed"

        # Get BuildRun status for debugging
        log_info "BuildRun status:"
        kubectl get buildrun "$BUILDRUN_NAME" -n team1 -o yaml

        # Check if the failure is just sidecar cleanup (image may still be built)
        FAILURE_REASON=$(kubectl get buildrun "$BUILDRUN_NAME" -n team1 -o jsonpath='{.status.conditions[?(@.type=="Succeeded")].reason}' 2>/dev/null || echo "")
        if [ "$FAILURE_REASON" = "TaskRunStopSidecarFailed" ]; then
            log_info "BuildRun failed due to sidecar cleanup issue, checking if image was built..."

            # For Kind, check if the build step completed successfully
            IMAGE_EXISTS=$(kubectl get pods -n team1 -l build.shipwright.io/name=weather-tool -o jsonpath='{.items[0].status.containerStatuses[?(@.name=="step-build-and-push")].state.terminated.exitCode}' 2>/dev/null || echo "")
            if [ "$IMAGE_EXISTS" = "0" ]; then
                IMAGE_EXISTS="yes"
            else
                IMAGE_EXISTS="no"
            fi

            if [ "$IMAGE_EXISTS" = "yes" ]; then
                log_info "Image was built successfully despite sidecar cleanup failure. Proceeding..."
            else
                log_error "Image not found in registry. Build actually failed."
                # Get build pod logs
                log_info "Build pod logs:"
                BUILD_POD=$(kubectl get pods -n team1 -l build.shipwright.io/name=weather-tool --sort-by=.metadata.creationTimestamp -o jsonpath='{.items[-1].metadata.name}' 2>/dev/null || echo "")
                if [ -n "$BUILD_POD" ]; then
                    kubectl logs -n team1 "$BUILD_POD" --all-containers=true || true
                fi
                exit 1
            fi
        else
            # Get build pod logs for other failures
            log_info "Build pod logs:"
            BUILD_POD=$(kubectl get pods -n team1 -l build.shipwright.io/name=weather-tool --sort-by=.metadata.creationTimestamp -o jsonpath='{.items[-1].metadata.name}' 2>/dev/null || echo "")
            if [ -n "$BUILD_POD" ]; then
                kubectl logs -n team1 "$BUILD_POD" --all-containers=true || true
            fi
            exit 1
        fi
    }

    log_success "Shipwright BuildRun completed successfully"
fi
