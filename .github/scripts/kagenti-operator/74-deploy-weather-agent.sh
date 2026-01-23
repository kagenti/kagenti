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

# Wait for Shipwright Build to be registered (with retry loop)
# Use full API group to avoid confusion with OpenShift legacy builds
run_with_timeout 60 'until kubectl get builds.shipwright.io weather-service -n team1 &> /dev/null; do sleep 2; done' || {
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

# WORKAROUND: Fix Service targetPort mismatch
# The kagenti-operator creates Service with targetPort: 8080, but the agent listens on 8000
# Patch the Service to use the correct targetPort until the operator is fixed
# See: https://github.com/kagenti/kagenti-operator/issues/XXX
log_info "Patching Service to use correct targetPort (8000)..."
kubectl patch svc weather-service -n team1 --type=json \
    -p '[{"op": "replace", "path": "/spec/ports/0/targetPort", "value": 8000}]' || {
    log_error "Failed to patch Service targetPort"
    kubectl get svc weather-service -n team1 -o yaml
}

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

    # Wait for the agent to be ready to serve traffic
    # The deployment "available" condition doesn't guarantee the app is ready
    if [ -n "$ROUTE_HOST" ]; then
        log_info "Waiting for weather-service agent to respond..."
        AGENT_URL="https://$ROUTE_HOST"
        for i in {1..60}; do
            # Try to fetch the agent card (A2A discovery endpoint)
            HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" -k --connect-timeout 5 "$AGENT_URL/.well-known/agent.json" 2>/dev/null || echo "000")
            if [ "$HTTP_CODE" = "200" ]; then
                log_success "Agent is ready and responding (HTTP 200)"
                break
            elif [ "$HTTP_CODE" = "503" ] || [ "$HTTP_CODE" = "502" ] || [ "$HTTP_CODE" = "000" ]; then
                echo "[$i/60] Agent not ready yet (HTTP $HTTP_CODE), waiting..."
                sleep 3
            else
                # Got a response, might be 401/403 which still means the agent is up
                log_success "Agent is responding (HTTP $HTTP_CODE)"
                break
            fi
        done
        if [ "$HTTP_CODE" = "503" ] || [ "$HTTP_CODE" = "502" ] || [ "$HTTP_CODE" = "000" ]; then
            log_error "Agent did not become ready after 3 minutes"
            log_info "Checking pod status:"
            kubectl get pods -n team1 -l app.kubernetes.io/name=weather-service 2>&1 || true
            kubectl describe pods -n team1 -l app.kubernetes.io/name=weather-service 2>&1 | tail -30 || true
        fi
    fi
fi
