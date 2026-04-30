import logging
import sys
from typing import Dict
from keycloak import KeycloakAdmin
from keycloak.exceptions import KeycloakPostError
from kagenti.auth.shared_utils import register_client, get_session_lifetime_payload
from kubernetes import client, dynamic
from kubernetes.client import api_client

# Import common utilities
from common import (
    get_required_env,
    get_optional_env,
    load_kubernetes_config,
    read_keycloak_credentials,
    configure_ssl_verification,
)

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
# Local OAuth callback for CLI tools (e.g. agentik) — must match Keycloak valid redirect URIs
CLI_OAUTH_REDIRECT_URI = "http://127.0.0.1:8250/oauth/callback"
CLI_OAUTH_WEB_ORIGIN = "http://127.0.0.1:8250"
SERVICE_ACCOUNT_CA_PATH = "/var/run/secrets/kubernetes.io/serviceaccount/ca.crt"
DEFAULT_DEMO_USERS = ("bob", "alice")
DEFAULT_DEMO_PASSWORDS = ("kagenti1", "kagenti2")
DEFAULT_DEMO_PASSWORD_OVERRIDE_ENV_VARS = (
    "KEYCLOAK_DEMO1_PASSWORD",
    "KEYCLOAK_DEMO2_PASSWORD",
)


class ConfigurationError(Exception):
    """Raised when required configuration is missing or invalid."""

    pass


class KubernetesResourceError(Exception):
    """Raised when Kubernetes resource operations fail."""

    pass


