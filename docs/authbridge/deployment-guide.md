---
draft: true       # excluded from https://www.rossoctl.dev/
---

# AuthBridge Deployment Guide

## Deployment Modes

AuthBridge ships three combined sidecar images, each hardcoded to its
deployment shape (cortex#411):

| | `authbridge` (proxy-sidecar, default) | `authbridge-envoy` (envoy-sidecar, advanced) | `authbridge-lite` (proxy-sidecar, auth-only) |
|---|---|---|---|
| **Containers per pod** | 1 combined sidecar | 1 combined sidecar + proxy-init container | 1 combined sidecar |
| **Privileged mode** | No | Yes (iptables init) | No |
| **Interception** | HTTP_PROXY env vars | iptables NAT rules | HTTP_PROXY env vars |
| **Plugins included** | jwt-validation + token-exchange + a2a/mcp/inference parsers | Same as proxy-sidecar | jwt-validation + token-exchange only |
| **Use when** | Standard deployments | Need transparent interception of non-HTTP protocols | Size-constrained / no protocol-aware events |

SPIRE integration is built into every combined image using the
[go-spiffe](https://github.com/spiffe/go-spiffe) SDK. It is enabled or disabled
per workload via the `SPIRE_ENABLED` env var (driven by the
`rossoctl.io/spiffe-helper-inject` label) — there is no separate spiffe-helper
binary or process. Client registration is handled by the operator's reconciler —
there's no in-pod client-registration sidecar.

## Selecting a mode

The mutating webhook resolves mode from this chain (first non-empty wins):

1. `mode:` field in the namespace-level `authbridge-runtime-config` ConfigMap **(canonical)**.
2. The deprecated `rossoctl.io/authbridge-mode` pod annotation (still honored).
3. Cluster-wide default (`proxy-sidecar`).

> **Note:** `AgentRuntime.Spec.AuthBridgeMode` is enum-validated by the CRD webhook but is not
> read by the mutating webhook when resolving injection mode. Setting it does not change which
> containers are injected.

The canonical way to set mode is the namespace ConfigMap, which applies to all workloads in
the namespace:

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: authbridge-runtime-config
  namespace: team1
data:
  config.yaml: |
    mode: envoy-sidecar
```

## Proxy-Sidecar Mode (Default)

### How It Works

The Rossoctl operator webhook injects a single `authbridge` container when
the workload's resolved mode is `proxy-sidecar`:

1. The reverse proxy takes over the agent's original port (e.g., `:8000`)
2. The agent is moved to a free port (e.g., `:8001`) via `PORT` env var
3. `HTTP_PROXY` and `HTTPS_PROXY` env vars are injected into the agent container
4. The Kubernetes Service targetPort remains unchanged — traffic flows through the proxy

### Traffic Flow

```
Inbound:   Client → Service:8000 → Reverse Proxy → Agent:8001
Outbound:  Agent → HTTP_PROXY → Forward Proxy → Token Exchange → External Service
```

## Envoy-Sidecar Mode (Advanced)

For environments that require transparent interception of all TCP traffic
(not just HTTP), envoy-sidecar mode uses iptables to redirect traffic
through Envoy with an ext_proc gRPC filter:

```yaml
spec:
  authBridgeMode: envoy-sidecar
```

This mode requires privileged mode for the `proxy-init` iptables init
container and uses [Envoy](https://www.envoyproxy.io/docs/envoy/latest/)
as the data path inside the combined `authbridge-envoy` container. Use it
only when you need protocol-level transparent interception.

## Configuration

AuthBridge is configured via YAML with `${ENV_VAR}` expansion. The operator
mounts the configuration from a ConfigMap such as `authbridge-config-weather-service`.

After cortex#411 the runtime config uses a per-plugin
schema: every plugin-specific setting lives under its own `config:`
block inside `pipeline.inbound.plugins[]` or
`pipeline.outbound.plugins[]`. Plugin-level defaults (audience_file,
bypass_paths, identity file paths) are applied by the authbridge
binary itself — see `authbridge/authlib/plugins/CONVENTIONS.md` in
cortex for the full reference. The chart-rendered
ConfigMaps and the backend's per-agent ConfigMap renderer both emit
this shape.

### Minimal config (mode-agnostic)

```yaml
# No top-level mode: — the operator resolves it per workload (CR →
# namespace ConfigMap → annotation → cluster default) and layers the
# resolved value onto each per-agent ConfigMap.
pipeline:
  inbound:
    plugins:
      - name: jwt-validation
        config:
          issuer: "${ISSUER}"
          keycloak_url: "${KEYCLOAK_URL}"
          keycloak_realm: "${KEYCLOAK_REALM}"
  outbound:
    plugins:
      - name: token-exchange
        config:
          keycloak_url: "${KEYCLOAK_URL}"
          keycloak_realm: "${KEYCLOAK_REALM}"
          default_policy: "passthrough"
          identity:
            type: spiffe
```

### Configuration Reference

The fields below appear inside each plugin's `config:` block, not at
the top level. See `authbridge/docs/plugin-reference.md` in
cortex for the per-plugin authoritative reference.

| Field | Plugin | Description | Default |
|---|---|---|---|
| `mode` (top-level) | — | Deployment mode: `proxy-sidecar`, `envoy-sidecar`, `lite`, `waypoint`. Usually unset; layered in by the operator. | `proxy-sidecar` |
| `issuer` | jwt-validation | Expected JWT issuer for inbound validation | Derived from keycloak_url |
| `jwks_url` | jwt-validation | JWKS endpoint for signature verification | Derived from issuer |
| `keycloak_url` | jwt-validation, token-exchange | Internal Keycloak base URL | Required |
| `keycloak_realm` | jwt-validation, token-exchange | Keycloak realm name | Required |
| `token_url` | token-exchange | Keycloak token endpoint | Derived from keycloak_url + realm |
| `default_policy` | token-exchange | `passthrough` or `exchange` | `passthrough` |
| `identity.type` | token-exchange | `spiffe` or `client-secret` | Required |
| `routes.file` | token-exchange | Path to `routes.yaml` (per-host token exchange rules) | `/etc/authproxy/routes.yaml` |
| `routes.rules[].host` | token-exchange | Glob pattern for destination host | — |
| `routes.rules[].target_audience` | token-exchange | OAuth audience for token exchange | — |
| `routes.rules[].token_scopes` | token-exchange | Space-separated scopes to request | `openid` |
| `bypass_paths` | jwt-validation | Paths to skip inbound JWT validation | `/.well-known/*, /healthz, /readyz, /livez` |

### URL Derivation

When explicit URLs are not set, they are derived automatically:

| Missing field | Derived from | Example |
|---|---|---|
| `token_url` | `keycloak_url` + `keycloak_realm` | `http://keycloak:8080/realms/rossoctl/protocol/openid-connect/token` |
| `issuer` | `keycloak_url` + `keycloak_realm` | `http://keycloak:8080/realms/rossoctl` |
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
     wget -qO- http://keycloak-service.keycloak.svc:8080/realms/rossoctl/.well-known/openid-configuration
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

1. Verify the pod has `rossoctl.io/type: agent` label — the operator sets this automatically when an AgentRuntime CR targets the workload
2. Check that the Rossoctl operator webhook is running:
   ```bash
   kubectl get mutatingwebhookconfigurations | grep rossoctl
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

- [Sidecar Injection](sidecar-injection.md) — expected containers per mode, label vocabulary, feature gates, how to switch modes
- [Authentication Guide](../authentication.md) — how `CLIENT_AUTH_TYPE=federated-jwt` (SPIFFE auth) works, how to enable it, and how it compares to client-secret mode
- [AuthBridge Binary README](https://github.com/rossoctl/cortex/blob/main/authbridge/cmd/README.md) — full YAML config reference, all listener modes
- [AuthBridge Architecture](https://github.com/rossoctl/cortex/blob/main/authbridge/README.md) — sequence diagrams, protocol details
