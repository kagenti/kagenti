---
draft: true       # excluded from https://www.rossoctl.dev/
---

# AuthBridge Demos

**What AuthBridge does:** AuthBridge is a sidecar proxy that runs alongside each agent.
It gives the agent a verifiable [SPIFFE](https://spiffe.io) identity and enforces *who is
allowed to call it* — all without the agent containing a single line of authentication
code. Every request coming *in* is checked against a JWT before it reaches the agent, and
every call going *out* to a tool can be re-issued with a fresh, narrowly-scoped token. The
agent stays focused on its job; the sidecar handles the zero-trust security around it.

**How it works.** Three components cooperate to make this happen:

1. **SPIRE** issues each workload a SPIFFE identity (an `spiffe://…` ID backed by a
   short-lived certificate). This is the agent's cryptographic "who am I."
2. **The Rossoctl operator** registers the agent as an OAuth client in Keycloak and wires
   up the audience scopes, so Keycloak can mint and validate tokens for that agent.
3. **The AuthBridge sidecar** enforces the rules at runtime. On the **inbound** side it
   rejects any request that lacks a valid JWT whose audience matches the agent's identity.
   On the **outbound** side it can exchange the caller's token for a new one scoped to a
   specific downstream tool ([RFC 8693](https://tools.ietf.org/html/rfc8693)), so each hop
   in a chain carries only the authority it actually needs.

This walkthrough demonstrates each of those behaviors, one layer at a time. You first
deploy the weather agent by following the
[weather demo UI guide](https://github.com/rossoctl/cortex/blob/main/authbridge/demos/weather-agent/demo-ui.md)
— that guide is where you learn the deployment steps themselves — and then run the checks
below to observe what AuthBridge is doing at each stage.

## Prerequisites

Install the platform with the components this demo needs:

```bash
scripts/kind/setup-rossoctl.sh --with-istio --with-spire --with-ui --with-backend
```

Before continuing, make sure the weather agent and its tool are deployed and running in
the `team1` namespace (`weather-service` and `weather-tool`). If you have not deployed them
yet, follow the
[weather demo UI guide](https://github.com/rossoctl/cortex/blob/main/authbridge/demos/weather-agent/demo-ui.md);
see the [Deployment Guide](deployment-guide.md) for broader platform details.

**Resource tip:** On a machine with only 4 CPUs, building the agent from source with
Shipwright often fails with `Insufficient cpu` / `ExceededNodeResources`. Choose **Deploy
from image** in the UI instead and point it at the prebuilt image
(`ghcr.io/rossoctl/examples/weather_service:latest`).

Once you finish the basic demo, the
[advanced demo](https://github.com/rossoctl/cortex/blob/main/authbridge/demos/weather-agent/demo-ui-advanced.md)
adds **token exchange** and per-tool JWTs. That is what powers Layer 2 and beyond, where
you watch the sidecar mint delegated tokens for downstream calls.

## Credentials and tokens

The demo authenticates to the agent as a test user. Read that user's password from the
`rossoctl-test-user` secret in the `keycloak` namespace:

```bash
export ROSSOCTL_UI_PW=$(kubectl get secret rossoctl-test-user -n keycloak \
  -o jsonpath='{.data.password}' | base64 -d)
```

If that secret does not exist yet, the platform is still finishing its first-run setup.
Wait for the setup job to complete, then read the password again:

```bash
kubectl wait --for=condition=complete job/rossoctl-agent-oauth-secret-job \
  -n rossoctl-system --timeout=300s
```

Three Keycloak clients show up in this demo, and it is easy to reach for the wrong one.
Use the table below to pick the right client for what you are doing:

| Client | When to use it |
|--------|----------------|
| `rossoctl` | The UI's own login client (PKCE). It has no client secret, so a password grant against it fails with `unauthorized_client`. |
| `admin-cli` | A password grant works, but the resulting token usually carries no agent `aud` claim, so AuthBridge rejects it with a 401. |
| `rossoctl-e2e-tests` | The client to use for CLI calls to the agent. Its `client_id` and `client_secret` are stored in the `rossoctl-test-user` secret. It is created by `87-setup-test-credentials.sh` **after** the agent is registered in Keycloak (see [Verify deployment](#verify-deployment)). |

### Gotchas

- **`admin-cli` lives in the `master` realm, not `rossoctl`.** When you fetch an admin token
  for Keycloak Admin API calls, post to `/realms/master/protocol/openid-connect/token`, not
  `/realms/rossoctl/...`. The Keycloak admin user is registered in the `master` realm; the
  `rossoctl` realm has its own separate user store and will reject `admin/admin` with a
  `null` `access_token`.
- **`"aud" not satisfied` from AuthBridge for `client_credentials` tokens.** On clusters
  running operator ≤ v0.2.0-rc.5, the agent's Keycloak client may have been registered
  before the realm-level audience scope existed, so the SPIFFE-ID audience claim is missing
  from the token. This is tracked and fixed in
  [rossoctl-operator#395](https://github.com/rossoctl/operator/pull/395)
  (issue [rossoctl-operator#394](https://github.com/rossoctl/operator/issues/394)).

## Verify deployment

After completing the UI deploy steps in
[demo-ui.md](https://github.com/rossoctl/cortex/blob/main/authbridge/demos/weather-agent/demo-ui.md),
confirm that everything came up correctly. Each command below checks one thing; the comment
above it describes what a healthy result looks like.

```bash
# The tool and agent pods are running.
# Tool is 1/1 (or 2/2); agent is 2/2 in proxy-sidecar mode, or 4/4 in envoy-sidecar mode.
kubectl get pods -n team1 -l 'app.kubernetes.io/name in (weather-tool,weather-service)'

# The AuthBridge sidecar was injected into the agent pod (the container name varies by mode).
kubectl get pod -n team1 -l app.kubernetes.io/name=weather-service \
  -o jsonpath='{.items[0].spec.containers[*].name}{"\n"}'

# The operator registered the agent as a Keycloak client (look in the operator's logs).
kubectl logs -n rossoctl-system deployment/rossoctl-controller-manager 2>/dev/null \
  | grep -i clientregistration | tail -5

# The sidecar can see the agent's SPIFFE identity.
SIDECAR=$(kubectl get pod -n team1 -l app.kubernetes.io/name=weather-service \
  -o jsonpath='{.items[0].spec.containers[*].name}' | tr ' ' '\n' \
  | grep -E '^(authbridge-proxy|envoy-proxy)$' | head -1)
kubectl exec deploy/weather-service -n team1 -c "$SIDECAR" -- cat /shared/client-id.txt
# Expected: spiffe://localtest.me/ns/team1/sa/weather-service

# The Service fronts AuthBridge on port 8080.
kubectl get svc -n team1 weather-service

# Create the E2E test client and attach its audience scopes. Run this once the agent is
# registered (the operator-log step above). On a Kind install, point the script at the
# platform Keycloak — it defaults to http://localhost:8081 (a CI port-forward assumption)
# and will otherwise fail with "Failed to get Keycloak admin token".
KEYCLOAK_URL=http://keycloak.localtest.me:8080 \
  .github/scripts/common/87-setup-test-credentials.sh

# Start a throwaway pod inside the cluster to run curl from. The demo calls the agent over
# its in-cluster Service name, so the requests must originate from inside the cluster.
kubectl run test-client --image=nicolaka/netshoot -n team1 --restart=Never -- sleep 3600
kubectl wait --for=condition=ready pod/test-client -n team1 --timeout=60s
```

## Layer 1: See it work

This first layer shows the core idea: the **sidecar**, not the agent, decides who gets in.
You send the same agent three different requests and watch AuthBridge treat each one
differently — allowing a public endpoint, rejecting an anonymous call, and rejecting a
forged token. The agent's own code never runs any of this logic.

### Get a token

First, obtain a valid access token for the test user. This uses the `rossoctl-e2e-tests`
client credentials you created earlier, together with the test user's password:

```bash
export ROSSOCTL_CLIENT_ID=$(kubectl get secret rossoctl-test-user -n keycloak \
  -o jsonpath='{.data.client_id}' | base64 -d)
export ROSSOCTL_CLIENT_SECRET=$(kubectl get secret rossoctl-test-user -n keycloak \
  -o jsonpath='{.data.client_secret}' | base64 -d)
export ROSSOCTL_TOKEN=$(curl -s -X POST \
  http://keycloak.localtest.me:8080/realms/rossoctl/protocol/openid-connect/token \
  -d "grant_type=password" \
  -d "client_id=${ROSSOCTL_CLIENT_ID}" \
  -d "client_secret=${ROSSOCTL_CLIENT_SECRET}" \
  -d "username=admin" \
  -d "password=${ROSSOCTL_UI_PW}" | jq -r '.access_token')

# Decode the token's payload to see who it is for. (JWTs use base64url, so a plain
# `base64 -d` will not decode them correctly.)
python3 -c "import os,base64,json; p=os.environ['ROSSOCTL_TOKEN'].split('.')[1]; p+='='*(-len(p)%4); print(json.dumps(json.loads(base64.urlsafe_b64decode(p)),indent=2))"
# You should see sub=admin and an aud claim containing spiffe://.../sa/weather-service.
# That audience is exactly what AuthBridge checks each incoming token against.
```

### Inbound checks (from the test-client)

Now send three requests from inside the cluster. Together they tell the whole inbound
story: AuthBridge lets the public agent card through, but blocks everything that is not
properly authenticated.

```bash
# 1. The public agent card requires no token — this path is deliberately allowed.
kubectl exec -n team1 test-client -- curl -s \
  http://weather-service:8080/.well-known/agent.json | jq -r .name
# Expected: Weather Assistant

# 2. A real endpoint with no token — the sidecar blocks it before the agent ever sees it.
kubectl exec -n team1 test-client -- curl -s http://weather-service:8080/
# Expected: an "unauthorized / missing Authorization header" error

# 3. A request carrying a bogus token — the sidecar validates the JWT and rejects it.
BAD_TOKEN=not-a-valid-jwt
kubectl exec -n team1 test-client -- curl -s \
  -H "Authorization: Bearer ${BAD_TOKEN}" http://weather-service:8080/
# Expected: a "token validation failed" error
```

### End-to-end with a valid token

Finally, send a real request with the valid token from earlier. This time the sidecar
accepts it and the agent answers the question:

```bash
kubectl exec -n team1 test-client -- \
  curl -s --max-time 300 \
  -H "Authorization: Bearer ${ROSSOCTL_TOKEN}" \
  -H "Content-Type: application/json" \
  -X POST "http://weather-service:8080/" \
  -d '{"jsonrpc":"2.0","id":"test-1","method":"message/send",
       "params":{"message":{"role":"user","messageId":"msg-001",
       "parts":[{"type":"text","text":"What is the weather in New York?"}]}}}'
```

In this basic demo, the agent's call out to the MCP weather tool is a simple
**passthrough** — no token exchange happens yet. For more CLI variations, see
[demo-ui Step 6](https://github.com/rossoctl/cortex/blob/main/authbridge/demos/weather-agent/demo-ui.md#step-6-test-via-cli).

## Layer 2: Watch the token flow

Layer 1 protected the agent's *front door*. Layer 2 is about what happens when the agent
calls *out* to a tool. Instead of forwarding the caller's original token, the sidecar
performs a **token exchange**: it asks Keycloak for a brand-new token scoped specifically
to the downstream tool. The agent's identity is delegated one hop at a time, and no single
token is powerful enough to be reused elsewhere.

This layer needs the advanced deployment (or an `authproxy-routes` config with an exchange
policy), so set that up first via
[demo-ui-advanced](https://github.com/rossoctl/cortex/blob/main/authbridge/demos/weather-agent/demo-ui-advanced.md).
Then turn up the sidecar's logging and repeat the Layer 1 request against the advanced
agent:

```bash
# Raise the sidecar's log level so the token exchange becomes visible.
kubectl set env deployment/weather-service-advanced -n team1 -c envoy-proxy LOG_LEVEL=debug

# Follow the sidecar logs, then in another shell re-run the Layer 1 request against
# weather-service-advanced:8080.
kubectl logs -f deploy/weather-service-advanced -n team1 -c envoy-proxy
```

In the logs you should see token-exchange and `Resolver` lines. That is the sidecar
trading the inbound token for a new, tool-scoped one before it calls the weather tool.

## Layer 3: Access denied

This layer shows that outbound access is governed by **policy**, not by the agent choosing
to behave. If you remove the tool's route from the agent's AuthBridge configuration, the
sidecar refuses to make the call — even though the agent still tries.

Edit the agent's AuthBridge ConfigMap to remove the `weather-tool` route, then restart the
agent so it picks up the change:

```bash
kubectl rollout restart deployment/weather-service -n team1
```

Now repeat the Layer 1 request. It fails with a blocked-host / 403 error from the proxy,
because the sidecar no longer has a route that authorizes the call to the tool.

## Layer 4: Agent-to-agent delegation

When one agent calls another, each hop should carry its own identity along with a record of
who it is acting for. AuthBridge does this with per-hop tokens that include an `act` (actor)
claim, so a downstream service can see both the original caller and the agent acting on
their behalf.

Follow the
[token-exchange routes guide](https://github.com/rossoctl/cortex/blob/main/authbridge/demos/token-exchange-routes/README.md),
which covers both single-target and multi-target exchange. As you drive the demo, watch the
sidecar logs for the `act` claims and the per-hop exchanges — that is the delegation chain
being built.

## Layer 5: MCP tool access control

The sidecar can also look *inside* the traffic to an MCP tool, not just at the token. When
you enable the `mcp-parser` plugin, AuthBridge inspects individual MCP `tools/call`
requests, which means tool-level access control can be enforced at the proxy instead of
inside the agent.

Add `mcp-parser` to the inbound plugins in the agent's AuthBridge ConfigMap. After that,
each `tools/call` the agent makes appears in the AuthBridge logs, where it can be allowed or
denied by policy.

## Demo index

| Demo | Difficulty | What it adds | Link |
|------|:----------:|--------------|------|
| Weather (basic) | Beginner | Inbound JWT validation, outbound passthrough | [demo-ui.md](https://github.com/rossoctl/cortex/blob/main/authbridge/demos/weather-agent/demo-ui.md) |
| Weather (advanced) | Intermediate | Token exchange, per-tool JWTs | [demo-ui-advanced.md](https://github.com/rossoctl/cortex/blob/main/authbridge/demos/weather-agent/demo-ui-advanced.md) |
| GitHub Issue | Intermediate | Calling an external API with scoped tokens | [README](https://github.com/rossoctl/cortex/blob/main/authbridge/demos/README.md#github-issue-agent-full-authbridge-flow) |
| Multi-Target | Advanced | Delegation across multiple tools | [token-exchange-routes](https://github.com/rossoctl/cortex/blob/main/authbridge/demos/token-exchange-routes/README.md) |

## Further reading

- [RFC 8693 — OAuth 2.0 Token Exchange](https://tools.ietf.org/html/rfc8693)
- [OpenID Connect Core](https://openid.net/specs/openid-connect-core-1_0.html)
- [jwt.io](https://jwt.io/) — decode and inspect JWTs
