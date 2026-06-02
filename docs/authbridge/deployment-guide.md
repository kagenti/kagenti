# AuthBridge Deployment Guide

## Deployment Modes

AuthBridge supports deployment modes `envoy-sidecar`, `waypoint`, and `proxy-sidecar`.
The proxy-sidecar mode is the recommended default for most environments.

| | Proxy-Sidecar (default) | Envoy-Sidecar (advanced) |
|---|---|---|
| **Containers per pod** | 1 sidecar | 2+ (Envoy + processor + init) |
| **Memory overhead** | ~15-30 MB | ~150-200 MB |
| **Privileged mode** | No | Yes (iptables init) |
| **Interception** | HTTP_PROXY env vars | iptables NAT rules |
| **Debugging** | Standard HTTP proxy logs | iptables chains + Envoy stats + ext_proc |
| **Image** | `authbridge-light` (29 MB, distroless) | `authbridge-envoy` (140 MB, UBI9-micro) |
| **Use when** | Standard deployments | Need transparent interception of non-HTTP protocols |

## Verifying and Tuning Sidecar Injection

The number of containers in a Kagenti agent pod depends on the resolved
AuthBridge mode (above) **and** on per-workload labels that opt individual
sidecars in or out. If you see a different `READY` count than you expect
(e.g. `3/3` instead of `2/2`), the labels on the pod template — not a
cluster-wide setting — are usually responsible.

### Verify the current mode and container layout

```bash
# List containers in the pod
kubectl get pod -n <namespace> -l app.kubernetes.io/name=<workload> \
  -o jsonpath='{.items[0].spec.containers[*].name}'

# Inspect injection-relevant labels
kubectl get pod -n <namespace> -l app.kubernetes.io/name=<workload> \
  -o jsonpath='{.items[0].metadata.labels}' | jq
```

### Containers per mode + label combination

`spiffe-helper` and `envoy-proxy` are **injected by default** when their
respective feature gates are on (which is the default Helm config).
`kagenti-client-registration` is **not** an in-pod sidecar in operator
0.2+ — the operator's reconciler handles registration outside the pod
and mounts the resulting Secret. The legacy sidecar can still be
requested via `kagenti.io/client-registration-inject=true` for
compatibility.

| Workload labels | Resolved mode | Containers (READY count) | Init containers |
|---|---|---|---|
| `kagenti.io/type=agent` (Helm defaults) | `envoy-sidecar` | `agent`, `envoy-proxy`, `spiffe-helper` (`3/3`) | `proxy-init` |
| `kagenti.io/type=agent` (Helm defaults) | `proxy-sidecar` | `agent`, `authbridge-proxy`, `spiffe-helper` (`3/3`) | — |
| `kagenti.io/type=agent` + `kagenti.io/spiffe-helper-inject=false` | `envoy-sidecar` | `agent`, `envoy-proxy` (`2/2`) | `proxy-init` |
| `kagenti.io/type=agent` + `kagenti.io/spiffe-helper-inject=false` | `proxy-sidecar` | `agent`, `authbridge-proxy` (`2/2`) | — |
| `kagenti.io/type=agent` + `kagenti.io/spire=disabled` | any | (same as `spiffe-helper-inject=false` row above) | as above |
| `kagenti.io/type=agent` + `kagenti.io/inject=disabled` | n/a — opted out | `agent` only (`1/1`) | — |

### Workload-level controls

These labels go on the **pod template** (e.g.
`spec.template.metadata.labels` on a Deployment), not on the workload
itself. All controls are **opt-out**: the absence of a label leaves the
sidecar enabled. Only the listed disable values block injection — any
other value is treated as "no opinion."

| Label | Default | Effect |
|---|---|---|
| `kagenti.io/type` | (required) | Must be `agent` or `tool` — without it the webhook skips the workload entirely. |
| `kagenti.io/inject` | (allow) | Set to `disabled` to opt the whole workload out of all sidecars. |
| `kagenti.io/spire` | (allow) | Set to `disabled` to skip `spiffe-helper` (no SPIFFE identity / JWT-SVID for this workload). |
| `kagenti.io/envoy-proxy-inject` | (allow) | Set to `false` to skip `envoy-proxy` (and the `proxy-init` init container) in envoy-sidecar mode. |
| `kagenti.io/spiffe-helper-inject` | (allow) | Set to `false` to skip the `spiffe-helper` sidecar. |
| `kagenti.io/client-registration-inject` | (skip) | Set to `true` to opt back into the legacy in-pod client-registration sidecar. |

