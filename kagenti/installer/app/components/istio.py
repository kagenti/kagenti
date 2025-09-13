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

from ..utils import run_command


def install(**kwargs):
    """Installs all Istio components using the official Helm charts."""
    run_command(
        [
            "helm",
            "repo",
            "add",
            "istio",
            "https://istio-release.storage.googleapis.com/charts",
        ],
        "Adding Istio Helm repo",
    )
    run_command(["helm", "repo", "update"], "Updating Helm repos")
    run_command(
        [
            "helm",
            "upgrade",
            "--install",
            "istio-base",
            "istio/base",
            "-n",
            "istio-system",
            "--create-namespace",
            "--wait",
        ],
        "Installing Istio base",
    )
    run_command(
        [
            "kubectl",
            "apply",
            "-f",
            "https://github.com/kubernetes-sigs/gateway-api/releases/download/v1.1.0/standard-install.yaml",
        ],
        "Installing Kubernetes Gateway API",
    )
    run_command(
        [
            "helm",
            "upgrade",
            "--install",
            "istiod",
            "istio/istiod",
            "-n",
            "istio-system",
            "--set",
            "profile=ambient",
            "--wait",
        ],
        "Installing Istiod (ambient profile)",
    )
    run_command(
        [
            "helm",
            "upgrade",
            "--install",
            "istio-cni",
            "istio/cni",
            "-n",
            "istio-system",
            "--set",
            "profile=ambient",
            "--wait",
        ],
        "Installing Istio CNI",
    )
    run_command(
        [
            "helm",
            "upgrade",
            "--install",
            "ztunnel",
            "istio/ztunnel",
            "-n",
            "istio-system",
            "--wait",
        ],
        "Installing Ztunnel",
    )

    # Wait for all Istio component rollouts to complete
    run_command(
        ["kubectl", "rollout", "status", "-n", "istio-system", "daemonset/ztunnel"],
        "Waiting for ztunnel rollout",
    )
    run_command(
        [
            "kubectl",
            "rollout",
            "status",
            "-n",
            "istio-system",
            "daemonset/istio-cni-node",
        ],
        "Waiting for Istio CNI rollout",
    )
    run_command(
        ["kubectl", "rollout", "status", "-n", "istio-system", "deployment/istiod"],
        "Waiting for Istiod rollout",
    )
