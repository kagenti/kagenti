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

import sys
from dataclasses import dataclass
from typing import List, Set

import typer
from rich.panel import Panel
from rich.text import Text

from . import checker, cluster, config
from .components import (
    addons,
    agent_namespaces,
    gateway,
    istio,
    spire,
    mcp_gateway,
    otel,
    keycloak,
    operator,
    registry,
    tekton,
    ui,
    metrics_server,
    inspector,
    cert_manager,
)
from .config import InstallableComponent
from .utils import console
from .cluster import is_openshift_cluster

app = typer.Typer(
    help="A CLI tool to install the Agent Platform on a Kubernetes cluster.",
    add_completion=False,
)

# A mapping from component enum to its installer function.
INSTALLER_MAP = {
    InstallableComponent.REGISTRY: registry.install,
    InstallableComponent.TEKTON: tekton.install,
    InstallableComponent.CERT_MANAGER: cert_manager.install,
    InstallableComponent.OPERATOR: operator.install,
    InstallableComponent.ISTIO: istio.install,
    InstallableComponent.SPIRE: spire.install,
    InstallableComponent.MCP_GATEWAY: mcp_gateway.install,
    InstallableComponent.OTEL: otel.install,
    InstallableComponent.ADDONS: addons.install,
    InstallableComponent.UI: ui.install,
    InstallableComponent.GATEWAY: gateway.install,
    InstallableComponent.KEYCLOAK: keycloak.install,
    InstallableComponent.AGENT_NAMESPACES: agent_namespaces.install,
    InstallableComponent.METRICS_SERVER: metrics_server.install,
    InstallableComponent.INSPECTOR: inspector.install,
}

# Define the installation order and dependencies explicitly.
CORE_COMPONENTS = [
    InstallableComponent.REGISTRY,
    InstallableComponent.METRICS_SERVER,
    InstallableComponent.TEKTON,
    InstallableComponent.CERT_MANAGER,
    InstallableComponent.OPERATOR,
    InstallableComponent.ISTIO,
    InstallableComponent.GATEWAY,
    InstallableComponent.MCP_GATEWAY,
    InstallableComponent.KEYCLOAK,
    InstallableComponent.AGENT_NAMESPACES,
    InstallableComponent.INSPECTOR,
    InstallableComponent.SPIRE,
    InstallableComponent.UI,
]

ISTIO_DEPENDENT_COMPONENTS = [
    InstallableComponent.ADDONS,
]


@dataclass
class ClusterContext:
    """Holds the configuration and state of the target cluster."""

    is_existing: bool = False
    is_openshift: bool = False
    is_kind: bool = False


def _deploy_component(
    component: InstallableComponent,
    skip_set: Set[InstallableComponent],
    install_params: dict,
):
    """Generic function to deploy a component or skip it."""
    if component in skip_set:
        console.print(
            f"[yellow]Skipping {component.value} installation as requested.[/yellow]\n"
        )
        return

    console.print(
        Panel(f"Installing {component.value.capitalize()}", style="bold cyan")
    )

    installer_func = INSTALLER_MAP.get(component)
    if installer_func:
        installer_func(**install_params)
    else:
        console.log(
            f"[bold red]Error: No installer found for {component.value}[/bold red]"
        )
    console.print()


def _print_header():
    """Prints the application header."""
    console.print(
        Panel(Text("Kagenti Agent Platform Installer", justify="center", style="bold blue"))
    )


def _determine_cluster_context(use_existing_cluster: bool) -> ClusterContext:
    """Determines the type of cluster we are working with."""
    is_openshift = is_openshift_cluster() if use_existing_cluster else False
    return ClusterContext(
        is_existing=use_existing_cluster,
        is_openshift=is_openshift,
        is_kind=not use_existing_cluster,
    )


def _handle_automatic_skips(
    context: ClusterContext, user_skip_list: List[InstallableComponent]
) -> Set[InstallableComponent]:
    """Determines which components to skip based on cluster type and user input."""
    skip_set = set(user_skip_list)

    # Rule: REGISTRY is not needed for any existing cluster.
    if context.is_existing:
        if InstallableComponent.REGISTRY not in skip_set:
            console.print(
                "[yellow]Info: Using an existing cluster, automatically skipping REGISTRY installation.[/yellow]\n"
            )
            skip_set.add(InstallableComponent.REGISTRY)

    if context.is_openshift:
         # Rule: METRICS_SERVER is not needed for OpenShift as it has a built-in equivalent.
        if InstallableComponent.METRICS_SERVER not in skip_set:
            console.print(
                "[yellow]Info: Using an OpenShift cluster, automatically skipping METRICS_SERVER installation.[/yellow]\n"
            )
            skip_set.add(InstallableComponent.METRICS_SERVER)

        # Rule: GATEWAY is not needed for OpenShift as it has a built-in equivalent.
        if InstallableComponent.GATEWAY not in skip_set:
            console.print(
                "[yellow]Info: Using an OpenShift cluster, automatically skipping ingress GATEWAY installation.[/yellow]\n"
            )
            skip_set.add(InstallableComponent.GATEWAY)        

    return skip_set


