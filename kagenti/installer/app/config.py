# Assisted by watsonx Code Assistant
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

from enum import Enum
from pathlib import Path

# --- Core Paths ---
SCRIPT_DIR = Path(__file__).parent.resolve()
PROJECT_ROOT = SCRIPT_DIR.parent.parent.parent  # Adjust if directory structure changes
ENV_FILE = SCRIPT_DIR / ".env"
RESOURCES_DIR = SCRIPT_DIR / "resources"

# --- Cluster & Operator Configuration ---
CLUSTER_NAME = "agent-platform"
OPERATOR_NAMESPACE = "kagenti-system"
TEKTON_VERSION = "v0.66.0"
KEYCLOAK_URL = "http://keycloak.localtest.me:8080/realms/master"

# --- Container Engine Options ---
class ContainerEngine(str, Enum):
    PODMAN = "podman"
    DOCKER = "docker"

CONTAINER_ENGINE =  "docker"

# --- Dependency Version Requirements ---
# Defines the minimum (inclusive) and maximum (exclusive) required versions for tools.
REQ_VERSIONS = {
    "kind": {"min": "0.20.0", "max": "0.99.0"},
    "docker": {"min": "5.0.0", "max": "29.0.0"},
    "podman": {"min":"5.0.0", "max":"5.6.0"},
    "kubectl": {"min": "1.29.0", "max": "1.35.0"},
    "helm": {"min": "3.14.0", "max": "3.19.0"},
    "git": {"min": "2.30.0", "max": "3.0.0"},
}

# --- Images to preload in the kind cluster ---
PRELOADABLE_IMAGES = [
    "docker.io/istio/proxyv2:1.26.1-distroless",
    "docker.io/istio/install-cni:1.26.1-distroless",
    "docker.io/istio/pilot:1.26.1-distroless",
    "docker.io/istio/ztunnel:1.26.1",
    "otel/opentelemetry-collector-contrib:0.122.1",
    "arizephoenix/phoenix:version-8.32.1",
    "postgres:12",
    "prom/prometheus:v3.1.0",
    "registry.k8s.io/metrics-server/metrics-server:v0.7.2",
    "ghcr.io/spiffe/oidc-discovery-provider:1.12.4",
    "docker.io/nginxinc/nginx-unprivileged:1.29.0-alpine",
    "docker.io/nginx/nginx-prometheus-exporter:1.4.2",
    "ghcr.io/kagenti/mcp-gateway:v0.1",
    "ghcr.io/modelcontextprotocol/inspector:0.15.0"
]

# --- Git Repos and fallback tag versions ---
OPERATOR_FALLBACK_VERSION = "0.2.0-alpha.4"
OPERATOR_GIT_REPO = "https://github.com/kagenti/kagenti-operator.git"
UI_FALLBACK_VERSION = "v0.0.4-alpha.13"
UI_GIT_REPO = "https://github.com/kagenti/kagenti.git"

# --- Enum for Skippable Components ---
class InstallableComponent(str, Enum):
    """Enumeration of all components that can be installed or skipped."""

    REGISTRY = "registry"
    TEKTON = "tekton"
    OPERATOR = "operator"
    ISTIO = "istio"
    ADDONS = "addons"  #  Kiali & Phoenix
    OTEL = "otel"
    UI = "ui"
    GATEWAY = "gateway"
    SPIRE = "spire"
    MCP_GATEWAY = "mcp_gateway"
    KEYCLOAK = "keycloak"
    AGENT_NAMESPACES = "agent_namespaces"
    METRICS_SERVER= "metrics_server"
    INSPECTOR = "inspector"
    CERT_MANAGER = "cert_manager"
