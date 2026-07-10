---
name: istio:mesh-selfheal
description: Detect and recover from Istio Ambient mesh outages where ztunnel/waypoint proxies serve expired mTLS certs and every gateway route returns HTTP 503 (long-running or suspended dev/Kind clusters)
---

# Istio Ambient Mesh Self-Heal

Detect and recover the classic **"everything returns 503"** outage on a long-running or
suspended dev/Kind cluster (kagenti/kagenti#1899): after a host suspend the Istio Ambient
data plane (ztunnel + waypoints) keeps serving **expired istiod-issued mTLS certs** and never
re-fetches, so all `*.localtest.me` routes 503 — while every pod still looks `Running`.

**Scope: dev / Kind.** Do not auto-run recovery against a production mesh.

## When to use

Reach for this when:
- `http://*.localtest.me:8080/` (UI, API, MLflow, Kiali…) all return **HTTP 503**, and
- `kubectl get pods -A` looks healthy, Gateway/HTTPRoute status is `Accepted`/`ResolvedRefs`, and
- the 503 body is `upstream connect error … connection termination` with header `server: istio-envoy`.

That pattern = the data plane is reachable and routing, but the upstream mTLS hop fails on an
expired cert.

## Two failure domains (don't conflate)

1. **Mesh 503 (this skill).** ztunnel/waypoint certs are **istiod-issued** (SDS), not SPIRE.
   The durable fix is upstream (**istio/ztunnel#1679**); the dev-cluster mitigation is to restart
   the data plane so it re-fetches fresh certs.
2. **SPIRE agent reattest deadlock** (a separate, coincident suspend casualty) breaks
   **AuthBridge / token-exchange identity**, *not* mesh routing. Check it with `--include-spire`.

## Detect + recover (one command)

```bash
# Detect only (read-only) — reports status and prints the recommended recovery commands
scripts/k8s/mesh-recover.sh

# Apply the recovery (rollout restart ztunnel + waypoints + gateway)
scripts/k8s/mesh-recover.sh --fix

# Also check/restart the SPIRE agent (separate AuthBridge domain)
scripts/k8s/mesh-recover.sh --fix --include-spire
```

Exit codes: `0` healthy · `2` degraded (or fix attempted) · `1` usage/precondition error.
Useful flags: `--probe-host <host>`, `--gateway-url <url>` (default `http://127.0.0.1:8080`),
`--json` (machine-readable). The script **discovers** the ztunnel namespace (Kind installs put it
in `istio-system`; the chart uses `istio-ztunnel`) rather than hardcoding it.

## Manual fallback (what --fix runs)

```bash
# 1. ztunnel — the node proxy all mesh traffic flows through (discover its namespace first)
ZT_NS=$(kubectl get ds -A -l app=ztunnel -o jsonpath='{.items[0].metadata.namespace}')
kubectl rollout restart daemonset/ztunnel -n "$ZT_NS"

# 2. waypoint proxies (L7), if any
kubectl rollout restart deploy -A -l gateway.networking.k8s.io/managed-by=istio.io-mesh-controller

# 3. the ingress gateway
kubectl rollout restart deploy/http-istio -n kagenti-system

# verify
curl -s -o /dev/null -w "HTTP %{http_code}\n" -H "Host: kagenti-ui.localtest.me" http://127.0.0.1:8080/
```

## Diagnostic one-liners

```bash
# Is it a mesh cert problem? (CertificateExpired / expired peer certificate)
kubectl logs -n "$ZT_NS" -l app=ztunnel --tail=100 | grep -iE "certificate expired|CertificateExpired"

# ztunnel cert status (if istioctl is installed)
istioctl ztunnel-config certificates "$(kubectl get pod -n "$ZT_NS" -l app=ztunnel -o jsonpath='{.items[0].metadata.name}')" -n "$ZT_NS"

# SPIRE agent failing to re-attest? (separate domain)
kubectl logs -n spire-system -l app=spire-agent --previous --tail=40 | grep -iE "reattest|token has expired|Agent crashed"
```

## Testing (dev/Kind)

A real suspend/clock-expiry can't be forced deterministically, so a helper induces the same
symptom (CA down + ztunnel restarted → data plane has no valid cert → mesh-wide 503) and runs the
full detect → `--fix` → re-probe loop. **Destructive to the mesh; Kind-guarded.**

```bash
scripts/k8s/induce-mesh-outage.sh --self-test   # break → assert detect(exit 2) → restore CA → --fix → assert green
scripts/k8s/induce-mesh-outage.sh --break       # induce and leave broken (to test manually)
scripts/k8s/induce-mesh-outage.sh --restore     # undo
```

## References

- kagenti/kagenti#1899 — the mesh-wide 503 outage this addresses.
- istio/ztunnel#1679 — the upstream bug for the durable data-plane self-heal fix.
- Related skills: `k8s:health`, `istio:ambient-waypoint`.
