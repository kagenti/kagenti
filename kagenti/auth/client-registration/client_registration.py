"""
client_registration.py

Registers a Keycloak client and stores its secret in a file.
Idempotent:
- Creates the client if it does not exist.
- If the client already exists, reuses it.
- Always retrieves and stores the client secret.
"""

import logging
import os
import jwt
from keycloak import KeycloakAdmin, KeycloakPostError

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

try:
    from kagenti.identity import get_identity_provider

    IDENTITY_AVAILABLE = True
    logger.info("Successfully imported kagenti.identity module")
except ImportError as e:
    # Fallback for environments where identity module is not available
    IDENTITY_AVAILABLE = False
    logger.warning("Failed to import kagenti.identity: %s", e)
    import sys

    logger.debug("Python path: %s", sys.path)


def get_env_var(name: str) -> str:
    """
    Fetch an environment variable or raise ValueError if missing.
    """
    value = os.environ.get(name)
    if not value:
        raise ValueError(f"Missing required environment variable: {name}")
    return value


def write_client_secret(
    keycloak_admin: KeycloakAdmin,
    internal_client_id: str,
    client_name: str,
    secret_file_path: str = "secret.txt",
) -> None:
    """
    Retrieve the secret for a Keycloak client and write it to a file.
    """
    try:
        # There will be a value field if client authentication is enabled
        # client authentication is enabled if "publicClient" is False
        secret = keycloak_admin.get_client_secrets(internal_client_id)["value"]
        logger.info('Successfully retrieved secret for client "%s"', client_name)
    except KeycloakPostError as e:
        logger.error("Could not retrieve secret for client '%s': %s", client_name, e)
        return

    try:
        with open(secret_file_path, "w") as f:
            f.write(secret)
        logger.info('Secret written to file: "%s"', secret_file_path)
    except OSError as ioe:
        logger.error("Error writing secret to file: %s", ioe)


# TODO: refactor this function so kagenti-client-registration image can use it
def register_client(keycloak_admin: KeycloakAdmin, client_id: str, client_payload):
    """
    Ensure a Keycloak client exists.
    Returns the internal client ID.
    """
    internal_client_id = keycloak_admin.get_client_id(f"{client_id}")
    if internal_client_id:
        logger.info(
            'Client "%s" already exists with ID: %s', client_id, internal_client_id
        )
        return internal_client_id

    # Create client
    internal_client_id = None
    try:
        internal_client_id = keycloak_admin.create_client(client_payload)

        logger.info('Created Keycloak client "%s": %s', client_id, internal_client_id)
        return internal_client_id
    except KeycloakPostError as e:
        logger.error('Could not create client "%s": %s', client_id, e)
        raise


def get_client_id() -> str:
    """
    Get the client ID from the workload identity.

    Uses the identity abstraction to support multiple providers.
    Requires explicit provider configuration via KAGENTI_IDENTITY_PROVIDER.
    """
    if not IDENTITY_AVAILABLE:
        raise RuntimeError(
            "Identity abstraction module not available. "
            "Ensure kagenti.identity module is installed and accessible."
        )

    try:
        # Use identity abstraction
        provider = get_identity_provider()
        identity = provider.get_current_identity()
        client_id = identity.get_subject()
        logger.info("Using %s identity provider", provider.get_name())
        return client_id
    except Exception as e:
        logger.error("Failed to use identity abstraction: %s", e)
        raise


client_id = get_client_id()

# The Keycloak URL is handled differently from the other env vars because unlike the others, it's intended to be optional
try:
    KEYCLOAK_URL = get_env_var("KEYCLOAK_URL")
except ValueError:
    logger.warning(
        'Expected environment variable "KEYCLOAK_URL" missing. Skipping client registration of %s.',
        client_id,
    )
    exit()


keycloak_admin = KeycloakAdmin(
    server_url=KEYCLOAK_URL,
    username=get_env_var("KEYCLOAK_ADMIN_USERNAME"),
    password=get_env_var("KEYCLOAK_ADMIN_PASSWORD"),
    realm_name=get_env_var("KEYCLOAK_REALM"),
    user_realm_name="master",
)

client_name = get_env_var("CLIENT_NAME")

internal_client_id = register_client(
    keycloak_admin,
    client_id,
    {
        "name": client_name,
        "clientId": client_id,
        "standardFlowEnabled": True,
        "directAccessGrantsEnabled": True,
        "fullScopeAllowed": False,
        "publicClient": False,  # Enable client authentication
        "attributes": {
            "standard.token.exchange.enabled": "true",  # Enable token exchange
        },
    },
)

try:
    secret_file_path = get_env_var("SECRET_FILE_PATH")
except ValueError:
    secret_file_path = "/shared/secret.txt"
logger.info(
    'Writing secret for client ID: "%s" (internal client ID: "%s") to file: "%s"',
    client_id,
    internal_client_id,
    secret_file_path,
)
write_client_secret(
    keycloak_admin,
    internal_client_id,
    client_name,
    secret_file_path=secret_file_path,
)

logger.info("Client registration complete.")
