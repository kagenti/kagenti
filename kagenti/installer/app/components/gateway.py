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
from ..utils import run_command, wait_for_deployment

# TODO - configure namespace(s) where this should be deployed - currently is in default


def install(**kwargs):
    """Installs the Istio ingress and egress gateways."""
    run_command(
        ["kubectl", "apply", "-f", str(config.RESOURCES_DIR / "http-gateway.yaml")],
        "Creating Istio ingress gateway",
    )
    run_command(
        ["kubectl", "apply", "-f", str(config.RESOURCES_DIR / "gateway-nodeport.yaml")],
        "Adding NodePort service for gateway",
    )
    run_command(
        [
            "kubectl",
            "annotate",
            "gateway",
            "http",
            "networking.istio.io/service-type=ClusterIP",
            f"--namespace={config.OPERATOR_NAMESPACE}",
            "--overwrite",
        ],
        "Annotating gateway service type",
    )
    run_command(
        ["kubectl", "apply", "-f", str(config.RESOURCES_DIR / "gateway-waypoint.yaml")],
        "Adding egress waypoint gateway",
    )

    # Wait for deployment to be created and ready
    if wait_for_deployment("default", "waypoint"):
        run_command(
            ["kubectl", "rollout", "status", "-n", "default", "deployment/waypoint"],
            "Waiting for waypoint gateway rollout",
        )
    else:
        print(
            "Failed to find the 'waypoint' deployment within the expected time frame."
        )
