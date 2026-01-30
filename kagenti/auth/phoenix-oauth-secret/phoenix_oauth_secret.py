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
        # Sanitize error message to avoid logging sensitive data
        error_msg = f"Could not fetch OpenShift route {route_name} in namespace {namespace}: {type(e).__name__}"
        logger.error(error_msg)
        raise KubernetesResourceError(error_msg) from e


def read_keycloak_credentials(
    v1_client: client.CoreV1Api,
    k8s_resource: str,
    namespace: str,
    user_key: str,
    pw_key: str,
) -> Tuple[str, str]:
    """Read Keycloak admin credentials from a Kubernetes secret.

    Args:
        v1_client: Kubernetes CoreV1Api client
        k8s_resource: Name of the Kubernetes Secret resource
        namespace: Namespace where the resource exists
        user_key: Key in data for username
        pw_key: Key in data for password

    Returns:
        Tuple of (username, password)
    """
    try:
        logger.info("Reading Keycloak admin credentials from K8s resource")
        k8s_data = v1_client.read_namespaced_secret(k8s_resource, namespace)

        if user_key not in k8s_data.data:
            raise KubernetesResourceError(
                "Keycloak admin resource missing required username key"
            )
        if pw_key not in k8s_data.data:
            raise KubernetesResourceError(
                "Keycloak admin resource missing required credential key"
            )

        # Decode credentials from K8s data
        decoded_user = base64.b64decode(k8s_data.data[user_key]).decode("utf-8").strip()
        decoded_cred = base64.b64decode(k8s_data.data[pw_key]).decode("utf-8").strip()

        logger.info("Successfully read credentials from K8s resource")
        return decoded_user, decoded_cred
    except client.exceptions.ApiException as e:
        # Sanitize error message to avoid logging sensitive data
        logger.error("Could not read Keycloak admin resource: status=%s", e.status)
        raise KubernetesResourceError(
            f"Could not read Keycloak admin resource: status={e.status}"
        ) from e


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

    Unlike public clients (SPAs), Phoenix needs a confidential client
    since it runs on the server and can securely store credentials.

    Args:
        keycloak_admin: Keycloak admin client
        client_id: Desired client ID
        root_url: Phoenix root URL
        redirect_uri: OAuth2 redirect URI

    Returns:
        Tuple of (internal_client_id, oidc_value)
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
        logger.info('Created Keycloak client "%s": %s', client_id, internal_client_id)
    except KeycloakPostError as e:
        # Log without sensitive details from exception
        logger.debug(
            'Keycloak client creation error for "%s": %s', client_id, type(e).__name__
        )

        try:
            error_json = json.loads(e.error_message)
            if error_json.get("errorMessage") == f"Client {client_id} already exists":
                internal_client_id = keycloak_admin.get_client_id(client_id)
                logger.info(
                    'Using existing Keycloak client "%s": %s',
                    client_id,
                    internal_client_id,
                )
            else:
                raise
        except (json.JSONDecodeError, KeyError, TypeError):
            # Sanitize error message to avoid logging sensitive data
            error_msg = f'Failed to create or retrieve Keycloak client "{client_id}"'
            logger.error(error_msg)
            raise KeycloakOperationError(error_msg) from e

    # Get or regenerate OIDC client credential for confidential client
    oidc_creds = keycloak_admin.get_client_secrets(internal_client_id)
    oidc_value = oidc_creds.get("value", "") if oidc_creds else ""

    if not oidc_value:
        # Regenerate if empty
        logger.info("Regenerating OIDC credential for client '%s'", client_id)
        new_creds = keycloak_admin.generate_client_secrets(internal_client_id)
        oidc_value = new_creds.get("value", "")

    if not oidc_value:
        raise KeycloakOperationError(
            f"Could not obtain OIDC credential for confidential client {client_id}"
        )

    logger.info("Successfully obtained OIDC credential for client '%s'", client_id)
    return internal_client_id, oidc_value


def create_or_update_k8s_resource(
    v1_client: client.CoreV1Api,
    namespace: str,
    resource_name: str,
    data: Dict[str, str],
) -> None:
    """Create or update a Kubernetes Secret resource.

    Args:
        v1_client: Kubernetes CoreV1Api client
        namespace: Target namespace
        resource_name: Name of the K8s Secret resource
        data: Data dictionary for the resource
    """
    try:
        resource_body = client.V1Secret(
            api_version="v1",
            kind="Secret",
            metadata=client.V1ObjectMeta(name=resource_name),
            type="Opaque",
            string_data=data,
        )
        v1_client.create_namespaced_secret(namespace=namespace, body=resource_body)
        logger.info("Created new K8s resource '%s'", resource_name)
    except client.exceptions.ApiException as e:
        if e.status == 409:
            try:
                v1_client.patch_namespaced_secret(
                    name=resource_name, namespace=namespace, body={"stringData": data}
                )
                logger.info("Updated existing K8s resource '%s'", resource_name)
            except Exception as patch_error:
                # Sanitize error message to avoid logging sensitive data
                error_msg = (
                    f"Failed to update K8s resource: {type(patch_error).__name__}"
                )
                logger.error(error_msg)
                raise KubernetesResourceError(error_msg) from patch_error
        else:
            # Sanitize error message to avoid logging sensitive data
            error_msg = f"Failed to create K8s resource: status={e.status}"
            logger.error(error_msg)
            raise KubernetesResourceError(error_msg) from e


