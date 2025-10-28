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
User interface for Import New Agent page.
"""

import streamlit as st
from lib.common_ui import check_auth
from lib.build_utils import render_import_form
from lib.kube import get_kube_api_client_cached

# --- Define Agent-Specific Settings for the Import Form ---
AGENT_EXAMPLE_SUBFOLDERS = [
    "a2a/weather_service",
    "a2a/a2a_contact_extractor",
    "a2a/a2a_currency_converter",
    "a2a/slack_researcher",
    "a2a/git_issue_agent",
]
AGENT_PROTOCOL_OPTIONS = ["a2a"]

check_auth()

# Get the generic ApiClient and status details
k8s_api_client, k8s_client_msg, k8s_client_icon = get_kube_api_client_cached()

render_import_form(
    st_object=st,
    resource_type="Agent",
    example_subfolders=AGENT_EXAMPLE_SUBFOLDERS,
    default_protocol="a2a",
    protocol_options=AGENT_PROTOCOL_OPTIONS,
    default_framework="LangGraph",
    k8s_api_client=k8s_api_client,
    k8s_client_status_msg=k8s_client_msg,
    k8s_client_status_icon=k8s_client_icon,
    show_enabled_namespaces_only=True,
)
