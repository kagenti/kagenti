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

# pylint: disable=too-many-lines,too-many-nested-blocks

"""
Utilities for building UI.
"""

import re
import logging
import json
import os
import time
from typing import Optional, List, Dict, Any
import requests
import streamlit as st
import kubernetes.client
from keycloak import KeycloakAdmin
from . import constants
from .kube import (
    get_custom_objects_api,
    get_core_v1_api,
    get_all_namespaces,
    get_enabled_namespaces,
    get_secret_data,
    get_config_map_data,
    _handle_kube_api_exception,
    _display_kube_config_status_once,
)
from .utils import sanitize_for_k8s_name, get_resource_name_from_path

logger = logging.getLogger(__name__)


def parse_env_file(content: str, st_object=None):  # pylint: disable=too-many-branches,too-many-statements,too-many-nested-blocks
    """Parse `.env` file content into a list of env var dicts.

    Returns a list of dicts suitable for inclusion in k8s env lists. Supports
    JSON-encoded values (quoted in the .env) that decode to objects like
    {"valueFrom": {...}} or shorthand {"secretKeyRef": {...}} which will be
    converted into a valueFrom entry.
    """
    env_vars = []
    lines = content.strip().splitlines()

    for line_num, line in enumerate(lines, 1):
        raw_line = line
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            if st_object:
                st_object.warning(
                    f"⚠️ Line {line_num}: Invalid format (missing '='): {raw_line}"
                )
            else:
                logger.warning(
                    "Line %s: Invalid format (missing '='): %s", line_num, raw_line
                )
            continue
        name, value = line.split("=", 1)
        name = name.strip()
        value = value.strip()

        # strip surrounding quotes if present
        if value.startswith('"') and value.endswith('"'):
            value = value[1:-1]
        elif value.startswith("'") and value.endswith("'"):
            value = value[1:-1]

        if not name:
            if st_object:
                st_object.warning(f"⚠️ Line {line_num}: Empty variable name")
            else:
                logger.warning("Line %s: Empty variable name", line_num)
            continue

        env_entry = None

        # Attempt JSON parse only when value looks like JSON
        if value and (value.startswith("{") or value.startswith("[")):
            env_entry = _parse_json_value(value, name, line_num, st_object)
        else:
            env_entry = {"name": name, "value": value}

        env_vars.append(env_entry)

    return env_vars


def _parse_json_value(value: str, name: str, line_num: int, st_object=None) -> dict:
    """Parse a JSON-looking value from an .env entry into an env dict.

    This centralizes the JSON parsing and logging/warning behavior to keep
    parse_env_file smaller and easier to read.
    """
    try:
        parsed = json.loads(value)
        if isinstance(parsed, dict):
            if "value" in parsed or "valueFrom" in parsed:
                return {"name": name, **parsed}
            if "secretKeyRef" in parsed or "configMapKeyRef" in parsed:
                return {"name": name, "valueFrom": parsed}
            # Unrecognized dict shape; keep as string but warn
            if st_object:
                st_object.warning(
                    f"⚠️ Line {line_num}: JSON parsed but has unrecognized keys; kept as string for '{name}'"
                )
            else:
                logger.warning(
                    "Line %s: JSON parsed but has unrecognized keys; kept as string for '%s'",
                    line_num,
                    name,
                )
            return {"name": name, "value": value}

        # Non-dict JSON (list, string etc) -> keep as string but warn
        if st_object:
            st_object.warning(
                f"⚠️ Line {line_num}: JSON parsed to non-object; kept as string for '{name}'"
            )
        else:
            logger.warning(
                "Line %s: JSON parsed to non-object; kept as string for '%s'",
                line_num,
                name,
            )
        return {"name": name, "value": value}
    except json.JSONDecodeError:
        if st_object:
            st_object.warning(
                f"⚠️ Line {line_num}: Invalid JSON; kept as string: {value}"
            )
        else:
            logger.warning("Line %s: Invalid JSON; kept as string: %s", line_num, value)
        return {"name": name, "value": value}


def _is_valid_env_entry(env_var: dict) -> bool:
    """Return True when an env var dict has a valid name and value/structured data.

    Valid when:
    - name exists and is non-empty after stripping, and
    - either contains a structured reference (valueFrom or dict-valued 'value')
      or contains a non-empty string 'value'.
    """
    if not isinstance(env_var, dict):
        return False
    name = (env_var.get("name") or "").strip()
    if not name:
        return False
    has_structured = "valueFrom" in env_var or isinstance(env_var.get("value"), dict)
    has_plain = (
        isinstance(env_var.get("value"), str) and env_var.get("value", "").strip()
    )
    return bool(has_structured or has_plain)


# Pipeline mode constants
DEV_EXTERNAL_MODE = "dev-external"
DEV_LOCAL_MODE = "dev-local"

# Registry type constants
LOCAL_REGISTRY = "Local Registry"
QUAY_REGISTRY = "Quay.io"
DOCKER_HUB_REGISTRY = "Docker Hub"
GITHUB_REGISTRY = "GitHub Container Registry"


def get_pipeline_steps_for_mode(mode):
    """
    Returns the pipeline steps configuration based on mode.

    Args:
        mode: Pipeline mode ('dev-local', 'custom', or 'dev-external')

    Returns:
        list: Pipeline steps configuration
    """
    if mode == DEV_EXTERNAL_MODE:
        return [
            {
                "name": "github-clone",
                "configMap": "github-clone-step",
                "enabled": True,
            },
            {
                "name": "folder-verification",
                "configMap": "check-subfolder-step",
                "enabled": True,
            },
            {
                "name": "kaniko-build",
                "configMap": "kaniko-docker-build-step-external",
                "enabled": True,
            },
        ]
    # DEV_LOCAL_MODE
    return [
        {
            "name": "github-clone",
            "configMap": "github-clone-step",
            "enabled": True,
        },
        {
            "name": "folder-verification",
            "configMap": "check-subfolder-step",
            "enabled": True,
        },
        {
            "name": "kaniko-build",
            "configMap": "kaniko-docker-build-step-local",
            "enabled": True,
        },
    ]


def _get_keycloak_client_secret(st_object, client_name: str) -> str:
    """
    Retrieves the client secret from Keycloak for the given client name.

    Args:
        st_object (streamlit.elements.StreamlitElement): The Streamlit object to display messages.
        client_name (str): The name of the Keycloak client.

    Returns:
        str: The client secret if found, otherwise an empty string.
    """
    if not os.getenv("KEYCLOAK_ENABLED", "false").lower() == "true":
        return ""
    try:
        keycloak_admin = KeycloakAdmin(
            server_url=os.getenv(
                "KEYCLOAK_SERVER_URL", "http://keycloak.localtest.me:8080"
            ),
            username=os.getenv("KEYCLOAK_ADMIN_USER", "admin"),
            password=os.getenv("KEYCLOAK_ADMIN_PASSWORD", "admin"),
            realm_name=os.getenv("KEYCLOAK_REALM_NAME", "demo"),
            user_realm_name="master",
            verify=True,
        )
        client_id_in_realm = keycloak_admin.get_client_id(client_name)
        if not client_id_in_realm:
            st_object.warning(
                f"Keycloak client '{client_name}' not found for agent runtime secret."
            )
            return ""
        secrets = keycloak_admin.get_client_secrets(client_id_in_realm)
        return secrets.get("value", "") if secrets else ""
    except Exception as e:
        st_object.error(
            f"Failed to get Keycloak client secret for '{client_name}' (agent runtime): {e}"
        )
        return ""


