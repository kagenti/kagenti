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

"""
Kubernetes configuration
"""

import os
import logging
from typing import Tuple, Optional, Any, List, Dict
import base64  # For decoding secret data
import json
import time
import streamlit as st
import kubernetes.client
import kubernetes.config
from . import constants

logger = logging.getLogger(__name__)


# --- Kubernetes Configuration ---
@st.cache_resource
def get_kube_api_client_cached() -> (
    Tuple[Optional[kubernetes.client.ApiClient], Optional[str], Optional[str]]
):
    """
    Loads Kubernetes configuration and returns an ApiClient,
    along with a status message and icon for UI feedback.
    Caches the ApiClient for efficiency.
    """
    try:
        if os.getenv("KUBERNETES_SERVICE_HOST") and os.getenv(
            "KUBERNETES_SERVICE_PORT"
        ):
            logger.info("KUBERNETES_SERVICE_HOST found, attempting in-cluster config.")
            kubernetes.config.load_incluster_config()
            return (
                kubernetes.client.ApiClient(),
                "✅ Loaded in-cluster K8s config.",
                "🎉",
            )

        logger.info("KUBERNETES_SERVICE_HOST not found, attempting kubeconfig.")
        raise kubernetes.config.ConfigException(
            "Not an in-cluster environment based on env vars."
        )
    except kubernetes.config.ConfigException:
        try:
            kubernetes.config.load_kube_config()
            return (
                kubernetes.client.ApiClient(),
                "✅ Loaded K8s kubeconfig (local).",
                "📄",
            )
        except kubernetes.config.ConfigException as e:
            logger.error(
                f"K8s Config Error: {e}. Ensure valid kubeconfig or in-cluster execution."
            )
            return (
                None,
                f"K8s Config Error: {e}. Ensure valid kubeconfig or in-cluster execution.",
                "⚠️",
            )
    except Exception as e:
        logger.error(f"Unexpected Kubernetes configuration error: {e}", exc_info=True)
        return None, f"Unexpected error loading K8s config: {e}", "💥"


def _display_kube_config_status_once(
    message: Optional[str], icon: Optional[str], success: bool
):
    """Helper to display toast/error for kube config status only once per unique message."""
    if not message:  # If no message, nothing to show
        return

    if "kube_config_status_shown" not in st.session_state:
        st.session_state.kube_config_status_shown = {"message": None}

    # Show message if it's new or if it's an error (errors should always be visible)
    if st.session_state.kube_config_status_shown["message"] != message or not success:
        if success:
            st.toast(message, icon=icon)
        else:
            st.error(message)  # Display errors from loading more prominently
        st.session_state.kube_config_status_shown["message"] = message


def get_custom_objects_api() -> Optional[kubernetes.client.CustomObjectsApi]:
    """Gets the Kubernetes CustomObjectsApi client and ensures config status is displayed."""
    api_client_instance, message, icon = get_kube_api_client_cached()
    _display_kube_config_status_once(message, icon, bool(api_client_instance))

    if not api_client_instance:
        # Error already displayed by _display_kube_config_status_once if message was present
        return None
    return kubernetes.client.CustomObjectsApi(api_client_instance)


def get_core_v1_api() -> Optional[kubernetes.client.CoreV1Api]:
    """Gets the Kubernetes CoreV1Api client and ensures config status is displayed."""
    api_client_instance, message, icon = get_kube_api_client_cached()
    _display_kube_config_status_once(message, icon, bool(api_client_instance))

    if not api_client_instance:
        return None
    return kubernetes.client.CoreV1Api(api_client_instance)


def get_all_namespaces(
    generic_api_client: Optional[kubernetes.client.ApiClient],
    label_selector: Optional[str] = None,
) -> List[str]:
    """Lists all namespaces the current user has access to."""
    default_fallback = ["default"]  # Define fallback
    if not generic_api_client:
        logger.warning(
            "Cannot list namespaces: Generic ApiClient not available (likely K8s connection issue)."
        )
        return default_fallback

    v1_api_for_ns = kubernetes.client.CoreV1Api(generic_api_client)
    try:
        namespaces_response = v1_api_for_ns.list_namespace(
            label_selector=label_selector, timeout_seconds=5
        )
        # Ensure metadata and name exist before trying to access
        names = [
            ns.metadata.name
            for ns in namespaces_response.items
            if ns.metadata and ns.metadata.name
        ]
        if (
            not names
        ):  # If list is empty (e.g. permissions allow listing but returns no items)
            logger.info(
                "list_namespace returned empty list of items, or items without names."
            )
            return default_fallback
        return sorted(names)
    except kubernetes.client.ApiException as e:
        logger.error(f"API Error listing namespaces: {e}")
        st.toast(
            f"Warning: Could not list all namespaces (API Error: {e.status}). Check K8s permissions.",
            icon="⚠️",
        )
        return default_fallback
    except Exception as e:
        logger.error(f"Unexpected error listing namespaces: {e}", exc_info=True)
        st.toast("Warning: Unexpected error listing namespaces.", icon="⚠️")
        return default_fallback


