from starlette.applications import Starlette
from starlette.routing import Mount, Route
import uvicorn
from mcp.server.fastmcp import FastMCP, Context
from mcp.server.sse import SseServerTransport
import httpx
import mcp.types as types


server = FastMCP("My FastMCP Server")


# tool definition
@server.tool()
async def fetch(
    url: str, ctx: Context
) -> list[types.TextContent | types.ImageContent | types.EmbeddedResource]:
    headers = {
        "User-Agent": "MCP Test Server (github.com/modelcontextprotocol/python-sdk)"
    }
    if ctx.request_context is not None and ctx.request_context.meta is not None:
        api_key = ctx.request_context.meta.api_key
        print(f"api_key={api_key}")
    async with httpx.AsyncClient(follow_redirects=True, headers=headers) as client:
        response = await client.get(url)
        response.raise_for_status()
        return [types.TextContent(type="text", text=response.text)]


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
    uvicorn.run(app, host="0.0.0.0", port=8000)