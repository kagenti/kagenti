# Combined AuthBridge sidecar (single `authbridge` container)

The [kagenti-extensions](https://github.com/kagenti/kagenti-extensions) admission webhook can inject AuthBridge in two shapes:

| Mode | Long-running containers | Init |
|------|-------------------------|------|
| **Legacy (default)** | `envoy-proxy`, `spiffe-helper`, `kagenti-client-registration` | `proxy-init` |
| **Combined** | Single `authbridge` (Envoy + go-processor + optional spiffe-helper + client-registration processes) | `proxy-init` |

Combined mode reduces per-pod overhead and is implemented in [kagenti-extensions#254](https://github.com/kagenti/kagenti-extensions/pull/254).

## Who turns it on?

**Cluster operators** enable combined mode on the **webhook**, not application developers from the Kagenti import UI.

The webhook reads `featureGates.combinedSidecar` from its feature-gate configuration (Helm values on the `kagenti-webhook` chart, or the ConfigMap the webhook loads—see the [kagenti-webhook chart](https://github.com/kagenti/kagenti-extensions/tree/main/charts/kagenti-webhook) and [webhook README](https://github.com/kagenti/kagenti-extensions/tree/main/kagenti-webhook)).

- Default: `combinedSidecar: false` (legacy three sidecars).
- Set to `true`: new pods for injected agents/tools get one `authbridge` container (plus `proxy-init` when Envoy injection applies).

## Relationship to import labels

Workload labels the Kagenti UI sets (for example `kagenti.io/envoy-proxy-inject`, `kagenti.io/spiffe-helper-inject`, `kagenti.io/client-registration-inject`) still apply in combined mode: the webhook passes them as environment flags (`SPIRE_ENABLED`, `CLIENT_REGISTRATION_ENABLED`) into the single container, as described in PR #254.

## Kagenti UI

The import flows do **not** toggle combined mode. After enabling it on the webhook, expect fewer containers in `kubectl get pods` without changing UI settings. The Import Agent and Import Tool pages link to this document for context.
