#!/usr/bin/env bash
#
# Deploy Sandbox Agents
#
# Builds one shared image, then deploys all sandbox agent variants:
#   - sandbox-agent:  basic variant (in-memory, stateless)
#   - sandbox-legion: persistent variant (PostgreSQL sessions, sub-agents)
#
# Shared infrastructure (deployed once):
#   - postgres-sessions StatefulSet (used by sandbox-legion)
#
# To add a new variant: create its *_deployment.yaml and *_service.yaml,
# then add it to the VARIANTS array below.
#
# Usage:
#   ./.github/scripts/kagenti-operator/76-deploy-sandbox-agents.sh
#
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
source "$SCRIPT_DIR/../lib/env-detect.sh"
source "$SCRIPT_DIR/../lib/logging.sh"
source "$SCRIPT_DIR/../lib/k8s-utils.sh"

log_step "76" "Deploying Sandbox Agents"

NAMESPACE="${SANDBOX_NAMESPACE:-team1}"
AGENTS_DIR="$REPO_ROOT/kagenti/examples/agents"

# ============================================================================
# Step 1: Deploy shared infrastructure (postgres-sessions)
# ============================================================================

log_info "Deploying postgres-sessions StatefulSet..."
kubectl apply -f "$REPO_ROOT/deployments/sandbox/postgres-sessions.yaml"

run_with_timeout 120 "kubectl rollout status statefulset/postgres-sessions -n $NAMESPACE --timeout=120s" || {
    log_error "postgres-sessions did not become ready"
    kubectl get pods -n "$NAMESPACE" -l app.kubernetes.io/name=postgres-sessions
    exit 1
}
log_success "postgres-sessions running"

# ============================================================================
# Step 2: Build shared sandbox-agent image via Shipwright
# ============================================================================

log_info "Building sandbox-agent image (shared by all variants)..."
kubectl delete build sandbox-agent -n "$NAMESPACE" --ignore-not-found 2>/dev/null || true
sleep 2
kubectl apply -f "$AGENTS_DIR/sandbox_agent_shipwright_build_ocp.yaml"

run_with_timeout 60 "kubectl get builds.shipwright.io sandbox-agent -n $NAMESPACE" || {
    log_error "Shipwright Build not found after 60 seconds"
    kubectl get builds.shipwright.io -n "$NAMESPACE" 2>&1 || echo "  (none)"
    exit 1
}

log_info "Triggering BuildRun..."
BUILDRUN_NAME=$(kubectl create -f - -o jsonpath='{.metadata.name}' <<EOF
apiVersion: shipwright.io/v1beta1
kind: BuildRun
metadata:
  generateName: sandbox-agent-run-
  namespace: $NAMESPACE
spec:
  build:
    name: sandbox-agent
EOF
)
log_info "BuildRun: $BUILDRUN_NAME"

log_info "Waiting for build (this may take a few minutes)..."
run_with_timeout 600 "kubectl wait --for=condition=Succeeded --timeout=600s buildrun/$BUILDRUN_NAME -n $NAMESPACE" || {
    log_error "BuildRun did not succeed"

    FAILURE_REASON=$(kubectl get buildrun "$BUILDRUN_NAME" -n "$NAMESPACE" -o jsonpath='{.status.conditions[?(@.type=="Succeeded")].reason}' 2>/dev/null || echo "")
    if [ "$FAILURE_REASON" = "TaskRunStopSidecarFailed" ]; then
        IMAGE_EXISTS=$(kubectl get imagestreamtag sandbox-agent:v0.0.1 -n "$NAMESPACE" 2>/dev/null && echo "yes" || echo "no")
        if [ "$IMAGE_EXISTS" = "yes" ]; then
            log_info "Image built despite sidecar cleanup failure. Proceeding..."
        else
            log_error "Image not found. Build failed."
            BUILD_POD=$(kubectl get pods -n "$NAMESPACE" -l build.shipwright.io/name=sandbox-agent --sort-by=.metadata.creationTimestamp -o jsonpath='{.items[-1].metadata.name}' 2>/dev/null || echo "")
            [ -n "$BUILD_POD" ] && kubectl logs -n "$NAMESPACE" "$BUILD_POD" --all-containers=true 2>&1 | tail -50 || true
            exit 1
        fi
    else
        BUILD_POD=$(kubectl get pods -n "$NAMESPACE" -l build.shipwright.io/name=sandbox-agent --sort-by=.metadata.creationTimestamp -o jsonpath='{.items[-1].metadata.name}' 2>/dev/null || echo "")
        [ -n "$BUILD_POD" ] && kubectl logs -n "$NAMESPACE" "$BUILD_POD" --all-containers=true 2>&1 | tail -50 || true
        exit 1
    fi
}
log_success "sandbox-agent image built"

