# CLAUDE.md - Kagenti Organization Guide

This document provides context for AI assistants working across the Kagenti organization repositories.

## Organization Overview

**Kagenti** is a cloud-native middleware platform for deploying and orchestrating AI agents. The project provides a framework-neutral, scalable, and secure infrastructure for running agents built with any framework through standardized protocols (A2A, MCP).

**Website**: [kagenti.io](http://kagenti.io)
**GitHub Organization**: [github.com/kagenti](https://github.com/kagenti)
**Slack**: [Kagenti Slack](https://ibm.biz/kagenti-slack)

## Repository Structure

The Kagenti organization consists of the following repositories:

| Repository | Language | Description |
|------------|----------|-------------|
| **[kagenti](https://github.com/kagenti/kagenti)** | Python | UI dashboard and documentation |
| **[kagenti-operator](https://github.com/kagenti/kagenti-operator)** | Go | Kubernetes operator for agent/tool lifecycle management |
| **[mcp-gateway](https://github.com/kagenti/mcp-gateway)** | Go | Envoy-based MCP Gateway for tool federation |
| **[agent-examples](https://github.com/kagenti/agent-examples)** | Python | Sample agents and tools for the platform |
| **[kagenti-extensions](https://github.com/kagenti/kagenti-extensions)** | Go | Extensions and plugins |
| **[agentic-control-plane](https://github.com/kagenti/agentic-control-plane)** | Python | Control plane of specialized A2A agents |
| **[plugins-adapter](https://github.com/kagenti/plugins-adapter)** | Python | Guardrails configuration for MCP Gateway |
| **[.github](https://github.com/kagenti/.github)** | HTML | Project website (Hugo-based) |

---

## Repository Details

### 1. kagenti (Main Repository)

**Purpose**: Primary entry point containing the web UI and documentation.

**Key Components**:
```
kagenti/
├── kagenti/
│   ├── ui-v2/                 # React (PatternFly) frontend
│   │   ├── src/pages/         # Page components
│   │   └── src/services/      # API client
│   ├── backend/               # FastAPI backend for UI
│   │   ├── app/routers/       # API route handlers
│   │   └── app/services/      # Kubernetes integration
│   ├── auth/                  # OAuth secret generation utilities
│   ├── tests/e2e/             # End-to-end tests
│   └── examples/              # Example configurations
├── charts/                    # Helm charts (kagenti, kagenti-deps)
├── deployments/
│   └── envs/                  # Environment-specific values
└── docs/                      # Documentation
```

**Commands**:
```bash
# Deploy to Kind cluster
# From repository root
cp deployments/envs/secret_values.yaml.example deployments/envs/.secret_values.yaml
# Edit deployments/envs/.secret_values.yaml with your values
scripts/kind/setup-kagenti.sh

# Run UI locally
cd kagenti/backend
uv run uvicorn app.main:app --reload --port 8000
# In a separate terminal:
cd kagenti/ui-v2
npm run dev

# Lint
make lint
```

---

### 2. kagenti-operator

**Purpose**: Kubernetes operator managing agent/tool deployment and lifecycle.

**Contains Two Operators**:

#### Platform Operator (`platform-operator/`)
Manages complex multi-component applications through:
- **Component CR**: Individual deployable units (Agent, Tool, Infrastructure)
- **Platform CR**: Orchestration layer managing collections of Components

#### Kagenti Operator (`kagenti-operator/`)
Manages agent lifecycle and discovery:
- **AgentCard CR**: Agent deployment and lifecycle

**Note**: Container image builds are now handled by Shipwright Build/BuildRun CRDs directly, triggered by the Kagenti UI. The UI creates Deployment + Service resources for both agents and tools after builds complete.

**Key Files**:
```
kagenti-operator/
├── platform-operator/
│   ├── api/v1alpha1/
│   │   ├── component_types.go    # Component CRD definition
│   │   └── platform_types.go     # Platform CRD definition
│   ├── internal/
│   │   ├── controller/           # Reconciliation logic
│   │   ├── deployer/             # Deployment strategies (K8s, Helm, OLM)
│   │   └── webhook/              # Admission webhooks
│   └── config/
│       ├── crd/bases/            # CRD YAML definitions
│       └── samples/              # Example CRs
├── kagenti-operator/
│   ├── api/v1alpha1/
│   │   └── agent_types.go
│   └── internal/controller/
└── charts/                       # Helm charts for both operators
```

**Container Image Builds (Shipwright)**:
```yaml
# Shipwright Build - Defines how to build container image from source
apiVersion: shipwright.io/v1beta1
kind: Build
metadata:
  name: weather-service
  labels:
    kagenti.io/type: agent  # or "tool"
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

# Shipwright BuildRun - Triggers the build
apiVersion: shipwright.io/v1beta1
kind: BuildRun
metadata:
  generateName: weather-service-run-
spec:
  build:
    name: weather-service
```

**Agent Deployment**: Agents are now deployed as standard Kubernetes Deployments + Services
(the old Component CRD from `kagenti.operator.dev` has been removed).
See `docs/plans/migrate-agent-crd-to-workloads.md` for details.

**Commands**:
```bash
cd platform-operator

# Build and deploy locally
make ko-local-build
make install-local-chart

# Run tests
make test

# Clean up
./scripts/cleanup.sh
```

---

### 3. mcp-gateway

**Purpose**: Envoy-based gateway for Model Context Protocol (MCP) tool federation.

**Features**:
- Automatic MCP server discovery and registration
- Request routing to appropriate tools
- OAuth/token-based authentication
- Load balancing across tool replicas

**Architecture**:
```
mcp-gateway/
├── cmd/                    # Entry points
├── internal/
│   ├── gateway/            # Core gateway logic
│   ├── broker/             # MCP broker/router
│   └── controller/         # MCPServer CR controller
├── api/v1alpha1/           # CRD definitions
└── charts/                 # Helm charts
```

**CRD**:
```yaml
apiVersion: mcp.kuadrant.io/v1alpha1
kind: MCPServerRegistration
metadata:
  name: weather-tool-servers
spec:
  toolPrefix: weather_
  targetRef:
    group: gateway.networking.k8s.io
    kind: HTTPRoute
    name: weather-tool-route
```

---

### 4. agent-examples

**Purpose**: Reference implementations of agents and MCP tools.

**Structure**:
```
agent-examples/
├── a2a/                    # A2A Protocol Agents
│   ├── weather_service/    # LangGraph weather agent
│   ├── currency_converter/ # LangGraph currency agent
│   ├── contact_extractor/  # Marvin extraction agent
│   ├── slack_researcher/   # AutoGen slack assistant
│   ├── file_organizer/     # File organization agent
│   └── generic_agent/      # Template agent
└── mcp/                    # MCP Tools
    ├── weather_tool/       # Weather MCP server
    ├── slack_tool/         # Slack MCP server
    ├── github_tool/        # GitHub MCP server
    ├── movie_tool/         # Movie database tool
    └── cloud_storage_tool/ # Cloud storage tool
```

**Agent Structure** (typical):
```
agent_name/
├── agent.py            # Main agent logic
├── server.py           # A2A/HTTP server wrapper
├── requirements.txt    # Dependencies
├── Dockerfile          # Container build
└── agent.yaml          # Kubernetes deployment
```

---

### 5. agentic-control-plane

**Purpose**: Kubernetes control plane composed of specialized A2A agents coordinated through Kagenti CRDs.

**Concept**: Uses AI agents themselves to manage and orchestrate the platform, creating a self-managing system.

---

### 6. kagenti-extensions

**Purpose**: Extensions and plugins for the Kagenti platform.

**Examples**:
- Custom deployers
- Additional protocol adapters
- Integration plugins

---

### 7. plugins-adapter

**Purpose**: Configuration and invocation of guardrails for the Envoy-based MCP Gateway.

**Features**:
- Request/response filtering
- Content moderation
- Rate limiting
- Custom policy enforcement

---

## Supported Protocols

### A2A (Agent-to-Agent)
- Google's standard for agent communication
- Agent discovery via Agent Cards (`/.well-known/agent-card.json`)
- JSON-RPC based task execution
- Python SDK: `a2a-sdk`

**Endpoints**:
```
GET  /.well-known/agent-card.json    # Agent Card discovery
POST /                          # Send task/message
GET  /tasks/{id}                # Get task status
```

### MCP (Model Context Protocol)
- Anthropic's protocol for tool integration
- Tool discovery and invocation
- Transport: `streamable-http` or `sse`
- Python SDK: `mcp`

**Endpoints**:
```
POST /mcp                       # JSON-RPC messages
GET  /sse                       # Server-sent events (legacy)
```

---

## Key Technologies

| Technology | Purpose | Namespace |
|------------|---------|-----------|
| **Istio Ambient** | Service mesh (mTLS, traffic mgmt) | `istio-system` |
| **SPIRE/SPIFFE** | Workload identity | `zero-trust-workload-identity-manager` |
| **Keycloak** | OAuth/OIDC identity provider | `keycloak` |
| **Shipwright** | Container image builds for agents/tools | `shipwright-build` |
| **Kubernetes Gateway API** | Ingress routing | `kagenti-system` |
| **Phoenix** | LLM observability/tracing | `kagenti-system` |
| **Kiali** | Service mesh visualization | `kagenti-system` |
| **Envoy** | MCP Gateway proxy | `gateway-system` |

---

## Development Setup

### Prerequisites
- Python ≥3.11 (backend)
- Go ≥1.21 (operators, gateway)
- Docker/Podman
- Kind, kubectl, Helm
- uv (Python package manager)

### Quick Start
```bash
# Clone main repo
git clone https://github.com/kagenti/kagenti.git
cd kagenti

# Configure secrets
cp deployments/envs/secret_values.yaml.example deployments/envs/.secret_values.yaml
# Edit .secret_values.yaml with your values

# Deploy to Kind cluster
scripts/kind/setup-kagenti.sh
```

### Access URLs (Kind)
| Service | URL |
|---------|-----|
| Kagenti UI | `http://kagenti-ui.localtest.me:8080` |
| Keycloak | `http://keycloak.localtest.me:8080` |
| Phoenix | `http://phoenix.localtest.me:8080` |
| Kiali | `http://kiali.localtest.me:8080` |
| MCP Inspector | `http://mcp-inspector.localtest.me:8080` |

Default credentials: `admin` / `admin`

---

## Kubernetes Namespaces

| Namespace | Purpose |
|-----------|---------|
| `kagenti-system` | Platform components (UI, operator, ingress) |
| `gateway-system` | MCP Gateway (Envoy proxy) |
| `mcp-system` | MCP broker/controller |
| `keycloak` | Keycloak server |
| `shipwright-build` | Shipwright build system |
| `zero-trust-workload-identity-manager` | SPIRE/SPIFFE |
| `istio-system` | Istio control plane |
| `team1`, `team2`, ... | Agent deployment namespaces |

---

## Common Labels

```yaml
# Component type
kagenti.io/type: agent | tool

# Protocol (prefix-based, multiple allowed)
protocol.kagenti.io/a2a: ""
protocol.kagenti.io/mcp: ""

# Framework
kagenti.io/framework: LangGraph | CrewAI | AG2 | Python

# Enable namespace for agents
kagenti-enabled: "true"

# Created by
app.kubernetes.io/created-by: kagenti-operator | kagenti-ui

# Shipwright build labels
kagenti.io/build-name: <build-name>      # Links BuildRun to Build
kagenti.io/shipwright-build: <build-name> # Links Agent/MCPServer to its Build
kagenti.io/built-by: shipwright          # Indicates resource was built from source

# Shipwright build annotations
kagenti.io/agent-config: <json>          # Agent config stored during build
kagenti.io/tool-config: <json>           # Tool config stored during build
```

---

## Code Style & Conventions

### Python
- Package manager: `uv`
- Linter: `pylint`
- Python ≥3.9 minimum
- Type hints required
- Apache 2.0 license headers

### Go
- Go modules
- Standard Go formatting (`gofmt`)
- Kubebuilder patterns for operators
- Apache 2.0 license headers

### Git Workflow
```bash
# Fork and clone
git clone https://github.com/<your-username>/kagenti.git
git remote add upstream https://github.com/kagenti/kagenti.git

# Create branch
git checkout -b feature/my-feature

# Rebase before PR
git fetch upstream
git rebase upstream/main

# Commit with sign-off
git commit -s -m "feat: add new feature"
```

### Pre-commit Hooks
```bash
pre-commit install
pre-commit run --all-files
```

---

## Testing

### End-to-End Tests (kagenti)
```bash
cd kagenti/tests
uv run pytest e2e/ -v
```

### Operator Tests (kagenti-operator)
```bash
cd platform-operator
make test
make test-e2e
```

### Gateway Tests (mcp-gateway)
```bash
make test
make e2e
```

---

## Debugging

### Check Operator Logs
```bash
kubectl logs -n kagenti-system -l app=kagenti-operator -f
kubectl logs -n kagenti-system -l app=platform-operator -f
```

### Check Component Status
```bash
kubectl get components -A
kubectl describe component <name> -n <namespace>
```

### Check Platform Status
```bash
kubectl get platforms -A
kubectl describe platform <name> -n <namespace>
```

### View Shipwright Builds
```bash
kubectl get builds -A
kubectl get buildruns -A
kubectl describe build <name> -n <namespace>
kubectl logs -n <namespace> -l build.shipwright.io/name=<build-name>
```

### Traces
Access Phoenix dashboard at `http://phoenix.localtest.me:8080`

### Service Mesh
Access Kiali dashboard at `http://kiali.localtest.me:8080`

---

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────────┐
│                           Kubernetes Cluster                            │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  ┌───────────────────────────────────────────────────────────────────┐  │
│  │                      kagenti-system Namespace                     │  │
│  │  ┌────────────┐  ┌────────────┐  ┌────────────┐  ┌────────────┐  │  │
│  │  │ Kagenti UI │  │  Platform  │  │  Ingress   │  │   Kiali    │  │  │
│  │  │ (Streamlit)│  │  Operator  │  │  Gateway   │  │  Phoenix   │  │  │
│  │  └────────────┘  └────────────┘  └────────────┘  └────────────┘  │  │
│  └───────────────────────────────────────────────────────────────────┘  │
│                                                                         │
│  ┌────────────────────┐  ┌────────────────────┐  ┌─────────────────┐   │
│  │  gateway-system    │  │     mcp-system     │  │    keycloak     │   │
│  │  ┌──────────────┐  │  │  ┌──────────────┐  │  │  ┌───────────┐  │   │
│  │  │ MCP Gateway  │  │  │  │ MCP Broker   │  │  │  │ Keycloak  │  │   │
│  │  │   (Envoy)    │  │  │  │ Controller   │  │  │  │  Server   │  │   │
│  │  └──────────────┘  │  │  └──────────────┘  │  │  └───────────┘  │   │
│  └────────────────────┘  └────────────────────┘  └─────────────────┘   │
│                                                                         │
│  ┌────────────────────────────────────────────────────────────────────┐ │
│  │                    Agent Namespaces (team1, team2, ...)           │ │
│  │  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────────┐ │ │
│  │  │  A2A Agents  │  │  MCP Tools   │  │   Istio Ambient Mesh     │ │ │
│  │  │  (LangGraph, │  │  (weather,   │  │  ┌────────┐ ┌─────────┐  │ │ │
│  │  │   CrewAI,    │  │   slack,     │  │  │Ztunnel │ │Waypoint │  │ │ │
│  │  │   AG2...)    │  │   github...) │  │  └────────┘ └─────────┘  │ │ │
│  │  └──────────────┘  └──────────────┘  └──────────────────────────┘ │ │
│  └────────────────────────────────────────────────────────────────────┘ │
│                                                                         │
│  ┌────────────────────────────────────────────────────────────────────┐ │
│  │              zero-trust-workload-identity-manager                  │ │
│  │  ┌────────────────┐  ┌────────────────┐  ┌──────────────────────┐ │ │
│  │  │  SPIRE Server  │  │  SPIRE Agent   │  │  SPIFFE CSI Driver   │ │ │
│  │  └────────────────┘  └────────────────┘  └──────────────────────┘ │ │
│  └────────────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## License

All Kagenti repositories are licensed under **Apache 2.0**.

---

## Contributing

See [CONTRIBUTING.md](https://github.com/kagenti/kagenti/blob/main/CONTRIBUTING.md) for guidelines.

Key points:
- Fork the repository
- Create feature branches
- Sign off commits (`git commit -s`)
- Follow conventional commits (recommended)
- Run pre-commit hooks
- Submit PR with clear description

