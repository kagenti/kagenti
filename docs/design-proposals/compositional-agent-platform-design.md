# Kagenti Implementation Design: Compositional Agent Platform Architecture

**Authors**: Kagenti Team

**Begin Design Discussion**: 2026-01-13

**Status**: Draft

**Checklist**:

- [ ] TokenExchange CR implementation
- [ ] AgentTrace CR implementation
- [ ] AgentCard CR adaptation (selector change)
- [ ] Mutating webhook implementation
- [ ] Controller consolidation (istiod pattern)
- [ ] Migration tooling
- [ ] Documentation updates
- [ ] Integration tests
- [ ] E2E tests
- [ ] Performance benchmarks

---

## Summary/Abstract

This design proposal describes the refactoring of Kagenti from an inheritance-based architecture to a composition-based architecture for managing AI agent workloads on Kubernetes. The current monolithic `Agent` Custom Resource (CR) will be replaced with a two-layer system consisting of automatic identity infrastructure injection via mutating webhook and optional configuration through three independent pillar CRs: `TokenExchange`, `AgentTrace`, and `AgentCard`.

The core thesis is straightforward: **higher-level Kubernetes abstractions that replace standard workload types consistently fail, while composition-based approaches that augment existing workloads succeed**. By adopting the composition pattern, Kagenti will enable users to deploy AI agents using standard Kubernetes primitives (Deployment, StatefulSet, Job) while adding agent-specific capabilities through optional, independent components.

### Architecture at a Glance

```
User Creates Standard Deployment
  + kagenti.io/inject: enabled label
        ↓
Webhook Injects Identity Infrastructure
  • Init container (network setup)
  • SPIFFE helper (identity)
  • Client registration (IdP integration)
  • Auth proxy (inbound validation)
  • Envoy proxy (outbound token exchange)
        ↓
Agent Pod Running with Defaults
  • Identity and auth configured
  • Agent code handles telemetry
  • Agent code exposes capabilities
        ↓
Optional: User Creates Pillar CRs
  • TokenExchange → customize identity/auth
  • AgentTrace → configure telemetry
  • AgentCard → enable discovery
        ↓
Controllers Reconcile
  • TokenExchange/AgentTrace: Create ConfigMaps
  • AgentCard: Fetch and cache agent cards
  • Identity sidecars reconfigure dynamically
  • No pod restarts required
```

---

## Background

### Motivation and Problem Space

An AI Agents PLatform needs to define a coherent set of capabilities for users operating fleets of AI agents. When exploring existing AgentOps frameworks, a key insight emerged: framing the problem as a single, general-purpose "Kubernetes AgentOps framework" is likely the wrong abstraction.

The Kubernetes ecosystem tells a consistent story: attempts to create higher-level workload abstractions fail, while composition-based add-ons succeed. This is not bad engineering or poor timing—it reflects something fundamental about how platform engineers and developers relate to their tools.

**Current Kagenti Problems (Inheritance Pattern)**:

1. **Tight coupling to upstream Kubernetes changes** - Requires constant rebasing on K8s releases without substantial benefits
2. **Responsibility for pass-through definitions** - Even when passing through PodSpec, Kagenti becomes responsible when something goes wrong in those definitions
3. **Limited workload type support** - Only works with Deployments; cannot handle StatefulSets (essential for stateful agents with long-term memory), Jobs (ideal for one-shot agent runs), or CronJobs (scheduled agent executions)
4. **CRD size issues** - Teams have found PodSpec validation can blow CRDs to ~700KB, hitting client-side apply limits
5. **Migration overhead** - Users must convert existing Deployments to new CRD format
6. **Missing integration** - Standard K8s tools/controllers may not recognize the new CRD

Red Hat's existing portfolio already addresses many needs of agentic workloads: service meshes handle inter-service communication, secret managers protect credentials, and observability stacks capture metrics and traces. Introducing a monolithic agent framework would duplicate this existing functionality, increase coupling between components, and add conceptual overhead.

