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

from typing import List

import typer
from rich.panel import Panel
from rich.text import Text

from . import checker, cluster, config
from .components import (
    addons,
    agents,
    gateway,
    istio,
    spire,
    mcp_gateway,
    keycloak,
    operator,
    registry,
    tekton,
    ui,
    metrics_server,
    inspector,
    cert_manager
)
from .config import InstallableComponent
from .utils import console

app = typer.Typer(
    help="A CLI tool to install the Agent Platform on a Kubernetes cluster (Kind or existing).",
    add_completion=False,
)

INSTALLERS = {
    InstallableComponent.REGISTRY: registry.install,
    InstallableComponent.TEKTON: tekton.install,
    InstallableComponent.CERT_MANAGER: cert_manager.install, 
    InstallableComponent.OPERATOR: operator.install,
    InstallableComponent.ISTIO: istio.install,
    InstallableComponent.SPIRE: spire.install,
    InstallableComponent.MCP_GATEWAY: mcp_gateway.install,
    InstallableComponent.ADDONS: addons.install,
    InstallableComponent.UI: ui.install,
    InstallableComponent.GATEWAY: gateway.install,
    InstallableComponent.KEYCLOAK: keycloak.install,
    InstallableComponent.AGENTS: agents.install,
    InstallableComponent.METRICS_SERVER: metrics_server.install,
    InstallableComponent.INSPECTOR: inspector.install,  
}


def deploy_component(
    component: InstallableComponent, skip_list: list[InstallableComponent]
):
    """Generic function to deploy a component or skip it based on user input."""
    if component in skip_list:
        console.print(
            f"[yellow]Skipping {component.value} installation as requested.[/yellow]\n"
        )
        return

    console.print(
        Panel(
            f"Installing {component.value.capitalize()}",
            style="bold cyan",
            expand=False,
        )
    )
    # Retrieve and run the correct installer function
    installer_func = INSTALLERS.get(component)
    if installer_func:
        installer_func()
    else:
        console.log(
            f"[bold red]Error: No installer found for component {component.value}[/bold red]"
        )
    console.print()


@app.command()
def main(
    skip_install: List[InstallableComponent] = typer.Option(
        [],
        "--skip-install",
        help="Name of a component to skip. Use the flag multiple times for multiple components.",
        case_sensitive=False,
    ),
    preload_images: bool = typer.Option(
        False,
        "--preload-images",
        help="Flag to enable preloading of images in kind.",
    ),
    use_existing_cluster: bool = typer.Option(
        False,
        "--use-existing-cluster",
        help="Use existing Kubernetes cluster defined in KUBECONFIG instead of creating a kind cluster.",
    ),
):
    """
    Installer for the Agent Platform. Checks dependencies and sets up a Kubernetes cluster (either Kind or existing) with optional components.
    """
    try:
        console.print(
            Panel(
                Text("Agent Platform Installer", justify="center", style="bold blue"),
                expand=False,
            )
        )

        # --- Setup and Pre-flight Checks ---
        checker.check_dependencies(use_existing_cluster=use_existing_cluster)
        checker.check_env_vars()

        should_install_registry = InstallableComponent.REGISTRY not in skip_install
        cluster.setup_cluster(install_registry=should_install_registry, use_existing_cluster=use_existing_cluster)

        if preload_images and not use_existing_cluster:
            cluster.preload_images_in_kind(config.PRELOADABLE_IMAGES)
        elif preload_images and use_existing_cluster:
            console.print("[yellow]Warning: --preload-images flag is only supported with kind clusters. Skipping image preloading.[/yellow]\n")

        if InstallableComponent.AGENTS not in skip_install:
            cluster.check_and_create_agent_namespaces()
        else:
            console.print(
                "[yellow]Skipping Agent Namespace check/creation as requested.[/yellow]\n"
            )

        # --- Component Installation ---
        console.print(
            Panel(
                Text("5. Installing Components", justify="center", style="bold yellow")
            )
        )

        deploy_component(InstallableComponent.REGISTRY, skip_install)
        deploy_component(InstallableComponent.TEKTON, skip_install)
        deploy_component(InstallableComponent.CERT_MANAGER, skip_install)          
        deploy_component(InstallableComponent.OPERATOR, skip_install)
        deploy_component(InstallableComponent.ISTIO, skip_install)
        deploy_component(InstallableComponent.METRICS_SERVER, skip_install)        
            

        # Components that depend on Istio
        if InstallableComponent.ISTIO not in skip_install:
            deploy_component(InstallableComponent.GATEWAY, skip_install)
            deploy_component(InstallableComponent.ADDONS, skip_install)
            deploy_component(InstallableComponent.KEYCLOAK, skip_install)
            deploy_component(InstallableComponent.SPIRE, skip_install)
            deploy_component(InstallableComponent.MCP_GATEWAY, skip_install)
            deploy_component(InstallableComponent.AGENTS, skip_install)
            deploy_component(InstallableComponent.UI, skip_install)
            deploy_component(InstallableComponent.INSPECTOR, skip_install)
        else:
            console.print(
                "[yellow]Skipping components because Istio installation was skipped.[/yellow]"
            )

        console.print(
            "\n",
            Panel(Text("Installation Complete!", justify="center", style="bold green")),
            "\n",
        )

        if use_existing_cluster:
            console.print(
                "To open Kagenti UI in your browser, you may need to set up port forwarding or ingress depending on your cluster configuration.",
                "\n",
            )
        else:
            console.print(
                "To open Kagenti UI in your browser: open http://kagenti-ui.localtest.me:8080",
                "\n",
            )

    except typer.Exit:
        console.print("\n[bold yellow]Installation aborted.[/bold yellow]")
    except Exception as e:
        console.print(f"\n[bold red]An unexpected error occurred: {e}[/bold red]")
        raise
