# Assisted by watsonx Code Assistant
#!/usr/bin/env python3

import os
import re
import shutil
import subprocess
import time
from enum import Enum
from pathlib import Path
from typing import List, Optional
import requests

import docker
import typer
from dotenv import load_dotenv
from kubernetes import client, config
from packaging.version import Version, parse
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm
from rich.text import Text
from .keycloak import setup_keycloak

# --- Configuration ---
SCRIPT_DIR = Path(__file__).parent.resolve()
PROJECT_ROOT = SCRIPT_DIR.parent.parent.parent
ENV_FILE = SCRIPT_DIR / ".env"
RESOURCES_DIR = SCRIPT_DIR / "resources"
CLUSTER_NAME = "agent-platform"
OPERATOR_NAMESPACE = "kagenti-system"
TEKTON_VERSION = "v0.66.0"
LATEST_TAG = "0.2.0-alpha.2"
KEYCLOAK_URL="http://keycloak.localtest.me:8080/realms/master"

# --- Dependency Version Requirements ---
REQ_VERSIONS = {
    "kind": {"min": "0.20.0", "max": "0.99.0"},
    "docker": {"min": "5.0.0", "max": "28.0.0"},
    "kubectl": {"min": "1.29.0", "max": "1.34.0"},
    "helm": {"min": "3.14.0", "max": "3.19.0"},
}

# --- Images to preload in kind ---
PRELOADABLE_IMAGES = [
    "docker.io/istio/proxyv2:1.26.1-distroless",
    "docker.io/istio/install-cni:1.26.1-distroless",
    "docker.io/istio/pilot:1.26.1-distroless",
    "docker.io/istio/ztunnel:1.26.1",
    "docker.io/istio/proxyv2:1.26.1-distroless",
    "otel/opentelemetry-collector-contrib:0.122.1",
    "arizephoenix/phoenix:version-8.32.1",
    "postgres:12",
    "prom/prometheus:v3.1.0",
]

# --- Enum for Skippable Components ---
class InstallableComponent(str, Enum):
    REGISTRY = "registry"
    TEKTON = "tekton"
    OPERATOR = "operator"
    ISTIO = "istio"
    ADDONS = "addons"  # Prometheus, Kiali & Phoenix
    UI = "ui"
    GATEWAY = "gateway"
    KEYCLOAK = "keycloak"
    AGENTS = "agents"


# --- Rich Console & Typer App Initialization ---
console = Console()
app = typer.Typer(
    help="A CLI tool to install the Agent Platform on a local Kind cluster.",
    add_completion=False,
)


def get_command_version(command: str) -> Optional[Version]:
    """Finds command on PATH and extracts its version."""
    # Use shutil.which to find the full path of the command
    executable_path = shutil.which(command)
    if not executable_path:
        return None  # Command not found in PATH

    try:
        if command == "kubectl":
            result = subprocess.run(
                [executable_path, "version", "--client", "-o", "json"],
                capture_output=True,
                text=True,
                check=True,
            )
            version_str = re.search(r'"gitVersion":\s*"v([^"]+)"', result.stdout).group(
                1
            )
        elif command == "helm":
            result = subprocess.run(
                [executable_path, "version"], capture_output=True, text=True, check=True
            )
            match = re.search(r'Version:"v([^"]+)"', result.stdout)
            if not match:
                return None
            version_str = match.group(1)
        else:
            result = subprocess.run(
                [executable_path, "--version"],
                capture_output=True,
                text=True,
                check=True,
            )
            # More robust regex to find version numbers like vX.Y.Z or X.Y.Z
            match = re.search(r"v?(\d+\.\d+\.\d+)", result.stdout)
            if not match:
                return None
            version_str = match.group(1)
        return parse(version_str)
    except (
        FileNotFoundError,
        IndexError,
        subprocess.CalledProcessError,
        AttributeError,
    ):
        return None


