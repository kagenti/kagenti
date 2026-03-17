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

# Use hypershift-full-test.sh with whitelist mode (--include-X flags)
# Note: CLUSTER_SUFFIX is set by the workflow (e.g., pr594), don't override it
# Intentionally not using `exec` here because the oauth bootstrap step below
# must run after deploy completes.
#
# Build custom webhook from kagenti-extensions main to pick up the
# proxy-init capabilities fix (merged as kagenti-extensions#242).
# TODO: Remove this default after bumping the webhook chart dependency version.
KAGENTI_EXTENSIONS_REF="${KAGENTI_EXTENSIONS_REF:-main}"

# When KAGENTI_EXTENSIONS_REF is set, split into two phases so we can build the
# custom webhook image between platform install and agent deployment.
if [[ -n "${KAGENTI_EXTENSIONS_REF:-}" ]]; then
    echo "Custom extensions ref detected: ${KAGENTI_EXTENSIONS_REF}"
    echo "Phase 1: Install platform..."
    "$REPO_ROOT/.github/scripts/local-setup/hypershift-full-test.sh" \
        --include-kagenti-install \
        --env ocp

    echo "Phase 2: Build custom webhook from ${KAGENTI_EXTENSIONS_REF}..."
    WEBHOOK_BUILD_SCRIPT="$REPO_ROOT/.github/scripts/common/30-build-webhook-image.sh"
    if [[ -x "$WEBHOOK_BUILD_SCRIPT" ]]; then
        "$WEBHOOK_BUILD_SCRIPT"
    elif [[ -f "$WEBHOOK_BUILD_SCRIPT" ]]; then
        bash "$WEBHOOK_BUILD_SCRIPT"
    else
        echo "WARNING: $WEBHOOK_BUILD_SCRIPT not found; skipping custom webhook build"
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
