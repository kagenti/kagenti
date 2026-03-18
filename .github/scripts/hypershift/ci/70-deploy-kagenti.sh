#!/usr/bin/env bash
# Deploy Kagenti to HyperShift cluster
# This script is a thin wrapper that calls hypershift-full-test.sh with appropriate options.
# This ensures CI and local development use the exact same code paths.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="${GITHUB_WORKSPACE:-$(cd "$SCRIPT_DIR/../../../.." && pwd)}"

# Detect main repo root for worktree compatibility (secrets stay in main repo)
if [[ "$REPO_ROOT" == *"/.worktrees/"* ]]; then
    MAIN_REPO_ROOT="${REPO_ROOT%%/.worktrees/*}"
else
    MAIN_REPO_ROOT="$REPO_ROOT"
fi

echo "Deploying Kagenti to cluster..."

# Set Python interpreter for Ansible (required in CI where .venv doesn't exist)
ANSIBLE_PYTHON_INTERPRETER=$(which python3)
export ANSIBLE_PYTHON_INTERPRETER

# Create minimal secrets file for CI with auto-generated values
# Use MAIN_REPO_ROOT so secrets are shared across worktrees
SECRETS_FILE="$MAIN_REPO_ROOT/deployments/envs/.secret_values.yaml"
if [ ! -f "$SECRETS_FILE" ]; then
    # Use real OPENAI_API_KEY from env if available (passed from GitHub secrets)
    OPENAI_KEY="${OPENAI_API_KEY:-ci-test-openai-key}"
    echo "Creating secrets file for CI..."
    cat > "$SECRETS_FILE" <<EOF
# Auto-generated secrets for CI
global: {}
charts:
  kagenti:
    values:
      secrets:
        githubUser: "ci-user"
        githubToken: "ci-token-placeholder"
        openaiApiKey: "${OPENAI_KEY}"
EOF
fi

cd "$REPO_ROOT"

# Wait for cluster to be fully ready before deploying
# HyperShift clusters can take time for all components to initialize
# Wait for nodes - increased timeout for autoscaling scenarios
# Autoscaling can take 5-10 minutes to provision new nodes
echo "Waiting for cluster nodes to be ready..."
MAX_RETRIES=60
RETRY_DELAY=10
for i in $(seq 1 $MAX_RETRIES); do
    # Count nodes that are NOT in Ready status
    # Use awk to reliably check the STATUS column (2nd column)
    NOT_READY=$(kubectl get nodes --no-headers 2>/dev/null | awk '$2 != "Ready" {count++} END {print count+0}' || echo "999")
    TOTAL=$(kubectl get nodes --no-headers 2>/dev/null | wc -l | tr -d ' ' || echo "0")
    # Validate numeric values to avoid arithmetic errors
    [[ ! "$NOT_READY" =~ ^[0-9]+$ ]] && NOT_READY=999
    [[ ! "$TOTAL" =~ ^[0-9]+$ ]] && TOTAL=0
    if [[ "$NOT_READY" == "0" && "$TOTAL" -gt 0 ]]; then
        echo "All $TOTAL nodes are ready"
        break
    fi
    READY_COUNT=$((TOTAL - NOT_READY))
    [[ $READY_COUNT -lt 0 ]] && READY_COUNT=0
    echo "[$i/$MAX_RETRIES] Waiting for nodes... ($READY_COUNT/$TOTAL ready)"
    if [[ $i -eq $MAX_RETRIES ]]; then
        echo "ERROR: Nodes not ready after $((MAX_RETRIES * RETRY_DELAY)) seconds"
        kubectl get nodes
        exit 1
    fi
    sleep $RETRY_DELAY
done

# Wait for OLM (Operator Lifecycle Manager) to be available
# This is required for installing OpenShift operators via Subscriptions
echo "Waiting for OLM to be available..."
for i in $(seq 1 $MAX_RETRIES); do
    if kubectl api-resources | grep -q "subscriptions.*operators.coreos.com" 2>/dev/null; then
        echo "OLM Subscription API is available"
        break
    fi
    echo "[$i/$MAX_RETRIES] Waiting for OLM..."
    if [[ $i -eq $MAX_RETRIES ]]; then
        echo "WARNING: OLM not available after $((MAX_RETRIES * RETRY_DELAY)) seconds"
        echo "Continuing anyway - some operators may not install correctly"
    fi
    sleep $RETRY_DELAY
done

