import os
from keycloak_wrapper import (
    create_keycloak_client,
    create_keycloak_client_scope,
    get_keycloak_access_token,
)

base_url = "http://localhost:8080"
admin_username = "admin"
admin_password = "admin"
realm = "Demo"

# # Example:
# SPIFFE_ID_API="spiffe://9.31.99.108.nip.io/ns/api/sa/default"
# SPIFFE_ID_AGENT="spiffe://9.31.99.108.nip.io/ns/agent/sa/default"
# JWKS_URL="http://oidc-discovery-http.9.31.99.108.nip.io/keys"

SPIFFE_ID_API = os.environ.get("SPIFFE_ID_API")
if SPIFFE_ID_API is None:
    raise Exception('Missing environment variable "SPIFFE_ID_API"')

SPIFFE_ID_AGENT = os.environ.get("SPIFFE_ID_AGENT")
if SPIFFE_ID_AGENT is None:
    raise Exception('Missing environment variable "SPIFFE_ID_AGENT"')

JWKS_URL = os.environ.get("JWKS_URL")
if JWKS_URL is None:
    raise Exception('Missing environment variable "JWKS_URL"')

# Constants
REALM_MANAGEMENT = "realm-management"

access_token = get_keycloak_access_token(base_url, admin_username, admin_password)

if len(access_token) > 0:
    # Create client scopes
    client_scopes = [
        {
            "name": "agent-audience",
            "protocol": "openid-connect",
            "protocolMappers": [
                {
                    "name": "agent-audience",
                    "protocol": "openid-connect",
                    "protocolMapper": "oidc-audience-mapper",
                    "config": {"included.client.audience": SPIFFE_ID_AGENT},
                }
            ],
        },
        {
            "name": "tool-audience",
            "protocol": "openid-connect",
            "protocolMappers": [
                {
                    "name": "tool-audience",
                    "protocol": "openid-connect",
                    "protocolMapper": "oidc-audience-mapper",
                    "config": {"included.custom.audience": "example-tool"},
                }
            ],
        },
    ]

    for client_scope in client_scopes:
        print(f'Creating client scope "{client_scope["name"]}"')

        create_keycloak_client_scope(client_scope, base_url, realm, access_token)

    # Create clients
    # NOTE: For some reason, setting the protocol to openid-connect causes client/capability/client authentication to be toggled off
    # However, the default protocol is openid-connect so we do not have to explicitly set it.
    # We are using this property to turn off client authentication for the ExampleTool
    # TODO: Setting optionalClientScopes this way prevents the client from having default optional client scopes.
    # Will this be an issue?
    clients = [
        {
            "clientId": "ExampleTool",
            "protocol": "openid-connect",
            "standardFlowEnabled": False,
            "directAccessGrantsEnabled": False,
        },
        {
            "clientId": SPIFFE_ID_API,
            "clientAuthenticatorType": "client-jwt",
            "standardFlowEnabled": True,
            "directAccessGrantsEnabled": True,
            # "protocol": "openid-connect",
            "attributes": {"jwks.url": JWKS_URL, "use.jwks.url": "True"},
            "fullScopeAllowed": False,
            "optionalClientScopes": [
                # "address",
                # "phone",
                # "organization",
                # "offline_access",
                # "microprofile-jwt",
                "agent-audience"
            ],
        },
        {
            "clientId": SPIFFE_ID_AGENT,
            "clientAuthenticatorType": "client-jwt",
            "standardFlowEnabled": True,
            "directAccessGrantsEnabled": True,
            # "protocol": "openid-connect",
            "attributes": {"jwks.url": JWKS_URL, "use.jwks.url": "True"},
            "fullScopeAllowed": False,
            "optionalClientScopes": [
                "tool-audience",
                # "address",
                # "phone",
                # "organization",
                # "offline_access",
                # "microprofile-jwt"
            ],
        },
    ]

    for client in clients:
        print(f'Creating client "{client["clientId"]}"')

        create_keycloak_client(client, base_url, realm, access_token)

    # # TODO: Set up token exchange
    # # 1) create token exchange policy
    # # 2) enable permissions for ExampleTool
    # # 3) attach token exchange policy to ExampleTool
