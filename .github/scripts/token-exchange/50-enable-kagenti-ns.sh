#!/usr/bin/env bash
# Enable kagenti sidecar injection in the token exchange test namespace.
#
# Creates the namespace, labels it, and creates all required configmaps
# for authbridge envoy mode (spiffe-helper, envoy-config, authbridge configs).
set -euo pipefail
source "$(dirname "$0")/lib.sh"

log_step "50" "Enable kagenti in namespace $TX_NAMESPACE"

PLATFORM="${PLATFORM:-$(detect_platform)}"

# Determine Keycloak host
if [[ "$PLATFORM" == "ocp" ]]; then
  KC_HOST="${KEYCLOAK_HOST:-$(kubectl get route -n "$KC_NAMESPACE" -o jsonpath='{.items[0].spec.host}' 2>/dev/null)}"
else
  KC_HOST="${KEYCLOAK_HOST:-keycloak.localtest.me}"
fi
KC_URL=$(get_keycloak_url)

# Create namespace
kubectl create namespace "$TX_NAMESPACE" 2>/dev/null || true

# Label namespace for sidecar injection
log_info "Labeling namespace $TX_NAMESPACE"
kubectl label namespace "$TX_NAMESPACE" \
  kagenti-enabled=true \
  pod-security.kubernetes.io/audit=privileged \
  pod-security.kubernetes.io/audit-version=latest \
  pod-security.kubernetes.io/warn=privileged \
  pod-security.kubernetes.io/warn-version=latest \
  --overwrite

# Grant SCC on OCP
if [[ "$PLATFORM" == "ocp" ]]; then
  oc adm policy add-scc-to-group kagenti-authbridge "system:serviceaccounts:${TX_NAMESPACE}" 2>/dev/null || true
fi

# --- spiffe-helper-config ---
log_info "Creating spiffe-helper-config"
cat <<EOF | kubectl apply -n "$TX_NAMESPACE" -f -
apiVersion: v1
kind: ConfigMap
metadata:
  name: spiffe-helper-config
data:
  helper.conf: |
    agent_address = "/spiffe-workload-api/spire-agent.sock"
    cmd = ""
    cmd_args = ""
    svid_file_name = "/opt/svid.pem"
    svid_key_file_name = "/opt/svid_key.pem"
    svid_bundle_file_name = "/opt/svid_bundle.pem"
    cert_file_mode = 0644
    key_file_mode = 0640
    jwt_svids = [{jwt_audience="https://${KC_HOST}/realms/${TX_REALM}", jwt_svid_file_name="/opt/jwt_svid.token"}]
    jwt_svid_file_mode = 0644
    include_federated_domains = true
EOF

# --- envoy-config ---
log_info "Creating envoy-config"
cat <<'ENVOY_EOF' | kubectl apply -n "$TX_NAMESPACE" -f -
apiVersion: v1
kind: ConfigMap
metadata:
  name: envoy-config
