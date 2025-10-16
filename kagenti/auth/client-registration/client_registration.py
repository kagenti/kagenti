"""
client_registration.py

Registers a Keycloak client and stores its secret in a file.
Idempotent:
- Creates the client if it does not exist.
- If the client already exists, reuses it.
- Always retrieves and stores the client secret.
"""

import os
import jwt
from keycloak import KeycloakAdmin, KeycloakPostError


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
        print(f'Successfully retrieved secret for client "{client_name}".')
    except KeycloakPostError as e:
        print(f"Could not retrieve secret for client '{client_name}': {e}")
        return

    try:
        with open(secret_file_path, "w") as f:
            f.write(secret)
        print(f'Secret written to file: "{secret_file_path}"')
    except OSError as ioe:
        print(f"Error writing secret to file: {ioe}")


# TODO: refactor this function so kagenti-client-registration image can use it
def register_client(keycloak_admin: KeycloakAdmin, client_id: str, client_payload):
    """
    Ensure a Keycloak client exists.
    Returns the internal client ID.
    """
    internal_client_id = keycloak_admin.get_client_id(f"{client_id}")
    if internal_client_id:
        print(f'Client "{client_id}" already exists with ID: {internal_client_id}')
        return internal_client_id

    # Create client
    internal_client_id = None
    try:
        internal_client_id = keycloak_admin.create_client(client_payload)

        print(f'Created Keycloak client "{client_id}": {internal_client_id}')
        return internal_client_id
    except KeycloakPostError as e:
        print(f'Could not create client "{client_id}": {e}')
        raise


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
    raise Exception(f"No content read from SVID JWT.")

decoded = jwt.decode(content, options={"verify_signature": False})
if "sub" not in decoded:
    raise Exception('SVID JWT does not contain a "sub" claim.')
client_id = decoded["sub"]


# The Keycloak URL is handled differently from the other env vars because unlike the others, it's intended to be optional
try:
    KEYCLOAK_URL = get_env_var("KEYCLOAK_URL")
except:
    print(
        f'Expected environment variable "KEYCLOAK_URL". Skipping client registration of {client_id}.'
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
    },
)

print(
    f'Writing secret for client ID: "{client_id}", internal client ID: "{internal_client_id}"'
)
write_client_secret(
    keycloak_admin,
    internal_client_id,
    client_name,
    secret_file_path="/shared/secret.txt",
)

print("Client registration complete.")
