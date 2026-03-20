#!/usr/bin/env bash
#
# Deploy Agent-Sandbox Controller
#
# Installs the kubernetes-sigs/agent-sandbox controller on the cluster:
#   - CRDs (Sandbox, SandboxTemplate, SandboxClaim, SandboxWarmPool)
#   - Namespace, RBAC, ServiceAccount
#   - Controller StatefulSet (built on-cluster via OpenShift Build)
#   - SandboxTemplate with hardening defaults in agent namespaces
#
# Prerequisites:
#   - Cluster must be accessible via KUBECONFIG
#   - OpenShift Build system must be available
#
# Usage:
#   ./.github/scripts/kagenti-operator/35-deploy-agent-sandbox.sh
#
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
source "$SCRIPT_DIR/../lib/logging.sh"

log_step "35" "Deploy Agent-Sandbox Controller"

AGENT_SANDBOX_RESEARCH_DIR="${AGENT_SANDBOX_RESEARCH_DIR:-$REPO_ROOT/.worktrees/sandbox_research/agent-sandbox}"
AGENT_SANDBOX_NS="agent-sandbox-system"
AGENT_SANDBOX_IMAGE_REF="us-central1-docker.pkg.dev/k8s-staging-images/agent-sandbox/agent-sandbox-controller:latest-main"

# Check if agent-sandbox research repo is available (for CRDs/RBAC)
# Fall back to applying from git if not
if [ ! -d "$AGENT_SANDBOX_RESEARCH_DIR/k8s/crds" ]; then
    log_warn "Agent-sandbox research dir not found at $AGENT_SANDBOX_RESEARCH_DIR"
    log_info "Applying CRDs directly from GitHub..."
    APPLY_FROM_GIT=true
else
    APPLY_FROM_GIT=false
fi

# ── Step 1: Install CRDs ──────────────────────────────────────────────────────
log_info "Installing agent-sandbox CRDs..."
if [ "$APPLY_FROM_GIT" = "true" ]; then
    for crd in agents.x-k8s.io_sandboxes extensions.agents.x-k8s.io_sandboxclaims extensions.agents.x-k8s.io_sandboxtemplates extensions.agents.x-k8s.io_sandboxwarmpools; do
        kubectl apply -f "https://raw.githubusercontent.com/kubernetes-sigs/agent-sandbox/main/k8s/crds/${crd}.yaml"
    done
else
    kubectl apply -f "$AGENT_SANDBOX_RESEARCH_DIR/k8s/crds/"
fi

# Verify CRDs
for crd in sandboxes.agents.x-k8s.io sandboxtemplates.extensions.agents.x-k8s.io sandboxclaims.extensions.agents.x-k8s.io sandboxwarmpools.extensions.agents.x-k8s.io; do
    kubectl wait --for=condition=Established crd/"$crd" --timeout=30s
done
log_success "Agent-sandbox CRDs installed"

# ── Step 2: Namespace + RBAC ──────────────────────────────────────────────────
log_info "Creating namespace and RBAC..."
kubectl create namespace "$AGENT_SANDBOX_NS" 2>/dev/null || true
kubectl create serviceaccount agent-sandbox-controller -n "$AGENT_SANDBOX_NS" 2>/dev/null || true

if [ "$APPLY_FROM_GIT" = "true" ]; then
    kubectl apply -f "https://raw.githubusercontent.com/kubernetes-sigs/agent-sandbox/main/k8s/rbac.generated.yaml"
    kubectl apply -f "https://raw.githubusercontent.com/kubernetes-sigs/agent-sandbox/main/k8s/extensions-rbac.generated.yaml"
    kubectl apply -f "https://raw.githubusercontent.com/kubernetes-sigs/agent-sandbox/main/k8s/extensions.yaml"
else
    kubectl apply -f "$AGENT_SANDBOX_RESEARCH_DIR/k8s/rbac.generated.yaml"
    kubectl apply -f "$AGENT_SANDBOX_RESEARCH_DIR/k8s/extensions-rbac.generated.yaml"
    kubectl apply -f "$AGENT_SANDBOX_RESEARCH_DIR/k8s/extensions.yaml"
fi

# Extra RBAC for finalizers (needed for ownerReference blockOwnerDeletion)
kubectl apply -f - <<'EOF'
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: agent-sandbox-controller-extra
rules:
- apiGroups: ["agents.x-k8s.io"]
  resources: ["sandboxes/finalizers"]
  verbs: ["update"]
