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

from .. import config
from ..utils import get_latest_tagged_version, run_command


def install(**kwargs):
    """Installs the Platform Operator using its Helm chart."""

    # Operator version strips v from tag
    operator_version = get_latest_tagged_version(
        github_repo=config.OPERATOR_GIT_REPO,
        fallback_version=config.OPERATOR_FALLBACK_VERSION,
    ).lstrip("v")
    print(f"Using Kagenti Operator version: {operator_version}")

    run_command(
        [
            "helm",
            "upgrade",
            "--install",
            "kagenti-operator",
            "oci://ghcr.io/kagenti/kagenti-operator/kagenti-operator-chart",
            "--create-namespace",
            "--namespace",
            config.OPERATOR_NAMESPACE,
            "--version",
            operator_version,
            "--set",
            "controllerManager.container.image.tag=" + operator_version,
        ],
        "Installing the Kagenti Operator",
    )
