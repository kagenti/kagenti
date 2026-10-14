# Copyright 2025 IBM Corp.
# Licensed under the Apache License, Version 2.0

"""
Regression test for issue #2312: connect_to_tool / invoke_tool must use the
mcp>=2.0.0 streamable_http_client transport (2-tuple return, no headers=
kwarg), not the pre-2.0 streamablehttp_client name and 3-tuple return.

Runs a real MCP server over streamable-http in a background thread and drives
the two endpoints against it end to end, so the test exercises the actual
transport call and tuple-unpacking shape rather than a mocked client.
"""

import socket
import threading
from unittest.mock import patch

import pytest
import uvicorn
from mcp.server.mcpserver import MCPServer

from app.routers.tools import MCPInvokeRequest, connect_to_tool, invoke_tool


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class _EventServer(uvicorn.Server):
    """uvicorn.Server that signals a threading.Event once startup() completes,
    so a hung server fails the fixture immediately instead of via a polling
    timeout that surfaces as a confusing connection error."""

    def __init__(self, config: uvicorn.Config, started_event: threading.Event) -> None:
        super().__init__(config)
        self._started_event = started_event

    async def startup(self, sockets=None) -> None:
        await super().startup(sockets=sockets)
        self._started_event.set()


@pytest.fixture(scope="module")
def mcp_server_url():
    """A real streamable-http MCP server exposing one 'echo' tool."""
    server = MCPServer("test-tool")

    @server.tool()
    def echo(text: str) -> str:
        return text

    app = server.streamable_http_app()
    port = _free_port()
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error")
    started_event = threading.Event()
    uv_server = _EventServer(config, started_event)
    thread = threading.Thread(target=uv_server.run, daemon=True)
    thread.start()
    if not started_event.wait(timeout=5):
        uv_server.should_exit = True
        thread.join(timeout=1)
        raise RuntimeError("MCP test server did not start within 5s")
    yield f"http://127.0.0.1:{port}"
    uv_server.should_exit = True
    thread.join(timeout=5)


@pytest.mark.asyncio
async def test_connect_to_tool_lists_tools(mcp_server_url):
    with patch("app.routers.tools._get_tool_url", return_value=mcp_server_url):
        response = await connect_to_tool(namespace="ns", name="echo-tool", kube=None)

    assert [t.name for t in response.tools] == ["echo"]


@pytest.mark.asyncio
async def test_invoke_tool_calls_tool(mcp_server_url):
    request = MCPInvokeRequest(tool_name="echo", arguments={"text": "hi"})
    with patch("app.routers.tools._get_tool_url", return_value=mcp_server_url):
        response = await invoke_tool(namespace="ns", name="echo-tool", request=request, kube=None)

    assert response.result["content"] == [{"type": "text", "text": "hi"}]
