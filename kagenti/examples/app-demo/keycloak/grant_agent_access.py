"""Grant the app-demo client access to AuthBridge-protected agents.

For each agent listed below, this script creates a Keycloak client scope with
an audience mapper that adds the agent's SPIFFE ID to the token's "aud" claim.
This allows users of the demo app to discover and chat with those agents.

Can run as a Kubernetes Job or locally with kubeconfig access.

To add more agents, append entries to the AGENTS list below.

See docs/agent-access-setup.md for the equivalent manual Keycloak steps.
"""

import base64
import logging
import os
import sys

from keycloak import KeycloakAdmin
from keycloak.exceptions import KeycloakPostError, KeycloakPutError
from kubernetes import client, config

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# --- Agent list ---
# Each entry is (agent-name, namespace). Extend this list when new agents
# are deployed and should be accessible through the demo app.
AGENTS = [
    ("git-issue-agent", "team1"),
    ("weather-agent", "team1"),
]


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
    keycloak_realm = os.environ.get("KEYCLOAK_REALM", "kagenti")
    client_id = os.environ.get("CLIENT_ID", "app-demo")
    keycloak_namespace = os.environ.get("KEYCLOAK_NAMESPACE", "keycloak")
    admin_secret_name = os.environ.get(
        "KEYCLOAK_ADMIN_SECRET_NAME", "keycloak-initial-admin"
    )
    domain = os.environ.get("DOMAIN_NAME", "localtest.me")
    root_url = os.environ.get("ROOT_URL", f"http://app-demo.{domain}:8080")

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

    # Resolve the app-demo client's internal ID
    app_client_id = keycloak_admin.get_client_id(client_id)
    if not app_client_id:
        logger.error(
            f"Client '{client_id}' not found in Keycloak. Run register_client.py first."
        )
        sys.exit(1)

    for agent_name, namespace in AGENTS:
        spiffe_id = f"spiffe://{domain}/ns/{namespace}/sa/{agent_name}"
        scope_name = f"{agent_name}-access"

        logger.info(f"Configuring access for '{agent_name}' ({spiffe_id})")

        # 1. Create client scope
        try:
            scope_id = keycloak_admin.create_client_scope(
                {
                    "name": scope_name,
                    "protocol": "openid-connect",
                    "attributes": {
                        "include.in.token.scope": "true",
                        "display.on.consent.screen": "false",
                    },
                },
                True,
            )
            logger.info(f"  Created client scope '{scope_name}'")
        except KeycloakPostError:
            scope_id = keycloak_admin.get_client_scope_id(scope_name)
            logger.info(f"  Client scope '{scope_name}' already exists")

        # 2. Add audience mapper
        try:
            keycloak_admin.add_mapper_to_client_scope(
                scope_id,
                {
                    "name": f"{agent_name}-audience",
                    "protocol": "openid-connect",
                    "protocolMapper": "oidc-audience-mapper",
                    "consentRequired": False,
                    "config": {
                        "included.client.audience": spiffe_id,
                        "access.token.claim": "true",
                        "id.token.claim": "false",
                        "introspection.token.claim": "true",
                        "userinfo.token.claim": "false",
                        "lightweight.claim": "false",
                        "lightweight.access.token.claim": "false",
                    },
                },
            )
            logger.info(f"  Added audience mapper -> {spiffe_id}")
        except (KeycloakPostError, KeycloakPutError):
            logger.info(f"  Audience mapper already exists")

        # 3. Set as realm default scope
        try:
            keycloak_admin.add_default_default_client_scope(scope_id)
            logger.info(f"  Set as realm default scope")
        except (KeycloakPostError, KeycloakPutError):
            logger.info(f"  Already a realm default scope")

        # 4. Explicitly add to the app-demo client
        try:
            keycloak_admin.add_client_default_client_scope(app_client_id, scope_id, {})
            logger.info(f"  Added to client '{client_id}'")
        except (KeycloakPostError, KeycloakPutError):
            logger.info(f"  Already on client '{client_id}'")

    logger.info("Agent access configuration completed successfully")
    logger.info("NOTE: Users must log out and back in to receive updated tokens.")
    logger.info(f"App Demo URL: {root_url}")


if __name__ == "__main__":
    main()
