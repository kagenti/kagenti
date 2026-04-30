# Copyright 2025 IBM Corp.
# Licensed under the Apache License, Version 2.0

"""
Constants shared across the application.
"""

from app.core.config import settings

# Kubernetes CRD Definitions (agent.kagenti.dev)
CRD_GROUP = settings.crd_group
CRD_VERSION = settings.crd_version
AGENTS_PLURAL = settings.agents_plural
AGENTRUNTIMES_PLURAL = settings.agentruntimes_plural

# Labels - Keys
KAGENTI_TYPE_LABEL = settings.kagenti_type_label
KAGENTI_PROTOCOL_LABEL = settings.kagenti_protocol_label  # deprecated; use PROTOCOL_LABEL_PREFIX
KAGENTI_FRAMEWORK_LABEL = settings.kagenti_framework_label

# Multi-protocol label prefix: protocol.kagenti.io/<name>
# The existence of a label with this prefix implies support for the named protocol.
PROTOCOL_LABEL_PREFIX = "protocol.kagenti.io/"
KAGENTI_INJECT_LABEL = "kagenti.io/inject"
KAGENTI_TRANSPORT_LABEL = "kagenti.io/transport"
KAGENTI_WORKLOAD_TYPE_LABEL = "kagenti.io/workload-type"
KAGENTI_DESCRIPTION_ANNOTATION = "kagenti.io/description"
APP_KUBERNETES_IO_CREATED_BY = "app.kubernetes.io/created-by"
APP_KUBERNETES_IO_NAME = "app.kubernetes.io/name"
APP_KUBERNETES_IO_MANAGED_BY = "app.kubernetes.io/managed-by"
APP_KUBERNETES_IO_COMPONENT = "app.kubernetes.io/component"

# SPIRE identity labels (matched by kagenti-webhook pod_mutator.go)
KAGENTI_SPIRE_LABEL = "kagenti.io/spire"
KAGENTI_SPIRE_ENABLED_VALUE = "enabled"

# Per-sidecar injection labels (matched by kagenti-webhook precedence evaluator)
KAGENTI_ENVOY_PROXY_INJECT_LABEL = "kagenti.io/envoy-proxy-inject"
KAGENTI_SPIFFE_HELPER_INJECT_LABEL = "kagenti.io/spiffe-helper-inject"
KAGENTI_CLIENT_REGISTRATION_INJECT_LABEL = "kagenti.io/client-registration-inject"

# Port exclusion annotations (matched by kagenti-webhook init-iptables.sh)
KAGENTI_OUTBOUND_PORTS_EXCLUDE = "kagenti.io/outbound-ports-exclude"
KAGENTI_INBOUND_PORTS_EXCLUDE = "kagenti.io/inbound-ports-exclude"

# Labels - Values
KAGENTI_UI_CREATOR_LABEL = "kagenti-ui"
KAGENTI_OPERATOR_LABEL_NAME = "kagenti-operator"

# Resource types
RESOURCE_TYPE_AGENT = "agent"
RESOURCE_TYPE_TOOL = "tool"
RESOURCE_TYPE_SKILL = "skill"


# Protocol values
VALUE_PROTOCOL_A2A = "a2a"
VALUE_PROTOCOL_MCP = "mcp"

# Transport values (for MCP tools)
VALUE_TRANSPORT_STREAMABLE_HTTP = "streamable_http"
VALUE_TRANSPORT_SSE = "sse"

# Service naming for tools
# Tools use {name}-mcp service naming convention
TOOL_SERVICE_SUFFIX = "-mcp"

# Workload types for agent deployment
WORKLOAD_TYPE_DEPLOYMENT = "deployment"
WORKLOAD_TYPE_STATEFULSET = "statefulset"
WORKLOAD_TYPE_JOB = "job"
WORKLOAD_TYPE_SANDBOX = "sandbox"

# agent-sandbox CRD coordinates (kubernetes-sigs/agent-sandbox)
AGENT_SANDBOX_CRD_GROUP = "agents.x-k8s.io"
AGENT_SANDBOX_CRD_VERSION = "v1alpha1"
AGENT_SANDBOX_PLURAL = "sandboxes"

# agent-sandbox extensions (SandboxTemplate, SandboxClaim)
AGENT_SANDBOX_EXT_GROUP = "extensions.agents.x-k8s.io"
AGENT_SANDBOX_EXT_VERSION = "v1alpha1"
AGENT_SANDBOX_TEMPLATE_PLURAL = "sandboxtemplates"
AGENT_SANDBOX_CLAIM_PLURAL = "sandboxclaims"

# Supported workload types (sandbox added conditionally at startup)
_BASE_WORKLOAD_TYPES = (
    WORKLOAD_TYPE_DEPLOYMENT,
    WORKLOAD_TYPE_STATEFULSET,
    WORKLOAD_TYPE_JOB,
)
SUPPORTED_WORKLOAD_TYPES = list(
    _BASE_WORKLOAD_TYPES
    + ((WORKLOAD_TYPE_SANDBOX,) if settings.kagenti_feature_flag_agent_sandbox else ())
)

# Namespace labels
ENABLED_NAMESPACE_LABEL_KEY = settings.enabled_namespace_label_key
ENABLED_NAMESPACE_LABEL_VALUE = settings.enabled_namespace_label_value

# Default ports
DEFAULT_IN_CLUSTER_PORT = 8000
DEFAULT_OFF_CLUSTER_PORT = 8080

