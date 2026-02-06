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

# ToolHive CRD Definitions
TOOLHIVE_CRD_GROUP = settings.toolhive_crd_group
TOOLHIVE_CRD_VERSION = settings.toolhive_crd_version
TOOLHIVE_MCP_PLURAL = settings.toolhive_mcp_plural

# Labels - Keys
KAGENTI_TYPE_LABEL = settings.kagenti_type_label
KAGENTI_PROTOCOL_LABEL = settings.kagenti_protocol_label
KAGENTI_FRAMEWORK_LABEL = settings.kagenti_framework_label
KAGENTI_TRANSPORT_LABEL = "kagenti.io/transport"
KAGENTI_WORKLOAD_TYPE_LABEL = "kagenti.io/workload-type"
KAGENTI_DESCRIPTION_ANNOTATION = "kagenti.io/description"
APP_KUBERNETES_IO_CREATED_BY = "app.kubernetes.io/created-by"
APP_KUBERNETES_IO_NAME = "app.kubernetes.io/name"
APP_KUBERNETES_IO_MANAGED_BY = "app.kubernetes.io/managed-by"
APP_KUBERNETES_IO_COMPONENT = "app.kubernetes.io/component"

# Labels - Values
KAGENTI_UI_CREATOR_LABEL = "kagenti-ui"
KAGENTI_OPERATOR_LABEL_NAME = "kagenti-operator"

# Resource types
RESOURCE_TYPE_AGENT = "agent"
RESOURCE_TYPE_TOOL = "tool"

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

# Supported workload types
SUPPORTED_WORKLOAD_TYPES = [
    WORKLOAD_TYPE_DEPLOYMENT,
    WORKLOAD_TYPE_STATEFULSET,
    WORKLOAD_TYPE_JOB,
]

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

# Default internal registry URL (for dev/kind clusters)
DEFAULT_INTERNAL_REGISTRY = "registry.cr-system.svc.cluster.local:5000"

# Default resource limits
DEFAULT_RESOURCE_LIMITS = {"cpu": "500m", "memory": "1Gi"}
DEFAULT_RESOURCE_REQUESTS = {"cpu": "100m", "memory": "256Mi"}

# Migration (Phase 4: Agent CRD to Deployment migration)
# Annotation to mark migrated resources
MIGRATION_SOURCE_ANNOTATION = "kagenti.io/migrated-from"
MIGRATION_TIMESTAMP_ANNOTATION = "kagenti.io/migration-timestamp"
# Label to identify legacy Agent CRD resources
LEGACY_AGENT_CRD_LABEL = "kagenti.io/legacy-crd"

# Migration (Phase 5: MCPServer CRD to Deployment migration)
# Annotation to track original Toolhive service name
ORIGINAL_SERVICE_ANNOTATION = "kagenti.io/original-service"
# Toolhive service naming pattern: mcp-{name}-proxy
TOOLHIVE_SERVICE_PREFIX = "mcp-"
TOOLHIVE_SERVICE_SUFFIX = "-proxy"
# Migration source values
MIGRATION_SOURCE_AGENT_CRD = "agent-crd"
MIGRATION_SOURCE_MCPSERVER_CRD = "mcpserver-crd"

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
