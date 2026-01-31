#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../lib/env-detect.sh"
source "$SCRIPT_DIR/../lib/logging.sh"
source "$SCRIPT_DIR/../lib/k8s-utils.sh"

log_step "72" "Deploying weather-tool via Deployment + Service"

# Create Deployment
cat <<'DEPLOYMENT_EOF' | kubectl apply -f -
apiVersion: apps/v1
kind: Deployment
metadata:
  name: weather-tool
  namespace: team1
  labels:
    kagenti.io/type: tool
    kagenti.io/protocol: mcp
    kagenti.io/transport: streamable_http
    kagenti.io/framework: Python
    app.kubernetes.io/name: weather-tool
    app.kubernetes.io/managed-by: e2e-test
  annotations:
    kagenti.io/description: "Weather MCP tool for E2E testing"
spec:
  replicas: 1
  selector:
    matchLabels:
      kagenti.io/type: tool
      app.kubernetes.io/name: weather-tool
  template:
    metadata:
      labels:
        kagenti.io/type: tool
        kagenti.io/protocol: mcp
        kagenti.io/transport: streamable_http
        kagenti.io/framework: Python
        app.kubernetes.io/name: weather-tool
    spec:
      securityContext:
        runAsNonRoot: true
        seccompProfile:
          type: RuntimeDefault
      containers:
        - name: mcp
          image: registry.cr-system.svc.cluster.local:5000/weather-tool:v0.0.1
          imagePullPolicy: Always
          env:
            - name: PORT
              value: "8000"
            - name: HOST
              value: "0.0.0.0"
            - name: OTEL_EXPORTER_OTLP_ENDPOINT
              value: "http://otel-collector.kagenti-system.svc.cluster.local:8335"
            - name: KEYCLOAK_URL
              value: "http://keycloak.keycloak.svc.cluster.local:8080"
            - name: UV_NO_CACHE
              value: "1"
            - name: LLM_API_BASE
              value: "http://dockerhost:11434/v1"
            - name: LLM_API_KEY
              value: "dummy"
            - name: LLM_MODEL
              value: "qwen2.5:0.5b"
          ports:
            - containerPort: 8000
              name: http
              protocol: TCP
          resources:
            requests:
              cpu: 100m
              memory: 256Mi
            limits:
              cpu: 500m
              memory: 1Gi
          volumeMounts:
            - name: cache
              mountPath: /app/.cache
            - name: tmp
              mountPath: /tmp
          securityContext:
            allowPrivilegeEscalation: false
            capabilities:
              drop: ["ALL"]
            # Note: runAsUser removed for OpenShift compatibility
            # OpenShift assigns UID from namespace's allowed range
      volumes:
        - name: cache
          emptyDir: {}
        - name: tmp
          emptyDir: {}
DEPLOYMENT_EOF

# Create Service
cat <<'SERVICE_EOF' | kubectl apply -f -
apiVersion: v1
kind: Service
metadata:
  name: weather-tool-mcp
  namespace: team1
  labels:
    kagenti.io/type: tool
    kagenti.io/protocol: mcp
    app.kubernetes.io/name: weather-tool
    app.kubernetes.io/managed-by: e2e-test
spec:
  type: ClusterIP
  selector:
    kagenti.io/type: tool
    app.kubernetes.io/name: weather-tool
  ports:
    - name: http
      port: 8000
      targetPort: 8000
      protocol: TCP
SERVICE_EOF

# Wait for deployment to be available
wait_for_deployment "weather-tool" "team1" 300 || {
    log_error "Weather-tool deployment not ready"
    kubectl get deployment weather-tool -n team1
    kubectl describe deployment weather-tool -n team1
    kubectl get pods -n team1 -l app.kubernetes.io/name=weather-tool
    exit 1
}

log_success "Weather-tool deployed successfully via Deployment + Service"
