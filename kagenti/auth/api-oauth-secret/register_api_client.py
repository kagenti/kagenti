# Copyright 2025 IBM Corp.
# Licensed under the Apache License, Version 2.0

"""
Register a confidential OAuth2 client in Keycloak for API access.

This script creates the `kagenti-api` client for external services to
authenticate via Client Credentials Grant. The client credentials are
stored in a Kubernetes secret for programmatic API access.

WARNING: The `kagenti-api` client is a shared credential intended for
testing and development only. For production, each external client should
have its own Keycloak service account.
"""

import base64
import logging
import os
import sys
import time
from typing import Optional, Tuple

from keycloak import KeycloakAdmin, KeycloakPostError
from kubernetes import client, config

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Constants
DEFAULT_KEYCLOAK_NAMESPACE = "keycloak"
DEFAULT_ADMIN_SECRET_NAME = "keycloak-initial-admin"
DEFAULT_ADMIN_USERNAME_KEY = "username"
DEFAULT_ADMIN_PASSWORD_KEY = "password"
DEFAULT_CLIENT_ID = "kagenti-api"
DEFAULT_SECRET_NAME = "kagenti-api-oauth-secret"

# RBAC Role Constants - must match backend app/core/auth.py
ROLE_VIEWER = "kagenti-viewer"
ROLE_OPERATOR = "kagenti-operator"
ROLE_ADMIN = "kagenti-admin"
RBAC_ROLES = [ROLE_VIEWER, ROLE_OPERATOR, ROLE_ADMIN]


def get_required_env(key: str) -> str:
    """Get a required environment variable or exit."""
    value = os.environ.get(key)
    if value is None or value == "":
        logger.error(f'Required environment variable: "{key}" is not set')
        sys.exit(1)
    return value


def get_optional_env(key: str, default: Optional[str] = None) -> Optional[str]:
    """Get an optional environment variable with optional default."""
    return os.environ.get(key, default)


def is_running_in_cluster() -> bool:
    """Check if running inside a Kubernetes cluster."""
    return bool(os.getenv("KUBERNETES_SERVICE_HOST"))


def read_keycloak_credentials(
    v1_client: client.CoreV1Api,
    secret_name: str,
    namespace: str,
    username_key: str,
    password_key: str,
) -> Tuple[str, str]:
    """Read Keycloak admin credentials from a Kubernetes secret."""
    try:
        logger.info("Reading Keycloak admin credentials from Kubernetes secret")
        secret = v1_client.read_namespaced_secret(secret_name, namespace)

        if username_key not in secret.data:
            raise ValueError(f"Secret missing key '{username_key}'")
        if password_key not in secret.data:
            raise ValueError(f"Secret missing key '{password_key}'")

        username = base64.b64decode(secret.data[username_key]).decode("utf-8").strip()
        password = base64.b64decode(secret.data[password_key]).decode("utf-8").strip()

        logger.info("Successfully read credentials from secret")
        return username, password
    except Exception as e:
        logger.error(f"Could not read Keycloak admin secret: {e}")
        raise


def configure_ssl_verification(ssl_cert_file: Optional[str]) -> Optional[str]:
    """Configure SSL verification based on certificate file availability."""
    if ssl_cert_file and os.path.exists(ssl_cert_file):
        logger.info(f"Using SSL certificate file: {ssl_cert_file}")
        return ssl_cert_file

    logger.info("Using system CA bundle for SSL verification")
    return None


def connect_to_keycloak(
    server_url: str,
    username: str,
    password: str,
    realm: str,
    verify_ssl: Optional[str],
    timeout: int = 120,
    interval: int = 5,
) -> Optional[KeycloakAdmin]:
    """Connect to Keycloak with retry logic."""
    logger.info("Attempting to connect to Keycloak...")
    start_time = time.monotonic()

    while time.monotonic() - start_time < timeout:
        try:
            keycloak_admin = KeycloakAdmin(
                server_url=server_url,
                username=username,
                password=password,
                realm_name=realm,
                user_realm_name="master",
                verify=verify_ssl if verify_ssl is not None else True,
            )
            # Verify connection
            keycloak_admin.get_server_info()
            logger.info("Successfully connected to Keycloak")
            return keycloak_admin

        except Exception as e:
            elapsed = int(time.monotonic() - start_time)
            logger.info(
                f"Connection failed: {e}. Retrying in {interval}s... "
                f"({elapsed}s/{timeout}s elapsed)"
            )
            time.sleep(interval)

    logger.error(f"Failed to connect to Keycloak after {timeout} seconds")
    return None


