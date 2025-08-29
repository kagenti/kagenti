import json
import os
import logging

from keycloak import KeycloakAdmin, KeycloakPostError

KEYCLOAK_URL = os.environ.get('KEYCLOAK_URL')
KEYCLOAK_REALM = os.environ.get('KEYCLOAK_REALM')
KEYCLOAK_ADMIN_USERNAME = os.environ.get('KEYCLOAK_ADMIN_USERNAME')
KEYCLOAK_ADMIN_PASSWORD = os.environ.get('KEYCLOAK_ADMIN_PASSWORD')

if KEYCLOAK_URL is None:
    raise Exception('Expected environment variable "KEYCLOAK_URL"')
if KEYCLOAK_REALM is None:
    raise Exception('Expected environment variable "KEYCLOAK_REALM"')
if KEYCLOAK_ADMIN_USERNAME is None:
    raise Exception('Expected environment variable "KEYCLOAK_ADMIN_USERNAME"')
if KEYCLOAK_ADMIN_PASSWORD is None:
    raise Exception('Expected environment variable "KEYCLOAK_ADMIN_PASSWORD"')

def assign_realm_role_to_client_scope(admin: KeycloakAdmin, scope_id: str, role_name: str):
    # Get full role representation
    role = admin.get_realm_role(role_name)

    # Construct proper URL
    url = f"{admin.connection.base_url}/admin/realms/master/client-scopes/{scope_id}/scope-mappings/realm"

    # POST the role representation
    admin.connection.raw_post(
        url,
        data=json.dumps([role])
    ).text

keycloak_admin = KeycloakAdmin(
            server_url=KEYCLOAK_URL,
            username=KEYCLOAK_ADMIN_USERNAME,
            password=KEYCLOAK_ADMIN_PASSWORD,
            realm_name=KEYCLOAK_REALM,
            user_realm_name='master')

user_id = keycloak_admin.create_user(
        {
            "username": "partial-access-slack-user",
            "enabled": True,
        },
        True
    )

keycloak_admin.set_user_password(user_id, "password", temporary=False)

user_id = keycloak_admin.create_user(
    {
        "username": "full-access-slack-user",
        "enabled": True,
    },
    True
)

keycloak_admin.set_user_password(user_id, "password", temporary=False)



# Create the full-slack-access client scope
full_client_scope_id = keycloak_admin.create_client_scope(
    {
        "name": "full-slack-access",
        "protocol": "openid-connect",
        "attributes": {
            "include.in.token.scope": "true",
            "display.on.consent.screen": "true",
        }
    },
    True
)

# Assign the slack-full-access realm role to full-slack-access client scope
assign_realm_role_to_client_scope(keycloak_admin, full_client_scope_id, "slack-full-access")

# Set full-slack-access client scope to a default client scope
try:
    keycloak_admin.add_default_default_client_scope(full_client_scope_id)
except Exception as e:
    print(f'Could not set full-slack-access client scope to a default client scope: {e}')




# Create the partial-slack-access client scope
partial_client_scope_id = keycloak_admin.create_client_scope(
    {
        "name": "partial-slack-access",
        "protocol": "openid-connect",
        "attributes": {
            "include.in.token.scope": "true",
            "display.on.consent.screen": "true",
        }
    },
    True
)

# Assign the slack-partial-access realm role to partial-slack-access client scope
assign_realm_role_to_client_scope(keycloak_admin, partial_client_scope_id, "slack-partial-access")

try:
    # Create and assign the slack-tool-audience audience protocol mapper to partial-slack-access client scope
    keycloak_admin.add_mapper_to_client_scope(
        partial_client_scope_id,
        {
            "name": "slack-tool-audience",
            "protocol": "openid-connect",
            "protocolMapper": "oidc-audience-mapper",
            "consentRequired": False,
            "config": {
                "included.client.audience": "spiffe://localhost.me/sa/slack-tool", # This part doesn't seem to work
                "included.custom.audience": "",
                "id.token.claim": "false",
                "access.token.claim": "true",
                "lightweight.access.token.claim": "false",
                "introspection.token.claim": "true"
            }
        }
    )
except Exception as e:
    print(f'Could not create and assign the slack-tool-audience audience protocol mapper to partial-slack-access client scope: {e}')

# Set partial-slack-access client scope to a default client scope
try:
    keycloak_admin.add_default_default_client_scope(partial_client_scope_id)
except Exception as e:
    print(f'Could not set partial-slack-access client scope to a default client scope: {e}')

# Assign partial-slack-access client scope
client_id = keycloak_admin.get_client_id("kagenti")
keycloak_admin.add_client_default_client_scope(client_id, full_client_scope_id, {})
keycloak_admin.add_client_default_client_scope(client_id, partial_client_scope_id, {})