def get_enabled_namespaces(
    generic_api_client: Optional[kubernetes.client.ApiClient],
) -> List[str]:
    """Lists all enabled namespaces for listing or deploying agents/tools."""
    selector = f"{constants.ENABLED_NAMESPACE_LABEL_KEY}={constants.ENABLED_NAMESPACE_LABEL_VALUE}"
    return get_all_namespaces(generic_api_client, label_selector=selector)


def get_secret_data(
    core_v1_api: Optional[kubernetes.client.CoreV1Api],
    namespace: str,
    secret_name: str,
    data_key: str,
) -> Optional[str]:
    """Fetches and decodes a specific key from a Kubernetes secret."""
    if not core_v1_api:
        logger.error("CoreV1Api not available, cannot fetch secret data.")
        return None
    try:
        logger.info(
            f"Attempting to read secret '{secret_name}' in namespace '{namespace}' for key '{data_key}'."
        )
        secret = core_v1_api.read_namespaced_secret(
            name=secret_name, namespace=namespace
        )
        if secret.data and data_key in secret.data:
            encoded_data = secret.data[data_key]
            decoded_data = base64.b64decode(encoded_data).decode("utf-8").strip()
            logger.info(
                f"Successfully fetched and decoded key '{data_key}' from secret '{secret_name}'."
            )
            return decoded_data

        logger.warning(
            # pylint: disable=line-too-long
            f"Key '{data_key}' not found in secret '{secret_name}' in namespace '{namespace}'. Data keys: {list(secret.data.keys()) if secret.data else 'None'}"
        )
        return None
    except kubernetes.client.ApiException as e:
        if e.status == 404:
            logger.warning(
                f"Secret '{secret_name}' not found in namespace '{namespace}'."
            )
        else:
            logger.error(
                f"ApiException when reading secret '{secret_name}' in ns '{namespace}': {e.status} - {e.reason}"
            )
        return None
    except Exception as e:
        logger.error(
            f"Unexpected error reading secret '{secret_name}' in ns '{namespace}': {e}",
            exc_info=True,
        )
        return None


def get_config_map_data(
    core_v1_api: Optional[kubernetes.client.CoreV1Api],
    namespace: str,
    config_map_name: str,
) -> Optional[Dict[str, Any]]:
    """Fetches and parses all data from a Kubernetes ConfigMap."""
    if not core_v1_api:
        logger.error("CoreV1Api not available, cannot fetch ConfigMap data.")
        return None
    try:
        logger.info(
            f"Attempting to read ConfigMap '{config_map_name}' in namespace '{namespace}'."
        )
        config_map = core_v1_api.read_namespaced_config_map(
            name=config_map_name, namespace=namespace
        )
        if not config_map.data:
            logger.warning(
                f"ConfigMap '{config_map_name}' in namespace '{namespace}' has no data."
            )
            return {}

        parsed_data = {}
        for key, value in config_map.data.items():
            try:
                parsed_data[key] = json.loads(value)
            except json.JSONDecodeError:
                # if not json, just store raw string
                parsed_data[key] = value

        logger.info(
            f"Successfully fetched and parsed data from ConfigMap '{config_map_name}'."
        )
        return parsed_data
    except kubernetes.client.ApiException as e:
        if e.status == 404:
            logger.warning(
                f"ConfigMap '{config_map_name}' not found in namespace '{namespace}'."
            )
            st.toast(
                f"Optional ConfigMap '{config_map_name}' not found in namespace '{namespace}'.",
                icon="ℹ️",
            )
        else:
            logger.error(
                f"ApiException when reading ConfigMap '{config_map_name}' in ns '{namespace}': {e.status} - {e.reason}"
            )
        return None
    except Exception as e:
        logger.error(
            f"Unexpected error reading ConfigMap '{config_map_name}' in ns '{namespace}': {e}",
            exc_info=True,
        )
        st.error(
            "An unexpected error occurred while fetching the environments ConfigMap."
        )
        return None


