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
from ..utils import run_command, console


def install(**kwargs):
    """
    Installs identity provider infrastructure.

    For SPIRE provider: Installs SPIRE components using the official Helm charts.
    For ServiceAccount provider: No additional infrastructure needed (uses K8s native).
    """
    if not config.IDENTITY_PROVIDER:
        raise ValueError(
            "IDENTITY_PROVIDER must be set to 'spire' or 'serviceaccount'. "
            "Set KAGENTI_IDENTITY_PROVIDER environment variable."
        )

    identity_provider = config.IDENTITY_PROVIDER.lower().strip()

    if identity_provider == "serviceaccount":
        console.log(
            "[yellow]Using ServiceAccount identity provider (no additional infrastructure needed)[/yellow]"
        )
        return

    if identity_provider != "spire":
        raise ValueError(
            f"Invalid identity provider: '{identity_provider}'. "
            "Must be 'spire' or 'serviceaccount'."
        )

    # Install SPIRE for "spire" provider
    console.log(
        f"[cyan]Installing SPIRE infrastructure for identity provider: {identity_provider}[/cyan]"
    )

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
