import json
import os

from keycloak import KeycloakAdmin

KEYCLOAK_URL = os.environ.get("KEYCLOAK_URL")
KEYCLOAK_REALM = os.environ.get("KEYCLOAK_REALM")
KEYCLOAK_ADMIN_USERNAME = os.environ.get("KEYCLOAK_ADMIN_USERNAME")
KEYCLOAK_ADMIN_PASSWORD = os.environ.get("KEYCLOAK_ADMIN_PASSWORD")
NAMESPACE = os.environ.get("NAMESPACE")

if KEYCLOAK_URL is None:
    raise Exception('Expected environment variable "KEYCLOAK_URL"')
if KEYCLOAK_REALM is None:
    raise Exception('Expected environment variable "KEYCLOAK_REALM"')
if KEYCLOAK_ADMIN_USERNAME is None:
    raise Exception('Expected environment variable "KEYCLOAK_ADMIN_USERNAME"')
if KEYCLOAK_ADMIN_PASSWORD is None:
    raise Exception('Expected environment variable "KEYCLOAK_ADMIN_PASSWORD"')
if NAMESPACE is None:
    raise Exception('Expected environment variable "NAMESPACE"')


def assign_realm_role_to_client_scope(
    admin: KeycloakAdmin, scope_id: str, role_name: str
):
    # Get full role representation
    role = admin.get_realm_role(role_name)

    # Construct proper URL
    url = f"{admin.connection.base_url}/admin/realms/master/client-scopes/{scope_id}/scope-mappings/realm"

    # POST the role representation
    admin.connection.raw_post(url, data=json.dumps([role])).text


slack_partial_access_string = "slack-partial-access"
slack_full_access_string = "slack-full-access"
slack_partial_access_user_string = f"{slack_partial_access_string}-user"
slack_full_access_user_string = f"{slack_full_access_string}-user"
slack_client_id = f"spiffe://localtest.me/ns/{NAMESPACE}/sa/slack-tool"
kagenti_client_id = "kagenti"

slack_agent_access_string = "slack-agent-access"
slack_agent_client_id = f"spiffe://localtest.me/ns/{NAMESPACE}/sa/slack-researcher"


keycloak_admin = KeycloakAdmin(
    server_url=KEYCLOAK_URL,
    username=KEYCLOAK_ADMIN_USERNAME,
    password=KEYCLOAK_ADMIN_PASSWORD,
    realm_name=KEYCLOAK_REALM,
    user_realm_name="master",
)


# Create the slack-partial-access client scope
partial_client_scope_id = keycloak_admin.create_client_scope(
    {
        "name": slack_partial_access_string,
        "protocol": "openid-connect",
        "attributes": {
            "include.in.token.scope": "true",
            "display.on.consent.screen": "true",
        },
    },
    True,
)

keycloak_admin.create_realm_role(
    {"name": slack_partial_access_string, "composite": True, "clientRole": True}, True
)

# Assign the slack-partial-access realm role to slack-partial-access client scope
assign_realm_role_to_client_scope(
    keycloak_admin, partial_client_scope_id, slack_partial_access_string
)

try:
    # Create and assign the slack-tool-audience audience protocol mapper to slack-partial-access client scope
    keycloak_admin.add_mapper_to_client_scope(
        partial_client_scope_id,
        {
            "name": "slack-tool-audience",
            "protocol": "openid-connect",
            "protocolMapper": "oidc-audience-mapper",
            "consentRequired": False,
            "config": {
                "included.client.audience": slack_client_id,
                "introspection.token.claim": "true",
                "userinfo.token.claim": "false",
                "id.token.claim": "false",
                "lightweight.claim": "false",
                "access.token.claim": "true",
                "lightweight.access.token.claim": "false",
            },
        },
    )
except Exception as e:
    print(
        f"Could not create and assign the slack-tool-audience audience protocol mapper to slack-partial-access client scope: {e}"
    )

# Set slack-partial-access client scope to a default client scope
try:
    keycloak_admin.add_default_default_client_scope(partial_client_scope_id)
except Exception as e:
    print(
        f"Could not set slack-partial-access client scope to a default client scope: {e}"
    )


# Create the slack-full-access client scope
full_client_scope_id = keycloak_admin.create_client_scope(
    {
        "name": slack_full_access_string,
        "protocol": "openid-connect",
        "attributes": {
            "include.in.token.scope": "true",
            "display.on.consent.screen": "true",
        },
    },
    True,
)

keycloak_admin.create_realm_role(
    {"name": slack_full_access_string, "composite": True, "clientRole": True}, True
)

# Assign the slack-full-access realm role to slack-full-access client scope
assign_realm_role_to_client_scope(
    keycloak_admin, full_client_scope_id, slack_full_access_string
)