def is_running_in_cluster() -> bool:
    """Is UI executing from a Kubernetes cluster?"""
    return bool(os.getenv("KUBERNETES_SERVICE_HOST"))


def _handle_kube_api_exception(st_object, e, resource_name, action="fetching"):
    if hasattr(e, "status"):
        if e.status == 404:
            st_object.warning(
                f"{resource_name} not found. CRD installed? Namespace correct?"
            )
        elif e.status == 403:
            st_object.warning(
                f"Permission denied {action} {resource_name}. Check RBAC."
            )
        else:
            st_object.error(
                f"Error {action} {resource_name}: {e.reason if hasattr(e, 'reason') else str(e)} (Status: {e.status})"
            )
        if hasattr(e, "body"):
            try:
                st_object.code(e.body, language="json")
            except:  # pylint: disable=bare-except
                st_object.text(f"Raw error body: {e.body}")
    else:
        st_object.error(f"An unexpected error occurred {action} {resource_name}: {e}")


def is_deployment_ready(resource_data: dict) -> str:
    """Is a deployment ready?"""
    if not isinstance(resource_data, dict):
        return "Unknown"
    conditions = resource_data.get("status", {}).get("conditions", [])
    if not isinstance(conditions, list):
        return "Not Ready"
    for condition in conditions:
        if not isinstance(condition, dict):
            continue
        if (
            condition.get("reason") == "Ready"
            and condition.get("type") == "Ready"
            and condition.get("status") == "True"
        ):
            return "Ready"
    return "Not Ready"


# pylint: disable=too-many-arguments, too-many-positional-arguments
def list_custom_resources(
    st_object,
    custom_obj_api: Optional[kubernetes.client.CustomObjectsApi],
    group: str,
    version: str,
    namespace: str,
    plural: str,
    label_selector: str = None,
):
    """List custom resources"""
    if not custom_obj_api:
        st_object.error("Kubernetes CustomObjectsApi client not initialized.")
        return []
    try:
        logger.info(
            f"Listing {plural} in ns '{namespace}' with selector '{label_selector}'"
        )
        api_response = custom_obj_api.list_namespaced_custom_object(
            group=group,
            version=version,
            namespace=namespace,
            plural=plural,
            label_selector=label_selector,
        )
        return api_response.get("items", [])
    except kubernetes.client.ApiException as e:
        _handle_kube_api_exception(st_object, e, plural, action="listing")
        return []
    except Exception as e:
        st_object.error(f"An unexpected error occurred while listing {plural}: {e}")
        logger.error(
            f"Unexpected error listing {plural} in ns '{namespace}': {e}", exc_info=True
        )
        return []


def get_custom_resource(
    st_object,
    custom_obj_api: Optional[kubernetes.client.CustomObjectsApi],
    group: str,
    version: str,
    namespace: str,
    plural: str,
    name: str,
):
    """Get a Kubernetes CR"""
    if not custom_obj_api:
        st_object.error("Kubernetes CustomObjectsApi client not initialized.")
        return None
    try:
        logger.info(f"Getting {plural}/{name} in ns '{namespace}'")
        return custom_obj_api.get_namespaced_custom_object(
            group=group, version=version, namespace=namespace, plural=plural, name=name
        )
    except kubernetes.client.ApiException as e:
        _handle_kube_api_exception(
            st_object, e, f"{plural}/{name}", action="getting details for"
        )
        return None
    except Exception as e:
        st_object.error(
            f"An unexpected error occurred while getting {plural}/{name}: {e}"
        )
        logger.error(
            f"Unexpected error getting {plural}/{name} in ns '{namespace}': {e}",
            exc_info=True,
        )
        return None


def list_agents(
    st_object,
    custom_obj_api: Optional[kubernetes.client.CustomObjectsApi],
    namespace="default",
):
    """List agents known to K8s"""
    return list_custom_resources(
        st_object=st_object,
        custom_obj_api=custom_obj_api,
        group=constants.CRD_GROUP,
        version=constants.CRD_VERSION,
        namespace=namespace,
        plural=constants.AGENTS_PLURAL,
        label_selector=f"{constants.KAGENTI_TYPE_LABEL}={constants.RESOURCE_TYPE_AGENT}",
    )


