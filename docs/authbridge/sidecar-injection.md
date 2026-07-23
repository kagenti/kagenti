---
draft: true       # excluded from https://www.rossoctl.dev/
---

# AuthBridge Sidecar Injection

This page explains what containers to expect in an agent pod, which labels
control injection, and how to switch modes.

## Verify which mode you're in

```bash
# List container names in the running pod
kubectl get pods -n team1 -l rossoctl.io/type=agent \
  -o jsonpath='{range .items[*]}{.metadata.name}{" → "}{.spec.containers[*].name}{"\n"}{end}'

# Or for a specific deployment
kubectl get pods -n team1 -l app=weather-service \
  -o jsonpath='{.items[0].spec.containers[*].name}'
```

## Expected containers by mode

| Mode | Regular containers | Init containers | Notes |
|---|---|---|---|
| `proxy-sidecar` (default) | `<agent>` `authbridge-proxy` | — | SPIRE integration is in-process inside `authbridge-proxy` when `SPIRE_ENABLED=true` |
| `lite` | `<agent>` `authbridge-proxy` | — | Same shape as proxy-sidecar; uses `authbridge-lite` image (auth-only plugins); SPIRE integration in-process when `SPIRE_ENABLED=true` |
| `envoy-sidecar` | `<agent>` `envoy-proxy` | `proxy-init` | SPIRE integration is in-process inside `envoy-proxy` when `SPIRE_ENABLED=true`; proxy-init runs as root (UID 0) with NET_ADMIN/NET_RAW — not privileged |
| `waypoint` | — | — | Not injected as a sidecar; waypoint is a standalone deployment |

> **There is no spiffe-helper container or process.** AuthBridge uses the
> [go-spiffe](https://github.com/spiffe/go-spiffe) SDK directly to open a
> `workloadapi.JWTSource` against the SPIRE workload API socket
> (`/spiffe-workload-api/spire-agent.sock`) and fetch JWT-SVIDs in-process.
> The files in `/opt` (`svid.pem`, `jwt_svid.token`, etc.) are written by a
> goroutine inside AuthBridge itself for compatibility with external file readers
> — not by a separate binary. SPIRE integration is enabled or disabled via the
> `SPIRE_ENABLED` env var, which the operator sets per workload based on the
> `rossoctl.io/spiffe-helper-inject` label.

## Label vocabulary

Labels are set on the **pod template** (e.g. `Deployment.spec.template.metadata.labels`).
The operator applies `rossoctl.io/type` automatically via the AgentRuntime reconciler —
you normally do not need to set it yourself.

### Pre-filter labels (control whether injection runs at all)

| Label | Values | Behavior |
|---|---|---|
| `rossoctl.io/type` | `agent` \| `tool` | **Required for injection.** Only `agent` and `tool` workloads are mutated. Set automatically by the operator. |
| `rossoctl.io/inject` | `disabled` | Set to `disabled` to opt this workload out of all sidecar injection. Any other value (or absent) allows injection. |

### Per-sidecar opt-out labels

These let you disable a specific sidecar while leaving others active.

| Label | Default | Set to `false` to… |
|---|---|---|
| `rossoctl.io/envoy-proxy-inject` | inject (when feature gate is on) | Disable the `envoy-proxy` sidecar (envoy-sidecar mode only) |
| `rossoctl.io/spiffe-helper-inject` | inject (enabled) | Suppress SPIRE — sets `SPIRE_ENABLED=false` on the sidecar, preventing the go-spiffe workload API source from being opened |

### Deprecated label

| Annotation | Status | Replacement |
|---|---|---|
| `rossoctl.io/authbridge-mode` | **Deprecated** — still honored | Set `mode:` in the namespace `authbridge-runtime-config` ConfigMap |

### Examples

```yaml
# Opt this workload out of all injection
metadata:
  labels:
    rossoctl.io/inject: "disabled"

# Keep injection but disable SPIRE
metadata:
  labels:
    rossoctl.io/spiffe-helper-inject: "false"

# Disable the envoy-proxy sidecar in envoy-sidecar mode
metadata:
  labels:
    rossoctl.io/envoy-proxy-inject: "false"
```

## How to switch modes

Mode is resolved by the **mutating webhook** from this chain (first non-empty wins):

1. `mode:` field in the namespace-level `authbridge-runtime-config` ConfigMap
2. `rossoctl.io/authbridge-mode` pod annotation *(deprecated — still honored)*
3. Cluster-wide default: `proxy-sidecar`

> **Note on `AgentRuntime.Spec.AuthBridgeMode`:** This field exists on the CRD and is
> enum-validated, but the mutating webhook does not read it during injection. Setting it
> does not change which containers are injected. Use the namespace ConfigMap to control
> mode for all workloads in a namespace.

### Namespace default (ConfigMap)

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: authbridge-runtime-config
  namespace: team1
data:
  config.yaml: |
    mode: proxy-sidecar
```

### Verify the resolved mode

```bash
kubectl logs -n rossoctl-system deploy/operator \
  | grep "resolved authbridge mode"
```

## Cluster-admin feature gates

Feature gates are loaded from the `rossoctl-feature-gates` ConfigMap in the
operator's namespace and take effect immediately (no restart needed).

| Gate | Default | Controls |
|---|---|---|
| `globalEnabled` | `true` | Master kill switch — set to `false` to disable all sidecar injection cluster-wide |
| `envoyProxy` | `true` | Whether the `envoy-proxy` sidecar is injected (envoy-sidecar mode) |
| `injectTools` | `false` | Whether `rossoctl.io/type=tool` workloads receive injection (agents are always injected) |
| `perWorkloadConfigResolution` | `false` | When `true`, webhook reads namespace ConfigMaps at admission time and injects literal env var values instead of `valueFrom` references |

Source of truth: [`internal/webhook/config/feature_gates.go`](https://github.com/rossoctl/operator/blob/main/operator/internal/webhook/config/feature_gates.go)

## Full injection decision flow

```
Pod admitted by webhook
  └─ rossoctl.io/type ∈ {agent, tool}?  — No → skip
       └─ globalEnabled=true?  — No → skip
            └─ type=tool and injectTools=false?  — Yes → skip
                 └─ rossoctl.io/inject=disabled?  — Yes → skip
                      └─ Resolve mode (namespace CM → annotation → default)
                           ├─ waypoint → skip (standalone deployment)
                           ├─ proxy-sidecar / lite
                           │    └─ inject authbridge-proxy
                           │         + HTTP_PROXY env vars into agent container
                           │         + SPIRE_ENABLED based on spiffe-helper-inject label
                           └─ envoy-sidecar
                                └─ inject envoy-proxy (if envoyProxy gate=true and label≠false)
                                     + proxy-init (follows envoy-proxy decision)
                                     + SPIRE_ENABLED based on spiffe-helper-inject label
```

## Related

- [Deployment Guide](deployment-guide.md) — mode details, configuration, troubleshooting
- [Security Model](security-model.md) — mTLS, SPIFFE identity, token exchange
- [AuthBridge Architecture](https://github.com/rossoctl/cortex/blob/main/authbridge/README.md) — sequence diagrams, protocol details
