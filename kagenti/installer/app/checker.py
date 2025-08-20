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
import time

import typer
from dotenv import load_dotenv
from packaging.version import parse
from rich.panel import Panel
from rich.text import Text

from . import config
from .utils import console, get_command_version


def check_dependencies(use_existing_cluster: bool = False):
    """Checks if required command-line tools are installed and meet version requirements."""
    console.print(
        Panel(Text("1. Checking Dependencies", justify="center", style="bold yellow"))
    )
    all_ok = True
    
    # Filter out tools not needed for existing clusters
    required_tools = config.REQ_VERSIONS.copy()
    if use_existing_cluster:
        # Remove kind and docker requirements when using existing cluster
        required_tools.pop('kind', None)
        required_tools.pop('docker', None)
        console.log("[yellow]Using existing cluster - skipping kind and docker checks.[/yellow]")
    
    for tool, versions in required_tools.items():
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


def check_env_vars():
    """Checks for the presence of required environment variables in the .env file."""
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
        load_dotenv(dotenv_path=config.ENV_FILE, override=True)
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
            raise typer.Exit(1)
        console.log(
            "[bold green]✓[/bold green] All required environment variables are set."
        )
    console.print()