def check_dependencies():
    """Checks for required binaries and their versions."""
    console.print(
        Panel(Text("1. Checking Dependencies", justify="center", style="bold yellow"))
    )
    all_ok = True
    for tool, versions in REQ_VERSIONS.items():
        with console.status(f"[cyan]Checking for {tool}..."):
            time.sleep(0.5)
            version = get_command_version(tool)
            min_ver, max_ver = parse(versions["min"]), parse(versions["max"])
            if version is None:
                console.log(
                    f"[bold red]✗ {tool}[/bold red] is not installed or not in PATH."
                )
                all_ok = False
            elif not (min_ver <= version < max_ver):
                console.log(
                    f"[bold red]✗ {tool}[/bold red] version [bold yellow]{version}[/bold yellow] not in range ({min_ver} - {max_ver})."
                )
                all_ok = False
            else:
                console.log(
                    f"[bold green]✓ {tool}[/bold green] version [bold cyan]{version}[/bold cyan] is compatible."
                )
    if not all_ok:
        console.print(
            "\n[bold red]Please install or update the required tools before proceeding.[/bold red]"
        )
        raise typer.Exit(1)
    console.print("[bold green]All dependency checks passed.[/bold green]\n")


def run_command(command: list, description: str):
    """Executes a shell command with a spinner."""
    # Find the full path of the command to run
    executable = shutil.which(command[0])
    if not executable:
        console.log(
            f"[bold red]✗ Command '{command[0]}' not found. Please ensure it is installed and in your PATH.[/bold red]"
        )
        raise typer.Exit(1)

    full_command = [executable] + command[1:]

    with console.status(f"[cyan]{description}..."):
        try:
            process = subprocess.run(
                full_command, check=True, capture_output=True, text=True
            )
            console.log(
                f"[bold green]✓[/bold green] {description} [bold green]done[/bold green]."
            )
            return process
        except subprocess.CalledProcessError as e:
            console.log(
                f"[bold red]✗[/bold red] {description} [bold red]failed[/bold red]."
            )
            console.log(f"[red]Error: {e.stderr.strip()}[/red]")
            raise typer.Exit(1)


def check_env_vars():
    """Checks for required environment variables."""
    console.print(
        Panel(
            Text(
                "2. Checking Environment Variables",
                justify="center",
                style="bold yellow",
            )
        )
    )
    with console.status("[cyan]Checking for .env file and variables..."):
        time.sleep(0.5)
        load_dotenv(dotenv_path=ENV_FILE)
        required_vars = [
            "GITHUB_USER",
            "GITHUB_TOKEN",
            "OPENAI_API_KEY",
            "AGENT_NAMESPACES",
        ]
        missing = [v for v in required_vars if not os.getenv(v)]
        if missing:
            console.log(
                f"[bold red]✗ Missing required environment variables: {', '.join(missing)}[/bold red]"
            )
            console.log(
                "  Please ensure they are set in your .env file or environment."
            )
            raise typer.Exit()
        console.log(
            "[bold green]✓[/bold green] All required environment variables are set."
        )
    console.print()


def kind_cluster_exists():
    """Checks if the Kind cluster is already running."""
    try:
        docker_client = docker.from_env()
        return any(CLUSTER_NAME in c.name for c in docker_client.containers.list())
    except docker.errors.DockerException:
        console.log(
            "[bold red]✗ Docker is not running. Please start the Docker daemon.[/bold red]"
        )
        raise typer.Exit(1)


