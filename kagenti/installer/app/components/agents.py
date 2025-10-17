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

import base64
import json
import os
import platform
import typer
from kubernetes import client, config as kube_config

from .. import config
from ..utils import console, run_command, create_or_update_secret


def install(**kwargs):
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
    admin_slack_bot_token = os.getenv("ADMIN_SLACK_BOT_TOKEN")

    for ns in agent_namespaces:
        console.print(f"\n[cyan]Configuring namespace: {ns}[/cyan]")

        github_token_secret = client.V1Secret(
            api_version="v1",
            kind="Secret",
            metadata=client.V1ObjectMeta(name="github-token-secret", namespace=ns),
            string_data={
                "user": github_user,
                "token": github_token,
            },
            type="Opaque",
        )
        create_or_update_secret(
            v1_api=v1_api, namespace=ns, secret_body=github_token_secret
        )

        # The docker-registry secret is used to pull images from private repos
        github_auth = f"{github_user}:{github_token}"
        docker_config = {
            "auths": {
                "ghcr.io": {
                    "username": github_user,
                    "password": github_token,
                    "auth": base64.b64encode(github_auth.encode("utf-8")).decode(
                        "utf-8"
                    ),
                }
            }
        }
        ghcr_secret = client.V1Secret(
            api_version="v1",
            kind="Secret",
            metadata=client.V1ObjectMeta(name="ghcr-secret", namespace=ns),
            data={
                ".dockerconfigjson": base64.b64encode(
                    json.dumps(docker_config).encode("utf-8")
                ).decode("utf-8")
            },
            type="kubernetes.io/dockerconfigjson",
        )
        create_or_update_secret(v1_api=v1_api, namespace=ns, secret_body=ghcr_secret)

        openai_secret = client.V1Secret(
            api_version="v1",
            kind="Secret",
            metadata=client.V1ObjectMeta(name="openai-secret", namespace=ns),
            string_data={
                "apikey": openai_api_key,
            },
            type="Opaque",
        )
        create_or_update_secret(v1_api=v1_api, namespace=ns, secret_body=openai_secret)

        slack_secret = client.V1Secret(
            api_version="v1",
            kind="Secret",
            metadata=client.V1ObjectMeta(name="slack-secret", namespace=ns),
            string_data={
                "bot-token": slack_bot_token,
                "admin-bot-token": admin_slack_bot_token,
            },
            type="Opaque",
        )
        create_or_update_secret(v1_api=v1_api, namespace=ns, secret_body=slack_secret)

        # if user operating system is linux, do some special config to enable ollama
        if platform.system() == "Linux":
            run_command(
                ["sh", "app/linux/ollama-config.sh"],
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
            [
                "kubectl",
                "apply",
                "-n",
                ns,
                "-f",
                str(config.RESOURCES_DIR / "spiffe-helper-config.yaml"),
            ],
            f"Applying spiffe-helper-config configmap in '{ns}'",
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
