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
AGENTBUILDS_PLURAL = settings.agentbuilds_plural

# ToolHive CRD Definitions
TOOLHIVE_CRD_GROUP = settings.toolhive_crd_group
TOOLHIVE_CRD_VERSION = settings.toolhive_crd_version
TOOLHIVE_MCP_PLURAL = settings.toolhive_mcp_plural

# Labels
KAGENTI_TYPE_LABEL = settings.kagenti_type_label
KAGENTI_PROTOCOL_LABEL = settings.kagenti_protocol_label
KAGENTI_FRAMEWORK_LABEL = settings.kagenti_framework_label
APP_KUBERNETES_IO_CREATED_BY = "app.kubernetes.io/created-by"
APP_KUBERNETES_IO_NAME = "app.kubernetes.io/name"
KAGENTI_UI_CREATOR_LABEL = "kagenti-ui"
KAGENTI_OPERATOR_LABEL_NAME = "kagenti-operator"

# Resource types
RESOURCE_TYPE_AGENT = "agent"
RESOURCE_TYPE_TOOL = "tool"

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

# Default resource limits
DEFAULT_RESOURCE_LIMITS = {"cpu": "500m", "memory": "1Gi"}
DEFAULT_RESOURCE_REQUESTS = {"cpu": "100m", "memory": "256Mi"}

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
