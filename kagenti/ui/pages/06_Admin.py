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
User interface for Admin Catalog page.
"""

import os
import streamlit as st
from lib.common_ui import check_auth
from lib import constants  # For Keycloak URL

# --- Page Configuration (Optional) ---
# st.set_page_config(page_title="Admin Console", layout="wide")

check_auth()

keycloak__console_url = os.environ.get(
    "KEYCLOAK_CONSOLE_URL", constants.KEYCLOAK_CONSOLE_URL_OFF_CLUSTER
)

# --- Main Page Content ---
st.header("🔑 Administration & Identity Management")
st.write(
    "This section provides access to administrative functions, including identity and "
    "access management via the Keycloak console."
)
st.markdown("---")

st.subheader("Identity Management (Keycloak)")
st.write(
    "Manage users, roles, client configurations, and authentication policies "
    "for the Cloud Native Agent Platform."
)

st.link_button(
    "Go to Identity Management Console",
    url=keycloak__console_url,
    help=(
        "Click to open the Keycloak Admin Console in a new tab. "
        "You may need appropriate credentials to log in."
    ),
    use_container_width=True,
)
st.caption(f"Keycloak admin console accessible at: `{keycloak__console_url}`")

st.markdown("---")

# Placeholder for other admin functionalities
st.subheader("Platform Configuration (Placeholder)")
st.info(
    "Placeholder for other administrative settings "
    "(e.g., global agent settings, resource quotas) could be managed here."
)
# Example:
# if st.button("Clear Platform Cache (Admin Only)"):
#     # Add appropriate admin checks here
#     st.cache_data.clear()
#     st.cache_resource.clear()
#     st.success("Platform caches cleared.")

st.markdown("---")
st.sidebar.info("Navigate to 'Admin' to manage platform-wide settings and identity.")
