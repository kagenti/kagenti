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

import streamlit as st
from lib.kube import (
    get_custom_objects_api,
    list_tools,
    get_tool_details,
    get_kube_api_client_cached,
    delete_custom_resource,
)
from lib.common_ui import check_auth, render_resource_catalog
from lib.tool_details_page import render_mcp_tool_details_content

check_auth()

# --- Main Tool Catalog Page Rendering ---

# Get the CustomObjectsApi (for listing/getting tools)
custom_obj_api = get_custom_objects_api()  # Correct function to get CustomObjectsApi
# Get the generic ApiClient (for listing namespaces - returned by the cached function)
generic_api_client, _, _ = get_kube_api_client_cached()

# Wrapper function to call delete_custom_resource with agent-specific parameters
def delete_tool_resource(custom_obj_api, name, namespace):
    """
    Wrapper function to delete agent resources specifically.
    Adjust the group, version, and plural parameters according to your agent CRD.
    """
    return delete_custom_resource(
        st_object=st,
        custom_obj_api=custom_obj_api,
        group="kagenti.operator.dev",
        version="v1alpha1",   
        namespace=namespace,
        plural="components",
        name=name
    )

render_resource_catalog(
    st_object=st,
    resource_type_name="Tool",
    list_resources_func=list_tools,
    get_details_func=get_tool_details,
    render_details_func=render_mcp_tool_details_content,
    custom_obj_api=custom_obj_api,  # Pass the CustomObjectsApi
    generic_api_client=generic_api_client,  # Pass the generic ApiClient
    session_state_key_selected_resource="selected_tool_name",
    delete_resource_func=delete_tool_resource, 
)
