#!/usr/bin/env bash
#
# Create HyperShift Cluster
#
# Creates an ephemeral OpenShift cluster via HyperShift for testing.
# Cluster names are AUTOMATICALLY prefixed with MANAGED_BY_TAG to ensure
# IAM scoping works correctly.
#
# USAGE:
#   ./.github/scripts/hypershift/create-cluster.sh [cluster-suffix]
#
# CLUSTER NAMING:
#   - Full name: ${MANAGED_BY_TAG}-${CLUSTER_SUFFIX}
#   - Default suffix: $USER (your username)
#   - Custom suffix: passed as argument
#   - Random suffix: CLUSTER_SUFFIX="" generates random 6-char suffix
#
# MANAGED_BY_TAG (controls cluster prefix and IAM scoping):
#   - Local: defaults to kagenti-hypershift-custom (shared by all developers)
#   - CI: set via secrets (kagenti-hypershift-ci)
#
# EXAMPLES:
#   # Using defaults (creates kagenti-hypershift-custom-ladas)
#   ./.github/scripts/hypershift/create-cluster.sh
#
#   # Custom suffix (creates kagenti-hypershift-custom-pr529)
#   ./.github/scripts/hypershift/create-cluster.sh pr529
#
#   # Random suffix (creates kagenti-hypershift-custom-<random>)
#   CLUSTER_SUFFIX="" ./.github/scripts/hypershift/create-cluster.sh
#
#   # Custom instance type and replicas
#   REPLICAS=3 INSTANCE_TYPE=m5.2xlarge ./.github/scripts/hypershift/create-cluster.sh
#
#   # Enable NodePool autoscaling (min 1, max 3 nodes)
#   AUTOSCALE_MIN=1 AUTOSCALE_MAX=3 ./.github/scripts/hypershift/create-cluster.sh
#

set -euo pipefail

# Handle Ctrl+C properly - kill child processes only (not the terminal!)
cleanup() {
    echo ""
    echo -e "\033[0;31m✗ Interrupted! Killing child processes...\033[0m"
    # Kill only direct child processes, not the entire process group
    # Using pkill -P is safer than kill -$$ which can kill the terminal
    pkill -P $$ 2>/dev/null || true
    sleep 1
    pkill -9 -P $$ 2>/dev/null || true
    exit 130
}
trap cleanup SIGINT SIGTERM

# Detect CI mode
CI_MODE="${GITHUB_ACTIONS:-false}"

# Ensure ~/.local/bin is in PATH (where local-setup.sh installs hcp)
export PATH="$HOME/.local/bin:$PATH"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
PARENT_DIR="$(cd "$REPO_ROOT/.." && pwd)"

# Find hypershift-automation directory
# Searches: 1) env override, 2) CI location, 3) sibling of repo, 4) worktree-aware paths
find_hypershift_automation() {
    # Allow explicit override
    if [ -n "${HYPERSHIFT_AUTOMATION_DIR:-}" ] && [ -d "$HYPERSHIFT_AUTOMATION_DIR" ]; then
        echo "$HYPERSHIFT_AUTOMATION_DIR"
        return
    fi

    # CI mode: cloned to /tmp
    if [ "$CI_MODE" = "true" ] && [ -d "/tmp/hypershift-automation" ]; then
        echo "/tmp/hypershift-automation"
        return
    fi

    # Standard location: sibling of repo root
    if [ -d "$PARENT_DIR/hypershift-automation" ]; then
        echo "$PARENT_DIR/hypershift-automation"
        return
    fi

    # Worktree-aware: if we're in .worktrees/, look higher up
    # e.g., /path/kagenti_hypershift_ci/.worktrees/feature -> /path/hypershift-automation
    if [[ "$REPO_ROOT" == *"/.worktrees/"* ]]; then
        # Extract path before .worktrees
        local base_path="${REPO_ROOT%%/.worktrees/*}"
        local grandparent="$(cd "$base_path/.." && pwd)"
        if [ -d "$grandparent/hypershift-automation" ]; then
            echo "$grandparent/hypershift-automation"
            return
        fi
    fi

    # Not found
    echo ""
}