def register_confidential_client(
    keycloak_admin: KeycloakAdmin,
    client_id: str,
) -> Tuple[str, str]:
    """
    Register a confidential client with service account for Client Credentials Grant.

    If the client already exists, updates its configuration to ensure it matches
    the expected settings for Client Credentials Grant.

    Args:
        keycloak_admin: Connected KeycloakAdmin instance
        client_id: The client ID to register

    Returns:
        Tuple of (internal_client_id, client_secret)
    """
    client_payload = {
        "clientId": client_id,
        "name": client_id,
        "description": "Kagenti API - Confidential client for programmatic access",
        "enabled": True,
        "publicClient": False,  # Confidential client
        "serviceAccountsEnabled": True,  # Enable service account for Client Credentials
        "standardFlowEnabled": False,  # No authorization code flow
        "implicitFlowEnabled": False,
        "directAccessGrantsEnabled": False,  # No password grant
        "protocol": "openid-connect",
        "fullScopeAllowed": True,
    }

    try:
        internal_client_id = keycloak_admin.create_client(client_payload)
        logger.info(f'Created confidential client "{client_id}"')
    except KeycloakPostError as e:
        # Check if client already exists
        if hasattr(e, "response_code") and e.response_code == 409:
            logger.info(
                f'Client "{client_id}" already exists, updating configuration...'
            )
            internal_client_id = keycloak_admin.get_client_id(client_id)
            # Update existing client to ensure correct configuration
            keycloak_admin.update_client(internal_client_id, client_payload)
            logger.info(f'Updated client "{client_id}" configuration')
        else:
            raise

    # Get client secret
    secrets = keycloak_admin.get_client_secrets(internal_client_id)
    client_secret = secrets.get("value", "")

    if not client_secret:
        # Regenerate secret if empty
        logger.info("Regenerating client secret...")
        keycloak_admin.generate_client_secrets(internal_client_id)
        secrets = keycloak_admin.get_client_secrets(internal_client_id)
        client_secret = secrets.get("value", "")

    return internal_client_id, client_secret


def create_realm_roles(
    keycloak_admin: KeycloakAdmin,
    roles: list[str],
) -> None:
    """Create RBAC realm roles in Keycloak.

    Creates the specified roles in the current realm. Roles that already
    exist are skipped without error.

    Args:
        keycloak_admin: Connected KeycloakAdmin instance
        roles: List of role names to create
    """
    for role_name in roles:
        try:
            keycloak_admin.create_realm_role(
                payload={
                    "name": role_name,
                    "description": f"Kagenti RBAC role: {role_name}",
                },
                skip_exists=False,
            )
            logger.info(f'Created realm role "{role_name}"')
        except KeycloakPostError as e:
            if hasattr(e, "response_code") and e.response_code == 409:
                logger.info(f'Realm role "{role_name}" already exists')
            else:
                logger.warning(f'Failed to create realm role "{role_name}": {e}')
        except Exception as e:
            logger.warning(f'Unexpected error creating realm role "{role_name}": {e}')


def assign_role_to_user(
    keycloak_admin: KeycloakAdmin,
    username: str,
    role_name: str,
) -> None:
    """Assign a realm role to a user.

    Args:
        keycloak_admin: Connected KeycloakAdmin instance
        username: The username to assign the role to
        role_name: The realm role name to assign
    """
    try:
        users = keycloak_admin.get_users({"username": username, "exact": True})
        if not users:
            logger.warning(
                f'Target user not found in realm, cannot assign role "{role_name}"'
            )
            return

        user_id = users[0]["id"]
        role = keycloak_admin.get_realm_role(role_name)
        if not role:
            logger.warning(
                f'Role "{role_name}" not found, cannot assign to target user'
            )
            return

        keycloak_admin.assign_realm_roles(user_id=user_id, roles=[role])
        logger.info(f'Assigned role "{role_name}" to target user')
    except Exception as e:
        logger.warning(
            f'Could not assign role "{role_name}" to target user: {type(e).__name__}'
        )


def assign_role_to_service_account(
    keycloak_admin: KeycloakAdmin,
    internal_client_id: str,
    role_name: str,
) -> None:
    """Assign a realm role to the client's service account.

    Raises:
        RuntimeError: If role assignment fails (role not found or API error)
    """
    # Get service account user for the client
    service_account_user = keycloak_admin.get_client_service_account_user(
        internal_client_id
    )
    user_id = service_account_user["id"]

    # Get the realm role (created by create_realm_roles earlier in this job)
    role = keycloak_admin.get_realm_role(role_name)
    if not role:
        raise RuntimeError(f'Role "{role_name}" not found in realm.')

    # Assign role to service account
    keycloak_admin.assign_realm_roles(user_id=user_id, roles=[role])
    logger.info(f'Assigned role "{role_name}" to service account')


