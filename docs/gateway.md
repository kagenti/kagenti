# MCP Gateway instructions

[MCP Gateway](https://github.com/kagenti/mcp-gateway) components are installed as part of the Kagenti installation process
unless the user has explicitly opted out of it, such as via `--skip-install mcp_gateway`. This document describes how

- An MCP server can be registered with the Gateway
- An agent connects to tools via the Gateway

## Weather Agent / Tools (no auth)

First, we are going to use the **Weather Agent** and **Weather Tool** as an
example where there is no auth. Then we will use **Slack Agent** and **Slack
Tools** to show MCP servers with auth enabled.

### Check MCP Gateway

Make sure the Envoy proxy is running in the `gateway-system` namespace:

```
$ kubectl -n gateway-system get pods
NAME                                 READY   STATUS    RESTARTS   AGE
mcp-gateway-istio-79d5d57dfc-njnbm   1/1     Running   0          30h
```

Also make sure the Gateway controller manager, broker, and router pods are running in
the `mcp-system` namespace:

```
$ kubectl -n mcp-system get pods
NAME                                 READY   STATUS    RESTARTS   AGE
mcp-broker-router-6bbbb5b577-9f67g   1/1     Running   0          29h
mcp-controller-666f8cf9bf-dcpbc      1/1     Running   0          30h
```

### Register Weather MCP Server

The Weather Service Tool can be installed using the Kagenti UI [as usual](./demos/demo-weather-agent.md#import-new-tool). Once it is
installed, to register it with the Gateway, create an [`HTTPRoute`](https://gateway-api.sigs.k8s.io/api-types/httproute/):

```
echo 'apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: weather-tool-route
  namespace: default
  labels:
    mcp-server: "true"
spec:
  parentRefs:
  - name: mcp-gateway
    namespace: gateway-system
  hostnames:
  - "weather-tool.mcp.local" #note this is matching the gateway listener. It is purely for internal routing by envoy
  rules:
  - matches:
    - path:
        type: PathPrefix
        value: /
    backendRefs:
    - name: weather-tool-mcp
      port: 8000' | kubectl apply -f -
```

and then create an `MCPServer` Custom Resource:

```
echo 'apiVersion: mcp.kagenti.com/v1alpha1
kind: MCPServer
metadata:
  name: weather-tool-servers
  namespace: default
spec:
  toolPrefix: weather_

  # Reference all three test MCP servers via their HTTPRoutes
  targetRef:
    group: gateway.networking.k8s.io
    kind: HTTPRoute
    name: weather-tool-route
    namespace: default' | kubectl apply -f -
```

This assumes the Weather Service Tool is installed in the `default` namespace. If it is installed
in a different namespace, adjust accordingly.

### Connect the Weather Service Agent to the Gateway

To connect the Weather Service Agent, install it using the Kagenti UI as usual.
However, we need to define a new environment variable so the Agent can access
various tools managed by the Gateway. Namely, we need to set `MCP_URL` to
`http://mcp-gateway-istio.gateway-system.svc.cluster.local:8080/mcp`.

The `weather-service` deployment can be edited manually or patched via a command like `kubectl set env deployment/weather-service -n default MCP_URL="http://mcp-gateway-istio.gateway-system.svc.cluster.local:8080/mcp"`, with the namespace adjusted as appropriate.

Once the Gateway implementation has stabilized, `MCP_URL` can be set to this
value by default, so we do not need to set this environment variable for every
agent. To check if the weather service is working, simply use the chatbot
exposed by the Weather Service Agent to query for weather information. Instructions for chatting with the agent can be referred to [here](./demos/demo-weather-agent.md#chat-with-the-weather-agent).

### Limitations

Most of the authentication and authorization capabilities are not currently implemented
in the Gateway.

## Slack Agent / Tools (with auth)

It is recommended to read all the instructions here before proceeding as some
steps are weaved into the normal Slack agent instructions.

### Slack Agent

The Slack agent can be installed as usual with a few exceptions:
- Do not import the `mcp-slack` environment variable
- Create a new env var called `MCP_URL` and set it to `http://mcp-gateway-istio.gateway-system.svc.cluster.local:8080/mcp`.

### Slack Tool

The Slack tool can be installed as usual.

### Keycloak Setup

Make sure to run `set_up_demo.py` only after the Slack Agent and Tool are installed.

Now, we need to obtain an access token the MCP Broker can use to initialize with the Slack MCP server to list available tools.

In the Kagenti UI, login to Keycloak admin console as `admin/admin`, and then perform the following steps:
- Go to Clients
- Go to `kagenti` client which should open settings
- Under Settings > Capability Config and enable Direct access grants
- Hit Save
- Now Under Credentials tab, obtain the Client Secret and save it to the local variable `CLIENT_SECRET`

To prevent tokens from expiring too quickly, we need to lengthy various expiration time:
- Go to Realm settings > Tokens > Access tokens: Set Access token lifespan to 365 days and hit Save
- Go to Realm settings > Sessions > SSO Session Settings: Set SSO Session Max to 365 days and hit Save

In one terminal, run:
```
kubectl -n keycloak port-forward service/keycloak 8080:8080
```

In another terminal that has `CLIENT_SECRET` set, run:
```
export ACCESS_TOKEN=`curl -sX POST -H "Content-Type: application/x-www-form-urlencoded"     -d "client_secret=$CLIENT_SECRET"     -d "grant_type=password"     -d "client_id=kagenti" -d "username=$USERNAME" -d "password=$PASSWORD"        "http://localhost:8080/realms/master/protocol/openid-connect/token" | jq -r .access_token`
echo $ACCESS_TOKEN
```

Now, store the access token as a secret to be used by Broker to access the Slack MCP server:
```
kubectl create secret generic slack-server-access-token --from-literal=token="Bearer $ACCESS_TOKEN" --namespace=default
kubectl label secret slack-server-access-token mcp.kagenti.com/credential=true
```

Next, we create the HttpRoute resource for the Slack MCP server:
```
kubectl apply -f - <<EOF
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: slack-tool-route
  namespace: default
  labels:
    mcp-server: "true"
spec:
  parentRefs:
  - name: mcp-gateway
    namespace: gateway-system
  hostnames:
  - 'slack-tool.mcp.local' #note this is matching the gateway listener. It is purely for internal routing by envoy'
  rules:
  - matches:
    - path:
        type: PathPrefix
        value: /
    backendRefs:
    - name: slack-tool
      port: 8000
EOF
```

Finally, we create the MCPServer resource with the access token:
```
kubectl apply -f - <<EOF
apiVersion: mcp.kagenti.com/v1alpha1
kind: MCPServer
metadata:
  name: slack-tool-servers
  namespace: default
spec:
  toolPrefix: slack_
  credentialRef:
    key: token
    name: slack-server-access-token
  targetRef:
    group: gateway.networking.k8s.io
    kind: HTTPRoute
    name: slack-tool-route
    namespace: default
EOF
```

It could take a while (up to 60s) for the newly created token to be discovered by the MCP Broker. To check if it is ready, run:
```
$ kubectl get mcpservers slack-tool-servers -o yaml
```

and make sure the status field shows `Ready`, e.g.,
```
status:
  conditions:
  - lastTransitionTime: "2025-10-01T19:28:33Z"
    message: MCPServer successfully reconciled and validated 1 servers with 2 tools
    reason: Ready
    status: "True"
    type: Ready
```

### Validation

To check if the Slack Agent is able to connect to the Slack tools via the MCP
Gateway, one way is to open the Kagenti UI and open the chatbot that is
connected to the Slack Agent. A query such as "List all the Slack channels" should
give the expected results.

Another way to validate is to do a port-forward on the MCP Gateway to your local ports,
and then use the MCP Inspector to connect to the Gateway.