# ============================================================================
# Step 3: Deploy all sandbox agent variants
# ============================================================================

# Each variant is defined by its deployment + service YAML files.
# All variants use the same sandbox-agent:v0.0.1 image.
VARIANTS=(
    "sandbox-agent"
    "sandbox-legion"
)

for VARIANT in "${VARIANTS[@]}"; do
    log_info "Deploying $VARIANT..."

    DEPLOYMENT_FILE="$AGENTS_DIR/${VARIANT//-/_}_deployment.yaml"
    SERVICE_FILE="$AGENTS_DIR/${VARIANT//-/_}_service.yaml"

    if [ ! -f "$DEPLOYMENT_FILE" ]; then
        log_error "Missing deployment manifest: $DEPLOYMENT_FILE"
        exit 1
    fi

    kubectl apply -f "$DEPLOYMENT_FILE"
    kubectl apply -f "$SERVICE_FILE"

    kubectl wait --for=condition=available --timeout=300s "deployment/$VARIANT" -n "$NAMESPACE" || {
        log_error "$VARIANT deployment not available"
        kubectl get pods -n "$NAMESPACE" -l "app.kubernetes.io/name=$VARIANT"
        kubectl describe pods -n "$NAMESPACE" -l "app.kubernetes.io/name=$VARIANT" 2>&1 | tail -20 || true
        exit 1
    }

    # Create OpenShift Route with streaming-friendly timeout
    if [ "$IS_OPENSHIFT" = "true" ]; then
        log_info "Creating route for $VARIANT..."
        cat <<EOF | kubectl apply -f -
apiVersion: route.openshift.io/v1
kind: Route
metadata:
  name: $VARIANT
  namespace: $NAMESPACE
  annotations:
    openshift.io/host.generated: "true"
    haproxy.router.openshift.io/timeout: 300s
spec:
  port:
    targetPort: 8000
  to:
    kind: Service
    name: $VARIANT
  tls:
    termination: edge
    insecureEdgeTerminationPolicy: Redirect
EOF

        # Wait for route and agent readiness
        for i in {1..30}; do
            ROUTE_HOST=$(oc get route -n "$NAMESPACE" "$VARIANT" -o jsonpath='{.spec.host}' 2>/dev/null || echo "")
            if [ -n "$ROUTE_HOST" ]; then
                log_info "Route: https://$ROUTE_HOST"
                break
            fi
            sleep 2
        done

        if [ -n "${ROUTE_HOST:-}" ]; then
            for i in {1..40}; do
                HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" -k --connect-timeout 5 "https://$ROUTE_HOST/.well-known/agent-card.json" 2>/dev/null || echo "000")
                if [ "$HTTP_CODE" = "200" ]; then
                    log_success "$VARIANT ready (HTTP 200)"
                    break
                fi
                [ "$i" -lt 40 ] && sleep 3
            done
        fi
    fi

    log_success "$VARIANT deployed"
done

log_success "All sandbox agents deployed: ${VARIANTS[*]}"
