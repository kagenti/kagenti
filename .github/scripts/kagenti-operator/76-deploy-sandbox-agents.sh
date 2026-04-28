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
# Step 1b: Deploy LLM budget proxy (per-namespace, shared by all agents)
# ============================================================================

log_info "Building llm-budget-proxy image..."
# Check if OpenShift BuildConfig API is available
# Note: avoid grep -q with pipefail — grep -q causes SIGPIPE (exit 141) on the producer
HAS_BUILDCONFIG=false
if [ "$IS_OPENSHIFT" = "true" ] && kubectl api-resources --api-group=build.openshift.io 2>/dev/null | grep BuildConfig > /dev/null; then
    HAS_BUILDCONFIG=true
fi
if [ "$HAS_BUILDCONFIG" = "true" ]; then
    oc create imagestream llm-budget-proxy -n "$NAMESPACE" 2>/dev/null || true
    cat <<BPEOF | kubectl apply -f -
apiVersion: build.openshift.io/v1
kind: BuildConfig
metadata:
  name: llm-budget-proxy
  namespace: $NAMESPACE
spec:
  output:
    to:
      kind: ImageStreamTag
      name: llm-budget-proxy:v0.0.1
  source:
    type: Git
    git:
      uri: $(git remote get-url origin 2>/dev/null | sed 's|git@github.com:|https://github.com/|' || echo "https://github.com/kagenti/kagenti.git")
      ref: $(git rev-parse HEAD 2>/dev/null || echo "main")
    contextDir: kagenti
  strategy:
    type: Docker
    dockerStrategy:
      dockerfilePath: llm-budget-proxy/Dockerfile
      noCache: true
BPEOF
    BUILD_NAME=$(oc start-build llm-budget-proxy -n "$NAMESPACE" -o name 2>&1) || {
        log_error "Failed to start llm-budget-proxy build"
        exit 1
    }
    log_info "Build: $BUILD_NAME"
    run_with_timeout 300 "oc wait --for=jsonpath='{.status.phase}'=Complete --timeout=300s $BUILD_NAME -n $NAMESPACE" || {
        BUILD_PHASE=$(oc get "$BUILD_NAME" -n "$NAMESPACE" -o jsonpath='{.status.phase}' 2>/dev/null || echo "Unknown")
        if [ "$BUILD_PHASE" != "Complete" ]; then
            log_error "llm-budget-proxy build failed (phase: $BUILD_PHASE)"
            oc logs "$BUILD_NAME" -n "$NAMESPACE" 2>&1 | tail -20 || true
            exit 1
        fi
    }
    log_success "llm-budget-proxy image built"
else
    log_warn "OpenShift builds not available — skipping llm-budget-proxy build"
    log_info "Pre-build the image and push to the registry manually"
fi

log_info "Deploying llm-budget-proxy..."

# Create the llm_budget database in postgres-sessions
POSTGRES_POD=$(kubectl get pod -n "$NAMESPACE" -l app.kubernetes.io/name=postgres-sessions \
    -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || echo "postgres-sessions-0")
kubectl exec -n "$NAMESPACE" "$POSTGRES_POD" -- bash -c \
    "psql -U kagenti -d postgres -tc \"SELECT 1 FROM pg_database WHERE datname='llm_budget'\" | grep -q 1 || \
     psql -U kagenti -d postgres -c 'CREATE DATABASE llm_budget'" 2>/dev/null || {
    log_warn "Could not create llm_budget DB (may already exist)"
}

# Ensure sessions DB has the tasks table (A2A SDK creates it on first message,
# but the backend reads from it immediately — must exist before tests run)
kubectl exec -n "$NAMESPACE" "$POSTGRES_POD" -- bash -c \
    "psql -U kagenti -d sessions -c \"CREATE TABLE IF NOT EXISTS tasks (
        id TEXT PRIMARY KEY,
        context_id TEXT,
        status TEXT DEFAULT 'submitted',
        artifacts JSONB DEFAULT '[]',
        history JSONB DEFAULT '[]',
        metadata JSONB DEFAULT '{}',
        created_at TIMESTAMPTZ DEFAULT NOW(),
        updated_at TIMESTAMPTZ DEFAULT NOW()
    )\"" 2>/dev/null || {
    log_warn "Could not ensure tasks table (may already exist or sessions DB missing)"
}

kubectl apply -f "$REPO_ROOT/deployments/sandbox/llm-budget-proxy.yaml"

run_with_timeout 120 "kubectl rollout status deployment/llm-budget-proxy -n $NAMESPACE --timeout=120s" || {
    log_error "llm-budget-proxy did not become ready"
    kubectl get pods -n "$NAMESPACE" -l app.kubernetes.io/name=llm-budget-proxy
    kubectl describe pods -n "$NAMESPACE" -l app.kubernetes.io/name=llm-budget-proxy 2>&1 | tail -20 || true
    exit 1
}
log_success "llm-budget-proxy running"

# ============================================================================
# Step 2: Build shared sandbox-agent image
# ============================================================================
# Uses OpenShift BuildConfig (Docker strategy with noCache: true) to avoid
# buildah layer caching issues. Falls back to Shipwright if OCP builds
# are not available.

log_info "Building sandbox-agent image (shared by all variants)..."

