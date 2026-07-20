---
name: istio
description: Istio service mesh patterns for Rossoctl
---

# Istio Skills

Skills for configuring Istio service mesh in Ambient mode.

## Available Skills

| Skill | Description |
|-------|-------------|
| `istio:ambient-waypoint` | L7 AuthorizationPolicy with waypoint proxies |
| `istio:mesh-selfheal` | Detect/recover the Ambient expired-cert 503 outage on long-running dev clusters |

## Ambient Mode Basics

In Istio Ambient mode:
- **ztunnel**: Handles L4 traffic (TCP, mTLS)
- **Waypoint**: Handles L7 traffic (HTTP) - needed for path-based authorization

## Common Tasks

### Enable Ambient for Namespace

```bash
kubectl label namespace rossoctl-system istio.io/dataplane-mode=ambient
```

### Create Waypoint

```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: Gateway
metadata:
  name: my-waypoint
  labels:
    istio.io/waypoint-for: service
spec:
  gatewayClassName: istio-waypoint
  listeners:
    - name: mesh
      port: 15008
      protocol: HBONE
```

## Related Skills

- `testing:kubectl-debugging`