HYPERSHIFT_AUTOMATION_DIR=$(find_hypershift_automation)

# Configuration with defaults
REPLICAS="${REPLICAS:-2}"
INSTANCE_TYPE="${INSTANCE_TYPE:-m5.xlarge}"
OCP_VERSION="${OCP_VERSION:-4.20.11}"

# NodePool autoscaling (optional)
# Set AUTOSCALE_MIN and AUTOSCALE_MAX to enable autoscaling
# When set, the NodePool will be configured with cluster-autoscaler after creation
AUTOSCALE_MIN="${AUTOSCALE_MIN:-}"
AUTOSCALE_MAX="${AUTOSCALE_MAX:-}"

# Cluster suffix - if not set, use positional arg, then default to username
# Set CLUSTER_SUFFIX="" to generate a random suffix
#
# Cluster name: ${MANAGED_BY_TAG}-${suffix}
# Default suffix: sanitized username (truncated to 5 chars for AWS IAM limits)
# Custom suffix: passed as argument (e.g., "pr529")
#
# Note: Truncated to 5 chars because default MANAGED_BY_TAG is 26 chars,
# max cluster name is 32 chars (AWS IAM limit), so 32-26-1=5 chars for suffix
SANITIZED_USER=$(echo "${USER:-local}" | tr '[:upper:]' '[:lower:]' | sed 's/[^a-z0-9]/-/g' | cut -c1-5)
if [ -n "${CLUSTER_SUFFIX+x}" ]; then
    # CLUSTER_SUFFIX is explicitly set (even if empty)
    :