### Impact and Desired Outcome

The compositional refactoring will:

1. **Reduce adoption friction** - Users keep their existing Deployments, StatefulSets, and Jobs
2. **Enable incremental adoption** - Each pillar can be adopted independently
3. **Improve tool compatibility** - kubectl, dashboards, and GitOps continue working normally
4. **Support multiple workload types** - StatefulSets for stateful agents, Jobs for one-shot runs, CronJobs for scheduled executions
5. **Simplify removal** - If disabled/uninstalled, core workloads continue running
6. **Reduce maintenance burden** - No need to track K8s PodSpec changes

The desired outcome is a Kagenti architecture where users can deploy any standard Kubernetes workload with a simple label (`kagenti.io/inject: enabled`) and immediately receive a complete identity infrastructure, with optional fine-tuning through independent CRs.


## User/User Story

**Platform Engineer (Primary)**:
- As a platform engineer, I want to enable AI agent capabilities on existing Kubernetes workloads without requiring developers to learn new CRDs or migrate existing deployments
- As a platform engineer, I want to configure identity and authorization policies centrally without modifying agent application code

**Application Developer**:
- As a developer, I want to deploy my AI agent using standard Kubernetes Deployments so I can use existing CI/CD pipelines and tooling
- As a developer, I want automatic SPIFFE identity and token exchange so my agent can securely communicate with other services without managing credentials
- As a developer, I want to expose my agent's capabilities through a standard discovery mechanism so other agents can find and invoke it

**Operations Engineer**:
- As an operations engineer, I want comprehensive observability into agent execution including tool calls, LLM interactions, and inter-agent communication
- As an operations engineer, I want to remove Kagenti from a workload without disrupting the workload itself

---

## Goals

1. **Compose with existing Kubernetes workload types** - Never require users to abandon Deployment, StatefulSet, or Job
2. **Avoid introducing new mandatory workload abstractions** - Factor out agent-specific concerns into separate, optional components
3. **Keep surface area small** - Focus on integration points, not comprehensive workload management
4. **Provide non-intrusive injection** - Automatic identity infrastructure via opt-in webhook
5. **Enable independent pillar adoption** - Each CR can be used separately
6. **Support dynamic reconfiguration** - Configuration changes without pod restarts
7. **Maintain backward compatibility** - Provide migration path from Agent CR

---

## Non-Goals

1. **Building another workload orchestrator** - Users keep their existing orchestration tools
2. **Introducing mandatory cross-dependencies between pillars** - Optional integration is acceptable, but no pillar requires another
3. **Replacing established deployment tools** - Helm, GitOps, OLM, and Terraform remain valid choices
4. **Duplicating existing Red Hat portfolio functionality** - Secret managers, service meshes, and observability stacks continue to be used
5. **Defining what constitutes an "Agent"** - The architecture is agnostic to agent implementation frameworks

---

## Proposal

### Architectural Principles

**MUST Requirements**:
- Compose with existing Kubernetes workload types
- Avoid introducing new mandatory workload abstractions
- Factor out agent-specific concerns into separate, optional components
- Keep surface area small

**SHOULD Requirements**:
- Avoid external state stores when possible—prefer Kubernetes-native storage
- Prefer compositional operators—reference workloads rather than embed them
- Leverage existing Red Hat portfolio—don't duplicate functionality

### The Two-Layer Architecture

The architecture consists of two layers:

```
┌─────────────────────────────────────────────────────────┐
│ LAYER 1: Automatic Identity Infrastructure (Webhook)   │
│─────────────────────────────────────────────────────────│
│ • Mutating webhook intercepts workload creation         │
│ • Injects identity and auth sidecars with defaults      │
│ • User gets working agent immediately                   │
│ • No CRDs required for basic functionality              │
└─────────────────────────────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────┐
│ LAYER 2: Optional Configuration & Discovery            │
│─────────────────────────────────────────────────────────│
│ • TokenExchange: Configure identity/auth sidecars       │
│ • AgentTrace: Configure agent telemetry                 │
│ • AgentCard: Discover agent capabilities                │
│ • Controllers create ConfigMaps or cache data           │
│ • No pod restarts needed                                │
└─────────────────────────────────────────────────────────┘
```

