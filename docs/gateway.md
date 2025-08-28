# MCP Gateway instructions

**Note that this is a temporary MCP Gateway to test gateway functionalities.
It will be replaced by the Gateway
[here](http://github.com/kagenti/mcp-gateway) very soon.  We expect the
following instructions will largely remain the same when the new Gateway is
swapped in.**

MCP Gateway components are installed as part of the Kagenti installation process
unless the user has explicitly opted out of it. This document describes how the
Gateway can be used by agents using the **Weather Service Agent** and **Weather
Service Tool**. 

## Check MCP Gateway

The Gateway control-plane and data-plane are installed in the `envoy-gateway-system` namespace:

```
$ kubectl get pods -n envoy-gateway-system
NAME                                             READY   STATUS    RESTARTS   AGE
envoy-gateway-7c88d4fff4-n6q8w                   1/1     Running   0          3d2h
envoy-mcp-gateway-eg-2141f0d0-6cf9cf987f-cvbwc   2/2     Running   0          3d2h
```

A Gateway helper pod should also be running in the `mcp-gateway` namespace:

```
$ kubectl -n mcp-gateway get pods
NAME                                 READY   STATUS    RESTARTS   AGE
mcp-gateway-server-95c46cc57-7cfzm   1/1     Running   0          3d2h
```

## Weather Service Tool

The Weather Service Tool can be installed using the Kagenti UI as usual. Once it is
installed, to register it with the Gateway, run the following command:

```
echo "apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: weather-route
spec:
  parentRefs:
  - name: eg
    namespace: mcp-gateway
  rules:
  - backendRefs:
    - group: ""
      kind: Service
      name: weather-tool
      port: 8000
      weight: 1
    matches:
    - path:
        type: PathPrefix
        value: /mcp/
      headers:
      - name: x-backend
        value: default/weather-mcp-service:8000
        type: Exact" | kubectl apply -f -
```

This assumes the Weather Service Tool is installed in the `default` namespace. If it is installed
in a different namespace, adjust the HTTPRoute resource above accordingly.

## Weather Service Agent

The Weather Service Agent can also be installed using the Kagenti UI as usual.
However, we need to define a new environment variable so the Agent can access
various tools managed by the Gateway. Namely, we need to set `MCP_URL` to
`http://envoy-mcp-gateway-eg-2141f0d0.envoy-gateway-system.svc.cluster.local:80/mcp`.

Once the Gateway implementation has stabilized, `MCP_URL` can be set to this
value by default, so we do not even need to set this environment variable when
deploying agents. To check if the weather service is working, simply use the
chatbot exposed by the Weather Service Agent to query for weather information.

## Limitations

The current Gateway does not support tool responses larger than 4KB. This limitation
will be removed once we swap in the ext-proc based Gateway.
