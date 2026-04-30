#!/usr/bin/env bash
#
# Build and load OpenShell PoC agent images into the cluster.
# Idempotent — skips images that already exist in the cluster.
#
# Supports:
#   Kind — docker build + kind load docker-image
#   OCP  — oc new-build --binary + oc start-build --from-dir
#
# Called by openshell-full-test.sh during the agents-deploy phase.
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="${GITHUB_WORKSPACE:-$(cd "$SCRIPT_DIR/../../.." && pwd)}"
AGENTS_DIR="$REPO_ROOT/deployments/openshell/agents"

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'
log_step()  { echo -e "${GREEN}>>>${NC} $1"; }
log_skip()  { echo -e "${YELLOW}>>>${NC} $1 (already exists)"; }

# Detect cluster type
CLUSTER_TYPE="${PLATFORM:-kind}"
CLUSTER_NAME="${CLUSTER_NAME:-kagenti}"
AGENT_NS="${AGENT_NS:-team1}"

OCP_INTERNAL_REGISTRY="image-registry.openshift-image-registry.svc:5000"

build_and_load() {
    local name="$1"
    local dir="$2"

    if [ ! -f "$dir/Dockerfile" ]; then
        log_skip "No Dockerfile for $name"
        return 0
    fi

    if [ "$CLUSTER_TYPE" = "kind" ]; then
        # Kind: docker build + kind load
        if docker exec "${CLUSTER_NAME}-control-plane" crictl images 2>/dev/null | grep -q "$name"; then
            log_skip "Image $name:latest (Kind)"
            return 0
        fi

        log_step "Building $name (docker)..."
        docker build -t "$name:latest" "$dir" -q

        log_step "Loading $name into Kind..."
        kind load docker-image "$name:latest" --name "$CLUSTER_NAME" 2>/dev/null

    elif [ "$CLUSTER_TYPE" = "ocp" ]; then
        # OCP: binary build via BuildConfig + ImageStream
        if oc get istag "$name:latest" -n "$AGENT_NS" >/dev/null 2>&1; then
            log_skip "Image $name:latest (OCP registry)"
            # Ensure deployment points at internal registry
            _patch_ocp_image "$name"
            return 0
        fi

        # Create BuildConfig if it doesn't exist
        if ! oc get bc "$name" -n "$AGENT_NS" >/dev/null 2>&1; then
            log_step "Creating BuildConfig for $name..."
            oc -n "$AGENT_NS" new-build --binary --strategy=docker --name="$name" 2>&1 | grep -v "^$" || true
        fi

        log_step "Building $name (OCP binary build)..."
        oc -n "$AGENT_NS" start-build "$name" --from-dir="$dir" --follow 2>&1 | tail -5

        # Patch deployment to use internal registry image
        _patch_ocp_image "$name"
    fi
}

_patch_ocp_image() {
    local name="$1"
    local target_image="$OCP_INTERNAL_REGISTRY/$AGENT_NS/$name:latest"
    local current_image
    current_image=$(kubectl get deploy "$name" -n "$AGENT_NS" -o jsonpath='{.spec.template.spec.containers[0].image}' 2>/dev/null || echo "")

    if [ "$current_image" != "$target_image" ] && kubectl get deploy "$name" -n "$AGENT_NS" >/dev/null 2>&1; then
        log_step "Patching $name image → internal registry"
        kubectl set image "deploy/$name" -n "$AGENT_NS" "agent=$target_image"
    fi
    # Scale back to 1 if scaled down (fulltest scales to 0 on OCP before build)
    local replicas
    replicas=$(kubectl get deploy "$name" -n "$AGENT_NS" -o jsonpath='{.spec.replicas}' 2>/dev/null || echo "1")
    if [ "$replicas" = "0" ]; then
        log_step "Scaling $name back to 1 replica"
        kubectl scale deploy "$name" -n "$AGENT_NS" --replicas=1
    fi
}

# Build custom agents and create policy ConfigMaps
for agent_dir in "$AGENTS_DIR"/*/; do
    [ -d "$agent_dir" ] || continue
    agent_name=$(basename "$agent_dir")

    # Build image if Dockerfile exists
    if [ -f "$agent_dir/Dockerfile" ]; then
        build_and_load "$agent_name" "$agent_dir"
    fi

    # Create policy ConfigMap if policy files exist (idempotent)
    if [ -f "$agent_dir/policy-data.yaml" ]; then
        cm_name="${agent_name}-policy"
        # Always apply (idempotent via --dry-run + apply)
        cm_args=("--from-file=policy.yaml=$agent_dir/policy-data.yaml")
        if [ -f "$agent_dir/sandbox-policy.rego" ]; then
            cm_args+=("--from-file=sandbox-policy.rego=$agent_dir/sandbox-policy.rego")
        fi
        kubectl create configmap "$cm_name" -n "$AGENT_NS" "${cm_args[@]}" \
            --dry-run=client -o yaml | kubectl apply -f - 2>&1 | grep -v "^Warning:" || true
    fi
done

log_step "All agent images built and loaded."
