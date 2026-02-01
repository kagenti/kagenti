import json
import logging
import os
import sys
from typing import Optional, Dict, Any, Tuple, Union
from keycloak import KeycloakAdmin
from kagenti.auth.shared_utils import register_client
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
DEFAULT_UI_NAMESPACE = "kagenti-system"
DEFAULT_KEYCLOAK_ROUTE_NAME = "keycloak"
DEFAULT_UI_ROUTE_NAME = "kagenti-ui"
DEFAULT_KEYCLOAK_REALM = "master"
DEFAULT_ADMIN_SECRET_NAME = "keycloak-initial-admin"
DEFAULT_ADMIN_USERNAME_KEY = "username"
DEFAULT_ADMIN_PASSWORD_KEY = "password"
OAUTH_REDIRECT_PATH = "/"
OAUTH_SCOPE = "openid profile email"
SERVICE_ACCOUNT_CA_PATH = "/var/run/secrets/kubernetes.io/serviceaccount/ca.crt"


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
    """Get the URL for an OpenShift route.

    Args:
        dyn_client: Kubernetes dynamic client
        namespace: Namespace where the route exists
        route_name: Name of the route resource

    Returns:
        HTTPS URL for the route

    Raises:
        KubernetesResourceError: If route cannot be fetched
    """
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

        # Routes use edge TLS termination by default, so use https
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
    """Read Keycloak admin credentials from a Kubernetes secret.

    Args:
        v1_client: Kubernetes CoreV1Api client
        secret_name: Name of the secret
        namespace: Namespace where secret exists
        username_key: Key in secret data for username
        password_key: Key in secret data for password

    Returns:
        Tuple of (username, password)

    Raises:
        KubernetesResourceError: If secret cannot be read or keys are missing
    """
    try:
        logger.info(
            f"Reading Keycloak admin credentials from secret {secret_name} in namespace {namespace}"
        )
        secret = v1_client.read_namespaced_secret(secret_name, namespace)

        if username_key not in secret.data:
            raise KubernetesResourceError(
                f"Secret {secret_name} in namespace {namespace} missing key '{username_key}'"
            )
        if password_key not in secret.data:
            raise KubernetesResourceError(
                f"Secret {secret_name} in namespace {namespace} missing key '{password_key}'"
            )

        username = base64.b64decode(secret.data[username_key]).decode("utf-8").strip()
        password = base64.b64decode(secret.data[password_key]).decode("utf-8").strip()

        logger.info("Successfully read credentials from secret")
        return username, password
    except client.exceptions.ApiException as e:
        error_msg = f"Could not read Keycloak admin secret {secret_name} in namespace {namespace}: {e}"
        logger.error(error_msg)
        raise KubernetesResourceError(error_msg) from e
    except Exception as e:
        error_msg = f"Unexpected error reading secret: {e}"
        logger.error(error_msg)
        raise KubernetesResourceError(error_msg) from e


def configure_ssl_verification(ssl_cert_file: Optional[str]) -> Optional[str]:
    """Configure SSL verification based on certificate file availability.

    Behaviour:
    - If an explicit SSL_CERT_FILE path is provided and exists, return that path.
    - Otherwise return None, which indicates to callers that the default
      system CA bundle (requests/certifi) should be used.

    Returning None avoids incorrectly defaulting to the Kubernetes
    serviceaccount CA (which is for the API server) when verifying
    external TLS endpoints such as OpenShift routes.

    Args:
        ssl_cert_file: Path to SSL certificate file

    Returns:
        Path to cert file if available and exists, otherwise None
    """
    if ssl_cert_file:
        if os.path.exists(ssl_cert_file):
            logger.info(f"Using SSL certificate file: {ssl_cert_file}")
            return ssl_cert_file
        else:
            logger.warning(
                f"Provided SSL_CERT_FILE '{ssl_cert_file}' does not exist; falling back to system CA bundle"
            )

    # No explicit certificate provided or file missing: use system CA bundle
    logger.info("No SSL_CERT_FILE provided - using system CA bundle for verification")
    return None


