import json
import os
import jwt
from keycloak import KeycloakAdmin, KeycloakPostError

# Read SVID JWT from file to get client ID
jwt_file_path = "/opt/jwt_svid.token"
try:
    with open(jwt_file_path, "r") as file:
        content = file.read()

except FileNotFoundError:
    print(f"Error: The file {jwt_file_path} was not found.")
except Exception as e:
    print(f"An error occurred: {e}")
    
if content is None or content.strip() == "":
    raise Exception(f'No content read from SVID JWT.')

decoded = jwt.decode(content, options={"verify_signature": False})
if 'sub' not in decoded:
    raise Exception('SVID JWT does not contain a "sub" claim.')
client_id = decoded['sub']



KEYCLOAK_URL = os.environ.get('KEYCLOAK_URL')
if KEYCLOAK_URL is None:
    print(f'Expected environment variable "KEYCLOAK_URL". Skipping client registration of {client_id}.')
    exit()

KEYCLOAK_REALM = os.environ.get('KEYCLOAK_REALM')
if KEYCLOAK_REALM is None:
    raise Exception('Expected environment variable "KEYCLOAK_REALM"')

KEYCLOAK_ADMIN_USERNAME = os.environ.get('KEYCLOAK_ADMIN_USERNAME')
if KEYCLOAK_ADMIN_USERNAME is None:
    raise Exception('Expected environment variable "KEYCLOAK_ADMIN_USERNAME"')

KEYCLOAK_ADMIN_PASSWORD = os.environ.get('KEYCLOAK_ADMIN_PASSWORD')
if KEYCLOAK_ADMIN_PASSWORD is None:
    raise Exception('Expected environment variable "KEYCLOAK_ADMIN_PASSWORD"')

CLIENT_NAME = os.environ.get('CLIENT_NAME')
if CLIENT_NAME is None:
    raise Exception('Expected environment variable "CLIENT_NAME"')



# TODO: refactor this function so kagenti-client-registration image can use it
def register_client(
    keycloak_admin: KeycloakAdmin,
    client_id: str,
    client_payload
):
    # Create client
    internal_client_id = None
    try:
        internal_client_id = keycloak_admin.create_client(
            client_payload
        )

        print(f'Created Keycloak client "{client_id}": {internal_client_id}')
    except KeycloakPostError as e:
        print(f'Could not create Keycloak client "{client_id}": {e}')

        error_json = json.loads(e.error_message)
        if error_json['errorMessage'] == f'Client {client_id} already exists':
            internal_client_id = keycloak_admin.get_client_id(client_id)
            print(f'Obtained internal client ID of existing client "{client_id}": {internal_client_id}')

    return internal_client_id

keycloak_admin = KeycloakAdmin(
    server_url=KEYCLOAK_URL,
    username=KEYCLOAK_ADMIN_USERNAME,
    password=KEYCLOAK_ADMIN_PASSWORD,
    realm_name=KEYCLOAK_REALM,
    user_realm_name='master' # user_realm_name is the realm where the admin user is defined
)

register_client(
    keycloak_admin,
    client_id,
    {
        "name": CLIENT_NAME,
        "clientId": client_id,
        "standardFlowEnabled": True,
        "directAccessGrantsEnabled": True,
        "fullScopeAllowed": False,
        "publicClient": True # Disable client authentication
    }
)