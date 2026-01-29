# Kagenti Components

This document provides detailed information about each component of the Kagenti platform.

## Table of Contents

- [Overview](#overview)
- [Architecture Diagram](#architecture-diagram)
- [Agent Lifecycle Operator](#agent-lifecycle-operator)
- [MCP Gateway](#mcp-gateway)
- [Plugins adapter](#plugins-adapter)
- [Kagenti UI](#kagenti-ui)
- [Identity & Auth Bridge](#identity--auth-bridge)
- [Infrastructure Services](#infrastructure-services)
- [Supported Agent Frameworks](#supported-agent-frameworks)
- [Communication Protocols](#communication-protocols)

---

## Overview

Kagenti is a cloud-native middleware providing a **framework-neutral**, **scalable**, and **secure** platform for deploying and orchestrating AI agents through a standardized REST API. It addresses the gap between agent development frameworks and production deployment by providing:

- **Authentication and Authorization** — Secure access control for agents and tools
- **Trusted Identity** — SPIRE-managed workload identities
- **Deployment & Configuration** — Kubernetes-native lifecycle management
- **Scaling & Fault-tolerance** — Auto-scaling and resilient deployments
- **Discovery** — Agent and tool discovery via A2A protocol
- **Persistence** — State management for agent workflows

### Value Proposition

Despite the extensive variety of frameworks available for developing agent-based applications, there is a distinct lack of standardized methods for deploying and operating agent code in production environments, as well as for exposing it through a standardized API. Agents are adept at reasoning, planning, and interacting with various tools, but their full potential can be limited by deployment challenges.

Kagenti addresses this gap by enhancing existing agent frameworks with production-ready infrastructure.

---

## Architecture Diagram

All the Kagenti components and their deployment namespaces

```shell
┌───────────────────────────────────────────────────────────────────────┐
│                           Kubernetes Cluster                          │
├───────────────────────────────────────────────────────────────────────┤
│                                                                       │
│  ┌─────────────────────────────────────────────────────────────────┐  │
│  │                      kagenti-system Namespace                   │  │
│  │  ┌────────────┐  ┌────────────┐  ┌────────────┐  ┌────────────┐ │  │
│  │  │ Kagenti UI │  │ Shipwright │  │  Ingress   │  │   Kiali    │ │  │
│  │  │            │  │  (Builds)  │  │  Gateway   │  │            │ │  │
│  │  │            │  │            │  │            │  │            │ │  │
│  │  └────────────┘  └────────────┘  └────────────┘  └────────────┘ │  │
│  └─────────────────────────────────────────────────────────────────┘  │
│                                                                       │
│  ┌──────────────────────────────────────────────────────────────────┐ │
│  │                Workload Namespaces (team1, team2, ...)           │ │
│  │     ┌──────────────┐  ┌──────────────┐   ┌──────────────┐        │ │
│  │     │  A2A Agents  │  │  MCP Tools   │   │ Custom       │        │ │
│  │     │  (LangGraph, │  │  (weather,   │   │ Workloads    │        │ │
│  │     │   CrewAI,    │  │   slack,     │   │              │        │ │
│  │     │   AG2...)    │  │   fetch...)  │   │              │        │ │
│  │     └──────────────┘  └──────────────┘   └──────────────┘        │ │
│  └──────────────────────────────────────────────────────────────────┘ │
│                                                                       │
│           ┌────────────────────┐  ┌────────────────────┐              |
│           │  gateway-system    │  │     mcp-system     │              │
│           │  ┌──────────────┐  │  │  ┌──────────────┐  │              │
│           │  │ MCP Gateway  │  │  │  │ MCP Broker   │  │              │
│           │  │   (Envoy)    │  │  │  │ Controller   │  │              │
│           │  └──────────────┘  │  │  └──────────────┘  │              │
│           └────────────────────┘  └────────────────────┘              │
│                                                                       │
│    ┌────────────────┐  ┌────────────────┐  ┌────────────────────┐     │
│    │     SPIRE      │  │       IAM      │  │  Istio Ambient     │     │
│    │  (Identity)    │  │(e.g. Keycloak) |  │  (Service Mesh)    │     │
│    └────────────────┘  └────────────────┘  └────────────────────┘     │
│                                                                       │
└───────────────────────────────────────────────────────────────────────┘
```

---

## Agent Deployment Architecture

Kagenti deploys agents using standard Kubernetes workloads (Deployments + Services), providing a simple, portable, and operator-free deployment model.

### Capabilities

| Feature | Description |
|---------|-------------|
| **Agent Deployment** | Deploy agents from source code or container images as Kubernetes Deployments |
| **Build Automation** | Build agent containers using Shipwright with Buildah |
| **Lifecycle Management** | Standard Kubernetes Deployment lifecycle (rolling updates, rollbacks, scaling) |
| **Configuration Management** | Environment variables, secrets, and config maps via Deployment spec |
| **Multi-Namespace Support** | Deploy agents to isolated team namespaces |

### Container Build System

Kagenti uses [Shipwright](https://shipwright.io) for building container images from source:

| Strategy | Use Case | Description |
|----------|----------|-------------|
| `buildah-insecure-push` | Internal registries | For registries without TLS (dev/Kind clusters) |
| `buildah` | External registries | For registries with TLS (quay.io, ghcr.io, docker.io) |

**Shipwright Build Flow:**
1. UI creates a Shipwright `Build` CR with source configuration
2. UI creates a `BuildRun` CR to trigger the build
3. UI polls `BuildRun` status until completion
4. On success, UI creates the Deployment + Service for the agent

### Agent Resources

Agents are deployed as standard Kubernetes resources:

```yaml
# Deployment - Manages agent pods
apiVersion: apps/v1
kind: Deployment
metadata:
  name: weather-service
  namespace: team1
  labels:
    kagenti.io/type: agent
    kagenti.io/protocol: a2a
    kagenti.io/framework: LangGraph
    app.kubernetes.io/name: weather-service
    app.kubernetes.io/managed-by: kagenti-ui
spec:
  replicas: 1
  selector:
    matchLabels:
      kagenti.io/type: agent
      app.kubernetes.io/name: weather-service
  template:
    metadata:
      labels:
        kagenti.io/type: agent
        kagenti.io/protocol: a2a
        app.kubernetes.io/name: weather-service
    spec:
      containers:
        - name: agent
          image: ghcr.io/kagenti/weather-service:latest
          env:
            - name: PORT
              value: "8000"
            - name: OPENAI_API_KEY
              valueFrom:
                secretKeyRef:
                  name: openai-secret
                  key: api-key
          ports:
            - containerPort: 8000
              name: http
```

```yaml
# Service - Exposes the agent within the cluster
apiVersion: v1
kind: Service
metadata:
  name: weather-service
  namespace: team1
  labels:
    kagenti.io/type: agent
    app.kubernetes.io/name: weather-service
spec:
  type: ClusterIP
  selector:
    kagenti.io/type: agent
    app.kubernetes.io/name: weather-service
  ports:
    - name: http
      port: 8080
      targetPort: 8000
```

```yaml
# Shipwright Build - For building from source
apiVersion: shipwright.io/v1beta1
kind: Build
metadata:
  name: weather-service
  labels:
    kagenti.io/type: agent
    kagenti.io/protocol: a2a
spec:
  source:
    type: Git
    git:
      url: https://github.com/kagenti/agent-examples
      revision: main
    contextDir: a2a/weather_service
  strategy:
    name: buildah-insecure-push  # or "buildah" for external registries
    kind: ClusterBuildStrategy
  output:
    image: registry.cr-system.svc.cluster.local:5000/weather-service:v0.0.1
```

### Architecture

```
┌─────────────────────────────────────────────────────┐
│                    Kagenti UI                       │
├─────────────────────────────────────────────────────┤
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  │
│  │   Import    │  │   Build     │  │   Deploy    │  │
│  │   Agent     │  │   (Source)  │  │   Agent     │  │
│  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘  │
│         │                │                │         │
│         ▼                ▼                ▼         │
│  ┌─────────────────────────────────────────────┐    │
│  │            Kubernetes API Server            │    │
│  │  (Deployment, Service, Build, HTTPRoute)    │    │
│  └─────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────┘
```

### Label Standards

All agent workloads use consistent labels for discovery:

| Label | Value | Purpose |
|-------|-------|---------|
| `kagenti.io/type` | `agent` | Identifies resource as a Kagenti agent |
| `kagenti.io/protocol` | `a2a` | Protocol type |
| `kagenti.io/framework` | `LangGraph`, `CrewAI`, etc. | Agent framework |
| `app.kubernetes.io/name` | `<agent-name>` | Standard K8s app name |
| `app.kubernetes.io/managed-by` | `kagenti-ui` | Resource manager |

---

## MCP Gateway

**Repository**: [Kuadrant/mcp-gateway](https://github.com/Kuadrant/mcp-gateway)

The MCP Gateway provides a unified entry point for [Model Context Protocol (MCP)](https://modelcontextprotocol.io) servers and tools. It acts as a "front door" for all MCP-based tool interactions.

### Capabilities

| Feature | Description |
|---------|-------------|
| **Tool Discovery** | Automatic discovery and registration of MCP servers |
| **Routing** | Route agent requests to appropriate MCP tools |
| **Authentication** | OAuth/token-based authentication for tool access |
| **Load Balancing** | Distribute requests across tool replicas |

### Components

| Component | Namespace | Purpose |
|-----------|-----------|---------|
| `mcp-gateway-istio` | `gateway-system` | Envoy proxy for request routing |
| `mcp-controller` | `mcp-system` | Manages MCPServer custom resources |
| `mcp-broker-router` | `mcp-system` | Routes requests to registered MCP servers |

### Registering Tools with the Gateway

Tools are registered using Kubernetes Gateway API resources:

```yaml
# HTTPRoute - Define routing to MCP server
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: weather-tool-route
  labels:
    mcp-server: "true"
spec:
  parentRefs:
  - name: mcp-gateway
    namespace: gateway-system
  hostnames:
  - "weather-tool.mcp.local"
  rules:
  - backendRefs:
    - name: weather-tool
      port: 8000
```

```yaml
# MCPServer - Register with the gateway
apiVersion: mcp.kagenti.com/v1alpha1
kind: MCPServer
metadata:
  name: weather-tool-servers
spec:
  toolPrefix: weather_
  targetRef:
    group: gateway.networking.k8s.io
    kind: HTTPRoute
    name: weather-tool-route
```

For detailed gateway configuration, see [MCP Gateway Instructions](./gateway.md).

### MCP Tool Builds with Shipwright

Similar to agents, MCP tools can be built from source using Shipwright. The build process is:

1. UI creates a Shipwright `Build` CR with source configuration
2. UI creates a `BuildRun` CR to trigger the build
3. UI polls `BuildRun` status until completion
4. On success, UI creates a Deployment + Service for the MCP tool

```yaml
# Shipwright Build for MCP Tool
apiVersion: shipwright.io/v1beta1
kind: Build
metadata:
  name: weather-tool
  labels:
    kagenti.io/type: tool
    kagenti.io/protocol: streamable_http
spec:
  source:
    type: Git
    git:
      url: https://github.com/kagenti/agent-examples
      revision: main
    contextDir: mcp/weather_tool
  strategy:
    name: buildah-insecure-push
    kind: ClusterBuildStrategy
  output:
    image: registry.cr-system.svc.cluster.local:5000/weather-tool:v0.0.1
```

```yaml
# Deployment - Manages MCP tool pods
apiVersion: apps/v1
kind: Deployment
metadata:
  name: weather-tool
  namespace: team1
  labels:
    kagenti.io/type: tool
    kagenti.io/protocol: mcp
    kagenti.io/transport: streamable_http
    app.kubernetes.io/name: weather-tool
spec:
  replicas: 1
  selector:
    matchLabels:
      kagenti.io/type: tool
      app.kubernetes.io/name: weather-tool
  template:
    metadata:
      labels:
        kagenti.io/type: tool
        kagenti.io/protocol: mcp
        app.kubernetes.io/name: weather-tool
    spec:
      containers:
        - name: mcp
          image: registry.cr-system.svc.cluster.local:5000/weather-tool:v0.0.1
          ports:
            - containerPort: 8000
              name: http
```

For detailed tool deployment instructions, see [Importing a New Tool](./new-tool.md).

---


## Plugins Adapter

**Repository**: [kagenti/plugins-adapter](https://github.com/kagenti/plugins-adapter)

The Plugins Adapter enables dynamic plugin loading and execution within Envoy-based gateways, including the [MCP gateway](#mcp-gateway), via Envoy's External Processing API (ext_proc). It allows runtime extension of gateway capabilities without recompiling or redeploying the gateway.

### Capabilities

| Feature | Description |
|---------|-------------|
| **Dynamic Plugin Loading** | Load and update plugins without traffic disruption |
| **Request/Response Control** | Inspect, modify, or block based on headers and body |
| **Bring-Your-Own (BYO) Logic** | Implement plugins in any language  |
| **Guardrails Enforcement** | Implement security policies, content filtering, and compliance checks |

---

## Kagenti UI

**Location**: `kagenti/ui-v2/`

A modern web dashboard built with React ([PatternFly](https://www.patternfly.org/get-started/develop/) frontend and FastAPI backend for managing agents and tools.

### Architecture

| Component | Technology | Description |
|-----------|------------|-------------|
| **Frontend** | React + PatternFly | Single-page application served by nginx |
| **Backend** | FastAPI + Python | REST API for Kubernetes interactions |

### Features

| Feature | Description |
|---------|-------------|
| **Agent Import** | Import A2A agents from any framework via Git URL or container image |
| **Tool Deployment** | Deploy MCP tools directly from source or container image |
| **Interactive Testing** | Chat interface to test agent capabilities |
| **Monitoring** | View traces, logs, and network traffic via Phoenix and Kiali |
| **Authentication** | Keycloak-based login/logout with OAuth2 |
| **MCP Gateway** | Browse and test MCP tools via MCP Inspector |

### Pages

| Page | Purpose |
|------|---------|
| Home | Overview and quick actions |
| Agents | List, import, and manage agents |
| Tools | List, import, and manage MCP tools |
| MCP Gateway | View MCP Gateway status and launch MCP Inspector |
| Observability | Access Phoenix traces and Kiali network dashboards |
| Admin | Keycloak and system configuration |

### Access

```bash
# Kind cluster
open http://kagenti-ui.localtest.me:8080

# OpenShift
kubectl get route kagenti-ui -n kagenti-system -o jsonpath='{.status.ingress[0].host}'
```

---

## Identity & Auth Bridge

**Repository**: [kagenti/kagenti-extensions/AuthBridge](https://github.com/kagenti/kagenti-extensions/tree/main/AuthBridge)

Kagenti provides a unified framework for identity and authorization in agentic systems, replacing static credentials with dynamic, short-lived tokens. We call this collection of assets **Auth Bridge**.

**Auth Bridge** solves a critical challenge in microservices and agentic architectures: **how can workloads authenticate and communicate securely without pre-provisioned static credentials?**

### Auth Bridge Components

| Component | Purpose | Repository |
|-----------|---------|------------|
| **[Client Registration](https://github.com/kagenti/kagenti-extensions/tree/main/AuthBridge/client-registration)** | Automatic OAuth2/OIDC client provisioning using SPIFFE ID | `AuthBridge/client-registration` |
| **[AuthProxy](https://github.com/kagenti/kagenti-extensions/tree/main/AuthBridge/AuthProxy)** | JWT validation and transparent token exchange | `AuthBridge/AuthProxy` |
| **[SPIRE](https://spiffe.io/docs/latest/spire-about/)** | Workload identity and attestation | External |
| **[Keycloak](https://www.keycloak.org/)** | Identity provider and access management | External |

### Client Registration

Automatically registers Kubernetes workloads as Keycloak clients at pod startup:

- Uses **SPIFFE ID** as client identifier (e.g., `spiffe://localtest.me/ns/team/sa/my-agent`)
- Eliminates manual client creation and secret distribution
- Writes credentials to shared volume for application use

### AuthProxy

A sidecar that validates incoming tokens and transparently exchanges them for downstream services:

```
┌────────────────────────────────────────────────────────────────────┐
│                            CALLER POD                              │
│  ┌──────────────┐    ┌────────────────────────────────────────┐    │
│  │              │    │         AuthProxy Sidecar:             │    │
│  │  Application │───►│  1. Validate token Signature + Issuer  │    │
│  │              │    │  2. Exchange token for target audience │    │
│  │              │    │  3. Forward to Target with new token   │    │
│  └──────────────┘    └────────────────────────────────────────┘    │
└────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
                         ┌─────────────────────┐
                         │   TARGET SERVICE    │
                         │  (aud: auth-target) │
                         └─────────────────────┘
```

**Key Features:**

- **JWT Validation** using JWKS from Keycloak
- **OAuth 2.0 Token Exchange** ([RFC 8693](https://datatracker.ietf.org/doc/html/rfc8693))
- **Transparent to applications** - handled by Envoy sidecar
- **Audience scoping** - tokens are scoped to specific services

### SPIRE (Workload Identity)

[SPIRE](https://spiffe.io/docs/latest/spire-about/) provides cryptographic workload identities using the SPIFFE standard.

| Component | Purpose |
|-----------|---------|
| **SPIRE Server** | Issues SVIDs (SPIFFE Verifiable Identity Documents) |
| **SPIRE Agent** | Node-level agent that attests workloads |
| **CSI Driver** | Mounts SVID certificates into pods |

**Identity Format**: `spiffe://<trust-domain>/ns/<namespace>/sa/<service-account>`

### Keycloak (Access Management)

[Keycloak](https://www.keycloak.org/) manages user authentication and OAuth/OIDC flows.

| Feature | Description |
|---------|-------------|
| **User Management** | Create and manage Kagenti users |
| **Client Registration** | OAuth clients for agents and UI (e.g. automated Keycloak Client registration via [Client Registration](https://github.com/kagenti/kagenti-extensions/tree/main/AuthBridge/client-registration) component) |
| **Token Exchange** | Exchange tokens between audiences ([RFC 8693](https://datatracker.ietf.org/doc/html/rfc8693)) |
| **SSO** | Single sign-on across Kagenti components |

### Authorization Pattern

The Agent and Tool Authorization Pattern replaces static credentials with dynamic SPIRE-managed identities, enforcing least privilege and continuous authentication:

```
┌──────────┐     ┌──────────┐     ┌──────────┐     ┌──────────┐
│   User   │────▶│ Keycloak │────▶│  Agent   │────▶│   Tool   │
└──────────┘     └──────────┘     └──────────┘     └──────────┘
                      │                │                │
                      ▼                ▼                ▼
                 ┌─────────────────────────────────────────┐
                 │              SPIRE Server               │
                 │    (Issues short-lived identities)      │
                 └─────────────────────────────────────────┘
```

1. **User authenticates** with Keycloak, receives access token
2. **Agent receives** user context via delegated token
3. **Agent identity** is attested by SPIRE
4. **Tool access** uses exchanged tokens with minimal scope

**Security Properties:**

- **No Static Secrets** - Credentials are dynamically generated at pod startup
- **Short-Lived Tokens** - JWT tokens expire and must be refreshed
- **Audience Scoping** - Tokens are scoped to specific audiences, preventing reuse
- **Transparent to Application** - Token exchange is handled by the sidecar

For detailed overview of Identity and Authorization Patterns, see the [Identity Guide](./identity-guide.md).

### Tornjak (SPIRE Management UI)

```bash
# API
curl http://spire-tornjak-api.localtest.me:8080/

# UI
open http://spire-tornjak-ui.localtest.me:8080/
```

---

## Infrastructure Services

### Ingress Gateway

The Ingress Gateway routes external HTTP requests to internal services using the [Kubernetes Gateway API](https://gateway-api.sigs.k8s.io).

- **Namespace**: `kagenti-system`
- **Implementation**: Istio Gateway

### Istio Ambient Mesh

[Istio Ambient](https://istio.io/latest/docs/ambient/) provides service mesh capabilities without sidecar proxies.

| Component | Purpose |
|-----------|---------|
| **Ztunnel** | Node-local proxy for mTLS and traffic interception |
| **Waypoint** | Optional L7 proxy for advanced traffic policies |

**Benefits**:

- Zero-config mTLS between services
- No sidecar resource overhead
- Transparent to applications

### Kiali (Service Mesh Observability)

[Kiali](https://kiali.io) provides visualization of the service mesh topology and traffic flows.

### Phoenix (Tracing)

LLM observability and tracing for agent interactions.

---

## Supported Agent Frameworks

Kagenti is framework-neutral and supports agents built with any framework that can be exposed via the A2A protocol:

| Framework | Description | Use Case |
|-----------|-------------|----------|
| **[LangGraph](https://github.com/langchain-ai/langgraph)** | Graph-based agent orchestration | Complex workflows with explicit control |
| **[CrewAI](https://www.crewai.com/)** | Role-based multi-agent collaboration | Autonomous goal-driven teams |
| **[AG2 (AutoGen)](https://microsoft.github.io/autogen/)** | Multi-agent conversation framework | Conversational agents |
| **[Llama Stack](https://github.com/meta-llama/llama-stack)** | Meta's agent framework | ReAct-style patterns |
| **[BeeAI](https://github.com/i-am-bee/bee-agent-framework)** | IBM's agent framework | Enterprise agents |

### Example Agents

| Agent | Framework | Description |
|-------|-----------|-------------|
| `weather-service` | LangGraph | Weather information assistant |
| `a2a-currency-converter` | LangGraph | Currency exchange rates |
| `a2a-contact-extractor` | Marvin | Extract contact info from text |
| `slack-researcher` | AutoGen | Slack research assistant |

---

## Communication Protocols

### A2A (Agent-to-Agent)

[A2A](https://google.github.io/A2A) is Google's standard protocol for agent communication.

**Features**:

- Agent discovery via Agent Cards
- Standardized task execution API
- Streaming support for long-running tasks

**Endpoints**:
```
GET  /.well-known/agent-card.json    # Agent Card (discovery)
POST /                          # Send message/task
GET  /tasks/{id}                # Get task status
```

### MCP (Model Context Protocol)

[MCP](https://modelcontextprotocol.io) is Anthropic's protocol for tool integration.

**Features**:

- Tool discovery and invocation
- Resource access
- Prompt templates

**Endpoints**:
```
POST /mcp    # MCP JSON-RPC messages
```

---

## Related Documentation

- [Installation Guide](./install.md)
- [Demo Documentation](./demos/README.md)
- [Technical Details](./tech-details.md)
- [Identity, Security, and Auth Bridge](./identity-guide.md)
- [MCP Gateway Instructions](./gateway.md)
- [New Agent Guide](./new-agent.md)
- [New Tool Guide](./new-tool.md)