**Layer 1: Automatic Identity Infrastructure (Webhook)**
- Mutating webhook intercepts workload creation
- Injects identity and auth sidecars with sensible defaults
- User gets working agent immediately
- No CRDs required for basic functionality

**Layer 2: Optional Configuration & Discovery**
- `TokenExchange`: Configure identity/auth sidecars
- `AgentTrace`: Configure agent telemetry
- `AgentCard`: Discover agent capabilities
- Controllers create ConfigMaps or cache data
- No pod restarts needed for configuration changes

### The Three Pillars

| Pillar | Domain | CR Name | Purpose |
|--------|--------|---------|---------|
| Identity | Delegated Authorization | `TokenExchange` | Provide workload identity and enable delegated authorization via RFC 8693 token exchange |
| Discovery | Agent Registry | `AgentCard` | Enable rich agent discovery—knowing which agents are running, what they can do, and how to connect |
| Observability | Tracing | `AgentTrace` | Make agent behavior observable end-to-end—tool call graphs, inter-agent communication, LLM I/O |

### Success Metrics

1. **Adoption Rate**: Percentage of agent workloads using composition pattern vs. legacy Agent CR
2. **Time to First Agent**: Time from deployment to working agent with identity infrastructure
3. **Configuration Change Latency**: Time from CR update to sidecar reconfiguration (target: <10s)
4. **Removal Impact**: Zero workload disruption when Kagenti is removed

---

## Design Details

### Mutating Webhook Design

#### Webhook Configuration

```yaml
apiVersion: admissionregistration.k8s.io/v1
kind: MutatingWebhookConfiguration
metadata:
  name: kagenti-injector
webhooks:
- name: inject.kagenti.io
  clientConfig:
    service:
      name: kagenti-operator
      namespace: kagenti-system
      path: /mutate
    caBundle: ${CA_BUNDLE}
  rules:
  - operations: ["CREATE", "UPDATE"]
    apiGroups: ["apps"]
    apiVersions: ["v1"]
    resources: ["deployments", "statefulsets", "daemonsets"]
  - operations: ["CREATE", "UPDATE"]
    apiGroups: ["batch"]
    apiVersions: ["v1"]
    resources: ["jobs", "cronjobs"]
  objectSelector:
    matchLabels:
      kagenti.io/inject: enabled
  namespaceSelector:
    matchExpressions:
    - key: kagenti.io/injection
      operator: In
      values: ["enabled", "true"]
  admissionReviewVersions: ["v1"]
  sideEffects: None
  timeoutSeconds: 10
  failurePolicy: Fail
  reinvocationPolicy: Never
```

**Key Design Decisions**:

- **Workload-level targeting**: Webhook watches Deployment/StatefulSet/Job, not Pods, enabling deterministic ConfigMap naming based on workload name
- **Explicit opt-in**: Each workload must have `kagenti.io/inject: enabled` and `kagenti.io/spiffe: enabled` labels to prevent accidental injection
- **Fail-closed policy**: If webhook unavailable, workload creation blocks, ensuring agents never run without required identity infrastructure

#### Injected Identity Infrastructure Components

| Component | Type | Purpose |
|-----------|------|---------|
| `proxy-init` | Init Container | Sets up iptables for traffic interception |
| `spiffe-helper` | Sidecar | Manages SPIFFE workload identity |
| `client-registration` | Sidecar | Registers agent with identity provider |
| `auth-proxy` | Sidecar | Validates incoming authentication tokens |
| `envoy-proxy` | Sidecar | Intercepts outbound traffic, performs token exchange |

#### Identity Infrastructure Flow

