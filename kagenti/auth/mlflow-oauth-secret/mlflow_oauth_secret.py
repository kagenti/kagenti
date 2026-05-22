"""MLflow OAuth Secret Generator for Keycloak Integration.

Reads the pre-existing 'mlflow' confidential client from Keycloak (created via
realm import) and writes its credentials into a Kubernetes secret for the
mlflow-oidc-auth plugin and the OTel collector OAuth2 extension.

The mlflow client MUST already exist in the Keycloak realm — this script does
NOT create it.  If the client is missing the script fails immediately.

MLflow uses the mlflow-oidc-auth plugin for OAuth authentication, which expects:
- OIDC_PROVIDER_DISPLAY_NAME
- OIDC_CLIENT_ID
- OIDC_CLIENT_SECRET
- OIDC_DISCOVERY_URL
- OIDC_REDIRECT_URI

See: https://pypi.org/project/mlflow-oidc-auth/
"""

import base64
import logging
import os
import sys
import time
from typing import Dict, Optional, Tuple

from keycloak import KeycloakAdmin
from kubernetes import client, config, dynamic
from kubernetes.client import api_client

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Constants
DEFAULT_KEYCLOAK_NAMESPACE = "keycloak"
DEFAULT_MLFLOW_NAMESPACE = "kagenti-system"
DEFAULT_KEYCLOAK_ROUTE_NAME = "keycloak"
DEFAULT_MLFLOW_ROUTE_NAME = "mlflow"
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
    """Read Keycloak admin credentials from a Kubernetes secret."""
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

        decoded_user = base64.b64decode(k8s_data.data[user_key]).decode("utf-8").strip()
        decoded_cred = base64.b64decode(k8s_data.data[pw_key]).decode("utf-8").strip()

        logger.info("Successfully read credentials from K8s resource")
        return decoded_user, decoded_cred
    except client.exceptions.ApiException as e:
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


def read_client_secret(
    keycloak_admin: KeycloakAdmin,
    client_id: str,
    wait_timeout: int = 120,
    poll_interval: int = 5,
) -> Tuple[str, str]:
    """Read the secret for an existing Keycloak confidential client.

    The client is created via the Keycloak realm import (KeycloakRealmImport
    CR on OpenShift, ConfigMap on Kind). Because the realm import is processed
    asynchronously, this function polls until the client appears or the
    timeout is reached.

    Returns:
        Tuple of (internal_client_uuid, client_secret_value)
    """
    deadline = time.time() + wait_timeout
    internal_id = None

    while True:
        internal_id = keycloak_admin.get_client_id(client_id)
        if internal_id:
            break
        if time.time() >= deadline:
            raise KeycloakOperationError(
                f"Keycloak client '{client_id}' not found after {wait_timeout}s. "
                "It must be created via the Keycloak realm import."
            )
        logger.info(
            "Waiting for client '%s' to appear (realm import in progress)...",
            client_id,
        )
        time.sleep(poll_interval)

    logger.info("Found existing Keycloak client '%s': %s", client_id, internal_id)

    oidc_creds = keycloak_admin.get_client_secrets(internal_id)
    secret_value = oidc_creds.get("value", "") if oidc_creds else ""

    if not secret_value:
        # Keycloak may not auto-generate a secret during realm import in all
        # versions. Regenerate as a defensive measure — this is a Keycloak API
        # write, but it's idempotent and only triggers when the secret is empty.
        logger.info("Regenerating secret for client '%s'", client_id)
        new_creds = keycloak_admin.generate_client_secrets(internal_id)
        secret_value = new_creds.get("value", "")

    if not secret_value:
        raise KeycloakOperationError(
            f"Could not obtain secret for confidential client '{client_id}'"
        )

    logger.info("Successfully obtained secret for client '%s'", client_id)
    return internal_id, secret_value


def create_or_update_k8s_resource(
    v1_client: client.CoreV1Api,
    namespace: str,
    resource_name: str,
    data: Dict[str, str],
) -> None:
    """Create or update a Kubernetes Secret resource."""
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
                error_msg = (
                    f"Failed to update K8s resource: {type(patch_error).__name__}"
                )
                logger.error(error_msg)
                raise KubernetesResourceError(error_msg) from patch_error
        else:
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
        mlflow_namespace = get_optional_env(
            "MLFLOW_NAMESPACE", DEFAULT_MLFLOW_NAMESPACE
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
        mlflow_url = get_optional_env("MLFLOW_URL")
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

            mlflow_url = get_openshift_route_url(
                dyn_client, mlflow_namespace, DEFAULT_MLFLOW_ROUTE_NAME
            )
            logger.info(f"MLflow URL: {mlflow_url}")

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
            if not mlflow_url:
                raise ConfigurationError(
                    "MLFLOW_URL environment variable required for vanilla k8s mode"
                )
            logger.info(
                f"Using provided URLs - Keycloak: {keycloak_url}, MLflow: {mlflow_url}"
            )

            if not keycloak_public_url:
                keycloak_public_url = keycloak_url

        # Configure SSL verification
        verify_ssl = configure_ssl_verification(ssl_cert_file)

        # Initialize Keycloak admin client
        kc_admin = KeycloakAdmin(
            server_url=keycloak_url,
            username=keycloak_admin_user,
            password=keycloak_admin_pw,
            realm_name=keycloak_realm,
            user_realm_name=DEFAULT_KEYCLOAK_REALM,
            verify=(verify_ssl if verify_ssl is not None else True),
        )

        # Read the existing mlflow client secret (client created via realm import)
        redirect_uri = f"{mlflow_url}/callback"
        _, oidc_client_value = read_client_secret(kc_admin, client_id)

        # Construct OIDC URLs
        # Use the internal Keycloak URL so MLflow can fetch the discovery
        # document server-side. The response contains the public
        # authorization_endpoint (set by KC_HOSTNAME) for browser redirects.
        oidc_discovery_url = (
            f"{keycloak_url}/realms/{keycloak_realm}/.well-known/openid-configuration"
        )
        oidc_token_url = (
            f"{keycloak_url}/realms/{keycloak_realm}/protocol/openid-connect/token"
        )

        logger.info("MLflow OAuth Configuration:")
        logger.info(f"  CLIENT_ID: {client_id}")
        logger.info(f"  OIDC_DISCOVERY_URL: {oidc_discovery_url}")
        logger.info(f"  REDIRECT_URI: {redirect_uri}")

        # Write K8s secret with mlflow-oidc-auth environment variables
        resource_data = {
            "MLFLOW_AUTH_ENABLED": "true",
            "OIDC_PROVIDER_DISPLAY_NAME": "Keycloak SSO",
            "OIDC_CLIENT_ID": client_id,
            "OIDC_CLIENT_SECRET": oidc_client_value,
            "OIDC_DISCOVERY_URL": oidc_discovery_url,
            "OIDC_TOKEN_URL": oidc_token_url,
            "OIDC_REDIRECT_URI": redirect_uri,
            "OIDC_SCOPE": "openid email profile",
            "OIDC_GROUPS_CLAIM": "groups",
        }

        create_or_update_k8s_resource(
            v1_client, namespace, output_resource, resource_data
        )

        logger.info("MLflow OAuth resource creation completed successfully")

    except (ConfigurationError, KubernetesResourceError, KeycloakOperationError) as e:
        logger.error(f"Error: {type(e).__name__}: {e}")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Unexpected error: {type(e).__name__}")
        sys.exit(1)


if __name__ == "__main__":
    main()
