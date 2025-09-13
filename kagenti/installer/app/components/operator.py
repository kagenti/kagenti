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

import subprocess
import re
from .. import config
from ..utils import run_command


def get_latest_operator_version(fallback="0.2.0-alpha.4") -> str:
    """Fetches the latest version tag of the Platform Operator from GitHub releases.

    Args:
        fallback (str): The fallback version to return if fetching fails.

    Returns:
        str: The latest version tag or the fallback version.
    """
    try:
        result = subprocess.run(
            [
                "git", "ls-remote", "--tags", "--sort=-version:refname",
                "https://github.com/kagenti/kagenti-operator.git",
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
                    return tag.lstrip('v')

        print("Could not find tag_name in the response. Using fallback version.")
        return fallback
    except subprocess.CalledProcessError as e:
        print(f"Error fetching latest version: {e}. Using fallback version.")
        return fallback
    

def install(**kwargs):
    """Installs the Platform Operator using its Helm chart."""

    operator_version = get_latest_operator_version()
    print(f"Using Platform Operator version: {operator_version}")

    run_command(
        [
            "helm",
            "upgrade",
            "--install",
            "kagenti-platform-operator",
            "oci://ghcr.io/kagenti/kagenti-operator/kagenti-platform-operator-chart",
            "--create-namespace",
            "--namespace",
            config.OPERATOR_NAMESPACE,
            "--version",
            operator_version,
            "--set",
            "controllerManager.container.image.tag="+operator_version
        ],
        "Installing the Platform Operator",
    )