class KeycloakOperationError(Exception):
    """Raised when Keycloak operations fail."""

    pass


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
        load_kubernetes_config()

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

        # Bootstrap realm and default user for non-master realms.
        # Controlled by AUTO_BOOTSTRAP_REALM (default: true).
        # Set to "false" in production to skip privileged operations.
        auto_bootstrap = (
            get_optional_env("AUTO_BOOTSTRAP_REALM", "true").lower() == "true"
        )

        if keycloak_realm != DEFAULT_KEYCLOAK_REALM and auto_bootstrap:
            logger.info(
                f"AUTO_BOOTSTRAP_REALM is enabled; ensuring realm '{keycloak_realm}' exists"
            )
            session_lifetimes = get_session_lifetime_payload()
            realm_payload = {
                "realm": keycloak_realm,
                "enabled": True,
                "registrationAllowed": False,
                **session_lifetimes,
            }

            try:
                # Create-first, catch-409: avoids the TOCTOU race of
                # get_realms → create when multiple job pods run concurrently.
                keycloak_admin.create_realm(payload=realm_payload)
                logger.info(
                    f"Created Keycloak realm '{keycloak_realm}' with session "
                    f"lifetimes: {session_lifetimes}"
                )
            except KeycloakPostError as e:
                if hasattr(e, "response_code") and e.response_code == 409:
                    logger.info(
                        f"Realm '{keycloak_realm}' already exists, "
                        f"updating session lifetimes"
                    )
                    try:
                        keycloak_admin.update_realm(keycloak_realm, realm_payload)
                    except Exception as update_err:
                        logger.warning(
                            f"Failed to update realm '{keycloak_realm}': "
                            f"{update_err}. Session lifetimes may not be configured."
                        )
                else:
                    logger.error(
                        f"Failed to bootstrap realm '{keycloak_realm}': {e}. "
                        "Ensure the Keycloak admin has realm-management permissions, "
                        "or set AUTO_BOOTSTRAP_REALM=false if the realm is "
                        "pre-provisioned."
                    )
                    raise
            except Exception as e:
                logger.error(
                    f"Failed to bootstrap realm '{keycloak_realm}': {e}. "
                    "Ensure the Keycloak admin has realm-management permissions, "
                    "or set AUTO_BOOTSTRAP_REALM=false if the realm is pre-provisioned."
                )
                raise

            # Create a default user so the UI has someone to log in as.
            # Uses the same credentials as the Keycloak admin.
            # Only creates if absent; never resets an existing user's password.
            # User creation is FATAL when bootstrap is enabled — without a
            # user the UI login will fail downstream.
            try:
                existing_users = keycloak_admin.get_users(
                    {"username": keycloak_admin_username}
                )
                if not existing_users:
                    user_id = keycloak_admin.create_user(
                        {
                            "username": keycloak_admin_username,
                            "enabled": True,
                            "email": f"{keycloak_admin_username}@localtest.me",
                            "emailVerified": True,
                            "firstName": keycloak_admin_username.capitalize(),
                            "lastName": "User",
                            "credentials": [
                                {
                                    "type": "password",
                                    "value": keycloak_admin_password,
                                    "temporary": False,
                                }
                            ],
                        }
                    )
                    logger.info(
                        f"Created default user '{keycloak_admin_username}' "
                        f"in realm '{keycloak_realm}'"
                    )
                else:
                    user_id = existing_users[0]["id"]
                    logger.info(
                        f"User '{keycloak_admin_username}' already exists "
                        f"in realm '{keycloak_realm}', ensuring roles"
                    )

                # Ensure realm-admin client role so the user can access
                # the Keycloak admin console for this realm.
                # Idempotent — Keycloak ignores duplicate role assignments.
                try:
                    realm_mgmt_client_id = keycloak_admin.get_client_id(
                        "realm-management"
                    )
                    realm_admin_role = keycloak_admin.get_client_role(
                        realm_mgmt_client_id, "realm-admin"
                    )
                    keycloak_admin.assign_client_role(
                        user_id, realm_mgmt_client_id, [realm_admin_role]
                    )
                    logger.info(
                        f"Ensured 'realm-admin' role for "
                        f"'{keycloak_admin_username}' in realm "
                        f"'{keycloak_realm}'"
                    )
                except Exception as role_err:
                    logger.warning(
                        f"Could not assign realm-admin role (non-fatal): {role_err}"
                    )

                # Ensure 'admin' realm role. The Kagenti backend maps this
                # to kagenti-admin (which inherits kagenti-operator and
                # kagenti-viewer) via a temporary mapping in auth.py until
                # proper realm roles are provisioned by a dedicated
                # Keycloak setup job.
                try:
                    try:
                        keycloak_admin.create_realm_role(
                            {
                                "name": "admin",
                                "description": (
                                    "Admin realm role for Kagenti backend RBAC mapping"
                                ),
                            }
                        )
                        logger.info(f"Created 'admin' realm role in '{keycloak_realm}'")
                    except Exception:
                        logger.info(
                            "'admin' realm role already exists, skipping creation"
                        )

                    admin_realm_role = keycloak_admin.get_realm_role("admin")
                    keycloak_admin.assign_realm_roles(user_id, [admin_realm_role])
                    logger.info(
                        f"Ensured 'admin' realm role for "
                        f"'{keycloak_admin_username}' in realm "
                        f"'{keycloak_realm}'"
                    )
                except Exception as role_err:
                    logger.warning(
                        f"Could not assign admin realm role (non-fatal): {role_err}"
                    )
            except Exception as e:
                logger.error(
                    f"Failed to provision default user in realm '{keycloak_realm}': {e}"
                )
                raise

            # Verify the bootstrap user exists — fail fast if missing
            # so we surface the root cause instead of downstream
            # "user_not_found" login errors.
            verification = keycloak_admin.get_users(
                {"username": keycloak_admin_username}
            )
            if not verification:
                raise KeycloakOperationError(
                    f"Bootstrap user '{keycloak_admin_username}' not found "
                    f"in realm '{keycloak_realm}' after bootstrap — "
                    f"cannot proceed"
                )

            # Create demo users for testing.
            # These get no realm-admin client role.
            for i, demo_username in enumerate(DEFAULT_DEMO_USERS):
                try:
                    existing = keycloak_admin.get_users(
                        {"username": demo_username, "exact": True}
                    )
                    if not existing:
                        keycloak_admin.create_user(
                            {
                                "username": demo_username,
                                "enabled": True,
                                "email": f"{demo_username}@localtest.me",
                                "emailVerified": True,
                                "firstName": demo_username.capitalize(),
                                "lastName": "User",
                                "credentials": [
                                    {
                                        "type": "password",
                                        "value": get_optional_env(
                                            DEFAULT_DEMO_PASSWORD_OVERRIDE_ENV_VARS[i],
                                            DEFAULT_DEMO_PASSWORDS[i],
                                        ),
                                        "temporary": False,
                                    }
                                ],
                            }
                        )
                        logger.info(
                            f"Created demo user '{demo_username}' "
                            f"in realm '{keycloak_realm}'"
                        )
                    else:
                        logger.info(
                            f"Demo user '{demo_username}' already exists "
                            f"in realm '{keycloak_realm}', skipping"
                        )
                except Exception as e:
                    logger.warning(f"Failed to create demo user '{demo_username}': {e}")

        elif keycloak_realm != DEFAULT_KEYCLOAK_REALM:
            logger.info(
                f"AUTO_BOOTSTRAP_REALM is disabled; assuming realm "
                f"'{keycloak_realm}' already exists"
            )

        enable_cli = get_optional_env("ENABLE_CLI", "true").lower() == "true"
        redirect_uris = [root_url + "/*"]
        web_origins = [root_url]
        if enable_cli:
            redirect_uris.append(CLI_OAUTH_REDIRECT_URI)
            web_origins.append(CLI_OAUTH_WEB_ORIGIN)
            logger.info(
                "ENABLE_CLI=true: adding CLI redirect URI %s", CLI_OAUTH_REDIRECT_URI
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
            "redirectUris": redirect_uris,
            "webOrigins": web_origins,
            "standardFlowEnabled": True,  # Authorization code flow
            "implicitFlowEnabled": False,  # Deprecated, use standard flow instead
            "directAccessGrantsEnabled": False,  # No password grant for SPAs
            "frontchannelLogout": True,
            "protocol": "openid-connect",
            "fullScopeAllowed": True,
            "attributes": {
                "pkce.code.challenge.method": "S256",  # Enable PKCE with S256
                "oauth2.device.authorization.grant.enabled": "true",  # Device code flow for TUI/CLI
            },
        }

        internal_client_id = register_client(keycloak_admin, client_id, client_payload)

        # Sync redirect URIs / web origins (covers upgrades and pre-existing clients)
        try:
            keycloak_admin.update_client(
                internal_client_id,
                {"redirectUris": redirect_uris, "webOrigins": web_origins},
            )
            logger.info("Updated Keycloak client redirect URIs and web origins")
        except Exception as upd_err:
            logger.warning(
                "Could not update client redirect URIs (client may still work if newly created): %s",
                upd_err,
            )

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
