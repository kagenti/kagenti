# AuthBridge Demos

A progressive learning path that starts with seeing AuthBridge work transparently,
then peels back layers to show what's happening underneath.

## Prerequisites

- A running Kagenti cluster (Kind or OpenShift)
- `kubectl` access to the cluster
- Python 3.11+ with `uv` for token generation scripts

Quick cluster setup:
```bash
scripts/kind/setup-kagenti.sh --with-istio --with-spire --with-ui --with-backend
```

Then deploy the weather agent example (see [Deployment Guide](deployment-guide.md) for details).

## Layer 1: See It Work

**Goal:** Observe that agents get authenticated access to tools without any auth code.

Deploy the weather agent and make a request:

```bash
# Get a user token from Keycloak
export KAGENTI_TOKEN=$(curl -s -X POST \
  http://keycloak.localtest.me:8080/realms/kagenti/protocol/openid-connect/token \
  -d "grant_type=password&client_id=kagenti&username=admin&password=${KAGENTI_UI_PW}" \
  | jq -r '.access_token')

# (Optional) Inspect the token to see audience, subject, and other OIDC claims
echo $KAGENTI_TOKEN | cut -d'.' -f2 | base64 -d | jq .

# Call the weather agent from an in-cluster test pod — AuthBridge handles everything
kubectl exec -n team1 deploy/test-client -- \
  curl -s -H "Authorization: Bearer $KAGENTI_TOKEN" \
  http://weather-service.team1.svc:8000/run \
  -d '{"query": "What is the weather in New York?"}'
```

The agent responds with weather data. It made an outbound call to the weather MCP tool,
but the agent code contains zero auth logic — AuthBridge exchanged the inbound JWT
for a different outbound JWT transparently when invoking the weather MCP tool.

Verify enforcement — try with an invalid token:

```bash
# Use a bogus token value to prove enforcement
BAD_TOKEN="not-a-valid-jwt"
kubectl exec -n team1 deploy/test-client -- \
  curl -s -H "Authorization: Bearer ${BAD_TOKEN}" \
  http://weather-service.team1.svc:8000/run \
  -d '{"query": "What is the weather in New York?"}'
# Returns: 401 Unauthorized
```

**What you've seen:**
- Inbound: your JWT was validated before reaching the agent (invalid tokens get 401)
- Outbound: the agent's call to the weather MCP tool received credentials automatically
- The agent code is a plain HTTP client — no SDKs, no secrets

