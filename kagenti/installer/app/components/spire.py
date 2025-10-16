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
    """Installs all SPIRE components using the official Helm charts."""
    # This command sets up SPIRE CRDs
    run_command(
        [
            "helm",
            "upgrade",
            "--install",
            "spire-crds",
            "spire-crds",
            "-n",
            "spire-mgmt",
            "--repo",
            "https://spiffe.github.io/helm-charts-hardened/",
            "--create-namespace",
            "--wait",
        ],
        "Installing SPIRE CRDs",
    )
    # run_command(
    #     [
    #         "pwd",
    #     ],
    #     "Print working directory",
    # )
    # Install SPIRE using provided helm configuration
    run_command(
        [
            "helm",
            "upgrade",
            "--install",
            "spire",
            "spire",
            "-n",
            "spire-mgmt",
            "--repo",
            "https://spiffe.github.io/helm-charts-hardened/",
            "-f",
            str(config.RESOURCES_DIR / "spire-helm-values.yaml"),
            "--wait",
        ],
        "Installing SPIRE Server",
    )
    # Setup OIDC route
    run_command(
        ["kubectl", "apply", "-f", str(config.RESOURCES_DIR / "spire-oidc-route.yaml")],
        "Applying Spire OIDC route",
    )
    # Setup Tornjak backend route
    run_command(
        [
            "kubectl",
            "apply",
            "-f",
            str(config.RESOURCES_DIR / "spire-tornjak-api-route.yaml"),
        ],
        "Applying Spire Tornjak api route",
    )
    # Setup Tornjak frontend route
    run_command(
        [
            "kubectl",
            "apply",
            "-f",
            str(config.RESOURCES_DIR / "spire-tornjak-ui-route.yaml"),
        ],
        "Applying Spire Tornjak UI route",
    )
    # Add SPIRE namespace to shared gateway access
    run_command(
        [
            "kubectl",
            "label",
            "ns",
            "spire-server",
            "shared-gateway-access=true",
            "--overwrite",
        ],
        "Sharing gateway access for Spire",
    )
    # Add SPIRE namespace to Istio ambient mesh
    run_command(
        [
            "kubectl",
            "label",
            "namespace",
            "spire-server",
            "istio.io/dataplane-mode=ambient",
            "--overwrite",
        ],
        "Adding Spire to Istio ambient mesh",
    )