```
1. Init Phase: proxy-init
   • Setup iptables for traffic interception
   • Create SPIFFE socket directory
           ↓
2. Identity Acquisition: spiffe-helper
   • Connect to SPIRE agent
   • Fetch JWT SVID
   • Write token to /shared/jwt_svid.token
           ↓
3. IdP Registration: client-registration
   • Read SPIFFE ID from JWT
   • Register with Keycloak/IdP
   • Write client_id and client_secret to shared volume
           ↓
4. Authorization Ready
   • auth-proxy: validates inbound tokens
   • envoy-proxy: exchanges outbound tokens
   • Agent container: ready to handle requests
```

#### Default Configuration

All identity infrastructure components start with sensible defaults:

**SPIFFE Helper Defaults**:
- Trust domain: `cluster.local`
- Socket path: `/run/spire/agent-sockets/agent.sock`
- Output format: JWT
- Audience: `kagenti-agents`

**Client Registration Defaults**:
- Provider: Keycloak
- IdP URL: `http://keycloak.kagenti-system.svc:8080`
- Realm: `default`
- Token exchange enabled: `true`

**Auth Proxy Defaults**:
- Inbound port: `8080`
- Target port (agent): `8081`
- Issuer: Cluster-default Keycloak
- Audience validation: Agent's SPIFFE ID

**Envoy Proxy Defaults**:
- Outbound proxy port: `15123`
- Proxy UID: `1337`
- Default token exchange audience: `downstream-service`
- Excluded ports: `8080` (inbound proxy)

### Pillar 1: TokenExchange CR

**Purpose**: Configure the identity infrastructure injected by the webhook.

**Scope**: Affects identity sidecars (spiffe-helper, client-registration, auth-proxy, envoy-proxy)

**Key Capabilities**:
- Customize SPIFFE trust domain and identity provider
- Configure identity provider (Keycloak, AWS IAM, GCP Workload Identity)
- Define inbound token validation rules
- Configure outbound token exchange policies
- Specify per-destination token exchange rules

**API Structure**:

```yaml
apiVersion: kagenti.io/v1alpha1
kind: TokenExchange
metadata:
  name: weather-agent-auth
  namespace: default
spec:
  targetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: weather-agent
  
  spiffe:
    enabled: true
    trustDomain: "prod.cluster.local"
    socketPath: "unix:///run/spire/agent-sockets/agent.sock"
    outputFormat: jwt
  
  clientRegistration:
    enabled: true
    provider: keycloak
    keycloak:
      url: "http://keycloak-prod.auth.svc:8080"
      realm: "production"
      adminCredentialsSecret: "keycloak-prod-admin"
      clientNameTemplate: "agent-{{.PodName}}"
      tokenExchangeEnabled: true
  
  inbound:
    enabled: true
    port: 8080
    targetPort: 8081
    validation:
      enabled: true
      issuer: "http://keycloak-prod.example.com/realms/production"
      jwksUrl: "http://keycloak-prod.auth.svc:8080/realms/production/certs"
      audience: "self"
      requiredScopes:
      - "agent:invoke"
      - "agent:stream"
  
  outbound:
    enabled: true
    trafficInterception:
      enabled: true
      proxyPort: 15123
      proxyUid: 1337
      excludePorts:
      - 8080
      - 9901
    tokenExchange:
      enabled: true
      tokenUrl: "http://keycloak-prod.auth.svc:8080/realms/production/protocol/openid-connect/token"
      defaultTarget:
        audience: "downstream-service"
        scopes:
        - "downstream:access"
      destinationRules:
      - match:
          host: "premium-api.external.com"
        target:
          audience: "premium-api"
          scopes:
          - "weather:premium"
          - "weather:historical"

status:
  phase: Active
  message: "Identity infrastructure configured"
  configMapName: "weather-agent-token-exchange"
  configuredPods: 2
  identityStatus:
    spiffeEnabled: true
    idpRegistered: true
    inboundProxyReady: true
    outboundProxyReady: true
```

