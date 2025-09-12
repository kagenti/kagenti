# MCP Gateway instructions

MCP Gateway components are installed as part of the Kagenti installation process
unless the user has explicitly opted out of it. This document describes how

- MCP servers can register with the Gateway
- An agent to connect to tools via the Gateway 

We are going to use the **Weather Service Agent** and **Weather Service Tool** as examples.

## Check MCP Gateway

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

## Register Weather MCP Server

The Weather Service Tool can be installed using the Kagenti UI as usual. Once it is
installed, to register it with the Gateway, create a HTTPRoute:

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
  - "weather-tool.mcp.test.com" #note this is matching the gateway listener. It is purely for internal routing by envoy
  rules:
  - matches:
    - path:
        type: PathPrefix
        value: /
    backendRefs:
    - name: weather-tool
      port: 8000' | kubectl apply -f -
```

and then create a MCPServer Custom Resource:

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

## Connect the Weather Service Agent to the Gateway

To connect the Weather Service Agent, install it using the Kagenti UI as usual.
However, we need to define a new environment variable so the Agent can access
various tools managed by the Gateway. Namely, we need to set `MCP_URL` to
`http://mcp-gateway-istio.gateway-system.svc.cluster.local:8080/mcp`.

Once the Gateway implementation has stabilized, `MCP_URL` can be set to this
value by default, so we do not need to set this environment variable for every
agent. To check if the weather service is working, simply use the chatbot
exposed by the Weather Service Agent to query for weather information.

## Limitations

Most of the authentication and authorization capabilities are not currently implemented
in the Gateway.
