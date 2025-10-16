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

import tempfile
import typer
import yaml

from .. import config
from ..utils import console, get_latest_tagged_version, run_command


def install(**kwargs):
    """Installs the Kagenti UI from its deployment YAML."""
    run_command(
        [
            "kubectl",
            "apply",
            "-n",
            "kagenti-system",
            "-f",
            str(config.RESOURCES_DIR / "global-environments.yaml"),
        ],
        "Applying global-environments configmap in 'kagenti-system'",
    )
    # Create the auth secret, containing the Keycloak client secret
    run_command(
        [
            "kubectl",
            "replace",  # Use replace --force to ensure the job gets replaced
            "--force",
            "-f",
            str(config.RESOURCES_DIR / "ui-oauth-secret.yaml"),
        ],
        "Creating OAuth secret",
    )
    run_command(
        [
            "kubectl",
            "wait",
            "--for=condition=complete",
            "job/kagenti-ui-oauth-job",
            "-n",
            "kagenti-system",
            "--timeout=300s",
        ],
        "Waiting for auth secret job to complete",
    )

    ui_yaml_path = config.PROJECT_ROOT / "deployments" / "ui" / "kagenti-ui.yaml"
    if not ui_yaml_path.exists():
        console.log(
            f"[bold red]✗ UI deployment file not found at expected path: {ui_yaml_path}[/bold red]"
        )
        raise typer.Exit(1)
    # Update kagenti-ui deployment with "latest" image tag
    with open(ui_yaml_path, "r") as f:
        ui_yamls = list(yaml.safe_load_all(f))
    for ui_yaml in ui_yamls:
        if ui_yaml.get("kind") == "Deployment":
            for container in ui_yaml["spec"]["template"]["spec"]["containers"]:
                # In case there are multiple containers, only update the expected UI one
                if container["name"] == "kagenti-ui-container":
                    image_name = container["image"].split(":")[0]
                    updated_tag = get_latest_tagged_version(
                        github_repo=config.UI_GIT_REPO,
                        fallback_version=config.UI_FALLBACK_VERSION,
                    )
                    console.log(
                        f"  Using image tag {updated_tag} for Kagenti UI deployment"
                    )
                    container["image"] = f"{image_name}:{updated_tag}"
    with tempfile.NamedTemporaryFile("w", delete=True, suffix=".yaml") as tmp_file:
        yaml.safe_dump_all(ui_yamls, tmp_file)
        tmp_path = tmp_file.name
        run_command(["kubectl", "apply", "-f", str(tmp_path)], "Installing Kagenti UI")

    run_command(
        [
            "kubectl",
            "label",
            "ns",
            "kagenti-system",
            "shared-gateway-access=true",
            "--overwrite",
        ],
        "Sharing gateway access for UI",
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
