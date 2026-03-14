# Kagenti Implementation Design: Consolidated Compositional Agent Platform Architecture

**Authors**: Kagenti Team

**Begin Design Discussion**: 2026-02-20

**Status**: Draft

**Supersedes**: [compositional-agent-platform-design.md](compositional-agent-platform-design.md)

**Checklist**:

- [ ] AgentRuntime CR implementation (identity + observability)
- [ ] AgentCard CR adaptation (selector change)
- [x] Mutating webhook implementation (Pod-level targeting, [PR #183](https://github.com/kagenti/kagenti-extensions/pull/183))
- [x] ConfigMap-based defaults mechanism ([PR #134](https://github.com/kagenti/kagenti-extensions/pull/134))
- [ ] AgentRuntime controller (applies labels, manages lifecycle)
- [ ] Controller consolidation (istiod pattern)
- [ ] Migration tooling
- [ ] Documentation updates
- [ ] Integration tests
- [ ] E2E tests
- [ ] Performance benchmarks

---

## Implementation Horizons

This proposal distinguishes between **short-term** and **long-term** goals. The current design reflects what is practical to implement now, while acknowledging that certain capabilities will be introduced as the platform matures.

## Short-Term (Current Design)

The immediate goal is a working, secure composition model with minimal complexity:

- **CR-triggered injection via controller-managed labels**: AgentRuntime CR is mandatory. The developer deploys a standard workload **without** kagenti labels and creates an AgentRuntime CR with `targetRef` pointing to the workload. The AgentRuntime controller applies `kagenti.io/type: agent|tool` to the Deployment's PodTemplateSpec. This label change triggers a rolling update — new Pods are created, and the admission webhook injects sidecars at Pod CREATE time. Developer workloads stay completely clean. The `objectSelector` on the webhook means only labeled Pods hit the webhook — no cluster-wide performance cost.
- **Explicit opt-out supported**: Developers can suppress injection by adding `kagenti.io/inject: disabled` to the PodTemplateSpec labels.
- **Per-sidecar disable via dedicated labels**: Individual AuthBridge components can be disabled using dedicated labels (`kagenti.io/<sidecar>-inject: "false"`) or feature gates without opting the entire workload out of injection.
- **Webhook targets Pods at CREATE time**: The `MutatingWebhookConfiguration` targets `pods` at `CREATE` — not Deployments or StatefulSets. This follows the proven pattern used by Istio, Linkerd, and Vault Agent Injector. Developer workload manifests remain unmodified in Git (no injected sidecars in the pod template), eliminating GitOps drift with Argo CD and Flux. Sidecars are visible at the pod level (`kubectl get pod -o yaml`) but not in the Deployment.
- **Optional namespace gating**: Platform engineers can restrict injection to opted-in namespaces by requiring a `kagenti-enabled: "true"` label on the namespace. The webhook's `namespaceSelector` enforces this. Off by default (all namespaces eligible), but available as an access control mechanism to prevent uncontrolled SPIFFE provisioning.
- **Webhook with ConfigMap-based defaults**: The webhook reads cluster-level defaults from two ConfigMaps in the `kagenti-webhook-system` namespace:
  - `kagenti-webhook-feature-gates` — controls which AuthBridge components are enabled globally (`globalEnabled`, `envoyProxy`, `spiffeHelper`, `clientRegistration`)
  - `kagenti-webhook-defaults` — provides default container images, proxy port configuration, and per-component resource requests/limits for all injected sidecars

This is the model described in detail throughout this document.

## Long-Term (Future Enhancements)

As the platform matures, the following improvements are planned. These are **not implemented in the current design** and are called out here to provide direction without overcomplicating the immediate implementation.

The short-term design already implements: mandatory CR as source of truth, controller-managed labels, pod-level webhook targeting, and flat ConfigMap defaults. The remaining long-term items focus on sidecar consolidation, advanced config propagation, and tooling maturation. These long-term items may be moved to a separate design document in the future to keep this proposal focused on the current architecture.

---

### 1. ~~Make AgentRuntime CR Mandatory~~ (Moved to Short-Term)

**Status: Part of MVP.** AgentRuntime CR is now mandatory in the short-term design. See Short-Term section above.

---

### 2. ~~Switch Injection Trigger from Label to CR Existence~~ (Moved to Short-Term)

**Status: Part of MVP.** CR-triggered injection via controller-managed labels is now the short-term model. The controller applies `kagenti.io/type` labels to the PodTemplateSpec when an AgentRuntime CR exists, and the webhook injects at Pod CREATE time. See Short-Term section above.

---

### 3. Drop the Layered CRD Defaults Hierarchy

**Current design (long-term plan)**: Replace ConfigMaps with `AgentRuntimeClusterConfig` (cluster-scoped) + `AgentRuntimeConfig` (namespace-scoped) CRDs forming a layered override chain.

**Proposed change**: Do not introduce parent/child or cluster-to-namespace CR layering. Keep defaults in ConfigMaps (or a single, independent cluster-scoped config entity purely for global settings like container image versions).

**Rationale** -- analysis of layered CR failure modes:
1. **Deletion**: Parent CR deleted, children orphaned with broken references -- the child AgentRuntime is not owned by the parent, so it is not cascade-deleted. It won't receive a reconcile event, leaving the agent in an undefined state. Rollback is not possible because the deletion of the parent is not the immediate previous known state change.

2. **Circular dependencies**: If a parent CR is updated to reference a child (or an intermediate is inserted), the state becomes undefined. Depending on controller logic, you either end up with an infinite reconcile loop or incomplete state.

3. **Parent update doesn't trigger child reconcile**: A parent update fires a reconcile for the parent but not for the child. The operator must manually discover and update all dependent children -- a pattern the operator framework is not optimized for.

4. **Parent update breaks child configuration**: The parent knows nothing about the child's specific needs. A config change in the parent cascades to deployments that were never modified, referencing an AgentRuntime that was never touched, which references a parent that got changed with a totally decoupled lifecycle. This is opaque, confusing, and hard to debug.

Additionally, cluster-wide CRDs make multi-tenancy challenging: all tenants share the same cluster-wide CRD, and updating it changes behavior for all tenants.

**Instead, handle composition at manifest-generation time**:

- **Helm values**: Cluster-wide defaults live in `values.yaml`; per-namespace overrides in per-namespace value files; per-agent overrides in the chart's agent template
- **Kustomize**: Base AgentRuntime template with overlays per namespace/agent
- **Templates/examples**: Well-documented AgentRuntime templates in the repo

This keeps the in-cluster model simple (one flat AgentRuntime per workload, no inheritance) and pushes composition complexity to tools designed for it (Helm, Kustomize).

---

### 4. ~~Make `kagenti.io/type` Label Operator-Managed~~ (Moved to Short-Term)

**Status: Part of MVP.** The `type` field is in the AgentRuntime CR spec. The controller applies `kagenti.io/type` to the PodTemplateSpec. See Short-Term section above.

---

### 5. ~~Move Webhook Injection Target from Workload Objects to Pods~~ (Moved to Short-Term)

**Status: Implemented.** Pod-level targeting is now part of the short-term design. The webhook targets `pods` at `CREATE` time, following the Istio/Linkerd/Vault pattern. See Short-Term section above.


### Proposed Model Summary

```
Developer creates:
  1. Deployment/StatefulSet (standard K8s workload, NO Kagenti labels needed)
  2. AgentRuntime CR (with targetRef pointing to the workload)
     - Contains: type (agent|tool), identity config, trace config
     - Reasonable defaults for all fields (most can be omitted)
  3. AgentCard CR (optional, for A2A discovery)

At admission time:
  Webhook sees new workload
    -> queries for AgentRuntime CR with matching targetRef
    -> Found: inject sidecars with CR config (merged with cluster defaults from ConfigMap)
    -> Not found: no injection

Post-admission:
  Operator reconciles AgentRuntime
    -> propagates config updates to running sidecars
  Operator applies kagenti.io/type label to workload (derived from CR)
  Operator reconciles AgentCard
    -> fetches and caches agent capabilities

Defaults:
  Cluster-wide: ConfigMap (or single independent cluster config entity)
  Per-namespace: NOT a CRD -- handled by Helm/Kustomize at deploy time
  Per-workload: AgentRuntime CR (explicit, no inheritance)
```

### Developer Experience: Minimal Case

```yaml
# 1. Standard Deployment (NO kagenti labels — workload stays clean)
apiVersion: apps/v1
kind: Deployment
metadata:
  name: weather-agent
  namespace: team1
spec:
  replicas: 1
  selector:
    matchLabels:
      app: weather-agent
  template:
    metadata:
      labels:
        app: weather-agent
    spec:
      containers:
        - name: agent
          image: weather-agent:latest
          ports:
            - containerPort: 8080
---
# 2. AgentRuntime CR (mandatory — triggers injection + provides config)
apiVersion: kagenti.io/v1alpha1
kind: AgentRuntime
metadata:
  name: weather-agent
  namespace: team1
spec:
  type: agent
  targetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: weather-agent
  # All other fields use cluster defaults — only override what you need
```

**What happens**: The AgentRuntime controller applies `kagenti.io/type: agent` and `kagenti.io/config-hash` to the Deployment's PodTemplateSpec → rolling update creates new Pods → webhook intercepts Pod CREATE → injects AuthBridge sidecars. Everything else (identity, trace, sidecar config) comes from platform ConfigMap defaults. The Helm chart generates both resources from a single set of values.

---

#### Migration Path from Current Design

| Current (Short-Term MVP) | Long-Term | Migration |
|---------|-----------|-----------|
| Mandatory AgentRuntime CR triggers injection via controller-managed labels | Same | Already the target model |
| Controller applies `kagenti.io/type` label to PodTemplateSpec | Same | Already the target model |
| ConfigMap-based platform defaults | ConfigMap defaults + Helm/Kustomize composition | No migration needed |
| Webhook targets Pods at CREATE | Same | Already implemented |

---

#### Alignment with Ecosystem Patterns

| Pattern | Used By | How This Aligns |
|---------|---------|-----------------|
| CR with `targetRef` triggers integration | MCP Gateway, cert-manager, KEDA | AgentRuntime CR with `targetRef` triggers sidecar injection |
| Flat CRs, no inheritance | Most Kubernetes operators | One AgentRuntime per workload, no parent/child CRs |
| Composition via Helm/Kustomize | Industry standard | Defaults and shared config managed outside the cluster |
| Operator manages derived labels | Istio, Argo CD | Operator applies `kagenti.io/type` based on CR spec |


---

## Summary/Abstract

This design proposal consolidates two earlier proposals into a unified architecture for managing AI agent workloads on Kubernetes:

1. The original **Compositional Agent Platform Architecture** ([PR #531](https://github.com/kagenti/kagenti/pull/531)), which proposed replacing the monolithic `Agent` CR with a mutating webhook plus three independent pillar CRs (`TokenExchange`, `AgentTrace`, `AgentCard`).
2. A **counter-proposal** advocating for a single `AgentRuntime` reference CR, removal of workload labels, and controller-based injection instead of a webhook.

This consolidated design retains the strengths of both while resolving their disagreements:

- **CR-triggered injection** — the AgentRuntime CR is mandatory; the controller applies `kagenti.io/type` labels to the PodTemplateSpec, triggering a rolling update; the webhook injects sidecars at Pod CREATE time
- **Developer workloads stay clean** — no kagenti labels in developer manifests; labels are controller-managed
- **TokenExchange and AgentTrace are consolidated** into a single `AgentRuntime` CR — reducing resource count while preserving configurability
- **AgentCard remains a separate CR** — different cardinality model, existing implementation, and distinct concern (discovery vs. runtime)
- **The mutating webhook is retained** for admission-time sidecar injection — security-first, already implemented
- **Platform defaults** (ConfigMaps) minimize per-workload configuration — most AgentRuntime CRs only need `type` and `targetRef`
- **The operator reconciles AgentRuntime CRs** for dynamic reconfiguration — complementary to the webhook, not a replacement

The result is a two-CR model (`AgentRuntime` + `AgentCard`) atop a label-and-webhook foundation, with layered defaults that minimize per-workload configuration.

### Two Distinct Configuration Concerns

This architecture separates configuration into two fundamentally different lifecycle stages that must not be conflated:

**1. Admission-time configuration** — occurs when Pods are created. The AgentRuntime controller applies labels to the PodTemplateSpec, triggering a rolling update. The mutating webhook intercepts each new Pod's CREATE request, reads platform defaults, and injects the AuthBridge sidecars. This is a one-shot operation: the webhook fires, sidecars are injected, and the pod starts. Security is guaranteed — any Pod carrying `kagenti.io/type: agent` (applied by the controller) will have sidecars injected at admission time unless explicitly opted out with `kagenti.io/inject: disabled`.

**2. Reconfiguration of running workloads** — occurs after pods are already running. When defaults or an AgentRuntime CR change, those changes must reach the already-running sidecars without restarting pods. This is handled by the operator, which detects configuration drift and propagates updates to running sidecars (see [Configuration Propagation](#configuration-propagation-open-design)). Note that some changes — such as modifications to injected sidecar images or init container configuration — inherently require a pod restart.

These two concerns are handled by different components (webhook vs. operator), operate at different points in the workload lifecycle, and have different latency and consistency requirements. Design decisions in one stage should not be conflated with the other.

### Architecture at a Glance

```
Developer Creates Standard Deployment (NO kagenti labels)
  + Creates AgentRuntime CR with targetRef → Deployment
        ↓
AgentRuntime Controller Reconciles
  • Applies kagenti.io/type: agent label to PodTemplateSpec
  • Applies kagenti.io/config-hash annotation (CR + defaults)
  • PodTemplateSpec change triggers rolling update
        ↓
Webhook Intercepts Pod CREATE (pods carry controller-applied labels)
  • Guards against non-Pod resources (defense-in-depth)
  • Checks idempotency (skips if already injected)
  • Injects AuthBridge sidecars:
    - proxy-init (init container — network setup)
    - spiffe-helper (identity)
    - client-registration (IdP integration)
    - envoy-proxy (outbound token exchange)
        ↓
Agent Pod Running with Secure Identity
  • Identity and auth fully configured from platform defaults
  • Sidecars reconfigure dynamically where possible
  • Pod restarts may be required for some changes (e.g. sidecar image updates)
        ↓
Optional: Developer Creates AgentCard CR
  • AgentCard → enable A2A discovery
  • Fetches /.well-known/agent.json from agent endpoints
```

---

## Background

### Prior Proposals

**Original Proposal (Three Pillars)**: Proposed a mutating webhook triggered by an explicit `kagenti.io/inject: enabled` label, plus three independent pillar CRs (`TokenExchange`, `AgentTrace`, `AgentCard`). Strong on composition-over-inheritance thesis, proven ecosystem analysis, and working webhook implementation. Weakness: four objects per fully-configured agent.

**Counter-Proposal (AgentRuntime)**: Proposed a single `AgentRuntime` CR with `workloadRef`, eliminating labels and the webhook in favor of controller-based injection. Strong on auditability and single-resource-per-agent simplicity. Weaknesses: loses admission-time security guarantees, creates race conditions during injection, requires reimplementing a working webhook.

### Key Disagreements Resolved

| Topic | Original | Counter-Proposal | This Design |
|-------|----------|-------------------|-------------|
| Labels | Required on workload for injection | Remove entirely | **Controller-managed** — AgentRuntime CR triggers controller to apply `kagenti.io/type` label; `kagenti.io/inject: disabled` to opt out |
| Injection | Mutating webhook | Controller patching | **Webhook** (admission-time, security-first) |
| CR count | 3 pillar CRs | 1 unified CR | **2 CRs**: AgentRuntime + AgentCard |
| Defaults | Per-CR defaults | CR sections optional | **Layered**: cluster → namespace → CR |
| AgentCard | Separate CR | Fold into AgentRuntime | **Separate CR** (different cardinality) |
| Workload targeting | `targetRef` + label selectors | `workloadRef` only | **`targetRef`** (duck typing) + label selectors for AgentCard |

### Motivation

The core thesis from the original proposal remains: **higher-level Kubernetes abstractions that replace standard workload types consistently fail, while composition-based approaches that augment existing workloads succeed**. This design extends that principle with two refinements:

1. **The AgentRuntime CR is the single source of truth.** Every agent has an AgentRuntime CR that triggers injection and provides configuration. Most CRs are minimal — just `type` and `targetRef` — with platform defaults providing everything else.
2. **Identity and observability are tightly coupled to the same workload lifecycle.** They share the same `targetRef`, the same configuration delivery mechanism, and are almost always co-configured. Separate CRs add object count without adding flexibility.

---

## User/User Story

**Platform Engineer**:

- As a platform engineer, I want any workload a developer classifies as an agent to automatically receive identity infrastructure at admission time — without requiring developers to understand or configure the injection mechanism
- As a platform engineer, I want to set cluster-wide and namespace-level defaults for identity and observability so that agents work securely out of the box without per-workload configuration
- As a platform engineer, I want to audit agent runtime configuration with `kubectl get agentruntime -A`

**Application Developer**:

- As a developer, I want to deploy my AI agent using a standard Kubernetes Deployment and have identity infrastructure injected automatically by creating an AgentRuntime CR — no labels needed in my workload manifest
- As a developer, I want to classify my workload as an agent or tool by specifying `type` in the AgentRuntime CR spec, so the Kagenti UI displays it correctly and the controller applies the appropriate labels
- As a developer, I want to override the platform defaults for my specific workload by specifying overrides in the AgentRuntime CR when the platform defaults don't fit my agent's requirements
- As a developer, I want to expose my agent's capabilities through a standard discovery mechanism by creating an AgentCard CR so other agents can find and invoke it

**Operations Engineer**:

- As an operations engineer, I want comprehensive observability into agent execution configured through defaults that I don't need to repeat per workload
- As an operations engineer, I want to remove Kagenti from a workload without disrupting the workload itself

---

## Goals

1. **Compose with existing Kubernetes workload types** — Never require users to abandon Deployment, StatefulSet, or Job
2. **Minimize per-workload configuration** — An AgentRuntime CR with `targetRef` plus platform defaults are all most agents need
3. **Retain labels for workload classification** — The Kagenti UI and ecosystem tooling rely on controller-managed `kagenti.io/type` labels to identify agents and tools
4. **Provide workload-scoped admission-time identity injection** — Pods with controller-applied `kagenti.io/type` labels automatically receive identity infrastructure at admission time; developers opt out with `kagenti.io/inject: disabled` if needed
5. **Consolidate related concerns** — Identity and observability in one CR; discovery separate
6. **Support dynamic reconfiguration** — Configuration changes without pod restarts where possible; some changes (e.g., modifications to injected sidecar images or init container configuration) may require a pod restart to take effect


---

## Non-Goals

1. **Making labels developer-owned** — `kagenti.io/type` is managed by the AgentRuntime controller, not by developers. The AgentRuntime CR is the developer's declaration
2. **Replacing the mutating webhook with controller-based injection** — The webhook provides security guarantees that controller patching cannot
3. **Folding AgentCard into AgentRuntime** — Different cardinality model, existing implementation, distinct concern
4. **Building another workload orchestrator** — Users keep their existing orchestration tools
5. **Duplicating existing portfolio functionality** — Secret managers, service meshes, and observability stacks continue to be used

---

## Proposal

### The Two-Layer Architecture (Refined)

```
┌──────────────────────────────────────────────────────────────┐
│ LAYER 1: CR-Triggered Identity Infrastructure                │
│──────────────────────────────────────────────────────────────│
│ Trigger: AgentRuntime CR with targetRef → workload           │
│  → Controller applies kagenti.io/type label to PodTemplate  │
│  → Rolling update creates new Pods with labels               │
│  → Webhook intercepts Pod CREATE, injects sidecars           │
│  (opt-out via kagenti.io/inject: disabled)                   │
│                                                              │
│ • Webhook targets Pods at CREATE (not Deployments)           │
│ • Reads platform defaults from ConfigMaps                    │
│ • Injects AuthBridge sidecars with resolved config           │
│ • Agent runs with secure identity immediately                │
│ • Developer workloads stay completely clean                   │
└──────────────────────────────────────────────────────────────┘
                            ↓
┌──────────────────────────────────────────────────────────────┐
│ LAYER 2: Discovery                                           │
│──────────────────────────────────────────────────────────────│
│ • AgentCard CR: Discover agent capabilities                  │
│   - Uses label selector to match pods                        │
│   - Fetches /.well-known/agent.json from agent endpoints     │
│   - Caches cards in CR status                                │
└──────────────────────────────────────────────────────────────┘
```

### Labels: Controller-Managed Classification and Injection Trigger

Labels on workloads are **managed by the AgentRuntime controller**, not set by developers directly. The controller applies labels to the PodTemplateSpec based on the AgentRuntime CR spec:

| Label | Level | Purpose | Set By |
|-------|-------|---------|--------|
| `kagenti.io/type: agent` or `tool` | PodTemplateSpec | **Controller-managed** — classifies the workload and triggers AuthBridge injection via the webhook's `objectSelector` | AgentRuntime controller |
| `kagenti.io/config-hash` | PodTemplateSpec | **Controller-managed** — hash of resolved configuration (CR + platform defaults); triggers rolling updates on config change | AgentRuntime controller |
| `kagenti.io/inject: disabled` | PodTemplateSpec | Optional — developer can suppress injection while keeping type classification | Developer |

#### CR-Triggered Injection (Primary Model)

The **primary mechanism** for AuthBridge sidecar injection is the AgentRuntime CR. The developer deploys a standard workload with no kagenti labels:

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: weather-agent
  labels:
    app: weather-agent
    # No kagenti labels — workload manifest stays clean
---
apiVersion: kagenti.io/v1alpha1
kind: AgentRuntime
metadata:
  name: weather-agent
  namespace: team1
spec:
  type: agent
  targetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: weather-agent
```

The AgentRuntime controller sees the CR, applies `kagenti.io/type: agent` and `kagenti.io/config-hash` to the Deployment's PodTemplateSpec. This triggers a rolling update. New Pods carry the labels and match the webhook's `objectSelector`, so the webhook injects sidecars at CREATE time.

#### Config Hash — One Mechanism for Create, Update, and Delete

The controller maintains a `kagenti.io/config-hash` annotation on the PodTemplateSpec, computed from the resolved configuration (AgentRuntime CR merged with platform defaults). Any configuration change updates the hash, triggering a rolling update:

| Event | What controller does | Rolling update? | Webhook behavior |
|-------|---------------------|-----------------|-----------------|
| **AgentRuntime created** | Adds label + config-hash | Yes | Injects with CR config |
| **AgentRuntime updated** | Updates config-hash | Yes | Injects with updated config |
| **AgentRuntime deleted** | Finalizer fires: preserves label, updates config-hash to defaults-only | Yes | Injects with platform defaults |

On deletion, the AgentRuntime CR carries a finalizer (`kagenti.io/cleanup`). The controller preserves the `kagenti.io/type` label, updates the config-hash to reflect defaults only, then removes the finalizer. The workload stays classified as an agent and continues to receive identity infrastructure — just with default configuration.

#### Opting Out of Injection

A developer can suppress injection while keeping type classification by adding `kagenti.io/inject: disabled` to the PodTemplateSpec:

```yaml
labels:
  kagenti.io/type: agent
  kagenti.io/inject: disabled   # Classified as agent but sidecars not injected
```

This is useful during migration, testing, or for workloads that need the type classification for UI display but are not yet ready for full AuthBridge injection.

#### Why the CR is the Source of Truth

The AgentRuntime CR resolves the ownership ambiguity of "who sets the label?":

- **Developer workloads stay clean** — no kagenti labels required from developers
- **AgentRuntime CR is the single source of truth** — for both injection trigger and configuration
- **Admission-time security guarantee** — sidecars are injected at Pod CREATE, no race window
- **Auditability** — `kubectl get agentruntime -A` shows all enrolled workloads
- **GitOps compatible** — the webhook targets Pods (not Deployments), so no drift in the Deployment manifest stored in Git. The controller-applied labels can be excluded from drift detection via Argo CD's `ignoreDifferences`

### Layered Defaults

Every agent has an AgentRuntime CR, but most only specify `type` and `targetRef` — platform defaults provide everything else. Defaults flow from cluster ConfigMaps to per-workload CR overrides:

```
┌─────────────────────────────────────────────────────┐
│ Cluster Defaults                                     │
│ (kagenti-system)                                     │
│                                                      │
│ • SPIFFE trust domain: cluster.local                 │
│ • IdP: keycloak.kagenti-system.svc:8080              │
│ • OTEL endpoint: otel-collector.observability:4317   │
│ • Inbound auth: enabled, port 8080 → 8081            │
│ • Outbound proxy: port 15123, token exchange enabled │
└──────────────────────┬──────────────────────────────┘
                       ↓ (namespace-level overrides)
┌─────────────────────────────────────────────────────┐
│ Namespace Defaults                                   │
│ (in agent namespace)                                 │
│                                                      │
│ • Override trust domain for this namespace            │
│ • Override IdP realm                                 │
│ • Override OTEL endpoint                             │
│ • Override sampling rate                             │
└──────────────────────┬──────────────────────────────┘
                       ↓ (AgentRuntime CR overrides)
┌─────────────────────────────────────────────────────┐
│ Per-Workload Override                                │
│ AgentRuntime CR (optional)                           │
│                                                      │
│ • Override specific fields for this workload         │
│ • Only needed when defaults don't fit                │
└─────────────────────────────────────────────────────┘
```

**Resolution order**: The webhook merges configuration in order: cluster defaults → namespace defaults → AgentRuntime CR (if exists). The merged configuration is used at injection time to configure sidecars. When defaults or CRs change post-injection, the operator propagates updates to running sidecars (see [Configuration Propagation](#configuration-propagation-open-design) below).

**Default Values** (representative, not exhaustive):

| Category | Setting | Default |
|----------|---------|---------|
| Identity | SPIFFE trust domain | `cluster.local` |
| Identity | SPIFFE socket path | `unix:///run/spire/agent-sockets/agent.sock` |
| Identity | IdP provider | Keycloak |
| Identity | IdP URL | `http://keycloak.kagenti-system.svc:8080` |
| Identity | IdP realm | `default` |
| Identity | Inbound auth port | `8080` → `8081` |
| Identity | Outbound proxy port | `15123` |
| Identity | Token exchange default audience | `downstream-service` |
| Trace | OTEL endpoint | `otel-collector.observability:4317` |
| Trace | OTEL protocol | `grpc` |
| Trace | Sampling type | `probabilistic` |
| Trace | Sampling rate | `0.1` |

Namespace-level defaults override cluster defaults for any setting. The specific storage mechanism for defaults (ConfigMap, CRD, or other) is an implementation detail to be determined.

### AgentRuntime CR

**Purpose**: Override layered defaults for a specific workload's identity and observability configuration.

**Owner**: The developer. Platform engineers set the defaults; developers create an AgentRuntime CR when those defaults need to be adjusted for a specific workload.

**When to create one**: Only when cluster/namespace defaults don't fit a specific workload. Most agents won't need this.

**API Structure**:

```yaml
apiVersion: kagenti.io/v1alpha1
kind: AgentRuntime
metadata:
  name: weather-agent-runtime
  namespace: default
spec:
  # Type classification — agent or tool
  type: agent

  # Reference to the target workload
  targetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: weather-agent

  # Identity configuration (overrides platform defaults)
  identity:
    spiffe:
      trustDomain: "prod.cluster.local"

    clientRegistration:
      provider: keycloak
      keycloak:
        url: "http://keycloak-prod.auth.svc:8080"
        realm: "production"
        adminCredentialsSecret: "keycloak-prod-admin"

  # Observability configuration (overrides platform defaults)
  trace:
    endpoint: "otel-collector.observability:4317"
    protocol: grpc

    sampling:
      type: probabilistic
      rate: 0.5

status:
  phase: Active
  message: "Runtime configured"
  configuredPods: 2
  identity:
    spiffeEnabled: true
    idpRegistered: true
```

> **v1alpha1 scope**: The AgentRuntime CRD is intentionally scoped to `targetRef`, `identity` (SPIFFE + client registration basics), and `trace` (OTEL endpoint + sampling). The following are **deferred to future versions**: MLflow integration, Prometheus metrics, GenAI capture, destination rules, per-exporter compression, inbound/outbound port overrides. This keeps the validation surface small and the CRD well within etcd limits.

**Controller Behavior**:
1. Watches AgentRuntime CRs for create/update/delete
2. Resolves `targetRef` to find workload (duck typing — works with Deployment, StatefulSet, Job, CronJob)
3. Merges CR spec with cluster/namespace defaults
4. Propagates merged configuration to running sidecars (see [Configuration Propagation](#configuration-propagation-open-design))
5. Updates CR status with identity and observability state

### AgentCard CR (Unchanged)

AgentCard remains a separate CR. It is reproduced here for completeness but is not modified from the original proposal.

**Why separate**:
- **Different cardinality**: AgentCard uses a label selector (can match multiple pods across workloads). AgentRuntime uses `targetRef` (1:1 with a workload). Forcing these into one CR would require supporting both targeting models in one resource.
- **Different concern**: Discovery ("what can agents do") is distinct from runtime ("how are agents configured"). The name `AgentRuntime` does not naturally encompass capability discovery.
- **Existing implementation**: Code exists and works. Refactoring it into a subsection of another CR is churn without benefit.

> **Future consideration — multi-agent-per-pod and Route-based keying**: When multiple A2A agents share a single pod, they also share a single SPIFFE identity. In this scenario, Route (not Pod) may be the more natural key for AgentCard creation, since each agent has its own route/endpoint but not its own pod or identity. The current label-selector model does not address this multi-agent-per-pod case. This does not need to be solved now but should be revisited when multi-agent pods become a supported pattern.

**API Structure**:

```yaml
apiVersion: kagenti.io/v1alpha1
kind: AgentCard
metadata:
  name: weather-agent-card
  namespace: default
spec:
  syncPeriod: "30s"
  selector:
    matchLabels:
      app: weather-agent
      kagenti.io/type: agent
status:
  protocol: "a2a"
  lastSyncTime: "2026-01-21T10:30:00Z"
  conditions:
  - type: Synced
    status: "True"
    lastTransitionTime: "2026-01-21T10:30:00Z"
    reason: SyncSuccess
    message: "Agent card successfully fetched"
  card:
    name: "Weather Intelligence Agent"
    description: "Provides weather forecasts and current conditions"
    version: "2.1.0"
    url: "http://weather-agent.default.svc.cluster.local:8080"
    capabilities:
      streaming: true
      pushNotifications: false
    defaultInputModes:
    - "application/json"
    - "text/plain"
    defaultOutputModes:
    - "application/json"
    skills:
    - name: "get_forecast"
      description: "Get weather forecast for a location"
      inputModes:
      - "application/json"
      outputModes:
      - "application/json"
      parameters:
      - name: "location"
        type: "string"
        description: "City name or coordinates (lat,lon)"
        required: true
      - name: "days"
        type: "number"
        description: "Number of days to forecast (1-14)"
        required: false
        default: "7"
```

### Cardinality: 1:1 Between AgentRuntime and Workload

The `targetRef` pattern establishes a 1:1 relationship between an AgentRuntime CR and a workload. This is intentional and should not be relaxed.

**Why 1:1 is correct**:
- **Auditability**: `kubectl get agentruntime -A` shows exactly which workloads have custom configuration
- **Proven pattern**: KEDA ScaledObject, Flagger Canary, and cert-manager Certificate all use 1:1 `targetRef`
- **Clear ownership**: One CR configures one workload — no ambiguity about which configuration applies

**Addressing the fleet concern**: The counter-proposal implicitly raised the concern that 50 identical agents would need 50 identical AgentRuntime CRs. Layered defaults solve this:

| Scenario | What the developer creates | AgentRuntime CR needed? |
|----------|---------------------------|------------------------|
| Standard agent | Deployment + AgentRuntime CR (type + targetRef) | Yes (minimal) |
| Agent with custom IdP realm | Deployment + AgentRuntime CR (with identity overrides) | Yes |
| Fleet of 50 identical agents | 50 Deployments + 50 AgentRuntime CRs (minimal, Helm-generated) | Yes (minimal, templated) |
| Workload without AgentRuntime CR | No injection occurs — no labels applied | N/A |
| Agent that should not be injected | Deployment + `kagenti.io/inject: disabled` on PodTemplateSpec | N/A |

**The 1:1 constraint is not a burden on developers** because most AgentRuntime CRs are minimal (just `type` and `targetRef`). Platform defaults handle the common case. When defaults do not fit a specific workload, the developer adds override fields to the AgentRuntime CR — this is a developer-owned resource, not a platform engineer concern. For fleets, Helm charts template the AgentRuntime CRs from shared values.

### Mutating Webhook Design

The mutating webhook from the original proposal is retained. While the counter-proposal's suggestion to use controller-based injection raises valid points worth acknowledging, the webhook approach remains the preferred path for the following reasons:

**Why keep the webhook**:

1. **Security guarantee**: The webhook injects at admission time. A pod is **never created** without identity sidecars. Controller-based patching introduces a race window where pods run without identity infrastructure — unacceptable for a security-first platform.
2. **Already implemented**: The webhook exists and functions. Replacing it is a rewrite with no functional benefit.
3. **Proven pattern**: Every major service mesh (Istio, Linkerd) and secrets manager (Vault Agent) uses admission-time injection for the same security reasons.
4. **Complementary to the operator**: The webhook handles injection. The operator handles reconfiguration. These are different concerns at different lifecycle stages.

**Webhook Configuration**:

The webhook targets `pods` at `CREATE` time — not workload objects like Deployments or StatefulSets. This follows the proven pattern used by Istio, Linkerd, and Vault Agent Injector. Developer workload manifests remain unmodified in Git, eliminating GitOps drift.

The `objectSelector` gates on `kagenti.io/type` (the label applied by the AgentRuntime controller) and excludes `kagenti.io/inject: disabled`. An optional `namespaceSelector` restricts injection to namespaces labeled `kagenti-enabled: "true"`.

```yaml
apiVersion: admissionregistration.k8s.io/v1
kind: MutatingWebhookConfiguration
metadata:
  name: kagenti-injector
webhooks:
- name: inject.kagenti.io
  clientConfig:
    service:
      name: kagenti-webhook
      namespace: kagenti-webhook-system
      path: /mutate-workloads-authbridge
    caBundle: ${CA_BUNDLE}
  rules:
  - operations: ["CREATE"]
    apiGroups: [""]
    apiVersions: ["v1"]
    resources: ["pods"]
  namespaceSelector:
    matchExpressions:
      # Exclude system namespaces
      - key: kubernetes.io/metadata.name
        operator: NotIn
        values:
          - kube-system
          - kube-public
          - kube-node-lease
          - kagenti-webhook-system
    matchLabels:
      kagenti-enabled: "true"       # Optional namespace gating
  objectSelector:
    matchExpressions:
    - key: kagenti.io/type
      operator: In
      values: ["agent", "tool"]
    - key: kagenti.io/inject
      operator: NotIn
      values: ["disabled"]          # Honours explicit opt-out
  admissionReviewVersions: ["v1"]
  sideEffects: None
  timeoutSeconds: 10
  failurePolicy: Fail
  reinvocationPolicy: IfNeeded
```

> **Note**: The webhook's `objectSelector` gates on `kagenti.io/type` (applied by the AgentRuntime controller) and excludes `kagenti.io/inject: disabled`. Tool injection requires the `injectTools` feature gate in `kagenti-webhook-feature-gates` to be enabled (default: disabled). The `namespaceSelector` optionally restricts injection to namespaces labeled `kagenti-enabled: "true"`.

**Webhook Injection Decision Logic**:

```
Is this a Pod CREATE request?
  ├─ NO  → Allow (not a Pod)
  └─ YES → Does Pod carry kagenti.io/type: agent or tool?
             ├─ NO  → No injection (objectSelector excludes this Pod)
             └─ YES → Is kagenti.io/inject: disabled present?
                        ├─ YES → No injection (objectSelector excludes this Pod)
                        └─ NO  → Are sidecars already injected? (idempotency check)
                                   ├─ YES → Allow (already injected)
                                   └─ NO  → Is globalEnabled feature gate true?
                                              ├─ NO  → No injection (kill switch)
                                              └─ YES → Inject sidecars (per-sidecar gates apply)
```

**Webhook Behavior**:

1. Intercepts Pod CREATE when the Pod carries `kagenti.io/type: agent` (or `tool` with feature gate) and does **not** carry `kagenti.io/inject: disabled`
2. Guards against non-Pod resources (defense-in-depth against stale webhook configs)
3. Derives workload name from `GenerateName` (trims trailing `-`) for ServiceAccount and client-registration naming
4. Checks idempotency — skips if sidecars are already present
5. Reads cluster defaults from ConfigMaps in `kagenti-webhook-system`
6. Injects AuthBridge sidecars with resolved configuration
7. Returns a JSON patch with the mutated Pod spec

**Kubernetes Admission Mechanics**:

Adding a label to a PodTemplateSpec within a Deployment triggers admission control at two levels:

1. **Deployment admission**: The API request to update the Deployment is intercepted by admission webhooks configured for `deployments`. The Kagenti webhook does NOT target Deployments — it ignores this event.
2. **Pod admission**: The PodTemplateSpec change triggers a rolling update — as the Deployment controller creates new Pods, each Pod creation request is intercepted by admission webhooks configured for `pods`. The Kagenti webhook targets this event, injecting sidecars into the Pod at CREATE time.

This two-step mechanism is what makes CR-triggered injection work: the controller modifies the PodTemplateSpec (step 1), Kubernetes creates new Pods (step 2), and the webhook injects sidecars into those Pods. The developer's Deployment manifest in Git is never modified by the webhook — only the ephemeral Pod objects receive injected sidecars.

**GitOps Compatibility (Argo CD)**:

The controller modifies the Deployment's PodTemplateSpec (adding labels and config-hash annotation). Argo CD will detect this as drift. Mitigation via server-side diff (Argo CD v2.5+) or `ignoreDifferences`:

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
spec:
  ignoreDifferences:
    - group: apps
      kind: Deployment
      jqPathExpressions:
        - .spec.template.metadata.labels."kagenti.io/type"
        - .spec.template.metadata.annotations."kagenti.io/config-hash"
```

This is the same approach used for Istio sidecar injection labels.

**Injected Components (Current)**:

| Component | Type | Purpose |
|-----------|------|---------|
| `proxy-init` | Init Container | Sets up iptables for traffic interception |
| `spiffe-helper` | Sidecar | Manages SPIFFE workload identity |
| `client-registration` | Sidecar | Registers agent with identity provider |
| `envoy-proxy` | Sidecar | Intercepts outbound traffic, performs token exchange |

> **Note: AuthBridge Sidecar Consolidation** — The current AuthBridge implementation uses multiple sidecars as listed above. The Kagenti team plans to consolidate these into fewer containers in the near term. The current multi-sidecar design reflects the initial implementation where each concern was developed independently. Consolidation will reduce per-pod resource overhead, simplify configuration propagation (fewer processes to update), and reduce pod startup latency. The architecture described in this proposal is designed to work with both the current multi-sidecar layout and the future consolidated form — the webhook injects whatever the current AuthBridge implementation requires, and the number of injected containers is an implementation detail transparent to the developer.

### Controller Architecture

The webhook and the operator run as independent pods. The webhook handles admission-time injection; the operator handles post-admission reconciliation.

```
┌────────────────────────────────────────────────────────┐
│ Kagenti Webhook Pod (kagenti-webhook-system)           │
│                                                        │
│  ┌──────────────────────────────────────────────────┐  │
│  │ Webhook Server                                   │  │
│  │  • Handles mutation requests at admission time   │  │
│  │  • Injects AuthBridge sidecars                   │  │
│  │  • Validates AgentRuntime CRs                    │  │
│  └──────────────────────────────────────────────────┘  │
│                                                        │
│  ┌──────────────────────────────────────────────────┐  │
│  │ Defaults Watcher                                 │  │
│  │  • Watches cluster/namespace defaults (ConfigMaps│  │
│  │  • Reloads defaults when ConfigMaps change       │  │
│  └──────────────────────────────────────────────────┘  │
└────────────────────────────────────────────────────────┘

┌────────────────────────────────────────────────────────┐
│ Kagenti Operator Pod                                   │
│                                                        │
│  ┌──────────────────────────────────────────────────┐  │
│  │ Controller Manager                               │  │
│  │                                                  │  │
│  │  • AgentRuntime Reconciler                       │  │
│  │    - Resolves targetRef (duck typing)            │  │
│  │    - Merges with layered defaults                │  │
│  │    - Propagates config to running sidecars       │  │
│  │    - Updates CR status                           │  │
│  │                                                  │  │
│  │  • AgentCard Reconciler                          │  │
│  │    - Discovers agent capabilities via selector   │  │
│  │    - Fetches /.well-known/agent.json             │  │
│  │    - Caches cards in CR status                   │  │
│  │                                                  │  │
│  │  • Shared Utilities                              │  │
│  │    - targetRef resolver (duck typing)            │  │
│  │    - Configuration propagation                   │  │
│  │    - Status updater                              │  │
│  │    - Defaults merger                             │  │
│  └──────────────────────────────────────────────────┘  │
└────────────────────────────────────────────────────────┘
```

### Configuration Propagation (Open Design)

A key requirement of the architecture is that configuration changes (whether to cluster/namespace defaults or to an AgentRuntime CR) must propagate efficiently to running identity, security, and observability sidecars **without requiring pod restarts where possible**. Some changes — such as modifications to sidecar container images or init container configuration — inherently require a pod restart.

The specific mechanism for this propagation is still under discussion. The candidates include:

| Mechanism | Pros | Cons |
|-----------|------|------|
| **xDS (Envoy discovery service)** | Sub-second propagation; native to Envoy proxy; proven at scale by Istio/Envoy ecosystem; supports streaming updates | Requires xDS control plane; only directly applicable to Envoy-based sidecars |
| **ConfigMap volume mounts** | Simple; native Kubernetes; no additional infrastructure | Kubelet sync period introduces lag (default ~60s, configurable); not suitable for latency-sensitive security updates |
| **gRPC streaming from operator** | Low latency; flexible; works for all sidecar types | Custom protocol; additional complexity |
| **Watch-based (sidecar watches K8s API)** | Real-time updates; no intermediary | Increases API server load at scale; requires RBAC for each sidecar |

**Current assessment**: For the Envoy proxy sidecar (which handles outbound token exchange and traffic interception), **xDS is the leading candidate** — it is Envoy's native configuration interface and provides the low-latency updates required for security-sensitive configuration like token exchange rules and destination policies.

> **Open gap: Non-Envoy sidecar configuration propagation.** The mechanism for propagating configuration to non-Envoy sidecars (spiffe-helper, client-registration) is not yet defined. These sidecars currently read configuration from environment variables and mounted ConfigMaps at startup. Dynamic reconfiguration without pod restart is an unsolved problem for these components. This gap should be tracked explicitly and addressed in a future design iteration.

**Requirements regardless of mechanism**:
- Configuration changes should reach running sidecars without pod restarts where possible; changes to sidecar images or init containers require a pod restart
- Identity and security configuration updates must propagate with low latency (target: seconds, not minutes)
- Observability configuration updates are less latency-sensitive but should avoid pod restarts where possible
- The operator must be able to verify that propagation has completed and report status

This is an active area of design. The choice of propagation mechanism will be finalized during Phase 1 implementation.

### Agent Code Requirements

#### Telemetry Instrumentation

It is the developer's responsibility to instrument their agent code with the OpenTelemetry SDK.

**Configuration Source**: Configuration is provided to agent code by the platform (delivery mechanism TBD — see [Configuration Propagation](#configuration-propagation-open-design)). Agent code reads OTEL configuration from environment variables or a configuration file provided at a well-known path.

**Minimal Example**:

```python
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
import os

def setup_telemetry():
    # OTEL endpoint provided by Kagenti platform via environment or config
    endpoint = os.getenv('OTEL_EXPORTER_OTLP_ENDPOINT',
                         'otel-collector.observability:4317')

    provider = TracerProvider()
    exporter = OTLPSpanExporter(endpoint=endpoint, insecure=True)
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)

    return trace.get_tracer(__name__)

tracer = setup_telemetry()

with tracer.start_as_current_span("tool_execution"):
    result = execute_tool()
```

#### Agent Card Endpoint

Agent code must expose a capability card for the AgentCard controller.

**Endpoint**: `/.well-known/agent.json` on agent port (8081)

**Minimal Example**:

```python
from flask import Flask, jsonify

app = Flask(__name__)

@app.route('/.well-known/agent.json')
def agent_card():
    return jsonify({
        "name": "Weather Intelligence Agent",
        "version": "2.1.0",
        "capabilities": {
            "streaming": True,
            "batchProcessing": True
        },
        "skills": [
            {
                "name": "get_forecast",
                "description": "Get weather forecast"
            }
        ]
    })

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8081)
```

---



### After (Composition — Custom Configuration Needed)

```yaml
# Standard Kubernetes Deployment — NO kagenti labels (workload stays clean)
apiVersion: apps/v1
kind: Deployment
metadata:
  name: weather-agent
  namespace: team1
  labels:
    app: weather-agent
spec:
  replicas: 1
  selector:
    matchLabels:
      app: weather-agent
  template:
    metadata:
      labels:
        app: weather-agent
    spec:
      containers:
      - name: agent
        image: "ghcr.io/example/weather-agent:v1"
        ports:
        - containerPort: 8081
---
# AgentRuntime — mandatory, triggers injection + provides config overrides
apiVersion: kagenti.io/v1alpha1
kind: AgentRuntime
metadata:
  name: weather-agent-runtime
  namespace: team1
spec:
  type: agent
  targetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: weather-agent
  identity:
    spiffe:
      trustDomain: "prod.cluster.local"
    clientRegistration:
      keycloak:
        realm: "production"
  trace:
    sampling:
      rate: 1.0  # full sampling for this agent
---
# AgentCard — optional, for discovery
apiVersion: kagenti.io/v1alpha1
kind: AgentCard
metadata:
  name: weather-agent-card
spec:
  selector:
    matchLabels:
      app: weather-agent
  syncPeriod: 30s
```

---

## Impacts / Key Questions

### Pattern Comparison

| Aspect | Inheritance (Agent CR) | Original (3 Pillar CRs) | Counter (AgentRuntime only) | This Design |
|--------|----------------------|-------------------------|---------------------------|-------------|
| Objects per agent | 1 | 1-4 | 2 | 2-3 (AgentRuntime + workload, optional AgentCard) |
| Labels needed | No | Yes (injection + type) | No | None on developer workloads (controller-managed) |
| Webhook | No | Yes | No | Yes |
| Admission-time security | No | Yes | No (race window) | Yes |
| Workload modification | Yes (replaced) | Yes (injection label) | No | None (controller applies labels) |
| Per-workload CR required | Always | Optional | Always | Always (AgentRuntime) |
| Auditability | `kubectl get agent` | Mixed | `kubectl get agentruntime` | `kubectl get agentruntime -A` |
| Fleet configuration | N/A | Per-workload CRs | Per-workload CRs | Layered defaults |

### Open Questions

1. **Defaults storage mechanism**: How should cluster and namespace defaults be stored and managed? (ConfigMap, dedicated CRD, or other). Current implementation uses ConfigMaps.
2. **Configuration propagation mechanism**: How should configuration updates reach running sidecars? (See [Configuration Propagation](#configuration-propagation-open-design))
3. **AgentRuntime CR lifecycle**: ~~Should deleting an AgentRuntime CR revert to defaults or remove configuration entirely?~~ **Resolved**: Deletion reverts to platform defaults. The controller uses a finalizer to preserve the `kagenti.io/type` label and update the config-hash to defaults-only, triggering a rolling update with default configuration.
4. **~~Injection trigger mechanism~~**: **Resolved**: CR-triggered injection via controller-managed labels. The AgentRuntime CR is mandatory, the controller applies `kagenti.io/type` labels, and the webhook injects at Pod CREATE time. See Short-Term section and [Labels: Controller-Managed Classification](#labels-controller-managed-classification-and-injection-trigger).

### Pros

1. **Clear developer intent**: Developers declare workload type via AgentRuntime CR — injection follows automatically, with explicit opt-out available via `kagenti.io/inject: disabled`
2. **Secure by default**: Webhook ensures agents never run without identity infrastructure
3. **Platform engineer friendly**: Defaults set once, override only when needed
4. **Low object count**: 1 object (Deployment) for common case, up to 3 for full customization
5. **Proven patterns**: Webhook injection, duck-typed targetRef, layered defaults
6. **Clean separation**: AgentRuntime for runtime config, AgentCard for discovery
7. **Incremental adoption**: AgentRuntime CR → platform defaults → AgentCard, each step builds on the previous
8. **Multi-workload support**: Works with any controller that creates Pods (Deployments, StatefulSets, Jobs, CronJobs)

### Cons

1. **AgentRuntime CR required**: Every workload needing injection must have an AgentRuntime CR. Mitigated by tooling: Helm charts, CLI, and UI generate CRs automatically
2. **Webhook dependency**: If webhook is unavailable, workload creation blocks (mitigated by replicas)
3. **Defaults complexity**: Three-layer merge adds implementation complexity
4. **Two CRs still needed for full functionality**: AgentRuntime + AgentCard remain separate resources
5. **CD tooling drift for controller-managed labels**: When the AgentRuntime controller applies `kagenti.io/type` labels to a Deployment's PodTemplateSpec, GitOps CD tools (Argo CD, Flux) may detect this as configuration drift. Mitigation: Argo CD's server-side diff feature (v2.5+) or `ignoreDifferences` configuration excludes controller-managed labels from drift detection. This is the same pattern used for Istio sidecar injection labels. Note: the webhook itself targets Pods (not Deployments), so sidecar injection does not cause GitOps drift.

---

## Risks and Mitigations

### Risk 1: Webhook Availability

**Risk**: If the mutating webhook is unavailable, agent workloads fail to create.

**Mitigation**:
- Deploy webhook with multiple replicas
- Use PodDisruptionBudgets
- Fail-closed is intentional (security-first approach)
- Webhook health monitoring and alerting

### Risk 2: Configuration Propagation Latency

**Risk**: Changes to defaults or AgentRuntime CRs may not propagate to running sidecars quickly enough.

**Mitigation**:
- Configuration propagation mechanism is being evaluated (see [Configuration Propagation](#configuration-propagation-open-design))
- xDS-based propagation (used by Envoy) provides sub-second updates as a candidate approach
- Operator monitors propagation state and reports drift in CR status
- Health checks verify configuration state matches expected defaults


### Risk 3: Multiple Webhook Ordering Conflicts

**Risk**: Kubernetes clusters running multiple mutating admission webhooks (e.g., Istio sidecar injection, Vault Agent injector, and the Kagenti AuthBridge injector simultaneously) can encounter subtle ordering failures. Kubernetes does not guarantee a deterministic execution order among webhooks within the same `failurePolicy` tier. If one webhook's mutation overwrites or conflicts with another's — for example, both modifying the pod's `initContainers` list or `volumes` — the result depends on execution order, which can vary across API server restarts or cluster upgrades. This produces failures that are intermittent, environment-specific, and hard to reproduce.

**Mitigation**:
- Set `reinvocationPolicy: IfNeeded` on the Kagenti webhook so Kubernetes re-invokes it if a later webhook mutates the object — giving Kagenti a chance to reconcile any overwritten fields
- Document which container names and volume names the Kagenti webhook uses so operators can identify and resolve conflicts with other webhooks
- Test explicitly in environments where Istio ambient or sidecar mode is also active, as this is the most common co-tenant webhook
- Pod-level injection (now implemented) narrows the webhook's scope to pod admission only, matching the pattern used by Istio and other well-established injectors — reducing the conflict surface with other webhooks

### Risk 4: Identity Infrastructure Overhead

**Risk**: Injected sidecars add resource overhead and latency.

**Mitigation**:
- Annotations allow disabling specific components
- Sidecar resource limits are configurable via defaults and AgentRuntime CR
- Token caching reduces token exchange latency

### Security Considerations

Unchanged from original proposal:

- **SPIFFE** provides cryptographic workload identity
- **IdP registration** provides OAuth2/OIDC tokens
- **Token validation** at inbound proxy (auth-proxy)
- **Token exchange** at outbound proxy (envoy-proxy)
- **Network policies** restrict traffic flows
- **Fail-closed webhook** ensures agents never run without identity
- **TLS certificates** managed by cert-manager with automatic rotation
- **Secret management** via Kubernetes Secrets with recommendation for external managers (Vault, External Secrets Operator)

---

## Implementation Phases

**Phase 1: Webhook Foundation + AgentRuntime CR** (Q1 2026)
- [x] Pod-level webhook targeting (Pods at CREATE, not Deployments/StatefulSets) — [kagenti-extensions PR #183](https://github.com/kagenti/kagenti-extensions/pull/183)
- [x] ConfigMap-based platform defaults (`kagenti-webhook-defaults`, `kagenti-webhook-feature-gates`) — [kagenti-extensions PR #134](https://github.com/kagenti/kagenti-extensions/pull/134)
- [x] Per-sidecar feature gates and precedence system — [kagenti-extensions PRs #110-#116](https://github.com/kagenti/kagenti-extensions/issues/109)
- [x] Optional namespace gating (`kagenti-enabled: "true"` namespaceSelector)
- [ ] Define lean AgentRuntime v1alpha1 CRD (`targetRef`, `identity`, `trace`)
- [ ] Implement AgentRuntime controller with targetRef resolution
- [ ] Controller applies `kagenti.io/type` + `kagenti.io/config-hash` to PodTemplateSpec
- [ ] Finalizer-based deletion (reverts to platform defaults)

**Phase 2: Observability Maturation** (Q2 2026)
- Refine AgentTrace section of AgentRuntime based on OTEL GenAI semantic conventions
- Integrate with observability stack (MLflow, Phoenix)
- Partner with observability team for feedback

### Sidecar Consolidation Plan

The current AuthBridge implementation injects four containers per pod:

| Container | Purpose | Runtime |
|-----------|---------|---------|
| `proxy-init` | iptables redirect setup | Init container (short-lived) |
| `envoy-proxy` | Envoy + go-processor ext-proc (outbound token exchange, inbound JWT validation) | Go + Envoy |
| `spiffe-helper` | SPIFFE JWT-SVID management | Go |
| `kagenti-client-registration` | Keycloak client registration | Python |

**Planned consolidation** (tracked as a separate work item):

1. **Merge spiffe-helper into go-processor**: The go-processor already reads JWT-SVIDs; spiffe-helper's role (writing SVIDs to disk) can be absorbed into the go-processor or handled via SPIRE's workload API directly.
2. **Merge client-registration into go-processor**: Client registration is a one-time operation that writes `client-id.txt` and `client-secret.txt`. This can run as an init phase within the go-processor.
3. **Target state**: 2 containers — `proxy-init` (init) + `envoy-proxy` (sidecar with consolidated go-processor).

**Benefits**: Reduced per-pod resource overhead, simplified configuration propagation (one process to update), reduced pod startup latency, fewer shared volumes.

**Constraint**: The webhook's injection architecture (separate `Build*Container` functions per sidecar) already supports this — consolidation changes the container builders, not the injection framework.


---

## Success Metrics

1. **Adoption Rate**: Percentage of agent workloads using composition pattern vs. legacy Agent CR
2. **Time to First Agent**: Time from `kubectl apply` of a labeled Deployment to a working agent with identity (target: <30s)
3. **CR-Free Ratio**: Percentage of agents running with defaults only (no AgentRuntime CR) — higher is better
4. **Configuration Change Latency**: Time from defaults/CR update to sidecar reconfiguration (target: seconds, not minutes — dependent on propagation mechanism)
5. **Removal Impact**: Zero workload disruption when Kagenti is removed

---

## References

### Prior Proposals
- [Compositional Agent Platform Architecture](compositional-agent-platform-design.md) — Original three-pillar proposal
- [Label-based injection versus using a reference CR pattern](https://hackmd.io/ci9bS5pYScKFfNBW0wfW1Q) — Counter-proposal for AgentRuntime CR

### Successful Composition Projects
- KEDA — Event-driven autoscaling (ScaledObject with targetRef)
- Flagger — Progressive delivery (Canary with targetRef)
- Prometheus Operator — Monitoring (ServiceMonitor with selector)
- cert-manager — Certificate management (Certificate with targetRef)

### Pattern References
- Knative pkg duck-typing — Duck-typing utilities
- RFC 8693 — OAuth 2.0 Token Exchange
- OpenTelemetry GenAI Semantic Conventions

---

*Document consolidates proposals from Kagenti Team and Roland Huss, authored with assistance from Claude Opus 4.6.*
