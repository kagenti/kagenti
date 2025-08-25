import os
from keycloak import KeycloakAdmin, KeycloakPostError

KEYCLOAK_URL = os.environ.get('KEYCLOAK_URL')
KEYCLOAK_REALM = os.environ.get('KEYCLOAK_REALM')
KEYCLOAK_ADMIN_USERNAME = os.environ.get('KEYCLOAK_ADMIN_USERNAME')
KEYCLOAK_ADMIN_PASSWORD = os.environ.get('KEYCLOAK_ADMIN_PASSWORD')
CLIENT_NAME = os.environ.get('CLIENT_NAME')
NAMESPACE = os.environ.get('NAMESPACE')

def register_client(
    keycloak_url: str,
    keycloak_realm: str,
    keycloak_admin_username: str,
    keycloak_admin_password: str,
    client_name: str,
    namespace: str
):
    clientId = f'{namespace}/{client_name}'

    if keycloak_url is None:
        print(f'Expected environment variable "KEYCLOAK_URL". Skipping client registration of {clientId}.')
        return
    if keycloak_realm is None:
        raise Exception('Expected environment variable "KEYCLOAK_REALM"')
    if keycloak_admin_username is None:
        raise Exception('Expected environment variable "KEYCLOAK_ADMIN_USERNAME"')
    if keycloak_admin_password is None:
        raise Exception('Expected environment variable "KEYCLOAK_ADMIN_PASSWORD"')
    if client_name is None:
        raise Exception('Expected environment variable "CLIENT_NAME"')
    if namespace is None:
        raise Exception('Expected environment variable "NAMESPACE"')

    keycloak_admin = KeycloakAdmin(
        server_url=keycloak_url,
        username=keycloak_admin_username,
        password=keycloak_admin_password,
        realm_name=keycloak_realm,
        user_realm_name='master'
    )

    # Create client
    try:
        internal_client_id = keycloak_admin.create_client(
            {
                "name": client_name,
                "clientId": clientId,
                "standardFlowEnabled": True,
                "directAccessGrantsEnabled": True,
                "fullScopeAllowed": False,
                "publicClient": True # Disable client authentication
            }
        )

        print(f'Created Keycloak client "{clientId}": {internal_client_id}')
    except KeycloakPostError as e:
        print(f'Could not create Keycloak client "{clientId}": {e}')

register_client(
    KEYCLOAK_URL,
    KEYCLOAK_REALM,
    KEYCLOAK_ADMIN_USERNAME,
    KEYCLOAK_ADMIN_PASSWORD,
    CLIENT_NAME,
    NAMESPACE
)