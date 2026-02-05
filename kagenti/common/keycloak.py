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

"""Keycloak utility functions for Kagenti."""

import base64
import logging
from typing import Tuple
from kubernetes import client
from kubernetes.client.rest import ApiException


logger = logging.getLogger(__name__)


def read_keycloak_credentials(
    v1_api: client.CoreV1Api,
    secret_name: str,
    namespace: str,
    username_key: str,
    password_key: str,
) -> Tuple[str, str]:
    """Read Keycloak admin credentials from a Kubernetes secret.

    Args:
        v1_api: Kubernetes CoreV1Api client
        secret_name: Name of the secret
        namespace: Namespace where secret exists
        username_key: Key in secret data for username
        password_key: Key in secret data for password

    Returns:
        Tuple of (username, password)

    Raises:
        ApiException: If secret cannot be read
        ValueError: If required keys are missing from secret
    """
    try:
        logger.info(
            f"Reading Keycloak admin credentials from secret {secret_name} in namespace {namespace}"
        )
        secret = v1_api.read_namespaced_secret(secret_name, namespace)

        if username_key not in secret.data:
            raise ValueError(
                f"Secret {secret_name} in namespace {namespace} missing key '{username_key}'"
            )
        if password_key not in secret.data:
            raise ValueError(
                f"Secret {secret_name} in namespace {namespace} missing key '{password_key}'"
            )

        username = base64.b64decode(secret.data[username_key]).decode("utf-8").strip()
        password = base64.b64decode(secret.data[password_key]).decode("utf-8").strip()

        logger.info("Successfully read credentials from secret")
        return username, password
    except ApiException as e:
        error_msg = f"Could not read Keycloak admin secret {secret_name} in namespace {namespace}: {e}"
        logger.error(error_msg)
        raise
    except Exception as e:
        error_msg = f"Unexpected error reading secret: {e}"
        logger.error(error_msg)
        raise

