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

import re
import time
import shutil
import subprocess
from typing import Optional
import base64
import logging
from typing import Type, TypeVar
from kubernetes import client, config
from kubernetes.client.rest import ApiException
from packaging.version import Version, parse
from rich.console import Console
import typer

console = Console()
# Set up a logger for this module
logger = logging.getLogger(__name__)

# Use a TypeVar to represent any Kubernetes API client class, like CoreV1Api, AppsV1Api, etc.
T = TypeVar("T")

class KubeConfigError(Exception):
    """Custom exception raised when Kubernetes config cannot be loaded."""
    pass

def get_latest_tagged_version(github_repo, fallback_version) -> str:
    """Fetches the latest version tag of the component from GitHub releases.

    Args:
        github_repo (str): The GitHub repository path of the component.
        fallback_version (str): The fallback version to return if fetching fails.

    Returns:
        str: The latest version tag or the fallback version.
    """
    try:
        result = subprocess.run(
            [
                "git", "ls-remote", "--tags", "--sort=-version:refname",
                github_repo,
            ],
            capture_output=True,
            text=True,
            check=True,
            timeout=30
        )

        lines = result.stdout.strip().split('\n')
        for line in lines:
            if line and 'refs/tags/' in line:
                # Extract tag name
                tag = line.split('refs/tags/')[-1]
                if '^{}' not in tag:  # Exclude annotated tags
                    return tag

        console.log(
            "[yellow]Could not find tag name in the response. Using fallback version.[/yellow]"
        )
        return fallback_version
    except subprocess.CalledProcessError as e:
        console.log(
            f"[bold red]Error fetching latest version: {e}. Using fallback version.[/bold red]"
        )
        return fallback_version


def get_command_version(command: str) -> Optional[Version]:
    """Finds a command on PATH and extracts its version string."""
    executable_path = shutil.which(command)
    if not executable_path:
        return None  # Command not found

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
            match = re.search(r'Version:"v?([^"]+)"', result.stdout)
            version_str = match.group(1) if match else ""
        else:
            result = subprocess.run(
                [executable_path, "--version"],
                capture_output=True,
                text=True,
                check=True,
            )
            match = re.search(r"v?(\d+\.\d+\.\d+)", result.stdout)
            version_str = match.group(1) if match else ""

        return parse(version_str) if version_str else None
    except (
        FileNotFoundError,
        IndexError,
        subprocess.CalledProcessError,
        AttributeError,
    ):
        return None


def run_command(command: list[str], description: str):
    """Executes a shell command with a spinner and rich logging."""
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


def get_api_client(api_client_class: Type[T]) -> T:
    """Initializes and returns a specific Kubernetes API client.

    This function attempts to load the Kubernetes configuration by trying two methods
    in order: first from the default kubeconfig file (e.g., `~/.kube/config`) and
    then from the in-cluster service account environment if running inside a pod.

    Args:
        api_client_class: The Kubernetes client class to instantiate.
                          For example, `client.CoreV1Api` or `client.AppsV1Api`.

    Returns:
        An initialized instance of the requested Kubernetes API client class.

    Raises:
        KubeConfigError: If both the local kubeconfig file and the in-cluster
                         configuration fail to load.
    """
    try:
        config.load_kube_config()
        logger.debug("Successfully loaded configuration from kubeconfig file.")
    except config.ConfigException:
        logger.debug("Could not load from kubeconfig. Attempting in-cluster config.")
        try:
            config.load_incluster_config()
            logger.debug("Successfully loaded in-cluster configuration.")
        except config.ConfigException as e:
            error_msg = "Failed to load both local and in-cluster Kubernetes config."
            logger.error(error_msg)
            # Chain the original exception for better debugging context
            raise KubeConfigError(error_msg) from e

    return api_client_class()


def secret_exists(v1_api: client.CoreV1Api, name: str, namespace: str) -> bool:
    """Checks if a Kubernetes secret exists in a given namespace."""
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


