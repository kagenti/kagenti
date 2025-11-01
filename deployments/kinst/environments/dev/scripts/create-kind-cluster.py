#!/usr/bin/env python3

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
import os
import subprocess
import shutil
import re
import argparse
import pathlib
from typing import Optional

# --- Constants ---

# Get the directory where this script is located
SCRIPT_DIR = pathlib.Path(__file__).resolve().parent

# Default values from the Bash script
DEFAULT_CLUSTER_NAME = "kagenti"
DEFAULT_IMAGES_FILE = SCRIPT_DIR / "preload-images.txt"
DEFAULT_CONTAINER_ENGINE = os.getenv("CONTAINER_ENGINE", "docker")


# --- Helper Functions ---


def check_command(cmd: str):
    """
    Check if a command exists in the system's PATH.
    Equivalent to 'command -v'.
    """
    if not shutil.which(cmd):
        print(f"✗ Error: Required command not found: {cmd}", file=sys.stderr)
        sys.exit(1)


def confirm(prompt: str) -> bool:
    """
    Ask the user for a yes/no confirmation.
    """
    try:
        resp = input(f"{prompt} [y/N]: ").lower().strip()
        return resp in ("y", "yes")
    except EOFError:
        return False  # Treat Ctrl+D as "No"


def kind_cluster_exists(cluster_name: str) -> bool:
    """
    Check if a Kind cluster with the given name already exists.
    Equivalent to 'kind get clusters | grep -wq "$CLUSTER_NAME"'.
    """
    try:
        result = subprocess.run(
            ["kind", "get", "clusters"], capture_output=True, text=True, check=True
        )
        clusters = result.stdout.splitlines()
        return cluster_name in clusters
    except FileNotFoundError:
        check_command("kind")  # Will print a nice error and exit
        return False  # Unreachable, but satisfies linter
    except subprocess.CalledProcessError as e:
        print(f"✗ Error checking Kind clusters: {e.stderr}", file=sys.stderr)
        sys.exit(1)


def kind_cluster_running(cluster_name: str, container_engine: str) -> bool:
    """
    Check if the Kind cluster's control-plane container is running.
    Equivalent to '$CONTAINER_ENGINE ps ... | grep ...'.
    """
    control_plane_name = f"{cluster_name}-control-plane"
    try:
        result = subprocess.run(
            [container_engine, "ps", "--format", "{{.Names}}"],
            capture_output=True,
            text=True,
            check=True,
        )
        running_containers = result.stdout.splitlines()
        return control_plane_name in running_containers
    except FileNotFoundError:
        check_command(container_engine)  # Will print a nice error and exit
        return False  # Unreachable
    except subprocess.CalledProcessError as e:
        print(f"✗ Error checking containers: {e.stderr}", file=sys.stderr)
        sys.exit(1)


def parse_cluster_name_from_values(values_file: pathlib.Path) -> Optional[str]:
    """
    Parse 'kind.clusterName' from a values.yaml file.
    Equivalent to the 'awk' command in the script.
    """
    if not values_file.is_file():
        return None

    in_kind_block = False
    cluster_name_re = re.compile(r"^\s*clusterName:\s*(.+)$")

    try:
        with open(values_file, "r") as f:
            for line in f:
                line = line.rstrip()
                if line.strip() == "kind:":
                    in_kind_block = True
                    continue

                # If we are in the 'kind:' block, look for clusterName
                if in_kind_block:
                    # If we hit another top-level key, stop
                    if line and not line.startswith((" ", "\t")):
                        in_kind_block = False
                        continue

                    match = cluster_name_re.match(line)
                    if match:
                        return match.group(1).strip()
    except Exception as e:
        print(f"Warning: Could not parse {values_file}: {e}", file=sys.stderr)

    return None


def run_cmd(cmd_args: list[str], error_msg: str, **kwargs):
    """Helper to run a command and exit on failure."""
    try:
        # 'check=True' makes it raise CalledProcessError on non-zero exit
        subprocess.run(cmd_args, check=True, **kwargs)
    except FileNotFoundError:
        print(f"✗ Error: Command not found: {cmd_args[0]}", file=sys.stderr)
        sys.exit(1)
    except subprocess.CalledProcessError as e:
        print(f"✗ {error_msg}", file=sys.stderr)
        if e.stderr:
            print(e.stderr.decode(), file=sys.stderr)
        sys.exit(e.returncode)
    except KeyboardInterrupt:
        print("\nOperation aborted by user.", file=sys.stderr)
        sys.exit(1)


# --- Main Logic ---


