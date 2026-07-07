#!/usr/bin/env python3
"""
setup_operator_client.py

Configures Keycloak for operator SPIFFE authentication by:
1. Ensuring SPIFFE Identity Provider exists
2. Creating the operator client with federated-jwt authentication
3. Assigning the manage-clients role to the operator's service account

This enables the operator to authenticate with JWT-SVID instead of admin credentials.

Usage:
    python setup_operator_client.py

Environment Variables:
    KEYCLOAK_URL: Keycloak server URL (default: http://keycloak-service.keycloak.svc:8080)
    KEYCLOAK_REALM: Target realm name (default: kagenti)
    KEYCLOAK_ADMIN_SECRET_NAME: Secret name containing admin credentials (default: keycloak-initial-admin)
    KEYCLOAK_ADMIN_SECRET_NAMESPACE: Namespace containing admin secret (default: keycloak)
    KEYCLOAK_ADMIN_USERNAME_KEY: Key in Secret for username (default: username)
    KEYCLOAK_ADMIN_PASSWORD_KEY: Key in Secret for password (default: password)
    SPIFFE_IDP_ALIAS: SPIFFE IdP alias in Keycloak (default: spire-spiffe)
    SPIRE_OIDC_URL: SPIRE OIDC Discovery Provider URL (required)
    SPIFFE_TRUST_DOMAIN: SPIFFE trust domain (required, e.g., localtest.me)
    OPERATOR_NAMESPACE: Operator namespace (required, e.g., kagenti-operator-system)
    OPERATOR_SERVICE_ACCOUNT: Operator ServiceAccount name (required, e.g., controller-manager)
"""

import os
import sys
import logging
import base64
from typing import Optional
import requests
from kubernetes import client, config as kube_config
from kubernetes.client.rest import ApiException

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Configuration from environment
KEYCLOAK_URL = os.getenv("KEYCLOAK_URL", "http://keycloak-service.keycloak.svc:8080")
KEYCLOAK_REALM = os.getenv("KEYCLOAK_REALM", "kagenti")
KEYCLOAK_ADMIN_SECRET_NAME = os.getenv(
    "KEYCLOAK_ADMIN_SECRET_NAME", "keycloak-initial-admin"
)
KEYCLOAK_ADMIN_SECRET_NAMESPACE = os.getenv(
    "KEYCLOAK_ADMIN_SECRET_NAMESPACE", "keycloak"
)
KEYCLOAK_ADMIN_USERNAME_KEY = os.getenv("KEYCLOAK_ADMIN_USERNAME_KEY", "username")
KEYCLOAK_ADMIN_PASSWORD_KEY = os.getenv("KEYCLOAK_ADMIN_PASSWORD_KEY", "password")
SPIFFE_IDP_ALIAS = os.getenv("SPIFFE_IDP_ALIAS", "spire-spiffe")
SPIRE_OIDC_URL = os.getenv("SPIRE_OIDC_URL")
# Derive operator SPIFFE ID from trust domain, namespace, and ServiceAccount
# Format: spiffe://<trust-domain>/ns/<namespace>/sa/<service-account-name>
# This matches the SPIFFE ID that SPIRE will issue to the operator pod
SPIFFE_TRUST_DOMAIN = os.getenv("SPIFFE_TRUST_DOMAIN")
OPERATOR_NAMESPACE = os.getenv("OPERATOR_NAMESPACE", "kagenti-operator-system")
OPERATOR_SERVICE_ACCOUNT = os.getenv("OPERATOR_SERVICE_ACCOUNT", "controller-manager")


