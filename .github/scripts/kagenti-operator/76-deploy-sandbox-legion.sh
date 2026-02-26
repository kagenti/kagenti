#!/usr/bin/env bash
#
# Deploy Sandbox Legion agent with session persistence
#
# Deploys:
#   - postgres-sessions StatefulSet (per-namespace session DB)
#   - sandbox-legion image build via Shipwright
#   - sandbox-legion Deployment + Service
#   - OpenShift Route with 300s timeout (for SSE/streaming)
#
# Prerequisites:
#   - Cluster accessible via KUBECONFIG
#   - openai-secret exists in team1 (created by installer)
#   - github-shipwright-secret exists in team1 (for git clone)
#   - Shipwright build system available
#
# Usage:
#   ./.github/scripts/kagenti-operator/76-deploy-sandbox-legion.sh
#
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
source "$SCRIPT_DIR/../lib/env-detect.sh"
source "$SCRIPT_DIR/../lib/logging.sh"
source "$SCRIPT_DIR/../lib/k8s-utils.sh"

log_step "76" "Deploying Sandbox Legion agent"

NAMESPACE="${SANDBOX_LEGION_NAMESPACE:-team1}"

# ============================================================================
# Step 1: Deploy postgres-sessions (session persistence DB)
# ============================================================================

log_info "Deploying postgres-sessions StatefulSet..."
kubectl apply -f "$REPO_ROOT/deployments/sandbox/postgres-sessions.yaml"

# Wait for postgres to be ready
run_with_timeout 120 "kubectl rollout status statefulset/postgres-sessions -n $NAMESPACE --timeout=120s" || {
    log_error "postgres-sessions did not become ready"
    kubectl get pods -n "$NAMESPACE" -l app.kubernetes.io/name=postgres-sessions
    exit 1
}
log_success "postgres-sessions running"

# ============================================================================
# Step 2: Build sandbox-legion image via Shipwright
# ============================================================================

log_info "Creating Shipwright Build for sandbox-legion..."
kubectl delete build sandbox-legion -n "$NAMESPACE" --ignore-not-found 2>/dev/null || true
sleep 2
kubectl apply -f "$REPO_ROOT/kagenti/examples/agents/sandbox_legion_shipwright_build_ocp.yaml"

# Wait for Build to be registered
run_with_timeout 60 "kubectl get builds.shipwright.io sandbox-legion -n $NAMESPACE" || {
    log_error "Shipwright Build not found after 60 seconds"
    kubectl get builds.shipwright.io -n "$NAMESPACE" 2>&1 || echo "  (none)"
    exit 1
}
log_info "Shipwright Build created"

# Trigger BuildRun
log_info "Triggering BuildRun..."
BUILDRUN_NAME=$(kubectl create -f "$REPO_ROOT/kagenti/examples/agents/sandbox_legion_shipwright_buildrun.yaml" -o jsonpath='{.metadata.name}')
log_info "BuildRun created: $BUILDRUN_NAME"

# Wait for build to complete
log_info "Waiting for BuildRun to complete (this may take a few minutes)..."
run_with_timeout 600 "kubectl wait --for=condition=Succeeded --timeout=600s buildrun/$BUILDRUN_NAME -n $NAMESPACE" || {
    log_error "BuildRun did not succeed"
    kubectl get buildrun "$BUILDRUN_NAME" -n "$NAMESPACE" -o yaml 2>&1 | tail -30 || true

    # Check for sidecar cleanup failure (image may still be built)
    FAILURE_REASON=$(kubectl get buildrun "$BUILDRUN_NAME" -n "$NAMESPACE" -o jsonpath='{.status.conditions[?(@.type=="Succeeded")].reason}' 2>/dev/null || echo "")
    if [ "$FAILURE_REASON" = "TaskRunStopSidecarFailed" ]; then
        log_info "BuildRun failed due to sidecar cleanup issue, checking if image was built..."
        IMAGE_EXISTS=$(kubectl get imagestreamtag sandbox-legion:v0.0.1 -n "$NAMESPACE" 2>/dev/null && echo "yes" || echo "no")
        if [ "$IMAGE_EXISTS" = "yes" ]; then
            log_info "Image was built successfully despite sidecar cleanup failure. Proceeding..."
        else
            log_error "Image not found in registry. Build actually failed."
            BUILD_POD=$(kubectl get pods -n "$NAMESPACE" -l build.shipwright.io/name=sandbox-legion --sort-by=.metadata.creationTimestamp -o jsonpath='{.items[-1].metadata.name}' 2>/dev/null || echo "")
            if [ -n "$BUILD_POD" ]; then
                kubectl logs -n "$NAMESPACE" "$BUILD_POD" --all-containers=true 2>&1 | tail -50 || true
            fi
            exit 1
        fi
    else
        BUILD_POD=$(kubectl get pods -n "$NAMESPACE" -l build.shipwright.io/name=sandbox-legion --sort-by=.metadata.creationTimestamp -o jsonpath='{.items[-1].metadata.name}' 2>/dev/null || echo "")
        if [ -n "$BUILD_POD" ]; then
            log_info "Build pod logs:"
            kubectl logs -n "$NAMESPACE" "$BUILD_POD" --all-containers=true 2>&1 | tail -50 || true
        fi
        exit 1
    fi
}
log_success "BuildRun completed successfully"

