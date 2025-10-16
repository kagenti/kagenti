import json
import os
from keycloak import KeycloakAdmin, KeycloakPostError
from kubernetes import client, config
import base64

KEYCLOAK_REALM = os.environ.get("KEYCLOAK_REALM")
if KEYCLOAK_REALM is None:
    raise Exception('Expected environment variable "KEYCLOAK_REALM"')

KEYCLOAK_ADMIN_USERNAME = os.environ.get("KEYCLOAK_ADMIN_USERNAME")
if KEYCLOAK_ADMIN_USERNAME is None:
    raise Exception('Expected environment variable "KEYCLOAK_ADMIN_USERNAME"')

KEYCLOAK_ADMIN_PASSWORD = os.environ.get("KEYCLOAK_ADMIN_PASSWORD")
if KEYCLOAK_ADMIN_PASSWORD is None:
    raise Exception('Expected environment variable "KEYCLOAK_ADMIN_PASSWORD"')

NAMESPACE = os.environ.get("NAMESPACE")
if NAMESPACE is None:
    raise Exception('Expected environment variable "NAMESPACE"')

CLIENT_ID = os.environ.get("CLIENT_ID")
if CLIENT_ID is None:
    raise Exception('Expected environment variable "CLIENT_ID"')

ROOT_URL = os.environ.get("ROOT_URL")
if ROOT_URL is None:
    raise Exception('Expected environment variable "ROOT_URL"')

SECRET_NAME = os.environ.get("SECRET_NAME")
if SECRET_NAME is None:
    raise Exception('Expected environment variable "SECRET_NAME"')

KEYCLOAK_URL = os.environ.get("KEYCLOAK_URL")
if KEYCLOAK_URL is None:
    print(
        f'Expected environment variable "KEYCLOAK_URL". Skipping client registration of {CLIENT_ID}.'
    )
    exit()  # KEYCLOAK_URL is optional so do not raise an error


# TODO: use the function from kagenti/ui/lib/kube.py
def is_running_in_cluster() -> bool:
    return bool(os.getenv("KUBERNETES_SERVICE_HOST"))


# TODO: refactor this function so kagenti-client-registration image can use it
def register_client(keycloak_admin: KeycloakAdmin, client_id: str, client_payload):
    # Create client
    internal_client_id = None
    try:
        internal_client_id = keycloak_admin.create_client(client_payload)

        print(f'Created Keycloak client "{client_id}": {internal_client_id}')
    except KeycloakPostError as e:
        print(f'Could not create Keycloak client "{client_id}": {e}')

        error_json = json.loads(e.error_message)
        if error_json["errorMessage"] == f"Client {client_id} already exists":
            internal_client_id = keycloak_admin.get_client_id(client_id)
            print(
                f'Obtained internal client ID of existing client "{client_id}": {internal_client_id}'
            )

    return internal_client_id


keycloak_admin = KeycloakAdmin(
    server_url=KEYCLOAK_URL,
    username=KEYCLOAK_ADMIN_USERNAME,
    password=KEYCLOAK_ADMIN_PASSWORD,
    realm_name=KEYCLOAK_REALM,
    user_realm_name="master",  # user_realm_name is the realm where the admin user is defined
)

internal_client_id = register_client(
    keycloak_admin,
    CLIENT_ID,
    {
        "clientId": CLIENT_ID,
        "name": CLIENT_ID,
        "description": "",
        "rootUrl": ROOT_URL,
        "adminUrl": ROOT_URL,
        "baseUrl": "",
        "enabled": True,
        "clientAuthenticatorType": "client-secret",
        "redirectUris": [ROOT_URL + "/*"],
        "webOrigins": [ROOT_URL],
        "standardFlowEnabled": True,
        "implicitFlowEnabled": False,
        "directAccessGrantsEnabled": False,
        "publicClient": False,
        "frontchannelLogout": True,
        "protocol": "openid-connect",
        "fullScopeAllowed": True,
    },
)

# Get client secret
secrets = keycloak_admin.get_client_secrets(internal_client_id)
client_secret = secrets.get("value", "") if secrets else ""
data = {
    "ENABLE_AUTH": "true",  # string true
    "CLIENT_SECRET": client_secret,
    "CLIENT_ID": CLIENT_ID,
    "AUTH_ENDPOINT": "http://keycloak.localtest.me:8080/realms/master/protocol/openid-connect/auth",
    "TOKEN_ENDPOINT": "http://keycloak.keycloak.svc.cluster.local:8080/realms/master/protocol/openid-connect/token",
    "REDIRECT_URI": "http://kagenti-ui.localtest.me:8080/oauth2/callback",
    "SCOPE": "openid profile email",
}

# Connect to Kubernetes API
if is_running_in_cluster():
    config.load_incluster_config()
else:
    config.load_kube_config()
v1 = client.CoreV1Api()

# Create the Kubernetes secret
try:
    # Try to create first
    secret_body = client.V1Secret(
        api_version="v1",
        kind="Secret",
        metadata=client.V1ObjectMeta(name=SECRET_NAME),
        type="Opaque",
        string_data=data,
    )
    v1.create_namespaced_secret(namespace=NAMESPACE, body=secret_body)
    print(f"Created new secret '{SECRET_NAME}'.")
except client.exceptions.ApiException as e:
    # Patch if it already exists
    if e.status == 409:
        v1.patch_namespaced_secret(
            name=SECRET_NAME, namespace=NAMESPACE, body={"stringData": data}
        )
        print(f"Patched existing secret '{SECRET_NAME}'.")
    else:
        raise