def main() -> None:
    """Main execution function."""
    try:
        # Load required configuration
        keycloak_realm = get_required_env("KEYCLOAK_REALM")
        namespace = get_required_env("NAMESPACE")
        client_id = get_required_env("CLIENT_ID")
        output_resource = get_required_env("SECRET_NAME")

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

        admin_resource = get_optional_env(
            "KEYCLOAK_ADMIN_SECRET_NAME", DEFAULT_ADMIN_SECRET_NAME
        )
        admin_user_key = get_optional_env(
            "KEYCLOAK_ADMIN_USERNAME_KEY", DEFAULT_ADMIN_USERNAME_KEY
        )
        admin_pw_key = get_optional_env(
            "KEYCLOAK_ADMIN_PASSWORD_KEY", DEFAULT_ADMIN_PASSWORD_KEY
        )

        keycloak_admin_user = get_optional_env("KEYCLOAK_ADMIN_USERNAME")
        keycloak_admin_pw = get_optional_env("KEYCLOAK_ADMIN_PASSWORD")
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
        if not keycloak_admin_user or not keycloak_admin_pw:
            keycloak_admin_user, keycloak_admin_pw = read_keycloak_credentials(
                v1_client,
                admin_resource,
                keycloak_namespace,
                admin_user_key,
                admin_pw_key,
            )

        if not keycloak_admin_user or not keycloak_admin_pw:
            raise ConfigurationError(
                "Keycloak admin credentials must be provided via env vars or resource"
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
            username=keycloak_admin_user,
            password=keycloak_admin_pw,
            realm_name=keycloak_realm,
            user_realm_name=DEFAULT_KEYCLOAK_REALM,
            verify=(verify_ssl if verify_ssl is not None else True),
        )

        # Phoenix OAuth2 redirect URI format
        # See: https://arize.com/docs/phoenix/self-hosting/features/authentication
        redirect_uri = f"{phoenix_url}/oauth2/keycloak/tokens"

        # Register confidential client
        internal_client_id, oidc_client_value = register_confidential_client(
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
        # Preserve existing value to avoid invalidating existing JWTs
        import secrets as py_secrets

        phoenix_jwt_key = None
        try:
            existing_data = v1_client.read_namespaced_secret(
                name=output_resource, namespace=namespace
            )
            if existing_data.data and "PHOENIX_SECRET" in existing_data.data:
                phoenix_jwt_key = base64.b64decode(
                    existing_data.data["PHOENIX_SECRET"]
                ).decode("utf-8")
                logger.info("Using existing PHOENIX_SECRET from K8s resource")
        except client.exceptions.ApiException as e:
            if e.status != 404:
                logger.warning(
                    "Error reading existing K8s resource: status=%s", e.status
                )

        if not phoenix_jwt_key:
            phoenix_jwt_key = py_secrets.token_urlsafe(32)
            logger.info("Generated new PHOENIX_SECRET")

        # Prepare resource data with Phoenix-expected environment variable names
        # See: https://arize.com/docs/phoenix/self-hosting/features/authentication
        resource_data = {
            # Required: Enable authentication
            "PHOENIX_ENABLE_AUTH": "true",
            # Required: Key for JWT signing
            "PHOENIX_SECRET": phoenix_jwt_key,
            # Phoenix OAuth2 environment variables
            "PHOENIX_OAUTH2_KEYCLOAK_CLIENT_ID": client_id,
            "PHOENIX_OAUTH2_KEYCLOAK_CLIENT_SECRET": oidc_client_value,
            "PHOENIX_OAUTH2_KEYCLOAK_OIDC_CONFIG_URL": oidc_config_url,
            # Optional: Display name for login button
            "PHOENIX_OAUTH2_KEYCLOAK_DISPLAY_NAME": "Keycloak SSO",
            # Allow new users to sign up
            "PHOENIX_OAUTH2_KEYCLOAK_ALLOW_SIGN_UP": "true",
        }

        # Create or update Kubernetes resource
        create_or_update_k8s_resource(
            v1_client, namespace, output_resource, resource_data
        )

        logger.info("Phoenix OAuth resource creation completed successfully")

    except (ConfigurationError, KubernetesResourceError, KeycloakOperationError) as e:
        # Log error type without potentially sensitive details
        logger.error("Error: %s: %s", type(e).__name__, e)
        sys.exit(1)
    except Exception as e:
        # Log error type without potentially sensitive details
        logger.error("Unexpected error: %s", type(e).__name__)
        sys.exit(1)


if __name__ == "__main__":
    main()