def get_agent_details(
    st_object,
    custom_obj_api: Optional[kubernetes.client.CustomObjectsApi],
    agent_name: str,
    namespace="default",
):
    """Get agent details from Kubernetes"""
    return get_custom_resource(
        st_object=st_object,
        custom_obj_api=custom_obj_api,
        group=constants.CRD_GROUP,
        version=constants.CRD_VERSION,
        namespace=namespace,
        plural=constants.AGENTS_PLURAL,
        name=agent_name,
    )


def list_tools(
    st_object,
    custom_obj_api: Optional[kubernetes.client.CustomObjectsApi],
    namespace="default",
):
    """List tools using Kubernetes"""
    return list_custom_resources(
        st_object=st_object,
        custom_obj_api=custom_obj_api,
        group=constants.TOOLHIVE_CRD_GROUP,
        version=constants.TOOLHIVE_CRD_VERSION,
        namespace=namespace,
        plural=constants.TOOLHIVE_MCP_PLURAL,
        label_selector=f"{constants.KAGENTI_TYPE_LABEL}={constants.RESOURCE_TYPE_TOOL}",
    )


def get_tool_details(
    st_object,
    custom_obj_api: Optional[kubernetes.client.CustomObjectsApi],
    tool_name: str,
    namespace="default",
):
    """Get tool details from Kubernetes"""
    return get_custom_resource(
        st_object=st_object,
        custom_obj_api=custom_obj_api,
        group=constants.TOOLHIVE_CRD_GROUP,
        version=constants.TOOLHIVE_CRD_VERSION,
        namespace=namespace,
        plural=constants.TOOLHIVE_MCP_PLURAL,
        name=tool_name,
    )


def _find_pods_for_resource(core_v1_api, resource_name, namespace):
    """Find pods for a given resource name."""
    label_selectors = [
        f"app.kubernetes.io/name={resource_name}",
        f"app={resource_name}",
    ]

    for label_selector in label_selectors:
        try:
            pods = core_v1_api.list_namespaced_pod(
                namespace=namespace,
                label_selector=label_selector,
                timeout_seconds=10,
            )
            if pods.items:
                return pods, None
        except Exception as e:
            logger.debug(f"Error trying label selector '{label_selector}': {e}")
            continue

    error_message = (
        f"No pods found with label app.kubernetes.io/name={resource_name} "
        f"or app={resource_name} in namespace {namespace}"
    )
    return None, error_message


def _extract_env_var_from_source(env_var, result):
    """Extract environment variable from its source and add to result."""
    if env_var.value:
        result["direct"].append({"name": env_var.name, "value": env_var.value})
    elif env_var.value_from:
        source = env_var.value_from
        if source.config_map_key_ref:
            result["configmap"].append(
                {
                    "name": env_var.name,
                    "source_name": source.config_map_key_ref.name,
                    "source_key": source.config_map_key_ref.key,
                }
            )
        elif source.secret_key_ref:
            result["secret"].append(
                {
                    "name": env_var.name,
                    "source_name": source.secret_key_ref.name,
                    "source_key": source.secret_key_ref.key,
                }
            )
        elif source.field_ref:
            result["fieldref"].append(
                {"name": env_var.name, "field_path": source.field_ref.field_path}
            )
        elif source.resource_field_ref:
            result["resourcefield"].append(
                {
                    "name": env_var.name,
                    "resource": source.resource_field_ref.resource,
                }
            )


def get_pod_environment_variables(
    core_v1_api: Optional[kubernetes.client.CoreV1Api],
    resource_name: str,
    namespace: str = "default",
) -> Dict[str, Any]:
    """Get environment variables from the pod associated with a resource (agent or tool)."""
    result = {
        "direct": [],
        "configmap": [],
        "secret": [],
        "fieldref": [],
        "resourcefield": [],
        "error": None,
    }

    if not core_v1_api:
        result["error"] = "CoreV1Api not available"
        return result

    try:
        pods, error = _find_pods_for_resource(core_v1_api, resource_name, namespace)
        if error:
            result["error"] = error
            return result

        pod = pods.items[0]

        for container in pod.spec.containers:
            if container.env:
                for env_var in container.env:
                    _extract_env_var_from_source(env_var, result)

    except Exception as e:
        result["error"] = f"An unexpected error occurred: {e}"

    return result


