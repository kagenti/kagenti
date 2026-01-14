"""Phoenix OAuth Secret Generator for Keycloak Integration.

This script registers a Keycloak confidential client for Phoenix and creates
a Kubernetes secret with the OAuth2 configuration environment variables.

Phoenix native OAuth2 support expects environment variables in the format:
- PHOENIX_OAUTH2_KEYCLOAK_CLIENT_ID
- PHOENIX_OAUTH2_KEYCLOAK_CLIENT_SECRET
- PHOENIX_OAUTH2_KEYCLOAK_OIDC_CONFIG_URL

Unlike the UI (which uses a public client for browser-based SPA), Phoenix
runs server-side and uses a confidential client with a client secret.

See: https://arize.com/docs/phoenix/self-hosting/features/authentication
"""

import json
import logging
import os
import sys
from typing import Optional, Dict, Any, Tuple

from keycloak import KeycloakAdmin, KeycloakPostError
from kubernetes import client, config, dynamic
from kubernetes.client import api_client
import base64

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Constants
DEFAULT_KEYCLOAK_NAMESPACE = "keycloak"
DEFAULT_PHOENIX_NAMESPACE = "kagenti-system"
DEFAULT_KEYCLOAK_ROUTE_NAME = "keycloak"
DEFAULT_PHOENIX_ROUTE_NAME = "phoenix"
DEFAULT_KEYCLOAK_REALM = "master"
DEFAULT_ADMIN_SECRET_NAME = "keycloak-initial-admin"
DEFAULT_ADMIN_USERNAME_KEY = "username"
DEFAULT_ADMIN_PASSWORD_KEY = "password"


class ConfigurationError(Exception):
    """Raised when required configuration is missing or invalid."""

    pass


class KubernetesResourceError(Exception):
    """Raised when Kubernetes resource operations fail."""

    pass


class KeycloakOperationError(Exception):
    """Raised when Keycloak operations fail."""

    pass


def get_required_env(key: str) -> str:
    """Get a required environment variable or raise ConfigurationError."""
    value = os.environ.get(key)
    if value is None or value == "":
        raise ConfigurationError(f'Required environment variable: "{key}" is not set')
    return value


def get_optional_env(key: str, default: Optional[str] = None) -> Optional[str]:
    """Get an optional environment variable with optional default."""
    return os.environ.get(key, default)


def is_running_in_cluster() -> bool:
    """Check if running inside a Kubernetes cluster."""
    return bool(os.getenv("KUBERNETES_SERVICE_HOST"))


def get_openshift_route_url(
    dyn_client: dynamic.DynamicClient, namespace: str, route_name: str
) -> str:
    """Get the URL for an OpenShift route."""
    try:
        route_api = dyn_client.resources.get(
            api_version="route.openshift.io/v1", kind="Route"
        )
        route = route_api.get(name=route_name, namespace=namespace)
        host = route.spec.host

        if not host:
            raise KubernetesResourceError(
                f"Route {route_name} in namespace {namespace} has no host defined"
            )

        return f"https://{host}"
    except Exception as e:
        error_msg = f"Could not fetch OpenShift route {route_name} in namespace {namespace}: {e}"
        logger.error(error_msg)
        raise KubernetesResourceError(error_msg) from e


def read_keycloak_credentials(
    v1_client: client.CoreV1Api,
    secret_name: str,
    namespace: str,
    username_key: str,
    password_key: str,
) -> Tuple[str, str]:
    """Read Keycloak admin credentials from a Kubernetes secret."""
    try:
        logger.info(
            f"Reading Keycloak admin credentials from secret {secret_name} "
            f"in namespace {namespace}"
        )
        secret = v1_client.read_namespaced_secret(secret_name, namespace)

        if username_key not in secret.data:
            raise KubernetesResourceError(
                f"Secret {secret_name} in namespace {namespace} "
                f"missing key '{username_key}'"
            )
        if password_key not in secret.data:
            raise KubernetesResourceError(
                f"Secret {secret_name} in namespace {namespace} "
                f"missing key '{password_key}'"
            )

        username = base64.b64decode(secret.data[username_key]).decode("utf-8").strip()
        password = base64.b64decode(secret.data[password_key]).decode("utf-8").strip()

        logger.info("Successfully read credentials from secret")
        return username, password
    except client.exceptions.ApiException as e:
        error_msg = (
            f"Could not read Keycloak admin secret {secret_name} "
            f"in namespace {namespace}: {e}"
        )
        logger.error(error_msg)
        raise KubernetesResourceError(error_msg) from e


