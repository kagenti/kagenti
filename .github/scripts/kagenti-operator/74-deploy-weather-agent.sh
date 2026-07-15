#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../lib/env-detect.sh"
source "$SCRIPT_DIR/../lib/logging.sh"
source "$SCRIPT_DIR/../lib/k8s-utils.sh"

log_step "74" "Deploying weather-service agent"

# IS_OPENSHIFT is set by env-detect.sh (sourced above)
# It checks for OpenShift-specific APIs, not just "oc whoami" which works on any cluster

# ============================================================================
# Step 1: Build the weather-service image (OpenShift only)
# On Kind, the deployment manifest references ghcr.io directly — no build needed.
# ============================================================================

SHIPWRIGHT_BUILD=false
if [ "$IS_OPENSHIFT" = "true" ] && kubectl get crd builds.shipwright.io &>/dev/null; then
    SHIPWRIGHT_BUILD=true
    log_info "Using OpenShift Shipwright files with internal registry"

    # Clean up previous Build to avoid conflicts
    kubectl delete build weather-service -n team1 --ignore-not-found 2>/dev/null || true
    sleep 2
    log_info "Creating Shipwright Build..."
    kubectl apply -f "$REPO_ROOT/kagenti/examples/agents/weather_agent_shipwright_build_ocp.yaml"

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

        # Check if the failure is just sidecar cleanup (image may still be built)
        FAILURE_REASON=$(kubectl get buildrun "$BUILDRUN_NAME" -n team1 -o jsonpath='{.status.conditions[?(@.type=="Succeeded")].reason}' 2>/dev/null || echo "")
        if [ "$FAILURE_REASON" = "TaskRunStopSidecarFailed" ]; then
            log_info "BuildRun failed due to sidecar cleanup issue, checking if image was built..."

            IMAGE_EXISTS=$(kubectl get imagestreamtag weather-service:v0.0.1 -n team1 2>/dev/null && echo "yes" || echo "no")

            if [ "$IMAGE_EXISTS" = "yes" ]; then
                log_info "Image was built successfully despite sidecar cleanup failure. Proceeding..."
            else
                log_error "Image not found in registry. Build actually failed."
                log_info "Build pod logs:"
                BUILD_POD=$(kubectl get pods -n team1 -l build.shipwright.io/name=weather-service --sort-by=.metadata.creationTimestamp -o jsonpath='{.items[-1].metadata.name}' 2>/dev/null || echo "")
                if [ -n "$BUILD_POD" ]; then
                    kubectl logs -n team1 "$BUILD_POD" --all-containers=true || true
                fi
                exit 1
            fi
        else
            log_info "Build pod logs:"
            BUILD_POD=$(kubectl get pods -n team1 -l build.shipwright.io/name=weather-service --sort-by=.metadata.creationTimestamp -o jsonpath='{.items[-1].metadata.name}' 2>/dev/null || echo "")
            if [ -n "$BUILD_POD" ]; then
                kubectl logs -n team1 "$BUILD_POD" --all-containers=true || true
            fi
            exit 1
        fi
    }

    log_success "BuildRun completed successfully"
else
    log_info "Shipwright not available — using ghcr.io image"
fi

# ============================================================================
# Step 2: Deploy using standard Kubernetes Deployment + Service
# (No longer uses Agent CRD - direct Deployment for operator independence)
# ============================================================================

log_info "Creating Deployment and Service..."

# Create ServiceAccount (required by webhook for correct SPIFFE ID derivation)
kubectl create serviceaccount weather-service -n team1 --dry-run=client -o yaml | kubectl apply -f -

# Apply Deployment manifest
if [ "$SHIPWRIGHT_BUILD" = "true" ]; then
    # Shipwright built the image into the internal registry — use OCP manifest
    kubectl apply -f "$REPO_ROOT/kagenti/examples/agents/weather_service_deployment_ocp.yaml"
