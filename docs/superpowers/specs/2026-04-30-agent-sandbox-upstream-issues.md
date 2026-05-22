# Agent-Sandbox Upstream Issues — Operator Integration Findings

**Epic:** [#1155](https://github.com/kagenti/kagenti/issues/1155)
**Component:** kagenti-operator AgentRuntime controller + agents.x-k8s.io Sandbox controller
**Discovered:** 2026-04-29, during live testing of operator PR [kagenti-operator#316](https://github.com/kagenti/kagenti-operator/pull/316)

## Context

The kagenti-operator's AgentRuntime controller manages workload configuration (labels,
annotations, config-hash) for Deployment, StatefulSet, and now Sandbox targets. When
configuration changes (e.g., a namespace-level ConfigMap is updated), the operator
recomputes a config-hash and applies it to the workload's pod template. For Deployments
and StatefulSets, the annotation change triggers a rolling update automatically. Sandbox
has no such mechanism.

## Issue 1: Sandbox Pods Do Not Roll Out on PodTemplate Changes

**Upstream issue:** [kubernetes-sigs/agent-sandbox#581](https://github.com/kubernetes-sigs/agent-sandbox/issues/581)

### Behavior

When the kagenti-operator updates `spec.podTemplate.metadata.annotations` on a Sandbox
CR (e.g., writing a new `kagenti.io/config-hash`), the Sandbox controller does not
terminate and recreate the running pod. The existing pod continues running with stale
configuration indefinitely.

This differs from Deployment and StatefulSet, where a change to
`spec.template.metadata.annotations` triggers a rolling update.

### Root cause

The Sandbox controller's `reconcilePod` method (`sandbox_controller.go:480`) checks
whether a pod exists by reading the `agents.x-k8s.io/pod-name` annotation. If the named
pod exists and is running, the controller considers reconciliation complete — it does not
compare the pod's spec against the current `spec.podTemplate`.

### Impact

Any configuration change that the kagenti-operator applies to the Sandbox (new config-hash
from ConfigMap changes, label updates, annotation changes) has no effect on the running
pod until the pod is externally deleted or the Sandbox is scaled down and back up.

### Our workaround

The operator's `restartSandbox` method performs an explicit scale 0 → 1 cycle:

1. Patch `spec.replicas` to 0 (with `retry.RetryOnConflict`)
2. Clear the `agents.x-k8s.io/pod-name` annotation (see Issue 2)
3. Patch `spec.replicas` to 1 (with `retry.RetryOnConflict`)

This forces the Sandbox controller to delete the existing pod and create a new one from
the updated `spec.podTemplate`.

---

## Issue 2: Sandbox Controller Stuck Loop After Pod Deletion

### Behavior

After the operator scales a Sandbox to 0 replicas (deleting the pod) and then scales back
to 1, the Sandbox controller enters a persistent error loop:

```
error: "pod in annotation get failed: Pod \"weather-service-1000\" not found"
```

The controller retries with exponential backoff (1s, 2s, 4s, 10s, 20s, 40s...) and does
**not** self-recover. The error loop continues indefinitely until the stale
`agents.x-k8s.io/pod-name` annotation is manually cleared.

### Root cause

The Sandbox controller tracks its adopted pod via the `agents.x-k8s.io/pod-name`
annotation on the Sandbox CR. When reconciling, the controller:

1. Reads `agents.x-k8s.io/pod-name` from the Sandbox metadata
2. Attempts `GET pod/<name>` in the same namespace
3. If the pod is not found, returns an error — **it does not clear the annotation or
   attempt to create a new pod**

The controller assumes the annotation always points to a valid pod. There is no fallback
path for the case where the annotated pod has been deleted externally (by a scale-down,
manual deletion, or eviction).

### Reproduction

```bash
# Start with a healthy Sandbox (replicas=1, pod running)
kubectl get sandbox weather-service-1000 -n team1
# Pod is "weather-service-1000", annotation is set

# Scale to 0 — pod is deleted
kubectl patch sandbox weather-service-1000 -n team1 \
  --type merge -p '{"spec":{"replicas":0}}'

# Scale back to 1 — controller should create a new pod
kubectl patch sandbox weather-service-1000 -n team1 \
  --type merge -p '{"spec":{"replicas":1}}'

# Controller logs show repeated errors:
# "pod in annotation get failed: Pod \"weather-service-1000\" not found"
# No new pod is created.

# Fix: clear the stale annotation
kubectl annotate sandbox weather-service-1000 -n team1 \
  agents.x-k8s.io/pod-name-

# Controller immediately creates a new pod.
```

### Race condition with our workaround

Our `restartSandbox` method attempts to clear the `agents.x-k8s.io/pod-name` annotation
between the scale-down and scale-up operations. However, the Sandbox controller runs
concurrently and may re-read the annotation from its informer cache or re-set it during
its own reconciliation loop before our clear takes effect.

The observed sequence:

```
T0: Operator patches replicas=0
T1: Sandbox controller deletes the pod, starts reconciling
T2: Operator clears agents.x-k8s.io/pod-name annotation
T3: Sandbox controller's concurrent reconcile re-reads the Sandbox object,
    sees replicas=0, does nothing — but the informer-cached version still
    has the annotation
T4: Operator patches replicas=1
T5: Sandbox controller reconciles, reads the stale annotation from its
    own update (or from T3's cached read), tries GET pod → fails
T6: Error loop begins
```

Even with `retry.RetryOnConflict`, our annotation-clearing update may succeed on the API
server but lose the race to the Sandbox controller's next write.

### Impact

The Sandbox pod is not recreated after a config-driven restart. The AgentRuntime shows
`Active` with `configuredPods: 1` (because the Sandbox's `spec.replicas` is 1), but no
actual pod exists. The Sandbox controller logs errors continuously.

Manual intervention (clearing the annotation) resolves the issue immediately — the
controller then creates a fresh pod within seconds.

### Possible upstream fixes

1. **Annotation-clearing on pod-not-found:** When the controller sees that the annotated
   pod doesn't exist, it should clear the annotation and fall through to the pod creation
   path rather than returning an error.

2. **Owner reference based discovery:** Instead of (or in addition to) the annotation, the
   controller could discover its pod via `ownerReferences`, which is already set on pods
   created by the Sandbox controller. This is resilient to annotation races.

3. **Pod template drift detection:** The controller should compare the running pod's
   labels/annotations against `spec.podTemplate` and recreate when they diverge. This
   would fix Issue 1 entirely.

### Possible kagenti-operator workarounds

1. **Poll-and-clear loop:** After scale-down, poll the Sandbox annotation in a loop and
   keep clearing it until the pod-name annotation is absent for a stable period, then
   scale up. Adds complexity and latency but is deterministic.

2. **Two-phase restart across reconcile cycles:** On config-hash change, scale to 0 in the
   current reconcile. On the next reconcile (triggered by the Sandbox watch), detect
   `replicas=0` with a "restart pending" annotation, clear the pod-name annotation, and
   scale to 1. This separates the scale-down and annotation-clear into different
   reconciliation windows, reducing the race window.

3. **Accept transient delay:** Keep the current implementation. In clusters where the
   Sandbox controller eventually backs off enough (the retry intervals grow: 1s, 2s, 4s,
   10s, 20s, 40s), the operator's annotation clear may win a subsequent retry. Testing
   showed this does **not** reliably self-heal — the controller re-reads its own stale
   state on each retry.

**Current recommendation:** Option 2 (two-phase restart) is the most robust within the
operator's control. It should be filed as a follow-up after the initial PR merges with the
current implementation and a documented known limitation.

## Issue 3: SandboxClaim Controller Overwrites Operator Config on Sandbox

### Behavior

When a `SandboxClaim` exists for a Sandbox, the SandboxClaim controller copies the
entire `spec.podTemplate` from the `SandboxTemplate` to the `Sandbox` on every
reconciliation. Any annotations or labels the kagenti-operator writes to
`spec.podTemplate.metadata` (e.g., `kagenti.io/config-hash`) are overwritten within
seconds, triggering a continuous reconcile loop:

```
Operator writes config-hash → SandboxClaim controller detects change →
  copies podTemplate from template (wiping config-hash) →
  Operator detects config-hash missing → writes it again → loop
```

### Root cause

This is **designed behavior**, not a bug. The SandboxClaim controller's purpose is to
keep the Sandbox's `spec.podTemplate` in sync with the SandboxTemplate. It performs a
full replacement of `podTemplate`, not a merge. Any fields added by external controllers
are lost on each reconciliation cycle.

### Impact

The kagenti-operator cannot persist any configuration on `spec.podTemplate` when a
SandboxClaim owns the Sandbox. This means:

1. `kagenti.io/config-hash` annotation is repeatedly wiped — the operator loops forever
   trying to reapply it.
2. Any kagenti-managed labels on `spec.podTemplate.metadata.labels` are wiped.
3. The two-phase restart mechanism cannot function because Phase 1 (scale to 0) triggers
   SandboxClaim reconciliation which may reset `spec.replicas` or other fields.

### Reproduction

```bash
# Create AgentRuntime pointing to a Sandbox owned by a SandboxClaim
# Observe operator logs: continuous "Applying config to workload" messages
kubectl logs deployment/kagenti-controller-manager -n kagenti-system --tail=20
# Verify config-hash is never persisted:
kubectl get sandbox weather-service-5000 -n team1 \
  -o jsonpath='{.spec.podTemplate.metadata.annotations}'
# Returns null — annotation is wiped every time
```

### Possible workarounds

1. **Store config-hash on Sandbox CR `metadata.annotations`** (not podTemplate) — the
   SandboxClaim controller doesn't overwrite CR-level metadata. However, any labels or
   annotations the operator needs on the actual *pod* must go through `spec.podTemplate`,
   which is still overwritten.

2. **Write operator config to the SandboxTemplate** — changes propagate down through the
   claim. But config-hash is per-instance (computed from namespace-specific ConfigMaps),
   not per-template. This would require one SandboxTemplate per agent instance, defeating
   the template's purpose.

3. **Upstream change**: Modify the SandboxClaim controller to merge `podTemplate` fields
   instead of replacing them. This is an upstream behavioral change we don't control.

### Resolution

**Bypass SandboxClaim entirely.** The kagenti backend creates `Sandbox` CRs directly
(no SandboxTemplate, no SandboxClaim). This eliminates the third writer and gives the
operator full control over `spec.podTemplate`. See
[ADR: Direct Sandbox Creation vs SandboxClaim](2026-04-30-adr-sandbox-direct-vs-claim.md).

Verified on live cluster: after removing the SandboxClaim (and its ownerReference on the
Sandbox), the operator's config-hash persists cleanly and the two-phase restart works
end-to-end without reconcile loops.

---

## Test Environment

- Kind cluster, single node
- agent-sandbox controller: `v0.3.10` (controller-runtime v0.23.3), upgraded to
  local build with commit `9c6264c` (Issue 2 self-healing fix)
- kagenti-operator: branch `feat/sandbox-workload-support` (two-phase restart)
- Sandbox CRD: `agents.x-k8s.io/v1alpha1`