# Set slack-full-access client scope to a default client scope
try:
    keycloak_admin.add_default_default_client_scope(full_client_scope_id)
except Exception as e:
    print(
        f"Could not set slack-full-access client scope to a default client scope: {e}"
    )


# Create the slack-agent-access client scope
agent_access_client_scope_id = keycloak_admin.create_client_scope(
    {
        "name": slack_agent_access_string,
        "protocol": "openid-connect",
        "attributes": {
            "include.in.token.scope": "true",
            "display.on.consent.screen": "true",
        },
    },
    True,
)

keycloak_admin.create_realm_role(
    {"name": slack_agent_access_string, "composite": True, "clientRole": True}, True
)

# Assign the slack-agent-access realm role to slack-agent-access client scope
assign_realm_role_to_client_scope(
    keycloak_admin, agent_access_client_scope_id, slack_agent_access_string
)

try:
    # Create and assign the slack-agent-audience audience protocol mapper to slack-agent-access client scope
    keycloak_admin.add_mapper_to_client_scope(
        agent_access_client_scope_id,
        {
            "name": "slack-agent-audience",
            "protocol": "openid-connect",
            "protocolMapper": "oidc-audience-mapper",
            "consentRequired": False,
            "config": {
                "included.client.audience": slack_agent_client_id,
                "introspection.token.claim": "true",
                "userinfo.token.claim": "false",
                "id.token.claim": "false",
                "lightweight.claim": "false",
                "access.token.claim": "true",
                "lightweight.access.token.claim": "false",
            },
        },
    )
except Exception as e:
    print(
        f"Could not create and assign the slack-agent-audience audience protocol mapper to slack-agent-access client scope: {e}"
    )

# Set slack-agent-access client scope to a default client scope
try:
    keycloak_admin.add_default_default_client_scope(agent_access_client_scope_id)
except Exception as e:
    print(
        f"Could not set slack-agent-access client scope to a default client scope: {e}"
    )


# Add slack-partial-access and slack-full-access and slack-agent-access client scopes to the kagenti client
try:
    internal_kagenti_client_id = keycloak_admin.get_client_id(kagenti_client_id)
    keycloak_admin.add_client_default_client_scope(
        internal_kagenti_client_id, partial_client_scope_id, {}
    )
    keycloak_admin.add_client_default_client_scope(
        internal_kagenti_client_id, full_client_scope_id, {}
    )
    keycloak_admin.add_client_default_client_scope(
        internal_kagenti_client_id, agent_access_client_scope_id, {}
    )
except Exception as e:
    print(f"Could not enable service accounts for client {kagenti_client_id}: {e}")

# Add slack-partial-access and slack-full-access client scopes to the agent client
try:
    internal_slack_agent_client_id = keycloak_admin.get_client_id(slack_agent_client_id)
    keycloak_admin.add_client_optional_client_scope(
        internal_slack_agent_client_id, partial_client_scope_id, {}
    )
    keycloak_admin.add_client_optional_client_scope(
        internal_slack_agent_client_id, full_client_scope_id, {}
    )
except Exception as e:
    print(f"Could not enable service accounts for client {slack_agent_client_id}: {e}")

# Create the partial access user and add the realm roles
partial_user_id = keycloak_admin.create_user(
    {
        "username": slack_partial_access_user_string,
        "enabled": True,
    },
    True,
)

keycloak_admin.set_user_password(partial_user_id, "password", temporary=False)

slack_partial_access_role = keycloak_admin.get_realm_role(slack_partial_access_string)
slack_agent_access_role = keycloak_admin.get_realm_role(slack_agent_access_string)
partial_user_roles = [slack_partial_access_role, slack_agent_access_role]
try:
    keycloak_admin.assign_realm_roles(partial_user_id, partial_user_roles)
except Exception as e:
    print(
        f'Could not add "{slack_partial_access_string}" realm role to user "{slack_partial_access_user_string}": {e}'
    )


# Create the full access user and add the realm roles
full_user_id = keycloak_admin.create_user(
    {
        "username": slack_full_access_user_string,
        "enabled": True,
    },
    True,
)
keycloak_admin.set_user_password(full_user_id, "password", temporary=False)

slack_full_access_role = keycloak_admin.get_realm_role(slack_full_access_string)
full_user_roles = [
    slack_partial_access_role,
    slack_full_access_role,
    slack_agent_access_role,
]
try:
    keycloak_admin.assign_realm_roles(full_user_id, full_user_roles)
except Exception as e:
    print(
        f'Could not add "{full_user_roles}" realm roles to user "{slack_full_access_user_string}": {e}'
    )


# Set the realm access token lifespan to 10 minutes
realm = keycloak_admin.get_realm(KEYCLOAK_REALM)
realm["accessTokenLifespan"] = 600  # 10 minutes
keycloak_admin.update_realm(KEYCLOAK_REALM, realm)
