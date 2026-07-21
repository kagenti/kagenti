"""Register the 'app-demo' public OIDC client in Keycloak.

Runs as a Kubernetes Job. Reads admin credentials from the
keycloak-initial-admin secret, then creates (or verifies) the client.
"""

import base64
import json
import logging
import os
import sys

from keycloak import KeycloakAdmin
from keycloak.exceptions import KeycloakPostError
from kubernetes import client, config

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def load_kubernetes_config():
    try:
        config.load_incluster_config()
    except config.ConfigException:
        config.load_kube_config()


def read_keycloak_credentials(
    v1: client.CoreV1Api,
    secret_name: str = "keycloak-initial-admin",
    namespace: str = "keycloak",
) -> tuple[str, str]:
    secret = v1.read_namespaced_secret(secret_name, namespace)
    username = base64.b64decode(secret.data["username"]).decode()
    password = base64.b64decode(secret.data["password"]).decode()
    return username, password


def main():
    keycloak_url = os.environ.get(
        "KEYCLOAK_URL", "http://keycloak-service.keycloak.svc.cluster.local:8080"
    )
    keycloak_realm = os.environ.get("KEYCLOAK_REALM", "rossoctl")
    client_id = os.environ.get("CLIENT_ID", "app-demo")
    root_url = os.environ.get("ROOT_URL", "http://app-demo.localtest.me:8080")
    keycloak_namespace = os.environ.get("KEYCLOAK_NAMESPACE", "keycloak")
    admin_secret_name = os.environ.get(
        "KEYCLOAK_ADMIN_SECRET_NAME", "keycloak-initial-admin"
    )

    load_kubernetes_config()
    v1 = client.CoreV1Api()

    username, password = read_keycloak_credentials(
        v1, admin_secret_name, keycloak_namespace
    )

    keycloak_admin = KeycloakAdmin(
        server_url=keycloak_url,
        username=username,
        password=password,
        realm_name=keycloak_realm,
        user_realm_name="master",
        verify=True,
    )

    client_payload = {
        "clientId": client_id,
        "name": "Rossoctl App Demo",
        "description": "Demo application showing Rossoctl platform integration",
        "rootUrl": root_url,
        "enabled": True,
        "publicClient": True,
        "redirectUris": [root_url + "/*"],
        "webOrigins": [root_url],
        "standardFlowEnabled": True,
        "implicitFlowEnabled": False,
        "directAccessGrantsEnabled": False,
        "protocol": "openid-connect",
        "fullScopeAllowed": True,
        "attributes": {
            "pkce.code.challenge.method": "S256",
        },
    }

    try:
        keycloak_admin.create_client(client_payload)
        logger.info(f"Created Keycloak client '{client_id}'")
    except KeycloakPostError as e:
        try:
            error_json = json.loads(e.error_message)
            if error_json.get("errorMessage") == f"Client {client_id} already exists":
                logger.info(f"Client '{client_id}' already exists")
            else:
                raise
        except (json.JSONDecodeError, KeyError, TypeError):
            logger.error(f"Failed to create client '{client_id}': {e}")
            sys.exit(1)

    # Add sub and session_uid claim mappers to the client
    client_internal_id = keycloak_admin.get_client_id(client_id)

    # Add sub claim mapper
    try:
        keycloak_admin.add_mapper_to_client(
            client_internal_id,
            {
                "name": "sub-mapper",
                "protocol": "openid-connect",
                "protocolMapper": "oidc-usermodel-property-mapper",
                "consentRequired": False,
                "config": {
                    "userinfo.token.claim": "true",
                    "user.attribute": "id",
                    "id.token.claim": "true",
                    "access.token.claim": "true",
                    "claim.name": "sub",
                    "jsonType.label": "String",
                },
            },
        )
        logger.info(f"Added 'sub' claim mapper to client '{client_id}'")
    except KeycloakPostError:
        logger.info(f"'sub' claim mapper already exists for client '{client_id}'")

    # Add session_uid claim mapper (maps session ID to session_uid)
    try:
        keycloak_admin.add_mapper_to_client(
            client_internal_id,
            {
                "name": "session-uid-mapper",
                "protocol": "openid-connect",
                "protocolMapper": "oidc-usersessionmodel-note-mapper",
                "consentRequired": False,
                "config": {
                    "user.session.note": "id",
                    "id.token.claim": "true",
                    "access.token.claim": "true",
                    "claim.name": "session_uid",
                    "jsonType.label": "String",
                },
            },
        )
        logger.info(f"Added 'session_uid' claim mapper to client '{client_id}'")
    except KeycloakPostError:
        logger.info(
            f"'session_uid' claim mapper already exists for client '{client_id}'"
        )

    try:
        keycloak_admin.create_realm_role(
            {
                "name": "rossoctl-operator",
                "description": "Can send tasks to agents and manage agent lifecycle",
            }
        )
        logger.info("Created 'rossoctl-operator' realm role")
    except KeycloakPostError:
        logger.info("'rossoctl-operator' realm role already exists")

    logger.info("App Demo Keycloak client registration completed successfully")
    logger.info(f"App Demo URL: {root_url}")


if __name__ == "__main__":
    main()