# pylint: disable=too-many-arguments, too-many-positional-arguments, too-many-locals
def _construct_tool_resource_body(
    st_object,
    core_v1_api: Optional[kubernetes.client.CoreV1Api],
    build_namespace: str,
    resource_name: str,
    resource_type: str,
    repo_url: str,
    protocol: str,
    framework: str,
    additional_env_vars: Optional[list] = None,
    pod_config: Optional[dict] = None,
) -> Optional[dict]:
    """
    Constructs the Kubernetes resource body for a new build.

    Args:
        st_object (streamlit.elements.StreamlitElement): The Streamlit object to display messages.
        core_v1_api (kubernetes.client.CoreV1Api): The Kubernetes CoreV1 API client.
        build_namespace (str): The namespace where the build will be created.
        resource_name (str): The name of the resource to be built.
        resource_type (str): The type of the resource (e.g., Agent, Tool).
        repo_url (str): The URL of the Git repository.
        repo_branch (str): The Git branch or tag to use for the build.
        source_subfolder (str): The subfolder in the repository to use for the build.
        protocol (str): The protocol to use for the resource.
        framework (str): The framework to use for the resource.
        description (str): A description for the resource.
        build_from_source (bool): True if build from source is requested, False otherwise
        additional_env_vars (Optional[list]): Additional environment variables to include in the build.
        image_tag (str): The image tag to use for the build.

    Returns:
        Optional[dict]: The constructed Kubernetes resource body, or None if an error occurred.
    """
    k8s_resource_name = sanitize_for_k8s_name(resource_name)
    repo_user = get_secret_data(
        core_v1_api,
        build_namespace,
        constants.GIT_USER_SECRET_NAME,
        constants.GIT_USER_SECRET_KEY,
    )
    if not repo_user:
        st_object.error(
            # pylint: disable=line-too-long
            f"Failed to fetch GitHub username from secret '{constants.GIT_USER_SECRET_NAME}' (key: '{constants.GIT_USER_SECRET_KEY}') in namespace '{build_namespace}'. Ensure secret exists and K8s client is functional."
        )
        return None
    st_object.info(f"Using GitHub username '{repo_user}' from secret for build.")

    client_secret_for_env = _get_keycloak_client_secret(
        st_object, f"{k8s_resource_name}-client"
    )
    final_env_vars = list(constants.DEFAULT_ENV_VARS)

    client_id = build_namespace + "/" + k8s_resource_name

    env_dict = {}

    # Add default vars
    for var in constants.DEFAULT_ENV_VARS:
        if isinstance(var, dict) and "name" in var:
            env_dict[var["name"]] = var

    # Add/override with additional vars from UI
    if client_secret_for_env:
        final_env_vars.append({"name": "CLIENT_SECRET", "value": client_secret_for_env})

    env_dict["CLIENT_NAME"] = {"name": "CLIENT_NAME", "value": client_id}
    env_dict["CLIENT_ID"] = {
        "name": "CLIENT_ID",
        "value": f"spiffe://localtest.me/sa/{k8s_resource_name}",
    }
    env_dict["NAMESPACE"] = {"name": "NAMESPACE", "value": build_namespace}

    # Convert back to list
    final_env_vars = list(env_dict.values())
    if additional_env_vars:
        final_env_vars.extend(additional_env_vars)

    # Extract service ports from pod_config or use defaults
    if pod_config and pod_config.get("service_ports"):
        service_ports = pod_config["service_ports"]
    else:
        # Use default service ports
        service_ports = [
            {
                "name": "http",
                "port": constants.DEFAULT_IN_CLUSTER_PORT,
                "targetPort": constants.DEFAULT_IN_CLUSTER_PORT,
                "protocol": "TCP",
            }
        ]

    body = {
        "apiVersion": f"{constants.TOOLHIVE_CRD_GROUP}/{constants.TOOLHIVE_CRD_VERSION}",
        "kind": "MCPServer",
        "metadata": {
            "name": k8s_resource_name,
            "namespace": build_namespace,
            "labels": {
                constants.APP_KUBERNETES_IO_CREATED_BY: constants.STREAMLIT_UI_CREATOR_LABEL,
                constants.APP_KUBERNETES_IO_NAME: constants.TOOLHIVE_OPERATOR_LABEL_NAME,
                constants.KAGENTI_TYPE_LABEL: resource_type,
                constants.KAGENTI_PROTOCOL_LABEL: protocol,
                constants.KAGENTI_FRAMEWORK_LABEL: framework,
            },
        },
        "spec": {
            "image": repo_url,
            "transport": "streamable-http",
            "port": service_ports[0]["port"],
            "targetPort": service_ports[0]["targetPort"],
            "podTemplateSpec": {
                "spec": {
                    "serviceAccountName": k8s_resource_name,
                    "securityContext": {
                        "runAsNonRoot": True,
                        "seccompProfile": {"type": "RuntimeDefault"},
                    },
                    "volumes": [
                        {
                            "name": "cache",
                            "emptyDir": {},
                        },
                    ],
                    "containers": [
                        {
                            "name": "mcp",
                            "securityContext": {
                                "allowPrivilegeEscalation": False,
                                "capabilities": {"drop": ["ALL"]},
                                "runAsUser": 1000,
                            },
                            "resources": {
                                "limits": constants.DEFAULT_RESOURCE_LIMITS,
                                "requests": constants.DEFAULT_RESOURCE_REQUESTS,
                            },
                            "env": final_env_vars,
                            "volumeMounts": [
                                {
                                    "name": "cache",
                                    "mountPath": "/app/.cache",
                                    "readOnly": False,
                                },
                            ],
                        }
                    ],
                },
            },
        },
    }

    st_object.subheader(f"DEBUG: MCPServer Resource Body for {resource_type} Build")
    st_object.write("MCPServer def:", body)

    return body


def is_valid_image_url(url: str) -> bool:
    """Is URL valid?"""
    pattern = re.compile(r"^[\w\.-]+(?:/[\w\-]+)+:[\w\.\-]+$")
    return bool(pattern.match(url))


def extract_repo_name(url):
    """Given a URL, extract the repo name"""
    pattern = r"^([^\/:]+)\/([^\/:]+):([^\/:]+)$"
    match = re.match(pattern, url)
    if match:
        return match.group(1)  # repo name is the first group
    return None


def extract_image_name(url):
    """Given a URL, extract the image name"""
    pattern = r"^([^\/:]+)\/([^\/:]+):([^\/:]+)$"
    match = re.match(pattern, url)
    if match:
        return match.group(2)  # image name is the second group
    return None


def _construct_agent_resource_body(
    st_object,
    core_v1_api: Optional[kubernetes.client.CoreV1Api],
    build_namespace: str,
    resource_name: str,
    resource_type: str,
    repo_url: str,
    protocol: str,
    framework: str,
    description: str,
    additional_env_vars: Optional[list] = None,
    pod_config: Optional[dict] = None,
) -> Optional[dict]:
    """
    Constructs the Kubernetes resource body for a new build.

    Args:
        st_object (streamlit.elements.StreamlitElement): The Streamlit object to display messages.
        core_v1_api (kubernetes.client.CoreV1Api): The Kubernetes CoreV1 API client.
        build_namespace (str): The namespace where the build will be created.
        resource_name (str): The name of the resource to be built.
        resource_type (str): The type of the resource (e.g., Agent, Tool).
        repo_url (str): The URL of the Git repository.
        repo_branch (str): The Git branch or tag to use for the build.
        source_subfolder (str): The subfolder in the repository to use for the build.
        protocol (str): The protocol to use for the resource.
        framework (str): The framework to use for the resource.
        description (str): A description for the resource.
        build_from_source (bool): True if build from source is requested, False otherwise
        additional_env_vars (Optional[list]): Additional environment variables to include in the build.
        image_tag (str): The image tag to use for the build.

    Returns:
        Optional[dict]: The constructed Kubernetes resource body, or None if an error occurred.
    """

    k8s_resource_name = sanitize_for_k8s_name(resource_name)
    repo_user = get_secret_data(
        core_v1_api,
        build_namespace,
        constants.GIT_USER_SECRET_NAME,
        constants.GIT_USER_SECRET_KEY,
    )
    if not repo_user:
        st_object.error(
            # pylint: disable=line-too-long
            f"Failed to fetch GitHub username from secret '{constants.GIT_USER_SECRET_NAME}' (key: '{constants.GIT_USER_SECRET_KEY}') in namespace '{build_namespace}'. Ensure secret exists and K8s client is functional."
        )
        return None
    st_object.info(f"Using GitHub username '{repo_user}' from secret for build.")

    client_secret_for_env = _get_keycloak_client_secret(
        st_object, f"{k8s_resource_name}-client"
    )
    final_env_vars = list(constants.DEFAULT_ENV_VARS)
    if additional_env_vars:
        final_env_vars.extend(additional_env_vars)

    client_id = build_namespace + "/" + k8s_resource_name

    env_dict = {}
    # Add default vars
    for var in constants.DEFAULT_ENV_VARS:
        if isinstance(var, dict) and "name" in var:
            env_dict[var["name"]] = var

    # Add/override with additional vars from UI
    if client_secret_for_env:
        final_env_vars.append({"name": "CLIENT_SECRET", "value": client_secret_for_env})

    env_dict["CLIENT_NAME"] = {"name": "CLIENT_NAME", "value": client_id}
    env_dict["CLIENT_ID"] = {
        "name": "CLIENT_ID",
        "value": f"spiffe://localtest.me/sa/{k8s_resource_name}",
    }
    env_dict["NAMESPACE"] = {"name": "NAMESPACE", "value": build_namespace}

    # Convert back to list
    final_env_vars = list(env_dict.values())
    if additional_env_vars:
        final_env_vars.extend(additional_env_vars)

    # Extract service ports from pod_config or use defaults
    if pod_config and pod_config.get("service_ports"):
        service_ports = pod_config["service_ports"]
    else:
        # Use default service ports
        service_ports = [
            {
                "name": "http",
                "port": constants.DEFAULT_IN_CLUSTER_PORT,
                "targetPort": constants.DEFAULT_IN_CLUSTER_PORT,
                "protocol": "TCP",
            }
        ]
    body = {
        "apiVersion": f"{constants.CRD_GROUP}/{constants.CRD_VERSION}",
        "kind": "Agent",
        "metadata": {
            "name": k8s_resource_name,
            "namespace": build_namespace,
            "labels": {
                constants.APP_KUBERNETES_IO_CREATED_BY: constants.STREAMLIT_UI_CREATOR_LABEL,
                constants.APP_KUBERNETES_IO_NAME: constants.KAGENTI_OPERATOR_LABEL_NAME,
                constants.KAGENTI_TYPE_LABEL: resource_type,
                constants.KAGENTI_PROTOCOL_LABEL: protocol,
                constants.KAGENTI_FRAMEWORK_LABEL: framework,
            },
        },
        "spec": {
            "description": description,
            "replicas": 1,
            "imageSource": {
                "image": repo_url,
            },
            "servicePorts": service_ports,
            "podTemplateSpec": {
                "spec": {
                    "containers": [
                        {
                            "name": "agent",
                            "image": repo_url,
                            "imagePullPolicy": constants.DEFAULT_IMAGE_POLICY,
                            "resources": {
                                "limits": constants.DEFAULT_RESOURCE_LIMITS,
                                "requests": constants.DEFAULT_RESOURCE_REQUESTS,
                            },
                            "env": final_env_vars,
                            "ports": [
                                {
                                    "name": "http",
                                    "containerPort": constants.DEFAULT_IN_CLUSTER_PORT,
                                    "protocol": "TCP",
                                },
                            ],
                            "volumeMounts": [
                                {
                                    "name": "cache",
                                    "mountPath": "/app/.cache",
                                },
                                {
                                    "name": "marvin",
                                    "mountPath": "/.marvin",
                                },
                                {
                                    "name": "shared-data",
                                    "mountPath": "/shared",
                                },
                            ],
                        }
                    ],
                    "volumes": [
                        {
                            "name": "cache",
                            "emptyDir": {},
                        },
                        {
                            "name": "marvin",
                            "emptyDir": {},
                        },
                        {
                            "name": "shared-data",
                            "emptyDir": {},
                        },
                    ],
                },
            },
        },
    }

    return body