**Controller Behavior**:
1. Watches TokenExchange CRs for create/update/delete
2. Resolves targetRef to find workload
3. Creates ConfigMap: `{workload-name}-token-exchange`
4. ConfigMap contains configuration for all identity sidecars
5. Identity sidecars watch ConfigMap via fsnotify
6. Sidecars reconfigure when ConfigMap changes (no pod restart)
7. Updates CR status with identity infrastructure state

**Key Insight**: This capability is reusable beyond agents. Token exchange and delegated authorization are valuable in pure microservice contexts.

### Pillar 2: AgentCard CR

**Purpose**: Discover agent capabilities by fetching cards from agent endpoints.

**Scope**: Discovery only—does not configure identity infrastructure or agent code.

**Key Capabilities**:
- Query pods via label selector
- Fetch agent capability cards from HTTP endpoints
- Cache discovered cards in CR status
- Support multi-instance agent discovery
- Provide discovery API for other agents

**API Structure**:

```yaml
apiVersion: kagenti.io/v1alpha1
kind: AgentCard
metadata:
  name: weather-agent-card
  namespace: default
spec:
  selector:
    matchLabels:
      app: weather-agent
  
  endpoint:
    path: "/.well-known/agent.json"
    port: 8081
    scheme: http
  
  syncPeriod: 30s
  
  metadata:
    name: "Weather Intelligence Agent"
    description: "Production weather forecasting service"
    tags:
    - weather
    - forecast
    - production

status:
  phase: Active
  lastSyncTime: "2026-01-13T16:10:00Z"
  discoveredPods: 3
  syncErrors: 0
  cards:
  - podName: weather-agent-7d5f8b9c4d-abc12
    podIP: 10.244.0.10
    url: "http://10.244.0.10:8081"
    lastFetchTime: "2026-01-13T16:10:00Z"
    fetchStatus: Success
    card:
      name: "Weather Intelligence Agent"
      version: "2.1.0"
      url: "http://weather-agent.default.svc.cluster.local"
      capabilities:
        streaming: true
        batchProcessing: true
      skills:
      - name: "get_forecast"
        description: "Get weather forecast for location"
      - name: "get_climate_data"
        description: "Get historical climate data"
```

**Adaptation Needed**: Change selector from Agent-specific to generic workload selector to work with any workload type via label matching.

### Pillar 3: AgentTrace CR

**Purpose**: Configure agent code telemetry (not identity infrastructure).

**Scope**: Provides configuration that agent code reads to configure OpenTelemetry.

**Key Capabilities**:
- Specify OTEL collector endpoints
- Configure sampling strategies
- Define resource attributes
- Enable GenAI semantic conventions
- Configure observability platform integrations

**API Structure**:

```yaml
apiVersion: kagenti.io/v1alpha1
kind: AgentTrace
metadata:
  name: weather-agent-trace
  namespace: default
spec:
  targetRef:
    kind: Deployment
    name: weather-agent
  
  exporters:
  - type: otlp
    endpoint: "otel-collector.observability:4317"
    protocol: grpc
    compression: gzip
  - type: jaeger
    endpoint: "jaeger-collector.observability:14250"
  
  sampling:
    type: probabilistic
    rate: 0.1
  
  genai:
    enabled: true
    capturePrompts: true
    captureCompletions: true
    captureModelParameters: true
  
  resourceAttributes:
    service.name: "weather-agent"
    service.version: "2.1.0"
    deployment.environment: "production"
  
  integration:
    mlflow:
      enabled: true
      trackingUri: "http://mlflow.ml-platform:5000"
      experimentName: "weather-agent-prod"
    prometheus:
      enabled: true
      port: 9090
      path: "/metrics"

status:
  phase: Active
  configMapName: "weather-agent-trace"
```

**Note on Maturity**: This is a nascent area with limited prior work. The specification will evolve as observability standards for AI agents mature.

### Controller Architecture

#### Consolidated Operator (Istiod Pattern)

