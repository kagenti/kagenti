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

import time
from typing import Optional

from kubernetes import client, config
from kubernetes.client.exceptions import ApiException
from rich.console import Console

# --- Configuration ---
POLL_INTERVAL = 10
OPERATOR_GROUP = "operators.coreos.com"
OPERATOR_API_VERSION = "v1alpha1"


def verify_operator_installation(
    subscription_name: str,
    namespace: str,
    timeout_seconds: int = 300,
) -> bool:
    """
    Verifies that an Operator Lifecycle Manager (OLM) operator has been
    installed successfully by monitoring its Subscription and ClusterServiceVersion (CSV).

    This function uses the Kubernetes Python client to check the status of OLM
    custom resources.

    Args:
        subscription_name: The name of the operator's Subscription resource.
        namespace: The namespace where the operator is being installed.
        timeout_seconds: The maximum time in seconds to wait for the installation.

    Returns:
        True if the operator installed successfully within the timeout, False otherwise.
    """
    console = Console()
    try:
        # Load Kubernetes configuration from default location (e.g., ~/.kube/config)
        # or from within a cluster if running in a pod.
        config.load_kube_config()
    except config.ConfigException:
        print("Could not load kube config. Trying in-cluster config.")
        try:
            config.load_incluster_config()
        except config.ConfigException:
            print("Failed to load both local and in-cluster kube config. Aborting.")
            return None

    api = client.CustomObjectsApi()
    start_time = time.time()

    def has_timed_out() -> bool:
        """Checks if the operation has exceeded the timeout."""
        return time.time() - start_time > timeout_seconds

    # --- 1. Wait for the Subscription to report the ClusterServiceVersion (CSV) name ---
    csv_name: Optional[str] = None
    console.print(
        f"➡️  [bold yellow]Step 1/2:[/bold yellow] Waiting for Subscription "
        f"'{subscription_name}' to report its CSV..."
    )
    while not has_timed_out():
        try:
            sub = api.get_namespaced_custom_object(
                group=OPERATOR_GROUP,
                version=OPERATOR_API_VERSION,
                name=subscription_name,
                namespace=namespace,
                plural="subscriptions",
            )
            # Safely access nested status fields
            csv_name = sub.get("status", {}).get("currentCSV")
            if csv_name:
                console.print(
                    f"✅  [bold green]SUCCESS:[/bold green] Subscription is ready. "
                    f"Target CSV is: [bold cyan]{csv_name}[/bold cyan]"
                )
                break
        except ApiException as e:
            # This is expected if the Subscription hasn't been created yet
            if e.status != 404:
                console.log(
                    f"[bold red]API Error:[/bold red] Failed to get Subscription: {e.reason}"
                )
                return False

        console.print(
            f"   ... subscription not ready yet, waiting {POLL_INTERVAL}s..."
        )
        time.sleep(POLL_INTERVAL)

    if not csv_name:
        console.log(
            f"[bold red]FAILURE:[/bold red] Timed out waiting for Subscription "
            f"'{subscription_name}' to report a CSV."
        )
        return False

    # --- 2. Wait for the ClusterServiceVersion (CSV) to reach the 'Succeeded' phase ---
    console.print(
        f"\n➡️  [bold yellow]Step 2/2:[/bold yellow] Waiting for ClusterServiceVersion "
        f"'{csv_name}' to succeed..."
    )
    while not has_timed_out():
        try:
            csv = api.get_namespaced_custom_object(
                group=OPERATOR_GROUP,
                version=OPERATOR_API_VERSION,
                name=csv_name,
                namespace=namespace,
                plural="clusterserviceversions",
            )
            csv_phase = csv.get("status", {}).get("phase")

            if csv_phase == "Succeeded":
                console.print(
                    f"✅  [bold green]SUCCESS:[/bold green] CSV '{csv_name}' has succeeded."
                )
                console.print("\n🎉 [bold]Operator installation is complete.[/bold]")
                return True
            if csv_phase == "Failed":
                console.log(
                    f"[bold red]FAILURE:[/bold red] CSV '{csv_name}' is in 'Failed' phase. "
                    "Please investigate the operator logs."
                )
                return False

            console.print(
                f"   ... CSV phase is '[bold yellow]{csv_phase}[/bold yellow]', "
                f"waiting {POLL_INTERVAL}s..."
            )
        except ApiException as e:
            if e.status != 404:
                console.log(f"[bold red]API Error:[/bold red] Failed to get CSV: {e.reason}")
                return False

        time.sleep(POLL_INTERVAL)

    console.log(
        f"[bold red]FAILURE:[/bold red] Timed out waiting for CSV '{csv_name}' to succeed."
    )
    return False