data:
  envoy.yaml: |
    admin:
      address:
        socket_address:
          protocol: TCP
          address: 127.0.0.1
          port_value: 9901
    static_resources:
      listeners:
      - name: outbound_listener
        address:
          socket_address:
            protocol: TCP
            address: 0.0.0.0
            port_value: 15123
        listener_filters:
        - name: envoy.filters.listener.original_dst
          typed_config:
            "@type": type.googleapis.com/envoy.extensions.filters.listener.original_dst.v3.OriginalDst
        - name: envoy.filters.listener.tls_inspector
          typed_config:
            "@type": type.googleapis.com/envoy.extensions.filters.listener.tls_inspector.v3.TlsInspector
        filter_chains:
        - filter_chain_match:
            transport_protocol: tls
          filters:
          - name: envoy.filters.network.tcp_proxy
            typed_config:
              "@type": type.googleapis.com/envoy.extensions.filters.network.tcp_proxy.v3.TcpProxy
              stat_prefix: outbound_tls_passthrough
              cluster: original_destination
        - filter_chain_match:
            transport_protocol: raw_buffer
          filters:
          - name: envoy.filters.network.http_connection_manager
            typed_config:
              "@type": type.googleapis.com/envoy.extensions.filters.network.http_connection_manager.v3.HttpConnectionManager
              stat_prefix: outbound_http
              codec_type: AUTO
              route_config:
                name: outbound_routes
                virtual_hosts:
                - name: catch_all
                  domains: ["*"]
                  routes:
                  - match:
                      prefix: "/"
                    route:
                      cluster: original_destination
                      timeout: 300s
              http_filters:
              - name: envoy.filters.http.ext_proc
                typed_config:
                  "@type": type.googleapis.com/envoy.extensions.filters.http.ext_proc.v3.ExternalProcessor
                  grpc_service:
                    envoy_grpc:
                      cluster_name: ext_proc_cluster
                    timeout: 300s
                  processing_mode:
                    request_header_mode: SEND
                    response_header_mode: SKIP
                    request_body_mode: NONE
                    response_body_mode: NONE
              - name: envoy.filters.http.router
                typed_config:
                  "@type": type.googleapis.com/envoy.extensions.filters.http.router.v3.Router
      - name: inbound_listener
        address:
          socket_address:
            protocol: TCP
            address: 0.0.0.0
            port_value: 15124
        listener_filters:
        - name: envoy.filters.listener.original_dst
          typed_config:
            "@type": type.googleapis.com/envoy.extensions.filters.listener.original_dst.v3.OriginalDst
        filter_chains:
        - filters:
          - name: envoy.filters.network.http_connection_manager
            typed_config:
              "@type": type.googleapis.com/envoy.extensions.filters.network.http_connection_manager.v3.HttpConnectionManager
              stat_prefix: inbound_http
              codec_type: AUTO
              route_config:
                name: inbound_routes
                virtual_hosts:
                - name: local_app
                  domains: ["*"]
                  routes:
                  - match:
                      prefix: "/"
                    route:
                      cluster: original_destination
                      timeout: 300s
              http_filters:
              - name: envoy.filters.http.lua
                typed_config:
                  "@type": type.googleapis.com/envoy.extensions.filters.http.lua.v3.Lua
                  inline_code: |
                    function envoy_on_request(request_handle)
                      request_handle:headers():add("x-authbridge-direction", "inbound")
                    end
              - name: envoy.filters.http.ext_proc
                typed_config:
                  "@type": type.googleapis.com/envoy.extensions.filters.http.ext_proc.v3.ExternalProcessor
                  grpc_service:
                    envoy_grpc:
                      cluster_name: ext_proc_cluster
                    timeout: 300s
                  processing_mode:
                    request_header_mode: SEND
                    response_header_mode: SKIP
                    request_body_mode: NONE
                    response_body_mode: NONE
              - name: envoy.filters.http.router
                typed_config:
                  "@type": type.googleapis.com/envoy.extensions.filters.http.router.v3.Router
      clusters:
      - name: original_destination
        connect_timeout: 30s
        type: ORIGINAL_DST
        lb_policy: CLUSTER_PROVIDED
        original_dst_lb_config:
          use_http_header: false
      - name: ext_proc_cluster
        connect_timeout: 5s
        type: STATIC
        lb_policy: ROUND_ROBIN
        http2_protocol_options: {}
        load_assignment:
          cluster_name: ext_proc_cluster
          endpoints:
          - lb_endpoints:
            - endpoint:
                address:
                  socket_address:
                    address: 127.0.0.1
                    port_value: 9090
ENVOY_EOF

# --- authbridge-runtime-config ---
log_info "Creating authbridge-runtime-config"
KC_INTERNAL="http://keycloak-service.${KC_NAMESPACE}.svc:8080"
cat <<EOF | kubectl apply -n "$TX_NAMESPACE" -f -
apiVersion: v1
kind: ConfigMap
metadata:
  name: authbridge-runtime-config
data:
  config.yaml: |
    mode: envoy-sidecar
    bypass:
      inbound_paths:
        - "/.well-known/*"
        - "/health"
        - "/healthz"
        - "/readyz"
        - "/livez"
    identity:
      type: "client-secret"
      client_id_file: "/shared/client-id.txt"
      client_secret_file: "/shared/client-secret.txt"
    inbound:
      issuer: "https://${KC_HOST}/realms/${TX_REALM}"
      expected_audience: "${TX_CLIENT_ID}"
    outbound:
      keycloak_url: "https://${KC_HOST}"
      keycloak_realm: "${TX_REALM}"
      default_policy: "passthrough"
    routes:
      file: "/etc/authproxy/routes.yaml"