# pylint: disable=too-many-return-statements, too-many-branches, too-many-statements
def trigger_and_monitor_build(
    st_object,
    custom_obj_api: Optional[kubernetes.client.CustomObjectsApi],
    core_v1_api: Optional[kubernetes.client.CoreV1Api],
    build_namespace: str,
    resource_name_suggestion: str,
    resource_type: str,
    repo_url: str,
    repo_branch: str,
    source_subfolder: str,
    protocol: str,
    framework: str,
    # pylint: disable=unused-argument
    build_from_source: bool,
    description: str = "",
    registry_config: Optional[dict] = None,
    pod_config: Optional[dict] = None,
    additional_env_vars: Optional[List[Dict[str, Any]]] = None,
):
    """
    Triggers a build for a new resource and monitors its status.

    Args:
        st_object (streamlit.elements.StreamlitElement): The Streamlit object to display messages.
        custom_obj_api (kubernetes.client.CustomObjectsApi): The Kubernetes CustomObjects API client.
        core_v1_api (kubernetes.client.CoreV1Api): The Kubernetes CoreV1 API client.
        build_namespace (str): The namespace where the build will be created.
        resource_name_suggestion (str): The suggested name for the new resource.
        resource_type (str): The type of the resource (e.g., Agent, Tool).
        repo_url (str): The URL of the Git repository.
        repo_branch (str): The Git branch or tag to use for the build.
        source_subfolder (str): The subfolder in the repository to use for the build.
        protocol (str): The protocol to use for the resource.
        framework (str): The framework to use for the resource.
        description (str): A description for the resource.
        additional_env_vars (Optional[List[Dict[str, Any]]]): Additional environment variables to include in the build.
        pod_config: Pod configuration dictionary.
    Returns:
        bool: True if the build was successful, False otherwise.
    """
    if not custom_obj_api:
        st_object.error(
            "Kubernetes CustomObjectsApi client not initialized. Cannot trigger build."
        )
        return False
    if not core_v1_api:
        st_object.error(
            "Kubernetes CoreV1Api client not initialized. Cannot fetch secrets for build."
        )
        return False
    logger.info("Generating Component manifest\n")
    k8s_resource_name = sanitize_for_k8s_name(resource_name_suggestion)
    if not k8s_resource_name:
        st_object.error("Invalid resource name after sanitization. Cannot proceed.")
        return False
    build_cr_body = None
    if resource_type.lower() == "agent":
        build_cr_body = _construct_agent_resource_body(
            st_object=st_object,
            core_v1_api=core_v1_api,
            build_namespace=build_namespace,
            resource_name=k8s_resource_name,
            resource_type=resource_type,
            repo_url=repo_url,
            protocol=protocol,
            framework=framework,
            description=description,
            additional_env_vars=additional_env_vars,
            pod_config=pod_config,
        )
    elif resource_type.lower() == "tool":
        build_cr_body = _construct_tool_resource_body(
            st_object=st_object,
            core_v1_api=core_v1_api,
            build_namespace=build_namespace,
            resource_name=k8s_resource_name,
            resource_type=resource_type,
            repo_url=repo_url,
            protocol=protocol,
            framework=framework,
            additional_env_vars=additional_env_vars,
            pod_config=pod_config,
        )
    if not build_cr_body:
        st_object.error(
            f"Failed to construct build resource body for '{k8s_resource_name}'. Check previous errors."
        )
        return False
    with st_object.spinner(
        f"Submitting build for {resource_type} '{k8s_resource_name}' in namespace '{build_namespace}'..."
    ):
        try:
            logger.info(
                "Generated Component manifest:\n%s", json.dumps(build_cr_body, indent=2)
            )
            custom_obj_api.create_namespaced_custom_object(
                group=constants.CRD_GROUP,
                version=constants.CRD_VERSION,
                namespace=build_namespace,
                plural=constants.AGENTS_PLURAL,
                body=build_cr_body,
            )
            st_object.success(
                f"{resource_type.capitalize()} '{k8s_resource_name}' creation request sent to namespace '{build_namespace}'."
            )
        except kubernetes.client.ApiException as e:
            _handle_kube_api_exception(
                st_object,
                e,
                f"{resource_type.capitalize()} '{k8s_resource_name}'",
                action="creating",
            )
            return False
        except Exception as e:
            st_object.error(
                f"An unexpected error occurred creating build for '{k8s_resource_name}': {e}"
            )
            return False
    status_placeholder = st_object.empty()
    current_build_status = "Pending"
    max_retries = 120
    retries = 0
    with st_object.spinner(
        f"Waiting for {resource_type} '{k8s_resource_name}' in '{build_namespace}' to build and deploy..."
    ):
        while (
            current_build_status not in ["Succeeded", "Failed", "Error"]
            and retries < max_retries
        ):
            retries += 1
            try:
                build_obj = custom_obj_api.get_namespaced_custom_object(
                    group=constants.CRD_GROUP,
                    version=constants.CRD_VERSION,
                    namespace=build_namespace,
                    plural=constants.AGENTS_PLURAL,
                    name=k8s_resource_name,
                )
                status_data = build_obj.get("status", {})
                # current_build_status = status_data.get("buildStatus", "Unknown")
                build_status_data = status_data.get("buildStatus", {})
                current_build_status = build_status_data.get("phase", "Unknown")

                status_message = build_status_data.get("message", "")
                # deployment_status = status_data.get("deploymentStatus", "")
                deployment_status_data = status_data.get("deploymentStatus", {})
                deployment_phase = deployment_status_data.get("phase", "Unknown")

                status_placeholder.info(
                    # pylint: disable=line-too-long
                    f"Build Status for '{k8s_resource_name}': **{current_build_status}**\nMessage: {status_message}\nDeployment Status: **{deployment_phase}**"
                )
                if current_build_status in ["Succeeded", "Failed", "Error"]:
                    break
                time.sleep(constants.POLL_INTERVAL_SECONDS)
            except kubernetes.client.ApiException as e:
                if e.status == 404:
                    status_placeholder.error(
                        f"{resource_type.capitalize()}Build '{k8s_resource_name}' not found during polling."
                    )
                else:
                    status_placeholder.error(
                        f"API error polling build status for '{k8s_resource_name}': {e.reason}"
                    )
                current_build_status = "Error"
                break
            except Exception as e:
                status_placeholder.error(
                    f"Unexpected error polling build status for '{k8s_resource_name}': {e}"
                )
                current_build_status = "Error"
                break
        if retries >= max_retries and current_build_status not in [
            "Succeeded",
            "Failed",
            "Error",
        ]:
            status_placeholder.error(
                f"Timeout waiting for build of '{k8s_resource_name}' to complete."
            )
            return False

    if current_build_status == "Succeeded":
        # Now wait for deployment to complete
        deployment_retries = 0
        max_deployment_retries = 120
        final_deployment_phase = "Unknown"

        with st_object.spinner(
            f"Build succeeded. Waiting for {resource_type} '{k8s_resource_name}' to deploy..."
        ):
            while (
                final_deployment_phase not in ["Ready", "Failed", "Error"]
                and deployment_retries < max_deployment_retries
            ):
                deployment_retries += 1
                try:
                    # Re-fetch the object to get latest deployment status
                    build_obj = custom_obj_api.get_namespaced_custom_object(
                        group=constants.CRD_GROUP,
                        version=constants.CRD_VERSION,
                        namespace=build_namespace,
                        plural=constants.AGENTS_PLURAL,
                        name=k8s_resource_name,
                    )

                    final_deployment_status = build_obj.get("status", {}).get(
                        "deploymentStatus", {}
                    )
                    final_deployment_phase = final_deployment_status.get(
                        "phase", "Unknown"
                    )
                    deployment_message = final_deployment_status.get(
                        "deploymentMessage", ""
                    )

                    # Update status display
                    status_placeholder.info(
                        f"Deployment Status for '{k8s_resource_name}': **{final_deployment_phase}**\n"
                        f"Message: {deployment_message}"
                    )

                    if final_deployment_phase in ["Ready", "Failed", "Error"]:
                        break

                    time.sleep(constants.POLL_INTERVAL_SECONDS)

                except Exception as e:
                    st_object.warning(f"Error checking deployment status: {str(e)}")
                    time.sleep(constants.POLL_INTERVAL_SECONDS)

        # Handle final deployment status
        if final_deployment_phase == "Ready":
            st_object.success(
                # pylint: disable=line-too-long
                f"{resource_type.capitalize()} '{k8s_resource_name}' built and deployed successfully in namespace '{build_namespace}'!"
            )
            return True
        if final_deployment_phase in ["Failed", "Error"]:
            st_object.error(
                # pylint: disable=line-too-long
                f"{resource_type.capitalize()} '{k8s_resource_name}' deployment failed with status: {final_deployment_phase}. Check operator logs."
            )
            return False

        # Timeout case
        st_object.warning(
            # pylint: disable=line-too-long
            f"{resource_type.capitalize()} '{k8s_resource_name}' deployment timed out after {max_deployment_retries} attempts. "
            f"Last status: {final_deployment_phase}. Manual check might be needed."
        )
        return False

    st_object.error(
        # pylint: disable=line-too-long
        f"{resource_type.capitalize()} build for '{k8s_resource_name}' in '{build_namespace}' finished with status: {current_build_status}. Check operator logs."
    )
    return False


