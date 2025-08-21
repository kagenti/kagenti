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
import shutil
import subprocess

import typer
from kubernetes import client, config as kube_config
from rich.prompt import Confirm
from rich.panel import Panel
from rich.text import Text

from . import config
from .utils import console, run_command


def kind_cluster_exists():
    """Checks if the Kind cluster exists."""
    try:
        result = subprocess.run(
            ["kind", "get", "clusters"],
            capture_output=True,
            text=True,
            check=True,
        )
        return config.CLUSTER_NAME in result.stdout.split()
    except subprocess.CalledProcessError as e:
        console.log(f"[bold red]✗ Failed to run kind command.[/bold red]")
        console.log(f"[red]{e.stderr.strip()}[/red]")
        raise typer.Exit(1)


def kind_cluster_running():
    """Checks if the Kind cluster is already running."""
    try:
        result = subprocess.run(
            ["docker", "ps", "--format", "{{.Names}}"],
            capture_output=True,
            text=True,
            check=True,
        )
        return f"{config.CLUSTER_NAME}-control-plane" in result.stdout.split()
    except subprocess.CalledProcessError as e:
        console.log(f"[bold red]✗ Failed to run docker ps.[/bold red]")
        console.log(f"[red]{e.stderr.strip()}[/red]")
        raise typer.Exit(1)


def check_kube_connection(install_registry: bool, use_existing_cluster: bool):
    """Sets up the Kubernetes cluster - either creates a kind cluster or uses existing cluster."""
    if use_existing_cluster:
        console.print(
            Panel(
                Text("3. Using Kubernetes Cluster", justify="center", style="bold yellow")
            )
        )
        try:
            kube_config.load_kube_config()
            v1_api = client.CoreV1Api()
            # Test connection by getting cluster info
            v1_api.list_namespace(limit=1)
            console.log(
                "[bold green]✓[/bold green] Successfully connected the Kubernetes cluster."
            )
        except Exception as e:
            console.log(
                f"[bold red]✗ Failed to connect to existing Kubernetes cluster: {e}[/bold red]"
            )
            console.print(
                "[red]Please ensure KUBECONFIG is set and points to a valid cluster.[/red]"
            )
            raise typer.Exit(1)

        console.print()