EOF

# --- authproxy-routes ---
log_info "Creating authproxy-routes"
cat <<'EOF' | kubectl apply -n "$TX_NAMESPACE" -f -
apiVersion: v1
kind: ConfigMap
metadata:
  name: authproxy-routes
data:
  routes.yaml: ""
EOF

# --- authbridge-config ---
log_info "Creating authbridge-config"
cat <<EOF | kubectl apply -n "$TX_NAMESPACE" -f -
apiVersion: v1
kind: ConfigMap
metadata:
  name: authbridge-config
data:
  KEYCLOAK_URL: "https://${KC_HOST}"
  KEYCLOAK_REALM: "${TX_REALM}"
  KEYCLOAK_NAMESPACE: "${KC_NAMESPACE}"
  ISSUER: "https://${KC_HOST}/realms/${TX_REALM}"
  SPIRE_ENABLED: "false"
  CLIENT_AUTH_TYPE: "client-secret"
  SPIFFE_IDP_ALIAS: "spire-spiffe"
  JWT_AUDIENCE: "https://${KC_HOST}/realms/${TX_REALM}"
  EXPECTED_AUDIENCE: "${TX_CLIENT_ID}"
  DEFAULT_OUTBOUND_POLICY: "passthrough"
EOF

# --- keycloak-admin-secret ---
# Note: keycloak-admin-secret is now managed by the operator in kagenti-system namespace.
# The operator reads credentials from there to register OAuth clients for workloads.
# No longer created in agent namespaces for security reasons.
log_info "Skipping keycloak-admin-secret creation (managed by operator in kagenti-system)"

# --- Add namespace to operator's NAMESPACES2WATCH ---
log_info "Adding $TX_NAMESPACE to operator NAMESPACES2WATCH"
OPERATOR_DEPLOY=$(kubectl get deploy -n kagenti-system -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || true)
kubectl get deploy kagenti-controller-manager -n kagenti-system &>/dev/null && OPERATOR_DEPLOY="kagenti-controller-manager"

if [[ -n "$OPERATOR_DEPLOY" ]]; then
  CURRENT=$(kubectl get deploy "$OPERATOR_DEPLOY" -n kagenti-system -o jsonpath='{.spec.template.spec.containers[0].env[?(@.name=="NAMESPACES2WATCH")].value}' 2>/dev/null || true)
  if [[ -n "$CURRENT" ]]; then
    if echo ",$CURRENT," | grep -q ",${TX_NAMESPACE},"; then
      log_info "$TX_NAMESPACE already in NAMESPACES2WATCH"
    else
      NEW="${CURRENT},${TX_NAMESPACE}"
      IDX=$(kubectl get deploy "$OPERATOR_DEPLOY" -n kagenti-system -o json | jq '.spec.template.spec.containers[0].env // [] | to_entries[] | select(.value.name=="NAMESPACES2WATCH") | .key')
      kubectl patch deploy "$OPERATOR_DEPLOY" -n kagenti-system --type=json \
        -p="[{\"op\":\"replace\",\"path\":\"/spec/template/spec/containers/0/env/${IDX}/value\",\"value\":\"${NEW}\"}]"
    fi
  else
    HAS_ENV=$(kubectl get deploy "$OPERATOR_DEPLOY" -n kagenti-system -o jsonpath='{.spec.template.spec.containers[0].env}' 2>/dev/null)
    if [[ -n "$HAS_ENV" && "$HAS_ENV" != "null" ]]; then
      kubectl patch deploy "$OPERATOR_DEPLOY" -n kagenti-system --type=json \
        -p="[{\"op\":\"add\",\"path\":\"/spec/template/spec/containers/0/env/-\",\"value\":{\"name\":\"NAMESPACES2WATCH\",\"value\":\"${TX_NAMESPACE}\"}}]"
    else
      kubectl patch deploy "$OPERATOR_DEPLOY" -n kagenti-system --type=json \
        -p="[{\"op\":\"add\",\"path\":\"/spec/template/spec/containers/0/env\",\"value\":[{\"name\":\"NAMESPACES2WATCH\",\"value\":\"${TX_NAMESPACE}\"}]}]"
    fi
  fi
fi

log_success "kagenti enabled in namespace $TX_NAMESPACE"