# pylint: disable=too-many-return-statements, too-many-branches
def trigger_and_monitor_deployment_from_image(
    st_object,
    custom_obj_api: Optional[kubernetes.client.CustomObjectsApi],
    core_v1_api: Optional[kubernetes.client.CoreV1Api],
    deployment_namespace: str,
    resource_name_suggestion: str,
    resource_type: str,
    repo_url: str,
    protocol: str,
    framework: str,
    description: str = "",
    additional_env_vars: Optional[List[Dict[str, Any]]] = None,
    pod_config: Optional[dict] = None,
):
    """
    Triggers a build for a new resource and monitors its status.

    Args:
        st_object (streamlit.elements.StreamlitElement): The Streamlit object to display messages.
        custom_obj_api (kubernetes.client.CustomObjectsApi): The Kubernetes CustomObjects API client.
        core_v1_api (kubernetes.client.CoreV1Api): The Kubernetes CoreV1 API client.
        deployment_namespace (str): The namespace where the resource will be deployed.
        resource_name_suggestion (str): The suggested name for the new resource.
        resource_type (str): The type of the resource (e.g., Agent, Tool).
        repo_url (str): The URL of the Git repository.
        protocol (str): The protocol to use for the resource.
        framework (str): The framework to use for the resource.
        description (str): A description for the resource.
        additional_env_vars (Optional[List[Dict[str, Any]]]): Additional environment variables to include in the build.

    Returns:
        bool: True if the build was successful, False otherwise.
    """
    if not custom_obj_api:
        st_object.error(
            "Kubernetes CustomObjectsApi client not initialized. Cannot trigger build."
        )
        return False
    if not core_v1_api:
        st_object.error(
            "Kubernetes CoreV1Api client not initialized. Cannot fetch secrets for build."
        )
        return False
    logger.info("Generating Component manifest\n")
    k8s_resource_name = sanitize_for_k8s_name(resource_name_suggestion)
    if not k8s_resource_name:
        st_object.error("Invalid resource name after sanitization. Cannot proceed.")
        return False
    cr_body = None
    if resource_type.lower() == "agent":
        cr_body = _construct_agent_resource_body(
            st_object=st_object,
            core_v1_api=core_v1_api,
            build_namespace=deployment_namespace,
            resource_name=k8s_resource_name,
            resource_type=resource_type,
            repo_url=repo_url,
            protocol=protocol,
            framework=framework,
            description=description,
            pod_config=pod_config,
            additional_env_vars=additional_env_vars,
        )
    elif resource_type.lower() == "tool":
        cr_body = _construct_tool_resource_body(
            st_object=st_object,
            core_v1_api=core_v1_api,
            build_namespace=deployment_namespace,
            resource_name=k8s_resource_name,
            resource_type=resource_type,
            repo_url=repo_url,
            protocol=protocol,
            framework=framework,
            pod_config=pod_config,
            additional_env_vars=additional_env_vars,
        )
    if not cr_body:
        st_object.error(
            f"Failed to construct resource body for '{k8s_resource_name}'. Check previous errors."
        )
        return False
    with st_object.spinner(
        f"Submitting deployment for {resource_type} '{k8s_resource_name}' in namespace '{deployment_namespace}'..."
    ):
        try:
            logger.info(
                "Generated Component manifest:\n%s", json.dumps(cr_body, indent=2)
            )

            if resource_type.lower() == "agent":
                custom_obj_api.create_namespaced_custom_object(
                    group=constants.CRD_GROUP,
                    version=constants.CRD_VERSION,
                    namespace=deployment_namespace,
                    plural=constants.AGENTS_PLURAL,
                    body=cr_body,
                )
            elif resource_type.lower() == "tool":
                custom_obj_api.create_namespaced_custom_object(
                    group=constants.TOOLHIVE_CRD_GROUP,
                    version=constants.TOOLHIVE_CRD_VERSION,
                    namespace=deployment_namespace,
                    plural=constants.TOOLHIVE_MCP_PLURAL,
                    body=cr_body,
                )

            st_object.success(
                f"{resource_type.capitalize()} '{k8s_resource_name}' creation request sent to namespace '{deployment_namespace}'."
            )
        except kubernetes.client.ApiException as e:
            _handle_kube_api_exception(
                st_object,
                e,
                f"{resource_type.capitalize()} '{k8s_resource_name}'",
                action="creating",
            )
            return False
        except Exception as e:
            st_object.error(
                f"An unexpected error occurred creating deployment for '{k8s_resource_name}': {e}"
            )
            return False
    status_placeholder = st_object.empty()
    # Now wait for deployment to complete
    deployment_retries = 0
    max_deployment_retries = 120
    final_deployment_phase = "Unknown"

    with st_object.spinner(
        f"Waiting for {resource_type} '{k8s_resource_name}' to deploy..."
    ):
        while (
            final_deployment_phase not in ["Ready", "Failed", "Error"]
            and deployment_retries < max_deployment_retries
        ):
            deployment_retries += 1
            try:
                # Re-fetch the object to get latest deployment status
                if resource_type.lower() == "agent":
                    build_obj = custom_obj_api.get_namespaced_custom_object(
                        group=constants.CRD_GROUP,
                        version=constants.CRD_VERSION,
                        namespace=deployment_namespace,
                        plural=constants.AGENTS_PLURAL,
                        name=k8s_resource_name,
                    )
                    final_deployment_status = build_obj.get("status", {}).get(
                        "deploymentStatus", {}
                    )
                    final_deployment_phase = final_deployment_status.get(
                        "phase", "Unknown"
                    )
                    deployment_message = final_deployment_status.get(
                        "deploymentMessage", ""
                    )
                    # Update status display
                    status_placeholder.info(
                        f"Deployment Status for '{k8s_resource_name}': **{final_deployment_phase}**\n"
                        f"Message: {deployment_message}"
                    )
                elif resource_type.lower() == "tool":
                    build_obj = custom_obj_api.get_namespaced_custom_object(
                        group=constants.TOOLHIVE_CRD_GROUP,
                        version=constants.TOOLHIVE_CRD_VERSION,
                        namespace=deployment_namespace,
                        plural=constants.TOOLHIVE_MCP_PLURAL,
                        name=k8s_resource_name,
                    )
                    final_deployment_status = build_obj.get("status", {})
                    final_deployment_phase = final_deployment_status.get(
                        "phase", "Unknown"
                    )
                    deployment_message = final_deployment_status.get("message", "")

                if final_deployment_phase in ["Running", "Failed", "Error"]:
                    if final_deployment_phase == "Running":
                        final_deployment_phase = "Ready"
                        status_placeholder.info(
                            f"Deployment Status for '{k8s_resource_name}': **{final_deployment_phase}**\n"
                            f"Message: Successfully deployed {k8s_resource_name}."
                        )
                    break

                time.sleep(constants.POLL_INTERVAL_SECONDS)

            except Exception as e:
                st_object.warning(f"Error checking deployment status: {str(e)}")
                time.sleep(constants.POLL_INTERVAL_SECONDS)

    # Handle final deployment status
    if final_deployment_phase == "Ready":
        st_object.success(
            f"{resource_type.capitalize()} '{k8s_resource_name}' deployed successfully in namespace '{deployment_namespace}'!"
        )
        return True
    if final_deployment_phase in ["Failed", "Error"]:
        st_object.error(
            # pylint: disable=line-too-long
            f"{resource_type.capitalize()} '{k8s_resource_name}' deployment failed with status: {final_deployment_phase}. Check operator logs."
        )
        return False

    # Timeout case
    st_object.warning(
        f"{resource_type.capitalize()} '{k8s_resource_name}' deployment timed out after {max_deployment_retries} attempts. "
        f"Last status: {final_deployment_phase}. Manual check might be needed."
    )
    return False