# ============================================================================
# Step 3: Deploy sandbox-legion Deployment + Service
# ============================================================================

log_info "Creating Deployment and Service..."
kubectl apply -f "$REPO_ROOT/kagenti/examples/agents/sandbox_legion_deployment.yaml"
kubectl apply -f "$REPO_ROOT/kagenti/examples/agents/sandbox_legion_service.yaml"

# Wait for Deployment to be available
kubectl wait --for=condition=available --timeout=300s deployment/sandbox-legion -n "$NAMESPACE" || {
    log_error "Deployment not available"
    kubectl get pods -n "$NAMESPACE" -l app.kubernetes.io/name=sandbox-legion
    kubectl describe pods -n "$NAMESPACE" -l app.kubernetes.io/name=sandbox-legion 2>&1 | tail -30 || true
    exit 1
}

# Verify Service
kubectl get service sandbox-legion -n "$NAMESPACE" || {
    log_error "Service not found"
    exit 1
}
log_success "Sandbox Legion deployed via Deployment + Service"

# ============================================================================
# Step 4: Create OpenShift Route with streaming-friendly timeout
# ============================================================================

if [ "$IS_OPENSHIFT" = "true" ]; then
    log_info "Creating OpenShift Route for sandbox-legion..."
    cat <<EOF | kubectl apply -f -
apiVersion: route.openshift.io/v1
kind: Route
metadata:
  name: sandbox-legion
  namespace: $NAMESPACE
  annotations:
    openshift.io/host.generated: "true"
    haproxy.router.openshift.io/timeout: 300s
spec:
  path: /
  port:
    targetPort: 8000
  to:
    kind: Service
    name: sandbox-legion
  wildcardPolicy: None
  tls:
    termination: edge
    insecureEdgeTerminationPolicy: Redirect
EOF

    # Wait for route host assignment
    for i in {1..30}; do
        ROUTE_HOST=$(oc get route -n "$NAMESPACE" sandbox-legion -o jsonpath='{.spec.host}' 2>/dev/null || echo "")
        if [ -n "$ROUTE_HOST" ]; then
            log_success "Route created: https://$ROUTE_HOST"
            break
        fi
        echo "[$i/30] Waiting for route host assignment..."
        sleep 2
    done

    # Wait for agent to be ready
    if [ -n "$ROUTE_HOST" ]; then
        log_info "Waiting for sandbox-legion agent to respond..."
        AGENT_URL="https://$ROUTE_HOST"
        for i in {1..60}; do
            HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" -k --connect-timeout 5 "$AGENT_URL/.well-known/agent-card.json" 2>/dev/null || echo "000")
            if [ "$HTTP_CODE" = "200" ]; then
                log_success "Agent is ready and responding (HTTP 200)"
                break
            elif [ "$HTTP_CODE" = "503" ] || [ "$HTTP_CODE" = "502" ] || [ "$HTTP_CODE" = "000" ]; then
                echo "[$i/60] Agent not ready yet (HTTP $HTTP_CODE), waiting..."
                sleep 3
            else
                log_success "Agent is responding (HTTP $HTTP_CODE)"
                break
            fi
        done
        if [ "$HTTP_CODE" = "503" ] || [ "$HTTP_CODE" = "502" ] || [ "$HTTP_CODE" = "000" ]; then
            log_error "Agent did not become ready after 3 minutes"
            kubectl get pods -n "$NAMESPACE" -l app.kubernetes.io/name=sandbox-legion 2>&1 || true
            kubectl describe pods -n "$NAMESPACE" -l app.kubernetes.io/name=sandbox-legion 2>&1 | tail -30 || true
            exit 1
        fi
    fi
fi

log_success "Sandbox Legion fully deployed"
