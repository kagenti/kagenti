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

import os
import platform
import subprocess
import typer
from kubernetes import client, config as kube_config

from .. import config
from ..utils import console, run_command, secret_exists


def install():
    """Applies required secrets and labels to the agent namespaces defined in .env."""
    namespaces_str = os.getenv("AGENT_NAMESPACES")
    if not namespaces_str:
        console.log(
            "[yellow]AGENT_NAMESPACES not set. Skipping agent namespace configuration.[/yellow]"
        )
        return

    agent_namespaces = [ns.strip() for ns in namespaces_str.split(",") if ns.strip()]

    try:
        kube_config.load_kube_config()
        v1_api = client.CoreV1Api()
    except Exception as e:
        console.log(f"[bold red]✗ Could not connect to Kubernetes: {e}[/bold red]")
        raise typer.Exit(1)

    github_user = os.getenv("GITHUB_USER")
    github_token = os.getenv("GITHUB_TOKEN")
    openai_api_key = os.getenv("OPENAI_API_KEY")
    slack_bot_token = os.getenv("SLACK_BOT_TOKEN")

    for ns in agent_namespaces:
        console.print(f"\n[cyan]Configuring namespace: {ns}[/cyan]")

        if not secret_exists(v1_api, "github-token-secret", ns):
            run_command(
                [
                    "kubectl",
                    "create",
                    "secret",
                    "generic",
                    "github-token-secret",
                    f"--from-literal=user={github_user}",
                    f"--from-literal=token={github_token}",
                    "-n",
                    ns,
                ],
                f"Creating 'github-token-secret' in '{ns}'",
            )
        # Create docker-registry secret so that we can pull images from private repos
        if not secret_exists(v1_api, "ghcr-secret", ns):
            run_command(
                [
                    "kubectl",
                    "create",
                    "secret",
                    "docker-registry",
                    "ghcr-secret",
                    "--docker-server=ghcr.io",
                    f"--docker-username={github_user}",
                    f"--docker-password={github_token}",
                    "-n",
                    ns,
                ],
                f"Creating 'ghcr-secret' in '{ns}'",
            )

        if not secret_exists(v1_api, "openai-secret", ns):
            run_command(
                [
                    "kubectl",
                    "create",
                    "secret",
                    "generic",
                    "openai-secret",
                    f"--from-literal=apikey={openai_api_key}",
                    "-n",
                    ns,
                ],
                f"Creating 'openai-secret' in '{ns}'",
            )
        if not secret_exists(v1_api, "slack-secret", ns):
            run_command(
                [
                    "kubectl",
                    "create",
                    "secret",
                    "generic",
                    "slack-secret",
                    f"--from-literal=bot-token={slack_bot_token}",
                    "-n",
                    ns,
                ],
                f"Creating 'slack-secret' in '{ns}'",
            )
        # if user operating system is linux, do some special config to enable ollama
        if platform.system() == "Linux":
            run_command(
                [
                    "sh",
                    "app/linux/ollama-config.sh"
                ],
                "Customizing ollama environment for Linux",
            )

        run_command(
            [
                "kubectl",
                "apply",
                "-n",
                ns,
                "-f",
                str(config.RESOURCES_DIR / "environments.yaml"),
            ],
            f"Applying environments configmap in '{ns}'",
        )
        run_command(
            ["kubectl", "label", "ns", ns, "shared-gateway-access=true", "--overwrite"],
            f"Applying shared-gateway-access label to '{ns}'",
        )
        run_command(
            [
                "kubectl",
                "label",
                "ns",
                ns,
                "istio.io/use-waypoint=waypoint",
                "--overwrite",
            ],
            f"Applying use-waypoint label to '{ns}'",
        )
        run_command(
            [
                "kubectl",
                "label",
                "ns",
                ns,
                "istio.io/dataplane-mode=ambient",
                "--overwrite",
            ],
            f"Applying dataplane-mode label to '{ns}'",
        )
