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
User interface for Import New Tool page.
"""

import streamlit as st
from lib.common_ui import check_auth
from lib.build_utils import render_import_form
from lib.kube import get_kube_api_client_cached

# --- Define Tool-Specific Settings for the Import Form ---
TOOL_EXAMPLE_SUBFOLDERS = ["mcp/weather_tool", "mcp/slack_tool"]
TOOL_PROTOCOL_OPTIONS = ["streamable_http", "sse"]

check_auth()

# Get the generic ApiClient and status details
k8s_api_client, k8s_client_msg, k8s_client_icon = get_kube_api_client_cached()

render_import_form(
    st_object=st,
    resource_type="Tool",
    example_subfolders=TOOL_EXAMPLE_SUBFOLDERS,
    default_protocol="MCP",
    protocol_options=TOOL_PROTOCOL_OPTIONS,
    default_framework="Python",
    k8s_api_client=k8s_api_client,
    k8s_client_status_msg=k8s_client_msg,
    k8s_client_status_icon=k8s_client_icon,
    show_enabled_namespaces_only=True,
)

st.markdown("---")
# st.warning(
#    "**Note:** The build process for 'Tools' currently uses the same 'Component' CRD mechanism."
# )