def create_or_update_secret(v1_api: client.CoreV1Api, namespace: str, secret_body: client.V1Secret):
    """Create or update a Kubernetes secret in a given namespace."""
    secret_name = secret_body.metadata.name
    try:
        v1_api.create_namespaced_secret(namespace=namespace, body=secret_body)
        console.log(
            f"[bold green]✓[/bold green] Secret '{secret_name}' creation in '{namespace}' [bold green]done[/bold green]."
        )
    except client.ApiException as e:
        # Secret already exists - patch it
        if e.status == 409:
            v1_api.patch_namespaced_secret(name=secret_name, namespace=namespace, body=secret_body)
            console.log(
                f"[bold green]✓[/bold green] Secret '{secret_name}' patch in '{namespace}' [bold green]done[/bold green]."
            )
        else:
            console.log(
                f"[bold red]Error creating secret '{secret_name}' in '{namespace}': {e}[/bold red]"
            )
            raise typer.Exit(1)
        

def create_or_update_configmap(v1_api: client.CoreV1Api, namespace: str, configmap: client.V1ConfigMap):
    """Create or update a Kubernetes configmap in a given namespace."""
    configmap_name = configmap.metadata.name
    try:
        v1_api.create_namespaced_config_map(namespace=namespace, body=configmap)
        console.log(
            f"[bold green]✓[/bold green] ConfigMap '{configmap_name}' creation in '{namespace}' [bold green]done[/bold green]."
        )
    except client.ApiException as e:
        # Configmap already exists - patch it
        if e.status == 409:
            v1_api.patch_namespaced_config_map(name=configmap_name, namespace=namespace, body=configmap)
            console.log(
                f"[bold green]✓[/bold green] Secret '{configmap_name}' patch in '{namespace}' [bold green]done[/bold green]."
            )
        else:
            console.log(
                f"[bold red]Error creating secret '{configmap_name}' in '{namespace}': {e}[/bold red]"
            )
            raise typer.Exit(1)        


def wait_for_deployment(namespace, deployment_name, retries=30, delay=10):
    """Waits for a deployment to be created."""
    for _ in range(retries):
        try:
            # Check if the deployment exists
            subprocess.run(
                ["kubectl", "get", "deployment", deployment_name, "-n", namespace],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            return True
        except subprocess.CalledProcessError:
            # Deployment does not exist yet; wait and retry
            time.sleep(delay)
    return False

def get_secret_values(v1_api: client.CoreV1Api, namespace: str, secret_name: str, key1_name: str, key2_name: str) -> dict | None:
    """
    Extracts and returns the decoded values of two named keys from a Kubernetes secret.

    Args:
        namespace (str): The Kubernetes namespace where the secret is located.
        secret_name (str): The name of the secret.
        key1_name (str): The name of the first key to retrieve from the secret's data.
        key2_name (str): The name of the second key to retrieve from the secret's data.

    Returns:
        key values if successful,
        otherwise None.
    """
    try:
        secret = v1_api.read_namespaced_secret(name=secret_name, namespace=namespace)

        if not secret.data:
            console.log(f"⚠️ Error: Secret '{secret_name}' in namespace '{namespace}' contains no data.")
            return None

        if key1_name not in secret.data or key2_name not in secret.data:
            missing = {key for key in [key1_name, key2_name] if key not in secret.data}
            console.log(f"⚠️ Error: Key(s) {missing} not found in secret '{secret_name}'.")
            return None

        value1 = base64.b64decode(secret.data[key1_name]).decode('utf-8')
        value2 = base64.b64decode(secret.data[key2_name]).decode('utf-8')

        return value1, value2

    except ApiException as e:
        if e.status == 404:
            console.log(f"❌ Error: Secret '{secret_name}' not found in namespace '{namespace}'.")
        else:
            console.log(f"❌ API Error reading secret '{secret_name}': {e.reason}")
        return None
    except Exception as e:
        console.log(f"An unexpected error occurred: {e}")
        return None