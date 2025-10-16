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
MCP Client.
"""

import logging
from typing import Optional, List, Dict, Any
from contextlib import AsyncExitStack
import anyio
from mcp import ClientSession  # type: ignore
from mcp.client.streamable_http import streamablehttp_client  # type: ignore
import httpx

DEFAULT_AUTH_TOKEN = "my_token"

logger = logging.getLogger(__name__)


class MCPClientWrapper:
    """
    A wrapper class for interacting with the MCP server.
    It provides methods to list available tools and execute them.
    """

    def __init__(self, mcp_server_url: str, auth_token: Optional[str] = None):
        """
        Initialize the MCPClientWrapper with the server URL and authentication token.

        :param mcp_server_url: The URL of the MCP server.
        :param auth_token: The authentication token for the MCP server. Defaults to DEFAULT_AUTH_TOKEN.
        """
        self.mcp_server_url = mcp_server_url
        self.auth_token = auth_token or DEFAULT_AUTH_TOKEN
        self.cached_tools: List[Dict[str, Any]] = []
        self.last_list_tools_successful: bool = False

    async def get_tools_from_server(self) -> List[Dict[str, Any]]:
        """
        Connects to the MCP server, lists available tools, caches them, and returns them.
        Manages its own AsyncExitStack for the duration of this operation.
        """
        # Reset state for this attempt
        self.cached_tools = []
        self.last_list_tools_successful = False

        exit_stack = AsyncExitStack()  # Local stack for this operation
        try:
            async with exit_stack:  # Ensures aclose is called on this stack
                headers = {"Authorization": f"Bearer {self.auth_token}"}

                # Connect to an MCP server running with HTTP Streamable transport
                streams_context = streamablehttp_client(  # pylint: disable=W0201
                    url=self.mcp_server_url,
                    headers=headers or {},
                )
                read_stream, write_stream, _ = await streams_context.__aenter__()  # pylint: disable=E1101

                session_context = ClientSession(read_stream, write_stream)  # pylint: disable=W0201
                session: ClientSession = await session_context.__aenter__()  # pylint: disable=C2801

                await session.initialize()

                logger.info("MCP session initialized for listing tools.")

                response = await session.list_tools()
                if response and hasattr(response, "tools"):
                    self.cached_tools = [
                        {
                            "name": tool.name,
                            "description": tool.description,
                            "input_schema": (
                                tool.inputSchema if hasattr(tool, "inputSchema") else {}
                            ),
                        }
                        for tool in response.tools
                    ]
                    logger.info(
                        f"Successfully listed tools. Found: {[tool['name'] for tool in self.cached_tools]}"
                    )
                    self.last_list_tools_successful = True
                    return self.cached_tools

                logger.warning("MCP list_tools response was empty or malformed.")
                return []
        except httpx.ConnectError as e:
            logger.error(
                f"MCP Connection Error while listing tools from {self.mcp_server_url}: {e}",
                exc_info=False,
            )
            raise ConnectionError(
                f"Failed to connect to MCP server at {self.mcp_server_url} to list tools: {e}"
            ) from e
        except Exception as e:
            logger.error(
                f"Failed to list tools from MCP server {self.mcp_server_url}: {e}",
                exc_info=True,
            )
            raise ConnectionError(
                f"An unexpected error occurred while listing tools from MCP server: {e}"
            ) from e

    async def execute_tool_on_server(
        self, tool_name: str, tool_args: Dict[str, Any]
    ) -> Any:
        """
        Connects to the MCP server, initializes a session, and calls the specified tool.
        Manages its own AsyncExitStack for the duration of this operation.

        :param tool_name: The name of the tool to execute.
        :param tool_args: The args for the tool.
        """
        logger.info(
            f"Attempting to connect and call MCP tool '{tool_name}' with args: {tool_args} on {self.mcp_server_url}"
        )
        exit_stack = AsyncExitStack()  # Local stack for this operation
        try:
            async with exit_stack:  # Ensures aclose is called on this stack
                headers = {"Authorization": f"Bearer {self.auth_token}"}

                streams_context = streamablehttp_client(  # pylint: disable=W0201
                    url=self.mcp_server_url,
                    headers=headers or {},
                )
                read_stream, write_stream, _ = await streams_context.__aenter__()  # pylint: disable=E1101

                session_context = ClientSession(read_stream, write_stream)  # pylint: disable=W0201
                session: ClientSession = await session_context.__aenter__()  # pylint: disable=C2801

                await session.initialize()
                logger.info(f"MCP session initialized for calling tool '{tool_name}'.")

                response = await session.call_tool(tool_name, tool_args)
                logger.info(f"MCP tool '{tool_name}' response: {response}")
                return response
        except httpx.ConnectError as e:
            logger.error(
                f"MCP Connection Error while calling tool '{tool_name}' on {self.mcp_server_url}: {e}",
                exc_info=False,
            )
            raise ConnectionError(
                f"Failed to connect to MCP server at {self.mcp_server_url} to call tool '{tool_name}': {e}"
            ) from e
        except anyio.ClosedResourceError as cre:
            logger.error(
                f"MCP ClosedResourceError while calling tool '{tool_name}': {cre}",
                exc_info=True,
            )
            raise ConnectionError(
                f"MCP connection closed unexpectedly while calling tool '{tool_name}'."
            ) from cre
        except Exception as e:
            logger.error(
                f"Error calling MCP tool '{tool_name}' on {self.mcp_server_url}: {e}",
                exc_info=True,
            )
            raise ConnectionError(
                f"An unexpected error occurred while calling MCP tool '{tool_name}': {e}"
            ) from e

    # get_cached_tools can be used by the UI to display tools without a new server call
    def get_cached_tools(self) -> List[Dict[str, Any]]:
        """
        Returns the cached list of tools.
        """
        return self.cached_tools

    def is_last_list_tools_successful(self) -> bool:
        """
        Returns whether the last call to list tools was successful.
        """
        return self.last_list_tools_successful
