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

import subprocess

from kubernetes import client, config as kube_config
import typer

from .. import config
from ..config import ContainerEngine
from ..utils import console, run_command


def install(**kwargs):
    """Deploys the internal container registry and configures its DNS."""
    run_command(
        ["kubectl", "apply", "-f", str(config.RESOURCES_DIR / "registry.yaml")],
        "Deploying container registry manifest",
    )
    run_command(
        ["kubectl", "-n", "cr-system", "rollout", "status", "deployment/registry"],
        "Waiting for registry deployment",
    )

    with console.status("[cyan]Configuring registry DNS..."):
        try:
            kube_config.load_kube_config()
            core_v1 = client.CoreV1Api()
            service = core_v1.read_namespaced_service(
                name="registry", namespace="cr-system"
            )
            registry_ip = service.spec.cluster_ip

            container = f"{config.CLUSTER_NAME}-control-plane"
            container_engine = ContainerEngine(config.CONTAINER_ENGINE)

            subprocess.run(
                [
                    container_engine.value,
                    "exec",
                    container,
                    "sh",
                    "-c",
                    f"echo {registry_ip} registry.cr-system.svc.cluster.local >> /etc/hosts",
                ]
            )

            console.log(
                "[bold green]✓[/bold green] Registry DNS configured in Kind container."
            )
        except ValueError as e:
            console.log(
                f"[bold red]✗ Container engine must be either 'docker' or 'podman'[/bold red]"
            )
            raise typer.Exit(1)

        except Exception as e:
            console.log(f"[bold red]✗[/bold red] Failed to configure registry DNS: {e}")
            raise typer.Exit(1)
