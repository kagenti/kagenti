# Copyright 2025 IBM Corp.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
Useful constants.
"""

# --- Kubernetes CRD Definitions ---
CRD_GROUP = "kagenti.operator.dev"
CRD_VERSION = "v1alpha1"
TOOLHIVE_CRD_GROUP = "toolhive.stacklok.dev"
TOOLHIVE_CRD_VERSION = "v1alpha1"
AGENTS_PLURAL = "agents"
TOOLHIVE_MCP_PLURAL = "mcpservers"
COMPONENTS_PLURAL = "components"
OPERATOR_NS = "kagenti-system"

# --- Kubernetes Labels and Selectors ---
KAGENTI_LABEL_PREFIX = "kagenti.io/"
KAGENTI_TYPE_LABEL = f"{KAGENTI_LABEL_PREFIX}type"
KAGENTI_PROTOCOL_LABEL = f"{KAGENTI_LABEL_PREFIX}protocol"
KAGENTI_FRAMEWORK_LABEL = f"{KAGENTI_LABEL_PREFIX}framework"
APP_KUBERNETES_IO_CREATED_BY = "app.kubernetes.io/created-by"
APP_KUBERNETES_IO_NAME = "app.kubernetes.io/name"

RESOURCE_TYPE_AGENT = "agent"
RESOURCE_TYPE_TOOL = "tool"

ENABLED_NAMESPACE_LABEL_KEY = "kagenti-enabled"
ENABLED_NAMESPACE_LABEL_VALUE = "true"

# --- External Service URLs ---
KEYCLOAK_CONSOLE_URL_OFF_CLUSTER = (
    "http://keycloak.localtest.me:8080/admin/master/console/"
)
KEYCLOAK_CONSOLE_URL_IN_CLUSTER = (
    "http://keycloak.keycloak.svc.cluster.local:8080/admin/master/console/"
)
TRACES_DASHBOARD_URL = "http://phoenix.localtest.me:8080"
NETWORK_TRAFFIC_DASHBOARD_URL = "http://kiali.localtest.me:8080"
MCP_INSPECTOR_URL = "http://mcp-inspector.localtest.me:8080"
MCP_PROXY_FULL_ADDRESS = "http://mcp-proxy.localtest.me:8080"

# --- Default Values for Import Forms ---
DEFAULT_REPO_URL = "https://github.com/kagenti/agent-examples"
DEFAULT_REPO_BRANCH = "main"
DEFAULT_IMAGE_TAG = "v0.0.1"
DEFAULT_IMAGE_POLICY = "Always"

# --- Kubernetes Secret for Git User ---
GIT_USER_SECRET_NAME = "github-token-secret"
GIT_USER_SECRET_KEY = "user"

# --- Agent/Tool Default Environment Variables ---
ENV_CONFIG_MAP_NAME = "environments"

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


# --- Resource Limits and Requests ---
DEFAULT_RESOURCE_LIMITS = {"cpu": "500m", "memory": "1Gi"}
DEFAULT_RESOURCE_REQUESTS = {"cpu": "100m", "memory": "256Mi"}

# --- A2A Constants ---
A2A_PUBLIC_AGENT_CARD_PATH = "/.well-known/agent.json"
A2A_EXTENDED_AGENT_CARD_PATH = "/agent/authenticatedExtendedCard"
A2A_DUMMY_AUTH_TOKEN = "Bearer dummy-token-for-extended-card"

# --- UI ---
STREAMLIT_UI_CREATOR_LABEL = "streamlit-ui"
KAGENTI_OPERATOR_LABEL_NAME = "kagenti-operator"
TOOLHIVE_OPERATOR_LABEL_NAME = "toolhive-operator"
POLL_INTERVAL_SECONDS = 2
AGENT_NAME_SEPARATOR = "-"
ENABLE_AUTH_STRING = "enable_auth"
TOKEN_STRING = "token"
ACCESS_TOKEN_STRING = "access_token"

# --- Default Ports for Agent/Tool Services ---
DEFAULT_IN_CLUSTER_PORT = 8000
DEFAULT_OFF_CLUSTER_PORT = 8080

# --- MCP Tool Constants ---
DEFAULT_MCP_PORT = DEFAULT_IN_CLUSTER_PORT
DEFAULT_MCP_OFF_CLUSTER_PORT = DEFAULT_OFF_CLUSTER_PORT
DEFAULT_MCP_SSE_PATH = "/sse"
DEFAULT_MCP_STREAMABLE_HTTP_PATH = "/mcp"
MCP_GATEWAY_IN_CLUSTER_URL = (
    "http://mcp-gateway-istio.gateway-system.svc.cluster.local:8080/mcp"
)
