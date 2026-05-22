#!/usr/bin/env bash
# Deploy test agent and tool workloads for token exchange E2E.
#
# Creates:
#   - tx-e2e-tool: A simple HTTP echo server (acts as MCP tool)
#   - tx-e2e-agent: A simple HTTP server (acts as agent calling the tool)
#
# Both get kagenti sidecars injected by the webhook (namespace is kagenti-enabled).
set -euo pipefail
source "$(dirname "$0")/lib.sh"

log_step "70" "Deploy test workloads"

# --- tx-e2e-tool (MCP tool mock) ---
log_info "Deploying tx-e2e-tool"
kubectl create sa tx-e2e-tool -n "$TX_NAMESPACE" 2>/dev/null || true

cat <<'EOF' | kubectl apply -n "$TX_NAMESPACE" -f -
apiVersion: apps/v1
kind: Deployment
metadata:
  name: tx-e2e-tool
  labels:
    app: tx-e2e-tool
    kagenti.io/type: tool
spec:
  replicas: 1
  selector:
    matchLabels:
      app: tx-e2e-tool
  template:
    metadata:
      labels:
        app: tx-e2e-tool
        kagenti.io/type: tool
    spec:
      serviceAccountName: tx-e2e-tool
      containers:
      - name: tool
        image: python:3.11-slim
        command:
        - python3
        - -c
        - |
          from http.server import HTTPServer, BaseHTTPRequestHandler
          import json, os

          class Handler(BaseHTTPRequestHandler):
              def do_GET(self):
                  # Echo back all headers (useful for verifying token injection)
                  headers = {k: v for k, v in self.headers.items()}
                  body = json.dumps({
                      "status": "ok",
                      "path": self.path,
                      "headers": headers,
                      "service": "tx-e2e-tool"
                  })
                  self.send_response(200)
                  self.send_header("Content-Type", "application/json")
                  self.end_headers()
                  self.wfile.write(body.encode())

              def do_POST(self):
                  content_len = int(self.headers.get("Content-Length", 0))
                  body_in = self.rfile.read(content_len).decode() if content_len else ""
                  headers = {k: v for k, v in self.headers.items()}
                  body = json.dumps({
                      "status": "ok",
                      "path": self.path,
                      "headers": headers,
                      "body": body_in,
                      "service": "tx-e2e-tool"
                  })
                  self.send_response(200)
                  self.send_header("Content-Type", "application/json")
                  self.end_headers()
                  self.wfile.write(body.encode())

              def log_message(self, fmt, *args):
                  pass  # Suppress noisy logs

          server = HTTPServer(("0.0.0.0", 8080), Handler)
          print("tx-e2e-tool listening on :8080", flush=True)
          server.serve_forever()
        ports:
        - containerPort: 8080
        readinessProbe:
          httpGet:
            path: /health
            port: 8080
          initialDelaySeconds: 2
          periodSeconds: 5
---
apiVersion: v1
kind: Service
metadata:
  name: tx-e2e-tool
spec:
  selector:
    app: tx-e2e-tool
  ports:
  - port: 8080
    targetPort: 8080
EOF

# --- tx-e2e-agent (agent mock that calls the tool) ---
log_info "Deploying tx-e2e-agent"
kubectl create sa tx-e2e-agent -n "$TX_NAMESPACE" 2>/dev/null || true

cat <<'EOF' | kubectl apply -n "$TX_NAMESPACE" -f -
apiVersion: apps/v1
kind: Deployment
metadata:
  name: tx-e2e-agent
  labels:
    app: tx-e2e-agent
    kagenti.io/type: agent
