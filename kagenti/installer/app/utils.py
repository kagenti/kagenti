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

from kubernetes import client
from packaging.version import Version, parse
from rich.console import Console
import typer

console = Console()


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