Following the Istiod pattern, we recommend a single operator managing all three CRs:

```
┌────────────────────────────────────────────────────────┐
│ Kagenti Operator Pod                                   │
│                                                        │
│  ┌──────────────────────────────────────────────────┐ │
│  │ Controller Manager                                │ │
│  │                                                   │ │
│  │  • TokenExchange Reconciler                      │ │
│  │    - Configures identity infrastructure          │ │
│  │    - Creates ConfigMaps for identity sidecars    │ │
│  │                                                   │ │
│  │  • AgentTrace Reconciler                         │ │
│  │    - Configures agent telemetry                  │ │
│  │    - Creates ConfigMaps for agent code           │ │
│  │                                                   │ │
│  │  • AgentCard Reconciler                          │ │
│  │    - Discovers agent capabilities                │ │
│  │    - Caches cards in CR status                   │ │
│  │                                                   │ │
│  │  • Shared Utilities                              │ │
│  │    - targetRef resolver                          │ │
│  │    - ConfigMap creator                           │ │
│  │    - Status updater                              │ │
│  └──────────────────────────────────────────────────┘ │
│                                                        │
│  ┌──────────────────────────────────────────────────┐ │
│  │ Webhook Server                                    │ │
│  │  • Handles mutation requests                     │ │
│  │  • Injects identity infrastructure               │ │
│  │  • Validates pillar CRs                          │ │
│  └──────────────────────────────────────────────────┘ │
└────────────────────────────────────────────────────────┘
```

**Benefits**:
- Resource efficient (single operator pod)
- Simpler deployment and upgrades
- Easier cross-pillar coordination when needed

**Resource Requirements**:
- Memory: ~200MB
- CPU: <200m
- Single pod for simplified operations

#### Duck-Typing Pattern for Workload References

Following Knative's pkg pattern, use flexible workload targeting via targetRef:

```yaml
spec:
  targetRef:
    apiVersion: apps/v1
    kind: Deployment  # or StatefulSet, Job, CronJob, etc.
    name: my-agent
```

**Benefits**:
- Works with Deployments, StatefulSets, Jobs (addressing current Kagenti limitation)
- No PodSpec duplication
- Minimal schema dependency
- Easy adoption on existing workloads

### Agent Code Requirements

#### Telemetry Instrumentation

Agent code must instrument itself with OpenTelemetry SDK.

**Configuration Source**: AgentTrace ConfigMap at `/etc/kagenti/trace`

**Minimal Example**:

```python
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
import os

def setup_telemetry():
    config_path = '/etc/kagenti/trace'
    try:
        with open(f'{config_path}/otel_endpoint', 'r') as f:
            endpoint = f.read().strip()
    except FileNotFoundError:
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

Agent code must expose capability card for AgentCard controller.

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

### Migration Example

**Before (Inheritance)**:

```yaml
apiVersion: kagenti.io/v1alpha1
kind: Agent
metadata:
  name: weather-agent
spec:
  imageSource:
    image: "ghcr.io/example/weather-agent:v1"
  podTemplateSpec:
    containers:
    - name: agent
      env:
      - name: LLM_MODEL
        value: "gpt-4"
  servicePorts:
  - name: http
    port: 8080
```

**After (Composition)**:

```yaml
# Standard Kubernetes Deployment
apiVersion: apps/v1
kind: Deployment
metadata:
  name: weather-agent
  labels:
    app: weather-agent
    kagenti.io/inject: enabled
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
        env:
        - name: LLM_MODEL
          value: "gpt-4"
        ports:
        - containerPort: 8081
---
# Identity add-on (optional - only if customization needed)
apiVersion: kagenti.io/v1alpha1
kind: TokenExchange
metadata:
  name: weather-agent-auth
spec:
  targetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: weather-agent
  tokenExchange:
    issuer: "https://keycloak.example.com"
---
# Discovery add-on (optional)
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

### Pattern Comparison: Inheritance vs. Composition