The full label vocabulary (and precedence) lives in the webhook source —
see [`kagenti-operator/internal/webhook/injector/`](https://github.com/kagenti/kagenti-operator/tree/main/kagenti-operator/internal/webhook/injector)
(`pod_mutator.go` for label constants, `precedence.go` for the per-sidecar
decision chain).

### Cluster-admin controls (feature gates)

Cluster operators can disable injection globally or per-sidecar via the
`kagenti-feature-gates` ConfigMap in `kagenti-system`:

```yaml
# kubectl get cm kagenti-feature-gates -n kagenti-system -o yaml
data:
  feature-gates.yaml: |
    globalEnabled: true       # kill switch — false disables ALL injection
    injectTools: false        # tool workloads are not injected by default
    envoyProxy: true          # per-sidecar enable
    spiffeHelper: true
    clientRegistration: true  # legacy in-pod client-registration sidecar
    combinedSidecar: false
```

Workload-level labels are evaluated against these gates: a sidecar is
injected only when both the cluster gate and the workload label allow it.

## Proxy-Sidecar Mode (Default)

### How It Works

The Kagenti operator webhook automatically injects the AuthBridge sidecar when it
detects the `kagenti.io/type: agent` label on a pod:

1. The reverse proxy takes over the agent's original port (e.g., `:8000`)
2. The agent is moved to a free port (e.g., `:8001`) via `PORT` env var
3. `HTTP_PROXY` and `HTTPS_PROXY` env vars are injected into the agent container
4. The Kubernetes Service targetPort remains unchanged — traffic flows through the proxy

```yaml
# To use proxy-sidecar mode, annotate your workload:
metadata:
  labels:
    kagenti.io/type: agent
  annotations:
    kagenti.io/authbridge-mode: "proxy-sidecar"
```

### Traffic Flow

```
Inbound:   Client → Service:8000 → Reverse Proxy → Agent:8001
Outbound:  Agent → HTTP_PROXY → Forward Proxy → Token Exchange → External Service
```

## Envoy-Sidecar Mode (Advanced)

For environments that require transparent interception of all TCP traffic
(not just HTTP), the Envoy-sidecar mode uses iptables to redirect traffic:

```yaml
# Envoy-sidecar is the default if no annotation is set, but will change to
# proxy-sidecar in a future release
metadata:
  labels:
    kagenti.io/type: agent
  # No annotation = envoy-sidecar (current default)
```

This mode requires privileged mode for the iptables init container and adds
a sidecar running [Envoy](https://www.envoyproxy.io/docs/envoy/latest/) as a
dependency. Use it only when you need protocol-level transparent interception.

## Configuration

AuthBridge is configured via YAML with `${ENV_VAR}` expansion. The operator
mounts the configuration from a ConfigMap such as `authbridge-config-weather-service`.

### Minimal Proxy-Sidecar Config

```yaml
mode: proxy-sidecar
listener:
  reverse_proxy_backend: "http://localhost:8081"
inbound:
  issuer: "${ISSUER}"
outbound:
  keycloak_url: "${KEYCLOAK_URL}"
  keycloak_realm: "${KEYCLOAK_REALM}"
identity:
  type: spiffe
  client_id: "${CLIENT_ID}"
  jwt_svid_path: "/opt/jwt_svid.token"
routes:
  rules:
    - host: "weather-api.example.com"
      target_audience: "weather-api"
```

### Minimal Envoy-Sidecar Config

```yaml
mode: envoy-sidecar
inbound:
  issuer: "${ISSUER}"
outbound:
  keycloak_url: "${KEYCLOAK_URL}"
  keycloak_realm: "${KEYCLOAK_REALM}"
  default_policy: "passthrough"
identity:
  type: spiffe
  client_id: "${CLIENT_ID}"
  jwt_svid_path: "/opt/jwt_svid.token"
routes:
  file: "/etc/authproxy/routes.yaml"
```

### Configuration Reference

| Field | Description | Default |
|---|---|---|
| `mode` | Deployment mode: `proxy-sidecar`, `envoy-sidecar`, `waypoint` | `envoy-sidecar` |
| `inbound.issuer` | Expected JWT issuer for inbound validation | Derived from keycloak_url |
| `inbound.jwks_url` | JWKS endpoint for signature verification | Derived from token_url |
| `outbound.token_url` | Keycloak token endpoint | Derived from keycloak_url + realm |
| `outbound.keycloak_url` | Keycloak base URL | Required |
| `outbound.keycloak_realm` | Keycloak realm name | Required |
| `outbound.default_policy` | `passthrough` or `exchange` | `passthrough` |
| `identity.type` | `spiffe` or `client-secret` | Required |
| `identity.client_id` | OAuth client ID (or file path with `client_id_file`) | Required |
| `identity.jwt_svid_path` | Path to SPIFFE JWT-SVID token file | — |
| `routes.rules[].host` | Glob pattern for destination host | — |
| `routes.rules[].target_audience` | OAuth audience for token exchange | — |
| `routes.rules[].token_scopes` | Space-separated scopes to request | `openid` |
| `bypass.inbound_paths` | Paths to skip inbound JWT validation | `/.well-known/*, /healthz, /readyz, /livez` |

### URL Derivation

When explicit URLs are not set, they are derived automatically:

| Missing field | Derived from | Example |
|---|---|---|
| `token_url` | `keycloak_url` + `keycloak_realm` | `http://keycloak:8080/realms/kagenti/protocol/openid-connect/token` |
| `issuer` | `keycloak_url` + `keycloak_realm` | `http://keycloak:8080/realms/kagenti` |
| `jwks_url` | `token_url` | `.../openid-connect/certs` |

### Session Store (Experimental)

The session store correlates inbound user intents with outbound tool calls across
request boundaries. It is opt-in:

```yaml
session:
  enabled: true
  ttl: 5m
  max_events: 100
```

When enabled, guardrail plugins can access conversation history to evaluate whether
a tool call aligns with the original user intent.

## Logging and Debugging

### Log Levels

Set via `LOG_LEVEL` environment variable (`debug`, `info`, `warn`, `error`).
Default: `info`.

```bash
# Enable debug logging for an agent's AuthBridge sidecar
kubectl set env deployment/weather-service -n team1 -c envoy-proxy LOG_LEVEL=debug
```

### Runtime Log Toggle

Toggle between `info` and `debug` without restart by sending `SIGUSR1`:

```bash
kubectl exec deploy/weather-service -n team1 -c envoy-proxy -- \
  sh -c 'for f in /proc/[0-9]*/cmdline; do [ -r "$f" ] || continue; \
  c=$(cat "$f"); case "$c" in /usr/local/bin/authbridge*) \
  kill -USR1 "${f%%/cmdline}"; break;; esac; done'
```

### What to Look For

| Log message | Meaning |
|---|---|
| `token-exchange: success` | Token exchanged successfully for outbound request |
| `token-exchange: failed` | Token exchange failed (check Keycloak connectivity) |
| `jwt-validation: rejected` | Inbound request failed JWT validation |
| `proxy: blocked host` | Outbound request to a disallowed destination |
| `a2a-parser: parsed message/send` | A2A protocol request parsed for guardrails |
| `mcp-parser: request` | MCP tool call intercepted and parsed |

## Troubleshooting

### Token Exchange Fails (503 from outbound calls)

1. Check Keycloak connectivity from inside the cluster:
   ```bash
   kubectl exec deploy/weather-service -n team1 -c weather-service -- \
     wget -qO- http://keycloak-service.keycloak.svc:8080/realms/kagenti/.well-known/openid-configuration
   ```
2. Verify the agent's client is registered in Keycloak
3. Check that the target audience matches a registered client
4. Enable debug logging to see the full token exchange request/response

### Inbound Requests Rejected (401)

1. Verify the token issuer matches `inbound.issuer` in config
2. Check token expiry — short-lived tokens may expire during network delays
3. Verify JWKS endpoint is reachable from the proxy
4. Check bypass paths — `/healthz` and `/.well-known/*` skip validation by default

### Agent Cannot Reach External Services (connection refused)

1. Verify `HTTP_PROXY`/`HTTPS_PROXY` env vars are set in the agent container:
   ```bash
   kubectl exec deploy/weather-service -n team1 -c weather-service -- env | grep -i proxy
   ```
2. Check that the destination host is in the routes configuration
3. If using NetworkPolicy, verify the proxy sidecar is allowed egress

### Proxy Not Injected

1. Verify the pod has `kagenti.io/type: agent` label
2. Check that the Kagenti operator webhook is running:
   ```bash
   kubectl get mutatingwebhookconfigurations | grep kagenti
   ```
3. Check operator logs for injection errors

## Resource Expectations

| Mode | CPU (idle) | CPU (active) | Memory |
|---|---|---|---|
| proxy-sidecar | ~1m | ~10-50m | 15-30 MB |
| envoy-sidecar | ~5m | ~50-100m | 150-200 MB |

For production, set resource requests/limits on the sidecar container. The operator
injects defaults that can be overridden via Helm values.

## Further Reading

- [AuthBridge Binary README](https://github.com/kagenti/kagenti-extensions/blob/main/authbridge/cmd/authbridge/README.md) — full YAML config reference, all listener modes
- [AuthBridge Architecture](https://github.com/kagenti/kagenti-extensions/blob/main/authbridge/README.md) — sequence diagrams, protocol details