else
    # Use ghcr.io image (Kind manifest)
    kubectl apply -f "$REPO_ROOT/kagenti/examples/agents/weather_service_deployment.yaml"

    # On OpenShift without Shipwright, patch LLM config to use MaaS LiteLLM proxy
    # (Kind manifest points to dockerhost:11434 which doesn't exist on OCP)
    if [ "$IS_OPENSHIFT" = "true" ]; then
        log_info "Patching LLM config for OpenShift (MaaS LiteLLM)..."

        LLM_HOST="litellm-litemaas.apps.prod.rhoai.rh-aiservices-bu.com"

        # The authbridge webhook injects HTTP(S)_PROXY=http://127.0.0.1:8081
        # at pod admission.  We cannot prevent injection, but we can ensure
        # NO_PROXY covers all traffic that must bypass the auth sidecar.
        # Include explicit hostnames for MCP/OTEL endpoints because some httpx
        # versions don't match leading-dot suffixes (e.g. .svc.cluster.local)
        # for plain HTTP URLs routed through HTTP_PROXY.
        NO_PROXY_VAL="127.0.0.1,localhost,${LLM_HOST},.svc,.svc.cluster.local,.local,.cluster.local,weather-tool-mcp.team1.svc.cluster.local,otel-collector.kagenti-system.svc.cluster.local,keycloak.keycloak.svc.cluster.local"
        # Set HTTP_PROXY="" (not remove it) so the authbridge webhook sees it
        # already exists and skips injection.  The MCP SDK reads HTTP_PROXY
        # from env and passes it to httpx as an explicit proxy= arg, which
        # bypasses NO_PROXY handling entirely.  Empty string = no proxy.
        kubectl set env deployment/weather-service -n team1 \
            LLM_API_BASE="https://${LLM_HOST}/v1" \
            LLM_MODEL="Qwen3.6-35B-A3B" \
            HTTP_PROXY="" \
            http_proxy="" \
            NO_PROXY="$NO_PROXY_VAL" \
            no_proxy="$NO_PROXY_VAL" \
            LLM_API_KEY- OPENAI_API_KEY- 2>/dev/null || true

        # HyperShift hosted clusters may lack external DNS resolution (CoreDNS
        # has no upstream forwarder configured). Resolve the LLM host from the
        # CI runner and inject as a hostAlias so the pod can reach it.
        LLM_IP=$(getent hosts "$LLM_HOST" 2>/dev/null | awk '{print $1; exit}' || \
                 python3 -c "import socket; print(socket.getaddrinfo('$LLM_HOST',443)[0][4][0])" 2>/dev/null || echo "")
        if [ -n "$LLM_IP" ]; then
            log_info "Adding hostAlias for $LLM_HOST → $LLM_IP (external DNS workaround)"
            kubectl patch deployment weather-service -n team1 --type=json -p "[
                {\"op\":\"add\",\"path\":\"/spec/template/spec/hostAliases\",\"value\":[{\"ip\":\"${LLM_IP}\",\"hostnames\":[\"${LLM_HOST}\"]}]}
            ]" 2>/dev/null || log_warn "Could not add hostAlias (may already exist)"
        else
            log_warn "Cannot resolve $LLM_HOST from CI runner — pod DNS may fail"
        fi
        # Set API keys from secret if it exists
        if kubectl get secret openai-secret -n team1 &>/dev/null; then
            kubectl patch deployment weather-service -n team1 --type=json -p '[
                {"op":"add","path":"/spec/template/spec/containers/0/env/-","value":{"name":"LLM_API_KEY","valueFrom":{"secretKeyRef":{"name":"openai-secret","key":"apikey"}}}},
                {"op":"add","path":"/spec/template/spec/containers/0/env/-","value":{"name":"OPENAI_API_KEY","valueFrom":{"secretKeyRef":{"name":"openai-secret","key":"apikey"}}}}
            ]' || true
        else
            log_warn "openai-secret not found in team1 — LLM calls will fail without API key"
        fi

        # Note: proxy-init is only injected in envoy-proxy mode. The default
        # authbridge proxy-sidecar mode uses HTTPS_PROXY env vars instead.
        # See NO_PROXY override above for external LLM endpoints.
    fi
fi

# Apply Service manifest
kubectl apply -f "$REPO_ROOT/kagenti/examples/agents/weather_service_service.yaml"

log_success "Weather-service deployed via Deployment + Service (operator-independent)"

# ============================================================================
# Step 3: Wait for operator to create the client credentials secret
# The webhook injects a volume mount for kagenti-keycloak-client-credentials-*
# into the pod at admission time.  The pod stays in ContainerCreating until
# the operator's ClientRegistrationReconciler registers the workload in
# Keycloak and creates the Secret.  Wait here to avoid a flaky timeout later.
# ============================================================================
log_info "Waiting for operator to create client credentials secret..."
if ! kubectl -n team1 wait --for=create secret/kagenti-keycloak-client-credentials --timeout=120s 2>/dev/null; then
    log_warn "Credentials secret not found after 120s — pod may be stuck in ContainerCreating"
    kubectl get pods -n kagenti-system 2>&1 || true
    kubectl get secrets -n team1 2>&1 || true
    kubectl logs -n kagenti-system -l app.kubernetes.io/instance=kagenti --tail=20 2>&1 || true
