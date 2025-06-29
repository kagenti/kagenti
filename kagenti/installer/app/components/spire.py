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
from ..utils import run_command


def install():
    """Installs all SPIRE components using the official Helm charts."""
    run_command(
        [
            "helm",
            "upgrade",
            "--install",
            "spire-crds",
            "spire-crds",
            "-n",
            "spire-mgmt",
            "--repo",
            "https://spiffe.github.io/helm-charts-hardened/",
            "--create-namespace",
            "--wait",
        ],
        "Installing SPIRE CRDs",
    )
    run_command(
        [
            "pwd",
        ],
        "Print working directory",
    )
    run_command(
        [
            "helm",
            "upgrade",
            "--install",
            "spire",
            "spire",
            "-n",
            "spire-mgmt",
            "--repo",
            "https://spiffe.github.io/helm-charts-hardened/",
            "-f",
            str(config.RESOURCES_DIR / "helm-values.yaml"),
            "--wait",
        ],
        "Installing SPIRE Server",
    )