# ══════════════════════════════════════════════════════════════════════════════
# Dependency overrides — build from source before deploying agents.
#
# Ref formats supported:
#   main                  — branch on upstream repo
#   fix/my-branch         — feature branch
#   pr/234                — PR head ref (works with forks)
#   a5607f9               — commit SHA (7-40 hex chars)
#
# ── HARDCODED OVERRIDES ──
# These override packaged chart dependencies that haven't released fixes yet.
# Remove each entry after bumping the chart dependency to a version that
# includes the fix.
#
# kagenti-extensions: proxy-init capabilities fix (extensions#242, not yet released)
#   Chart dep: v0.4.0-alpha.5 (uses privileged:true, proxy-init:latest incompatible)
#   Fix on main: uses NET_ADMIN/NET_RAW capabilities + DNAT (no privileged)
#   Remove after: bumping kagenti-webhook-chart to >= v0.4.0-alpha.9
# ──────────────────────────────────────────────────────────────────────────────
# SHADOW TEST: skip dep builds entirely — use stock GHCR images
# This isolates whether the dep rebuild from extensions@main is the cause of SCC failures
if [[ -z "${KAGENTI_DEP_BUILDS:-}" || "${KAGENTI_DEP_BUILDS:-}" == "[]" ]]; then
    export KAGENTI_DEP_BUILDS='[]'
fi

# Use hypershift-full-test.sh with whitelist mode (--include-X flags)
# Note: CLUSTER_SUFFIX is set by the workflow (e.g., pr594), don't override it
# Intentionally not using `exec` here because the oauth bootstrap step below
# must run after deploy completes.
#
# When KAGENTI_DEP_BUILDS is set, split into three phases:
#   1. Install platform (helm charts, CRDs, operators)
#   2. Build dependency images from custom refs
#   3. Deploy agents (uses the rebuilt images)
if [[ -n "${KAGENTI_DEP_BUILDS:-}" && "${KAGENTI_DEP_BUILDS:-}" != "[]" ]]; then
    echo "=================================================="
    echo "  Dependency overrides (built from source):"
    echo "$KAGENTI_DEP_BUILDS" | python3 -c "