def create_or_update_secret(
    v1_client: client.CoreV1Api,
    namespace: str,
    secret_name: str,
    data: dict,
) -> None:
    """Create or update a Kubernetes secret."""
    try:
        secret_body = client.V1Secret(
            api_version="v1",
            kind="Secret",
            metadata=client.V1ObjectMeta(
                name=secret_name,
                labels={
                    "app": "kagenti",
                    "kagenti.io/type": "api-credentials",
                },
            ),
            type="Opaque",
            string_data=data,
        )
        v1_client.create_namespaced_secret(namespace=namespace, body=secret_body)
        logger.info(f"Created Kubernetes secret in namespace '{namespace}'")
    except client.exceptions.ApiException as e:
        if e.status == 409:
            # Secret exists, update it
            v1_client.patch_namespaced_secret(
                name=secret_name,
                namespace=namespace,
                body={"stringData": data},
            )
            logger.info(f"Updated Kubernetes secret in namespace '{namespace}'")
        else:
            raise


def main() -> None:
    """Main execution function."""
    try:
        # Load configuration
        keycloak_url = get_required_env("KEYCLOAK_URL")
        keycloak_realm = get_required_env("KEYCLOAK_REALM")
        target_namespace = get_required_env("TARGET_NAMESPACE")

        keycloak_namespace = get_optional_env(
            "KEYCLOAK_NAMESPACE", DEFAULT_KEYCLOAK_NAMESPACE
        )
        admin_secret_name = get_optional_env(
            "KEYCLOAK_ADMIN_SECRET_NAME", DEFAULT_ADMIN_SECRET_NAME
        )
        admin_username_key = get_optional_env(
            "KEYCLOAK_ADMIN_USERNAME_KEY", DEFAULT_ADMIN_USERNAME_KEY
        )
        admin_password_key = get_optional_env(
            "KEYCLOAK_ADMIN_PASSWORD_KEY", DEFAULT_ADMIN_PASSWORD_KEY
        )
        client_id = get_optional_env("CLIENT_ID", DEFAULT_CLIENT_ID)
        secret_name = get_optional_env("SECRET_NAME", DEFAULT_SECRET_NAME)
        ssl_cert_file = get_optional_env("SSL_CERT_FILE")
        role_name = get_optional_env("SERVICE_ACCOUNT_ROLE", ROLE_OPERATOR)

        # Connect to Kubernetes
        if is_running_in_cluster():
            config.load_incluster_config()
        else:
            config.load_kube_config()

        v1_client = client.CoreV1Api()

        # Read Keycloak admin credentials
        admin_username, admin_password = read_keycloak_credentials(
            v1_client,
            admin_secret_name,
            keycloak_namespace,
            admin_username_key,
            admin_password_key,
        )

        # Configure SSL
        verify_ssl = configure_ssl_verification(ssl_cert_file)

        # Connect to Keycloak
        keycloak_admin = connect_to_keycloak(
            server_url=keycloak_url,
            username=admin_username,
            password=admin_password,
            realm=keycloak_realm,
            verify_ssl=verify_ssl,
        )

        if not keycloak_admin:
            logger.error("Failed to connect to Keycloak")
            sys.exit(1)

        # Create RBAC realm roles for API authorization
        create_realm_roles(keycloak_admin, RBAC_ROLES)

        # Assign kagenti-admin to the Keycloak admin user so the default
        # admin has full platform access via the UI
        assign_role_to_user(keycloak_admin, admin_username, ROLE_ADMIN)

        # Register confidential client
        internal_client_id, client_secret = register_confidential_client(
            keycloak_admin, client_id
        )

        # Assign role to service account
        try:
            assign_role_to_service_account(
                keycloak_admin, internal_client_id, role_name
            )
        except RuntimeError as exc:
            logger.error(
                "Failed to assign role '%s' to service account for client '%s': %s. "
                "Verify that the role exists in realm '%s' and that the admin user "
                "has sufficient permissions.",
                role_name,
                client_id,
                exc,
                keycloak_realm,
            )
            raise

        # Construct token endpoint
        token_endpoint = (
            f"{keycloak_url}/realms/{keycloak_realm}/protocol/openid-connect/token"
        )

        # Create Kubernetes secret with credentials
        secret_data = {
            "CLIENT_ID": client_id,
            "CLIENT_SECRET": client_secret,
            "TOKEN_ENDPOINT": token_endpoint,
            "KEYCLOAK_URL": keycloak_url,
            "KEYCLOAK_REALM": keycloak_realm,
        }

        create_or_update_secret(v1_client, target_namespace, secret_name, secret_data)

        logger.info("API OAuth secret creation completed successfully")
        logger.info(f"  Client ID: {client_id}")
        logger.info(f"  Namespace: {target_namespace}")
        logger.info(f"  Token endpoint: {token_endpoint}")

    except Exception as e:
        logger.exception(f"Unexpected error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
