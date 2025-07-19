import os
import logging

from keycloak import KeycloakAdmin, KeycloakPostError

KEYCLOAK_URL = os.environ.get('KEYCLOAK_URL')
KEYCLOAK_REALM = os.environ.get('KEYCLOAK_REALM')
KEYCLOAK_ADMIN_USERNAME = os.environ.get('KEYCLOAK_ADMIN_USERNAME')
KEYCLOAK_ADMIN_PASSWORD = os.environ.get('KEYCLOAK_ADMIN_PASSWORD')
CLIENT_NAME = os.environ.get('CLIENT_NAME')

if KEYCLOAK_URL is None:
    raise Exception('Expected environment variable "KEYCLOAK_URL"')
if KEYCLOAK_REALM is None:
    raise Exception('Expected environment variable "KEYCLOAK_REALM"')
if KEYCLOAK_ADMIN_USERNAME is None:
    raise Exception('Expected environment variable "KEYCLOAK_ADMIN_USERNAME"')
if KEYCLOAK_ADMIN_PASSWORD is None:
    raise Exception('Expected environment variable "KEYCLOAK_ADMIN_PASSWORD"')
if CLIENT_NAME is None:
    raise Exception('Expected environment variable "CLIENT_NAME"')

keycloak_admin = KeycloakAdmin(
            server_url=KEYCLOAK_URL,
            username=KEYCLOAK_ADMIN_USERNAME,
            password=KEYCLOAK_ADMIN_PASSWORD,
            realm_name=KEYCLOAK_REALM,
            user_realm_name='master')

# Create client
try:
    llama_stack_client_id = keycloak_admin.create_client({
        "clientId": CLIENT_NAME,
        "standardFlowEnabled": True,
        "directAccessGrantsEnabled": True,
        "fullScopeAllowed": False,
        "publicClient": True # Disable client authentication
    })

    logging.info("Created Keycloak client")
except KeycloakPostError as e:
    logging.error(f'Could not create Keycloak client "{CLIENT_NAME}": {e}')