- apiGroups: ["extensions.agents.x-k8s.io"]
  resources: ["sandboxclaims/finalizers", "sandboxwarmpools/finalizers", "sandboxtemplates/finalizers"]
  verbs: ["update"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: agent-sandbox-controller-extra
subjects:
- kind: ServiceAccount
  name: agent-sandbox-controller
  namespace: agent-sandbox-system
roleRef:
  kind: ClusterRole
  name: agent-sandbox-controller-extra
  apiGroup: rbac.authorization.k8s.io
EOF
log_success "RBAC configured"

# ── Step 3: Deploy Controller ─────────────────────────────────────────────────
log_info "Deploying agent-sandbox controller..."

# Check if OpenShift Build is available for on-cluster image build
if oc api-resources --api-group=build.openshift.io 2>/dev/null | grep -q BuildConfig; then
    log_info "OpenShift Build available — building controller on-cluster..."

    # Create ImageStream
    oc create imagestream agent-sandbox-controller -n "$AGENT_SANDBOX_NS" 2>/dev/null || true

    # Create BuildConfig
    kubectl apply -f - <<EOF
apiVersion: build.openshift.io/v1
kind: BuildConfig
metadata:
  name: agent-sandbox-controller
  namespace: $AGENT_SANDBOX_NS
spec:
  output:
    to:
      kind: ImageStreamTag
      name: agent-sandbox-controller:latest
  source:
    type: Git
    git:
      uri: https://github.com/kubernetes-sigs/agent-sandbox.git
      ref: main
  strategy:
    type: Docker
    dockerStrategy:
      dockerfilePath: Dockerfile
EOF

    # Start build and wait
    log_info "Starting controller image build (this takes ~4 minutes)..."
    oc start-build agent-sandbox-controller -n "$AGENT_SANDBOX_NS" --follow

    AGENT_SANDBOX_IMAGE_REF="image-registry.openshift-image-registry.svc:5000/$AGENT_SANDBOX_NS/agent-sandbox-controller:latest"
    log_success "Controller image built: $AGENT_SANDBOX_IMAGE_REF"
else
    log_info "No OpenShift Build — using staging image: $AGENT_SANDBOX_IMAGE_REF"
fi

# Apply controller manifest (upstream changed from StatefulSet to Deployment in #191)
if [ "$APPLY_FROM_GIT" = "true" ]; then
    kubectl apply -f "https://raw.githubusercontent.com/kubernetes-sigs/agent-sandbox/main/k8s/controller.yaml"
else
    kubectl apply -f "$AGENT_SANDBOX_RESEARCH_DIR/k8s/controller.yaml"
fi

# Clean up old StatefulSet if it exists (upstream migrated to Deployment)
kubectl delete statefulset agent-sandbox-controller -n "$AGENT_SANDBOX_NS" 2>/dev/null || true

# Patch controller deployment with real image and enable extensions
kubectl patch deployment agent-sandbox-controller -n "$AGENT_SANDBOX_NS" --type='json' -p='[
  {"op":"replace","path":"/spec/template/spec/containers/0/image","value":"'"$AGENT_SANDBOX_IMAGE_REF"'"},
  {"op":"replace","path":"/spec/template/spec/containers/0/args","value":["--extensions=true"]}
]'

# Wait for controller to be ready
log_info "Waiting for controller pod..."
kubectl rollout status deployment/agent-sandbox-controller -n "$AGENT_SANDBOX_NS" --timeout=120s
log_success "Agent-sandbox controller running"

# ── Step 4: Deploy SandboxTemplate ────────────────────────────────────────────
log_info "Deploying SandboxTemplate to agent namespaces..."

# Check if gVisor RuntimeClass exists on the cluster
GVISOR_RUNTIME=""
if kubectl get runtimeclass gvisor 2>/dev/null; then
    GVISOR_RUNTIME="gvisor"
    log_info "gVisor RuntimeClass detected — enabling in SandboxTemplate"
fi

for NS in team1 team2; do
    kubectl get namespace "$NS" 2>/dev/null || continue
    kubectl apply -f - <<EOF
apiVersion: extensions.agents.x-k8s.io/v1alpha1
kind: SandboxTemplate
metadata:
  name: kagenti-agent-sandbox
  namespace: $NS
spec:
  podTemplate:
    metadata:
      labels:
        app.kubernetes.io/part-of: kagenti
        app.kubernetes.io/component: agent-sandbox
    spec:
      ${GVISOR_RUNTIME:+runtimeClassName: $GVISOR_RUNTIME}
      automountServiceAccountToken: false
      securityContext:
        runAsNonRoot: true
        seccompProfile:
          type: RuntimeDefault
      containers:
      - name: agent
        image: python:3.11-slim
        command: ["/bin/sh", "-c", "echo 'Sandbox ready'; sleep 36000"]
        ports:
        - containerPort: 8080
          protocol: TCP
        securityContext:
          allowPrivilegeEscalation: false
          readOnlyRootFilesystem: true
          capabilities:
            drop:
            - ALL
        resources:
          requests:
            cpu: "250m"
            memory: "512Mi"
          limits:
            cpu: "2"
            memory: "4Gi"
        volumeMounts:
        - name: workspace
          mountPath: /workspace
        - name: tmp
          mountPath: /tmp
      volumes:
      - name: workspace
        emptyDir: {}
      - name: tmp
        emptyDir: {}
  networkPolicy:
    ingress: []
    egress:
    - ports:
      - protocol: UDP
        port: 53
      - protocol: TCP
        port: 53
EOF
    log_success "SandboxTemplate deployed to $NS"
done

log_success "Agent-sandbox controller fully deployed"