spec:
  replicas: 1
  selector:
    matchLabels:
      app: tx-e2e-agent
  template:
    metadata:
      labels:
        app: tx-e2e-agent
        kagenti.io/type: agent
    spec:
      serviceAccountName: tx-e2e-agent
      containers:
      - name: agent
        image: python:3.11-slim
        command:
        - python3
        - -c
        - |
          from http.server import HTTPServer, BaseHTTPRequestHandler
          import json, urllib.request, os

          TOOL_URL = os.environ.get("TOOL_URL", "http://tx-e2e-tool:8080")

          class Handler(BaseHTTPRequestHandler):
              def do_GET(self):
                  if self.path == "/.well-known/agent-card.json":
                      card = {"name": "tx-e2e-agent", "version": "1.0", "capabilities": ["echo"]}
                      self.send_response(200)
                      self.send_header("Content-Type", "application/json")
                      self.end_headers()
                      self.wfile.write(json.dumps(card).encode())
                      return
                  headers = {k: v for k, v in self.headers.items()}
                  body = json.dumps({"status": "ok", "path": self.path, "headers": headers, "service": "tx-e2e-agent"})
                  self.send_response(200)
                  self.send_header("Content-Type", "application/json")
                  self.end_headers()
                  self.wfile.write(body.encode())

              def do_POST(self):
                  content_len = int(self.headers.get("Content-Length", 0))
                  body_in = self.rfile.read(content_len).decode() if content_len else ""
                  # Forward to tool (authbridge envoy will perform token exchange)
                  try:
                      req = urllib.request.Request(
                          f"{TOOL_URL}/echo",
                          data=body_in.encode(),
                          headers={
                              "Content-Type": "application/json",
                              "Authorization": self.headers.get("Authorization", ""),
                          },
                      )
                      with urllib.request.urlopen(req) as resp:
                          tool_resp = json.loads(resp.read().decode())
                  except Exception as e:
                      tool_resp = {"error": str(e)}

                  body = json.dumps({
                      "status": "ok",
                      "agent": "tx-e2e-agent",
                      "tool_response": tool_resp,
                      "inbound_headers": {k: v for k, v in self.headers.items()},
                  })
                  self.send_response(200)
                  self.send_header("Content-Type", "application/json")
                  self.end_headers()
                  self.wfile.write(body.encode())

              def log_message(self, fmt, *args):
                  pass

          server = HTTPServer(("0.0.0.0", 8080), Handler)
          print("tx-e2e-agent listening on :8080", flush=True)
          server.serve_forever()
        ports:
        - containerPort: 8080
        env:
        - name: TOOL_URL
          value: "http://tx-e2e-tool:8080"
        readinessProbe:
          httpGet:
            path: /health
            port: 8080
          initialDelaySeconds: 2
          periodSeconds: 5
---
apiVersion: v1
kind: Service
metadata:
  name: tx-e2e-agent
spec:
  selector:
    app: tx-e2e-agent
  ports:
  - port: 8080
    targetPort: 8080
EOF

# --- AgentRuntime CRs ---
log_info "Creating AgentRuntime CRs"
cat <<EOF | kubectl apply -n "$TX_NAMESPACE" -f -
apiVersion: agent.kagenti.dev/v1alpha1
kind: AgentRuntime
metadata:
  name: tx-e2e-tool-runtime
spec:
  type: tool
  targetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: tx-e2e-tool
---
apiVersion: agent.kagenti.dev/v1alpha1
kind: AgentRuntime
metadata:
  name: tx-e2e-agent-runtime
spec:
  type: agent
  targetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: tx-e2e-agent
EOF

# --- Wait for rollouts ---
log_info "Waiting for workloads to be ready..."

# Wait for pods to be injected and running (sidecars take time)
for deploy in tx-e2e-tool tx-e2e-agent; do
  log_info "Waiting for $deploy..."
  kubectl rollout status "deployment/$deploy" -n "$TX_NAMESPACE" --timeout=300s 2>/dev/null || {
    log_warn "$deploy not ready after 300s — checking pod status"
    kubectl get pods -n "$TX_NAMESPACE" -l "app=$deploy" 2>/dev/null || true
  }
done

# Wait for keycloak client credentials to be created by the operator
log_info "Waiting for keycloak client credentials..."
for i in $(seq 1 60); do
  CRED_COUNT=$(kubectl get secrets -n "$TX_NAMESPACE" -o name 2>/dev/null | grep -c kagenti-keycloak-client-credentials || echo "0")
  if [[ "$CRED_COUNT" -ge 2 ]]; then
    log_success "Found $CRED_COUNT keycloak credential secrets"
    break
  fi
  if [[ "$i" -eq 60 ]]; then
    log_warn "Only found $CRED_COUNT credential secrets after 5 min"
  fi
  sleep 5
done

log_success "Test workloads deployed in $TX_NAMESPACE"
