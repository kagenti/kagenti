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


from llama_stack_client import LlamaStackClient
from llama_stack_client.lib.agents.agent import Agent
from llama_stack_client.lib.agents.event_logger import EventLogger
from llama_stack_client.types.agent_create_params import AgentConfig
from llama_stack_client.types.agents.turn_create_params import Document
from termcolor import colored
from rich.pretty import pprint
import argparse


def run_main(
    host: str,
    port: int,
    unregister_toolgroup: bool,
    register_toolgroup: bool,
    list_toolgroups: bool,
    toolgroup_id: str,
    mcp_endpoint: str,
    mcp_fetch_url: str,
    api_key: str,
):
    client = LlamaStackClient(
        base_url=f"http://{host}:{port}",
        provider_data={
            "api_key": api_key,
        },
    )

    # Unregister the MCP Tool Group based on the flag
    if list_toolgroups:
        try:
            list = client.toolgroups.list()
            for toolgroup in list:
                pprint(toolgroup)
        except Exception as e:
            print(f"Error listing tool groups: {e}")
        return

    # Unregister the MCP Tool Group based on the flag
    if unregister_toolgroup:
        try:
            client.toolgroups.unregister(toolgroup_id=toolgroup_id)
            print(f"Successfully unregistered MCP tool group: {toolgroup_id}")
        except Exception as e:
            print(f"Error unregistering tool group: {e}")
        return

    # Register the MCP Tool Group based on the flag
    if register_toolgroup:
        try:
            client.toolgroups.register(
                toolgroup_id=toolgroup_id,
                provider_id="mcp-identity",
                mcp_endpoint=dict(uri=mcp_endpoint),
                args={"metadata": {"key1": "value1", "key2": "value2"}},
            )
            print(f"Successfully registered MCP tool group: {toolgroup_id}")
        except Exception as e:
            print(f"Error registering tool group: {e}")
        return

    for toolgroup in client.toolgroups.list():
        pprint(toolgroup)

    print(f"listing tools for {toolgroup_id}")
    tools = client.tools.list(toolgroup_id=toolgroup_id)  # List tools in the group
    for tool in tools:
        pprint(tool)

    result = client.tool_runtime.invoke_tool(
        tool_name="fetch",
        kwargs={
            "url": mcp_fetch_url
        },
    )
    print(result)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run your script with arguments.")

    parser.add_argument("--host", type=str, required=True, help="Specify the host.")
    parser.add_argument(
        "--port", type=int, required=True, help="Specify the port number."
    )
    parser.add_argument(
        "--list_toolgroups",
        action="store_true",
        help="Flag to list toolgroups.",
    )
    parser.add_argument(
        "--unregister_toolgroup",
        action="store_true",
        help="Flag to unregister toolgroup.",
    )
    parser.add_argument(
        "--register_toolgroup", action="store_true", help="Flag to register toolgroup."
    )
    parser.add_argument(
        "--toolgroup_id",
        type=str,
        required=False,
        default="remote::web-fetch",
        help="Specify the id of the toolgroup -e.g. remote::mygroup",
    )
    parser.add_argument(
        "--mcp_endpoint",
        type=str,
        required=False,
        default="http://localhost:8000/sse",
        help="Specify the MCP endpoint.",
    )
    parser.add_argument(
        "--mcp_fetch_url",
        type=str,
        required=False,
        default="https://raw.githubusercontent.com/kubestellar/kubeflex/refs/heads/main/docs/contributors.md",
        help="Specify where the MCP server fetches",
    )
    parser.add_argument(
        "--access_token",
        type=str,
        required=False,
        default="some-api-key",
        help="Bearer token for tool at MCP Fetch URL",
    )

    args = parser.parse_args()

    run_main(
        host=args.host,
        port=args.port,
        list_toolgroups=args.list_toolgroups,
        unregister_toolgroup=args.unregister_toolgroup,
        register_toolgroup=args.register_toolgroup,
        toolgroup_id=args.toolgroup_id,
        mcp_endpoint=args.mcp_endpoint,
        mcp_fetch_url=args.mcp_fetch_url,
        api_key=args.access_token,
    )