def get_admitted_openshift_route_host(route_name: str, namespace: str, timeout_seconds: int = 180) -> str | None:
    """
    Waits for an OpenShift Route to have an 'Admitted' condition with status 'True'
    and then returns its host.

    This function polls the route's status periodically until the condition is met
    or until the timeout is reached.

    Args:
        route_name (str): The name of the OpenShift Route.
        namespace (str): The namespace where the Route is located.
        timeout_seconds (int): The maximum time in seconds to wait for the route
                               to become admitted. Defaults to 180.

    Returns:
        str | None: The value of .spec.host from the route if it becomes admitted
                    within the timeout period. Otherwise, returns None.
    
    Raises:
        ApiException: If there is an error communicating with the Kubernetes API,
                      other than a 404 Not Found error which is handled gracefully.
        Exception: For any other unexpected errors during the process.
    """
    try:
        # Load Kubernetes configuration from default location (e.g., ~/.kube/config)
        # or from within a cluster if running in a pod.
        config.load_kube_config()
    except config.ConfigException:
        print("Could not load kube config. Trying in-cluster config.")
        try:
            config.load_incluster_config()
        except config.ConfigException:
            print("Failed to load both local and in-cluster kube config. Aborting.")
            return None
        
    console = Console()

    # OpenShift Routes are accessed via the CustomObjectsApi
    api = client.CustomObjectsApi()
    
    # API group, version, and plural for OpenShift Routes
    group = 'route.openshift.io'
    version = 'v1'
    plural = 'routes'

    console.log(f"Waiting for route '{route_name}' in namespace '{namespace}' to be admitted...")

    start_time = time.time()
    while time.time() - start_time < timeout_seconds:
        try:
            # Fetch the specific route custom object
            route_obj = api.get_namespaced_custom_object(
                group=group,
                version=version,
                name=route_name,
                namespace=namespace,
                plural=plural
            )

            # Navigate the object to find the status conditions
            # The structure is status -> ingress -> conditions
            if 'status' in route_obj and 'ingress' in route_obj['status']:
                for ingress in route_obj['status']['ingress']:
                    if 'conditions' in ingress:
                        for condition in ingress['conditions']:
                            # Check for the specific condition type and status
                            if condition.get('type') == 'Admitted' and condition.get('status') == 'True':
                                host = route_obj.get('spec', {}).get('host')
                                if host:
                                    console.print(
                                        f"✅  [bold green]SUCCESS:[/bold green] Route '{route_name}' is admitted."
                                    )
                                    return host
                                else:
                                    console.log(f"[bold red]Error: Route '{route_name}' is admitted but has no .spec.host value.[/bold red]")
                                    return None
        
        except ApiException as e:
            # A 404 error is expected if the route hasn't been created yet, so we'll just wait.
            if e.status == 404:
                console.log(f"[bold yellow]: Route '{route_name}' not found yet. Retrying...[/bold yellow]")
            else:
                # For other API errors, we should raise the exception
                console.log(f"[bold red] API Error occurred: {e}[/bold red]")
                raise
        except Exception as e:
            console.log(f"[bold red] An unexpected error occurred: {e}[/bold red]")
            raise

        # Wait for a few seconds before the next poll
        time.sleep(5)

    console.log(f"[bold red]Timeout: Route '{route_name}' did not become admitted within {timeout_seconds} seconds.[/bold red]")
    return None