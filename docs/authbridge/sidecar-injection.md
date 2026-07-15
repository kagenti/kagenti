# AuthBridge Sidecar Injection

This page explains what containers to expect in an agent pod, which labels
control injection, and how to switch modes.

## Verify which mode you're in

```bash
# List container names in the running pod
kubectl get pods -n team1 -l kagenti.io/type=agent \
  -o jsonpath='{range .items[*]}{.metadata.name}{" → "}{.spec.containers[*].name}{"\n"}{end}'

# Or for a specific deployment
kubectl get pods -n team1 -l app=weather-service \
  -o jsonpath='{.items[0].spec.containers[*].name}'
```

## Expected containers by mode

| Mode | Regular containers | Init containers | Notes |
|---|---|---|---|
| `proxy-sidecar` (default) | `<agent>` `authbridge-proxy` | — | SPIRE integration is in-process inside `authbridge-proxy` when `SPIRE_ENABLED=true` |
| `lite` | `<agent>` `authbridge-proxy` | — | Same shape as proxy-sidecar; uses `authbridge-lite` image (auth-only) |
| `envoy-sidecar` | `<agent>` `envoy-proxy` | `proxy-init` | SPIRE integration is in-process inside `envoy-proxy` when `SPIRE_ENABLED=true`; proxy-init is privileged |
| `waypoint` | — | — | Not injected as a sidecar; waypoint is a standalone deployment |

> **There is no spiffe-helper container or process.** AuthBridge uses the
> [go-spiffe](https://github.com/spiffe/go-spiffe) SDK directly to open a
> `workloadapi.JWTSource` against the SPIRE workload API socket
> (`/spiffe-workload-api/spire-agent.sock`) and fetch JWT-SVIDs in-process.
> The files in `/opt` (`svid.pem`, `jwt_svid.token`, etc.) are written by a
> goroutine inside AuthBridge itself for compatibility with external file readers
> — not by a separate binary. SPIRE integration is enabled or disabled via the
> `SPIRE_ENABLED` env var, which the operator sets per workload based on the
> `kagenti.io/spiffe-helper-inject` label.

## Label vocabulary

Labels are set on the **pod template** (e.g. `Deployment.spec.template.metadata.labels`).
The operator applies `kagenti.io/type` automatically via the AgentRuntime reconciler —
you normally do not need to set it yourself.

### Pre-filter labels (control whether injection runs at all)

| Label | Values | Behavior |
|---|---|---|
| `kagenti.io/type` | `agent` \| `tool` | **Required for injection.** Only `agent` and `tool` workloads are mutated. Set automatically by the operator. |
| `kagenti.io/inject` | `disabled` | Set to `disabled` to opt this workload out of all sidecar injection. Any other value (or absent) allows injection. |

### Per-sidecar opt-out labels

These let you disable a specific sidecar while leaving others active.

| Label | Default | Set to `false` to… |
|---|---|---|
| `kagenti.io/envoy-proxy-inject` | inject (when feature gate is on) | Disable the `envoy-proxy` sidecar (envoy-sidecar mode only) |
| `kagenti.io/spiffe-helper-inject` | inject (enabled) | Suppress SPIRE — sets `SPIRE_ENABLED=false` on the combined sidecar, preventing the bundled spiffe-helper process from starting |

### Deprecated label

| Annotation | Status | Replacement |
|---|---|---|
| `kagenti.io/authbridge-mode` | **Deprecated** — still honored | Use `AgentRuntime.Spec.AuthBridgeMode` |

### Examples

```yaml
# Opt this workload out of all injection
metadata:
  labels:
    kagenti.io/inject: "disabled"

# Keep injection but disable SPIRE
metadata:
  labels:
    kagenti.io/spiffe-helper-inject: "false"

# Disable the envoy-proxy sidecar in envoy-sidecar mode
metadata:
  labels:
    kagenti.io/envoy-proxy-inject: "false"
```

## How to switch modes

Mode is resolved from this chain (first non-empty wins):

1. `AgentRuntime.Spec.AuthBridgeMode` on the workload's CR **(canonical)**
2. `mode:` field in the namespace-level `authbridge-runtime-config` ConfigMap
3. `kagenti.io/authbridge-mode` pod annotation *(deprecated — still honored)*
4. Cluster-wide default: `proxy-sidecar`

### Per-workload override (AgentRuntime CR)

```yaml
apiVersion: kagenti.io/v1alpha1
kind: AgentRuntime
metadata:
  name: weather-service
  namespace: team1
spec:
  authBridgeMode: envoy-sidecar   # proxy-sidecar | envoy-sidecar | lite | waypoint
  targetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: weather-service
```

### Namespace default (ConfigMap)

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: authbridge-runtime-config
  namespace: team1
data:
  mode: proxy-sidecar
```

### Verify the resolved mode

```bash
kubectl logs -n kagenti-system deploy/kagenti-operator \
  | grep "resolved authbridge mode"
```

## Cluster-admin feature gates

Feature gates are loaded from the `kagenti-webhook-config` ConfigMap in the
operator's namespace and take effect immediately (no restart needed).

| Gate | Default | Controls |
|---|---|---|
| `globalEnabled` | `true` | Master kill switch — set to `false` to disable all sidecar injection cluster-wide |
| `envoyProxy` | `true` | Whether the `envoy-proxy` sidecar is injected (envoy-sidecar mode) |
| `injectTools` | `false` | Whether `kagenti.io/type=tool` workloads receive injection (agents are always injected) |
| `perWorkloadConfigResolution` | `false` | When `true`, webhook reads namespace ConfigMaps at admission time and injects literal env var values instead of `valueFrom` references |

Source of truth: [`internal/webhook/config/feature_gates.go`](https://github.com/kagenti/kagenti-operator/blob/main/kagenti-operator/internal/webhook/config/feature_gates.go)

## Full injection decision flow

```
Pod admitted by webhook
  └─ kagenti.io/type ∈ {agent, tool}?  — No → skip
       └─ globalEnabled=true?  — No → skip
            └─ type=tool and injectTools=false?  — Yes → skip
                 └─ kagenti.io/inject=disabled?  — Yes → skip
                      └─ Resolve mode (CR → namespace CM → annotation → default)
                           ├─ waypoint → skip (standalone deployment)
                           ├─ proxy-sidecar / lite
                           │    └─ inject authbridge-proxy
                           │         + HTTP_PROXY env vars into agent container
                           │         + SPIRE_ENABLED based on spiffe-helper decision
                           └─ envoy-sidecar
                                └─ inject envoy-proxy (if envoyProxy gate=true and label≠false)
                                     + proxy-init (follows envoy-proxy decision)
                                     + SPIRE_ENABLED based on spiffe-helper decision
```

## Related

- [Deployment Guide](deployment-guide.md) — mode details, configuration, troubleshooting
- [Security Model](security-model.md) — mTLS, SPIFFE identity, token exchange
- [AuthBridge Architecture](https://github.com/kagenti/kagenti-extensions/blob/main/authbridge/README.md) — sequence diagrams, protocol details