# Default values
DEFAULT_IMAGE_TAG = "v0.0.1"
DEFAULT_IMAGE_POLICY = "Always"
PYTHON_VERSION = "3.13"
OPERATOR_NS = "kagenti-system"
GIT_USER_SECRET_NAME = "github-token-secret"

# Shipwright CRD Definitions (shipwright.io)
SHIPWRIGHT_CRD_GROUP = "shipwright.io"
SHIPWRIGHT_CRD_VERSION = "v1beta1"
SHIPWRIGHT_BUILDS_PLURAL = "builds"
SHIPWRIGHT_BUILDRUNS_PLURAL = "buildruns"
SHIPWRIGHT_CLUSTER_BUILD_STRATEGIES_PLURAL = "clusterbuildstrategies"
# Argument to collect_kagenti_shipwright_builds / label_selector_for_kagenti_builds:
# use RESOURCE_TYPE_AGENT or RESOURCE_TYPE_TOOL for a single type, or this for both.
SHIPWRIGHT_BUILDS_LIST_SCOPE_ALL = "all"

# Shipwright defaults
SHIPWRIGHT_GIT_SECRET_NAME = "github-shipwright-secret"
SHIPWRIGHT_DEFAULT_DOCKERFILE = "Dockerfile"
SHIPWRIGHT_DEFAULT_TIMEOUT = "15m"
SHIPWRIGHT_DEFAULT_RETENTION_SUCCEEDED = 3
SHIPWRIGHT_DEFAULT_RETENTION_FAILED = 3

# Shipwright build strategies
# For internal registries without TLS (dev/kind clusters)
SHIPWRIGHT_STRATEGY_INSECURE = "buildah-insecure-push"
# For external registries with TLS (quay.io, ghcr.io, docker.io)
SHIPWRIGHT_STRATEGY_SECURE = "buildah"

# Default internal registry URL (configurable via DEFAULT_REGISTRY_URL env var)
DEFAULT_INTERNAL_REGISTRY = settings.default_registry_url

# Default resource limits
DEFAULT_RESOURCE_LIMITS = {"cpu": "500m", "memory": "1Gi"}
DEFAULT_RESOURCE_REQUESTS = {"cpu": "100m", "memory": "256Mi"}

# Migration (Phase 4: Agent CRD to Deployment migration)
# Annotation to mark migrated resources
MIGRATION_SOURCE_ANNOTATION = "kagenti.io/migrated-from"
MIGRATION_TIMESTAMP_ANNOTATION = "kagenti.io/migration-timestamp"
# Label to identify legacy Agent CRD resources
LEGACY_AGENT_CRD_LABEL = "kagenti.io/legacy-crd"

# Default environment variables for agents
DEFAULT_ENV_VARS = [
    {"name": "PORT", "value": "8000"},
    {"name": "HOST", "value": "0.0.0.0"},
    {
        "name": "OTEL_EXPORTER_OTLP_ENDPOINT",
        "value": "http://otel-collector.kagenti-system.svc.cluster.local:8335",
    },
    {
        "name": "KEYCLOAK_URL",
        "value": "http://keycloak.keycloak.svc.cluster.local:8080",
    },
    {"name": "UV_CACHE_DIR", "value": "/app/.cache/uv"},
]


# Skill management constants
SKILL_TYPE_LABEL = "kagenti.io/type"
SKILL_TYPE_VALUE = "skill"
SKILL_CATEGORY_LABEL = "kagenti.io/category"
SKILL_DESCRIPTION_ANNOTATION = "kagenti.io/description"
SKILL_ORIGIN_ANNOTATION = "kagenti.io/origin"
SKILL_USAGE_ANNOTATION = "kagenti.io/usage-count"
SKILL_FILE_PATHS_ANNOTATION = "kagenti.io/file-paths"
SKILL_STATUS_READY = "Ready"
# Environment variable name for the agent endpoint (the agent card URL for the agent)
AGENT_ENDPOINT = "AGENT_ENDPOINT"

# Default Keycloak in-cluster URL (used by AuthBridge ConfigMaps)
DEFAULT_KEYCLOAK_INTERNAL_URL = "http://keycloak-service.keycloak.svc:8080"
DEFAULT_KEYCLOAK_REALM = "kagenti"

# Default spiffe-helper configuration for AuthBridge sidecars
DEFAULT_SPIFFE_HELPER_CONF = (
    'agent_address = "/spiffe-workload-api/spire-agent.sock"\n'
    'cmd = ""\n'
    'cmd_args = ""\n'
    'svid_file_name = "/opt/svid.pem"\n'
    'svid_key_file_name = "/opt/svid_key.pem"\n'
    'svid_bundle_file_name = "/opt/svid_bundle.pem"\n'
    'jwt_svids = [{jwt_audience="kagenti", jwt_svid_file_name="/opt/jwt_svid.token"}]\n'
    "jwt_svid_file_mode = 0644\n"
    "include_federated_domains = true\n"
)

# Default envoy-config for AuthBridge sidecars.
# Matches the Helm chart template in charts/kagenti/templates/agent-namespaces.yaml.
DEFAULT_ENVOY_YAML = """\
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
    # AuthBridge config and stats passthrough
    - filter_chain_match:
        destination_port: 9093
      filters:
      - name: envoy.filters.network.tcp_proxy
        typed_config:
          "@type": type.googleapis.com/envoy.extensions.filters.network.tcp_proxy.v3.TcpProxy
          stat_prefix: outbound_passthrough_9093
          cluster: original_destination
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
"""