else
    log_success "Client credentials secret created by operator"
fi

# WORKAROUND: Fix Service targetPort mismatch
# The kagenti-operator creates Service with targetPort: 8080, but the agent listens on 8000
# Patch the Service to use the correct targetPort until the operator is fixed
# TODO: Remove this workaround once kagenti-operator is fixed to use port from Agent spec
log_info "Patching Service to use correct targetPort (8000)..."
kubectl patch svc weather-service -n team1 --type=json \
    -p '[{"op": "replace", "path": "/spec/ports/0/targetPort", "value": 8000}]' || {
    log_error "Failed to patch Service targetPort"
    kubectl get svc weather-service -n team1 -o yaml
    exit 1
}

# ============================================================================
# Step 4: Wait for pod to be Ready (common for Kind and OpenShift)
# After the credentials secret exists, the pod transitions from
# ContainerCreating → Running.  Wait for the deployment rollout to complete
# so subsequent scripts can rely on the agent being up.
# ============================================================================
log_info "Waiting for weather-service pod to be ready..."
wait_for_deployment "weather-service" "team1" 180 || {
    log_error "weather-service deployment not ready"
    kubectl get pods -n team1 -l app.kubernetes.io/name=weather-service 2>&1 || true
    kubectl describe pods -n team1 -l app.kubernetes.io/name=weather-service 2>&1 | tail -30 || true
    exit 1
}
log_success "weather-service pod is ready"

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
    # Agent chat involves a cold MCP session + multiple LLM round-trips that can
    # exceed HAProxy's 30s default, surfacing as a 504 on the first request.
    haproxy.router.openshift.io/timeout: "120s"
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
            HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" -k --connect-timeout 5 "$AGENT_URL/.well-known/agent-card.json" 2>/dev/null || echo "000")
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
            exit 1
        fi

        # Diagnostic: verify LLM endpoint is reachable from inside the pod
        WEATHER_POD=$(kubectl get pods -n team1 -l app.kubernetes.io/name=weather-service -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || echo "")
        if [ -n "$WEATHER_POD" ]; then
            log_info "Testing LLM endpoint connectivity from agent pod..."
            LLM_BASE=$(kubectl get deployment weather-service -n team1 -o jsonpath='{.spec.template.spec.containers[?(@.name=="agent")].env[?(@.name=="LLM_API_BASE")].value}' 2>/dev/null || echo "")
            if [ -n "$LLM_BASE" ]; then
                LLM_HOST=$(echo "$LLM_BASE" | sed 's|https\?://||' | cut -d/ -f1)
                # Test DNS + TLS + HTTP connectivity from inside the agent container
                kubectl exec -n team1 "$WEATHER_POD" -c agent -- \
                    python3 -c "
import socket, ssl, os, sys
host = '$LLM_HOST'
port = 443
url = '$LLM_BASE'

# Check proxy env vars
for k in ('HTTP_PROXY','HTTPS_PROXY','http_proxy','https_proxy','NO_PROXY','no_proxy'):
    v = os.environ.get(k)
    if v: print(f'PROXY: {k}={v}')

# DNS
try:
    ip = socket.getaddrinfo(host, port)[0][4][0]
    print(f'DNS OK: {host} -> {ip}')
except Exception as e:
    print(f'DNS FAIL: {host} -> {e}'); sys.exit(1)

# TLS
try:
    ctx = ssl.create_default_context()
    with socket.create_connection((host, port), timeout=10) as sock:
        with ctx.wrap_socket(sock, server_hostname=host) as ssock:
            print(f'TLS OK: {ssock.version()}')
except Exception as e:
    print(f'TLS FAIL: {host}:{port} -> {e}'); sys.exit(1)

# HTTP via httpx (same library as OpenAI client)
try:
    import httpx
    r = httpx.get(url + '/models', timeout=15, headers={'Authorization': 'Bearer test'})
    print(f'HTTPX OK: status={r.status_code}')
except Exception as e:
    print(f'HTTPX FAIL: {type(e).__name__}: {e}')

# Check OpenAI client
try:
    import openai
    c = openai.OpenAI(base_url=url, api_key=os.environ.get('OPENAI_API_KEY','test'))
    c.models.list()
    print('OPENAI OK')
except openai.APIConnectionError as e:
    print(f'OPENAI CONN FAIL: {e.__cause__}')
except Exception as e:
    print(f'OPENAI OTHER: {type(e).__name__}: {e}')
" 2>&1 || log_warn "LLM endpoint not reachable from pod — agent conversation tests will fail"
            fi
        fi
    fi
fi