def create_or_update_secret(
    v1_client: client.CoreV1Api, namespace: str, secret_name: str, data: Dict[str, str]
) -> None:
    """Create or update a Kubernetes secret.

    Args:
        v1_client: Kubernetes CoreV1Api client
        namespace: Target namespace
        secret_name: Name of the secret
        data: Secret data dictionary

    Raises:
        KubernetesResourceError: If secret creation/update fails
    """
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
            # Secret already exists, update it
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
        ui_namespace = get_optional_env("UI_NAMESPACE", DEFAULT_UI_NAMESPACE)

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

        # For backward compatibility with vanilla k8s
        root_url = get_optional_env("ROOT_URL")
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
                "Keycloak admin credentials must be provided via environment variables or secret"
            )

        # Determine URLs based on environment
        if openshift_enabled:
            logger.info("OpenShift mode enabled, fetching routes...")

            # In OpenShift, route URLs are public (external)
            keycloak_public_url = get_openshift_route_url(
                dyn_client, keycloak_namespace, DEFAULT_KEYCLOAK_ROUTE_NAME
            )
            logger.info(f"Keycloak public URL (route): {keycloak_public_url}")

            root_url = get_openshift_route_url(
                dyn_client, ui_namespace, DEFAULT_UI_ROUTE_NAME
            )
            logger.info(f"UI URL: {root_url}")

            # For OpenShift, use internal service URL for token exchange if KEYCLOAK_URL is provided
            # Otherwise, use the route URL for both (backward compatibility)
            if keycloak_url:
                logger.info(
                    f"Using separate URLs - Internal (token): {keycloak_url}, External (auth): {keycloak_public_url}"
                )
            else:
                keycloak_url = keycloak_public_url
                logger.info(
                    "KEYCLOAK_URL not set, using route URL for both auth and token endpoints"
                )
        else:
            # Vanilla Kubernetes mode - URLs must be provided
            if not keycloak_url:
                raise ConfigurationError(
                    "KEYCLOAK_URL environment variable required for vanilla k8s mode"
                )
            if not root_url:
                raise ConfigurationError(
                    "ROOT_URL environment variable required for vanilla k8s mode"
                )
            logger.info(
                f"Using provided URLs - Keycloak: {keycloak_url}, UI: {root_url}"
            )

            # If KEYCLOAK_PUBLIC_URL is not set, use KEYCLOAK_URL for both
            # Otherwise, KEYCLOAK_URL is internal (for token exchange), KEYCLOAK_PUBLIC_URL is external (for browser)
            if not keycloak_public_url:
                keycloak_public_url = keycloak_url
                logger.info(
                    "KEYCLOAK_PUBLIC_URL not set, using KEYCLOAK_URL for both auth and token endpoints"
                )
            else:
                logger.info(
                    f"Using separate URLs - Internal (token): {keycloak_url}, External (auth): {keycloak_public_url}"
                )

        # Configure SSL verification. If configure_ssl_verification returns None
        # we want KeycloakAdmin/requests to use the default system CA bundle
        # (i.e. the certifi bundle used by requests). If a path is returned,
        # pass it through to requests so that a custom CA bundle will be used.
        verify_ssl = configure_ssl_verification(ssl_cert_file)

        # Initialize Keycloak admin client. If verify_ssl is None then let
        # the Keycloak client use the default verification behaviour (True).
        keycloak_admin = KeycloakAdmin(
            server_url=keycloak_url,
            username=keycloak_admin_username,
            password=keycloak_admin_password,
            realm_name=keycloak_realm,
            user_realm_name=DEFAULT_KEYCLOAK_REALM,
            verify=(verify_ssl if verify_ssl is not None else True),
        )

        # Register client
        # Configure as public client with PKCE for SPA best practices
        # Public clients don't use client secrets (can't be kept confidential in browser)
        # PKCE (S256) provides security for the authorization code flow
        client_payload = {
            "clientId": client_id,
            "name": client_id,
            "description": "Kagenti UI - Public SPA client with PKCE",
            "rootUrl": root_url,
            "adminUrl": root_url,
            "baseUrl": "",
            "enabled": True,
            "publicClient": True,  # Public client - no client secret
            "redirectUris": [root_url + "/*"],
            "webOrigins": [root_url],
            "standardFlowEnabled": True,  # Authorization code flow
            "implicitFlowEnabled": False,  # Deprecated, use standard flow instead
            "directAccessGrantsEnabled": False,  # No password grant for SPAs
            "frontchannelLogout": True,
            "protocol": "openid-connect",
            "fullScopeAllowed": True,
            "attributes": {
                "pkce.code.challenge.method": "S256"  # Enable PKCE with S256
            },
        }

        internal_client_id = register_client(keycloak_admin, client_id, client_payload)

        # Get client secret (will be empty for public clients, but kept for backward compatibility)
        # Public clients don't have secrets, so this will return empty
        secrets = keycloak_admin.get_client_secrets(internal_client_id)
        client_secret = secrets.get("value", "") if secrets else ""

        if not client_secret:
            logger.info(
                f"Client {client_id} is a public client (no secret) - this is expected for SPAs with PKCE"
            )

        # Construct OAuth endpoints
        # AUTH_ENDPOINT uses public URL for browser redirects
        # TOKEN_ENDPOINT uses internal URL for server-to-server calls
        auth_endpoint_url = keycloak_public_url if keycloak_public_url else keycloak_url
        auth_endpoint = (
            f"{auth_endpoint_url}/realms/{keycloak_realm}/protocol/openid-connect/auth"
        )
        token_endpoint = (
            f"{keycloak_url}/realms/{keycloak_realm}/protocol/openid-connect/token"
        )
        redirect_uri = f"{root_url}{OAUTH_REDIRECT_PATH}"

        logger.info("OAuth Configuration:")
        logger.info(f"  AUTH_ENDPOINT: {auth_endpoint}")
        logger.info(f"  TOKEN_ENDPOINT: {token_endpoint}")
        logger.info(f"  REDIRECT_URI: {redirect_uri}")

        # Prepare secret data
        # For the created secret expose the cert path if an explicit file was
        # configured; otherwise set an empty value so downstream consumers
        # know to use the system CA bundle.
        secret_data = {
            "ENABLE_AUTH": "true",
            "CLIENT_SECRET": client_secret,
            "CLIENT_ID": client_id,
            "AUTH_ENDPOINT": auth_endpoint,
            "TOKEN_ENDPOINT": token_endpoint,
            "REDIRECT_URI": redirect_uri,
            "SCOPE": OAUTH_SCOPE,
            "SSL_CERT_FILE": verify_ssl if verify_ssl is not None else "",
        }

        # Create or update Kubernetes secret
        create_or_update_secret(v1_client, namespace, secret_name, secret_data)

        logger.info("OAuth secret creation completed successfully")

    except (ConfigurationError, KubernetesResourceError, KeycloakOperationError) as e:
        logger.error(f"Error: {e}")
        sys.exit(1)
    except Exception as e:
        logger.exception(f"Unexpected error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
