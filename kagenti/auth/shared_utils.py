import json
import logging
from typing import Dict, Any

from keycloak import KeycloakAdmin, KeycloakPostError

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


class KeycloakOperationError(Exception):
    """Raised when Keycloak operations fail."""

    pass


def register_client(
    keycloak_admin: KeycloakAdmin, client_id: str, client_payload: Dict[str, Any]
) -> str:
    """Register a client in Keycloak or retrieve existing client ID.

    Args:
        keycloak_admin: Keycloak admin client
        client_id: Desired client ID
        client_payload: Client configuration payload

    Returns:
        Internal client ID

    Raises:
        KeycloakOperationError: If client cannot be created or retrieved
    """
    try:
        internal_client_id = keycloak_admin.create_client(client_payload)
        logger.info(f'Created Keycloak client "{client_id}": {internal_client_id}')
        return internal_client_id
    except KeycloakPostError as e:
        logger.debug(f'Keycloak client creation error for "{client_id}": {e}')

        try:
            error_json = json.loads(e.error_message)
            if error_json.get("errorMessage") == f"Client {client_id} already exists":
                internal_client_id = keycloak_admin.get_client_id(client_id)
                logger.info(
                    f'Using existing Keycloak client "{client_id}": {internal_client_id}'
                )
                return internal_client_id
        except (json.JSONDecodeError, KeyError, TypeError):
            pass  # Error message format doesn't match expected pattern

        error_msg = f'Failed to create or retrieve Keycloak client "{client_id}": {e}'
        logger.error(error_msg)
        raise KeycloakOperationError(error_msg) from e
