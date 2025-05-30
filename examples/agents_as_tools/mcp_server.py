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

from starlette.applications import Starlette
from starlette.routing import Mount, Route
import uvicorn
from mcp.server.fastmcp import FastMCP, Context
from mcp.server.sse import SseServerTransport
import httpx
import mcp.types as types
from crew.researcher import Researcher


server = FastMCP("FastMCP Server")


# tool definition
@server.tool(
    description="given a topic, research that topic and provide"
    + "a list with 5 bullet points of the most relevant information about it"
)
async def researcher(
    topic: str, ctx: Context
) -> list[types.TextContent | types.ImageContent | types.EmbeddedResource]:
    headers = {
        "User-Agent": "MCP Test Server (github.com/modelcontextprotocol/python-sdk)"
    }
    researcher = Researcher()
    return researcher.crew().kickoff(inputs={"topic": topic})


# Create an SseServerTransport instance
sse = SseServerTransport("/messages/")


async def handle_sse(request):
    async with sse.connect_sse(
        request.scope, request.receive, request._send
    ) as streams:
        await server._mcp_server.run(
            streams[0], streams[1], server._mcp_server.create_initialization_options()
        )


app = Starlette(
    debug=True,
    routes=[
        Route("/sse", endpoint=handle_sse),
        Mount("/messages/", app=sse.handle_post_message),
    ],
)

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8001)