def configure_ssl_verification(ssl_cert_file: Optional[str]) -> Optional[str]:
    """Configure SSL verification based on certificate file availability."""
    if ssl_cert_file:
        if os.path.exists(ssl_cert_file):
            logger.info(f"Using SSL certificate file: {ssl_cert_file}")
            return ssl_cert_file
        else:
            logger.warning(
                f"Provided SSL_CERT_FILE '{ssl_cert_file}' does not exist; "
                "falling back to system CA bundle"
            )

    logger.info("No SSL_CERT_FILE provided - using system CA bundle for verification")
    return None


def register_confidential_client(
    keycloak_admin: KeycloakAdmin,
    client_id: str,
    root_url: str,
    redirect_uri: str,
) -> Tuple[str, str]:
    """Register a confidential OAuth2 client in Keycloak.

    Unlike public clients (SPAs), Phoenix needs a confidential client with a secret
    since it runs on the server and can securely store credentials.

    Args:
        keycloak_admin: Keycloak admin client
        client_id: Desired client ID
        root_url: Phoenix root URL
        redirect_uri: OAuth2 redirect URI

    Returns:
        Tuple of (internal_client_id, client_secret)
    """
    client_payload = {
        "clientId": client_id,
        "name": f"{client_id} - Phoenix Observability Dashboard",
        "description": "Phoenix LLM Observability Dashboard - Confidential client",
        "rootUrl": root_url,
        "adminUrl": root_url,
        "baseUrl": "",
        "enabled": True,
        "publicClient": False,  # Confidential client - has client secret
        "clientAuthenticatorType": "client-secret",
        "redirectUris": [redirect_uri],
        "webOrigins": [root_url],
        "standardFlowEnabled": True,  # Authorization code flow
        "implicitFlowEnabled": False,
        "directAccessGrantsEnabled": False,
        "serviceAccountsEnabled": False,
        "frontchannelLogout": True,
        "protocol": "openid-connect",
        "fullScopeAllowed": True,
    }

    try:
        internal_client_id = keycloak_admin.create_client(client_payload)
        logger.info(f'Created Keycloak client "{client_id}": {internal_client_id}')
    except KeycloakPostError as e:
        logger.debug(f'Keycloak client creation error for "{client_id}": {e}')

        try:
            error_json = json.loads(e.error_message)
            if error_json.get("errorMessage") == f"Client {client_id} already exists":
                internal_client_id = keycloak_admin.get_client_id(client_id)
                logger.info(
                    f'Using existing Keycloak client "{client_id}": {internal_client_id}'
                )
            else:
                raise
        except (json.JSONDecodeError, KeyError, TypeError):
            error_msg = (
                f'Failed to create or retrieve Keycloak client "{client_id}": {e}'
            )
            logger.error(error_msg)
            raise KeycloakOperationError(error_msg) from e

    # Get or regenerate client secret for confidential client
    secrets = keycloak_admin.get_client_secrets(internal_client_id)
    client_secret = secrets.get("value", "") if secrets else ""

    if not client_secret:
        # Regenerate secret if empty
        logger.info(f"Regenerating client secret for {client_id}")
        new_secrets = keycloak_admin.generate_client_secrets(internal_client_id)
        client_secret = new_secrets.get("value", "")

    if not client_secret:
        raise KeycloakOperationError(
            f"Could not obtain client secret for confidential client {client_id}"
        )

    logger.info(f"Successfully obtained client secret for {client_id}")
    return internal_client_id, client_secret