# pylint: disable=too-many-branches
def render_import_form(
    st_object,
    resource_type: str,
    default_protocol: str,
    default_framework: str,
    k8s_api_client: Optional[kubernetes.client.ApiClient],
    k8s_client_status_msg: Optional[str],
    k8s_client_status_icon: Optional[str],
    example_subfolders: List[str] = None,
    protocol_options: Optional[List[str]] = None,
    show_enabled_namespaces_only: bool = False,
):
    """
    Renders the common UI form for importing a new Agent or Tool.

    Args:
        st_object (streamlit.elements.StreamlitElement): The Streamlit object to display messages.
        resource_type (str): The type of the resource (e.g., Agent, Tool).
        default_protocol (str): The default protocol for the resource.
        default_framework (str): The default framework for the resource.
        k8s_api_client (Optional[kubernetes.client.ApiClient]): The Kubernetes API client.
        k8s_client_status_msg (Optional[str]): The message to display for the Kubernetes client status.
        k8s_client_status_icon (Optional[str]): The icon to display for the Kubernetes client status.
        example_subfolders (List[str]): The list of example subfolders.
        protocol_options (Optional[List[str]]): The list of available protocols.
    """
    st_object.header(f"Import New {resource_type}")

    _display_kube_config_status_once(
        k8s_client_status_msg, k8s_client_status_icon, bool(k8s_api_client)
    )

    core_v1_api = get_core_v1_api()

    # --- Namespace Selector for Build/Deployment ---
    available_build_namespaces = ["default"]
    if k8s_api_client:
        if show_enabled_namespaces_only:
            available_build_namespaces = get_enabled_namespaces(k8s_api_client)
        else:
            available_build_namespaces = get_all_namespaces(k8s_api_client)
        if not available_build_namespaces:
            available_build_namespaces = ["default"]
            st_object.caption(
                "Could not list all namespaces, defaulting to 'default'. Check K8s permissions."
            )
    else:
        st_object.caption(
            "Kubernetes client not available. Build will target 'default' namespace."
        )

    default_build_ns = "default"
    initial_selected_build_ns = st.session_state.get(
        "selected_build_k8s_namespace", default_build_ns
    )

    if initial_selected_build_ns not in available_build_namespaces:
        initial_selected_build_ns = (
            default_build_ns
            if default_build_ns in available_build_namespaces
            else available_build_namespaces[0]
        )

    build_ns_index = available_build_namespaces.index(initial_selected_build_ns)

    newly_selected_build_namespace = st_object.selectbox(
        f"Select Namespace to Deploy {resource_type}:",
        options=available_build_namespaces,
        index=build_ns_index,
        key=f"{resource_type.lower()}_build_namespace_selector",
        # pylint: disable=line-too-long
        help=f"The Component resource, the {resource_type}, and the '{constants.ENV_CONFIG_MAP_NAME}' ConfigMap will be in this namespace.",
    )

    if (
        newly_selected_build_namespace
        and newly_selected_build_namespace
        != st.session_state.get("selected_build_k8s_namespace")
    ):
        st.session_state.selected_build_k8s_namespace = newly_selected_build_namespace
        st.toast(f"Build namespace set to: {newly_selected_build_namespace}")

    build_namespace_to_use = st.session_state.get(
        "selected_build_k8s_namespace", default_build_ns
    )
    st_object.caption(f"Build will target namespace: **{build_namespace_to_use}**")
    st_object.markdown("---")

    # --- Environment Variable Selection ---
    env_options = {}
    if core_v1_api:
        env_options = get_config_map_data(
            core_v1_api, build_namespace_to_use, constants.ENV_CONFIG_MAP_NAME
        )
        if env_options is None:
            env_options = {}
    custom_env_vars = []
    selected_env_sets = []
    import_dialog_key = f"{resource_type.lower()}_import_env_dialog"
    if import_dialog_key not in st.session_state:
        st.session_state[import_dialog_key] = False
        # used to trigger re-rendering of the import dialog
    configmap_loaded_key = f"{resource_type.lower()}_configmap_vars_loaded"
    if configmap_loaded_key not in st.session_state:
        st.session_state[configmap_loaded_key] = False

    if env_options:
        st_object.subheader("Select Environment Variable Sets")
        sorted_env_keys = sorted(list(env_options.keys()))
        selected_env_sets = st_object.multiselect(
            "Select environments to append:",
            options=sorted_env_keys,
            key=f"{resource_type.lower()}_env_sets_selector",
            # pylint: disable=line-too-long
            help=f"Select sets of environment variables from the '{constants.ENV_CONFIG_MAP_NAME}' ConfigMap in '{build_namespace_to_use}'.",
        )
        st_object.markdown("---")

        # --- Custom Environment Variables Editor ---
        st_object.subheader("Environment Variables")
        st_object.caption(
            f"Define environment variables specific to this {resource_type}"
        )

        custom_env_key = f"{resource_type.lower()}_custom_env_vars"

        if custom_env_key not in st.session_state:
            st.session_state[custom_env_key] = []

        def add_env_var():
            st.session_state[custom_env_key].append({"name": "", "value": ""})

        def remove_env_var(index):
            if 0 <= index < len(st.session_state[custom_env_key]):
                st.session_state[custom_env_key].pop(index)

        def load_all_configmap_vars():
            """load original configmap vars, keeping user-added custom vars"""
            if not env_options:
                st_object.warning(
                    f"No configMap data available to load in namespace '{build_namespace_to_use}'"
                )
                return
            # First, remove any previously loaded configmap vars
            user_custom_vars = [
                var
                for var in st.session_state.get(custom_env_key, [])
                if not var.get("configmap_origin", False)
            ]
            # Then, add all configmap vars
            config_map_data = get_config_map_data(
                core_v1_api, build_namespace_to_use, constants.ENV_CONFIG_MAP_NAME
            )

            if config_map_data:
                # Parse configmap data into env vars
                all_configmap_vars = parse_configmap_data_to_env_vars(config_map_data)
                configmap_names = set()  # Track names we've seen
                configmap = []
                for var in all_configmap_vars:
                    var_name = var["name"].strip()
                    if var_name not in configmap_names:
                        configmap_names.add(var_name)
                        configmap.append(
                            {
                                "name": var["name"],
                                "value": var["value"],
                                "configmap_origin": True,
                                "configmap_section": var.get("section", ""),
                                "configmap_type": var.get("type", "configmap"),
                            }
                        )
                st.session_state[custom_env_key] = configmap + user_custom_vars
                st.session_state[configmap_loaded_key] = True
                return

        # Using module-level `parse_env_file` implementation (supports JSON values)
        # The module-level function accepts an optional `st_object` for warnings/logging.

        configmap_col1, configmap_col2, _ = st_object.columns([2, 2, 2])
        with configmap_col1:
            if st_object.button(
                "📄 Load Global Environment Vars",
                key=f"{resource_type.lower()}_load_configmap",
                # pylint: disable=line-too-long
                help=f"Load all environment variables from the '{constants.ENV_CONFIG_MAP_NAME}' ConfigMap in '{build_namespace_to_use}' namespace",
            ):
                load_all_configmap_vars()
                if st.session_state[configmap_loaded_key]:
                    configmap_var_count = len(
                        [
                            var
                            for var in st.session_state[custom_env_key]
                            if var.get("configmap_origin", False)
                        ]
                    )
                    st_object.success(
                        f"Loaded {configmap_var_count} environment variables from ConfigMap"
                    )
                st.rerun()
        with configmap_col2:
            if st.session_state[configmap_loaded_key]:
                if st_object.button(
                    "🔄 Reload Global Environment Vars",
                    key=f"{resource_type.lower()}_reload_configmap",
                    # pylint: disable=line-too-long
                    help=f"Restore original environment variables from the '{constants.ENV_CONFIG_MAP_NAME}' ConfigMap in '{build_namespace_to_use}' namespace",
                ):
                    load_all_configmap_vars()
                    st_object.success(
                        f"Restored environment variables from a '{constants.ENV_CONFIG_MAP_NAME}' ConfigMap"
                    )
                    st.rerun()

        if st.session_state[configmap_loaded_key]:
            configmap_vars_count = len(
                [
                    var
                    for var in st.session_state[custom_env_key]
                    if var.get("configmap_origin", False)
                ]
            )
            st_object.caption(
                f"Loaded {configmap_vars_count} environment variables from ConfigMap "
            )

        custom_env_vars = st.session_state[custom_env_key]
        if custom_env_vars:
            # --------- Render each env var
            for i, env_var in enumerate(custom_env_vars):
                col1, col2, col3, col4 = st_object.columns([3, 3, 2, 1])
                # Determine if this env var originated from configmap or custom added
                is_configmap_var = env_var.get("configmap_origin", False)

                with col1:
                    env_var["name"] = st.text_input(
                        "Name",
                        value=env_var["name"],
                        key=f"{resource_type.lower()}_env_name_{i}",
                        placeholder="example: API_KEY",
                        label_visibility="collapsed" if i > 0 else "visible",
                    )
                with col2:
                    # Support plain string values and structured JSON (valueFrom) entries.
                    # Determine if this entry is structured
                    is_structured = (
                        isinstance(env_var.get("value"), dict) or "valueFrom" in env_var
                    )

                    mode_key = f"{resource_type.lower()}_env_mode_{i}"
                    # default to Structured when detected, otherwise Plain
                    default_index = 0 if is_structured else 1
                    mode = st_object.radio(
                        "",
                        options=["Structured", "Plain"],
                        index=default_index,
                        key=mode_key,
                        horizontal=True,
                        label_visibility="collapsed",
                    )

                    if mode == "Structured":
                        # show JSON editor populated from valueFrom or from a dict value
                        json_obj = None
                        if "valueFrom" in env_var:
                            json_obj = env_var.get("valueFrom")
                        elif isinstance(env_var.get("value"), dict):
                            json_obj = env_var.get("value")

                        json_str = (
                            json.dumps(json_obj, indent=2)
                            if json_obj is not None
                            else "{}"
                        )
                        edited = st_object.text_area(
                            "Structured JSON",
                            value=json_str,
                            key=f"{resource_type.lower()}_env_json_{i}",
                            height=120,
                            label_visibility="collapsed",
                        )
                        # Try to parse edited JSON and store as valueFrom
                        try:
                            parsed = json.loads(edited)
                            env_var.pop("value", None)
                            env_var["valueFrom"] = parsed
                        except json.JSONDecodeError:
                            # Keep the message concise and use an f-string
                            var_name = env_var.get("name", "")
                            st_object.warning(
                                f"⚠️ Invalid JSON for variable '{var_name}'. Fix the JSON or switch to Plain mode."
                            )
                    else:
                        # Plain mode: keep a simple text input. If previously structured, drop structured data.
                        current_value = env_var.get("value")
                        if current_value is None:
                            # avoid exposing structured secret data; start empty
                            current_value = ""
                        env_var["value"] = st_object.text_input(
                            "Value",
                            value=current_value,
                            key=f"{resource_type.lower()}_env_value_{i}",
                            placeholder="example: AAAA_BBBB_CCCC",
                            label_visibility="collapsed" if i > 0 else "visible",
                        )
                        env_var.pop("valueFrom", None)

                with col3:
                    if i == 0:
                        st_object.write("")
                        st_object.write("")
                    # visualize origin: configmap-loaded vars, structured references, or custom
                    structured_ref = False
                    # valueFrom can be present directly, or value may be a dict with structured content
                    if "valueFrom" in env_var and isinstance(
                        env_var.get("valueFrom"), dict
                    ):
                        structured_ref = True
                        vf = env_var.get("valueFrom")
                    elif isinstance(env_var.get("value"), dict):
                        structured_ref = True
                        vf = env_var.get("value")
                    else:
                        vf = None

                    if is_configmap_var:
                        var_type = env_var.get("configmap_type", "configmap")
                        if var_type == "secret":
                            st_object.markdown(
                                "<span style='font-size: 10px; color: blue; '>🔒 **Custom Secret**</span>",
                                unsafe_allow_html=True,
                            )
                        elif var_type == "configmap-secret":
                            st_object.markdown(
                                "<span style='font-size: 10px; color: green; '>🔒 **ConfigMap Secret**</span>",
                                unsafe_allow_html=True,
                            )
                        else:
                            st_object.markdown(
                                "<span style='font-size: 10px; color: green'>🗂️ **ConfigMap**</span>",
                                unsafe_allow_html=True,
                            )
                    elif structured_ref and vf is not None:
                        # Detect secret vs configmap inside structured valueFrom
                        if "secretKeyRef" in vf:
                            st_object.markdown(
                                "<span style='font-size: 10px; color: red'>🔒 **Secret reference**</span>",
                                unsafe_allow_html=True,
                            )
                        elif "configMapKeyRef" in vf:
                            st_object.markdown(
                                "<span style='font-size: 10px; color: green'>🗂️ **ConfigMap reference**</span>",
                                unsafe_allow_html=True,
                            )
                        else:
                            st_object.markdown(
                                "<span style='font-size: 10px; color: purple'>🧩 **Structured**</span>",
                                unsafe_allow_html=True,
                            )
                    else:
                        st_object.markdown(
                            "<span style='font-size: 10px; color: blue; '>✏️ **Custom**</span>",
                            unsafe_allow_html=True,
                        )

                with col4:
                    if i == 0:
                        st_object.write("")
                        st_object.write("")

                    if st.button(
                        "🗑️",
                        key=f"{resource_type}.lower()-remove_env_{i}",
                        help="Remove this environment variable",
                    ):
                        remove_env_var(i)
                        st.rerun()

        button_col1, button_col2, _ = st_object.columns([1, 1, 1])
        with button_col1:
            if st_object.button(
                "✚ Add Environment Variable",
                key=f"{resource_type.lower()}_add_env_var",
                help="Add a new custom environment variable",
            ):
                add_env_var()
                st.rerun()

        with button_col2:
            if st_object.button(
                "📥 Import .env File",
                key=f"{resource_type.lower()}_import_env_var",
                help="Import environment variables from .env file",
            ):
                st.session_state[import_dialog_key] = True
                st.rerun()

    # --- Import flow ---
    if st.session_state.get(import_dialog_key, False):
        st_object.markdown("---")
        st_object.subheader("Import Environment Variables from .env file")
        # Small tooltip/note about secret references
        st_object.caption(
            "Tip: If your .env contains JSON secret/configmap references (e.g. using `secretKeyRef` or `configMapKeyRef`), "
            "Kagenti will include them as `valueFrom` references in the generated manifest but will NOT store secret plaintext. "
            "Ensure the referenced Secrets/ConfigMaps already exist in the target namespace before deploying. "
            "See `docs/new-agent.md` for examples."
        )

        repo_url = st_object.text_input(
            "Github Repository URL:",
            placeholder="http://github.com/username/repository",
            key=f"{resource_type.lower()}_repo_url",
            help="Enter the Github repository URL",
        )
        file_path = st_object.text_input(
            "Path to .env file:",
            placeholder=". env or config/.env or path/to/your/.env",
            key=f"{resource_type.lower()}_env_file_path",
            help="Enter the path to .env file within the repository",
        )

        import_col1, import_col2, _import_col3 = st_object.columns([1, 1, 2])
        with import_col1:
            if st_object.button(
                " 🔄 Import",
                key=f"{resource_type.lower()}_do_import",
                disabled=not (repo_url and file_path),
            ):
                try:
                    with st_object.spinner("Fetching .env file from repository ..."):
                        # Need to convert Github repo URL to raw file URL
                        if "github.com" in repo_url:
                            if repo_url.endswith(".git"):
                                repo_url = repo_url[:-4]

                            repo_path = repo_url.replace(
                                "https://github.com/", ""
                            ).replace("http://github.com/", "")
                            if "/tree/" in repo_path:
                                parts = repo_path.split("/tree/")
                                repo_path = parts[0]
                                branch = parts[1].split("/")[0]
                            else:
                                branch = "main"
                            raw_url = f"https://raw.githubusercontent.com/{repo_path}/{branch}/{file_path.lstrip('/')}"
                        else:
                            raw_url = f"{repo_url.rstrip('/')}/{file_path.lstrip('/')}"

                        response = requests.get(raw_url, timeout=20)
                        env_content = response.text

                        imported_vars = parse_env_file(env_content, st_object)
                        if imported_vars:
                            existing_names = {
                                var["name"] for var in st.session_state[custom_env_key]
                            }
                            new_vars = [
                                var
                                for var in imported_vars
                                if var["name"] not in existing_names
                            ]
                            duplicate_vars = [
                                var
                                for var in imported_vars
                                if var["name"] in existing_names
                            ]
                            st.session_state[custom_env_key].extend(new_vars)
                            st_object.success(
                                "Successfully imported env vars from the .env file"
                            )
                            if duplicate_vars:
                                # pylint: disable=line-too-long
                                st_object.warning(
                                    f"⚠️ Skipped {len(duplicate_vars)} duplicate variables {', '.join([var['name'] for var in duplicate_vars])}"
                                )
                            st.session_state[import_dialog_key] = False
                            st.rerun()
                        else:
                            st_object.error(
                                "❌ No valid environment variables found in the file"
                            )
                except requests.RequestException as e:
                    st_object.error(f"❌ Failed to fetch file: {str(e)}")
                except Exception as e:
                    st_object.error(f"❌ Import error: {str(e)}")

        with import_col2:
            if st_object.button(
                "❌ Cancel", key=f"{resource_type.lower()}_cancel_import"
            ):
                st.session_state[import_dialog_key] = False
                st.rerun()

    # Validate custom env vars
    if custom_env_vars:
        valid_custom_env_vars = []
        invalid_custom_env_vars = []

        for env_var in custom_env_vars:
            filtered_env_var = {
                k: v for k, v in env_var.items() if k in ("name", "value", "valueFrom")
            }
            if _is_valid_env_entry(env_var):
                valid_custom_env_vars.append(filtered_env_var)
            else:
                invalid_custom_env_vars.append(filtered_env_var)

        if invalid_custom_env_vars:
            st_object.warning(
                f"{len(invalid_custom_env_vars)} environment variable(s) have missing name or value and will be ignored"
            )

    st_object.markdown("---")

    if not k8s_api_client:
        st_object.error("Kubernetes client not available. Cannot proceed with build.")
        return
    seen_env_names = set()
    final_additional_envs = []
    if selected_env_sets and env_options:
        for key in selected_env_sets:
            # Skip if key not found or not a list
            if key not in env_options or not isinstance(env_options[key], list):
                continue

            for env_var in env_options[key]:
                # Skip if not a dict
                if not isinstance(env_var, dict):
                    continue

                name = env_var.get("name", "").strip()
                # Skip if no name or already seen
                if not name or name in seen_env_names:
                    continue

                seen_env_names.add(name)
                final_additional_envs.append(env_var)

    if custom_env_vars:
        for env_var in custom_env_vars:

            # Skip invalid entries centrally
            if not _is_valid_env_entry(env_var):
                continue

            name = (env_var.get("name") or "").strip()

            # Structured env var (valueFrom)
            if "valueFrom" in env_var and isinstance(env_var.get("valueFrom"), dict):
                final_additional_envs.append(
                    {"name": name, "valueFrom": env_var["valueFrom"]}
                )
                continue

            # Sometimes structured JSON may be stored under 'value' as a dict
            if isinstance(env_var.get("value"), dict):
                # Only allow known keys to be included for manifest predictability
                allowed_keys = ["valueFrom", "configMapKeyRef", "secretKeyRef"]
                env_entry = {"name": name}
                for key in allowed_keys:
                    if key in env_var["value"]:
                        env_entry[key] = env_var["value"][key]
                final_additional_envs.append(env_entry)
                continue

            # Plain string value (helper ensured non-empty)
            val = env_var.get("value")
            if isinstance(val, str):
                final_additional_envs.append({"name": name, "value": val.strip()})
            else:
                logger.warning(
                    f"Skipping env var '{name}' with non-string value: {val!r}"
                )

    custom_obj_api = get_custom_objects_api()
    if not custom_obj_api or not core_v1_api:
        st_object.error(
            "K8s API clients not initialized correctly. Cannot trigger build."
        )
        return

    pod_config = render_k8s_pod_configuration(st_object, resource_type)

    # Tools can only be deployed from existing images, Agents can be built from source
    if resource_type.lower() == "tool":
        deployment_method = "Deploy from Existing Image"
    else:
        deployment_method = st_object.radio(
            "Deployment Method",
            ("Build from Source", "Deploy from Existing Image"),
            key=f"{resource_type.lower()}_deployment_method",
        )

    if example_subfolders is None:
        example_subfolders = []

    if deployment_method == "Build from Source":
        st_object.write(
            f"Provide source details to build and deploy a new {resource_type.lower()}."
        )
        source_url = st_object.text_input(
            f"{resource_type} Source Repository URL",
            value=constants.DEFAULT_REPO_URL,
            key=f"{resource_type.lower()}_source_url",
        )
        branch_or_tag = st_object.text_input(
            "Git Branch or Tag",
            value=constants.DEFAULT_REPO_BRANCH,
            key=f"{resource_type.lower()}_branch_or_tag",
        )

        # Registry configuration section
        st_object.markdown("---")
        registry_config = get_registry_config_from_ui(st_object, resource_type, True)
        if registry_config and not validate_registry_config(registry_config, st_object):
            return
        selected_protocol = default_protocol
        if protocol_options:
            current_protocol_index = (
                protocol_options.index(default_protocol)
                if default_protocol in protocol_options
                else 0
            )
            selected_protocol = st_object.selectbox(
                "Select protocol:",
                options=protocol_options,
                index=current_protocol_index,
                key=f"selected_{resource_type.lower()}_protocol_option",
            )
        selected_framework = default_framework
        final_source_subfolder_path = ""
        manual_resource_name = ""
        if source_url and branch_or_tag:
            st_object.markdown("---")
            st_object.subheader("Specify Source Subfolder")
            subfolder_selection_method = st_object.radio(
                "Subfolder specification:",
                ("Select from examples", "Enter manually"),
                key=f"{resource_type.lower()}_subfolder_method",
            )
            if subfolder_selection_method == "Select from examples":
                if example_subfolders:
                    selected_example = st_object.selectbox(
                        "Select an example:",
                        options=[""] + example_subfolders,
                        key=f"selected_{resource_type.lower()}_example_subfolder",
                        format_func=lambda x: x if x else "Select an example...",
                    )
                    if selected_example:
                        final_source_subfolder_path = selected_example
                else:
                    st_object.info("No example subfolders.")
            manual_subfolder_input = st_object.text_input(
                "Source Subfolder Path (relative to root)",
                value=final_source_subfolder_path
                if final_source_subfolder_path
                else "",
                placeholder=f"e.g., {resource_type.lower()}s/my-new-{resource_type.lower()}",
                key=f"manual_{resource_type.lower()}_source_subfolder_path",
            )
            if manual_subfolder_input:
                final_source_subfolder_path = manual_subfolder_input

            # If no subfolder is specified, require a manual resource name
            if not final_source_subfolder_path:
                manual_resource_name = st_object.text_input(
                    f"{resource_type} Name",
                    value="",
                    placeholder=f"Enter a name for your {resource_type.lower()} (required when no subfolder is specified)",
                    key=f"manual_{resource_type.lower()}_resource_name",
                )

        if st_object.button(
            f"Build & Deploy New {resource_type}",
            key=f"build_new_{resource_type.lower()}_btn",
        ):
            # Determine resource name: derived from subfolder or manually entered
            if final_source_subfolder_path:
                resource_name_suggestion = get_resource_name_from_path(
                    final_source_subfolder_path
                )
            else:
                resource_name_suggestion = manual_resource_name

            # Validation: require either subfolder (with name derived) or manual name
            if not all(
                [
                    source_url,
                    branch_or_tag,
                    resource_name_suggestion,
                    build_namespace_to_use,
                ]
            ):
                st_object.warning(
                    "Please provide all source details, and either a subfolder or a resource name, and select a build namespace."
                )
                return

            # Validate registry configuration for external registries
            if (
                registry_config
                and registry_config.get("requires_auth")
                and not registry_config.get("credentials_secret")
            ):
                st_object.warning(
                    "Please specify a registry secret name for external registry authentication."
                )
                return

            trigger_and_monitor_build(
                st_object=st,
                custom_obj_api=custom_obj_api,
                core_v1_api=core_v1_api,
                build_namespace=build_namespace_to_use,
                resource_name_suggestion=resource_name_suggestion,
                resource_type=resource_type.lower(),
                repo_url=source_url,
                repo_branch=branch_or_tag,
                source_subfolder=final_source_subfolder_path,
                protocol=selected_protocol,
                framework=selected_framework,
                build_from_source=True,
                description=f"{resource_type} '{resource_name_suggestion}' built from UI.",
                registry_config=registry_config,
                pod_config=pod_config,
                additional_env_vars=final_additional_envs,
            )

    elif deployment_method == "Deploy from Existing Image":
        # You can deploy using a Docker image from either a public or private repository.
        # *** If you're using a private repository, make sure the .env file in the installer/app folder
        #     is set up correctly.
        # *** One key setting in that file is AGENT_NAMESPACES, which lists the Kubernetes namespaces where
        #     agents and tools should be deployed.
        # *** The Kagenti installer will only copy the necessary configuration (like ConfigMaps and Secrets) for those specific
        #     namespaces.
        st_object.write(
            f"Provide Docker image details to deploy a new {resource_type.lower()}."
        )
        docker_image_url = st_object.text_input(
            "Docker Image (e.g., myrepo/myimage:tag)",
            key=f"{resource_type.lower()}_docker_image",
        )

        selected_protocol = default_protocol
        if protocol_options:
            current_protocol_index = (
                protocol_options.index(default_protocol)
                if default_protocol in protocol_options
                else 0
            )
            selected_protocol = st_object.selectbox(
                "Select protocol:",
                options=protocol_options,
                index=current_protocol_index,
                key=f"selected_{resource_type.lower()}_protocol_option",
            )
        selected_framework = default_framework

        if st_object.button(
            f"Deploy {resource_type} from Image",
            key=f"deploy_{resource_type.lower()}_from_image_btn",
        ):
            if not docker_image_url or not build_namespace_to_use:
                st_object.warning(
                    "Please provide the Docker image and select a namespace."
                )
                return
            if not k8s_api_client:
                st_object.error(
                    "Kubernetes client not available. Cannot proceed with deployment."
                )
                return
            _repo, resource_name, _tag = parse_image_url(docker_image_url)

            # Trigger deployment using the image
            custom_obj_api = get_custom_objects_api()
            if not custom_obj_api or not core_v1_api:
                st_object.error(
                    "K8s API clients not initialized correctly. Cannot trigger deployment."
                )
                return

            resource_name_suggestion = extract_image_name(docker_image_url)

            trigger_and_monitor_deployment_from_image(
                st_object=st,
                custom_obj_api=custom_obj_api,
                core_v1_api=core_v1_api,
                deployment_namespace=build_namespace_to_use,
                resource_name_suggestion=resource_name,
                resource_type=resource_type.lower(),
                repo_url=docker_image_url,
                protocol=selected_protocol,
                framework=selected_framework,
                description=f"{resource_type} '{resource_name_suggestion}' built from UI.",
                pod_config=pod_config,
                additional_env_vars=final_additional_envs,
            )

    st_object.markdown("---")


