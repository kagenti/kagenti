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

import typer

from .. import config
from ..utils import console, run_command


def install(**kwargs):
    """Installs the MCP inspector"""
    deploy_path = str(config.RESOURCES_DIR / "mcp-inspector.yaml")
    run_command(
        ["kubectl", "apply", "-f", str(deploy_path)], "Installing MCP Inspector"
    )
    run_command(
        [
            "kubectl",
            "label",
            "ns",
            "kagenti-system",
            "shared-gateway-access=true",
            "--overwrite",
        ],
        "Sharing gateway access for inspector",
    )
    run_command(
        [
            "kubectl",
            "rollout",
            "status",
            "-n",
            "kagenti-system",
            "deployment/mcp-inspector",
        ],
        "Waiting for mcp-inspector rollout",
    )
