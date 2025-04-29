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
git clone git@github.ibm.com:aiplatform/kagenti.git
cd kagenti
```

On one terminal, run:

```shell
ollama run llama3.2:3b-instruct-fp16 --keepalive 60m
```

On another terminal, run:

```shell
conda create -n stack python=3.10
conda activate stack
```

Install llama-stack tagged release with:

```shell
pip install uv
uv pip install llama-stack==v0.1.6
```

Update the registry with:

```shell
stack/scripts/update-registry.sh
```

Build the ollama template with the command:

```shell
PYTHONPATH=$(pwd) llama stack build --config stack/templates/ollama/build.yaml
```

You are now ready to run the PoCs.

## Multi-Framework Agent Provider

Running this PoC shows how to run Llama Stack and LangGraph Agents fronted by the Llama Stack API.

Run the server with:

```shell
export INFERENCE_MODEL="meta-llama/Llama-3.2-3B-Instruct"
llama stack run stack/templates/ollama/run.yaml 
```

When running the server on Mac, you might get a pop-up asking to
`accept incoming network connections`, so just click **Allow**.

On new terminal, activate env first with `conda activate stack`, then:

### Run Llama Stack Agent

```shell
python -m examples.clients.llama_stack.simple_rag localhost 8321
```

### Run LangGraph Agent

```shell
python -m examples.clients.langgraph.call_math_agent localhost 8321
```

### Run CrewAI Agent

```shell
python -m examples.clients.crewai.call_math_agent localhost 8321
```

## API Key Propagation from LS client to MCP Tool Server

This PoC uses `provider_data` to send data to the MCP
tool_runtime. Details on design and implementation
are described in [this section.](./tech-details.md#api-key-propagation-to-mcp-tool)

Run llama stack server as above. On a new terminal,
activate env first with `conda activate stack`, then:

Start example MCP server with `web-fetch` tool:

```shell
cd examples/mcp 
uv run sse_server.py
```

On a new terminal, first go back to `kagenti` directory `cd ../../`,
activate env with `conda activate stack`,
then run the following command to register the tool group:

```shell
python -m examples.clients.mcp.tool-util --host localhost --port 8321 --register_toolgroup
```

If you get an error:

```shell
ModuleNotFoundError: No module named 'llama_stack_client.types.shared_params.url'
```

Install an appropriate version of `llama_stack_client`:

```shell
pip install llama_stack_client==v0.1.6
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


Run llama stack server as above. On a new terminal, 
activate env first with `conda activate stack`, then:

Start MCP server for CrewAI researcher agent:

```shell
cd examples/agents_as_tools 
uv run mcp_server.py
```

on another reminal, activate env first with `conda activate stack`, 
then run the following command to register the tool group:

```shell
python -m examples.clients.mcp.tool-util --host localhost --port 8321 --register_toolgroup --toolgroup_id remote::researcher
```

finally, run the Llama Stack agent which should use the crewai researcher agent as a tool:

```shell
python -m examples.agents_as_tools.agent_mcp_agent localhost 8321
```

## Web-Queue-Worker Pattern

