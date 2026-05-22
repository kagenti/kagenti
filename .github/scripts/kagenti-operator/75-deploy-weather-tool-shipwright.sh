#!/bin/bash
# Copyright 2025 IBM Corp.
# Licensed under the Apache License, Version 2.0

# This script demonstrates deploying the weather tool using Shipwright source build.
# It creates a Build resource, triggers a BuildRun, waits for the image to be built,
# then creates a Deployment + Service for the tool.

set -e

NAMESPACE="${NAMESPACE:-team1}"
TOOL_NAME="weather-tool"
GIT_URL="${GIT_URL:-https://github.com/kagenti/agent-examples}"
GIT_BRANCH="${GIT_BRANCH:-main}"
GIT_PATH="${GIT_PATH:-mcp/weather_tool}"
IMAGE_TAG="${IMAGE_TAG:-v0.0.1}"

# Set registry based on environment (OpenShift vs Kind)
# Source env-detect if available to get IS_OPENSHIFT
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ -f "$SCRIPT_DIR/../lib/env-detect.sh" ]; then
    source "$SCRIPT_DIR/../lib/env-detect.sh"
fi

if [ "${IS_OPENSHIFT:-false}" = "true" ]; then
    REGISTRY="${REGISTRY:-image-registry.openshift-image-registry.svc:5000/${NAMESPACE}}"
else
    REGISTRY="${REGISTRY:-registry.cr-system.svc.cluster.local:5000}"
fi

echo "=== Deploying Weather Tool via Shipwright Build ==="
echo "Namespace: ${NAMESPACE}"
echo "Git URL: ${GIT_URL}"
echo "Git Branch: ${GIT_BRANCH}"
echo "Git Path: ${GIT_PATH}"
echo "Registry: ${REGISTRY}"
echo "Image Tag: ${IMAGE_TAG}"
echo ""

# Step 1: Create the Shipwright Build
echo "Step 1: Creating Shipwright Build resource..."
cat <<EOF | kubectl apply -f -
apiVersion: shipwright.io/v1beta1
kind: Build
metadata:
  name: ${TOOL_NAME}
  namespace: ${NAMESPACE}
  labels:
    kagenti.io/type: tool
    kagenti.io/managed-by: shipwright
  annotations:
    kagenti.io/tool-config: |
      {
        "protocol": "streamable_http",
        "framework": "Python",
        "description": "Weather lookup tool for MCP",
        "createHttpRoute": false,
        "workloadType": "deployment",
        "envVars": [],
        "servicePorts": [{"containerPort": 8000, "servicePort": 80}]
      }
spec:
  source:
    type: Git
    git:
      url: ${GIT_URL}
      revision: ${GIT_BRANCH}
    contextDir: ${GIT_PATH}
  strategy:
    name: buildah-insecure
    kind: ClusterBuildStrategy
  output:
    image: ${REGISTRY}/${TOOL_NAME}:${IMAGE_TAG}
EOF

echo "Build resource created."

# Step 2: Create BuildRun to start the build
echo ""
echo "Step 2: Creating BuildRun to start container image build..."
BUILDRUN_NAME="${TOOL_NAME}-run-$(date +%s)"
cat <<EOF | kubectl apply -f -
apiVersion: shipwright.io/v1beta1
kind: BuildRun
metadata:
  name: ${BUILDRUN_NAME}
  namespace: ${NAMESPACE}
  labels:
    kagenti.io/type: tool
    kagenti.io/build-name: ${TOOL_NAME}
spec:
  build:
    name: ${TOOL_NAME}
EOF

echo "BuildRun '${BUILDRUN_NAME}' created."

# Step 3: Wait for BuildRun to complete
echo ""
echo "Step 3: Waiting for BuildRun to complete..."
echo "This may take several minutes depending on the build complexity."

TIMEOUT=600  # 10 minutes
ELAPSED=0
POLL_INTERVAL=10

while [ $ELAPSED -lt $TIMEOUT ]; do
    STATUS=$(kubectl get buildrun "${BUILDRUN_NAME}" -n "${NAMESPACE}" -o jsonpath='{.status.conditions[?(@.type=="Succeeded")].status}' 2>/dev/null || echo "")
    REASON=$(kubectl get buildrun "${BUILDRUN_NAME}" -n "${NAMESPACE}" -o jsonpath='{.status.conditions[?(@.type=="Succeeded")].reason}' 2>/dev/null || echo "")

    if [ "$STATUS" == "True" ]; then
        echo "BuildRun succeeded!"
        break
    elif [ "$STATUS" == "False" ]; then
        echo "BuildRun failed with reason: ${REASON}"
        kubectl get buildrun "${BUILDRUN_NAME}" -n "${NAMESPACE}" -o yaml
        exit 1
    else
        echo "BuildRun status: ${REASON:-Pending}... (${ELAPSED}s elapsed)"
    fi

    sleep $POLL_INTERVAL
    ELAPSED=$((ELAPSED + POLL_INTERVAL))
