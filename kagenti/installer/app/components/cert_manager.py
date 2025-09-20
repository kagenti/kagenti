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

from pathlib import Path
from .. import config
from ..utils import run_command
from ..ocp_utils import verify_operator_installation

def install(use_openshift_cluster: bool = False, **kwargs):
    if use_openshift_cluster:
        _install_on_openshift()
    else:
        _install_on_k8s()


def _install_on_k8s():
    """Installs cert-manager into the Kubernetes cluster."""
    # Install cert-manager
    run_command(
        [
            "kubectl", 
            "apply", 
            "-f", 
            "https://github.com/cert-manager/cert-manager/releases/download/v1.17.2/cert-manager.yaml"
        ],
        "Installing Cert Manager",
    )
    
    # Wait for cert-manager deployments to be ready
    _wait_for_cert_manager_deployments()


def _wait_for_cert_manager_deployments():
    """Wait for all cert-manager deployments to be ready."""
    deployments = [
        "cert-manager",
        "cert-manager-cainjector", 
        "cert-manager-webhook"
    ]
    
    wait_timeout_seconds = 300
    
    for deployment in deployments:
        run_command(
            [
                "kubectl",
                "wait",
                "--for=condition=Available",
                f"deployment/{deployment}",
                "-n",
                "cert-manager",
                f"--timeout={wait_timeout_seconds}s"
            ],
            f"Waiting for deployment/{deployment} in namespace cert-manager",
        )

def _install_on_openshift():
    """Installs Cert Manager using OpenShift Cert Manager Operator."""
    namespace = "cert-manager-operator"
    subscription = "openshift-cert-manager-operator"
    deploy_path: Path = config.RESOURCES_DIR / "ocp" / "cert-manager-operator.yaml"

    run_command(
        ["kubectl", "apply", "-n", namespace, "-f", deploy_path],
        "Installing OpenShift Cert Manager Operator"
    )

    verify_operator_installation(
        subscription_name=subscription,
        namespace=namespace,
    )

