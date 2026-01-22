#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../lib/env-detect.sh"
source "$SCRIPT_DIR/../lib/logging.sh"
source "$SCRIPT_DIR/../lib/k8s-utils.sh"

log_step "74" "Deploying weather-service agent via Shipwright + Deployment"

# ============================================================================
# Step 1: Build the weather-service image using Shipwright
# ============================================================================

# Detect if running on OpenShift (check for oc command and logged in)
if oc whoami &>/dev/null; then
    IS_OPENSHIFT=true
    log_info "Detected OpenShift - using OpenShift Shipwright files with internal registry"
else
    IS_OPENSHIFT=false
    log_info "Detected Kind/vanilla Kubernetes - using Kind Shipwright files"
fi

# Clean up previous Build to avoid conflicts
kubectl delete build weather-service -n team1 --ignore-not-found 2>/dev/null || true
sleep 2
log_info "Creating Shipwright Build..."
if [ "$IS_OPENSHIFT" = "true" ]; then
    kubectl apply -f "$REPO_ROOT/kagenti/examples/agents/weather_agent_shipwright_build_ocp.yaml"
else
    kubectl apply -f "$REPO_ROOT/kagenti/examples/agents/weather_agent_shipwright_build.yaml"
fi

# Wait for Build to be registered (with retry loop)
run_with_timeout 30 'until kubectl get build weather-service -n team1 &> /dev/null; do sleep 2; done' || {
    log_error "Shipwright Build not created"
    exit 1
}
log_info "Shipwright Build created"

# Create BuildRun to trigger the build
log_info "Triggering BuildRun..."
BUILDRUN_NAME=$(kubectl create -f "$REPO_ROOT/kagenti/examples/agents/weather_agent_shipwright_buildrun.yaml" -o jsonpath='{.metadata.name}')
log_info "BuildRun created: $BUILDRUN_NAME"

# Wait for BuildRun to complete
log_info "Waiting for BuildRun to complete (this may take a few minutes)..."
run_with_timeout 600 "kubectl wait --for=condition=Succeeded --timeout=600s buildrun/$BUILDRUN_NAME -n team1" || {
    log_error "BuildRun did not succeed"

    # Get BuildRun status for debugging
    log_info "BuildRun status:"
    kubectl get buildrun "$BUILDRUN_NAME" -n team1 -o yaml

    # Get build pod logs
    log_info "Build pod logs:"
    BUILD_POD=$(kubectl get pods -n team1 -l build.shipwright.io/name=weather-service --sort-by=.metadata.creationTimestamp -o jsonpath='{.items[-1].metadata.name}' 2>/dev/null || echo "")
    if [ -n "$BUILD_POD" ]; then
        kubectl logs -n team1 "$BUILD_POD" --all-containers=true || true
    fi

    exit 1
}

log_success "BuildRun completed successfully"

# ============================================================================
# Step 2: Deploy using standard Kubernetes Deployment + Service
# (No longer uses Agent CRD - direct Deployment for operator independence)
# ============================================================================

log_info "Creating Deployment and Service..."

# Apply Deployment manifest
kubectl apply -f "$REPO_ROOT/kagenti/examples/agents/weather_service_deployment.yaml"

# Apply Service manifest
kubectl apply -f "$REPO_ROOT/kagenti/examples/agents/weather_service_service.yaml"

# Wait for Deployment to be created
run_with_timeout 60 'kubectl get deployment weather-service -n team1 &> /dev/null' || {
    log_error "Deployment not created"
    kubectl get deployments -n team1
    exit 1
}

# Wait for Deployment to be available
kubectl wait --for=condition=available --timeout=300s deployment/weather-service -n team1 || {
    log_error "Deployment not available"
    kubectl get pods -n team1 -l app.kubernetes.io/name=weather-service
    kubectl get events -n team1 --sort-by='.lastTimestamp'
    exit 1
}

# Verify Service exists
kubectl get service weather-service -n team1 || {
    log_error "Service not found"
    exit 1
}

log_success "Weather-service deployed via Deployment + Service (operator-independent)"

# Create OpenShift Route for the agent (on OpenShift only)
# The kagenti-operator doesn't create routes automatically - they're created by the UI backend
# when using the web interface. For E2E tests, we need to create the route manually.
if [ "$IS_OPENSHIFT" = "true" ]; then
    log_info "Creating OpenShift Route for weather-service..."
    cat <<EOF | kubectl apply -f -
apiVersion: route.openshift.io/v1
kind: Route
metadata:
  name: weather-service
  namespace: team1
  annotations:
    openshift.io/host.generated: "true"
spec:
  path: /
  port:
    targetPort: 8000
  to:
    kind: Service
    name: weather-service
  wildcardPolicy: None
  tls:
    termination: edge
    insecureEdgeTerminationPolicy: Redirect
EOF
    # Wait for route to be assigned a host
    for i in {1..30}; do
        ROUTE_HOST=$(oc get route -n team1 weather-service -o jsonpath='{.spec.host}' 2>/dev/null || echo "")
        if [ -n "$ROUTE_HOST" ]; then
            log_success "Route created: https://$ROUTE_HOST"
            break
        fi
        echo "[$i/30] Waiting for route host assignment..."
        sleep 2
    done
fi