if [ "$IS_OPENSHIFT" = "true" ] && oc api-resources --api-group=build.openshift.io 2>/dev/null | grep -q BuildConfig; then
    # ── OpenShift BuildConfig (preferred — no layer caching) ──
    log_info "Using OpenShift BuildConfig (Docker strategy, noCache)..."

    # Create ImageStream if it doesn't exist
    oc create imagestream sandbox-agent -n "$NAMESPACE" 2>/dev/null || true

    # Apply BuildConfig
    kubectl apply -f "$AGENTS_DIR/sandbox_agent_buildconfig_ocp.yaml"

    # Start build and follow logs
    log_info "Starting build (this may take a few minutes)..."
    BUILD_NAME=$(oc start-build sandbox-agent -n "$NAMESPACE" -o name 2>&1) || {
        log_error "Failed to start build"
        exit 1
    }
    log_info "Build: $BUILD_NAME"

    # Wait for build to complete
    run_with_timeout 600 "oc wait --for=jsonpath='{.status.phase}'=Complete --timeout=600s $BUILD_NAME -n $NAMESPACE" || {
        BUILD_PHASE=$(oc get "$BUILD_NAME" -n "$NAMESPACE" -o jsonpath='{.status.phase}' 2>/dev/null || echo "Unknown")
        if [ "$BUILD_PHASE" = "Complete" ]; then
            log_info "Build completed (status race condition). Proceeding..."
        else
            log_error "Build did not complete (phase: $BUILD_PHASE)"
            oc logs "$BUILD_NAME" -n "$NAMESPACE" 2>&1 | tail -30 || true
            exit 1
        fi
    }
    log_success "sandbox-agent image built (OpenShift BuildConfig)"

else
    # ── Shipwright fallback (non-OpenShift or no Build API) ──
    log_info "Using Shipwright Build (fallback)..."
    kubectl delete build sandbox-agent -n "$NAMESPACE" --ignore-not-found 2>/dev/null || true
    sleep 2
    kubectl apply -f "$AGENTS_DIR/sandbox_agent_shipwright_build_ocp.yaml"

    run_with_timeout 60 "kubectl get builds.shipwright.io sandbox-agent -n $NAMESPACE" || {
        log_error "Shipwright Build not found after 60 seconds"
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

    log_info "Waiting for build..."
    run_with_timeout 600 "kubectl wait --for=condition=Succeeded --timeout=600s buildrun/$BUILDRUN_NAME -n $NAMESPACE" || {
        log_error "BuildRun did not succeed"
        BUILD_POD=$(kubectl get pods -n "$NAMESPACE" -l build.shipwright.io/name=sandbox-agent --sort-by=.metadata.creationTimestamp -o jsonpath='{.items[-1].metadata.name}' 2>/dev/null || echo "")
        [ -n "$BUILD_POD" ] && kubectl logs -n "$NAMESPACE" "$BUILD_POD" --all-containers=true 2>&1 | tail -30 || true
        exit 1
    }
    log_success "sandbox-agent image built (Shipwright)"
fi

# ============================================================================
# Step 3: Deploy all sandbox agent variants
# ============================================================================

# Each variant is defined by its deployment + service YAML files.
# All variants use the same sandbox-agent:v0.0.1 image.
VARIANTS=(
    "sandbox-agent"
    "sandbox-legion"
    "sandbox-hardened"
    "sandbox-basic"
    "sandbox-restricted"
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

    # Wait for deployment — use shorter timeout with a retry to handle ImagePullBackOff
    if ! kubectl wait --for=condition=available --timeout=120s "deployment/$VARIANT" -n "$NAMESPACE" 2>/dev/null; then
        log_warn "$VARIANT not ready after 120s, waiting 60s more for image pull..."
        sleep 60
        if ! kubectl wait --for=condition=available --timeout=120s "deployment/$VARIANT" -n "$NAMESPACE" 2>/dev/null; then
            log_warn "$VARIANT deployment not available (will retry route later)"
            kubectl get pods -n "$NAMESPACE" -l "app.kubernetes.io/name=$VARIANT" || true
        fi
    fi

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

# Retry route creation for any variants that were slow to deploy
if [ "$IS_OPENSHIFT" = "true" ]; then
    for VARIANT in "${VARIANTS[@]}"; do
        if ! oc get route "$VARIANT" -n "$NAMESPACE" &>/dev/null; then
            # Check if deployment is now available
            if kubectl get deployment "$VARIANT" -n "$NAMESPACE" -o jsonpath='{.status.availableReplicas}' 2>/dev/null | grep -q "^[1-9]"; then
                log_info "Late route creation for $VARIANT..."
                cat <<ROUTEEOF | kubectl apply -f -
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
ROUTEEOF
                ROUTE_HOST=$(oc get route "$VARIANT" -n "$NAMESPACE" -o jsonpath='{.spec.host}' 2>/dev/null || echo "")
                [ -n "$ROUTE_HOST" ] && log_info "Late route: https://$ROUTE_HOST"
            fi
        fi
    done
fi

# ============================================================================
# Step 4: Verify LLM_API_BASE points to local budget proxy (not external MaaS)
# ============================================================================

EXPECTED_LLM_BASE="http://llm-budget-proxy.${NAMESPACE}.svc:8080/v1"
for VARIANT in sandbox-legion sandbox-hardened sandbox-basic sandbox-restricted sandbox-agent; do
    ACTUAL=$(kubectl get deploy "$VARIANT" -n "$NAMESPACE" -o jsonpath='{.spec.template.spec.containers[0].env[?(@.name=="LLM_API_BASE")].value}' 2>/dev/null || echo "")
    if [ -n "$ACTUAL" ] && [ "$ACTUAL" != "$EXPECTED_LLM_BASE" ]; then
        log_warn "$VARIANT has LLM_API_BASE=$ACTUAL, patching to $EXPECTED_LLM_BASE"
        kubectl set env "deploy/$VARIANT" -n "$NAMESPACE" "LLM_API_BASE=$EXPECTED_LLM_BASE"
    fi
done

log_success "All sandbox agents deployed: ${VARIANTS[*]}"