def main():
    parser = argparse.ArgumentParser(
        description="Create or manage a Kind cluster.",
        formatter_class=argparse.RawTextHelpFormatter,
    )

    parser.add_argument(
        "--cluster-name",
        "--name",
        dest="cluster_name",
        default=os.getenv("CLUSTER_NAME", DEFAULT_CLUSTER_NAME),
        help=f"Name of the Kind cluster (default: {DEFAULT_CLUSTER_NAME} or $CLUSTER_NAME)",
    )
    parser.add_argument(
        "--delete", action="store_true", help="Delete the Kind cluster and exit"
    )
    parser.add_argument(
        "--container-engine",
        default=DEFAULT_CONTAINER_ENGINE,
        help=f"Container engine: docker or podman (default: {DEFAULT_CONTAINER_ENGINE} or $CONTAINER_ENGINE)",
    )
    parser.add_argument(
        "--install-registry",
        action="store_true",
        help="Add containerd registry patch for local registry",
    )
    parser.add_argument(
        "--preload",
        action="store_true",
        help="Preload images from the images file into kind",
    )
    parser.add_argument(
        "--images-file",
        type=pathlib.Path,
        default=DEFAULT_IMAGES_FILE,
        help=f"Path to images file (default: {DEFAULT_IMAGES_FILE})",
    )
    parser.add_argument(
        "--yes", "-y", action="store_true", help="Skip interactive confirmation prompts"
    )

    args = parser.parse_args()

    # --- Cluster Name Resolution ---
    # Check if user *explicitly* passed --cluster-name or --name
    name_specified = any(arg in sys.argv for arg in ("--cluster-name", "--name"))
    cluster_name = args.cluster_name

    if not name_specified:
        values_file = SCRIPT_DIR / ".." / "values.yaml"
        parsed_name = parse_cluster_name_from_values(values_file)
        if parsed_name:
            cluster_name = parsed_name

    print(f"Cluster: {cluster_name}")
    print(f"Container engine: {args.container_engine}")

    # --- Initial Command Checks ---
    check_command("kind")
    check_command(args.container_engine)

    # --- Delete Action ---
    if args.delete:
        if not args.yes and not confirm(f"Delete kind cluster '{cluster_name}'?"):
            print("Delete aborted by user.")
            sys.exit(0)

        print(f"Deleting Kind cluster '{cluster_name}'...")
        run_cmd(
            ["kind", "delete", "cluster", "--name", cluster_name],
            f"Failed to delete Kind cluster '{cluster_name}'.",
        )
        print(f"✓ Kind cluster '{cluster_name}' deleted.")
        sys.exit(0)

    # --- Create / Check Action ---
    if kind_cluster_exists(cluster_name):
        if kind_cluster_running(cluster_name, args.container_engine):
            print(
                f"✓ Kind cluster '{cluster_name}' already running. Skipping creation."
            )
        else:
            print(
                f"✗ Kind cluster '{cluster_name}' exists but is not running. Cannot proceed.",
                file=sys.stderr,
            )
            sys.exit(1)
    else:
        if not args.yes and not confirm(
            f"Kind cluster '{cluster_name}' not found. Create it now?"
        ):
            print("Aborted by user.")
            sys.exit(0)

        # --- Build Kind Config ---
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

        final_config = base_config
        if args.install_registry:
            final_config += registry_patch

        print(f"Creating Kind cluster '{cluster_name}'...")
        # Pass the config to 'kind create' via stdin
        run_cmd(
            ["kind", "create", "cluster", "--name", cluster_name, "--config", "-"],
            "Failed to create Kind cluster.",
            input=final_config.encode("utf-8"),  # Pass string as bytes to stdin
        )
        print(f"✓ Kind cluster '{cluster_name}' created.")

    # --- Preload Images ---
    if args.preload:
        if not args.images_file.is_file():
            print(f"✗ Images file not found: {args.images_file}", file=sys.stderr)
            sys.exit(1)

        print(
            f"Preloading images from {args.images_file} into kind cluster '{cluster_name}'..."
        )

        try:
            with open(args.images_file, "r") as f:
                for line in f:
                    image = line.strip()

                    # Skip blank lines and comments
                    if not image or image.startswith("#"):
                        continue

                    print(f"Pulling image: {image}")
                    # Run pull, but don't exit on failure (check=False)
                    pull_result = subprocess.run([args.container_engine, "pull", image])
                    if pull_result.returncode != 0:
                        print(
                            f"Warning: failed to pull {image} with {args.container_engine}",
                            file=sys.stderr,
                        )

                    print(f"Loading {image} into kind ({cluster_name})")
                    # Run load, but don't exit on failure (check=False)
                    load_result = subprocess.run(
                        ["kind", "load", "docker-image", image, "--name", cluster_name]
                    )
                    if load_result.returncode != 0:
                        print(
                            f"Warning: failed to load {image} into kind",
                            file=sys.stderr,
                        )

        except Exception as e:
            print(
                f"✗ Error reading images file {args.images_file}: {e}", file=sys.stderr
            )
            sys.exit(1)

        print("✓ Preloading images completed.")

    print("Done.")


if __name__ == "__main__":
    main()
