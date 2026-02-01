# Copyright 2024 Kagenti Authors
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

"""
MLflow Experiment Initialization Script.

Creates MLflow experiments for each agent namespace with proper RBAC permissions.
This script runs as a post-install hook after Kagenti is deployed.

Usage:
    python mlflow_experiment_init.py

Environment Variables:
    MLFLOW_TRACKING_URI: MLflow server URL (required)
    KEYCLOAK_URL: Keycloak server URL (required)
    KEYCLOAK_REALM: Keycloak realm (default: demo)
    CLIENT_ID: OAuth client ID for MLflow access
    CLIENT_SECRET: OAuth client secret
    NAMESPACES: Comma-separated list of namespaces to create experiments for
    SSL_CERT_FILE: Path to CA certificate for TLS verification
"""

import logging
import os
import sys

import httpx

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def get_keycloak_token(
    keycloak_url: str,
    realm: str,
    client_id: str,
    client_secret: str,
    verify_ssl: bool = True,
) -> str | None:
    """Get access token from Keycloak using client credentials flow."""
    token_url = f"{keycloak_url}/realms/{realm}/protocol/openid-connect/token"

    try:
        response = httpx.post(
            token_url,
            data={
                "grant_type": "client_credentials",
                "client_id": client_id,
                "client_secret": client_secret,
            },
            verify=verify_ssl,
            timeout=30.0,
        )
        response.raise_for_status()
        return response.json().get("access_token")
    except httpx.HTTPError as e:
        logger.error(f"Failed to get Keycloak token: {e}")
        return None


def create_experiment(
    mlflow_url: str,
    experiment_name: str,
    access_token: str | None = None,
    verify_ssl: bool = True,
    tags: dict | None = None,
) -> str | None:
    """Create MLflow experiment if it doesn't exist."""
    headers = {}
    if access_token:
        headers["Authorization"] = f"Bearer {access_token}"

    # First check if experiment exists
    try:
        response = httpx.get(
            f"{mlflow_url}/api/2.0/mlflow/experiments/get-by-name",
            params={"experiment_name": experiment_name},
            headers=headers,
            verify=verify_ssl,
            timeout=30.0,
        )
        if response.status_code == 200:
            exp_id = response.json().get("experiment", {}).get("experiment_id")
            logger.info(f"Experiment '{experiment_name}' already exists (id: {exp_id})")
            return exp_id
    except httpx.HTTPError:
        pass  # Experiment doesn't exist, create it

    # Create experiment
    try:
        payload = {"name": experiment_name}
        if tags:
            payload["tags"] = [{"key": k, "value": v} for k, v in tags.items()]

        response = httpx.post(
            f"{mlflow_url}/api/2.0/mlflow/experiments/create",
            json=payload,
            headers=headers,
            verify=verify_ssl,
            timeout=30.0,
        )
        response.raise_for_status()
        exp_id = response.json().get("experiment_id")
        logger.info(f"Created experiment '{experiment_name}' (id: {exp_id})")
        return exp_id
    except httpx.HTTPError as e:
        logger.error(f"Failed to create experiment '{experiment_name}': {e}")
        if hasattr(e, "response") and e.response is not None:
            logger.error(f"Response: {e.response.text}")
        return None


def set_experiment_permission(
    mlflow_url: str,
    experiment_id: str,
    username: str,
    permission: str,
    access_token: str | None = None,
    verify_ssl: bool = True,
) -> bool:
    """Set permission on experiment for a user/group."""
    headers = {}
    if access_token:
        headers["Authorization"] = f"Bearer {access_token}"

    try:
        response = httpx.post(
            f"{mlflow_url}/api/2.0/mlflow/experiments/permissions/create",
            json={
                "experiment_id": experiment_id,
                "username": username,
                "permission": permission,
            },
            headers=headers,
            verify=verify_ssl,
            timeout=30.0,
        )
        if response.status_code in (200, 201):
            logger.info(
                f"Set permission {permission} for {username} on experiment {experiment_id}"
            )
            return True
        elif response.status_code == 409:
            # Permission already exists, try update
            response = httpx.patch(
                f"{mlflow_url}/api/2.0/mlflow/experiments/permissions/update",
                json={
                    "experiment_id": experiment_id,
                    "username": username,
                    "permission": permission,
                },
                headers=headers,
                verify=verify_ssl,
                timeout=30.0,
            )
            return response.status_code == 200
        return False
    except httpx.HTTPError as e:
        logger.warning(f"Failed to set permission: {e}")
        return False


def main():
    """Main entry point."""
    # Get configuration from environment
    mlflow_url = os.environ.get("MLFLOW_TRACKING_URI", "http://mlflow:5000")
    keycloak_url = os.environ.get("KEYCLOAK_URL")
    keycloak_realm = os.environ.get("KEYCLOAK_REALM", "demo")
    client_id = os.environ.get("CLIENT_ID", "mlflow")
    client_secret = os.environ.get("CLIENT_SECRET")
    namespaces_str = os.environ.get("NAMESPACES", "team1,team2")
    ssl_cert_file = os.environ.get("SSL_CERT_FILE")

    # Parse namespaces
    namespaces = [ns.strip() for ns in namespaces_str.split(",") if ns.strip()]

    if not namespaces:
        logger.error("No namespaces specified")
        return 1

    logger.info(f"MLflow URL: {mlflow_url}")
    logger.info(f"Namespaces to initialize: {namespaces}")

    # Determine SSL verification
    verify_ssl = True
    if ssl_cert_file and os.path.exists(ssl_cert_file):
        verify_ssl = ssl_cert_file
        logger.info(f"Using SSL certificate: {ssl_cert_file}")

    # Get Keycloak token if credentials provided
    access_token = None
    if keycloak_url and client_secret:
        logger.info(f"Getting Keycloak token from {keycloak_url}")
        access_token = get_keycloak_token(
            keycloak_url,
            keycloak_realm,
            client_id,
            client_secret,
            verify_ssl=verify_ssl if isinstance(verify_ssl, bool) else True,
        )
        if access_token:
            logger.info("Successfully obtained Keycloak token")
        else:
            logger.warning("Failed to get Keycloak token, proceeding without auth")

    # Create experiments for each namespace
    success_count = 0
    for namespace in namespaces:
        logger.info(f"Initializing experiment for namespace: {namespace}")

        # Create experiment with namespace as name
        exp_id = create_experiment(
            mlflow_url,
            namespace,
            access_token=access_token,
            verify_ssl=verify_ssl,
            tags={
                "kagenti.io/namespace": namespace,
                "kagenti.io/type": "agent-traces",
                "description": f"LLM traces for agents in {namespace} namespace",
            },
        )

        if exp_id:
            success_count += 1
            # Set group permission (group name = namespace)
            # The @prefix indicates a group in mlflow-oidc-auth
            set_experiment_permission(
                mlflow_url,
                exp_id,
                f"@{namespace}",  # Group permission
                "MANAGE",
                access_token=access_token,
                verify_ssl=verify_ssl,
            )

    logger.info(
        f"Experiment initialization complete: {success_count}/{len(namespaces)} succeeded"
    )
    return 0 if success_count == len(namespaces) else 1


if __name__ == "__main__":
    sys.exit(main())
