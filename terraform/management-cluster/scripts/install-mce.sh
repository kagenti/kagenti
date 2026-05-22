#!/usr/bin/env bash
#
# Install multicluster-engine (MCE) 2.10 on OpenShift management cluster
#
# This installs MCE 2.10 which includes HyperShift operator supporting OpenShift 4.19-4.21

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TF_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

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
echo "║        Install MCE 2.10 (HyperShift Operator)                 ║"
echo "╚════════════════════════════════════════════════════════════════╝"
echo ""

# Configuration
MCE_VERSION="${MCE_VERSION:-2.10}"
MCE_CHANNEL="stable-${MCE_VERSION}"
MCE_NAMESPACE="multicluster-engine"

# Check prerequisites
if ! command -v oc &> /dev/null; then
    log_error "oc CLI not found. Please install OpenShift CLI."
    exit 1
fi

if [ -z "${KUBECONFIG:-}" ]; then
    log_error "KUBECONFIG not set"
    log_info "Example: export KUBECONFIG=~/openshift-clusters/my-cluster/auth/kubeconfig"
    exit 1
fi

# Verify cluster access
if ! oc cluster-info &> /dev/null; then
    log_error "Cannot access OpenShift cluster. Check your KUBECONFIG."
    exit 1
fi

CLUSTER_VERSION=$(oc get clusterversion version -o jsonpath='{.status.desired.version}')
log_info "Connected to cluster running OpenShift $CLUSTER_VERSION"

# Verify this is OpenShift (not a hosted cluster)
if ! oc get namespace openshift-marketplace &> /dev/null; then
    log_error "This doesn't appear to be a full OpenShift cluster"
    log_error "MCE must be installed on the management cluster, not a hosted cluster"
    exit 1
fi

log_success "Prerequisites check passed"
echo ""

# Create namespace
log_info "Creating namespace: $MCE_NAMESPACE..."
oc create namespace "$MCE_NAMESPACE" 2>/dev/null || log_warn "Namespace already exists"

# Create OperatorGroup
log_info "Creating OperatorGroup..."
oc apply -f - <<EOF
apiVersion: operators.coreos.com/v1
kind: OperatorGroup
metadata:
  name: multicluster-engine-operatorgroup
  namespace: $MCE_NAMESPACE
spec:
  targetNamespaces:
  - $MCE_NAMESPACE
EOF

# Create Subscription
log_info "Creating Subscription for MCE $MCE_VERSION..."
oc apply -f - <<EOF
apiVersion: operators.coreos.com/v1alpha1
kind: Subscription
metadata:
  name: multicluster-engine
  namespace: $MCE_NAMESPACE
spec:
  channel: $MCE_CHANNEL
  installPlanApproval: Automatic
  name: multicluster-engine
  source: redhat-operators
  sourceNamespace: openshift-marketplace
EOF

log_success "MCE operator subscription created"
echo ""

# Wait for operator to be ready
log_info "Waiting for MCE operator to be ready (this may take 5-10 minutes)..."
MAX_WAIT=600
ELAPSED=0

while [ $ELAPSED -lt $MAX_WAIT ]; do
    CSV_PHASE=$(oc get csv -n "$MCE_NAMESPACE" \
        -l operators.coreos.com/multicluster-engine."$MCE_NAMESPACE"="" \
        -o jsonpath='{.items[0].status.phase}' 2>/dev/null || echo "Unknown")

    if [ "$CSV_PHASE" = "Succeeded" ]; then
        log_success "MCE operator is ready"
        break
    fi

    printf "\r${BLUE}→${NC} Waiting for operator... (${ELAPSED}s/${MAX_WAIT}s) Status: $CSV_PHASE"
    sleep 10
    ((ELAPSED+=10))
done
echo ""

if [ "$CSV_PHASE" != "Succeeded" ]; then
    log_error "Timeout waiting for MCE operator to be ready"
    log_info "Check operator status: oc get csv -n $MCE_NAMESPACE"
    exit 1
fi

# Create MultiClusterEngine instance
log_info "Creating MultiClusterEngine instance with HyperShift enabled..."
oc apply -f - <<EOF
apiVersion: multicluster.openshift.io/v1
kind: MultiClusterEngine
metadata:
  name: multiclusterengine
spec:
  targetNamespace: multicluster-engine
  overrides:
    components:
    - name: hypershift
      enabled: true
    - name: hypershift-local-hosting
      enabled: true
    - name: console-mce
      enabled: true
EOF

log_success "MultiClusterEngine instance created"
echo ""

# Wait for HyperShift operator
log_info "Waiting for HyperShift operator to be ready..."
MAX_WAIT=600
ELAPSED=0

while [ $ELAPSED -lt $MAX_WAIT ]; do
    if oc get deployment operator -n hypershift &> /dev/null; then
        READY_REPLICAS=$(oc get deployment operator -n hypershift \
            -o jsonpath='{.status.readyReplicas}' 2>/dev/null || echo "0")

        if [ "$READY_REPLICAS" -gt 0 ]; then
            log_success "HyperShift operator is ready"
            break
        fi
    fi

    printf "\r${BLUE}→${NC} Waiting for HyperShift operator... (${ELAPSED}s/${MAX_WAIT}s)"
    sleep 10
    ((ELAPSED+=10))
done
echo ""

if [ "$READY_REPLICAS" -eq 0 ]; then
    log_error "Timeout waiting for HyperShift operator"
    log_info "Check deployment: oc get deployment operator -n hypershift"
    exit 1
fi

# Verify installation
echo ""
log_info "Verifying installation..."
echo ""

OPERATOR_IMAGE=$(oc get deployment operator -n hypershift \
    -o jsonpath='{.spec.template.spec.containers[0].image}')

echo "MultiClusterEngine:"
oc get multiclusterengine

echo ""
echo "HyperShift Operator:"
echo "  Image: $OPERATOR_IMAGE"
oc get deployment operator -n hypershift

echo ""
echo "╔════════════════════════════════════════════════════════════════╗"
echo "║                  MCE 2.10 Installation Complete               ║"
echo "╚════════════════════════════════════════════════════════════════╝"
echo ""
echo "Your management cluster is now ready to create OpenShift hosted clusters!"
echo "MCE 2.10 supports OpenShift 4.19, 4.20, and 4.21 for hosted clusters."
echo ""
echo "Next steps:"
echo "1. Configure AWS credentials and HyperShift settings"
echo "2. Create a hosted cluster using the kagenti scripts:"
echo "   ./.github/scripts/local-setup/hypershift-full-test.sh <cluster-suffix> --skip-cluster-destroy"
echo ""