This pattern, implemented as part of the AMF provider, facilitates independent scaling 
of agents and tools separate from the API server. For a description of the architecture and
more technical details [check this section](./tech-details.md#web-queue-worker-pattern-architecture).
This pattern requires the use of a postgres and a redis DB. This PoC uses docker
to run the databases.

To run this PoC you need to have docker installed on your environment. 

### Starting the infrastructure services

On a terminal on the `llama-stack` project, run the following:

```shell
stack/scripts/start-infra.sh
```

This wil start a redis and a postgres container in docker.


### Starting llama-stack server

First, make sure that ollama is started as explained in the [setup section](#setup)

Open another terminal on the `llama-stack` project and branch previosuly cloned, then make sure the conda
env 'stack' is activated and run the server as follows:

```shell
conda activate stack
export INFERENCE_MODEL="meta-llama/Llama-3.2-3B-Instruct"
ROLE=producer llama stack run stack/templates/ollama/run-dispatcher.yaml 
```

### Starting llama-stack worker

Open another terminal on the `llama-stack` project and branch previosuly cloned, then make sure the conda
env `stack` is activated, and run the llama-stack agent worker
as follows:

```shell
conda activate stack
export INFERENCE_MODEL="meta-llama/Llama-3.2-3B-Instruct"
stack/scripts/run-worker.sh stack/templates/ollama/run-worker.yaml
```

### Running a Llama Stack agent turn using the SDK

On a new terminal on the `llama-stack`, run the following:

```shell
conda activate stack
python -m examples.clients.llama_stack.simple_rag localhost 8321
```

### Running other Llama Stack Agents demo from community

Clone the llama-stack-apps demo:

```shell
git clone https://github.com/meta-llama/llama-stack-apps.git
cd llama-stack-apps
```

You may use the same conda env as specified in the README or create a new one. For these instructions
we will use the same one:

```shell
conda activate stack
pip install -r requirements.txt
```

**Important** - to run the first example, you need a `$TAVILY_SEARCH_API_KEY`. You can get
a free one signig up at [tavily.com](https://tavily.com). The key is only required in the worker
as the agent and the tool call run there. Therefore, you need to stop the worker, set the key 
in the environment and restart:

On the terminal where you previosuly run the worker, stop the current instance with CTRL+C
and then:

```shell
conda activate stack
export TAVILY_SEARCH_API_KEY=<your key>
export INFERENCE_MODEL="meta-llama/Llama-3.2-3B-Instruct"
stack/scripts/run-worker.sh stack/templates/ollama/run-worker.yaml
```

Open a new terminal to run the SDK client code, and activate it.

```shell
conda activate stack
```

**Important** The client SDK code doesn't actually require TAVILY_SEARCH_API_KEY 
to be set in the client environment. However, the code is structured to rely on 
the presence of this environment variable to decide whether to use the Tavily 
search tool. Therefore, before running the code, you should set the key to any 
value, as the specific value is irrelevant.

```shell
export TAVILY_SEARCH_API_KEY=any-value
```

Finally, you can run the hello agent example:

```shell
python -m examples.agents.hello localhost 8321
```

#### Running inflation.py

The code requires an adjustment to work. Note that the adjustments on `tool_choice` 
is required even if running the llama-stack as monolith server as usual.

```shell
sed -i.bak -e 's/tool_choice="required"/tool_choice="auto"/' examples/agents/inflation.py
python -m examples.agents.inflation localhost 8321
```

Note: when running the worker agent on MacOS, you may see a number of warnings in the response
of the form:

```shell
[stderr]
Traceback (most recent call last):
  line 5, in <module>
    from bwrap.core import main
ModuleNotFoundError: No module named 'bwrap.core'
[/stderr]
```

This is expected and it is because `bwra, which is a command-line tool used for sandboxing applications 
in Linux, requires a Linux system with namespaces support, and does not work on MacOS`. We should be 
able to make this work e2e (with code execution in the sandboxed env) when running in Kube on a linux box.

#### Running podcast_transcript.py

The code requires couple of adjustments to work. Note that the adjustments on `tool_choice` and 
`toolgroups` to use are required even if running the llama-stack as monolith server as usual.

```shell
sed -e 's/tool_choice="required"/tool_choice="auto"/' -e 's/\["builtin::code_interpreter"\]/& + \["builtin::rag"\]/' examples/agents/podcast_transcript.py
python -m examples.agents.podcast_transcript localhost 8321
```

#### Running rag_as_attachments.py

```shell
python -m examples.agents.rag_as_attachments localhost 8321
```

#### Running rag_with_vector_db.py

```shell
python -m examples.agents.rag_with_vector_db localhost 8321
```

Note: this particular example uses the `faiss` vector DB. By default the faiss provider uses 
`sqllite` as kvstore. Both server and worker have been configured with faiss backed by
postgres. This allow the worker to access the `vector_db_id` created by the client
via `client.tool_runtime.rag_tool.insert`.

#### Running react_agent.py

```shell
python -m examples.agents.react_agent localhost 8321
```