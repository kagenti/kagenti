# Tutorial for Llama Stack and MCP and Access Token propagation

This tutorial is will take us through obtaining an initial access token and sending it through Llama Stack to call a tool with this access token. This tool is a Golang server that will be secured via Keycloak. 

In this case, the Llama stack client will be granted access to the tool on behalf of a user registered in Keycloak. The tool is connected and registered to the Llama stack instance via MCP. 

This tutorial is broken down into the following steps:

- [Step 0: Prerequisites](#step-0-prerequisites)
- [Step 1: Setup the Tool components](#step-1-setup-the-tool-components)
  - [Step 1a: Run and setup Keycloak](#step-1a-run-and-setup-keycloak)
  - [Step 1b: Run the Golang Server](#step-1b-run-the-golang-server)
  - [Step 1c: Run the MCP Server](#step-1c-run-the-mcp-server)
- [Step 2: Setup the Llama Stack Components](#step-2-setup-the-llama-stack-components)
  - [Step 2a: Setup and Run the Llama Stack Server](#step-2a-setup-and-run-the-llama-stack-server)
  - [Step 2b: Register the toolgroup with the Llama Stack Server](#step-2b-register-the-toolgroup-with-the-llama-stack-server)
- [Step 3: Make a tool call](#step-3-make-an-unauthorized-tool-call)
  - [Step 3a: Make an unauthorized tool call](#step-3a-make-an-unauthorized-tool-call)
  - [Step 3b: Make an authorized tool call](#step-3b-make-an-authorized-tool-call)

## Step 0: Prerequisites

- Install the Prereqs in [pocs](../../../docs/pocs.md#prereqs)
  - Python 3.11+
  - [conda-forge](https://conda-forge.org/download/)
  - [ollama](https://ollama.com/download)
- [golang](https://go.dev/) version go1.23
- [Docker](https://www.docker.com/) or your favorite container runtime

To obtain the necessary files and resources:

```shell
git clone https://github.com/kagenti/kagenti.git
cd kagenti
```

## Step 1: Setup the Tool components

There are three components involved: Keycloak, the Golang Server, and the MCP Server. Keycloak is required because we will demonstrate a Golang server that responds successfully only to requests with JWTs provided by this Keycloak instance. The MCP Server is required so that we can connect the Llama Stack server with the Golang server via the usual MCP pattern. 

### Step 1a: Run and setup Keycloak

First, let's run Keycloak in Docker. Ensure Docker Desktop is running, or if you're using podman:

```shell
podman machine init
podman machine start
``` 
Then, using the following command we can run Keycloak: 

```shell
podman|docker run --name keycloak -p 8080:8080 \
        -e KC_BOOTSTRAP_ADMIN_USERNAME=admin -e KC_BOOTSTRAP_ADMIN_PASSWORD=admin \
        quay.io/keycloak/keycloak:latest \
        start-dev
```

This runs Keycloak at `http://localhost:8080` with username `admin` and password `admin`. 

#### Setup Keycloak [TODO: automate]

First let's create a demo: 

1. Access Keycloak at http://localhost:8080/ (Credentials: `admin`/`admin`)
2. Create a new realm `demo` [this is case-sensitive] by clicking `Manager realms` in the left sidebar and clicking `Create realm`
3. Ensure you are within this realm (The top of the left sidebar should say `demo [Current realm]`). Go to `Users` on the sidebar, and create a new user. 
4. Once that user is created, set a password by going to `Users > <username> > Credentials` where Credentials is in the top breadcrumbs. Set the password as not temporary. Keep note of the credentials you used. 

In the shell you are running, store the values of the user credentials:

```shell
export USER_NAME=<username>
export USER_PASSWORD=<password>
```

Now, we need to set up two clients. One will represent the `llama-stack` cilent, and one will represent the tool `my-external-tool`. 

Back in the Keycloak UI, let's set up the tool client first:

1. In the left sidebar, select `Clients`, then `Create client`
2. We'll name the Client ID `my-external-tool`.
3. Select `Client authentication` to false, and de-select all Authentication flows. [NOTE: This is an insecure setting, only for demo purposes]
4. Save
5. Now go to `Clients > my-external-tool > Client scopes > my-external-dedicated > Scope` and set `Full scope allowed` to `Off`. 

Let's set up the client scope related to this tool:

1. In the left-hand side bar, go to `Client scopes`. 
2. Click `Create client scope`. Name the client scope `-audience`. Set the type to `Optional` and Protocol to `OpenID Connect`. Click `Save`. 
3. Now that you have saved, you should see a `Mappers` tab near the top. Click on `Mappers > Configure a new mapper > Audience`. 
4. Enter `tool-audience` as the name, and add the client `my-external-tool`, to the `Included Client Audience`.  Click `Save`. 

1. In the left sidebar, select `Clients`, then `Create client`
2. We'll name the Client ID `llama-stack`.
3. Select `Client authentication` to false, and select Authentication flows `Standard flow` and `Direct access grants`. [NOTE: This is an insecure setting, only for demo purposes]
4. Save
5. Now go to `Clients > llama-stack > Client scopes > llama-stack-dedicated > Scope` and set `Full scope allowed` to `Off`. 
5. Finally, let's add the client scope to the llama-stack client profile in Keycloak. Go to `Clients > `llama-stack` > Client scopes > Add client scope`. Select `tool-audience`. Add as `Optional`. 

With the above, you can now simulate login and delegating termporary user permission using the following command: 

```shell
curl -sX POST -H "Content-Type: application/x-www-form-urlencoded" \
    -d "grant_type=password" \
    -d "username=$USER_NAME" \
    -d "password=$USER_PASSWORD" \
    -d "client_id=llama-stack" \
    -d "scope=tool-audience" \
    "http://localhost:8080/realms/demo/protocol/openid-connect/token" | jq
```

### Step 1b: Run the Golang Server

The implementation of the Golang server can be found [here](./golang_server/). Run it in a separate terminal with the following command:

```shell
./examples/identity/keycloak_llama_stack/golang_server/com.example.webserver -issuer "http://localhost:8080/realms/demo"
```

This runs the server on `http://localhost:10000` and validates received JWTs against the Keycloak we are running. 

### Step 1c: Run the MCP Server

Finally, we can run the MCP Server so that the Llama Stack server can make MCP calls to our running golang server. Open a new terminal:

```shell
conda activate stack
cd examples/mcp
uv run sse_server.py
```

This runs the MCP Server. 

## Step 2: Setup the Llama Stack components

Now that we have the tool components running, we can set up the Llama Stack server. 

### Step 2a: Setup and Run the Llama Stack Server

We will be running the Llama Stack server. This particular distribution requires ollama. To set these components up, run the [Setup steps in our pocs document](../../../docs/pocs.md). 

Once you do so, you should be ready to run the Llama Stack server with the following command: 

```shell
conda activate stack
export INFERENCE_MODEL="meta-llama/Llama-3.2-3B-Instruct"
llama stack run stack/templates/ollama/run.yaml 
```

When running the server on Mac, you might get a pop-up asking to `accept incoming network connections`, so just click **Allow**.  

### Step 2b: Register the toolgroup with the Llama Stack Server

Activate the environment.

```shell
conda activate stack
```

To register the tool group with the server, run:

```shell
python -m examples.clients.mcp.tool-util --host localhost --port 8321 --register_toolgroup
```

If you get an error `ModuleNotFoundError: No module named 'llama_stack_client.types.shared_params.url'`, Install an appropriate version of `llama_stack_client`:

```
pip install llama_stack_client==v0.1.6
```

## Step 3: Make a tool call

### Step 3a: Make an unauthorized tool call

We can make a tool call to request the golang server with the following command:

```shell
python -m examples.clients.mcp.tool-util --host localhost --port 8321 --mcp_fetch_url="http://localhost:10000"
```

This should return output with the following at the end:

```shell
ToolInvocationResult(content='{"type":"text","text":"Error executing tool fetch: Client error \'401 Unauthorized\' for url \'http://localhost:10000\'\\nFor more information check: https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/401","annotations":null}', error_code=1, error_message=None, metadata=None)
```

Note that we are getting a `401 Unauthorized` error because the golang server cannot validate against the running Keycloak instance. Indeed if we look at the golang server logs:

```shell
Validating token some-api-key against issuer http://localhost:8080/realms/demo
Token validation failed oidc: malformed jwt: go-jose/go-jose: compact JWS format must have three parts
```

Evidently, we are passing the string `some-api-key` as the bearer token. 

### Step 3b: Make an authorized tool call

Let's obtain a proper access token. We can use the curl command from above to store the access token in an environment variable:

```shell
export ACCESS_TOKEN=$(curl -sX POST -H "Content-Type: application/x-www-form-urlencoded" \
    -d "grant_type=password" \
    -d "username=$USER_NAME" \    
    -d "password=$USER_PASSWORD" \
    -d "client_id=llama-stack" \
    -d "scope=tool-audience" \                                                              
    "http://localhost:8080/realms/demo/protocol/openid-connect/token" | jq -r .access_token)
```

And now let's run the Llama stack client again, now passing the bearer token as an arg:

```shell
python -m examples.clients.mcp.tool-util --host localhost --port 8321 --mcp_fetch_url="http://localhost:10000" --access_token="$ACCESS_TOKEN"
```

We should get the result:

```shell
ToolInvocationResult(content='{"type":"text","text":"Hello, world!","annotations":null}', error_code=0, error_message=None, metadata=None)
```

And indeed in the Golang server logs:

```shell
Validating token eyJ... against issuer http://localhost:8080/realms/demo
Received access token with Subject 31c8ba97-b31e-40a8-8bec-1ef08dfff33a and Roles []
```
