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

from pathlib import Path
import subprocess
import shutil
from rich.console import Console
import typer
from ..utils import run_command
from .. import config
from ..ocp_utils import verify_operator_installation


def install_gateway_api_if_needed():
    """
    Checks if the Gateway API CRD exists in the Kubernetes cluster
    and installs it if it is not found. 
    """
    console = Console()
    check_command = ["kubectl", "get", "crd", "gateways.gateway.networking.k8s.io"]
    description = "Checking for Kubernetes Gateway API CRD"

    executable = shutil.which(check_command[0])
    if not executable:
        console.log(
            f"[bold red]✗ Command '{check_command[0]}' not found. Please ensure it is installed and in your PATH.[/bold red]"
        )
        raise typer.Exit(1)
    
    full_check_command = [executable] + check_command[1:]

    crd_exists = False
    console.log(f"[cyan]{description}...[/cyan]")
    try:
        subprocess.run(
            full_check_command,
            check=True,
            capture_output=True,
            text=True,
        )
        console.log("[bold green]✓ Gateway API CRD already installed.[/bold green]")
        crd_exists = True
    except subprocess.CalledProcessError:
        console.log("[yellow]i Gateway API CRD not found. Proceeding with installation.[/yellow]")
        crd_exists = False

    # If the CRD was not found, run the installation command.
    if not crd_exists:
        install_url = "https://github.com/kubernetes-sigs/gateway-api/config/crd?ref=v1.3.0"
        #install_url = "https://github.com/kubernetes-sigs/gateway-api/releases/download/v1.2.0/standard-install.yaml"
        install_command = ["kubectl", "apply", "-f", install_url]
        run_command(install_command, "Installing Kubernetes Gateway API")


def install(use_openshift_cluster: bool = False, **kwargs):
    if use_openshift_cluster:
        _install_on_openshift()
    else:
        _install_on_k8s()


def _install_on_k8s():
    """Installs all Istio components using the official Helm charts."""
    run_command(
        [
            "helm",
            "repo",
            "add",
            "istio",
            "https://istio-release.storage.googleapis.com/charts",
        ],
        "Adding Istio Helm repo",
    )
    run_command(["helm", "repo", "update"], "Updating Helm repos")
    run_command(
        [
            "helm",
            "upgrade",
            "--install",
            "istio-base",
            "istio/base",
            "-n",
            "istio-system",
            "--create-namespace",
            "--wait",
        ],
        "Installing Istio base",
    )
    run_command(
        [
            "kubectl",
            "apply",
            "-f",
            "https://github.com/kubernetes-sigs/gateway-api/releases/download/v1.1.0/standard-install.yaml",
        ],
        "Installing Kubernetes Gateway API",
    )
    run_command(
        [
            "helm",
            "upgrade",
            "--install",
            "istiod",
            "istio/istiod",
            "-n",
            "istio-system",
            "--set",
            "profile=ambient",
            "--wait",
        ],
        "Installing Istiod (ambient profile)",
    )
    run_command(
        [
            "helm",
            "upgrade",
            "--install",
            "istio-cni",
            "istio/cni",
            "-n",
            "istio-system",
            "--set",
            "profile=ambient",
            "--wait",
        ],
        "Installing Istio CNI",
    )
    run_command(
        [
            "helm",
            "upgrade",
            "--install",
            "ztunnel",
            "istio/ztunnel",
            "-n",
            "istio-system",
            "--wait",
        ],
        "Installing Ztunnel",
    )

    # Wait for all Istio component rollouts to complete
    run_command(
        ["kubectl", "rollout", "status", "-n", "istio-system", "daemonset/ztunnel"],
        "Waiting for ztunnel rollout",
    )
    run_command(
        [
            "kubectl",
            "rollout",
            "status",
            "-n",
            "istio-system",
            "daemonset/istio-cni-node",
        ],
        "Waiting for Istio CNI rollout",
    )
    run_command(
        ["kubectl", "rollout", "status", "-n", "istio-system", "deployment/istiod"],
        "Waiting for Istiod rollout",
    )


def _install_on_openshift():
    """Installs Istio ambient on OpenShift using the Sail operator."""
    operator_path: Path = config.RESOURCES_DIR / "ocp" / "servicemeshoperator3.yaml"
    namespace = "openshift-operators"
    subscription = "servicemeshoperator3"
    run_command(
        ["kubectl", "apply", "-n", namespace, "-f", operator_path],
        "Installing Service Mesh Operator 3"
    )

    verify_operator_installation(
        subscription_name=subscription,
        namespace=namespace,
    )

    # setup istio instance
    istio_path: Path = config.RESOURCES_DIR / "ocp" / "istio.yaml"
    run_command(
        ["kubectl", "apply", "-n", namespace, "-f", istio_path],
        "Creating Istio Instance"
    )

    run_command(
        [
            "kubectl",
            "wait",
            "--for=condition=Ready",
            "istios/default",
            "--timeout=180s"
        ],
        "Waiting for Istio instance to become ready",
    )

    # setup istio-cni
    istiocni_path: Path = config.RESOURCES_DIR / "ocp" / "istio-cni.yaml"
    run_command(
        ["kubectl", "apply", "-f", istiocni_path],
        "Creating Istio CNI instance"
    )

    run_command(
        [
            "kubectl",
            "wait",
            "--for=condition=Ready",
            "istiocnis/default",
            "--timeout=180s"
        ],
        "Waiting for IstioCNI instance to become ready",
    )

    # setup ztunnel
    ztunnel_path: Path = config.RESOURCES_DIR / "ocp" / "ztunnel.yaml"
    run_command(
        ["kubectl", "apply", "-f", ztunnel_path],
        "Creating Ztunnel instance"
    )

    run_command(
        [
            "kubectl",
            "wait",
            "--for=condition=Ready",
            "ztunnel/default",
            "--timeout=180s"
        ],
        "Waiting for Ztunnel instance to become ready",
    )

    # install Gateway API
    install_gateway_api_if_needed()