def create_kind_cluster(install_registry: bool):
    """Creates a Kind cluster if it doesn't already exist."""
    console.print(
        Panel(
            Text("3. Kubernetes Cluster Setup", justify="center", style="bold yellow")
        )
    )
    if kind_cluster_exists():
        if kind_cluster_running():
            console.log(
                f"[bold green]✓[/bold green] Kind cluster '{config.CLUSTER_NAME}' already running. Skipping creation."
            )
            return
        else:
            console.log(
                f"[bold red]x Kind cluster '{config.CLUSTER_NAME}' exists but is not running."
            )
            console.print("[bold red]Cannot proceed. Exiting.[/bold red]")
            raise typer.Exit(1)

    if not Confirm.ask(
        f"[bold yellow]?[/bold yellow] Kind cluster '{config.CLUSTER_NAME}' not found. Create it now?",
        default=True,
    ):
        # Ask if they want to use an existing cluster instead
        if Confirm.ask(
            "[bold yellow]?[/bold yellow] Would you like to use an existing Kubernetes cluster defined in your KUBECONFIG?",
            default=True,
        ):
            console.print(
                "[bold green]Switching to existing cluster mode...[/bold green]"
            )
            # Test connection to existing cluster
            try:
                kube_config.load_kube_config()
                v1_api = client.CoreV1Api()
                # Test connection by getting cluster info
                v1_api.list_namespace(limit=1)
                console.log(
                    "[bold green]✓[/bold green] Successfully connected to existing Kubernetes cluster."
                )

                if install_registry:
                    console.print(
                        "[yellow]Warning: Registry installation is not recommended for existing clusters. "
                        "Consider using --skip-install registry if you encounter issues.[/yellow]\n"
                    )
                console.print()
                return  # Exit without creating kind cluster

            except Exception as e:
                console.log(
                    f"[bold red]✗ Failed to connect to existing Kubernetes cluster: {e}[/bold red]"
                )
                console.print(
                    "[red]Please ensure KUBECONFIG is set and points to a valid cluster.[/red]"
                )
                raise typer.Exit(1)
        else:
            console.print("[bold red]Cannot proceed without a cluster. Exiting.[/bold red]")
            raise typer.Exit()

    base_config = """
kind: Cluster
apiVersion: kind.x-k8s.io/v1alpha4
nodes:
- role: control-plane
  extraPortMappings:
  - containerPort: 30080
    hostPort: 8080
  - containerPort: 30443
    hostPort: 9443
"""
    registry_patch = """
containerdConfigPatches:
- |
  [plugins."io.containerd.grpc.v1.cri".registry]
    [plugins."io.containerd.grpc.v1.cri".registry.mirrors."registry.cr-system.svc.cluster.local:5000"]
      endpoint = ["http://registry.cr-system.svc.cluster.local:5000"]
    [plugins."io.containerd.grpc.v1.cri".registry.configs."registry.cr-system.svc.cluster.local:5000".tls]
      insecure_skip_verify = true
"""
    final_config = base_config + (registry_patch if install_registry else "")

    with console.status(f"[cyan]Creating Kind cluster '{config.CLUSTER_NAME}'..."):
        try:
            kind_executable = shutil.which("kind")
            subprocess.run(
                [
                    kind_executable,
                    "create",
                    "cluster",
                    "--name",
                    config.CLUSTER_NAME,
                    "--config=-",
                ],
                input=final_config,
                text=True,
                check=True,
                capture_output=True,
            )
            console.log(
                f"[bold green]✓[/bold green] Kind cluster '{config.CLUSTER_NAME}' created."
            )
        except subprocess.CalledProcessError as e:
            console.log(f"[bold red]✗ Failed to create Kind cluster.[/bold red]")
            console.log(f"[red]{e.stderr.strip()}[/red]")
            raise typer.Exit(1)
    console.print()


def preload_images_in_kind(images: list[str]):
    """Pulls and preloads a list of Docker images into the Kind cluster."""
    console.print(
        Panel(
            Text("Preloading Images into Kind", justify="center", style="bold yellow")
        )
    )
    for image in images:
        run_command(["docker", "pull", image], f"Pulling image {image}")
        run_command(
            ["kind", "load", "docker-image", image, "--name", config.CLUSTER_NAME],
            f"Loading image {image} into kind",
        )
    console.print()


def check_and_create_agent_namespaces():
    """Checks for agent namespaces and creates them if they are missing."""
    console.print(
        Panel(
            Text("4. Checking Agent Namespaces", justify="center", style="bold yellow")
        )
    )
    namespaces_str = os.getenv("AGENT_NAMESPACES", "")
    if not namespaces_str:
        console.log(
            "[yellow]AGENT_NAMESPACES not set. Skipping agent namespace check.[/yellow]"
        )
        return

    agent_namespaces = [ns.strip() for ns in namespaces_str.split(",") if ns.strip()]

    try:
        kube_config.load_kube_config()
        v1_api = client.CoreV1Api()
    except Exception as e:
        console.log(
            f"[bold red]✗ Could not connect to Kubernetes to check namespaces: {e}[/bold red]"
        )
        raise typer.Exit(1)

    existing_namespaces = {ns.metadata.name for ns in v1_api.list_namespace().items}
    missing_namespaces = [
        ns for ns in agent_namespaces if ns not in existing_namespaces
    ]

    if missing_namespaces:
        console.print(
            f"The following required agent namespaces do not exist: [bold yellow]{', '.join(missing_namespaces)}[/bold yellow]"
        )
        if Confirm.ask("Do you want to create them now?", default=True):
            for ns in missing_namespaces:
                run_command(
                    ["kubectl", "create", "namespace", ns], f"Creating namespace '{ns}'"
                )
        else:
            console.print(
                "[bold red]Cannot proceed without agent namespaces. Exiting.[/bold red]"
            )
            raise typer.Exit(1)
    else:
        console.log(
            "[bold green]✓ All required agent namespaces already exist.[/bold green]"
        )
    console.print()
