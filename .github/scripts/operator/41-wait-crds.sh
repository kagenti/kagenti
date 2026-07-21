#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../lib/env-detect.sh"
source "$SCRIPT_DIR/../lib/logging.sh"
source "$SCRIPT_DIR/../lib/k8s-utils.sh"

log_step "41" "Waiting for Rossoctl Operator CRDs"

# Check if MCP Gateway is installed before waiting for its CRDs.
# The mcp-gateway chart is optional (requires --with-mcp-gateway or --with-all
# on Kind, and is skipped by default on HyperShift/OCP).
MCP_GATEWAY_INSTALLED=false
if helm list -n mcp-system -q 2>/dev/null | grep -q "^mcp-gateway$"; then
    MCP_GATEWAY_INSTALLED=true
elif kubectl get namespace mcp-system &>/dev/null && \
     kubectl get crds 2>/dev/null | grep -q "mcp\.\(kuadrant\.io\|rossoctl\.com\)"; then
    MCP_GATEWAY_INSTALLED=true
fi

if [ "$MCP_GATEWAY_INSTALLED" = "false" ]; then
    log_info "MCP Gateway not installed — skipping MCP CRD validation"
else
    MCP_RESOURCES=(
        "mcpserverregistrations"
        "mcpvirtualservers"
        "mcpgatewayextensions"
    )

    # Detect which MCP CRD domain is installed.
    # Retry up to 60s since operators may still be registering CRDs.
    MCP_DOMAIN=""
    for i in $(seq 1 12); do
        if kubectl get crd "mcpserverregistrations.mcp.kuadrant.io" &>/dev/null; then
            MCP_DOMAIN="mcp.kuadrant.io"
            break
        elif kubectl get crd "mcpserverregistrations.mcp.rossoctl.com" &>/dev/null; then
            MCP_DOMAIN="mcp.rossoctl.com"
            break
        fi
        log_info "MCP CRDs not yet available, retrying ($i/12)..."
        sleep 5
    done
    if [ -z "$MCP_DOMAIN" ]; then
        MCP_DOMAIN="mcp.kuadrant.io"
        log_info "Defaulting to $MCP_DOMAIN (neither domain detected after 60s)"
    fi
    log_info "MCP CRD domain: $MCP_DOMAIN"

    for resource in "${MCP_RESOURCES[@]}"; do
        crd="${resource}.${MCP_DOMAIN}"
        log_info "Waiting for CRD: $crd"
        wait_for_crd "$crd" || {
            log_error "CRD $crd not found"
            kubectl get crds | grep -E 'rossoctl|mcp' || echo "No rossoctl/mcp CRDs found"
            kubectl get pods -n rossoctl-system
            exit 1
        }
    done
fi

log_success "All Rossoctl Operator CRDs established"

# ── Ensure keycloak-admin-secret exists in rossoctl-system ────────────────────
# The operator's ClientRegistrationReconciler reads admin credentials from
# keycloak-admin-secret in its own namespace to register Keycloak clients.
# PR #1791 removed the Helm template that created this; the operator blocks
# with "waiting for keycloak-admin-secret" without it.  Copy from
# keycloak-initial-admin (created by the Keycloak operator in the keycloak ns).
KC_NS="${KEYCLOAK_NAMESPACE:-keycloak}"
OPERATOR_NS="${ROSSOCTL_NAMESPACE:-rossoctl-system}"
if ! kubectl get secret keycloak-admin-secret -n "$OPERATOR_NS" &>/dev/null; then
    log_info "Creating keycloak-admin-secret in $OPERATOR_NS from keycloak-initial-admin..."
    KC_USER=$(kubectl get secret keycloak-initial-admin -n "$KC_NS" -o jsonpath='{.data.username}' 2>/dev/null | base64 -d) || true
    KC_PASS=$(kubectl get secret keycloak-initial-admin -n "$KC_NS" -o jsonpath='{.data.password}' 2>/dev/null | base64 -d) || true
    if [ -n "$KC_USER" ] && [ -n "$KC_PASS" ]; then
        kubectl create secret generic keycloak-admin-secret -n "$OPERATOR_NS" \
            --from-literal=KEYCLOAK_ADMIN_USERNAME="$KC_USER" \
            --from-literal=KEYCLOAK_ADMIN_PASSWORD="$KC_PASS" \
            --dry-run=client -o yaml | kubectl apply -f -
        log_success "keycloak-admin-secret created in $OPERATOR_NS"
    else
        log_warn "Could not read keycloak-initial-admin from $KC_NS — operator may block"
    fi
else
    log_info "keycloak-admin-secret already exists in $OPERATOR_NS"
fi

# Wait for rossoctl-operator pod to be ready.
# The operator's ClientRegistrationReconciler creates per-workload credential
# secrets when agent pods are admitted by the webhook.  If the operator isn't
# Running/Ready by the time agents are deployed (scripts 70+), pods get stuck
# in ContainerCreating waiting for the secret volume.
#
# The deployment name varies (subchart naming, alias, etc.) so we wait by pod
# label instead.  Non-fatal: the credential secret wait in 74-deploy-weather-agent.sh
# provides a second gate.
OPERATOR_LABEL="app.kubernetes.io/name=rossoctl-operator"
if kubectl get pods -n rossoctl-system -l "$OPERATOR_LABEL" --no-headers 2>/dev/null | grep -q .; then
    log_info "Waiting for rossoctl-operator pod to be ready..."
    if wait_for_pod "$OPERATOR_LABEL" "rossoctl-system" 120; then
        log_success "rossoctl-operator is ready"
    else
        log_warn "rossoctl-operator pod not ready — credential secret creation may be delayed"
    fi
else
    log_info "rossoctl-operator pod not found by label ($OPERATOR_LABEL), checking by deployment..."
    FOUND_OPERATOR=false
    for NAME in rossoctl-operator rossoctl-rossoctl-operator-controller-manager; do
        if kubectl get deployment "$NAME" -n rossoctl-system &>/dev/null; then
            FOUND_OPERATOR=true
            if wait_for_deployment "$NAME" "rossoctl-system" 120; then
                log_success "$NAME is ready"
            else
                log_warn "$NAME not ready — credential secret creation may be delayed"
            fi
            break
        fi
    done
    if [ "$FOUND_OPERATOR" != "true" ]; then
        log_warn "No rossoctl-operator deployment found — listing rossoctl-system contents for diagnostics:"
        kubectl get deployments -n rossoctl-system 2>&1 || true
        kubectl get pods -n rossoctl-system 2>&1 || true
    fi
fi
