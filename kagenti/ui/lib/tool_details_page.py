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

"""
Tool details.
"""

import asyncio
import json
import logging
import os
from urllib.parse import urljoin, quote
import streamlit as st
from .utils import sanitize_for_session_state_key
from .kube import (
    get_custom_objects_api,
    get_core_v1_api,
    get_tool_details,
    get_kubernetes_namespace,
    get_pod_environment_variables,
    is_running_in_cluster,
)  # Changed to get_custom_objects_api
from .common_ui import display_resource_metadata, display_environment_variables
from .mcp_client import MCPClientWrapper
from . import constants  # Import constants

logger = logging.getLogger(__name__)


def get_mcp_client_from_session(session_key: str, mcp_url: str) -> MCPClientWrapper:
    """
    Gets or creates an MCPClientWrapper instance in session state.

    Args:
        session_key (str): The session key to store the MCPClientWrapper instance.
        mcp_url (str): The URL of the MCP server.

    Returns:
        MCPClientWrapper: The MCPClientWrapper instance.
    """
    if session_key not in st.session_state:
        logger.info(
            f"Creating new MCPClientWrapper for session key '{session_key}' with URL: {mcp_url}"
        )
        st.session_state[session_key] = MCPClientWrapper(mcp_server_url=mcp_url)
    else:
        client: MCPClientWrapper = st.session_state[session_key]
        if client.mcp_server_url != mcp_url:
            logger.info(
                # pylint: disable=line-too-long
                f"MCP URL changed for '{session_key}'. Re-initializing MCPClientWrapper from {client.mcp_server_url} to {mcp_url}."
            )
            st.session_state[session_key] = MCPClientWrapper(mcp_server_url=mcp_url)
        else:
            logger.debug(
                f"Reusing existing MCPClientWrapper for session key '{session_key}' with URL {mcp_url}"
            )
    return st.session_state[session_key]