def create_or_update_secret(
    v1_client: client.CoreV1Api, namespace: str, secret_name: str, data: Dict[str, str]
) -> None:
    """Create or update a Kubernetes secret."""
    try:
        secret_body = client.V1Secret(
            api_version="v1",
            kind="Secret",
            metadata=client.V1ObjectMeta(name=secret_name),
            type="Opaque",
            string_data=data,
        )
        v1_client.create_namespaced_secret(namespace=namespace, body=secret_body)
        logger.info(f"Created new secret '{secret_name}'")
    except client.exceptions.ApiException as e:
        if e.status == 409:
            try:
                v1_client.patch_namespaced_secret(
                    name=secret_name, namespace=namespace, body={"stringData": data}
                )
                logger.info(f"Updated existing secret '{secret_name}'")
            except Exception as patch_error:
                error_msg = f"Failed to update secret '{secret_name}': {patch_error}"
                logger.error(error_msg)
                raise KubernetesResourceError(error_msg) from patch_error
        else:
            error_msg = f"Failed to create secret '{secret_name}': {e}"
            logger.error(error_msg)
            raise KubernetesResourceError(error_msg) from e


def main() -> None:
    """Main execution function."""
    try:
        # Load required configuration
        keycloak_realm = get_required_env("KEYCLOAK_REALM")
        namespace = get_required_env("NAMESPACE")
        client_id = get_required_env("CLIENT_ID")
        secret_name = get_required_env("SECRET_NAME")

        # Load optional configuration
        openshift_enabled = (
            get_optional_env("OPENSHIFT_ENABLED", "false").lower() == "true"
        )
        keycloak_namespace = get_optional_env(
            "KEYCLOAK_NAMESPACE", DEFAULT_KEYCLOAK_NAMESPACE
        )
        phoenix_namespace = get_optional_env(
            "PHOENIX_NAMESPACE", DEFAULT_PHOENIX_NAMESPACE
        )

        admin_secret_name = get_optional_env(
            "KEYCLOAK_ADMIN_SECRET_NAME", DEFAULT_ADMIN_SECRET_NAME
        )
        admin_username_key = get_optional_env(
            "KEYCLOAK_ADMIN_USERNAME_KEY", DEFAULT_ADMIN_USERNAME_KEY
        )
        admin_password_key = get_optional_env(
            "KEYCLOAK_ADMIN_PASSWORD_KEY", DEFAULT_ADMIN_PASSWORD_KEY
        )

        keycloak_admin_username = get_optional_env("KEYCLOAK_ADMIN_USERNAME")
        keycloak_admin_password = get_optional_env("KEYCLOAK_ADMIN_PASSWORD")
        ssl_cert_file = get_optional_env("SSL_CERT_FILE")

        # For vanilla k8s
        phoenix_url = get_optional_env("PHOENIX_URL")
        keycloak_url = get_optional_env("KEYCLOAK_URL")
        keycloak_public_url = get_optional_env("KEYCLOAK_PUBLIC_URL")

        # Connect to Kubernetes API
        if is_running_in_cluster():
            config.load_incluster_config()
        else:
            config.load_kube_config()

        v1_client = client.CoreV1Api()
        dyn_client = dynamic.DynamicClient(api_client.ApiClient())

        # Load Keycloak admin credentials
        if not keycloak_admin_username or not keycloak_admin_password:
            keycloak_admin_username, keycloak_admin_password = (
                read_keycloak_credentials(
                    v1_client,
                    admin_secret_name,
                    keycloak_namespace,
                    admin_username_key,
                    admin_password_key,
                )
            )

        if not keycloak_admin_username or not keycloak_admin_password:
            raise ConfigurationError(
                "Keycloak admin credentials must be provided via env vars or secret"
            )

        # Determine URLs based on environment
        if openshift_enabled:
            logger.info("OpenShift mode enabled, fetching routes...")

            keycloak_public_url = get_openshift_route_url(
                dyn_client, keycloak_namespace, DEFAULT_KEYCLOAK_ROUTE_NAME
            )
            logger.info(f"Keycloak public URL (route): {keycloak_public_url}")

            phoenix_url = get_openshift_route_url(
                dyn_client, phoenix_namespace, DEFAULT_PHOENIX_ROUTE_NAME
            )
            logger.info(f"Phoenix URL: {phoenix_url}")

            if keycloak_url:
                logger.info(
                    f"Using separate URLs - Internal: {keycloak_url}, "
                    f"External: {keycloak_public_url}"
                )
            else:
                keycloak_url = keycloak_public_url
                logger.info("KEYCLOAK_URL not set, using route URL for both endpoints")
        else:
            if not keycloak_url:
                raise ConfigurationError(
                    "KEYCLOAK_URL environment variable required for vanilla k8s mode"
                )
            if not phoenix_url:
                raise ConfigurationError(
                    "PHOENIX_URL environment variable required for vanilla k8s mode"
                )
            logger.info(
                f"Using provided URLs - Keycloak: {keycloak_url}, Phoenix: {phoenix_url}"
            )

            if not keycloak_public_url:
                keycloak_public_url = keycloak_url

        # Configure SSL verification
        verify_ssl = configure_ssl_verification(ssl_cert_file)

        # Initialize Keycloak admin client
        keycloak_admin = KeycloakAdmin(
            server_url=keycloak_url,
            username=keycloak_admin_username,
            password=keycloak_admin_password,
            realm_name=keycloak_realm,
            user_realm_name=DEFAULT_KEYCLOAK_REALM,
            verify=(verify_ssl if verify_ssl is not None else True),
        )

        # Phoenix OAuth2 redirect URI format
        # See: https://arize.com/docs/phoenix/self-hosting/features/authentication
        redirect_uri = f"{phoenix_url}/oauth2/keycloak/tokens"

        # Register confidential client
        internal_client_id, client_secret = register_confidential_client(
            keycloak_admin=keycloak_admin,
            client_id=client_id,
            root_url=phoenix_url,
            redirect_uri=redirect_uri,
        )

        # Construct OIDC config URL (well-known endpoint)
        oidc_config_url = (
            f"{keycloak_public_url}/realms/{keycloak_realm}/"
            ".well-known/openid-configuration"
        )

        logger.info("Phoenix OAuth Configuration:")
        logger.info(f"  CLIENT_ID: {client_id}")
        logger.info(f"  OIDC_CONFIG_URL: {oidc_config_url}")
        logger.info(f"  REDIRECT_URI: {redirect_uri}")

        # Get or generate PHOENIX_SECRET for JWT signing
        # Preserve existing secret to avoid invalidating existing JWTs
        import secrets as py_secrets

        phoenix_secret = None
        try:
            existing_secret = v1_client.read_namespaced_secret(
                name=secret_name, namespace=namespace
            )
            if existing_secret.data and "PHOENIX_SECRET" in existing_secret.data:
                phoenix_secret = base64.b64decode(
                    existing_secret.data["PHOENIX_SECRET"]
                ).decode("utf-8")
                logger.info("Using existing PHOENIX_SECRET from secret")
        except client.exceptions.ApiException as e:
            if e.status != 404:
                logger.warning(f"Error reading existing secret: {e}")

        if not phoenix_secret:
            phoenix_secret = py_secrets.token_urlsafe(32)
            logger.info("Generated new PHOENIX_SECRET")

        # Prepare secret data with Phoenix-expected environment variable names
        # See: https://arize.com/docs/phoenix/self-hosting/features/authentication
        secret_data = {
            # Required: Enable authentication
            "PHOENIX_ENABLE_AUTH": "true",
            # Required: Secret for JWT signing
            "PHOENIX_SECRET": phoenix_secret,
            # Phoenix OAuth2 environment variables
            "PHOENIX_OAUTH2_KEYCLOAK_CLIENT_ID": client_id,
            "PHOENIX_OAUTH2_KEYCLOAK_CLIENT_SECRET": client_secret,
            "PHOENIX_OAUTH2_KEYCLOAK_OIDC_CONFIG_URL": oidc_config_url,
            # Optional: Display name for login button
            "PHOENIX_OAUTH2_KEYCLOAK_DISPLAY_NAME": "Keycloak SSO",
            # Allow new users to sign up
            "PHOENIX_OAUTH2_KEYCLOAK_ALLOW_SIGN_UP": "true",
        }

        # Create or update Kubernetes secret
        create_or_update_secret(v1_client, namespace, secret_name, secret_data)

        logger.info("Phoenix OAuth secret creation completed successfully")

    except (ConfigurationError, KubernetesResourceError, KeycloakOperationError) as e:
        logger.error(f"Error: {e}")
        sys.exit(1)
    except Exception as e:
        logger.exception(f"Unexpected error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
