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


def install(**kwargs):
    """Installs the Kubernetes metrics server."""
    # Install metrics server
    run_command(
        [
            "kubectl",
            "apply",
            "-f",
            "https://github.com/kubernetes-sigs/metrics-server/releases/latest/download/components.yaml",
        ],
        "Installing Kubernetes metrics server",
    )

    # Patch metrics server to allow insecure TLS (needed for local development)
    run_command(
        [
            "kubectl",
            "patch",
            "-n",
            "kube-system",
            "deployment",
            "metrics-server",
            "--type=json",
            "-p",
            '[{"op":"add","path":"/spec/template/spec/containers/0/args/-","value":"--kubelet-insecure-tls"}]',
        ],
        "Patching metrics server to allow insecure TLS for kubelet communication",
    )

    # Wait for metrics server deployment to be ready
    run_command(
        [
            "kubectl",
            "wait",
            "--for=condition=Available",
            "deployment/metrics-server",
            "-n",
            "kube-system",
            "--timeout=300s",
        ],
        "Waiting for metrics server deployment to be ready",
    )