| Aspect | Inheritance | Composition |
|--------|-------------|-------------|
| Schema size | Large (includes PodSpec) | Small (only extension config) |
| Migration required | Yes | No |
| Learning curve | Steep | Gentle |
| Workload type support | Usually single type | Multiple types |
| Tool compatibility | Limited | Full |
| Removal impact | Workload disappears | Workload continues |
| Maintenance burden | High (track K8s changes) | Low (stable references) |

### Open Questions

1. **Namespace-scoped vs. Cluster-scoped CRs**: Should TokenExchange be namespace-scoped (current proposal) or cluster-scoped for multi-tenant scenarios?
2. **Default identity provider**: Should we assume Keycloak or support pluggable providers from day one?
3. **Cross-namespace agent communication**: How should token exchange work for agents in different namespaces?

### Pros

1. **Proven pattern**: KEDA, Flagger, Prometheus Operator all use composition successfully
2. **Low adoption friction**: Users keep familiar Kubernetes primitives
3. **Incremental adoption**: Each pillar is independently useful
4. **Easy removal**: Uninstalling Kagenti leaves workloads running
5. **Multi-workload support**: Deployments, StatefulSets, Jobs, CronJobs all work
6. **Reduced maintenance**: No PodSpec tracking required
7. **Reusable capabilities**: Token exchange valuable beyond agents

### Cons

1. **Multiple objects**: Users must create and understand 2+ resources for full functionality
2. **Sync concerns**: Controllers must reliably track target resources
3. **Base limitations**: Extensions can only do what underlying resources allow
4. **Migration effort**: Existing Agent CR users need migration path

---

## Risks and Mitigations

### Risk 1: Webhook Availability

**Risk**: If the mutating webhook is unavailable, agent workloads fail to create.

**Mitigation**: 
- Deploy webhook with multiple replicas
- Use PodDisruptionBudgets
- Fail-closed is intentional (security-first approach)
- Consider webhook auto-recovery mechanisms

### Risk 2: Configuration Drift

**Risk**: ConfigMap changes may not propagate to all sidecar instances.

**Mitigation**:
- Sidecars use fsnotify for real-time ConfigMap watching
- Controller validates propagation and updates CR status
- Health checks verify configuration state

### Risk 3: Migration Complexity

**Risk**: Users with many Agent CRs face significant migration effort.

**Mitigation**:
- Provide automated migration tooling (`kagenti migrate`)
- Maintain dual support during transition period
- Clear deprecation timeline (v2.0: deprecation, v3.0: removal)

### Risk 4: Identity Infrastructure Overhead

**Risk**: Injected sidecars add resource overhead and latency.

**Mitigation**:
- Annotations allow disabling specific components
- Sidecar resource limits are configurable
- Token caching reduces token exchange latency

### Security Considerations

**Defense in Depth**:
- SPIFFE provides cryptographic workload identity
- IdP registration provides OAuth2/OIDC tokens
- Token validation at inbound proxy (auth-proxy)
- Token exchange at outbound proxy (envoy-proxy)
- Network policies restrict traffic flows

**Security Contexts**:

```yaml
# Init container (needs root for iptables)
securityContext:
  runAsUser: 0
  capabilities:
    add: ["NET_ADMIN"]

# Proxy sidecars (specific UID)
securityContext:
  runAsUser: 1337
  runAsNonRoot: true
  capabilities:
    drop: ["ALL"]

# Other sidecars (most restrictive)
securityContext:
  runAsUser: 1000
  runAsNonRoot: true
  readOnlyRootFilesystem: true
  capabilities:
    drop: ["ALL"]
```

**Webhook Security**:
- TLS certificates managed by cert-manager with automatic rotation
- Fail-closed policy ensures agents never run without identity infrastructure
- 10-second timeout prevents slow denial attacks

**Secret Management**:
- IdP admin credentials stored in Kubernetes Secrets
- Client credentials written to ephemeral shared volumes
- SPIFFE tokens are short-lived and auto-rotated
- Recommendation: Use external secret managers (Vault, External Secrets Operator)