**Full demo instructions:**
[Weather Agent Demo](https://github.com/kagenti/kagenti-extensions/blob/main/authbridge/demos/README.md#weather-agent-demo)

## Layer 2: Watch the Token Flow

**Goal:** See the actual token exchange happening in real-time.

Enable debug logging on the AuthBridge sidecar:

```bash
kubectl set env deployment/weather-service -n team1 -c envoy-proxy LOG_LEVEL=debug
```

Make the same request again and watch the logs:

```bash
# In one terminal, stream AuthBridge logs
kubectl logs -f deploy/weather-service -n team1 -c envoy-proxy

# In another terminal, send the request
kubectl exec -n team1 deploy/test-client -- \
  curl -s -H "Authorization: Bearer $KAGENTI_TOKEN" \
  http://weather-service.team1.svc:8000/run \
  -d '{"query": "What is the weather in New York?"}'
```

You'll see:
```
INFO  jwt-validation: token valid, subject=admin, issuer=http://keycloak-service.keycloak.svc:8080/realms/kagenti
INFO  token-exchange: success, audience=weather-tool, expires_in=60s
DEBUG token-exchange: subject_token=spiffe://kagenti.io/ns/team1/sa/weather-service
DEBUG forward-proxy: injecting Authorization header for weather-tool.team1.svc
```

**What you've learned:**
- The inbound JWT identifies the caller (admin, or whichever user obtained the token)
- The agent's SPIFFE identity is used as the subject token for exchange
- The resulting token is audience-scoped (weather-tool only) and short-lived (60s)
- The proxy injects the Authorization header — the agent never sees it

## Layer 3: Access Denied

**Goal:** See what happens when an agent tries to reach an unauthorized service.

Modify the weather agent's route configuration to remove access to the weather tool:

```bash
# Edit the AuthBridge ConfigMap to remove the weather-tool route
kubectl edit configmap authbridge-config-weather-service -n team1
# Remove the route rule for weather-tool.team1.svc
```

Restart the agent pod and try the same request:

```bash
kubectl rollout restart deployment/weather-service -n team1

kubectl exec -n team1 deploy/test-client -- \
  curl -s -H "Authorization: Bearer $KAGENTI_TOKEN" \
  http://weather-service.team1.svc:8000/run \
  -d '{"query": "What is the weather in New York?"}'
```

The agent receives a 403 from AuthBridge when it tries to call the weather tool:
```
WARN  proxy: blocked host, destination=weather-tool.team1.svc, reason=no matching route
```

The agent returns an error to the user — it cannot access the tool.

**What you've learned:**
- Access control is enforced at the proxy, not in the agent code
- The agent cannot bypass the restriction (NetworkPolicy + proxy enforcement)
- Clear error messages explain what was blocked and why
- Restore the route to re-enable access

## Layer 4: Agent-to-Agent Delegation

**Goal:** See how identity flows through a multi-agent chain.

This demo requires two agents: an orchestrator and a worker. The orchestrator
receives a user request, then delegates to the worker agent via A2A protocol.

```bash
# Deploy the multi-target demo (orchestrator + worker agents)
# See full instructions at the link below
```

Drive traffic to the orchestrator agent (e.g., via the Kagenti UI at
`http://kagenti-ui.localtest.me:8080` or via curl) and watch the delegation chain
in logs:

```
# Orchestrator receives user request
INFO  jwt-validation: token valid, subject=admin
INFO  token-exchange: success, audience=worker-agent, subject=orchestrator-agent

# Worker receives delegated request
INFO  jwt-validation: token valid, subject=orchestrator-agent, act.sub=admin
INFO  token-exchange: success, audience=github-api, subject=worker-agent
```

**What you've learned:**
- The user's identity is preserved through the chain via the `act` (actor) claim —
  `act.sub=admin` means the orchestrator is acting on behalf of the original user
  (per [RFC 8693 Section 4.1](https://tools.ietf.org/html/rfc8693#section-4.1))
- Each hop exchanges tokens with the appropriate audience
- The worker knows it's acting on behalf of the original user via the orchestrator
- Access decisions at each hop reflect the original user's permissions

**Full demo instructions:**
[Multi-Target Demo](https://github.com/kagenti/kagenti-extensions/blob/main/authbridge/demos/README.md#multi-target-demo)

## Layer 5: MCP Tool Access Control

**Goal:** See protocol-aware access control for MCP tool calls.

With the MCP parser plugin enabled, AuthBridge inspects JSON-RPC requests to
understand which tool is being called:

```bash
# Enable the MCP parser in the pipeline config
kubectl edit configmap authbridge-config-weather-service -n team1
# Add to inbound plugins: mcp-parser
```

Send an MCP tools/call request through the agent:

```
INFO  mcp-parser: request, method=tools/call
DEBUG mcp-parser: payload, method=tools/call, tool=get_weather, args={"city":"NYC"}
```

Future: with guardrail plugins, the platform can evaluate whether a tool call
aligns with the user's original intent before allowing it.

## Demo Index

| Demo | Difficulty | Features Shown | Link |
|---|---|---|---|
| Weather Agent (basic) | Beginner | Token exchange, transparent auth | [Demo](https://github.com/kagenti/kagenti-extensions/blob/main/authbridge/demos/README.md#weather-agent-demo) |
| Weather Agent (advanced) | Intermediate | Scope-based access, Alice vs Bob | [Demo](https://github.com/kagenti/kagenti-extensions/blob/main/authbridge/demos/README.md#weather-agent-advanced) |
| GitHub Issue Agent | Intermediate | External API integration, token scoping | [Demo](https://github.com/kagenti/kagenti-extensions/blob/main/authbridge/demos/README.md#github-issue-demo) |
| Single-Target | Intermediate | Route configuration, audience mapping | [Demo](https://github.com/kagenti/kagenti-extensions/blob/main/authbridge/demos/README.md#single-target-demo) |
| Multi-Target | Advanced | Delegation chains, multi-service access | [Demo](https://github.com/kagenti/kagenti-extensions/blob/main/authbridge/demos/README.md#multi-target-demo) |
| Webhook | Advanced | Event-driven auth, callback verification | [Demo](https://github.com/kagenti/kagenti-extensions/blob/main/authbridge/demos/README.md#webhook-demo) |

## Further Reading

- [Hands-on with MCP Gateway](https://medium.com/kagenti-the-agentic-platform/hands-on-with-mcp-gateway-from-local-setup-to-agent-integration-in-kagenti-f9bd3b7cc334)
- [Introducing MCP Gateway in Kagenti](https://medium.com/kagenti-the-agentic-platform/introducing-mcp-gateway-in-kagenti-a-unified-front-door-for-your-mcp-servers-28db5b6ef62d)
- [OAuth 2.0 Token Exchange (RFC 8693)](https://tools.ietf.org/html/rfc8693) — the standard AuthBridge uses for credential delegation
- [OpenID Connect Core](https://openid.net/specs/openid-connect-core-1_0.html) — if you're new to JWTs and OIDC
- [jwt.io](https://jwt.io/) — online tool to decode and inspect JWT tokens
