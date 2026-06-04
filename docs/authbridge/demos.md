# AuthBridge Demos

Progressive walkthrough of AuthBridge on the weather agent. Deploy via the
[weather demo UI guide](https://github.com/kagenti/kagenti-extensions/blob/main/authbridge/demos/weather-agent/demo-ui.md),
then use the checks below to confirm each step.

## Prerequisites

```bash
scripts/kind/setup-kagenti.sh --with-istio --with-spire --with-ui --with-backend
```

- `weather-service` and `weather-tool` in `team1`
- [Deployment Guide](deployment-guide.md) for platform details

**Resource tip:** On a 4-CPU Podman/Kind node, use **Deploy from image**
(`ghcr.io/kagenti/agent-examples/weather_service:latest`) instead of
build-from-source to avoid Shipwright `Insufficient cpu` / `ExceededNodeResources`.

Advanced demo: [demo-ui-advanced.md](https://github.com/kagenti/kagenti-extensions/blob/main/authbridge/demos/weather-agent/demo-ui-advanced.md).

## Credentials and tokens

```bash
export KAGENTI_UI_PW=$(kubectl get secret kagenti-test-user -n keycloak \
  -o jsonpath='{.data.password}' | base64 -d)
```

If missing: `kubectl wait --for=condition=complete job/kagenti-agent-oauth-secret-job -n kagenti-system --timeout=300s` then re-read, or run `KEYCLOAK_URL=http://keycloak.localtest.me:8080 .github/scripts/common/87-setup-test-credentials.sh`.

| Client | Use |
|--------|-----|
| `kagenti` | UI only (PKCE) — password grant → `unauthorized_client` |
| `admin-cli` | Password grant OK but usually **no agent `aud`** → 401 |
| `kagenti-e2e-tests` | **CLI agent calls** — use `client_id` + `client_secret` from `kagenti-test-user` |

Run `87-setup-test-credentials.sh` **after** `weather-service` is registered in Keycloak (pass `KEYCLOAK_URL=http://keycloak.localtest.me:8080` on a Kind install — see below).

### Gotchas

- **`admin-cli` lives in the `master` realm, not `kagenti`.** When fetching an admin token for Keycloak Admin API calls, post to `/realms/master/protocol/openid-connect/token`, not `/realms/kagenti/...`. The Keycloak admin user is registered in `master`; the `kagenti` realm has its own user store and rejects `admin/admin` with a `null` `access_token`.
- **`"aud" not satisfied` from AuthBridge for `client_credentials` tokens.** On clusters running operator ≤ v0.2.0-rc.5, the agent's Keycloak client may have been registered before the realm-level audience scope existed, so the SPIFFE-ID audience claim is missing from the token. Tracked and fixed in [kagenti-operator#395](https://github.com/kagenti/kagenti-operator/pull/395) (issue [kagenti-operator#394](https://github.com/kagenti/kagenti-operator/issues/394)).

## Verify deployment

After the UI deploy steps in [demo-ui.md](https://github.com/kagenti/kagenti-extensions/blob/main/authbridge/demos/weather-agent/demo-ui.md):

```bash
# Pods: tool 1/1 (or 2/2); agent 2/2 (proxy-sidecar) or 4/4 (envoy-sidecar + init)
kubectl get pods -n team1 -l 'app.kubernetes.io/name in (weather-tool,weather-service)'

# AuthBridge sidecar present (name varies by mode)
kubectl get pod -n team1 -l app.kubernetes.io/name=weather-service \
  -o jsonpath='{.items[0].spec.containers[*].name}{"\n"}'

# Operator registered the agent SPIFFE client (logs in kagenti-system)
kubectl logs -n kagenti-system deployment/kagenti-controller-manager 2>/dev/null \
  | grep -i clientregistration | tail -5

# SPIFFE client ID visible to the sidecar
SIDECAR=$(kubectl get pod -n team1 -l app.kubernetes.io/name=weather-service \
  -o jsonpath='{.items[0].spec.containers[*].name}' | tr ' ' '\n' \
  | grep -E '^(authbridge-proxy|envoy-proxy)$' | head -1)
kubectl exec deploy/weather-service -n team1 -c "$SIDECAR" -- cat /shared/client-id.txt
# Expected: spiffe://localtest.me/ns/team1/sa/weather-service

# Service fronts AuthBridge on 8080
kubectl get svc -n team1 weather-service

# E2E token client + audience scopes (once agent is registered).
# On a Kind installer setup, point it at the platform Keycloak — the script
# defaults to http://localhost:8081 (a CI port-forward assumption) and will
# fail with "Failed to get Keycloak admin token" otherwise.
KEYCLOAK_URL=http://keycloak.localtest.me:8080 \
  .github/scripts/common/87-setup-test-credentials.sh

# In-cluster curl client
kubectl run test-client --image=nicolaka/netshoot -n team1 --restart=Never -- sleep 3600
kubectl wait --for=condition=ready pod/test-client -n team1 --timeout=60s
```

## Layer 1: See It Work

### Get a token

```bash
export KAGENTI_CLIENT_ID=$(kubectl get secret kagenti-test-user -n keycloak \
  -o jsonpath='{.data.client_id}' | base64 -d)
export KAGENTI_CLIENT_SECRET=$(kubectl get secret kagenti-test-user -n keycloak \
  -o jsonpath='{.data.client_secret}' | base64 -d)
export KAGENTI_TOKEN=$(curl -s -X POST \
  http://keycloak.localtest.me:8080/realms/kagenti/protocol/openid-connect/token \
  -d "grant_type=password" \
  -d "client_id=${KAGENTI_CLIENT_ID}" \
  -d "client_secret=${KAGENTI_CLIENT_SECRET}" \
  -d "username=admin" \
  -d "password=${KAGENTI_UI_PW}" | jq -r '.access_token')

# JWT uses base64url (not plain base64 -d)
python3 -c "import os,base64,json; p=os.environ['KAGENTI_TOKEN'].split('.')[1]; p+='='*(-len(p)%4); print(json.dumps(json.loads(base64.urlsafe_b64decode(p)),indent=2))"
# Expect sub=admin and aud containing spiffe://.../sa/weather-service
```

### Inbound checks (from test-client)

```bash
# Public agent card — no token (bypass paths)
kubectl exec -n team1 test-client -- curl -s \
  http://weather-service:8080/.well-known/agent.json | jq -r .name
# Expected: Weather Assistant

# Protected route — no token
kubectl exec -n team1 test-client -- curl -s http://weather-service:8080/
# Expected: unauthorized / missing Authorization

# Invalid token
BAD_TOKEN=not-a-valid-jwt
kubectl exec -n team1 test-client -- curl -s \
  -H "Authorization: Bearer ${BAD_TOKEN}" http://weather-service:8080/
# Expected: token validation failed
```

### End-to-end (valid token)

```bash
kubectl exec -n team1 test-client -- \
  curl -s --max-time 300 \
  -H "Authorization: Bearer ${KAGENTI_TOKEN}" \
  -H "Content-Type: application/json" \
  -X POST "http://weather-service:8080/" \
  -d '{"jsonrpc":"2.0","id":"test-1","method":"message/send",
       "params":{"message":{"role":"user","messageId":"msg-001",
       "parts":[{"type":"text","text":"What is the weather in New York?"}]}}}'
```

Beginner demo: outbound **passthrough** to the MCP tool. Full CLI variants:
[demo-ui Step 6](https://github.com/kagenti/kagenti-extensions/blob/main/authbridge/demos/weather-agent/demo-ui.md#step-6-test-via-cli).

## Layer 2: Watch the Token Flow

Requires [demo-ui-advanced](https://github.com/kagenti/kagenti-extensions/blob/main/authbridge/demos/weather-agent/demo-ui-advanced.md) or `authproxy-routes` with exchange policy.

```bash
kubectl set env deployment/weather-service-advanced -n team1 -c envoy-proxy LOG_LEVEL=debug
kubectl logs -f deploy/weather-service-advanced -n team1 -c envoy-proxy
# Repeat Layer 1 curl against http://weather-service-advanced:8080/
# Expect token-exchange / Resolver lines in logs
```

## Layer 3: Access Denied

Exchange routing only. Remove the weather-tool route from the agent AuthBridge
ConfigMap, `kubectl rollout restart deployment/weather-service -n team1`, retry the
Layer 1 curl — expect blocked-host / 403 from the proxy.

## Layer 4: Agent-to-Agent Delegation

[token-exchange routes](https://github.com/kagenti/kagenti-extensions/blob/main/authbridge/demos/token-exchange-routes/README.md) (single- and multi-target exchange) — watch `act` claims and per-hop exchange in sidecar logs.

## Layer 5: MCP Tool Access Control

Add `mcp-parser` to inbound plugins on the agent ConfigMap; `tools/call` shows in AuthBridge logs.

## Demo Index

| Demo | Difficulty | Features | Link |
|------|:----------:|----------|------|
| Weather (basic) | Beginner | Inbound JWT, passthrough | [demo-ui.md](https://github.com/kagenti/kagenti-extensions/blob/main/authbridge/demos/weather-agent/demo-ui.md) |
| Weather (advanced) | Intermediate | Token exchange, tool JWT | [demo-ui-advanced.md](https://github.com/kagenti/kagenti-extensions/blob/main/authbridge/demos/weather-agent/demo-ui-advanced.md) |
| GitHub Issue | Intermediate | External API, scopes | [README](https://github.com/kagenti/kagenti-extensions/blob/main/authbridge/demos/README.md#github-issue-agent-full-authbridge-flow) |
| Multi-Target | Advanced | Delegation | [token-exchange-routes](https://github.com/kagenti/kagenti-extensions/blob/main/authbridge/demos/token-exchange-routes/README.md) |

## Further Reading

- [RFC 8693](https://tools.ietf.org/html/rfc8693) · [OIDC Core](https://openid.net/specs/openid-connect-core-1_0.html) · [jwt.io](https://jwt.io/)
