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
    """Installs the OpenTelemetry Collector and Phoenix"""
    # Phoenix & Postgres
    run_command(
        [
            "kubectl",
            "apply",
            "-n",
            "kagenti-system",
            "-f",
            str(config.RESOURCES_DIR / "phoenix.yaml"),
        ],
        "Installing Phoenix",
    )
    run_command(
        [
            "kubectl",
            "rollout",
            "status",
            "-n",
            "kagenti-system",
            "statefulset/postgres",
        ],
        "Waiting for Postgres rollout",
    )
    run_command(
        ["kubectl", "rollout", "status", "-n", "kagenti-system", "statefulset/phoenix"],
        "Waiting for Phoenix rollout",
    )

    # OpenTelemetry Collector
    run_command(
        [
            "kubectl",
            "apply",
            "-n",
            "kagenti-system",
            "-f",
            str(config.RESOURCES_DIR / "otel-collector.yaml"),
        ],
        "Installing Otel Collector",
    )
    run_command(
        [
            "kubectl",
            "rollout",
            "status",
            "-n",
            "kagenti-system",
            "deployment/otel-collector",
        ],
        "Waiting for otel collector rollout",
    )
