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
Utilities for handling [A2A](https://github.com/a2aproject/A2A) protocol.
"""

import logging
from uuid import uuid4
from typing import Any, Tuple
import streamlit as st
import httpx
from a2a.client import A2ACardResolver, A2AClient
from a2a.types import (
    AgentCard,
    AgentCapabilities,
    AgentProvider,
    Task,
    Message as A2AMessage,  # Renamed to avoid conflict with Streamlit's Message
    TaskStatusUpdateEvent,
    TaskArtifactUpdateEvent,
    MessageSendParams,
    SendStreamingMessageRequest,
    SendStreamingMessageSuccessResponse,
    JSONRPCErrorResponse,
    TextPart,
    DataPart,
)
from lib.constants import ACCESS_TOKEN_STRING, TOKEN_STRING
from . import constants
from .utils import append_to_log_history

# Configure logger for this module
logger = logging.getLogger(__name__)
# Basic config should ideally be called once at app startup (e.g. in Home.py or main script)
logging.basicConfig(level=logging.INFO)


async def _fetch_agent_card_with_resolver(
    st_object,
    httpx_client: httpx.AsyncClient,
    base_url: str,
    relative_card_path: str,
    auth_headers: dict = None,
) -> AgentCard | None:
    """Helper to fetch an agent card using A2ACardResolver."""
    try:
        resolver = A2ACardResolver(
            httpx_client=httpx_client,
            base_url=base_url,
            agent_card_path=constants.A2A_PUBLIC_AGENT_CARD_PATH,
        )
        logger.info(
            f"Attempting to fetch agent card from path: {relative_card_path} on base URL: {base_url}"
        )

        http_kwargs = {"headers": auth_headers} if auth_headers else {}
        agent_card: AgentCard = await resolver.get_agent_card(
            relative_card_path=relative_card_path, http_kwargs=http_kwargs
        )
        logger.info(
            f"Successfully retrieved Agent Card from path: {relative_card_path}."
        )
        logger.debug(agent_card.model_dump_json(indent=2, exclude_none=True))
        return agent_card
    except httpx.HTTPStatusError as e:
        error_msg = f"HTTP Error: {e.response.status_code} - {e.response.text}"
        logger.error(f"{error_msg} fetching from {e.request.url}")
        st_object.error(f"{error_msg} fetching from {e.request.url}")
    except httpx.RequestError as e:
        error_msg = f"Network Error: Could not connect to {base_url}. Error: {e}"
        logger.error(error_msg)
        st_object.error(error_msg)
    except AttributeError as e:
        error_msg = f"AttributeError fetching agent card (possibly an issue with A2A library or path handling): {e}"
        logger.error(error_msg, exc_info=True)
        st_object.error(error_msg)
    except Exception as e:
        error_msg = f"An unexpected error occurred fetching agent card: {e}"
        logger.error(
            error_msg, exc_info=True
        )  # Log full traceback for unexpected errors
        st_object.error(error_msg)
    return None


async def get_effective_agent_card(st_object, base_url: str) -> AgentCard | None:
    """
    Fetches the public agent card and, if supported and available, the authenticated extended card.
    Returns the most appropriate card (extended if available, otherwise public).
    """
    async with httpx.AsyncClient() as client:
        public_card = await _fetch_agent_card_with_resolver(
            st_object, client, base_url, constants.A2A_PUBLIC_AGENT_CARD_PATH
        )

        if not public_card:
            st_object.error(
                "Failed to fetch public agent card. Cannot proceed with A2A interaction."
            )
            return None

        if public_card.supportsAuthenticatedExtendedCard:
            logger.info(
                "Public card supports authenticated extended card. Attempting to fetch."
            )
            auth_headers = {"Authorization": constants.A2A_DUMMY_AUTH_TOKEN}
            extended_card = await _fetch_agent_card_with_resolver(
                st_object,
                client,
                base_url,
                constants.A2A_EXTENDED_AGENT_CARD_PATH,
                auth_headers,
            )
            if extended_card:
                logger.info("Using AUTHENTICATED EXTENDED agent card.")
                return extended_card

            logger.warning(
                "Failed to fetch extended card, falling back to public card."
            )
        else:
            logger.info(
                "Public card does not support extended card, or fetching failed. Using public card."
            )
        return public_card


# pylint: disable=too-many-branches
def display_a2a_agent_card_details(st_object, agent_card: AgentCard):
    """Displays formatted details of an A2A AgentCard using Streamlit components."""
    if not agent_card:
        st_object.warning("No Agent Card data to display.")
        return

    st_object.markdown(f"#### Agent: {agent_card.name} (v{agent_card.version})")
    st_object.markdown(f"**URL**: `{agent_card.url}`")
    if agent_card.description:
        st_object.markdown(f"**Description**: {agent_card.description}")
    if agent_card.documentationUrl:
        st_object.markdown(f"**Documentation**: [Link]({agent_card.documentationUrl})")

    with st_object.expander("Capabilities & Modes", expanded=False):
        if agent_card.capabilities:
            caps: AgentCapabilities = agent_card.capabilities
            st.markdown(f"  - Streaming Supported: `{caps.streaming}`")
            st.markdown(f"  - Push Notifications Supported: `{caps.pushNotifications}`")
            st.markdown(
                f"  - State Transition History Supported: `{caps.stateTransitionHistory}`"
            )
        else:
            st.markdown("  - Capabilities: Not specified")

        if agent_card.defaultInputModes:
            st.markdown(
                f"  - Default Input Modes: `{', '.join(agent_card.defaultInputModes)}`"
            )
        if agent_card.defaultOutputModes:
            st.markdown(
                f"  - Default Output Modes: `{', '.join(agent_card.defaultOutputModes)}`"
            )

    if agent_card.skills:
        with st_object.expander("Skills", expanded=False):
            for skill_obj in agent_card.skills:
                st.markdown(f"##### Skill: {skill_obj.name} (`{skill_obj.id}`)")
                if skill_obj.description:
                    st.markdown(f"  - Description: {skill_obj.description}")
                if skill_obj.tags:
                    st.markdown(f"  - Tags: `{', '.join(skill_obj.tags)}`")
                if skill_obj.examples:
                    st.markdown(f"  - Examples: `{', '.join(skill_obj.examples)}`")
                if skill_obj.inputModes:
                    st.markdown(f"  - Input Modes: `{', '.join(skill_obj.inputModes)}`")
                if skill_obj.outputModes:
                    st.markdown(
                        f"  - Output Modes: `{', '.join(skill_obj.outputModes)}`"
                    )
    else:
        st_object.markdown("**Skills**: None specified")

    if agent_card.provider:
        with st_object.expander("Provider Information", expanded=False):
            provider_obj: AgentProvider = agent_card.provider
            st.markdown(f"  - Organization: {provider_obj.organization}")
            if provider_obj.url:
                st.markdown(f"  - URL: [{provider_obj.url}]({provider_obj.url})")

    if agent_card.security or agent_card.securitySchemes:
        with st_object.expander("Security", expanded=False):
            if agent_card.security:
                st.markdown(f"  - Security Requirements: `{agent_card.security}`")
            if agent_card.securitySchemes:
                st.markdown(
                    f"  - Security Scheme Details: `{agent_card.securitySchemes}`"
                )

    st_object.caption(
        f"Supports Authenticated Extended Card: `{agent_card.supportsAuthenticatedExtendedCard}`"
    )


async def render_a2a_agent_card(st_object, base_url: str):
    """Retrieves and displays the A2A agent card details."""
    agent_card = await get_effective_agent_card(st_object, base_url)
    if agent_card:
        display_a2a_agent_card_details(st_object, agent_card)
    else:
        st_object.error("Could not retrieve agent card to display.")


# pylint: disable=too-many-branches, too-many-statements
def _process_a2a_stream_chunk(
    chunk_data, session_key_prefix: str, log_container, message_placeholder
) -> Tuple[str, bool]:
    """Processes a single chunk from the A2A streaming response."""
    full_response_content_chunk = ""
    is_final_event = False

    if isinstance(chunk_data.root, SendStreamingMessageSuccessResponse):
        event = chunk_data.root.result
        log_message = ""

        if isinstance(event, Task):
            log_message = f"ℹ️ Task Event (ID: {event.id}): Status - {event.status.state if event.status else 'N/A'}"
            if event.status and event.status.message and event.status.message.parts:
                text_content = " ".join(
                    [
                        p.root.text
                        for p in event.status.message.parts
                        if isinstance(p.root, TextPart)
                    ]
                )
                if text_content:
                    log_message += f" | Message: {text_content}"
            is_final_event = (
                event.status.state in ["COMPLETED", "FAILED"] if event.status else False
            )

        elif isinstance(event, A2AMessage):
            text_content = " ".join(
                [p.root.text for p in event.parts if isinstance(p.root, TextPart)]
            )
            log_message = f"💬 Agent Message (ID: {event.messageId}): {text_content}"
            # This isn't streamed to the main chat, but logged.

        elif isinstance(event, TaskStatusUpdateEvent):
            log_message = f"🔄 Task Status Update (ID: {event.taskId}): New State - {event.status.state}"
            if event.status.message and event.status.message.parts:
                text_content = " ".join(
                    [
                        p.root.text
                        for p in event.status.message.parts
                        if isinstance(p.root, TextPart)
                    ]
                )
                if text_content:
                    log_message += f" | Details: {text_content}"
            is_final_event = event.final

        elif isinstance(event, TaskArtifactUpdateEvent):
            log_message = f"🔄 Task Artifact Update (ID: {event.taskId}, Artifact: {event.artifact.artifactId})"
            for part in event.artifact.parts:
                if isinstance(part.root, TextPart):
                    full_response_content_chunk += part.root.text
                    log_message += f" | Text: '{part.root.text[:50]}...'"
                elif isinstance(part.root, DataPart):
                    data_str = str(part.root.data)
                    full_response_content_chunk += data_str
                    log_message += (
                        f" | Data: (type: {part.root.kind}, {len(data_str)} bytes)"
                    )
            if event.lastChunk:
                log_message += " (Last Chunk)"

        else:
            log_message = f"❓ Unknown A2A Event Type: {type(event)}"
            logger.warning(f"{log_message} - Data: {event.model_dump_json(indent=2)}")

        if log_message:
            append_to_log_history(session_key_prefix, log_message)
            log_container.markdown(log_message)

    elif isinstance(chunk_data.root, JSONRPCErrorResponse):
        error = chunk_data.root.error
        error_message = f"A2A Error (Code: {error.code}): {error.message}"
        if error.data:
            error_message += f" | Data: {error.data}"
        logger.error(error_message)
        append_to_log_history(session_key_prefix, f"❌ {error_message}")
        log_container.error(error_message)
        message_placeholder.error(error_message)
        full_response_content_chunk = error_message
        is_final_event = True

    else:
        unknown_chunk_msg = (
            f"--- Received Unexpected A2A Chunk Type: {type(chunk_data.root)} ---"
        )
        logger.warning(
            f"{unknown_chunk_msg}\nRaw Chunk: {chunk_data.model_dump_json(indent=2)}"
        )
        append_to_log_history(session_key_prefix, f"❓ {unknown_chunk_msg}")
        log_container.warning(unknown_chunk_msg)

    return full_response_content_chunk, is_final_event


# pylint: disable=too-many-branches, too-many-statements, too-many-arguments, too-many-locals, too-many-positional-arguments
async def run_agent_chat_stream_a2a(
    st_object,
    session_key_prefix: str,
    user_message: str,
    agent_url: str,
    message_placeholder,
    log_container,
) -> str:
    """
    Asynchronously runs an agent-to-agent chat stream with error handling and logging.

    Args:
        st_object (StreamlitObject): The Streamlit object to interact with for displaying messages and errors.
        session_key_prefix (str): The session key prefix for logging purposes.
        user_message (str): The user's input message to send to the agent.
        agent_url (str): The URL of the agent to communicate with.
        message_placeholder (Placeholder): The placeholder object to display messages and errors.
        log_container (LogContainer): The log container object to store logs.

    Returns:
        str: The full response content from the agent.

    Raises:
        HTTPStatusError: If an HTTP status error occurs during the chat.
        RequestError: If a network error occurs during the chat.
        Exception: If any other unexpected error occurs during the chat.

    The function initializes an A2AClient, sends a streaming message to the agent, and processes the response chunks.
    It handles various exceptions, logs errors, and updates the message placeholder with the response content.
    Finally, it returns the full response content from the agent.
    """
    full_response_content = ""
    effective_agent_card = await get_effective_agent_card(st_object, agent_url)
    if not effective_agent_card:
        err_msg = "Failed to initialize A2A client: No effective agent card."
        st_object.error(err_msg)
        append_to_log_history(session_key_prefix, f"❌ {err_msg}")
        log_container.error(err_msg)
        return err_msg

    async with httpx.AsyncClient() as httpx_client:
        try:
            client = A2AClient(httpx_client=httpx_client, url=agent_url)
            logger.info("A2AClient initialized.")

            send_message_payload: dict[str, Any] = {
                "message": {
                    "role": "user",
                    "parts": [{"kind": "text", "text": user_message}],
                    "messageId": uuid4().hex,
                },
            }

            streaming_request = SendStreamingMessageRequest(
                id=str(uuid4()), params=MessageSendParams(**send_message_payload)
            )
            http_kwargs = {}
            if TOKEN_STRING in st.session_state:
                if ACCESS_TOKEN_STRING in st.session_state[TOKEN_STRING]:
                    bearer_token = st.session_state[TOKEN_STRING][ACCESS_TOKEN_STRING]
                    http_kwargs = {
                        "headers": {"Authorization": f"Bearer {bearer_token}"}
                    }

            stream_response_iterator = client.send_message_streaming(
                streaming_request, http_kwargs=http_kwargs
            )

            async for chunk in stream_response_iterator:
                chunk_text, is_final = _process_a2a_stream_chunk(
                    chunk, session_key_prefix, log_container, message_placeholder
                )
                if chunk_text:
                    full_response_content += chunk_text
                    message_placeholder.markdown(full_response_content + "▌")

                if is_final:
                    message_placeholder.markdown(full_response_content)
                    break
            else:  # Loop completed without break (e.g., no explicit final event received)
                message_placeholder.markdown(full_response_content)

        except httpx.HTTPStatusError as e:
            error_msg = f"A2A HTTP Status Error during chat: {e.response.status_code} - {e.response.text}"
            logger.error(f"{error_msg} from {e.request.url}", exc_info=True)
            st_object.error(error_msg)
            append_to_log_history(session_key_prefix, f"❌ {error_msg}")
            log_container.error(error_msg)
            full_response_content = error_msg
            if message_placeholder:
                message_placeholder.error(error_msg)
        except httpx.RequestError as e:  # More general network errors
            error_msg = f"A2A Network Request Error during chat: Could not connect to {agent_url}. Error: {e}"
            logger.error(error_msg, exc_info=True)
            st_object.error(error_msg)
            append_to_log_history(session_key_prefix, f"❌ {error_msg}")
            log_container.error(error_msg)
            full_response_content = error_msg
            if message_placeholder:
                message_placeholder.error(error_msg)
        except Exception as e:  # Catch any other unexpected errors during streaming
            error_msg = f"An unexpected error occurred during A2A chat streaming: {e}"
            logger.error(error_msg, exc_info=True)
            st_object.error(error_msg)
            append_to_log_history(session_key_prefix, f"❌ {error_msg}")
            log_container.error(error_msg)
            full_response_content = error_msg
            if message_placeholder:
                message_placeholder.error(error_msg)
        finally:
            # Attempt to explicitly close the stream iterator if it was created and has an aclose method.
            # This is important for httpx.Response based streams.
            if stream_response_iterator and hasattr(stream_response_iterator, "aclose"):
                logger.info(
                    "Attempting to explicitly aclose A2A stream response iterator."
                )
                try:
                    await stream_response_iterator.aclose()
                    logger.info("A2A stream response iterator aclosed successfully.")
                except RuntimeError as re:
                    # These errors during aclose can sometimes be logged as warnings if the stream
                    # might have been implicitly closed or is in a state where explicit close is problematic.
                    if (
                        "already running" in str(re).lower()
                        or "no running event loop" in str(re).lower()
                    ):
                        logger.warning(
                            f"RuntimeError during explicit aclose of A2A stream (may be benign): {re}"
                        )
                    else:  # Other RuntimeErrors during aclose are more concerning
                        logger.error(
                            f"Unexpected RuntimeError during explicit aclose of A2A stream: {re}",
                            exc_info=True,
                        )
                except Exception as ex_aclose:  # Catch any other error during aclose
                    logger.error(
                        f"Exception during explicit aclose of A2A stream: {ex_aclose}",
                        exc_info=True,
                    )
            # The `async with httpx_client:` statement handles closing the httpx_client itself.

    return full_response_content
