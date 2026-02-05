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

"""Kagenti common utilities package."""

# Kubernetes utilities
from .kube import (
    is_running_in_cluster,
    load_kubernetes_config,
)

# Keycloak utilities
from .keycloak import (
    read_keycloak_credentials,
)

# Configuration utilities
from .config import (
    get_required_env,
    get_optional_env,
    configure_ssl_verification,
)

__all__ = [
    # Kubernetes
    "is_running_in_cluster",
    "load_kubernetes_config",
    # Keycloak
    "read_keycloak_credentials",
    # Configuration
    "get_required_env",
    "get_optional_env",
    "configure_ssl_verification",
]
