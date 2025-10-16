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
Utilities for UI code.
"""

import re
import os
import streamlit as st
from . import constants


def display_tags(st_object, tags_dict: dict):
    """
    Displays a dictionary of tags in a single row with gray backgrounds.

    Args:
        st_object: Streamlit object for displaying markdown.
        tags_dict: A dictionary of tags.
                   Example: {"framework": "LangGraph", "language": "Python"}
    """
    if not tags_dict:
        return

    tag_strings = [
        f":gray-background[{category}: {value}]"
        for category, value in tags_dict.items()
    ]
    full_string = "**Tags:** " + "&nbsp;".join(tag_strings)
    st_object.markdown(full_string, unsafe_allow_html=True)


def extract_tags_from_labels(labels: dict) -> dict:
    """
    Extracts tags relevant to 'kagenti.io/' from Kubernetes labels.

    Args:
        labels: A dictionary of Kubernetes labels.

    Returns:
        A dictionary of extracted tags.
    """
    tags = {}
    if not labels:
        return tags
    for key, value in labels.items():
        if key.startswith(constants.KAGENTI_LABEL_PREFIX):
            tag_name = key.replace(constants.KAGENTI_LABEL_PREFIX, "")
            tags[tag_name] = value
    return tags


def sanitize_for_k8s_name(name: str) -> str:
    """
    Sanitizes a string to be a valid Kubernetes resource name.

    Converts to lowercase, replaces disallowed characters (like underscores) with hyphens,
    and ensures it starts and ends with an alphanumeric character.
    Limits length to Kubernetes standards (e.g., 63 for many resources).
    """
    if not name:
        return ""
    # Replace underscores and other common separators with hyphens
    name = name.replace("_", constants.AGENT_NAME_SEPARATOR).replace(
        " ", constants.AGENT_NAME_SEPARATOR
    )
    # Convert to lowercase
    name = name.lower()
    # Keep only alphanumeric characters and hyphens
    name = re.sub(r"[^a-z0-9-]", "", name)
    # Remove leading/trailing hyphens
    name = name.strip(constants.AGENT_NAME_SEPARATOR)
    # Truncate to a reasonable length (e.g., 63 chars, common k8s limit)
    name = name[:63]
    # Ensure it doesn't end with a hyphen after truncation
    name = name.rstrip(constants.AGENT_NAME_SEPARATOR)
    return name


def sanitize_for_session_state_key(name: str) -> str:
    """Sanitizes names for use in Python variables and Streamlit session state keys."""
    if not name:
        return "default_key"
    return re.sub(r"\W|^(?=\d)", "_", name)  # Replace non-alphanumeric with underscore


def remove_url_prefix(url: str, prefix: str = "https://") -> str:
    """Removes a given prefix from a URL if it exists."""
    if url and url.startswith(prefix):
        return url[len(prefix) :]
    return url


def get_resource_name_from_path(path: str) -> str:
    """
    Extracts a resource name from the last part of a file path.

    Example: "a2a/a2a_currency_converter" -> "a2a-currency-converter"
    """
    if not path:
        return ""
    base_name = os.path.basename(path.strip("/\\"))
    return sanitize_for_k8s_name(base_name)


def initialize_chat_session_state(session_key_prefix: str):
    """Initializes chat and log history in session state for a given prefix."""
    chat_history_key = f"chat_history_{session_key_prefix}"
    log_history_key = f"log_history_{session_key_prefix}"

    if chat_history_key not in st.session_state:
        st.session_state[chat_history_key] = []
    if log_history_key not in st.session_state:
        st.session_state[log_history_key] = []


def display_chat_history(session_key_prefix: str):
    """Displays all messages from the current item's chat history."""
    chat_history_key = f"chat_history_{session_key_prefix}"
    if chat_history_key in st.session_state:
        for message in st.session_state[chat_history_key]:
            with st.chat_message(message["role"]):
                st.markdown(message["content"])


def append_to_chat_history(session_key_prefix: str, role: str, content: str):
    """Appends a message to the chat history."""
    chat_history_key = f"chat_history_{session_key_prefix}"
    if chat_history_key not in st.session_state:
        st.session_state[chat_history_key] = []
    st.session_state[chat_history_key].append({"role": role, "content": content})


def append_to_log_history(session_key_prefix: str, log_content: str):
    """Appends a log entry to the log history."""
    log_history_key = f"log_history_{session_key_prefix}"
    if log_history_key not in st.session_state:
        st.session_state[log_history_key] = []
    st.session_state[log_history_key].append(log_content)


def display_log_history(st_object, session_key_prefix: str):
    """Displays all messages from the current item's log history."""
    log_history_key = f"log_history_{session_key_prefix}"
    if log_history_key in st.session_state:
        for log_entry in st.session_state[log_history_key]:
            st_object.markdown(log_entry)


def clear_log_history(session_key_prefix: str):
    """Clears the log history for a given session prefix."""
    log_history_key = f"log_history_{session_key_prefix}"
    if log_history_key in st.session_state:
        st.session_state[log_history_key] = []
