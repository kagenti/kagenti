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
Common utilities for UI.
"""

from typing import Callable, Optional
import streamlit as st
import kubernetes
from .utils import (
    display_tags,
    extract_tags_from_labels,
    sanitize_for_session_state_key,
)
from .kube import (
    is_deployment_ready,
    get_kubernetes_namespace,
    get_enabled_namespaces,
    get_all_namespaces,
)
from . import constants


# pylint: disable=too-many-arguments, too-many-positional-arguments, too-many-locals, too-many-branches, too-many-statements
def render_resource_catalog(
    st_object,
    resource_type_name: str,
    list_resources_func: Callable,
    # pylint: disable=unused-argument
    get_details_func: Callable,
    render_details_func: Callable,
    custom_obj_api: Optional[kubernetes.client.CustomObjectsApi],
    generic_api_client: Optional[kubernetes.client.ApiClient],
    session_state_key_selected_resource: str,
    delete_resource_func: Optional[Callable] = None,
    show_enabled_namespaces_only: bool = False,
):
    # pylint: disable=line-too-long
    """
    Renders a catalog page for a given type of Kubernetes resource.
    Manages selection and navigation between list and detail views.
    Includes a namespace selector.

    Args:
        st_object (streamlit.BaseStreamlitWidget): The Streamlit object for displaying content.
        resource_type_name (str): The name of the Kubernetes resource type.
        list_resources_func (Callable): A function to list resources of the given type.
        get_details_func (Callable): A function to get details of a specific resource.
        render_details_func (Callable): A function to render details of a specific resource.
        custom_obj_api (Optional[kubernetes.client.CustomObjectsApi]): The Kubernetes API client for custom resources.
        generic_api_client (Optional[kubernetes.client.ApiClient]): The Kubernetes API client for generic resources.
        session_state_key_selected_resource (str): The Streamlit session state key for the selected resource.
        delete_resource_func (Optional[Callable]): A function to delete a resource. Should accept (api_client, resource_name, namespace).
        enabled_namespaces_only (bool): If True, only list enabled namespaces in the selector.

    Returns:
        None
    """
    st_object.header(f"{resource_type_name} Catalog")

    # --- Namespace Selector ---
    available_namespaces = []
    if show_enabled_namespaces_only:
        available_namespaces = get_enabled_namespaces(generic_api_client)
    else:
        available_namespaces = get_all_namespaces(generic_api_client)

    # Get the initial/current namespace
    current_namespace_from_kube_lib = get_kubernetes_namespace()

    selected_namespace_for_ui = current_namespace_from_kube_lib

    if not available_namespaces:
        st_object.warning(
            "Could not fetch list of available namespaces. Using default or previously selected namespace."
        )
        # If we can't list namespaces, we can't offer a selector.
        # Use current_namespace_from_kube_lib which might be 'default' or from env.
    else:
        # Ensure current_namespace_from_kube_lib is in the list, or add it to avoid errors with selectbox index
        if current_namespace_from_kube_lib not in available_namespaces:
            # This case implies the default/env namespace is not listable by the user,
            # which is unusual but possible. Fallback to first available or 'default'.
            st_object.caption(
                f"Current default namespace '{current_namespace_from_kube_lib}' not in listable namespaces. Defaulting selector."
            )
            display_namespaces_for_selector = ["default"] + [
                ns for ns in available_namespaces if ns != "default"
            ]
            if "default" not in available_namespaces:
                display_namespaces_for_selector = (
                    available_namespaces  # if default isn't even there
                )

            # Try to set a sensible default for the UI if the auto-detected one is not in the list
            selected_namespace_for_ui = (
                display_namespaces_for_selector[0]
                if display_namespaces_for_selector
                else "default"
            )

        else:
            display_namespaces_for_selector = available_namespaces
            selected_namespace_for_ui = current_namespace_from_kube_lib

        try:
            selected_ns_index = display_namespaces_for_selector.index(
                selected_namespace_for_ui
            )
        except (
            ValueError
        ):  # Fallback if selected_namespace_for_ui is somehow not in the list
            selected_ns_index = 0
            selected_namespace_for_ui = (
                display_namespaces_for_selector[0]
                if display_namespaces_for_selector
                else "default"
            )

        newly_selected_namespace = st_object.selectbox(
            "Select Kubernetes Namespace:",
            options=display_namespaces_for_selector,
            index=selected_ns_index,
            key=f"{resource_type_name.lower()}_namespace_selector",
        )

        if (
            newly_selected_namespace
            and newly_selected_namespace
            != st.session_state.get("selected_k8s_namespace")
        ):
            st.session_state.selected_k8s_namespace = newly_selected_namespace
            st.info(
                f"Namespace changed to: **{newly_selected_namespace}**. Refreshing list..."
            )
            # Clear selection of specific resource if namespace changes
            if session_state_key_selected_resource in st.session_state:
                st.session_state[session_state_key_selected_resource] = None
            st.rerun()

    # Use the namespace from session state, which reflects the user's selection
    namespace_to_use = st.session_state.get(
        "selected_k8s_namespace", current_namespace_from_kube_lib
    )

    st_object.write(
        f"Displaying {resource_type_name.lower()}s from namespace: **{namespace_to_use}**. "
        f"Use the dropdown above to change namespaces."
    )
    st_object.markdown("---")

    if session_state_key_selected_resource not in st.session_state:
        st.session_state[session_state_key_selected_resource] = None

    if st.session_state[session_state_key_selected_resource]:
        # --- Detail View ---
        selected_resource_name = st.session_state[session_state_key_selected_resource]
        render_details_func(selected_resource_name)
        st_object.markdown("---")
        if st_object.button(
            f"Back to {resource_type_name} List",
            key=f"back_to_{resource_type_name.lower()}_list_btn",
        ):
            st.session_state[session_state_key_selected_resource] = None
            st.rerun()
    else:
        # --- List View ---
        st_object.subheader(f"Available {resource_type_name}s in '{namespace_to_use}'")
        if not custom_obj_api:
            st_object.warning(
                f"Kubernetes API client not initialized. Cannot fetch {resource_type_name.lower()} list."
            )
            return

        resources = list_resources_func(st_object, custom_obj_api, namespace_to_use)

        if resources:
            for resource_item in resources:
                item_metadata = resource_item.get("metadata", {})
                item_spec = resource_item.get("spec", {})

                item_name = item_metadata.get("name", "N/A")
                item_description = item_spec.get(
                    "description", "No description provided."
                )
                item_labels = item_metadata.get("labels", {})

                tags = extract_tags_from_labels(item_labels)
                status = is_deployment_ready(resource_item)

                with st_object.container(border=True):
                    col_name, col_button = st.columns([3, 2])
                    with col_name:
                        st.markdown(f"### {item_name}")
                        st.write(f"**Description:** {item_description}")
                        st.write(f"**Status:** {status}")
                        display_tags(st, tags)
                    with col_button:
                        st.markdown(
                            "<div style='height: 20px;'></div>", unsafe_allow_html=True
                        )
                        button_key = f"view_details_{sanitize_for_session_state_key(item_name)}_{resource_type_name.lower()}"
                        if st.button("📋 View Details", key=button_key):
                            st.session_state[session_state_key_selected_resource] = (
                                item_name
                            )
                            st.rerun()

                        # Enable the Delete button if delete function is provided in arg list
                        if delete_resource_func:
                            # pylint: disable=line-too-long
                            delete_confirm_key = f"delete_confirm_{sanitize_for_session_state_key(item_name)}_{resource_type_name.lower()}"

                            # Initialize delete confirmation state for the delete key
                            if delete_confirm_key not in st.session_state:
                                st.session_state[delete_confirm_key] = False

                            if not st.session_state[delete_confirm_key]:
                                delete_button_key = f"delete_{sanitize_for_session_state_key(item_name)}_{resource_type_name.lower()}"
                                if st.button(
                                    "🗑️ Delete",
                                    key=delete_button_key,
                                    type="secondary",
                                    help=f"Delete {resource_type_name} '{item_name}'",
                                ):
                                    st.session_state[delete_confirm_key] = True
                                    # Refresh screen to show confirmation buttons
                                    st.rerun()
                            else:
                                # Confirmation buttons
                                st.write("⚠️ **Confirm delete?**")

                                col_confirm, col_cancel = st.columns([1, 1])

                                with col_confirm:
                                    confirm_button_key = f"confirm_delete_{sanitize_for_session_state_key(item_name)}_{resource_type_name.lower()}"
                                    if st.button(
                                        "✅ Yes",
                                        key=confirm_button_key,
                                        type="primary",
                                        help="Confirm deletion",
                                    ):
                                        try:
                                            # Call the delete function
                                            delete_resource_func(
                                                custom_obj_api,
                                                item_name,
                                                namespace_to_use,
                                            )
                                            st.success(
                                                f"Successfully deleted {resource_type_name} '{item_name}'"
                                            )

                                            # Reset confirmation state
                                            st.session_state[delete_confirm_key] = False
                                            st.rerun()

                                        except Exception as e:
                                            st.error(
                                                f"Failed to delete {resource_type_name}: {str(e)}"
                                            )
                                            st.session_state[delete_confirm_key] = False

                                with col_cancel:
                                    cancel_button_key = f"cancel_delete_{sanitize_for_session_state_key(item_name)}_{resource_type_name.lower()}"
                                    if st.button(
                                        "❌ No",
                                        key=cancel_button_key,
                                        help="Cancel deletion",
                                    ):
                                        st.session_state[delete_confirm_key] = False
                                        st.rerun()
        else:
            st_object.info(
                f"No '{resource_type_name}' custom resources with the required labels found in the '{namespace_to_use}' namespace."
            )


def display_resource_metadata(st_object, resource_details: dict):
    """
    Displays common metadata for a Kubernetes resource (Agent or Tool).

    Args:
        st_object (streamlit.BaseStreamlitWidget): The Streamlit object for displaying content.
        resource_details (dict): The dictionary representation of the resource.

    Returns:
        A dictionary of extracted tags.
    """
    if not resource_details:
        st_object.warning("No resource details to display.")
        return {}

    spec = resource_details.get("spec", {})
    metadata = resource_details.get("metadata", {})

    description = spec.get("description", "No description available.")
    creation_timestamp = metadata.get("creationTimestamp", "N/A")
    status = is_deployment_ready(resource_details)
    labels = metadata.get("labels", {})
    tags = extract_tags_from_labels(labels)

    st_object.write(f"**Description:** {description}")
    st_object.write(f"**Status:** {status}")
    st_object.write(f"**Created On:** {creation_timestamp}")
    display_tags(st_object, tags)
    st_object.markdown("---")
    return tags


def check_auth():
    """If authentication is enabled, display content only if the user is logged in"""
    if (
        constants.ENABLE_AUTH_STRING in st.session_state
        and st.session_state[constants.ENABLE_AUTH_STRING]
        and constants.TOKEN_STRING not in st.session_state
    ):
        st.page_link("Home.py", label="Click here to login", icon="🏠")

        # Stop rendering other content
        st.stop()