import json, sys
for b in json.load(sys.stdin):
    print(f\"    {b['repo']}@{b['ref']}\")
" 2>/dev/null || echo "    ${KAGENTI_DEP_BUILDS}"
    echo "=================================================="

    # Write to GitHub step summary if available
    if [[ -n "${GITHUB_STEP_SUMMARY:-}" ]]; then
        {
            echo "### Dependency overrides (built from source)"
            echo "$KAGENTI_DEP_BUILDS" | python3 -c "
import json, sys
for b in json.load(sys.stdin):
    print(f\"- \`{b['repo']}\` @ \`{b['ref']}\`\")
" 2>/dev/null || echo "- ${KAGENTI_DEP_BUILDS}"
        } >> "$GITHUB_STEP_SUMMARY"
    fi

    echo "Phase 1: Install platform..."
    "$REPO_ROOT/.github/scripts/local-setup/hypershift-full-test.sh" \
        --include-kagenti-install \
        --env ocp

    echo "Phase 2: Build dependencies from source..."
    DEP_BUILD_SCRIPT="$REPO_ROOT/.github/scripts/common/31-build-deps-from-refs.sh"
    if [[ -x "$DEP_BUILD_SCRIPT" ]]; then
        "$DEP_BUILD_SCRIPT"
    elif [[ -f "$DEP_BUILD_SCRIPT" ]]; then
        bash "$DEP_BUILD_SCRIPT"
    else
        echo "WARNING: $DEP_BUILD_SCRIPT not found; skipping dependency builds"
    fi

    echo "Phase 3: Deploy agents..."
    "$REPO_ROOT/.github/scripts/local-setup/hypershift-full-test.sh" \
        --include-agents \
        --env ocp
else
    # Standard path: install + agents in one pass
    "$REPO_ROOT/.github/scripts/local-setup/hypershift-full-test.sh" \
        --include-kagenti-install \
        --include-agents \
        --env ocp
fi

# When this script runs in GitHub Actions, always rebuild/restart ui-oauth-secret
# from the checked-out source. This keeps PR behavior correct even when a
# comment-triggered workflow definition comes from the default branch.
if [[ "${GITHUB_ACTIONS:-}" == "true" ]]; then
    HELPER_SCRIPT="$REPO_ROOT/.github/scripts/common/25-build-oauth-secret-image.sh"
    echo "Rebuilding and restarting ui-oauth-secret job from current checkout..."
    if [[ -x "$HELPER_SCRIPT" ]]; then
        "$HELPER_SCRIPT"
    elif [[ -f "$HELPER_SCRIPT" ]]; then
        echo "Helper script is not executable, running with bash: $HELPER_SCRIPT"
        bash "$HELPER_SCRIPT"
    else
        echo "WARNING: $HELPER_SCRIPT not found; using inline fallback path."
        NAMESPACE="kagenti-system"
        JOB_NAME="kagenti-ui-oauth-secret-job"
        BUILD_NAME="ui-oauth-secret"
        INTERNAL_REGISTRY="image-registry.openshift-image-registry.svc:5000"

        echo "Creating ImageStream and BuildConfig for ${BUILD_NAME}..."
        oc apply -f - <<EOF
apiVersion: image.openshift.io/v1
kind: ImageStream
metadata:
  name: ${BUILD_NAME}
  namespace: ${NAMESPACE}
---
apiVersion: build.openshift.io/v1
kind: BuildConfig
metadata:
  name: ${BUILD_NAME}
  namespace: ${NAMESPACE}
spec:
  output:
    to:
      kind: ImageStreamTag
      name: ${BUILD_NAME}:latest
  source:
    type: Binary
    binary: {}
  strategy:
    type: Docker
    dockerStrategy:
      dockerfilePath: auth/ui-oauth-secret/Dockerfile
EOF

        echo "Starting OpenShift binary build from source..."
        OC_BUILD=$(oc start-build "$BUILD_NAME" -n "$NAMESPACE" \
            --from-dir="$REPO_ROOT/kagenti/" --follow=false -o name 2>/dev/null || echo "")
        if [[ -z "$OC_BUILD" ]]; then
            echo "ERROR: Failed to start ui-oauth-secret build"
            exit 1
        fi
        PHASE="Unknown"
        for _ in {1..120}; do
            PHASE=$(oc get "$OC_BUILD" -n "$NAMESPACE" -o jsonpath='{.status.phase}' 2>/dev/null || echo "Unknown")
            if [[ "$PHASE" == "Complete" ]]; then
                echo "OpenShift build completed"
                break
            elif [[ "$PHASE" == "Failed" || "$PHASE" == "Error" || "$PHASE" == "Cancelled" ]]; then
                echo "ERROR: ui-oauth-secret build failed with phase: $PHASE"
                oc logs "$OC_BUILD" -n "$NAMESPACE" || true
                exit 1
            fi
            sleep 5
        done
        if [[ "$PHASE" != "Complete" ]]; then
            echo "ERROR: ui-oauth-secret build timed out after 600s (phase: $PHASE)"
            oc logs "$OC_BUILD" -n "$NAMESPACE" || true
            exit 1
        fi

        echo "Restarting oauth-secret job with updated image..."
        kubectl delete job "$JOB_NAME" -n "$NAMESPACE" --ignore-not-found
        sleep 2
        helm upgrade kagenti "$REPO_ROOT/charts/kagenti" -n "$NAMESPACE" \
            --reuse-values --no-hooks \
            --set "uiOAuthSecret.image=${INTERNAL_REGISTRY}/${NAMESPACE}/${BUILD_NAME}" \
            --set "uiOAuthSecret.tag=latest" \
            --set "uiOAuthSecret.imagePullPolicy=Always" || true

        kubectl wait --for=condition=complete "job/$JOB_NAME" -n "$NAMESPACE" --timeout=120s || {
            echo "ERROR: OAuth secret job did not complete"
            kubectl logs "job/$JOB_NAME" -n "$NAMESPACE" || true
            exit 1
        }
        kubectl rollout restart deployment/kagenti-ui -n "$NAMESPACE"
        kubectl rollout status deployment/kagenti-ui -n "$NAMESPACE" --timeout=120s
    fi
    if [[ -n "${GITHUB_STEP_SUMMARY:-}" ]]; then
        {
            echo "### UI OAuth bootstrap"
            echo "- Rebuilt and restarted \`kagenti-ui-oauth-secret-job\` from current checkout."
            echo "- Trigger script: \`.github/scripts/hypershift/ci/70-deploy-kagenti.sh\`."
        } >> "$GITHUB_STEP_SUMMARY"
    fi
fi
