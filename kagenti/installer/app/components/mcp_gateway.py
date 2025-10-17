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

    """Install MCP Gateway Helm chart"""
    # This command installs MCP Gateway
    run_command(
        [
            "helm",
            "upgrade",
            "--install",
            "mcp-gateway",
            "oci://ghcr.io/kagenti/charts/mcp-gateway",
            "--version",
            "0.2.0",
        ],
        "Installing MCP Gateway",
    )

    """Add Kuadrant Helm repo"""
    # This command adds Kuadrant helm chart
    run_command(
        [
            "helm",
            "repo",
            "add",
            "kuadrant",
            "https://kuadrant.io/helm-charts",
        ],
        "Adding Kuadrant Helm repo",
    )

    """Update Kuadrant Helm repo"""
    # This command updates Kuadrant chart
    run_command(
        [
            "helm",
            "repo",
            "update",
        ],
        "Updating Kuadrant Helm chart",
    )
    
    """Install Kuadrant Operator"""
    # This command installs Kuadrant operator
    run_command(
        [
            "helm",
            "upgrade",
            "--install",
            "kuadrant-operator",
            "kuadrant/kuadrant-operator",
            "--create-namespace",
            "--wait",
            "--timeout=600s",
            "--namespace",
            "kuadrant-system",
        ],
        "Installing Kuadrant operator",
    )

    """Installs Kudrant"""
    # This command installs Kuadrant
    run_command(
        ["kubectl", "apply", "-f", str(config.RESOURCES_DIR / "kuadrant.yaml")],
        "Installing Kuadrant",
    )