def get_kubernetes_namespace():
    """Get the Kubernetes namespace"""
    if (
        "selected_k8s_namespace" in st.session_state
        and st.session_state.selected_k8s_namespace
    ):
        logger.debug(
            f"Using display namespace from session state: {st.session_state.selected_k8s_namespace}"
        )
        return st.session_state.selected_k8s_namespace

    ns_path = "/var/run/secrets/kubernetes.io/serviceaccount/namespace"
    if os.path.exists(ns_path):
        try:
            with open(ns_path, "r", encoding="utf-8") as f:
                ns = f.read().strip()
                if ns:
                    return ns
        except Exception as e:
            logger.warning(
                f"Could not read namespace from service account path {ns_path}: {e}"
            )
    return os.getenv("KUBERNETES_NAMESPACE", "default")


# pylint: disable=too-many-return-statements
def delete_custom_resource(
    st_object,
    custom_obj_api: Optional[kubernetes.client.CustomObjectsApi],
    group: str,
    version: str,
    namespace: str,
    plural: str,
    name: str,
):
    """
    Delete a custom resource from Kubernetes.

    Args:
        st_object: Streamlit object for displaying messages
        custom_obj_api: Kubernetes CustomObjectsApi client
        group: API group of the custom resource
        version: API version of the custom resource
        namespace: Kubernetes namespace
        plural: Plural name of the custom resource
        name: Name of the resource to delete

    Returns:
        bool: True if deletion was successful, False otherwise
    """
    if not custom_obj_api:
        st_object.error("Kubernetes CustomObjectsApi client not initialized.")
        return False

    try:
        logger.info(f"Deleting {plural}/{name} in ns '{namespace}'")
        # pylint: disable=line-too-long
        logger.info(
            f"Delete parameters - group: {group}, version: {version}, namespace: {namespace}, plural: {plural}, name: {name}"
        )

        # First, verify the resource exists before trying to delete
        try:
            _existing_resource = custom_obj_api.get_namespaced_custom_object(
                group=group,
                version=version,
                namespace=namespace,
                plural=plural,
                name=name,
            )
            logger.info(f"Resource {plural}/{name} exists, proceeding with deletion")
        except kubernetes.client.ApiException as e:
            if e.status == 404:
                st_object.warning(
                    f"Resource {plural}/{name} not found - it may have already been deleted."
                )
                logger.warning(f"Resource {plural}/{name} not found (404)")
                return True  # Consider this success since the resource is gone

            logger.error(f"Error checking if resource exists: {e}")
            raise  # Re-raise to be handled by outer try-catch

        # Perform the deletion
        delete_response = custom_obj_api.delete_namespaced_custom_object(
            group=group, version=version, namespace=namespace, plural=plural, name=name
        )

        logger.info(f"Delete API call completed for {plural}/{name}")
        logger.debug(f"Delete response: {delete_response}")

        # Verify deletion was successful by checking if resource still exists
        try:
            # Wait a moment for deletion to propagate
            time.sleep(1)

            custom_obj_api.get_namespaced_custom_object(
                group=group,
                version=version,
                namespace=namespace,
                plural=plural,
                name=name,
            )
            # If we get here, the resource still exists
            logger.warning(
                f"Resource {plural}/{name} still exists after deletion attempt"
            )
            st_object.warning(
                f"Deletion initiated but {plural}/{name} may still be terminating..."
            )
            return True  # Deletion was initiated even if not completed yet

        except kubernetes.client.ApiException as e:
            if e.status == 404:
                logger.info(
                    f"Successfully deleted {plural}/{name} in ns '{namespace}' - resource no longer exists"
                )
                return True

            logger.error(f"Unexpected error verifying deletion: {e}")
            return False

    except kubernetes.client.ApiException as e:
        logger.error(f"Kubernetes API exception during deletion: {e}")
        logger.error(
            f"Exception details - status: {e.status}, reason: {e.reason}, body: {e.body}"
        )
        _handle_kube_api_exception(st_object, e, f"{plural}/{name}", action="deleting")
        return False

    except Exception as e:
        logger.error(f"Unexpected error deleting {plural}/{name}: {e}")
        st_object.error(
            f"An unexpected error occurred while deleting {plural}/{name}: {e}"
        )
        logger.error(
            f"Unexpected error deleting {plural}/{name} in ns '{namespace}': {e}",
            exc_info=True,
        )
        return False
