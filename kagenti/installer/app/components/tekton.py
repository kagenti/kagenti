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
from .. import config
from ..utils import console, run_command


def install(**kwargs):
    """Installs Tekton Pipelines from its official release YAML."""
    tekton_url = f"https://storage.googleapis.com/tekton-releases/pipeline/previous/{config.TEKTON_VERSION}/release.yaml"
    run_command(
        ["kubectl", "apply", "--filename", tekton_url], "Installing Tekton Pipelines"
    )

    # Patch Tekton Pipelines to enable step actions for buildpacks
    patch = [
        "kubectl",
        "patch",
        "configmap",
        "feature-flags",
        "-n",
        "tekton-pipelines",
        "--type",
        "merge",
        "-p",
        '{"data":{"enable-step-actions":"true"}}',
    ]
    run_command(patch, "Patching Tekton Pipelines to enable step actions")
    namespaces_str = os.getenv("AGENT_NAMESPACES")
    if not namespaces_str:
        console.log(
            "[yellow]AGENT_NAMESPACES not set. Skipping buildpacks configuration.[/yellow]"
        )
        return

    """Installs buildpacks phases for Tekton."""
    buildpacks_url = f"https://raw.githubusercontent.com/tektoncd/catalog/main/task/buildpacks-phases/{config.BUILDPACKS_VERSION}/buildpacks-phases.yaml"

    agent_namespaces = [ns.strip() for ns in namespaces_str.split(",") if ns.strip()]

    for ns in agent_namespaces:
        run_command(
            ["kubectl", "apply", "--filename", buildpacks_url, "--namespace", ns],
            f"Installing Tekton Buildpacks Phases in namespace {ns}",
        )
