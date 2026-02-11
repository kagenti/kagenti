# This file was modified with the assistance of Bob.
# Copyright 2025 IBM Corp.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import os
import time
import typer
from typing import Optional, Tuple
from kubernetes import client, config as kube_config
from kubernetes.client.rest import ApiException

from keycloak import KeycloakAdmin, KeycloakPostError

# Import common utilities
from common import (
    get_optional_env as _get_optional_env,
    read_keycloak_credentials as _read_keycloak_credentials,
    configure_ssl_verification as _configure_ssl_verification,
)


# Constants
DEFAULT_KEYCLOAK_NAMESPACE = "keycloak"
DEFAULT_ADMIN_SECRET_NAME = "keycloak-initial-admin"
DEFAULT_ADMIN_USERNAME_KEY = "username"
DEFAULT_ADMIN_PASSWORD_KEY = "password"
DEFAULT_SPIFFE_PREFIX = "spiffe://localtest.me/sa"


def get_optional_env(key: str, default: Optional[str] = None) -> Optional[str]:
    """Get an optional environment variable with optional default."""
    return _get_optional_env(key, default)


def read_keycloak_credentials(
    v1_api: client.CoreV1Api,
    credential_ref: str,
    namespace: str,
    username_key: str,
    password_key: str,
) -> Tuple[str, str]:
    """Read Keycloak admin credentials from a Kubernetes secret.

    Wrapper around common.read_keycloak_credentials that uses typer for output.
    """
    try:
        typer.echo(
            f"Reading Keycloak admin credentials from secret {credential_ref} in namespace {namespace}"
        )
        username, password = _read_keycloak_credentials(
            v1_api, credential_ref, namespace, username_key, password_key
        )
        typer.echo("Successfully read credentials from secret")
        return username, password
    except Exception as e:
        typer.secho(f"Error reading credentials: {e}", fg="red", err=True)
        raise


def configure_ssl_verification(ssl_cert_file: Optional[str]) -> Optional[str]:
    """Configure SSL verification based on certificate file availability.

    Wrapper around common.configure_ssl_verification that uses typer for output.
    """
    if ssl_cert_file:
        if os.path.exists(ssl_cert_file):
            typer.echo(f"Using SSL certificate file: {ssl_cert_file}")
            return ssl_cert_file
        else:
            typer.secho(
                f"Provided SSL_CERT_FILE '{ssl_cert_file}' does not exist. Falling back to system CA bundle.",
                fg="yellow",
            )
            return None

    typer.echo("No SSL_CERT_FILE provided - using system CA bundle for verification")
    return None


def parse_bool(value: Optional[str]) -> bool:
    """Parse common truthy strings to boolean.

    Accepts: '1', 'true', 'yes', 'on' (case-insensitive) as True.
    Anything else (including None) is False.
    """
    if not value:
        return False
    return str(value).strip().lower() in ("1", "true", "yes", "on")


def get_keycloak_env_config() -> Tuple[str, str, Optional[str], str]:
    """Read common Keycloak environment configuration values.

    Returns a tuple: (base_url, demo_realm_name, ssl_cert_file, spiffe_prefix)
    """
    base_url = get_optional_env(
        "KEYCLOAK_BASE_URL", "http://keycloak.localtest.me:8080"
    )
    demo_realm_name = get_optional_env("KEYCLOAK_DEMO_REALM", "demo")
    ssl_cert_file = get_optional_env("SSL_CERT_FILE")
    spiffe_prefix = get_optional_env("SPIFFE_PREFIX", DEFAULT_SPIFFE_PREFIX)

    return base_url, demo_realm_name, ssl_cert_file, spiffe_prefix


