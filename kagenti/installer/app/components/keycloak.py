# Assisted by watsonx Code Assistant
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
import requests
from kubernetes import client, config as kube_config

from .. import config
from ..utils import console, run_command, secret_exists


import time
from keycloak import KeycloakAdmin, KeycloakPostError


class KeycloakSetup:
    def __init__(self, server_url, admin_username, admin_password, realm_name):
        self.server_url = server_url
        self.admin_username = admin_username
        self.admin_password = admin_password
        self.realm_name = realm_name

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
        print("Attempting to connect to Keycloak...")
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
                )

                # This API call triggers the actual authentication.
                # If it succeeds, the server is ready.
                self.keycloak_admin.get_server_info()

                print("✅ Successfully connected and authenticated with Keycloak.")
                return True

            except KeycloakPostError as e:
                elapsed_time = int(time.monotonic() - start_time)
                print(
                    f"⏳ Connection failed ({type(e).__name__}). "
                    f"Retrying in {interval}s... ({elapsed_time}s/{timeout}s elapsed)"
                )
                time.sleep(interval)

        print(f"❌ Failed to connect to Keycloak after {timeout} seconds.")
        self.keycloak_admin = None  # Ensure no unusable client object is stored
        return False

    def create_realm(self):
        try:
            self.keycloak_admin.create_realm(
                payload={"realm": self.realm_name, "enabled": True}, skip_exists=False
            )
            print(f'Created realm "{self.realm_name}"')
        except Exception as e:
            print(f'error creating realm "{self.realm_name}" - {e}')

    def create_user(self, username):
        try:
            self.keycloak_admin.create_user(
                {
                    "username": username,
                    "firstName": username,
                    "lastName": username,
                    "email": f"{username}@test.com",
                    "emailVerified": True,
                    "enabled": True,
                    "credentials": [{"value": "test-password", "type": "password"}],
                }
            )
            print(f'Created user "{username}"')
        except KeycloakPostError:
            print(f'User "{username}" already exists')

    def create_client(self, app_name):
        try:
            client_name = f"spiffe://localtest.me/sa/{app_name}"
            client_id = self.keycloak_admin.create_client(
                {
                    "clientId": client_name,
                    "standardFlowEnabled": True,
                    "directAccessGrantsEnabled": True,
                    "fullScopeAllowed": True,
                    "enabled": True,
                }
            )
            print(f'Created client "{client_name}"')
            return client_id
        except KeycloakPostError:
            print(f'Client "{client_name}" already exists. Retrieving its ID.')
            client_id = self.keycloak_admin.get_client_id(client_id=client_name)
            print(f'Successfully retrieved ID for existing client "{client_name}".')
            return client_id

    def get_client_secret(self, client_id):
        return self.keycloak_admin.get_client_secrets(client_id)["value"]


def setup_keycloak() -> str:
    """Setup keycloak and return client secret"""
    base_url = "http://keycloak.localtest.me:8080"
    admin_username = "admin"
    admin_password = "admin"
    demo_realm_name = "demo"

    setup = KeycloakSetup(base_url, admin_username, admin_password, demo_realm_name)
    setup.connect()
    setup.create_realm()

    test_user_name = "test-user"
    setup.create_user(test_user_name)

    external_agent_client_name = "slack-researcher"
    external_tool_client_name = "slack-tool"
    slack_agent_client_id = setup.create_client(external_agent_client_name)
    slack_tool_client_id = setup.create_client(external_tool_client_name)

    return (setup.get_client_secret(slack_agent_client_id), setup.get_client_secret(slack_tool_client_id))


def install():
    """Installs Keycloak, patches it for proxy headers, and runs initial setup."""
    run_command(
        [
            "kubectl",
            "apply",
            "-f",
            str(config.RESOURCES_DIR / "keycloak-namespace.yaml"),
        ],
        "Creating Keycloak namespace",
    )
    run_command(
        [
            "kubectl",
            "apply",
            "-n",
            "keycloak",
            "-f",
            str(config.RESOURCES_DIR / "keycloak.yaml"),
        ],
        "Deploying Keycloak with Postgres DB",
    )
    run_command(
        ["kubectl", "rollout", "status", "-n", "keycloak", "statefulset/postgres"],
        "Waiting for Postgres rollout",
    )
    run_command(
        ["kubectl", "rollout", "status", "-n", "keycloak", "statefulset/keycloak"],
        "Waiting for Keycloak rollout",
    )
    run_command(
        ["kubectl", "apply", "-f", str(config.RESOURCES_DIR / "keycloak-route.yaml")],
        "Applying Keycloak route",
    )
    run_command(
        [
            "kubectl",
            "label",
            "ns",
            "keycloak",
            "shared-gateway-access=true",
            "--overwrite",
        ],
        "Sharing gateway access for Keycloak",
    )
    run_command(
        [
            "kubectl",
            "label",
            "namespace",
            "keycloak",
            "istio.io/dataplane-mode=ambient",
            "--overwrite",
        ],
        "Adding Keycloak to Istio ambient mesh",
    )

    # Setup Keycloak demo realm, user, and agent client
    (slack_agent_client_secret, slack_tool_client_secret) = setup_keycloak()

    # Distribute client secret to agent namespaces
    namespaces_str = os.getenv("AGENT_NAMESPACES", "")
    if not namespaces_str:
        return

    agent_namespaces = [ns.strip() for ns in namespaces_str.split(",") if ns.strip()]
    try:
        kube_config.load_kube_config()
        v1_api = client.CoreV1Api()
    except Exception as e:
        console.log(
            f"[bold red]✗ Could not connect to Kubernetes to create secrets: {e}[/bold red]"
        )
        raise typer.Exit(1)

    for ns in agent_namespaces:
        if not secret_exists(v1_api, "slack-agent-client-secret", ns):
            run_command(
                [
                    "kubectl",
                    "create",
                    "secret",
                    "generic",
                    "slack-agent-client-secret",
                    f"--from-literal=client-secret={slack_agent_client_secret}",
                    "-n",
                    ns,
                ],
                f"Creating 'slack-agent-client-secret' in '{ns}'",
            )
        if not secret_exists(v1_api, "slack-tool-client-secret", ns):
            run_command(
                [
                    "kubectl",
                    "create",
                    "secret",
                    "generic",
                    "slack-tool-client-secret",
                    f"--from-literal=client-secret={slack_tool_client_secret}",
                    "-n",
                    ns,
                ],
                f"Creating 'slack-tool-client-secret' in '{ns}'",
            )