done

if [ $ELAPSED -ge $TIMEOUT ]; then
    echo "Timeout waiting for BuildRun to complete"
    exit 1
fi

# Step 4: Get the output image
echo ""
echo "Step 4: Retrieving output image..."
OUTPUT_IMAGE=$(kubectl get buildrun "${BUILDRUN_NAME}" -n "${NAMESPACE}" -o jsonpath='{.status.output.image}')
OUTPUT_DIGEST=$(kubectl get buildrun "${BUILDRUN_NAME}" -n "${NAMESPACE}" -o jsonpath='{.status.output.digest}')
echo "Output Image: ${OUTPUT_IMAGE}"
echo "Output Digest: ${OUTPUT_DIGEST}"

# Step 5: Create Deployment for the tool
echo ""
echo "Step 5: Creating Deployment resource..."
cat <<EOF | kubectl apply -f -
apiVersion: apps/v1
kind: Deployment
metadata:
  name: ${TOOL_NAME}
  namespace: ${NAMESPACE}
  labels:
    kagenti.io/type: tool
    protocol.kagenti.io/mcp: ""
    kagenti.io/transport: streamable_http
    kagenti.io/built-by: shipwright
    kagenti.io/build-name: ${TOOL_NAME}
    app.kubernetes.io/name: ${TOOL_NAME}
  annotations:
    kagenti.io/description: "Weather lookup tool for MCP (built by Shipwright)"
    kagenti.io/shipwright-build: "${TOOL_NAME}"
spec:
  replicas: 1
  selector:
    matchLabels:
      kagenti.io/type: tool
      app.kubernetes.io/name: ${TOOL_NAME}
  template:
    metadata:
      labels:
        kagenti.io/type: tool
        protocol.kagenti.io/mcp: ""
        kagenti.io/transport: streamable_http
        app.kubernetes.io/name: ${TOOL_NAME}
    spec:
      securityContext:
        runAsNonRoot: true
        seccompProfile:
          type: RuntimeDefault
      containers:
        - name: mcp
          image: ${OUTPUT_IMAGE}
          imagePullPolicy: Always
          ports:
            - containerPort: 8000
              name: http
              protocol: TCP
          resources:
            limits:
              cpu: "500m"
              memory: "512Mi"
            requests:
              cpu: "100m"
              memory: "128Mi"
          volumeMounts:
            - name: tmp
              mountPath: /tmp
          securityContext:
            allowPrivilegeEscalation: false
            capabilities:
              drop: ["ALL"]
            # Note: runAsUser removed for OpenShift compatibility
            # OpenShift assigns UID from namespace's allowed range
      volumes:
        - name: tmp
          emptyDir: {}
EOF

# Step 5b: Create Service
echo "Creating Service..."
cat <<EOF | kubectl apply -f -
apiVersion: v1
kind: Service
metadata:
  name: ${TOOL_NAME}-mcp
  namespace: ${NAMESPACE}
  labels:
    kagenti.io/type: tool
    protocol.kagenti.io/mcp: ""
    app.kubernetes.io/name: ${TOOL_NAME}
spec:
  type: ClusterIP
  selector:
    kagenti.io/type: tool
    app.kubernetes.io/name: ${TOOL_NAME}
  ports:
    - name: http
      port: 8000
      targetPort: 8000
      protocol: TCP
EOF

echo "Deployment '${TOOL_NAME}' and Service '${TOOL_NAME}-mcp' created."

# Step 6: Wait for Deployment to be ready
echo ""
echo "Step 6: Waiting for Deployment to be ready..."
kubectl wait --for=condition=available "deployment/${TOOL_NAME}" -n "${NAMESPACE}" --timeout=120s || {
    echo "Warning: Deployment not ready within timeout, checking status..."
    kubectl get "deployment/${TOOL_NAME}" -n "${NAMESPACE}" -o yaml
}

echo ""
echo "=== Weather Tool Deployment Complete ==="
echo "Tool Name: ${TOOL_NAME}"
echo "Namespace: ${NAMESPACE}"
echo "Image: ${OUTPUT_IMAGE}"
echo "Service: ${TOOL_NAME}-mcp"
echo ""
echo "To verify the tool is running:"
echo "  kubectl get deployment ${TOOL_NAME} -n ${NAMESPACE}"
echo "  kubectl get service ${TOOL_NAME}-mcp -n ${NAMESPACE}"
echo "  kubectl get pods -l app.kubernetes.io/name=${TOOL_NAME} -n ${NAMESPACE}"