class KeycloakBootstrap:
    """Handles Keycloak configuration for operator SPIFFE authentication."""

    def __init__(self):
        self.keycloak_url = KEYCLOAK_URL.rstrip("/")
        self.realm = KEYCLOAK_REALM
        self.admin_username: Optional[str] = None
        self.admin_password: Optional[str] = None
        self.token: Optional[str] = None
        self.session = requests.Session()
        # Disable SSL verification for in-cluster communication
        self.session.verify = False

    def load_kubernetes_config(self):
        """Load Kubernetes configuration."""
        try:
            kube_config.load_incluster_config()
            logger.info("Loaded in-cluster Kubernetes configuration")
        except Exception as e:
            logger.error(f"Failed to load Kubernetes config: {e}")
            raise

    def get_admin_credentials(self) -> tuple[str, str]:
        """Retrieve admin credentials from Kubernetes Secret."""
        logger.info("Retrieving admin credentials from configured Kubernetes Secret")

        try:
            v1 = client.CoreV1Api()
            secret = v1.read_namespaced_secret(
                name=KEYCLOAK_ADMIN_SECRET_NAME,
                namespace=KEYCLOAK_ADMIN_SECRET_NAMESPACE,
            )

            username_b64 = secret.data.get(KEYCLOAK_ADMIN_USERNAME_KEY)
            password_b64 = secret.data.get(KEYCLOAK_ADMIN_PASSWORD_KEY)

            if not username_b64 or not password_b64:
                raise ValueError(
                    f"Secret missing required keys: {KEYCLOAK_ADMIN_USERNAME_KEY}, {KEYCLOAK_ADMIN_PASSWORD_KEY}"
                )

            username = base64.b64decode(username_b64).decode("utf-8")
            password = base64.b64decode(password_b64).decode("utf-8")

            logger.info("✓ Admin credentials retrieved")
            return username, password

        except ApiException as e:
            logger.error(f"Failed to read Kubernetes Secret: {e}")
            raise
        except Exception as e:
            logger.error(f"Error decoding credentials: {e}")
            raise

    def authenticate(self):
        """Authenticate to Keycloak and obtain admin token."""
        logger.info("1. Authenticating to Keycloak...")

        self.admin_username, self.admin_password = self.get_admin_credentials()

        token_url = f"{self.keycloak_url}/realms/master/protocol/openid-connect/token"
        data = {
            "grant_type": "password",
            "client_id": "admin-cli",
            "username": self.admin_username,
            "password": self.admin_password,
        }

        try:
            response = self.session.post(token_url, data=data)
            response.raise_for_status()
            self.token = response.json()["access_token"]
            logger.info("   ✓ Authenticated successfully")
        except requests.RequestException as e:
            logger.error(
                "   ERROR: Authentication failed (check credentials and Keycloak availability)"
            )
            raise

    def ensure_spiffe_idp(self):
        """Ensure SPIFFE Identity Provider exists in Keycloak."""
        logger.info("2. Ensuring SPIFFE Identity Provider exists...")

        if not SPIRE_OIDC_URL:
            logger.error("   ERROR: SPIRE_OIDC_URL not set")
            sys.exit(1)

        headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
        }

        # Check if IdP exists
        idp_url = f"{self.keycloak_url}/admin/realms/{self.realm}/identity-provider/instances/{SPIFFE_IDP_ALIAS}"

        try:
            response = self.session.get(idp_url, headers=headers)
            if response.status_code == 200:
                logger.info(
                    f"   ✓ SPIFFE Identity Provider '{SPIFFE_IDP_ALIAS}' already exists"
                )
                return
            elif response.status_code != 404:
                logger.error(
                    f"   ERROR: Unexpected response checking IdP: {response.status_code}"
                )
                sys.exit(1)
        except requests.RequestException as e:
            logger.error(f"   ERROR: Failed to check IdP: {e}")
            raise

        # Create IdP using SPIFFE provider type (not OIDC!)
        # Keycloak has a dedicated SPIFFE provider that doesn't require OAuth2 endpoints
        logger.info(f"   Creating SPIFFE Identity Provider '{SPIFFE_IDP_ALIAS}'...")

        if not SPIFFE_TRUST_DOMAIN:
            logger.error("   ERROR: SPIFFE_TRUST_DOMAIN not set")
            sys.exit(1)

        # Construct trust domain URI (e.g., "spiffe://localtest.me")
        trust_domain_uri = f"spiffe://{SPIFFE_TRUST_DOMAIN}"

        idp_config = {
            "alias": SPIFFE_IDP_ALIAS,
            "providerId": "spiffe",  # Use SPIFFE provider, not OIDC!
            "enabled": True,
            "config": {
                "trustDomain": trust_domain_uri,  # SPIFFE uses trustDomain, not issuer
                "bundleEndpoint": f"{SPIRE_OIDC_URL}/keys",  # SPIFFE uses bundleEndpoint, not jwksUrl
                "validateSignature": "true",
            },
        }

        create_url = (
            f"{self.keycloak_url}/admin/realms/{self.realm}/identity-provider/instances"
        )
        try:
            response = self.session.post(create_url, headers=headers, json=idp_config)
            response.raise_for_status()
            logger.info("   ✓ SPIFFE Identity Provider created")
        except requests.RequestException as e:
            logger.error(f"   ERROR: Failed to create SPIFFE IdP: {e}")
            if hasattr(e, "response") and e.response is not None:
                logger.error(f"   Response: {e.response.text}")
            raise

    def ensure_operator_client(self) -> str:
        """Ensure operator client exists and return its UUID."""
        logger.info("3. Ensuring operator client exists...")

        if not OPERATOR_CLIENT_ID:
            logger.error("   ERROR: OPERATOR_CLIENT_ID not set")
            sys.exit(1)

        headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
        }

        # Check if client exists
        search_url = f"{self.keycloak_url}/admin/realms/{self.realm}/clients"
        params = {"clientId": OPERATOR_CLIENT_ID}

        try:
            response = self.session.get(search_url, headers=headers, params=params)
            response.raise_for_status()
            clients = response.json()

            if clients:
                client_uuid = clients[0]["id"]
                logger.info(
                    f"   ✓ Operator client already exists (UUID: {client_uuid})"
                )
                return client_uuid
        except requests.RequestException as e:
            logger.error(f"   ERROR: Failed to search for client: {e}")
            raise

        # Create client
        logger.info(f"   Creating operator client with ID '{OPERATOR_CLIENT_ID}'...")
        client_config = {
            "clientId": OPERATOR_CLIENT_ID,
            "enabled": True,
            "clientAuthenticatorType": "federated-jwt",
            "serviceAccountsEnabled": True,
            "standardFlowEnabled": False,
            "directAccessGrantsEnabled": False,
            "publicClient": False,
            "attributes": {
                "jwt.credential.issuer": SPIFFE_IDP_ALIAS,
                "jwt.credential.sub": OPERATOR_CLIENT_ID,
            },
        }

        try:
            response = self.session.post(
                search_url, headers=headers, json=client_config
            )
            response.raise_for_status()
            logger.info("   ✓ Operator client created")

            # Retrieve UUID
            response = self.session.get(search_url, headers=headers, params=params)
            response.raise_for_status()
            clients = response.json()
            if not clients:
                raise ValueError("Failed to retrieve created client")

            return clients[0]["id"]

        except requests.RequestException as e:
            logger.error(f"   ERROR: Failed to create operator client: {e}")
            if hasattr(e, "response") and e.response is not None:
                logger.error(f"   Response: {e.response.text}")
            raise

    def assign_manage_clients_role(self, client_uuid: str):
        """Assign manage-clients role to operator's service account."""
        logger.info("4. Assigning manage-clients role to operator service account...")

        headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
        }

        # Get service account user
        sa_url = f"{self.keycloak_url}/admin/realms/{self.realm}/clients/{client_uuid}/service-account-user"
        try:
            response = self.session.get(sa_url, headers=headers)
            response.raise_for_status()
            sa_user = response.json()
            sa_user_id = sa_user["id"]
            logger.info(f"   ✓ Service account user ID: {sa_user_id}")
        except requests.RequestException as e:
            logger.error(f"   ERROR: Failed to get service account: {e}")
            raise

        # Get realm-management client UUID
        search_url = f"{self.keycloak_url}/admin/realms/{self.realm}/clients"
        params = {"clientId": "realm-management"}
        try:
            response = self.session.get(search_url, headers=headers, params=params)
            response.raise_for_status()
            clients = response.json()
            if not clients:
                raise ValueError("realm-management client not found")
            realm_mgmt_uuid = clients[0]["id"]
        except requests.RequestException as e:
            logger.error(f"   ERROR: Failed to get realm-management client: {e}")
            raise

        # Get available client roles
        roles_url = f"{self.keycloak_url}/admin/realms/{self.realm}/users/{sa_user_id}/role-mappings/clients/{realm_mgmt_uuid}/available"
        try:
            response = self.session.get(roles_url, headers=headers)
            response.raise_for_status()
            available_roles = response.json()

            # Find manage-clients role
            manage_clients_role = None
            for role in available_roles:
                if role["name"] == "manage-clients":
                    manage_clients_role = role
                    break

            if not manage_clients_role:
                logger.info("   ✓ manage-clients role already assigned")
                return

        except requests.RequestException as e:
            logger.error(f"   ERROR: Failed to get available roles: {e}")
            raise

        # Assign role
        assign_url = f"{self.keycloak_url}/admin/realms/{self.realm}/users/{sa_user_id}/role-mappings/clients/{realm_mgmt_uuid}"
        try:
            response = self.session.post(
                assign_url, headers=headers, json=[manage_clients_role]
            )
            response.raise_for_status()
            logger.info("   ✓ manage-clients role assigned")
        except requests.RequestException as e:
            logger.error(f"   ERROR: Failed to assign role: {e}")
            if hasattr(e, "response") and e.response is not None:
                logger.error(f"   Response: {e.response.text}")
            raise

    def run(self):
        """Execute the full bootstrap process."""
        logger.info("=" * 60)
        logger.info("Operator SPIFFE Authentication Bootstrap")
        logger.info("=" * 60)

        try:
            self.load_kubernetes_config()
            self.authenticate()
            self.ensure_spiffe_idp()
            client_uuid = self.ensure_operator_client()
            self.assign_manage_clients_role(client_uuid)

            logger.info("=" * 60)
            logger.info("✓ Bootstrap completed successfully")
            logger.info("=" * 60)

        except Exception as e:
            logger.error(f"Bootstrap failed: {e}")
            sys.exit(1)


def main():
    """Main entry point."""
    # Validate required environment variables
    if not SPIRE_OIDC_URL:
        logger.error("SPIRE_OIDC_URL environment variable is required")
        sys.exit(1)
    if not SPIFFE_TRUST_DOMAIN:
        logger.error("SPIFFE_TRUST_DOMAIN environment variable is required")
        sys.exit(1)

    # Derive operator SPIFFE ID from components
    # This must match the SPIFFE ID that SPIRE issues to the operator pod
    operator_client_id = f"spiffe://{SPIFFE_TRUST_DOMAIN}/ns/{OPERATOR_NAMESPACE}/sa/{OPERATOR_SERVICE_ACCOUNT}"
    logger.info(f"Derived operator SPIFFE ID: {operator_client_id}")

    # Override global OPERATOR_CLIENT_ID for backward compatibility with KeycloakBootstrap class
    global OPERATOR_CLIENT_ID
    OPERATOR_CLIENT_ID = operator_client_id

    bootstrap = KeycloakBootstrap()
    bootstrap.run()


if __name__ == "__main__":
    main()
