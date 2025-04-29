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
from llama_stack_client.types.shared_params.url import URL
from rich.pretty import pprint
import argparse


def run_main(
    host: str,
    port: int,
    unregister_toolgroup: bool,
    register_toolgroup: bool,
    toolgroup_id: str,
    mcp_endpoint: str,
):
    api_key = "eyJhbGciOiJSUzI1NiIsInR5cCIgOiAiSldUIiwia2lkIiA6ICJ3dGRua2FtNk9DdGpLcTRuRmsxcjhscjdCU2l1Q1NjZW4taHE3RC1aZVlJIn0.eyJleHAiOjE3NDU5NDkzMzgsImlhdCI6MTc0NTk0OTAzOCwianRpIjoib25ydHJvOmFiZjIwM2QzLTRiOTAtNGM5Zi05ZDFkLWU0ODg0NDEyOGNhZSIsImlzcyI6Imh0dHA6Ly9sb2NhbGhvc3Q6ODA4MC9yZWFsbXMvZGVtbyIsImF1ZCI6WyJteS1leHRlcm5hbC10b29sIiwiYWNjb3VudCJdLCJzdWIiOiI5YmI2NTQ1ZS0wN2NmLTRiNzQtOTQxMi1hMmY1MGNiYmRlNmUiLCJ0eXAiOiJCZWFyZXIiLCJhenAiOiJsbGFtYV9zdGFjayIsInNpZCI6IjE5MmM5MGM5LTFmNTAtNGMwNy1hM2VmLTI0MjdhMzNkYTExNCIsImFjciI6IjEiLCJhbGxvd2VkLW9yaWdpbnMiOlsiLyoiXSwicmVhbG1fYWNjZXNzIjp7InJvbGVzIjpbIm9mZmxpbmVfYWNjZXNzIiwidW1hX2F1dGhvcml6YXRpb24iLCJkZWZhdWx0LXJvbGVzLWRlbW8iXX0sInJlc291cmNlX2FjY2VzcyI6eyJhY2NvdW50Ijp7InJvbGVzIjpbIm1hbmFnZS1hY2NvdW50IiwibWFuYWdlLWFjY291bnQtbGlua3MiLCJ2aWV3LXByb2ZpbGUiXX19LCJzY29wZSI6InByb2ZpbGUgZW1haWwiLCJlbWFpbF92ZXJpZmllZCI6dHJ1ZSwibmFtZSI6ImFsYW4gYWxhbiIsInByZWZlcnJlZF91c2VybmFtZSI6ImFsYW4iLCJnaXZlbl9uYW1lIjoiYWxhbiIsImZhbWlseV9uYW1lIjoiYWxhbiIsImVtYWlsIjoiYWxhbkBhbGFuLmNvbSJ9.em1Pb72g4KAQuQB9bv2SSVeMAUwi1F0BoEQ9qz8k3N0hNckAIXvgKMShe-XilM25KMTGFPEX8J_Ue2OtzFrI4zmFsq7fkm6D4knPMqxjFIvr8PSAgDFKUDqOkc3pRg0a_G7wKPdQ7g9lqOUTBPIbCUJakewNS4XxR0U8IdcRrsqEs-oaWHp7aX2IIS0A-SdSrrmW3ah0zWNTXLb24nSCK0ykt3Q6YRMmYGUCboICa-2SzeIUd9BaqSOr8cXcZ7IBUxwMJth1XSg9DOgwUL-eQ4svJTVbngmWPTetCmnYeC6HmP2qQ5mlc_E7dP4Ux9J2MIMAfrn_Apvj3nlMykLBJA"

    client = LlamaStackClient(
        base_url=f"http://{host}:{port}",
        provider_data={
            "api_key": api_key,
        },
    )

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
                provider_id="model-context-protocol",
                mcp_endpoint=URL(uri=mcp_endpoint),
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
            "url": "http://localhost:10000"
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

    args = parser.parse_args()

    run_main(
        host=args.host,
        port=args.port,
        unregister_toolgroup=args.unregister_toolgroup,
        register_toolgroup=args.register_toolgroup,
        toolgroup_id=args.toolgroup_id,
        mcp_endpoint=args.mcp_endpoint,
    )