def merge_env_variables(global_envs, custom_envs):
    """Merge global env vars from configmap with custom env vars, giving precedence to custom vars."""
    final_envs = {}

    temp_env_dict = {}
    for env_var in global_envs:
        if isinstance(env_var, dict) and "name" in env_var and "value" in env_var:
            var_name = env_var["name"].strip()
            if var_name and var_name not in temp_env_dict:
                temp_env_dict[env_var["name"]] = env_var["value"]
    for var_name, var_value in temp_env_dict.items():
        if var_name not in final_envs:
            final_envs[var_name] = var_value
    if custom_envs:
        temp_custom_dict = {}
        for env in custom_envs:
            name = env.get("name", "").strip()
            value = env.get("value", "")
            if name and value:
                temp_custom_dict[name] = value
        for var_name, var_value in temp_custom_dict.items():
            final_envs[var_name] = var_value

    merged_env_list = [
        {"name": name, "value": value} for name, value in final_envs.items()
    ]
    return merged_env_list


def convert_secret_string_to_k8s_format(env_var_dict):
    """
    Convert secret reference strings like '<slack-secret:bot-token>'
    back to Kubernetes valueFrom.secretKeyRef format.

    Args:
        env_var_dict: Environment variable dictionary with 'name' and 'value'

    Returns:
        Dictionary with proper Kubernetes format
    """

    name = env_var_dict.get("name", "")
    value = env_var_dict.get("value", "")
    # Check if already has valueFrom (from selected_env_sets)
    if "valueFrom" in env_var_dict:
        return env_var_dict

    # Check if value is a secret reference in format <secret-name:key>
    secret_pattern = r"^<([^:]+):([^>]+)>$"
    match = re.match(secret_pattern, str(value))
    if match:
        secret_name = match.group(1)
        secret_key = match.group(2)
        return {
            "name": name,
            "valueFrom": {"secretKeyRef": {"name": secret_name, "key": secret_key}},
        }

    # Regular value
    return {"name": name, "value": value}