# pylint: disable=too-many-locals, too-many-branches, too-many-statements
def render_mcp_tool_details_content(tool_k8s_name: str):
    """
    Renders the detailed view for a specific MCP-enabled Tool.

    Args:
        tool_k8s_name (str): The name of the MCP-enabled Tool in Kubernetes.
    """
    st.header(f"MCP Tool: {tool_k8s_name}")

    mcp_inspector_url = os.environ.get("MCP_INSPECTOR_URL", constants.MCP_INSPECTOR_URL)
    mcp_proxy_url = os.environ.get(
        "MCP_PROXY_FULL_ADDRESS", constants.MCP_PROXY_FULL_ADDRESS
    )

    custom_obj_api = get_custom_objects_api()
    if not custom_obj_api:
        st.error(
            "Kubernetes API client (CustomObjectsApi) not available. Cannot load tool details."
        )
        return

    namespace = get_kubernetes_namespace()
    tool_details_data = get_tool_details(st, custom_obj_api, tool_k8s_name, namespace)

    if not tool_details_data:
        st.warning(f"Could not load K8s details for tool '{tool_k8s_name}'.")
        return

    session_key_prefix = sanitize_for_session_state_key(tool_k8s_name)
    mcp_client_session_key = f"mcp_client_{session_key_prefix}"

    _tags = display_resource_metadata(st, tool_details_data)

    # Display environment variables
    core_v1_api = get_core_v1_api()
    if core_v1_api:
        env_vars = get_pod_environment_variables(core_v1_api, tool_k8s_name, namespace)
        display_environment_variables(st, env_vars)

    st.markdown("---")

    # TODO - should use service info
    tool_service_name = tool_k8s_name

    # Determine port based on environment, allowing override from spec
    running_in_cluster = is_running_in_cluster()
    default_port = (
        constants.DEFAULT_IN_CLUSTER_PORT
        if running_in_cluster
        else constants.DEFAULT_OFF_CLUSTER_PORT
    )

    # TODO - should use service info
    mcp_tool_service_port = default_port
    mcp_path = constants.DEFAULT_MCP_STREAMABLE_HTTP_PATH

    if tool_service_name:
        scheme = "http://"

        base_host_port = ""
        if running_in_cluster:
            base_host_port = f"{tool_service_name}.{namespace}.svc.cluster.local:{mcp_tool_service_port}"
        else:
            base_host_port = f"{tool_service_name}.localtest.me:{mcp_tool_service_port}"

        base_url_with_scheme = scheme + base_host_port

        if not base_url_with_scheme.endswith("/"):
            base_url_with_scheme += "/"

        mcp_server_url = urljoin(base_url_with_scheme, mcp_path)

        logger.info(
            # pylint: disable=line-too-long
            f"Constructed MCP server URL for '{tool_k8s_name}': {mcp_server_url} (port: {mcp_tool_service_port}, in-cluster: {running_in_cluster})"
        )
    else:
        st.error(
            f"Could not determine service name or explicit MCP URL for tool '{tool_k8s_name}'."
        )
        logger.error(f"MCP service name/URL for tool '{tool_k8s_name}' is missing.")
        return

    if not mcp_server_url:
        st.error(
            f"MCP Server URL for tool '{tool_k8s_name}' could not be determined. Cannot connect."
        )
        return

    # setup MCP inspector URL
    encoded_server_url = quote(mcp_server_url, safe="")
    encoded_proxy_url = quote(mcp_proxy_url, safe="")
    console_url = (
        f"{mcp_inspector_url}?"
        f"serverUrl={encoded_server_url}&"
        f"transport=streamable-http&"
        f"MCP_PROXY_FULL_ADDRESS={encoded_proxy_url}"
    )

    st.subheader("MCP Inspector")
    st.link_button(
        "Connect with MCP Inspector",
        # TODO - transport should be a property of MCP server
        url=console_url,
        help="Click to open the MCP Inspector in a new tab.",
        use_container_width=True,
    )
    st.caption(f"Access MCP inspector: `{mcp_inspector_url}`")

    st.subheader("MCP Server Interaction")
    st.caption(f"Target MCP Server URL: `{mcp_server_url}`")

    mcp_client = get_mcp_client_from_session(mcp_client_session_key, mcp_server_url)

    if not mcp_client.is_last_list_tools_successful():
        action_button_label = "Connect to MCP Server and List Tools"
        if mcp_client.get_cached_tools():
            action_button_label = f"Refresh MCP Tools for '{tool_k8s_name}'"

        if st.button(action_button_label, key=f"connect_mcp_{session_key_prefix}"):
            with st.spinner(
                f"Connecting to MCP server at {mcp_server_url} and listing tools..."
            ):
                try:
                    asyncio.run(mcp_client.get_tools_from_server())
                    if mcp_client.is_last_list_tools_successful():
                        st.success(
                            f"Successfully connected and listed tools. Found {len(mcp_client.get_cached_tools())} tools."
                        )
                    else:
                        st.warning(
                            "Connected, but failed to list tools or no tools found."
                        )
                    st.rerun()
                except ConnectionError as ce:
                    st.error(f"Connection or listing failed: {ce}")
                except Exception as e:
                    st.error(f"Failed to connect/list tools from MCP server: {e}")
                    logger.error(
                        f"MCP connection/list tools failed for {tool_k8s_name}: {e}",
                        exc_info=True,
                    )
    else:
        st.success(
            f"Successfully listed tools from MCP Server. Found {len(mcp_client.get_cached_tools())} tools."
        )
        if st.button("Refresh MCP Tools", key=f"refresh_mcp_{session_key_prefix}"):
            with st.spinner("Connecting and refreshing tools..."):
                try:
                    asyncio.run(mcp_client.get_tools_from_server())
                    if mcp_client.is_last_list_tools_successful():
                        st.success(
                            f"Refreshed. Found {len(mcp_client.get_cached_tools())} tools."
                        )
                    else:
                        st.warning(
                            "Refresh attempt complete, but failed to list tools or no tools found."
                        )
                    st.rerun()
                except ConnectionError as ce:
                    st.error(f"Refresh failed: {ce}")
                except Exception as e:
                    st.error(f"Failed to refresh MCP tools: {e}")

        mcp_tools_list = mcp_client.get_cached_tools()
        if not mcp_tools_list:
            st.info("No tools currently listed from the MCP server.")
        else:
            st.markdown("#### Available MCP Tools on Server:")
            for i, mcp_tool_data in enumerate(mcp_tools_list):
                tool_name_on_mcp = mcp_tool_data.get("name", f"Unnamed Tool {i+1}")
                with st.expander(
                    f"Tool: {tool_name_on_mcp}",
                    expanded=len(mcp_tools_list) == 1,
                ):
                    st.markdown(
                        f"**Description:** {mcp_tool_data.get('description', 'N/A')}"
                    )

                    input_schema = mcp_tool_data.get("input_schema", {})
                    st.markdown("**Input Schema:**")
                    if input_schema:
                        st.json(input_schema, expanded=False)
                    else:
                        st.caption("No input schema provided.")

                    st.markdown("**Call Tool:**")
                    args_json_key = f"mcp_tool_args_{session_key_prefix}_{tool_name_on_mcp.replace('.', '_')}"

                    default_args_str = "{}"
                    if (
                        isinstance(input_schema, dict)
                        and input_schema.get("type") == "object"
                        and "properties" in input_schema
                    ):
                        default_args = {}
                        for prop_name, prop_details in input_schema.get(
                            "properties", {}
                        ).items():
                            prop_type = prop_details.get("type", "string")
                            if prop_type == "string":
                                default_args[prop_name] = prop_details.get(
                                    "example", "your_string_value"
                                )
                            elif prop_type == "integer":
                                default_args[prop_name] = prop_details.get("example", 0)
                            elif prop_type == "number":
                                default_args[prop_name] = prop_details.get(
                                    "example", 0.0
                                )
                            elif prop_type == "boolean":
                                default_args[prop_name] = prop_details.get(
                                    "example", False
                                )
                            elif prop_type == "array":
                                default_args[prop_name] = prop_details.get(
                                    "example", []
                                )
                            elif prop_type == "object":
                                default_args[prop_name] = prop_details.get(
                                    "example", {}
                                )
                            else:
                                default_args[prop_name] = None
                        try:
                            default_args_str = json.dumps(default_args, indent=2)
                        except TypeError:
                            default_args_str = "{}"

                    tool_args_str = st.text_area(
                        "Arguments (JSON format):",
                        value=default_args_str,
                        key=args_json_key,
                        height=150 if len(default_args_str) < 100 else 250,
                    )

                    call_button_key = f"call_mcp_tool_{session_key_prefix}_{tool_name_on_mcp.replace('.', '_')}"
                    if st.button(f"Call '{tool_name_on_mcp}'", key=call_button_key):
                        try:
                            tool_args = json.loads(tool_args_str)
                            if not isinstance(tool_args, dict):
                                st.error(
                                    "Arguments must be a valid JSON object (dictionary)."
                                )
                            else:
                                with st.spinner(
                                    f"Calling tool '{tool_name_on_mcp}'..."
                                ):
                                    try:
                                        response = asyncio.run(
                                            mcp_client.execute_tool_on_server(
                                                tool_name_on_mcp, tool_args
                                            )
                                        )
                                        st.markdown("**Tool Response:**")
                                        if hasattr(response, "model_dump_json"):
                                            st.json(response.model_dump_json())
                                        elif isinstance(response, (dict, list)):
                                            st.json(response)
                                        else:
                                            st.code(str(response))
                                    except ConnectionError as ce:
                                        st.error(
                                            f"Failed to call tool '{tool_name_on_mcp}': {ce}"
                                        )
                                    except Exception as call_e:
                                        st.error(
                                            f"Error calling tool '{tool_name_on_mcp}': {call_e}"
                                        )
                                        logger.error(
                                            f"MCP tool call failed for {tool_name_on_mcp}: {call_e}",
                                            exc_info=True,
                                        )
                        except json.JSONDecodeError:
                            st.error("Invalid JSON format for arguments.")
                        except Exception as e:
                            st.error(f"Failed to initiate tool call: {e}")

        if st.button(
            "Clear Cached Tools & Refresh UI",
            key=f"clear_mcp_cache_{session_key_prefix}",
        ):
            mcp_client.cached_tools = []
            mcp_client.last_list_tools_successful = False
            st.info("Cached tools cleared. Click 'Connect/Refresh' to fetch again.")
            st.rerun()
