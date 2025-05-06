# Proof-Of-Concepts

The following proof on concepts have been implemented on Llama Stack.

## Installation

### Prereqs: 

- Make sure you have Python 3.11+ installed
- Install a [conda-forge](https://conda-forge.org/download/) distribution for your environment 
- Install [ollama](https://ollama.com/download)


### Setup

Clone this project:

```shell
git clone git@github.com:kagenti/kagenti.git
cd kagenti
```

On one terminal, run:

```shell
ollama run llama3.2:3b --keepalive 60m
```

On another terminal, run:

```shell
conda create -n stack python=3.10
conda activate stack
```

Install uv:

```shell
pip install uv
```

Install providers

```shell
cd providers
uv pip install -e .
```

Build Llama Stack

```shell
llama stack build --template ollama
```

Start Llama Stack:

```shell
export INFERENCE_MODEL=llama3.2:3b
llama stack run templates/ollama/run.yaml 
```

You are now ready to run the PoCs.


## API Key Propagation from LS client to MCP Tool Server

This PoC uses `provider_data` to send data to the MCP
tool_runtime. Details on design and implementation
are described in [this section.](./tech-details.md#api-key-propagation-to-mcp-tool)

Run llama stack server as above; open a new terminal and start sample 
MCP server with `web-fetch` tool:

```shell
conda activate stack
cd examples/mcp 
uv run sse_server.py
```

On a new terminal, first go back to `kagenti` directory `cd ../../`,
then run the following command to activate the env and register the tool group:

```shell
conda activate stack
python -m examples.clients.mcp.tool-util --host localhost --port 8321 --register_toolgroup
```

Then invoke the tool with:

```shell
python -m examples.clients.mcp.tool-util --host localhost --port 8321
```

verify the log for the MCP server, it should contain a printout like the following:

```console
[03/12/25 21:09:19] INFO     Processing request of type CallToolRequest                                    server.py:534
api_key=some-api-key
```

verify that this is the `api_key` provided in the client looking at the client code:

```shell
cat examples/clients/mcp/tool-util.py 
```

### Agent to Tool Key Propagation

As an extension to this PoC, you can verify that the `api_key` is propagated 
to the MCP tool when the tool is invoked by an agent instead than directly
by the client. A sequence diagram for this scenario is illustrated 
[here](./tech-details.md#api-key-propagation-to-mcp-tool).

After running the LS client to MCP Tool Server PoC, have a look at the
[agent-mcp client](../examples/clients/mcp/agent-mcp.py) code which uses
the MCP fetch tool registred in the previous step, then run the agent as
follows:

```shell
python -m examples.clients.mcp.agent-mcp localhost 8321
```
You should get an answer to the prompt that requires the agent to run
the MCP tool to fetch some info from the web. Verify the log for the MCP server
contains the `api_key` injected by the agent client.

```console
[03/13/25 16:02:04] INFO     Processing request of type CallToolRequest                                               server.py:534
api_key=some-api-key
```

## Agent as Tool

This Proof of Concept (PoC) involves registering a 
CrewAI agent as a tool within the MCP framework. Once 
registered, the Llama Stack agent, configured with this tool, 
can utilize the CrewAI agent to conduct research on a given topic 
and provide a final result. This PoC currently utilizes a 
single tool. However, it is conceivable that this approach could be 
extended to register multiple agents, even those developed with 
different frameworks, as tools. These tools can then be orchestrated 
by the Llama Stack agent. This method leverages Large Language Models 
(LLMs) to drive orchestration, offering a more dynamic alternative 
to user-defined static workflows.


Run llama stack server as above. On a new terminal, start 
the MCP server for CrewAI researcher agent:

```shell
conda activate stack
cd examples/agents_as_tools 
uv run mcp_server.py
```

on another terminal, run the following command to register the tool group:

```shell
conda activate stack
python -m examples.clients.mcp.tool-util --host localhost --port 8321 --register_toolgroup --toolgroup_id remote::researcher --mcp_endpoint http://localhost:8001/sse
```

finally, run the Llama Stack agent which should use the crewai researcher agent as a tool:

```shell
python -m examples.agents_as_tools.agent_mcp_agent localhost 8321
```