def render_k8s_pod_configuration(st_object, resource_type: str) -> Optional[dict]:
    """
    Renders UI form for configuring Kubernetes Pod settings for an Agent or Tool.

    Args:
        st_object (streamlit.elements.StreamlitElement): The Streamlit object to display messages.
        resource_type (str): The type of the resource (e.g., Agent, Tool).
    Returns:
        dict: Configuration dictionary with dns_domain and service_ports
        None: If user hasn't completed configuration
    """

    st_object.header(f"{resource_type} Kubernetes Pod Configuration")

    st_object.write(
        f"Configure Kubernetes Pod settings for the {resource_type.lower()}."
    )

    service_ports_key = f"{resource_type.lower()}_service_ports"
    if service_ports_key not in st.session_state:
        st.session_state[service_ports_key] = [
            {
                "name": "http",
                "port": constants.DEFAULT_IN_CLUSTER_PORT,
                "targetPort": constants.DEFAULT_IN_CLUSTER_PORT,
                "protocol": "TCP",
            }
        ]

    st_object.write("**Service Ports**")

    service_ports = st.session_state[service_ports_key]
    if service_ports:
        for i, port in enumerate(service_ports):
            col1, col2, col3, col4, col5 = st_object.columns([2, 2, 2, 2, 1])
            with col1:
                port["name"] = st_object.text_input(
                    "Port Name",
                    value=port["name"],
                    key=f"{resource_type.lower()}_port_name_{i}",
                    placeholder="e.g., http",
                    label_visibility="collapsed" if i > 0 else "visible",
                )
            with col2:
                port["port"] = st_object.number_input(
                    "Service Port",
                    min_value=1,
                    max_value=65535,
                    value=port.get("port", 8080),
                    key=f"{resource_type.lower()}_port_{i}",
                    label_visibility="collapsed" if i > 0 else "visible",
                )
            with col3:
                port["targetPort"] = st_object.number_input(
                    "Target Port",
                    min_value=1,
                    max_value=65535,
                    value=port.get("targetPort", 8080),
                    key=f"{resource_type.lower()}_target_port_{i}",
                    label_visibility="collapsed" if i > 0 else "visible",
                )
            with col4:
                port["protocol"] = st_object.selectbox(
                    "Protocol",
                    options=["TCP", "UDP"],
                    index=0 if port.get("protocol", "TCP") == "TCP" else 1,
                    key=f"{resource_type.lower()}_protocol_{i}",
                    label_visibility="collapsed" if i > 0 else "visible",
                )
            with col5:
                if i == 0:
                    st_object.write("")
                    st_object.write("")
                if st_object.button(
                    "🗑️",
                    key=f"{resource_type.lower()}_remove_port_{i}",
                    help="Remove this service port",
                ):
                    remove_service_port(i, service_ports_key)
                    st.rerun()
    if st_object.button(
        "✚ Add Service Port",
        key=f"{resource_type.lower()}_add_service_port",
        help="Add a new service port",
    ):
        add_service_port(service_ports_key)
        st.rerun()

    # Validate service ports
    if service_ports:
        port_names = [p["name"] for p in service_ports if p["name"]]
        if len(port_names) != len(set(port_names)):
            st_object.error("Duplicate port names found")
            return None

    st_object.markdown("---")

    # use dict to return multiple config options in future
    return {
        "service_ports": service_ports,
    }


