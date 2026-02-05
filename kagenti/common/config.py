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

"""Configuration utility functions for Kagenti."""

import os
import logging
from typing import Optional


logger = logging.getLogger(__name__)


def get_required_env(key: str) -> str:
    """Get a required environment variable or raise ValueError.

    Args:
        key: Environment variable name

    Returns:
        The environment variable value

    Raises:
        ValueError: If the environment variable is not set or is empty
    """
    value = os.environ.get(key)
    if value is None or value == "":
        raise ValueError(f'Required environment variable: "{key}" is not set')
    return value


def get_optional_env(key: str, default: Optional[str] = None) -> Optional[str]:
    """Get an optional environment variable with optional default.

    Args:
        key: Environment variable name
        default: Default value if not set

    Returns:
        The environment variable value or default
    """
    return os.environ.get(key, default)


def configure_ssl_verification(ssl_cert_file: Optional[str]) -> Optional[str]:
    """Configure SSL verification based on certificate file availability.

    Behavior:
    - If an explicit SSL_CERT_FILE path is provided and exists, return that path.
    - Otherwise return None, which indicates to callers that the default
      system CA bundle (requests/certifi) should be used.

    Returning None avoids incorrectly defaulting to the Kubernetes
    serviceaccount CA (which is for the API server) when verifying
    external TLS endpoints such as OpenShift routes.

    Args:
        ssl_cert_file: Path to SSL certificate file

    Returns:
        Path to cert file if available and exists, otherwise None
    """
    if ssl_cert_file:
        if os.path.exists(ssl_cert_file):
            logger.info(f"Using SSL certificate file: {ssl_cert_file}")
            return ssl_cert_file
        else:
            logger.warning(
                f"Provided SSL_CERT_FILE '{ssl_cert_file}' does not exist; falling back to system CA bundle"
            )

    # No explicit certificate provided or file missing: use system CA bundle
    logger.info("No SSL_CERT_FILE provided - using system CA bundle for verification")
    return None
