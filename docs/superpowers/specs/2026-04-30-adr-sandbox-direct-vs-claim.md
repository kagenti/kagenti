# ADR: Direct Sandbox Creation vs SandboxTemplate + SandboxClaim

**Status:** Proposed
**Date:** 2026-04-30
**Epic:** [#1155](https://github.com/kagenti/kagenti/issues/1155)
**Context:** [Agent-Sandbox Upstream Issues](2026-04-30-agent-sandbox-upstream-issues.md),
[Workload Type Design Spec](2026-04-21-agent-sandbox-workload-type-design.md)

## Decision

The kagenti backend should create `Sandbox` CRs directly, bypassing
`SandboxTemplate` and `SandboxClaim`. This applies to both Phase 1 and the
default path going forward, with SandboxClaim support deferred to a future
phase if demand materializes.

## Context

The agent-sandbox project has three CRD layers:

```
SandboxTemplate          (extensions.agents.x-k8s.io/v1alpha1)
    └── SandboxClaim     (extensions.agents.x-k8s.io/v1alpha1)
        └── Sandbox      (agents.x-k8s.io/v1alpha1)
            ├── Pod
            ├── Service  (headless)
            └── PVCs     (from volumeClaimTemplates)
```

The **core layer** (Sandbox) is self-contained: it manages pods, services, PVCs,
scaling, and expiry. The **extensions layer** (SandboxTemplate + SandboxClaim)
adds network policy management, warm pool adoption, env var injection policies,
and secure defaults.

The question is whether kagenti should target the Sandbox API directly or go
through the claim-based abstraction.

## Options Evaluated

### Option A: Direct Sandbox Creation (Recommended)

The backend builds a `Sandbox` CR manifest (same pattern as Deployment /
StatefulSet) and creates it via the Kubernetes API. No SandboxTemplate or
SandboxClaim objects are created.

### Option B: SandboxTemplate + SandboxClaim (Current epic scope)

The backend creates a SandboxTemplate per agent template, then a SandboxClaim
per agent instance. The SandboxClaim controller creates the Sandbox.

### Option C: Hybrid (SandboxClaim for creation, operator manages Sandbox)

Use SandboxClaim to create Sandboxes (getting secure defaults and network
policy), but have the operator reconcile against the resulting Sandbox CR.

## Analysis

### What Sandbox alone provides

| Capability | Direct Sandbox |
|---|---|
| Pod lifecycle (create, delete, scale 0/1) | Yes |
| Headless Service (auto-created, same name) | Yes |
| PVC lifecycle (`volumeClaimTemplates`) | **Yes** — fully handled by Sandbox controller |
| Shutdown/expiry (`shutdownTime`, `shutdownPolicy`) | Yes |
| Replicas (0 or 1, with scale subresource) | Yes |

**Storage is fully available without the claim layer.** The Sandbox controller
creates PVCs from `spec.volumeClaimTemplates`, names them
`<template>-<sandbox>`, sets owner references for garbage collection, and
mounts them into the pod. Neither SandboxTemplate nor SandboxClaim participate
in PVC management. In fact, the SandboxClaim controller only copies
`podTemplate` from the SandboxTemplate — it does not propagate
`volumeClaimTemplates`.

### What SandboxTemplate + SandboxClaim adds

| Capability | Kagenti equivalent | Gap? |
|---|---|---|
| **NetworkPolicy (secure defaults)** — ingress from sandbox-router only, egress to public internet, blocks RFC1918/metadata server, overrides DNS to 8.8.8.8 | Istio ambient mesh (mTLS between all pods), AuthBridge envoy-proxy (OAuth2 enforcement on every request), per-namespace network policies | **No gap.** Kagenti's mesh-level isolation is stronger than the template-scoped NetworkPolicy. |
| **Warm pool adoption** — pre-provisioned pods for fast cold-start | Not implemented | **Gap, but not needed for Phase 1.** Cold-start is acceptable for initial release. |
| **Env var injection policy** — template controls whether claims can inject/override env vars | Backend controls env vars directly, webhook injects sidecar config | **No gap.** Simpler model — the backend is the single source of truth. |
| **Secure defaults** — `automountServiceAccountToken: false`, DNS override to public resolvers | Backend sets `automountServiceAccountToken: false` in manifest builder. DNS handled by mesh. | **No gap.** Backend applies these directly. |
| **Ownership cascade** — Claim → Sandbox → Pod/Service/PVC | Backend manages lifecycle. Sandbox → Pod/Service/PVC cascade still works. | **No gap.** The Sandbox-level cascade is sufficient. |
| **Additional pod metadata validation** — blocks restricted label domains on claims | Backend controls all labels. Webhook validates at pod CREATE time. | **No gap.** |

### Operator compatibility

This is the decisive factor. The kagenti-operator's AgentRuntime controller
reconciles against the **workload object** specified in `spec.targetRef`. With
the claim-based flow:

```
AgentRuntime (targetRef: Sandbox) ──reconciles──▶ Sandbox
                                                     ▲
                                          owned by   │
                                                     │
                                              SandboxClaim
```

The operator writes labels, annotations, and config-hash to the Sandbox's
`spec.podTemplate`. The SandboxClaim controller also writes to the Sandbox
(claim-uid label, template-ref-hash label, pod-name annotation during warm pool
adoption). This creates **three concurrent writers** on the same object:

1. **kagenti-operator** — writes config-hash, kagenti labels
2. **Sandbox controller** — writes pod-name annotation, reconciles pod metadata
3. **SandboxClaim controller** — writes claim-uid, template-ref-hash, pod-name (adoption)

The `agents.x-k8s.io/pod-name` annotation race condition
([documented here](2026-04-30-agent-sandbox-upstream-issues.md#issue-2-sandbox-controller-stuck-loop-after-pod-deletion))
is already problematic with two writers. Adding a third writer (SandboxClaim)
widens the race window.

With direct Sandbox creation:

```
AgentRuntime (targetRef: Sandbox) ──reconciles──▶ Sandbox
```

Only two writers (operator + Sandbox controller). The race window is narrower
and the ownership model is unambiguous — the backend creates the Sandbox, the
operator configures it.

### Pod rollout problem

Neither approach fixes the upstream pod rollout issue
([kubernetes-sigs/agent-sandbox#581](https://github.com/kubernetes-sigs/agent-sandbox/issues/581)).
The Sandbox controller does not recreate pods when `spec.podTemplate` changes,
regardless of whether the Sandbox was created by a SandboxClaim or directly.

The operator's scale 0→1 workaround works the same way in both approaches. The
claim layer adds no value for rollout handling.

### Complexity comparison

| Aspect | Direct Sandbox | SandboxClaim |
|---|---|---|
| CRDs the backend must manage | 1 (Sandbox) | 3 (SandboxTemplate, SandboxClaim, Sandbox) |
| Objects created per agent | 1 | 2-3 |
| Operator targetRef target | Sandbox (direct) | Sandbox (indirect, owned by claim) |
| Concurrent writers on Sandbox | 2 | 3 |
| Backend code | Mirror Deployment pattern | New claim lifecycle code |
| Cleanup on delete | Delete Sandbox (cascades) | Delete SandboxClaim (cascades) |
| `volumeClaimTemplates` | Set directly on Sandbox | **Not propagated** by SandboxClaim controller |
| Feature-flag scope | Sandbox CRD only | Sandbox CRD + extensions CRDs |

## Decision Rationale

1. **Every capability SandboxTemplate/SandboxClaim provides is already covered
   by kagenti's platform layer** (Istio ambient, AuthBridge, webhook injection,
   operator config management). The claim layer would be redundant
   infrastructure.

2. **Storage lifecycle (`volumeClaimTemplates`) works better with direct
   creation.** The SandboxClaim controller does not propagate volume claim
   templates from the SandboxTemplate — it only copies `podTemplate`. Direct
   Sandbox creation gives the backend full control over PVC configuration.

3. **Fewer concurrent writers reduces the pod-name annotation race window.**
   The operator's restart mechanism (scale 0→1 with annotation clearing)
   competes with the Sandbox controller. Adding the SandboxClaim controller as
   a third writer makes the race harder to reason about and harder to fix.

4. **Simpler operational model.** One CRD type to manage, one object per agent,
   clear ownership. The backend creates it, the operator configures it, the
   Sandbox controller runs it.

5. **Warm pool is the only genuinely lost capability**, and it is explicitly
   out of scope for Phase 1. If warm pool support is needed later, it can be
   added as an optional optimization — the backend creates a SandboxClaim
   instead of a Sandbox when a warm pool is configured.

## Consequences

### Positive

- Backend code follows the established Deployment/StatefulSet pattern — no new
  abstraction layer to learn or maintain.
- Operator has a clean reconciliation target with predictable ownership.
- Full control over `volumeClaimTemplates` for persistent agent storage.
- Fewer moving parts to debug when things go wrong (one controller, not three).
- No dependency on the extensions CRDs — clusters only need the core Sandbox
  CRD installed.

### Negative

- No shared NetworkPolicy per template. Kagenti's mesh provides equivalent
  isolation, but clusters without Istio would need to manage NetworkPolicies
  separately.
- No warm pool adoption. Cold-start time for Sandbox agents equals pod creation
  time (typically 5-15s with sidecar injection). This is acceptable for Phase 1
  but may need revisiting for latency-sensitive use cases.
- The backend must explicitly set secure defaults (`automountServiceAccountToken:
  false`, resource limits, non-root security context) that the SandboxClaim
  path would apply automatically. The current manifest builder already does
  this.

### Migration path

If SandboxClaim support is needed later:

1. Add a "pool" field to the agent creation request.
2. When a pool is specified, create a SandboxClaim instead of a Sandbox.
3. The operator's `targetRef` still points to the resulting Sandbox CR — no
   operator changes needed.
4. The direct creation path remains the default for agents without a pool.

## References

- [Agent-Sandbox Upstream Issues](2026-04-30-agent-sandbox-upstream-issues.md)
- [Agent-Sandbox Workload Type Design](2026-04-21-agent-sandbox-workload-type-design.md)
- [kubernetes-sigs/agent-sandbox#581](https://github.com/kubernetes-sigs/agent-sandbox/issues/581) — Pod rollout
- [kagenti-operator#316](https://github.com/kagenti/kagenti-operator/pull/316) — Operator Sandbox support PR
- [Epic #1155](https://github.com/kagenti/kagenti/issues/1155) — Sandbox workload type