elif [ $# -ge 1 ]; then
    CLUSTER_SUFFIX="$1"
else
    CLUSTER_SUFFIX="$SANITIZED_USER"
fi

# Generate random suffix if empty
if [ -z "$CLUSTER_SUFFIX" ]; then
    CLUSTER_SUFFIX=$(LC_ALL=C tr -dc 'a-z0-9' < /dev/urandom | head -c 6)
fi

# Validate cluster suffix for RFC1123 compliance (lowercase, alphanumeric, hyphens only)
if ! [[ "$CLUSTER_SUFFIX" =~ ^[a-z0-9]([a-z0-9-]*[a-z0-9])?$ ]]; then
    echo "Error: Invalid cluster suffix '$CLUSTER_SUFFIX'" >&2
    echo "" >&2
    echo "Cluster names must be valid RFC1123 labels:" >&2
    echo "  - Only lowercase letters (a-z), numbers (0-9), and hyphens (-)" >&2
    echo "  - Must start and end with an alphanumeric character" >&2
    echo "  - No underscores, uppercase letters, or special characters" >&2
    echo "" >&2
    echo "Examples of valid suffixes: pr529, test-1, my-cluster" >&2
    echo "Examples of invalid suffixes: PR529, test_1, -cluster-, my.cluster" >&2
    exit 1
fi

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m'

log_info() { echo -e "${BLUE}→${NC} $1"; }
log_success() { echo -e "${GREEN}✓${NC} $1"; }
log_warn() { echo -e "${YELLOW}⚠${NC} $1"; }
log_error() { echo -e "${RED}✗${NC} $1"; }

echo ""
echo "╔════════════════════════════════════════════════════════════════╗"
echo "║           Create HyperShift Cluster                            ║"
echo "╚════════════════════════════════════════════════════════════════╝"
echo ""

# ============================================================================
# 1. Load credentials
# ============================================================================

if [ "$CI_MODE" = "true" ]; then
    # CI mode: credentials are passed via environment variables from GitHub secrets
    # Required: MANAGED_BY_TAG, AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_REGION,
    #           BASE_DOMAIN, HCP_ROLE_NAME, KUBECONFIG (already set in GITHUB_ENV)
    log_success "Using CI credentials from environment"
elif [ -n "${AWS_ACCESS_KEY_ID:-}" ] && [ -n "${AWS_SECRET_ACCESS_KEY:-}" ] && [ -n "${KUBECONFIG:-}" ]; then
    # Credentials already in environment (user ran: source .env.xxx before script)
    log_success "Using pre-sourced credentials from environment"
    MANAGED_BY_TAG="${MANAGED_BY_TAG:-kagenti-hypershift-custom}"
else
    # Local mode: find and load .env file
    # Priority: 1) .env.${MANAGED_BY_TAG}, 2) legacy .env.hypershift-ci, 3) any .env.kagenti-*
    MANAGED_BY_TAG="${MANAGED_BY_TAG:-kagenti-hypershift-custom}"
    find_env_file() {
        if [ -f "$REPO_ROOT/.env.${MANAGED_BY_TAG}" ]; then
            echo "$REPO_ROOT/.env.${MANAGED_BY_TAG}"
        elif [ -f "$REPO_ROOT/.env.hypershift-ci" ]; then
            echo "$REPO_ROOT/.env.hypershift-ci"
        else
            ls "$REPO_ROOT"/.env.kagenti-* 2>/dev/null | head -1
        fi
    }

    ENV_FILE=$(find_env_file)
    if [ -z "$ENV_FILE" ] || [ ! -f "$ENV_FILE" ]; then
        log_error "No .env file found. Either:"
        log_error "  1. Run: source .env.${MANAGED_BY_TAG} before this script"
        log_error "  2. Run setup-hypershift-ci-credentials.sh to create .env file"
        exit 1
    fi
    # shellcheck source=/dev/null
    source "$ENV_FILE"
    log_success "Loaded credentials from $(basename "$ENV_FILE")"
fi

# Construct cluster name: ${MANAGED_BY_TAG}-${CLUSTER_SUFFIX}
# This ensures all clusters are prefixed correctly for IAM scoping
CLUSTER_NAME="${MANAGED_BY_TAG}-${CLUSTER_SUFFIX}"
log_success "Cluster name: $CLUSTER_NAME"

# ============================================================================
# 2. Verify prerequisites
# ============================================================================

if [ ! -d "$HYPERSHIFT_AUTOMATION_DIR" ]; then
    if [ "$CI_MODE" = "true" ]; then
        echo "Error: hypershift-automation not found at $HYPERSHIFT_AUTOMATION_DIR" >&2
        echo "Ensure the clone step ran before this script." >&2
    else
        echo "Error: hypershift-automation not found. Run local-setup.sh first." >&2
    fi
    exit 1
fi

if [ ! -f "$HOME/.pullsecret.json" ]; then
    if [ "$CI_MODE" = "true" ]; then
        echo "Error: Pull secret not found at ~/.pullsecret.json" >&2
        echo "Ensure the setup-credentials step ran before this script." >&2
    else
        echo "Error: Pull secret not found. Run local-setup.sh first." >&2
    fi
    exit 1
fi

# Verify KUBECONFIG is set
if [ -z "${KUBECONFIG:-}" ]; then
    if [ "$CI_MODE" = "true" ]; then
        echo "Error: KUBECONFIG not set. Check the setup-credentials step." >&2
    else
        echo "Error: KUBECONFIG not set. Is .env.hypershift-ci properly configured?" >&2
    fi
    exit 1
fi

if [ ! -f "$KUBECONFIG" ]; then
    echo "Error: KUBECONFIG file not found at $KUBECONFIG" >&2
    if [ "$CI_MODE" != "true" ]; then
        echo "Re-run setup-hypershift-ci-credentials.sh to regenerate it." >&2
    fi
    exit 1
fi

log_success "Using management cluster kubeconfig: $KUBECONFIG"

# ============================================================================
# 3. Verify AWS credentials
# ============================================================================

if [ -z "${AWS_ACCESS_KEY_ID:-}" ] || [ -z "${AWS_SECRET_ACCESS_KEY:-}" ]; then
    echo "Error: AWS credentials not set. Check .env.hypershift-ci" >&2
    exit 1
fi

log_success "AWS credentials configured"

# ============================================================================
# 4. Show configuration
# ============================================================================

echo ""
echo "Cluster configuration:"
echo "  Name:          $CLUSTER_NAME"
echo "  Region:        $AWS_REGION"
echo "  Replicas:      $REPLICAS"
if [[ -n "$AUTOSCALE_MIN" ]] && [[ -n "$AUTOSCALE_MAX" ]]; then
    echo "  Autoscaling:   min=$AUTOSCALE_MIN, max=$AUTOSCALE_MAX"
fi
echo "  Instance Type: $INSTANCE_TYPE"
echo "  OCP Version:   $OCP_VERSION"
echo "  Base Domain:   $BASE_DOMAIN"
echo "  IAM Scope Tag: kagenti.io/managed-by=$MANAGED_BY_TAG"
echo ""

# ============================================================================
# 5. Pre-flight check - verify no conflicting resources exist
# ============================================================================

CONTROL_PLANE_NS="clusters-$CLUSTER_NAME"

# Check if namespace already exists (indicates incomplete cleanup)
if oc get ns "$CONTROL_PLANE_NS" &>/dev/null; then
    echo ""
    echo "╔════════════════════════════════════════════════════════════════════════════╗"
    echo "║   ERROR: Control plane namespace already exists                            ║"
    echo "╚════════════════════════════════════════════════════════════════════════════╝"
    echo ""
    echo "Namespace: $CONTROL_PLANE_NS"
    echo ""
    echo "This indicates a previous cluster was not fully cleaned up."
    echo "Creating a new cluster with the same name will fail."
    echo ""
    echo "To fix this, run the destroy script first:"
    echo "  ./.github/scripts/hypershift/destroy-cluster.sh $CLUSTER_SUFFIX"
    echo ""
    echo "If the namespace is stuck, try force-deleting it:"
    echo "  oc delete ns $CONTROL_PLANE_NS --wait=false"
    echo "  oc patch ns $CONTROL_PLANE_NS -p '{\"metadata\":{\"finalizers\":null}}' --type=merge"
    echo ""
    exit 1
fi

# Check if HostedCluster resource already exists
if oc get hostedcluster "$CLUSTER_NAME" -n clusters &>/dev/null; then
    echo ""
    echo "╔════════════════════════════════════════════════════════════════════════════╗"
    echo "║   ERROR: HostedCluster resource already exists                             ║"
    echo "╚════════════════════════════════════════════════════════════════════════════╝"
    echo ""
    echo "HostedCluster: clusters/$CLUSTER_NAME"
    echo ""
    echo "To fix this, run the destroy script first:"
    echo "  ./.github/scripts/hypershift/destroy-cluster.sh $CLUSTER_SUFFIX"
    echo ""
    exit 1
fi

log_success "Pre-flight check passed - no conflicting resources"

# ============================================================================
# 6. Create cluster
# ============================================================================

log_info "Creating cluster (this may take 10-15 minutes)..."

cd "$HYPERSHIFT_AUTOMATION_DIR"

# Pass kagenti.io/managed-by tag for IAM scoping - this namespaced tag is applied
# to all AWS resources (VPC, subnets, security groups, EC2 instances, etc.) and
# allows IAM policies to restrict operations to only resources tagged with this value.
# The tag key follows Kubernetes label conventions to avoid conflicts with other tools.

# Build cluster config JSON
CLUSTER_CONFIG='"name": "'"$CLUSTER_NAME"'", "region": "'"$AWS_REGION"'", "replicas": '"$REPLICAS"', "instance_type": "'"$INSTANCE_TYPE"'", "image": "'"$OCP_VERSION"'"'

# Add autoscaling config if min and max are set
if [[ -n "$AUTOSCALE_MIN" ]] && [[ -n "$AUTOSCALE_MAX" ]]; then
    log_info "Autoscaling enabled: min=$AUTOSCALE_MIN, max=$AUTOSCALE_MAX"
    CLUSTER_CONFIG="$CLUSTER_CONFIG"', "autoscaling": {"min": '"$AUTOSCALE_MIN"', "max": '"$AUTOSCALE_MAX"'}'
fi

ansible-playbook site.yml \
    -e '{"create": true, "destroy": false, "create_iam": false}' \
    -e '{"iam": {"hcp_role_name": "'"$HCP_ROLE_NAME"'"}}' \
    -e "domain=$BASE_DOMAIN" \
    -e "additional_tags=kagenti.io/managed-by=${MANAGED_BY_TAG}" \
    -e '{"clusters": [{'"$CLUSTER_CONFIG"'}]}'

# ============================================================================
# 7. Summary and Next Steps
# ============================================================================

CLUSTER_KUBECONFIG="$HOME/clusters/hcp/$CLUSTER_NAME/auth/kubeconfig"
CLUSTER_INFO="$HOME/clusters/hcp/$CLUSTER_NAME/cluster-info.txt"

# Wait for cluster to be ready (both CI and local mode)
# Save management cluster kubeconfig before switching (needed for diagnostics)
MGMT_KUBECONFIG="$KUBECONFIG"

# Check if kubeconfig was created by Ansible
if [ ! -f "$CLUSTER_KUBECONFIG" ]; then
    log_error "Cluster kubeconfig not found at: $CLUSTER_KUBECONFIG"
    echo ""
    echo "Expected location: $CLUSTER_KUBECONFIG"
    echo "Checking if Ansible created it elsewhere..."
    ls -la "$HOME/clusters/hcp/" 2>/dev/null || echo "  Directory $HOME/clusters/hcp/ does not exist"
    ls -la "$HOME/clusters/hcp/$CLUSTER_NAME/" 2>/dev/null || echo "  Directory $HOME/clusters/hcp/$CLUSTER_NAME/ does not exist"
    ls -la "$HOME/clusters/hcp/$CLUSTER_NAME/auth/" 2>/dev/null || echo "  Directory $HOME/clusters/hcp/$CLUSTER_NAME/auth/ does not exist"
    exit 1
fi

export KUBECONFIG="$CLUSTER_KUBECONFIG"
log_info "Waiting for cluster API to be reachable..."

# Wait for API server with retries (up to 5 minutes)
for i in {1..30}; do
    if oc get nodes &>/dev/null; then
        log_success "Cluster API is reachable"
        break
    fi
    if [ $i -eq 30 ]; then
        log_warn "Cluster API not reachable after 5 minutes, continuing anyway..."
    else
        echo "  Attempt $i/30 - waiting for API server..."
        sleep 10
    fi
done

# ── NodePool health check ─────────────────────────────────────────────────
# Verify NodePool exists and is provisioning before waiting for nodes.
# NodePool name pattern: <cluster-name>-<az> (e.g. mycluster-us-east-1a)
CONTROL_PLANE_NS="clusters-$CLUSTER_NAME"
log_info "Checking NodePool health..."

NP_HEALTHY=false
for np_check in {1..18}; do  # 3 minutes (18 x 10s)
    NP_COUNT=$(KUBECONFIG="$MGMT_KUBECONFIG" oc get nodepool -n clusters \
        -o jsonpath='{.items[?(@.spec.clusterName=="'"$CLUSTER_NAME"'")].metadata.name}' 2>/dev/null | wc -w | tr -d ' ' || echo "0")
    [[ ! "$NP_COUNT" =~ ^[0-9]+$ ]] && NP_COUNT=0

    if [ "$NP_COUNT" -gt 0 ]; then
        NP_NAME=$(KUBECONFIG="$MGMT_KUBECONFIG" oc get nodepool -n clusters \
            -o jsonpath='{.items[?(@.spec.clusterName=="'"$CLUSTER_NAME"'")].metadata.name}' 2>/dev/null | awk '{print $1}')
        NP_DESIRED=$(KUBECONFIG="$MGMT_KUBECONFIG" oc get nodepool -n clusters "$NP_NAME" \
            -o jsonpath='{.spec.replicas}' 2>/dev/null || echo "0")
        log_success "NodePool '$NP_NAME' found (desired replicas: $NP_DESIRED)"
        NP_HEALTHY=true
        break
    fi
    echo "  Attempt $np_check/18 - waiting for NodePool to be created..."
    sleep 10
done

if [ "$NP_HEALTHY" != "true" ]; then
    log_error "No NodePool found for cluster $CLUSTER_NAME after 3 minutes"
    echo ""
    echo "  The HostedCluster exists but no NodePool was created."
    echo "  This typically indicates an operator issue or resource exhaustion."
    echo ""
    echo "  HostedCluster conditions:"
    KUBECONFIG="$MGMT_KUBECONFIG" oc get hostedcluster -n clusters "$CLUSTER_NAME" \
        -o jsonpath='{range .status.conditions[*]}{.type}{": "}{.status}{" - "}{.message}{"\n"}{end}' 2>/dev/null || true
    exit 1
fi

# ── Wait for nodes ────────────────────────────────────────────────────────
log_info "Waiting for at least one node to be ready..."
for i in {1..90}; do  # 15 minutes (90 x 10s)
    # Use || true to prevent pipefail from exiting on API errors during wait
    NODE_COUNT=$(oc get nodes --no-headers 2>/dev/null | wc -l | tr -d ' ' || echo "0")
    # Validate NODE_COUNT is numeric
    [[ ! "$NODE_COUNT" =~ ^[0-9]+$ ]] && NODE_COUNT=0
    if [ "$NODE_COUNT" -gt 0 ]; then
        log_info "Found $NODE_COUNT node(s), waiting for Ready condition..."
        break
    fi
    if [ $i -eq 90 ]; then
        log_error "No nodes appeared after 15 minutes"
        echo ""
        echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        echo "DIAGNOSTIC INFO"
        echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        echo ""
        echo "HostedCluster status (check conditions for errors):"
        KUBECONFIG="$MGMT_KUBECONFIG" oc get hostedcluster -n clusters "$CLUSTER_NAME" -o wide 2>/dev/null || true
        echo ""
        echo "HostedCluster conditions:"
        KUBECONFIG="$MGMT_KUBECONFIG" oc get hostedcluster -n clusters "$CLUSTER_NAME" \
            -o jsonpath='{range .status.conditions[*]}{.type}{": "}{.status}{" - "}{.message}{"\n"}{end}' 2>/dev/null || true
        echo ""
        echo "NodePool status:"
        KUBECONFIG="$MGMT_KUBECONFIG" oc get nodepool -n clusters -o wide 2>/dev/null | grep "$CLUSTER_NAME" || echo "(not found)"
        echo ""
        echo "NodePool conditions:"
        KUBECONFIG="$MGMT_KUBECONFIG" oc get nodepool -n clusters "$NP_NAME" \
            -o jsonpath='{range .status.conditions[*]}{.type}{": "}{.status}{" - "}{.message}{"\n"}{end}' 2>/dev/null || true
        echo ""
        echo "Machine status:"
        KUBECONFIG="$MGMT_KUBECONFIG" oc get machines -n "$CONTROL_PLANE_NS" 2>/dev/null || true
        echo ""
        echo "Machine failure reasons (if any):"
        # Get status message for each machine in Failed phase
        KUBECONFIG="$MGMT_KUBECONFIG" oc get machines -n "$CONTROL_PLANE_NS" -o json 2>/dev/null | \
            jq -r '.items[] | select(.status.phase == "Failed") | "  \(.metadata.name): \(.status.errorMessage // .status.conditions[-1].message // "unknown")"' 2>/dev/null || true
        echo ""
        echo "EC2 instances:"
        aws ec2 describe-instances --region "$AWS_REGION" \
            --filters "Name=tag-key,Values=kubernetes.io/cluster/$CLUSTER_NAME" \
            --query 'Reservations[*].Instances[*].[InstanceId,State.Name,InstanceType]' \
            --output table 2>/dev/null || true
        echo ""
        echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        exit 1
    fi
    # Show status every 5 attempts
    if [ $((i % 5)) -eq 0 ]; then
        HC_PROGRESS=$(KUBECONFIG="$MGMT_KUBECONFIG" oc get hostedcluster -n clusters "$CLUSTER_NAME" -o jsonpath='{.status.conditions[?(@.type=="Available")].message}' 2>/dev/null || echo "unknown")
        NP_REPLICAS=$(KUBECONFIG="$MGMT_KUBECONFIG" oc get nodepool -n clusters "$NP_NAME" -o jsonpath='{.status.replicas}' 2>/dev/null || echo "0")
        NP_READY=$(KUBECONFIG="$MGMT_KUBECONFIG" oc get nodepool -n clusters "$NP_NAME" -o jsonpath='{.status.conditions[?(@.type=="Ready")].status}' 2>/dev/null || echo "unknown")
        MACHINE_COUNT=$(KUBECONFIG="$MGMT_KUBECONFIG" oc get machines -n "$CONTROL_PLANE_NS" --no-headers 2>/dev/null | wc -l | tr -d ' ' || echo "0")
        echo "  Attempt $i/90 - HostedCluster: $HC_PROGRESS"
        echo "               - NodePool: replicas=$NP_REPLICAS ready=$NP_READY machines=$MACHINE_COUNT"
    else
        echo "  Attempt $i/90 - waiting for nodes to appear..."
    fi
    sleep 10
done
# Now wait for nodes to be Ready
oc wait --for=condition=Ready nodes --all --timeout=600s || {
    log_error "Timeout waiting for nodes to be Ready"
    oc get nodes
    exit 1
}
oc get nodes
oc get clusterversion

log_success "Cluster $CLUSTER_NAME created and ready"

# In CI mode, output for subsequent steps
if [ "$CI_MODE" = "true" ]; then
    echo "cluster_kubeconfig=$CLUSTER_KUBECONFIG" >> "$GITHUB_OUTPUT"
    echo "cluster_name=$CLUSTER_NAME" >> "$GITHUB_OUTPUT"
else
    # Local mode: show next steps
    echo ""
    echo "╔════════════════════════════════════════════════════════════════════════════╗"
    echo "║                           Cluster Created                                  ║"
    echo "╚════════════════════════════════════════════════════════════════════════════╝"
    echo ""

    if [ -f "$CLUSTER_INFO" ]; then
        echo "Cluster info (console URL, credentials):"
        echo "  cat $CLUSTER_INFO"
        echo ""
    fi

    cat << EOF
# ┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
# ┃ PHASE 3: DEPLOY KAGENTI + E2E (uses hosted cluster kubeconfig)              ┃
# ┃ Credentials: KUBECONFIG from created cluster (cluster-admin on hosted)      ┃
# ┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛
export KUBECONFIG=$CLUSTER_KUBECONFIG
oc get nodes

./.github/scripts/kagenti-operator/30-run-installer.sh --env ocp
./.github/scripts/kagenti-operator/41-wait-crds.sh
./.github/scripts/kagenti-operator/42-apply-pipeline-template.sh

./.github/scripts/kagenti-operator/71-build-weather-tool.sh
./.github/scripts/kagenti-operator/72-deploy-weather-tool.sh
./.github/scripts/kagenti-operator/73-patch-weather-tool.sh
./.github/scripts/kagenti-operator/74-deploy-weather-agent.sh

export AGENT_URL="https://\$(oc get route -n team1 weather-service -o jsonpath='{.spec.host}')"
export KAGENTI_CONFIG_FILE=deployments/envs/ocp_values.yaml
./.github/scripts/kagenti-operator/90-run-e2e-tests.sh

# ┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
# ┃ CLEANUP: Destroy cluster (uses scoped CI credentials)                       ┃
# ┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛
source .env.hypershift-ci
./.github/scripts/hypershift/destroy-cluster.sh ${CLUSTER_SUFFIX}
EOF
    echo ""
fi
