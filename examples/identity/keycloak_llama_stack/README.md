# Tutorial for Llama Stack and MCP and Access Token propagation

This tutorial is will take us through obtaining an initial access token and sending it through Llama stack to call a tool with this access token. This tool is a Golang server that will be secured via Keycloak. 

This tutorial is broken down into the following steps:

- [Step 0: Prerequisites](#step-0-prerequisites)
- [Step 1: Setup the Tool components](#step-1-setup-the-tool-components)
  - [Step 1a: Run and setup Keycloak](#step-1a-run-and-setup-keycloak)
  - Step 1b: Run the Golang Server
  - Step 1c: Run the MCP Server
- Step 2: Setup the Llama Stack Components
  - Step 2a: Setup and Run the Llama Stack Server
  - Step 2b: Register the toolgroup with the Llama Stack Server
- Step 3: Make a tool call
  - Case 3a: Make a tool call with no access token
  - Case 3b: Make a tool call with the right access token

## Step 0: Prerequisites

- Install the Prereqs in [pocs](./docs/pocs.md#prereqs)
  - Python 3.11+
  - [conda-forge](https://conda-forge.org/download/)
  - [ollama](https://ollama.com/download)
- [golang](https://go.dev/) version go1.23
- [Docker](https://www.docker.com/) or your favorite container runtime

## Step 1: Setup the Tool components

There are three components involved: Keycloak, the Golang Server, and the MCP Server. Keycloak is required because we will demonstrate a Golang server that responds successfully only to requests with JWTs provided by this Keycloak instance. The MCP Server is required so that we can connect the Llama Stack server with the Golang server via the usual MCP pattern. 

### Step 1a: Run and setup Keycloak

First, let's run Keycloak in Docker using the following command: 

```
podman|docker run --name keycloak -p 8080:8080 \
        -e KC_BOOTSTRAP_ADMIN_USERNAME=admin -e KC_BOOTSTRAP_ADMIN_PASSWORD=admin \
        quay.io/keycloak/keycloak:latest \
        start-dev
```

This runs Keycloak at `http://localhost:8080` with admin username and password `admin`. 

Now, let's set up Keycloak. We will set up Keycloak. We will create a demo realm, along with two clients: one for the llama stack client, and one tool client. 

[TODO]

### Step 1b: Run the Golang Server

The implementation of the Golang server can be found [here](./golang-webserver). Run it with the following command:

```
./com.example.webserver -issuer "http://localhost:8080/realms/demo"
```

This runs the server on `http://localhost:10000` and validates received JWTs against the Keycloak we are running. 

### Step 1c: Run the MCP Server

Finally, we can run the MCP Server so that the Llama stack server can make MCP calls to our running golang server:

```
cd examples/mcp 
uv run sse_server.py
```

This runs the MCP Server. [TODO: need to add edited code, possibly to this directory]

## Step 2: Setup the llama stack components

Now that we have the tool components running, we can set up the Llama stack server. 

### Step 2a: Setup and Run the Llama stack Server

We will be running the llama stack server. This particular distribution requires ollama. To set these components up, run the [Setup steps in our pocs document](./docs/pocs.md#setup). 

Once you do so, you should be ready to run the Llama stack server with the following command: 

```
export INFERENCE_MODEL="meta-llama/Llama-3.2-3B-Instruct"
llama stack run stack/templates/ollama/run.yaml 
```

When running the server on Mac, you might get a pop-up asking to `accept incoming network connections`, so just click **Allow**.  

## Step 2b: Register the toolgroup with the Llama Stack Server

To register the tool group with the server, run:

```
python -m examples.clients.mcp.tool-util --host localhost --port 8321 --register_toolgroup
```

If you get an error `ModuleNotFoundError: No module named 'llama_stack_client.types.shared_params.url'`, Install an appropriate version of `llama_stack_client`:

```
pip install llama_stack_client==v0.1.6
```

## Step 3: Make a tool call

We are