---

## Future Milestones

1. **Multi-cluster agent discovery**: AgentCard federation across clusters
2. **Advanced token exchange patterns**: Chained delegation, constrained delegation
3. **Agent-to-agent communication protocols**: A2A protocol native support
4. **Policy-based authorization**: Integration with OPA/Gatekeeper for fine-grained access control
5. **Agent lifecycle management**: Health checks, circuit breakers, graceful degradation
6. **Cost attribution**: Per-agent LLM token usage tracking and allocation

---

## Implementation Details

### Testing Plan

**Unit Tests**:
- Webhook injection logic
- Controller reconciliation loops
- targetRef resolution
- ConfigMap generation

**Integration Tests**:
- End-to-end identity flow (SPIFFE → registration → token exchange)
- Multi-workload type support (Deployment, StatefulSet, Job)
- Configuration propagation without pod restart
- AgentCard discovery across multiple pod instances

**E2E Tests**:
- Complete agent deployment workflow
- Migration from Agent CR to composition
- Removal of Kagenti with workload continuity
- Cross-namespace agent communication

### Update/Rollback Compatibility

**Forward Compatibility**:
- New pillar CRs are additive; existing workloads with `kagenti.io/inject` continue working
- Unknown CR fields are ignored (Kubernetes standard behavior)

**Rollback Strategy**:
- Phase 1: Both patterns work (dual support)
- Rollback: Simply re-deploy Agent CRs
- ConfigMaps persist after CR deletion; manual cleanup may be needed

### Scalability

**Webhook Performance**:
- Target: <50ms mutation latency at p99
- Horizontal scaling via multiple webhook replicas
- No external dependencies in hot path

**Controller Performance**:
- ConfigMap creation is O(1) per CR
- AgentCard discovery scales with pod count (mitigated by caching)
- Target: <1000 pillar CRs per cluster without performance degradation

### Implementation Phases/History

**Phase 1: Extract TokenExchange** (Q1 2026)
- Create standalone TokenExchange CR with targetRef pattern
- Extract current SPIFFE/SVID integration from Agent controller
- Validate works with Deployment, StatefulSet, Job
- Write migration documentation

**Phase 2: Adapt AgentCard** (Q1 2026)
- Change selector from Agent-specific to generic workload selector
- Ensure works with any workload type via label matching
- Keep A2A card fetching and caching logic
- Update documentation

**Phase 3: Add Observability CR** (Q2 2026)
- Design AgentTrace CR for OTEL trace configuration
- Integrate with existing observability stack (MLFlow)
- Define GenAI semantic conventions alignment
- Partner with observability team for feedback

**Phase 4: Migration Period** (Q2-Q3 2026)
- v2.0: Agent CR marked deprecated with warnings
- v2.x: Dual support maintained
- Migration tooling available
- Documentation and examples updated

**Phase 5: Agent CR Removal** (Q4 2026)
- v3.0: Agent CR removed
- Final migration guide published
- Legacy support ended

---

## References

### Failed Kubernetes Abstraction Projects
- kubernetes-sigs/application - Dormant Application CRD
- Kabanero.io GitHub - Archived IBM project
- oam-dev/rudr - Archived OAM implementation
- DeploymentConfig Deprecation - Red Hat Customer Portal

### Successful Composition Projects
- KEDA - Event-driven autoscaling
- Flagger - Progressive delivery
- Prometheus Operator - Monitoring
- cert-manager - Certificate management

### Pattern References
- Knative pkg duck-typing - Duck-typing utilities
- Flagger vs Argo Rollouts - Pattern comparison
- OAM vs DevOps Analysis - Critical analysis
- RFC 8693 - OAuth 2.0 Token Exchange

---
*Document generated with help from Claude Opus 4.5 based on Red Hat (Roland Huss, Morgan Foster and Gordon Sim) and research kagenti team discussions.
