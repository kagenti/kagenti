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


github_partial_access_string = "github-partial-access"
github_full_access_string = "github-full-access"
github_partial_access_user_string = f"{github_partial_access_string}-user"
github_full_access_user_string = f"{github_full_access_string}-user"
github_client_id = f"spiffe://localtest.me/ns/{NAMESPACE}/sa/github-tool"
kagenti_client_id = "kagenti"

github_agent_access_string = "github-agent-access"
github_agent_client_id = f"spiffe://localtest.me/ns/{NAMESPACE}/sa/git-issue-agent"


keycloak_admin = KeycloakAdmin(
    server_url=KEYCLOAK_URL,
    username=KEYCLOAK_ADMIN_USERNAME,
    password=KEYCLOAK_ADMIN_PASSWORD,
    realm_name=KEYCLOAK_REALM,
    user_realm_name="master",
)


# Create the github-partial-access client scope
partial_client_scope_id = keycloak_admin.create_client_scope(
    {
        "name": github_partial_access_string,
        "protocol": "openid-connect",
        "attributes": {
            "include.in.token.scope": "true",
            "display.on.consent.screen": "true",
        },
    },
    True,
)

keycloak_admin.create_realm_role(
    {"name": github_partial_access_string, "composite": True, "clientRole": True}, True
)

# Assign the github-partial-access realm role to github-partial-access client scope
assign_realm_role_to_client_scope(
    keycloak_admin, partial_client_scope_id, github_partial_access_string
)

try:
    # Create and assign the github-tool-audience audience protocol mapper to github-partial-access client scope
    keycloak_admin.add_mapper_to_client_scope(
        partial_client_scope_id,
        {
            "name": "github-tool-audience",
            "protocol": "openid-connect",
            "protocolMapper": "oidc-audience-mapper",
            "consentRequired": False,
            "config": {
                "included.client.audience": github_client_id,
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
        f"Could not create and assign the github-tool-audience audience protocol mapper to github-partial-access client scope: {e}"
    )

# Set github-partial-access client scope to a default client scope
try:
    keycloak_admin.add_default_default_client_scope(partial_client_scope_id)
except Exception as e:
    print(
        f"Could not set github-partial-access client scope to a default client scope: {e}"
    )


# Create the github-full-access client scope
full_client_scope_id = keycloak_admin.create_client_scope(
    {
        "name": github_full_access_string,
        "protocol": "openid-connect",
        "attributes": {
            "include.in.token.scope": "true",
            "display.on.consent.screen": "true",
        },
    },
    True,
)

keycloak_admin.create_realm_role(
    {"name": github_full_access_string, "composite": True, "clientRole": True}, True
)

# Assign the github-full-access realm role to github-full-access client scope
assign_realm_role_to_client_scope(
    keycloak_admin, full_client_scope_id, github_full_access_string
)

# Set github-full-access client scope to a default client scope
try:
    keycloak_admin.add_default_default_client_scope(full_client_scope_id)
except Exception as e:
    print(
        f"Could not set github-full-access client scope to a default client scope: {e}"
    )


# Create the github-agent-access client scope
agent_access_client_scope_id = keycloak_admin.create_client_scope(
    {
        "name": github_agent_access_string,
        "protocol": "openid-connect",
        "attributes": {
            "include.in.token.scope": "true",
            "display.on.consent.screen": "true",
        },
    },
    True,
)

keycloak_admin.create_realm_role(
    {"name": github_agent_access_string, "composite": True, "clientRole": True}, True
)

# Assign the github-agent-access realm role to github-agent-access client scope
assign_realm_role_to_client_scope(
    keycloak_admin, agent_access_client_scope_id, github_agent_access_string
)

try:
    # Create and assign the github-agent-audience audience protocol mapper to github-agent-access client scope
    keycloak_admin.add_mapper_to_client_scope(
        agent_access_client_scope_id,
        {
            "name": "github-agent-audience",
            "protocol": "openid-connect",
            "protocolMapper": "oidc-audience-mapper",
            "consentRequired": False,
            "config": {
                "included.client.audience": github_agent_client_id,
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
        f"Could not create and assign the github-agent-audience audience protocol mapper to github-agent-access client scope: {e}"
    )

# Set github-agent-access client scope to a default client scope
try:
    keycloak_admin.add_default_default_client_scope(agent_access_client_scope_id)
except Exception as e:
    print(
        f"Could not set github-agent-access client scope to a default client scope: {e}"
    )


# Add github-partial-access and github-full-access and github-agent-access client scopes to the kagenti client
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
    print(f"Could not enable service accounts for client {github_client_id}: {e}")

# Add github-partial-access and github-full-access client scopes to the agent client
try:
    internal_github_agent_client_id = keycloak_admin.get_client_id(
        github_agent_client_id
    )
    keycloak_admin.add_client_optional_client_scope(
        internal_github_agent_client_id, partial_client_scope_id, {}
    )
    keycloak_admin.add_client_optional_client_scope(
        internal_github_agent_client_id, full_client_scope_id, {}
    )
except Exception as e:
    print(
        f"Could not enable service accounts for client {internal_github_agent_client_id}: {e}"
    )

# Create the partial access user and add the realm roles
partial_user_id = keycloak_admin.create_user(
    {
        "username": github_partial_access_user_string,
        "enabled": True,
    },
    True,
)

keycloak_admin.set_user_password(partial_user_id, "password", temporary=False)

github_partial_access_role = keycloak_admin.get_realm_role(github_partial_access_string)
github_agent_access_role = keycloak_admin.get_realm_role(github_agent_access_string)
partial_user_roles = [github_partial_access_role, github_agent_access_role]
try:
    keycloak_admin.assign_realm_roles(partial_user_id, partial_user_roles)
except Exception as e:
    print(
        f'Could not add "{github_partial_access_string}" realm role to user "{github_partial_access_user_string}": {e}'
    )


# Create the full access user and add the realm roles
full_user_id = keycloak_admin.create_user(
    {
        "username": github_full_access_user_string,
        "enabled": True,
    },
    True,
)
keycloak_admin.set_user_password(full_user_id, "password", temporary=False)

github_full_access_role = keycloak_admin.get_realm_role(github_full_access_string)
full_user_roles = [
    github_partial_access_role,
    github_full_access_role,
    github_agent_access_role,
]
try:
    keycloak_admin.assign_realm_roles(full_user_id, full_user_roles)
except Exception as e:
    print(
        f'Could not add "{full_user_roles}" realm roles to user "{github_full_access_user_string}": {e}'
    )


# Set the realm access token lifespan to 10 minutes
realm = keycloak_admin.get_realm(KEYCLOAK_REALM)
realm["accessTokenLifespan"] = 600  # 10 minutes
keycloak_admin.update_realm(KEYCLOAK_REALM, realm)