def add_service_port(service_ports_key):
    """Add default service port under the given key."""
    st.session_state[service_ports_key].append(
        {
            "name": "http",
            "port": constants.DEFAULT_IN_CLUSTER_PORT,
            "targetPort": constants.DEFAULT_IN_CLUSTER_PORT,
            "protocol": "TCP",
        }
    )


def remove_service_port(index, service_ports_key):
    """Remove a service port at the given index."""
    if 0 <= index < len(st.session_state[service_ports_key]):
        st.session_state[service_ports_key].pop(index)


def parse_image_url(url: str):
    """Parse an Image URL"""
    # Split off the tag
    if ":" not in url:
        raise ValueError("URL must contain a tag (e.g., :latest)")

    base, tag = url.rsplit(":", 1)
    parts = base.strip("/").split("/")

    if len(parts) < 2:
        raise ValueError("URL must contain at least a repo and image name")

    image_name = parts[-1]
    repo = "/".join(parts[:-1])

    return repo, image_name, tag


# Registry configuration constants
DEFAULT_REGISTRY_OPTIONS = {
    LOCAL_REGISTRY: "registry.cr-system.svc.cluster.local:5000",
    QUAY_REGISTRY: "quay.io",
    DOCKER_HUB_REGISTRY: "docker.io",
    GITHUB_REGISTRY: "ghcr.io",
}


def get_registry_config_from_ui(st_object, resource_type, build_from_source):
    """
    Renders registry configuration UI and returns selected registry settings.

    Args:
        st_object: Streamlit object
        resource_type: "Agent" or "Tool"
        build_from_source: Whether building from source or deploying from image

    Returns:
        dict: Registry configuration with 'registry_url', 'registry_type', 'credentials_secret', 'requires_auth'
    """
    if not build_from_source:
        return None

    st_object.subheader("Container Registry Configuration")

    # Registry selection
    registry_options = list(DEFAULT_REGISTRY_OPTIONS.keys())
    selected_registry_key = st_object.selectbox(
        "Select Container Registry:",
        options=registry_options,
        index=0,  # Default to Local Registry
        key=f"{resource_type.lower()}_registry_selector",
        help="Choose the container registry where the built image will be pushed",
    )

    registry_url = DEFAULT_REGISTRY_OPTIONS[selected_registry_key]

    # For Quay.io and other external registries, ask for namespace/organization
    if selected_registry_key in [QUAY_REGISTRY, DOCKER_HUB_REGISTRY, GITHUB_REGISTRY]:
        namespace_or_org = st_object.text_input(
            f"{selected_registry_key} Organization/Namespace:",
            placeholder="your-org-name",
            key=f"{resource_type.lower()}_registry_namespace",
            help=f"Your organization or namespace in {selected_registry_key}",
        )

        # Show authentication requirements
        if selected_registry_key == QUAY_REGISTRY:
            st_object.info(
                "📝 **Quay.io Authentication Required**\n"
                "Ensure your Kubernetes cluster has access to Quay.io:\n"
                "1. Create a robot account in your Quay.io organization\n"
                "2. Create a Kubernetes secret with registry credentials\n"
                "3. Configure the build pipeline with the secret name"
            )

            secret_name = st_object.text_input(
                "Registry Secret Name:",
                value="quay-registry-secret",
                key=f"{resource_type.lower()}_registry_secret",
                help="Name of the Kubernetes secret containing Quay.io credentials",
            )
        else:
            secret_name = st_object.text_input(
                f"{selected_registry_key} Secret Name:",
                value=f"{selected_registry_key.lower().replace(' ', '-').replace('.', '-')}-registry-secret",
                key=f"{resource_type.lower()}_registry_secret",
                help=f"Name of the Kubernetes secret containing {selected_registry_key} credentials",
            )

        if not namespace_or_org:
            st_object.warning(
                f"Please specify your {selected_registry_key} organization/namespace"
            )
            return None

        full_registry_url = f"{registry_url}/{namespace_or_org}"
    else:
        # Local registry
        full_registry_url = registry_url
        secret_name = None

    return {
        "registry_url": full_registry_url,
        "registry_type": selected_registry_key,
        "credentials_secret": secret_name,
        "requires_auth": selected_registry_key != LOCAL_REGISTRY,
    }


def validate_registry_config(registry_config, st_object):
    """
    Validates the registry configuration and shows helpful error messages.
    """
    if not registry_config:
        return False

    if registry_config["requires_auth"] and not registry_config.get(
        "credentials_secret"
    ):
        st_object.error(
            "External registries require authentication. Please specify a secret name."
        )
        return False

    if registry_config["registry_type"] == QUAY_REGISTRY:
        if not registry_config["registry_url"].startswith("quay.io/"):
            st_object.error("Invalid Quay.io registry URL format.")
            return False

    return True


def parse_configmap_data_to_env_vars(
    env_options: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """
    Parses ConfigMap data and return all environment variables as a flat list.

    Args:
        env_options(Dict[str, Any]): The data from the ConfigMap.

    Returns:
        List[Dict[str, Any]]: A list of environment variable dictionaries.
    """

    env_vars = []

    # pylint: disable=too-many-nested-blocks
    for section_name, section_content in env_options.items():
        if isinstance(section_content, list):
            for _, var in enumerate(section_content):
                if isinstance(var, dict) and "name" in var:
                    parsed_var = {
                        "name": var["name"],
                        "section": section_name,
                        "configmap_origin": True,
                    }

                    if "valueFrom" in var and isinstance(var["valueFrom"], dict):
                        secret_ref = var["valueFrom"].get("secretKeyRef", {})
                        if secret_ref:
                            secret_name = secret_ref.get("name", "")
                            secret_key = secret_ref.get("key", "")
                            parsed_var["value"] = f"<{secret_name}:{secret_key}>"
                            parsed_var["type"] = "configmap-secret"
                        else:
                            parsed_var["value"] = str(var.get("valueFrom", ""))
                            parsed_var["type"] = "configmap"
                    elif "value" in var:
                        parsed_var["value"] = var["value"]
                        parsed_var["type"] = "configmap"
                    else:
                        parsed_var["value"] = str(var)
                        parsed_var["type"] = "configmap"

                    env_vars.append(parsed_var)

        elif isinstance(section_content, str):
            try:
                parsed_content = json.loads(section_content)
                if isinstance(parsed_content, list):
                    for var in parsed_content:
                        if isinstance(var, dict) and "name" in var:
                            parsed_var = {
                                "name": var["name"],
                                "section": section_name,
                                "configmap_origin": True,
                            }
                            if "valueFrom" in var and isinstance(
                                var["valueFrom"], dict
                            ):
                                secret_ref = var["valueFrom"].get("secretKeyRef", {})
                                if secret_ref:
                                    secret_name = secret_ref.get("name", "")
                                    secret_key = secret_ref.get("key", "")
                                    parsed_var["value"] = (
                                        f"<{secret_name}:{secret_key}>"
                                    )
                                    parsed_var["type"] = "configmap-secret"
                                else:
                                    parsed_var["value"] = str(var.get("valueFrom", ""))
                                    parsed_var["type"] = "configmap"
                            elif "value" in var:
                                parsed_var["value"] = var["value"]
                                parsed_var["type"] = "configmap"
                            else:
                                parsed_var["value"] = str(var)
                                parsed_var["type"] = "configmap"
                            env_vars.append(parsed_var)
            except json.JSONDecodeError:
                # If not JSON, treat as single env var with section name as prefix
                env_vars.append(
                    {
                        "name": section_name.upper(),
                        "value": str(section_content),
                        "section": section_name,
                        "configmap_origin": True,
                        "type": "configmap",
                    }
                )
        elif isinstance(section_content, dict):
            if "name" in section_content:
                parsed_var = {
                    "name": section_content["name"],
                    "section": section_name,
                    "configmap_origin": True,
                }
                if "valueFrom" in section_content and isinstance(
                    section_content["valueFrom"], dict
                ):
                    secret_ref = section_content["valueFrom"].get("secretKeyRef", {})
                    if secret_ref:
                        secret_name = secret_ref.get("name", "")
                        secret_key = secret_ref.get("key", "")
                        parsed_var["value"] = f"<{secret_name}:{secret_key}>"
                        parsed_var["type"] = "configmap-secret"
                    else:
                        parsed_var["value"] = str(section_content.get("valueFrom", ""))
                        parsed_var["type"] = "configmap"
                elif "value" in section_content:
                    parsed_var["value"] = section_content["value"]
                    parsed_var["type"] = "configmap"
                else:
                    parsed_var["value"] = str(section_content)
                    parsed_var["type"] = "configmap"
                env_vars.append(parsed_var)
        else:
            # Treat as single env var with section name as prefix
            env_vars.append(
                {
                    "name": section_name.upper(),
                    "value": str(section_content),
                    "section": section_name,
                    "configmap_origin": True,
                    "type": "configmap",
                }
            )

    return env_vars