def get_keycloak_admin_credentials(
    v1_api: Optional[client.CoreV1Api] = None,
) -> Tuple[str, str]:
    """Compute Keycloak admin username/password the same way `setup_keycloak` did.

    Tries environment variables first (`KEYCLOAK_ADMIN_USERNAME`, `KEYCLOAK_ADMIN_PASSWORD`).
    If missing and `v1_api` is provided, tries to read the secret from Kubernetes.
    Falls back to ('admin', 'admin').
    """
    admin_username = get_optional_env("KEYCLOAK_ADMIN_USERNAME")
    admin_password = get_optional_env("KEYCLOAK_ADMIN_PASSWORD")

    if (not admin_username or not admin_password) and v1_api:
        keycloak_namespace = get_optional_env(
            "KEYCLOAK_NAMESPACE", DEFAULT_KEYCLOAK_NAMESPACE
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

        try:
            admin_username, admin_password = read_keycloak_credentials(
                v1_api,
                admin_secret_name,
                keycloak_namespace,
                admin_username_key,
                admin_password_key,
            )
        except Exception:
            typer.secho(
                "Failed to read credentials from secret, falling back to defaults",
                fg="yellow",
            )
            admin_username = admin_username or "admin"
            admin_password = admin_password or "admin"
    else:
        admin_username = admin_username or "admin"
        admin_password = admin_password or "admin"

    return admin_username, admin_password


class KeycloakSetup:
    def __init__(self, server_url, admin_username, admin_password, realm_name):
        self.server_url = server_url
        self.admin_username = admin_username
        self.admin_password = admin_password
        self.realm_name = realm_name
        self.verify_ssl = True  # Default to True, can be overridden

    def connect(self, timeout=120, interval=5):
        """
        Initializes the KeycloakAdmin client and verifies the connection.

        This method will poll the Keycloak server until a connection and
        authentication are successful, or until the timeout is reached.

        Args:
            timeout (int): The maximum time in seconds to wait for a connection.
            interval (int): The time in seconds to wait between connection attempts.

        Returns:
            bool: True if the connection was successful, False otherwise.
        """
        typer.echo("Attempting to connect to Keycloak...")
        start_time = time.monotonic()

        while time.monotonic() - start_time < timeout:
            try:
                # Instantiate the client on each attempt for a clean state
                self.keycloak_admin = KeycloakAdmin(
                    server_url=self.server_url,
                    username=self.admin_username,
                    password=self.admin_password,
                    realm_name="master",
                    user_realm_name="master",
                    verify=self.verify_ssl,
                )

                # This API call triggers the actual authentication.
                # If it succeeds, the server is ready.
                self.keycloak_admin.get_server_info()

                typer.echo("✅ Successfully connected and authenticated with Keycloak.")
                return True

            except KeycloakPostError as e:
                elapsed_time = int(time.monotonic() - start_time)
                typer.echo(
                    f"⏳ Connection failed ({type(e).__name__}). "
                    f"Retrying in {interval}s... ({elapsed_time}s/{timeout}s elapsed)"
                )
                time.sleep(interval)

        typer.echo(f"❌ Failed to connect to Keycloak after {timeout} seconds.")
        self.keycloak_admin = None  # Ensure no unusable client object is stored
        return False

    def create_realm(self):
        try:
            self.keycloak_admin.create_realm(
                payload={"realm": self.realm_name, "enabled": True}, skip_exists=False
            )
            typer.echo(f'Created realm "{self.realm_name}"')
        except KeycloakPostError as e:
            # Keycloak returns 409 if the realm already exists
            if hasattr(e, "response_code") and e.response_code == 409:
                typer.echo(f'Realm "{self.realm_name}" already exists')
            else:
                typer.echo(f'Failed to create realm "{self.realm_name}": {e}')
        except Exception as e:
            typer.echo(f'Unexpected error creating realm "{self.realm_name}": {e}')

    def create_user(self, username, password: Optional[str] = None):
        """Create a Keycloak user with the provided password.

        If `password` is None or empty the function will skip creation and
        emit a warning. This avoids hardcoding default passwords in source.
        """
        if not password:
            typer.secho(
                f"Skipping creation of user '{username}': no password provided",
                fg="yellow",
            )
            return

        try:
            self.keycloak_admin.create_user(
                {
                    "username": username,
                    "firstName": username,
                    "lastName": username,
                    "email": f"{username}@test.com",
                    "emailVerified": True,
                    "enabled": True,
                    "credentials": [{"value": password, "type": "password"}],
                }
            )
            typer.echo(f'Created user "{username}"')
        except KeycloakPostError:
            typer.echo(f'User "{username}" already exists')

    def create_client(self, app_name, spiffe_prefix):
        try:
            client_name = f"{spiffe_prefix}/{app_name}"
            client_id = self.keycloak_admin.create_client(
                {
                    "clientId": client_name,
                    "standardFlowEnabled": True,
                    "directAccessGrantsEnabled": True,
                    "fullScopeAllowed": True,
                    "enabled": True,
                }
            )
            typer.echo(f'Created client "{client_name}"')
            return client_id
        except KeycloakPostError:
            typer.echo(f'Client "{client_name}" already exists. Retrieving its ID.')
            client_id = self.keycloak_admin.get_client_id(client_id=client_name)
            typer.echo(
                f'Successfully retrieved ID for existing client "{client_name}".'
            )
            return client_id

    def get_client_secret(self, client_id):
        return self.keycloak_admin.get_client_secrets(client_id)["value"]


def setup_keycloak(v1_api: Optional[client.CoreV1Api] = None) -> str:
    """Setup keycloak and return client secret.

    Configuration is read from environment variables with sensible defaults:

    - `KEYCLOAK_BASE_URL` (default: "http://keycloak.localtest.me:8080")
    - `KEYCLOAK_ADMIN_USERNAME` (default: "admin") - can be read from secret if not provided
    - `KEYCLOAK_ADMIN_PASSWORD` (default: "admin") - can be read from secret if not provided
    - `KEYCLOAK_DEMO_REALM` (default: "demo")
    - `KAGENTI_KEYCLOAK_CLIENT_NAME` (default: "kagenti-keycloak-client")
    - `SSL_CERT_FILE` (optional) - path to custom SSL certificate for Keycloak connection
    - `KEYCLOAK_NAMESPACE` (default: "keycloak") - namespace where Keycloak admin secret exists
    - `KEYCLOAK_ADMIN_SECRET_NAME` (default: "keycloak-initial-admin") - secret containing credentials
    - `KEYCLOAK_ADMIN_USERNAME_KEY` (default: "username") - key in secret for username
    - `KEYCLOAK_ADMIN_PASSWORD_KEY` (default: "password") - key in secret for password
    - `SPIFFE_PREFIX` (default: "spiffe://localtest.me/sa") - SPIFFE ID prefix for client names

    Args:
        v1_api: Optional Kubernetes CoreV1Api client for reading secrets
    """
    base_url, demo_realm_name, ssl_cert_file, spiffe_prefix = get_keycloak_env_config()

    # Compute admin credentials consistently using helper
    admin_username, admin_password = get_keycloak_admin_credentials(v1_api)

    # Configure SSL verification
    verify_ssl = configure_ssl_verification(ssl_cert_file)

    setup = KeycloakSetup(base_url, admin_username, admin_password, demo_realm_name)
    # Pass verify parameter to KeycloakAdmin (will be used in connect method)
    setup.verify_ssl = verify_ssl if verify_ssl is not None else True
    if not setup.connect():
        typer.secho("Failed to connect to Keycloak", fg="red", err=True)
        raise typer.Exit(1)
    setup.create_realm()

    # Optionally create a demo/test user. Controlled by env var
    # `CREATE_KEYCLOAK_TEST_USER` (defaults to true for backwards compatibility).
    create_test_user = parse_bool(get_optional_env("CREATE_KEYCLOAK_TEST_USER", "true"))
    if create_test_user:
        test_user_name = get_optional_env("KEYCLOAK_TEST_USER_NAME", "test-user")
        test_user_password = get_optional_env("KEYCLOAK_TEST_USER_PASSWORD")
        if not test_user_password:
            typer.secho(
                "Environment variable KEYCLOAK_TEST_USER_PASSWORD not set; skipping test user creation",
                fg="yellow",
            )
        else:
            setup.create_user(test_user_name, test_user_password)
    else:
        typer.echo(
            "Skipping creation of Keycloak test user (CREATE_KEYCLOAK_TEST_USER=false)"
        )

    kagenti_keycloak_client_name = get_optional_env(
        "KAGENTI_KEYCLOAK_CLIENT_NAME", "kagenti-keycloak-client"
    )
    kagenti_keycloak_client_id = setup.create_client(
        kagenti_keycloak_client_name, spiffe_prefix
    )

    return setup.get_client_secret(kagenti_keycloak_client_id)


def create_secrets(**kwargs):
    """Create or update Keycloak client secrets in agent namespaces.

    Environment variables:
    - `AGENT_NAMESPACES` (required) - comma-separated list of namespaces
    - See setup_keycloak() docstring for Keycloak configuration variables
    """
    # Setup Kubernetes client first for potential secret reading
    try:
        cfg_mode = None
        # Prefer in-cluster configuration when running inside Kubernetes.
        try:
            kube_config.load_incluster_config()
            cfg_mode = "in-cluster"
        except Exception:
            # Fall back to local kubeconfig (developer machine)
            kube_config.load_kube_config()
            cfg_mode = "kube-config"

        v1_api = client.CoreV1Api()
        typer.echo(f"Using Kubernetes config: {cfg_mode}")
    except Exception as e:
        typer.secho(f"✗ Could not connect to Kubernetes: {e}", fg="red", err=True)
        raise typer.Exit(1)

    # Setup Keycloak demo realm, user, and agent client (pass v1_api for secret reading)
    kagenti_keycloak_client_secret = setup_keycloak(v1_api)

    # Optionally update the 'environments' ConfigMap in each namespace with Keycloak info
    update_envs = parse_bool(get_optional_env("UPDATE_ENV_CONFIGMAPS", "false"))
    typer.echo(f"Update environments ConfigMaps: {update_envs}")
    if update_envs:
        # Compute admin credentials to write into ConfigMaps
        admin_username, admin_password = get_keycloak_admin_credentials(v1_api)
        # Reuse shared env config to ensure consistency with setup_keycloak
        base_url, demo_realm_name, _, _ = get_keycloak_env_config()
        try:
            update_environments_configmaps(
                v1_api,
                admin_username,
                admin_password,
                base_url,
                demo_realm_name,
            )
        except Exception as e:
            typer.secho(f"Failed to update 'environments' ConfigMaps: {e}", fg="yellow")

    # Distribute client secret to agent namespaces
    namespaces_str = os.getenv("AGENT_NAMESPACES", "")
    if not namespaces_str:
        typer.echo("No AGENT_NAMESPACES set; skipping secret distribution")
        return

    agent_namespaces = [ns.strip() for ns in namespaces_str.split(",") if ns.strip()]

    kagenti_keycloak_secret_name = "kagenti-keycloak-client-secret"

    for ns in agent_namespaces:
        try:
            # Check if secret exists
            v1_api.read_namespaced_secret(kagenti_keycloak_secret_name, ns)
            # Secret exists -> patch its stringData (no base64 required)
            patch_body = {
                "stringData": {"client-secret": kagenti_keycloak_client_secret}
            }
            v1_api.patch_namespaced_secret(kagenti_keycloak_secret_name, ns, patch_body)
            typer.echo(
                f"🔄 Patched '{kagenti_keycloak_secret_name}' in namespace '{ns}'"
            )
        except ApiException as e:
            if e.status == 404:
                # Secret not found -> create it using string_data
                secret_body = client.V1Secret(
                    metadata=client.V1ObjectMeta(name=kagenti_keycloak_secret_name),
                    string_data={"client-secret": kagenti_keycloak_client_secret},
                )
                v1_api.create_namespaced_secret(ns, secret_body)
                typer.echo(f"Created '{kagenti_keycloak_secret_name}' in '{ns}'")
            else:
                typer.secho(
                    f"Failed to ensure secret in namespace '{ns}': {e}",
                    fg="red",
                    err=True,
                )
                raise


def update_environments_configmaps(
    v1_api: client.CoreV1Api,
    admin_username: str,
    admin_password: str,
    base_url: str,
    realm_name: str,
    timeout: int = 120,
    interval: int = 5,
) -> None:
    """Wait for and update the `environments` ConfigMap in each agent namespace.

    Writes the following keys into the ConfigMap `data`:
      - KEYCLOAK_URL
      - KEYCLOAK_REALM
      - KEYCLOAK_ADMIN_USERNAME
      - KEYCLOAK_ADMIN_PASSWORD

    The function will wait up to `timeout` seconds for the ConfigMap to exist in
    each namespace, polling every `interval` seconds.
    """
    namespaces_str = os.getenv("AGENT_NAMESPACES", "")
    if not namespaces_str:
        typer.echo("No AGENT_NAMESPACES set; skipping ConfigMap updates")
        return

    agent_namespaces = [ns.strip() for ns in namespaces_str.split(",") if ns.strip()]
    cm_name = "environments"

    for ns in agent_namespaces:
        typer.echo(
            f"Waiting for ConfigMap '{cm_name}' in namespace '{ns}' (timeout {timeout}s)..."
        )
        start_time = time.monotonic()
        cm = None
        while time.monotonic() - start_time < timeout:
            try:
                cm = v1_api.read_namespaced_config_map(cm_name, ns)
                break
            except ApiException as e:
                if getattr(e, "status", None) == 404:
                    time.sleep(interval)
                    continue
                else:
                    raise

        if cm is None:
            typer.secho(
                f"ConfigMap '{cm_name}' not found in namespace '{ns}' after {timeout}s; skipping",
                fg="yellow",
            )
            continue

        patch_body = {
            "data": {
                "KEYCLOAK_URL": base_url,
                "KEYCLOAK_REALM": realm_name,
                "KEYCLOAK_ADMIN_USERNAME": admin_username,
                "KEYCLOAK_ADMIN_PASSWORD": admin_password,
            }
        }

        try:
            v1_api.patch_namespaced_config_map(cm_name, ns, patch_body)
            typer.echo(
                f"Patched ConfigMap '{cm_name}' in namespace '{ns}' with Keycloak settings"
            )
        except ApiException as e:
            typer.secho(
                f"Failed to patch ConfigMap '{cm_name}' in '{ns}': {e}",
                fg="red",
                err=True,
            )
            raise


def main() -> None:
    """CLI entrypoint for the keycloak client helper.

    Runs the `create_secrets` flow which provisions/patches the Keycloak
    client secret into the namespaces defined by `AGENT_NAMESPACES`.
    """
    # Use Typer to provide a clean CLI interface and error handling.
    create_secrets()


if __name__ == "__main__":
    typer.run(main)