def create_kind_cluster(install_registry: bool):
    """Creates a Kind cluster, optionally configuring it for an insecure registry."""
    console.print(
        Panel(
            Text("3. Kubernetes Cluster Setup", justify="center", style="bold yellow")
        )
    )
    if kind_cluster_exists():
        console.log(
            f"[bold green]✓[/bold green] Kind cluster '{CLUSTER_NAME}' already exists. Skipping creation."
        )
        return

    if not Confirm.ask(
        f"[bold yellow]?[/bold yellow] Kind cluster '{CLUSTER_NAME}' not found. Create it now?",
        default=True,
    ):
        console.print("[bold red]Cannot proceed without a cluster. Exiting.[/bold red]")
        raise typer.Exit()

    base_config = f"""
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

    with console.status(f"[cyan]Creating Kind cluster '{CLUSTER_NAME}'..."):
        try:
            kind_executable = shutil.which("kind")
            subprocess.run(
                [
                    kind_executable,
                    "create",
                    "cluster",
                    "--name",
                    CLUSTER_NAME,
                    "--config=-",
                ],
                input=final_config,
                text=True,
                check=True,
            )
            console.log(
                f"[bold green]✓[/bold green] Kind cluster '{CLUSTER_NAME}' created."
            )
        except subprocess.CalledProcessError as e:
            console.log(f"[bold red]✗ Failed to create Kind cluster.[/bold red]")
            console.log(f"[red]{e.stderr.strip()}[/red]")
            raise typer.Exit(1)
    console.print()

def preload_images_in_kind(images):
    for image in images:
        run_command(["docker", "pull", image],f"Pulling image {image}")
        run_command(["kind", "load", "docker-image", image, "--name", CLUSTER_NAME],f"Loading image {image} in kind")

def check_and_create_agent_namespaces():
    """Checks for agent namespaces and prompts to create them if missing."""
    namespaces_str = os.getenv("AGENT_NAMESPACES", "")
    if not namespaces_str:
        console.log(
            "[yellow]AGENT_NAMESPACES not set. Skipping agent namespace check.[/yellow]"
        )
        return

    agent_namespaces = [ns.strip() for ns in namespaces_str.split(",") if ns.strip()]

    try:
        config.load_kube_config()
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
            raise typer.Exit()
    else:
        console.log(
            "[bold green]✓ All required agent namespaces already exist.[/bold green]"
        )
    console.print()


def deploy_component(name: str, func, skip_list: list):
    """Generic function to deploy a component or skip it."""
    component_enum = InstallableComponent(name.lower())
    if component_enum in skip_list:
        console.print(f"[yellow]Skipping {name} installation as requested.[/yellow]")
        return

    console.print(Panel(f"Installing {name}", style="bold cyan", expand=False))
    func()
    console.print()


def install_registry():
    """Deploys the internal container registry and configures DNS."""
    run_command(
        ["kubectl", "apply", "-f", str(RESOURCES_DIR / "registry.yaml")],
        "Deploying container registry manifest",
    )
    run_command(
        ["kubectl", "-n", "cr-system", "rollout", "status", "deployment/registry"],
        "Waiting for registry deployment to be ready",
    )

    with console.status("[cyan]Configuring registry DNS..."):
        try:
            config.load_kube_config()
            core_v1 = client.CoreV1Api()
            service = core_v1.read_namespaced_service(
                name="registry", namespace="cr-system"
            )
            registry_ip = service.spec.cluster_ip
            docker_client = docker.from_env()
            container = docker_client.containers.get(f"{CLUSTER_NAME}-control-plane")
            container.exec_run(
                f"sh -c 'echo {registry_ip} registry.cr-system.svc.cluster.local >> /etc/hosts'"
            )
            console.log(
                "[bold green]✓[/bold green] Registry DNS configured in Kind container."
            )
        except Exception as e:
            console.log(f"[bold red]✗[/bold red] Failed to configure registry DNS: {e}")
            raise typer.Exit(1)


def install_tekton():
    """Installs Tekton Pipelines."""
    tekton_url = f"https://storage.googleapis.com/tekton-releases/pipeline/previous/{TEKTON_VERSION}/release.yaml"
    run_command(
        ["kubectl", "apply", "--filename", tekton_url], "Installing Tekton Pipelines"
    )


def install_operator():
    """Installs the BeeAI Operator using Helm."""
    run_command(
        [
            "helm",
            "upgrade",
            "--install",
            "kagenti-beeai-operator",
            "oci://ghcr.io/kagenti/kagenti-operator/kagenti-beeai-operator-chart",
            "--create-namespace",
            "--namespace",
            OPERATOR_NAMESPACE,
            "--version",
            LATEST_TAG,
        ],
        "Installing the BeeAI Operator",
    )


def install_ui():
    """Installs the Kagent UI."""
    ui_yaml_path = PROJECT_ROOT / "deployments" / "ui" / "kagenti-ui.yaml"
    if not ui_yaml_path.exists():
        console.log(
            f"[bold red]✗ UI deployment file not found at expected path: {ui_yaml_path}[/bold red]"
        )
        raise typer.Exit(1)
    run_command(["kubectl", "apply", "-f", str(ui_yaml_path)], "Installing Kagenti UI")
    run_command(
        [
            "kubectl",
            "label",
            "ns",
            "kagenti-system",
            "shared-gateway-access=true",
            "--overwrite",
        ],
        "Sharing gateway access",
    )
    run_command(
        [
            "kubectl",
            "rollout",
            "status",
            "-n",
            "kagenti-system",
            "deployment/kagenti-ui",
        ],
        "Waiting for kagenti-ui rollout",
    )


def install_istio():
    """Installs all Istio components using Helm."""
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

    # Wait for rollouts
    run_command(
        ["kubectl", "rollout", "status", "-n", "istio-system", "daemonset/ztunnel"],
        "Checking ztunnel rollout status",
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
        "Checking Istio CNI rollout status",
    )
    run_command(
        ["kubectl", "rollout", "status", "-n", "istio-system", "deployment/istiod"],
        "Checking Istiod rollout status",
    )


def install_gateway():
    """Installs the Istio ingress and egress gateways."""
    run_command(
        ["kubectl", "apply", "-f", str(RESOURCES_DIR / "http-gateway.yaml")],
        "Creating Istio ingress gateway",
    )
    run_command(
        ["kubectl", "apply", "-f", str(RESOURCES_DIR / "gateway-nodeport.yaml")],
        "Adding NodePort service for gateway",
    )
    run_command(
        [
            "kubectl",
            "annotate",
            "gateway",
            "http",
            "networking.istio.io/service-type=ClusterIP",
            f"--namespace={OPERATOR_NAMESPACE}",
            "--overwrite",
        ],
        "Annotating gateway service type",
    )
    run_command(
        ["kubectl", "apply", "-f", str(RESOURCES_DIR / "gateway-waypoint.yaml")],
        "Adding egress waypoint gateway",
    )
    run_command(
        ["kubectl", "rollout", "status", "-n", "default", "deployment/waypoint"],
        "Waiting for waypoint gateway rollout",
    )


def install_addons():
    """Installs Prometheus, Kiali, and Phoenix."""
    run_command(
        [
            "kubectl",
            "apply",
            "-f",
            "https://raw.githubusercontent.com/istio/istio/release-1.25/samples/addons/prometheus.yaml",
        ],
        "Installing Prometheus",
    )
    run_command(
        ["kubectl", "rollout", "status", "-n", "istio-system", "deployment/prometheus"],
        "Waiting for Prometheus rollout",
    )
    run_command(
        [
            "kubectl",
            "apply",
            "-f",
            "https://raw.githubusercontent.com/istio/istio/release-1.25/samples/addons/kiali.yaml",
        ],
        "Installing Kiali",
    )
    run_command(
        [
            "kubectl",
            "apply",
            "-f",
            str(RESOURCES_DIR / "kiali-route.yaml"),
        ],
        "Adding Kiali Route",
    )
    run_command(
        [
            "kubectl",
            "label",
            "ns",
            "istio-system",
            "shared-gateway-access=true",
            "--overwrite",
        ],
        "Enabling istio-system for kiali routing",
    )
    run_command(
        ["kubectl", "rollout", "status", "-n", "istio-system", "deployment/kiali"],
        "Waiting for Kiali rollout",
    )
    run_command(
        [
            "kubectl",
            "apply",
            "-n",
            "kagenti-system",
            "-f",
            str(RESOURCES_DIR / "phoenix.yaml"),
        ],
        "Installing Phoenix",
    )
    run_command(
        [
            "kubectl",
            "rollout",
            "status",
            "-n",
            "kagenti-system",
            "statefulset/postgres",
        ],
        "Waiting for Postgres rollout",
    )

    run_command(
        ["kubectl", "rollout", "status", "-n", "kagenti-system", "statefulset/phoenix"],
        "Waiting for Phoenix rollout",
    )
    run_command(
        [
            "kubectl",
            "apply",
            "-n",
            "kagenti-system",
            "-f",
            str(RESOURCES_DIR / "otel-collector.yaml"),
        ],
        "Installing Otel Collector",
    )
    run_command(
        [
            "kubectl",
            "rollout",
            "status",
            "-n",
            "kagenti-system",
            "deployment/otel-collector",
        ],
        "Waiting for otel collector rollout",
    )


def install_keycloak():
    """Installs Keycloak and its required resources."""
    keycloak_namespace_path = RESOURCES_DIR / "keycloak-namespace.yaml"
    keycloak_route_path = RESOURCES_DIR / "keycloak-route.yaml"

    run_command(
        ["kubectl", "apply", "-f", str(keycloak_namespace_path)],
        "Creating Keycloak namespace",
    )
    run_command(
        [
            "kubectl",
            "apply",
            "-n",
            "keycloak",
            "-f",
            "https://raw.githubusercontent.com/keycloak/keycloak-quickstarts/refs/heads/main/kubernetes/keycloak.yaml",
        ],
        "Deploying Keycloak statefulset",
    )
    run_command(
        [
            "kubectl",
            "scale",
            "-n",
            "keycloak",
            "statefulset",
            "keycloak",
            "--replicas=1",
        ],
        "Scaling Keycloak to 1 replica",
    )

    patch_str = """
    {
        "spec": {
            "template": {
                "spec": {
                    "containers": [
                        {
                            "name": "keycloak",
                            "env": [
                                {
                                    "name": "KC_PROXY_HEADERS",
                                    "value": "forwarded"
                                }
                            ],
                            "resources": {
                                "limits": {
                                    "memory": "3000Mi"
                                }
                            },
                            "startupProbe": {
                                "periodSeconds": 30,
                                "timeoutSeconds": 60
                            }
                        }
                    ]
                }
            }
        }
    }
    """
    run_command(
        [
            "kubectl",
            "patch",
            "statefulset",
            "keycloak",
            "-n",
            "keycloak",
            "--type",
            "strategic",
            "--patch",
            patch_str,
        ],
        "Patching Keycloak for proxy headers",
    )
    run_command(
        ["kubectl", "rollout", "status", "-n", "keycloak", "statefulset/keycloak"],
        "Waiting for Keycloak rollout",
    )
    run_command(
        ["kubectl", "apply", "-f", str(keycloak_route_path)], "Applying Keycloak route"
    )
    run_command(
        [
            "kubectl",
            "label",
            "ns",
            "keycloak",
            "shared-gateway-access=true",
            "--overwrite",
        ],
        "Sharing gateway access for Keycloak",
    )
    run_command(
        [
            "kubectl",
            "label",
            "namespace",
            "keycloak",
            "istio.io/dataplane-mode=ambient",
            "--overwrite",
        ],
        "Adding Keycloak to Istio ambient mesh",
    )

    # setup Keycloak demo realm, user and agent
    client_secret = setup_keycloak()

    # setup namespaces
    namespaces_str = os.getenv("AGENT_NAMESPACES", "")
    if not namespaces_str:
        return
    agent_namespaces = [ns.strip() for ns in namespaces_str.split(",") if ns.strip()]
    try:
        config.load_kube_config()
        v1_api = client.CoreV1Api()
    except Exception as e:
        console.log(
            f"[bold red]✗ Could not connect to Kubernetes to configure agent namespaces for keycloak: {e}[/bold red]"
        )
        raise typer.Exit(1)
    for ns in agent_namespaces:
        console.print(
            f"\n[cyan]Setting up keycloak client secret in namespace: {ns}[/cyan]"
        )
        if not secret_exists(v1_api, "keycloak-client-secret", ns):
            run_command(
                [
                    "kubectl",
                    "create",
                    "secret",
                    "generic",
                    "keycloak-client-secret",
                    f"--from-literal=client-secret={client_secret}",
                    "-n",
                    ns,
                ],
                f"Creating 'keycloak-client-secret' in '{ns}'",
            )

def secret_exists(v1_api: client.CoreV1Api, name: str, namespace: str) -> bool:
    """Checks if a secret exists in a given namespace."""
    try:
        v1_api.read_namespaced_secret(name=name, namespace=namespace)
        console.log(
            f"[grey70]Secret '{name}' already exists in namespace '{namespace}'. Skipping creation.[/grey70]"
        )
        return True
    except client.ApiException as e:
        if e.status == 404:
            return False
        console.log(
            f"[bold red]Error checking for secret '{name}' in '{namespace}': {e}[/bold red]"
        )
        raise typer.Exit(1)


def install_agent_namespaces():
    """Applies required secrets and labels to agent namespaces."""
    namespaces_str = os.getenv("AGENT_NAMESPACES", "")
    if not namespaces_str:
        return  # Should not happen if AGENTS component is not skipped

    agent_namespaces = [ns.strip() for ns in namespaces_str.split(",") if ns.strip()]

    try:
        config.load_kube_config()
        v1_api = client.CoreV1Api()
    except Exception as e:
        console.log(
            f"[bold red]✗ Could not connect to Kubernetes to configure agent namespaces: {e}[/bold red]"
        )
        raise typer.Exit(1)

    github_user = os.getenv("GITHUB_USER")
    github_token = os.getenv("GITHUB_TOKEN")
    openai_api_key = os.getenv("OPENAI_API_KEY")

    for ns in agent_namespaces:
        console.print(f"\n[cyan]Configuring namespace: {ns}[/cyan]")

        # Create GitHub secret if it doesn't exist
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
                f"Creating github-token-secret in '{ns}'",
            )

        # Create OpenAI secret if it doesn't exist
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
                f"Creating openai-secret in '{ns}'",
            )

        # apply configmap with environments
        run_command(
            [
                "kubectl",
                "apply",
                "-n",
                ns,
                "-f",
                str(RESOURCES_DIR / "environments.yaml"),
            ],
            f"Applying environments configmap in '{ns}'",
        )

        # Apply labels
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
):
    """
    Installer for the Agent Platform. Checks dependencies and sets up a Kind cluster with optional components.
    """
    try:
        console.print(
            Panel(
                Text("Agent Platform Installer", justify="center", style="bold blue"),
                expand=False,
            )
        )

        check_dependencies()
        check_env_vars()

        should_install_registry = InstallableComponent.REGISTRY not in skip_install
        create_kind_cluster(install_registry=should_install_registry)

        if preload_images:
            preload_images_in_kind(PRELOADABLE_IMAGES)

        console.print(
            Panel(
                Text(
                    "4. Checking Agent Namespaces",
                    justify="center",
                    style="bold yellow",
                )
            )
        )
        if InstallableComponent.AGENTS not in skip_install:
            check_and_create_agent_namespaces()
        else:
            console.print(
                "[yellow]Skipping Agent Namespace check/creation as requested.[/yellow]"
            )
        console.print()

        # --- Component Installation ---
        console.print(
            Panel(
                Text("5. Installing Components", justify="center", style="bold yellow")
            )
        )

        if should_install_registry:
            deploy_component("Registry", install_registry, skip_install)
        else:
            console.print(
                "[yellow]Skipping Registry installation as requested.[/yellow]"
            )

        deploy_component("Tekton", install_tekton, skip_install)
        deploy_component("Operator", install_operator, skip_install)
        deploy_component("Istio", install_istio, skip_install)
        deploy_component("UI", install_ui, skip_install)

        # Components that depend on Istio
        if InstallableComponent.ISTIO not in skip_install:
            deploy_component("Addons", install_addons, skip_install)
            deploy_component("Gateway", install_gateway, skip_install)
            deploy_component("Agents", install_agent_namespaces, skip_install)
            deploy_component("Keycloak", install_keycloak, skip_install)
        else:
            console.print(
                "[yellow]Skipping Addons, Gateway, Keycloak, and Agent Namespace configuration because Istio is skipped.[/yellow]"
            )

        console.print(
            "\n",
            Panel(Text("Installation Complete!", justify="center", style="bold green")),
            "\n",
        )

    except typer.Exit:
        console.print("\n[bold yellow]Installation aborted.[/bold yellow]")
    except Exception as e:
        console.print(f"\n[bold red]An unexpected error occurred: {e}[/bold red]")
        raise


if __name__ == "__main__":
    app()