def _setup_cluster(
    context: ClusterContext,
    skip_set: Set[InstallableComponent],
    preload_images: bool,
    silent: bool,
):
    """Performs all pre-flight checks and cluster setup."""
    checker.check_dependencies(use_existing_cluster=context.is_existing)
    checker.check_env_vars()

    install_registry = False
    if context.is_kind:
        install_registry = InstallableComponent.REGISTRY not in skip_set
        cluster.create_kind_cluster(install_registry=install_registry, silent=silent)
        if preload_images:
            cluster.preload_images_in_kind(config.PRELOADABLE_IMAGES)
    elif preload_images:
        console.print(
            "[yellow]Warning: --preload-images is only supported with kind clusters. Skipping.[/yellow]\n"
        )

    cluster.check_kube_connection(
        install_registry=install_registry,
        use_existing_cluster=context.is_existing, 
        using_kind_cluster=context.is_kind
    )

    if InstallableComponent.AGENT_NAMESPACES not in skip_set:
        cluster.check_and_create_agent_namespaces(silent=silent)
    else:
        console.print(
            "[yellow]Skipping Agent Namespace check/creation as requested.[/yellow]\n"
        )


def _install_components(context: ClusterContext, skip_set: Set[InstallableComponent]):
    """Orchestrates the installation of all components in the correct order."""
    console.print(
        Panel(Text("Installing Components", justify="center", style="bold yellow"))
    )

    install_params = {
        "use_existing_cluster": context.is_existing,
        "use_openshift_cluster": context.is_openshift,
    }

    # Install core components
    for component in CORE_COMPONENTS:
        _deploy_component(component, skip_set, install_params)

    # Check if Istio was skipped before proceeding with dependent components
    if InstallableComponent.ISTIO in skip_set:
        console.print(
            "[yellow]Skipping dependent components because Istio installation was skipped.[/yellow]"
        )
        return

    # Install Istio-dependent components
    for component in ISTIO_DEPENDENT_COMPONENTS:
        _deploy_component(component, skip_set, install_params)


def _print_final_instructions(context: ClusterContext):
    """Prints the final success message and instructions."""
    console.print(
        "\n",
        Panel(Text("Installation Complete!", justify="center", style="bold green")),
        "\n",
    )
    if context.is_existing:
        console.print(
            "To open the UI, you may need to set up port forwarding or an Ingress for your cluster.",
            "\n",
        )
    else:
        console.print(
            "To open the UI, navigate to: http://kagenti-ui.localtest.me:8080", "\n"
        )


@app.command()
def main(
    skip_install: List[InstallableComponent] = typer.Option(
        [],
        "--skip-install",
        help="Name of a component to skip. Use the flag multiple times.",
        case_sensitive=False,
    ),
    preload_images: bool = typer.Option(
        False,
        "--preload-images",
        help="Enable preloading of images in the kind cluster.",
    ),
    silent: bool = typer.Option(
        False,
        "--silent",
        help="Run the install without user interaction.",
    ),
    use_existing_cluster: bool = typer.Option(
        False,
        "--use-existing-cluster",
        help="Use an existing Kubernetes cluster from KUBECONFIG instead of creating a kind cluster.",
    ),
):
    """
    Installs the Agent Platform on a Kubernetes cluster.
    """
    try:
        _print_header()

        context = _determine_cluster_context(use_existing_cluster)

        skip_set = _handle_automatic_skips(context, skip_install)

        # Perform pre-flight checks and cluster setup
        _setup_cluster(context, skip_set, preload_images, silent)

        _install_components(context, skip_set)

        _print_final_instructions(context)

    except typer.Exit:
        console.print("\n[bold yellow]Installation aborted.[/bold yellow]")
        sys.exit(1)
    except Exception as e:
        console.print(f"\n[bold red]An unexpected error occurred: {e}[/bold red]")
        raise

if __name__ == "__main__":
    app()
