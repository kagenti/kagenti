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

from .. import config
from ..utils import run_command


def install(**kwargs):
    """Install K8s Gateway CRDs."""
    # This command installs K8s Gateway CRDs
    run_command(
        [
            "kubectl",
            "apply",
            "-k",
            "https://github.com/kubernetes-sigs/gateway-api/config/crd?ref=v1.3.0",
        ],
        "Installing K8s Gateway CRDs",
    )

    """Create MCPGateway namespaces."""
    # This command creates namespaces for MCP gateway components
    run_command(
        [
            "kubectl",
            "apply",
            "-f",
            str(config.RESOURCES_DIR / "gateway-namespaces.yaml"),
        ],
        "Creating MCPGateway namespaces",
    )

    """Create Gateway listeners."""
    # This command installs listeners on the Gateway
    run_command(
        ["kubectl", "apply", "-f", str(config.RESOURCES_DIR / "gateway.yaml")],
        "Creating Gateway listeners",
    )

    """Enable ext-proc filter on the Gateway."""
    # This command enables ext-proc based filter on the Gateway
    run_command(
        ["kubectl", "apply", "-f", str(config.RESOURCES_DIR / "envoyfilter.yaml")],
        "Enabling ext-proc filter on the Gateway",
    )

    """Install MCPGateway CRDs."""
    # This command installs MCPGateway CRDs
    run_command(
        ["kubectl", "apply", "-f", str(config.RESOURCES_DIR / "gateway-crd.yaml")],
        "Installing MCPGateway CRDs",
    )

    """Deploy MCPGateway Broker, Router, and Controller."""
    # This command installs MCPGateway components
    run_command(
        [
            "kubectl",
            "apply",
            "-f",
            str(config.RESOURCES_DIR / "gateway-deployment.yaml"),
        ],
        "Deploying MCPGateway Broker, Router, and Controller",
    )

    # """Init MCPServer CR."""
    # This command creates an empty MCPServer resource
    # run_command(
    #    ["kubectl", "apply", "-f", str(config.RESOURCES_DIR / "gateway-mcpserver.yaml")],
    #    "Initing MCPServer CR",
    # )
