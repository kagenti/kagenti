# This file has been modified with the assistance of Bob
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

"""Kubernetes utility functions for Kagenti."""

import os
from kubernetes import config


def is_running_in_cluster() -> bool:
    """Check if running inside a Kubernetes cluster.
    
    Returns:
        True if running in a Kubernetes cluster, False otherwise.
    """
    return bool(os.getenv("KUBERNETES_SERVICE_HOST"))


def load_kubernetes_config() -> None:
    """Load Kubernetes configuration based on environment.
    
    Loads in-cluster config if running in a cluster, otherwise loads
    from kubeconfig file.
    """
    if is_running_in_cluster():
        config.load_incluster_config()
    else:
        config.load_kube_config()

