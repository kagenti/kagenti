
# Rossoctl

[![CI](https://github.com/rossoctl/rossoctl/actions/workflows/ci.yaml/badge.svg)](https://github.com/rossoctl/rossoctl/actions/workflows/ci.yaml)
[![E2E K8s 1.35.0 (Kind)](https://github.com/rossoctl/rossoctl/actions/workflows/e2e-kind.yaml/badge.svg)](https://github.com/rossoctl/rossoctl/actions/workflows/e2e-kind.yaml)
[![E2E OCP 4.20.21 (HyperShift)](https://github.com/rossoctl/rossoctl/actions/workflows/e2e-hypershift.yaml/badge.svg)](https://github.com/rossoctl/rossoctl/actions/workflows/e2e-hypershift.yaml)
[![OpenSSF Scorecard](https://api.securityscorecards.dev/projects/github.com/rossoctl/rossoctl/badge)](https://scorecard.dev/viewer/?uri=github.com/rossoctl/rossoctl)
[![GitHub Release](https://img.shields.io/github/v/release/rossoctl/rossoctl)](https://github.com/rossoctl/rossoctl/releases/latest)
[![License](https://img.shields.io/github/license/rossoctl/rossoctl)](LICENSE)
[![Slack](https://img.shields.io/badge/Slack-Join%20us-4A154B?logo=slack&logoColor=white)](https://ibm.biz/rossoctl-slack)

**Rossoctl** is a cloud-native middleware providing a *framework-neutral*, *scalable*, and *secure* platform for deploying and orchestrating AI agents through standardized agent communication protocols (A2A, MCP).

| Included Services: |  |
|--------------------|--------|
| - Zero-Trust Security Architecture<br>- Authentication and Authorization<br>- Trusted workload identity (SPIRE)<br>- Deployment and Configuration<br>- Scaling and Fault-tolerance<br>- Discovery of agents and tools<br>- State Persistence | <img src="banner.png" width="400"/> |

## Why Rossoctl?

Despite the extensive variety of frameworks available for developing agent-based applications (LangGraph, CrewAI, AG2, etc.), there is a distinct lack of standardized methods for deploying and operating agent code in production environments. Agents are adept at reasoning, planning, and interacting with tools, but their full potential is often limited by:

- **Deployment Complexity** - Each framework requires custom deployment scripts and infrastructure
- **Security Gaps** - No standardized approach to authentication, authorization, and workload identity
- **Protocol Fragmentation** - Agents and tools use different communication patterns
- **Operational Overhead** - Scaling, monitoring, and lifecycle management require custom solutions

Rossoctl addresses these challenges by enhancing existing agent frameworks with production-ready, framework-neutral infrastructure.

## Supported AI Use‑Case Types
Rossoctl is designed to support a broad range of AI‑agent deployment patterns, including knowledge services, synchronous and asynchronous user‑authorized assistants, continuous monitoring agents, and event‑driven workflows.

See the full list and definitions in the **[Rossoctl Use Cases](./docs/use-case-types.md)** document.

## Architecture

The goal of Rossoctl is to provide a pluggable agentic platform blueprint. Key functionalities are currently organized into four key pillars:
1. Lifecycle Orchestration
2. Networking
3. Security
4. Observability

Under each of these pillars are logical components that support the workload runtime.

```
┌─────────────────────────────────────────────────────────────────────────────────────────┐
│                                         ROSSOCTL PLATFORM                                │
├─────────────────────────────────────────────────────────────────────────────────────────┤
│                                                                                         │
│  ┌───────────────────────────────────────────────────────────────────────────────────┐  │
│  │                                  ROSSOCTL UI*                                      │  │
│  │          (Dashboard: Deploy, Test, Monitor Agents & Tools + Backend API)          │  │
│  └───────────────────────────────────────────────────────────────────────────────────┘  │
│                                                 │                                       │
│                                                 ▼                                       │
│  ┌───────────────────────────────────────────────────────────────────────────────────┐  │
│  │                                    WORKLOAD RUNTIME                               │  │
│  │   ┌──────────────────────┐    ┌──────────────────────┐    ┌───────────────────┐   │  │
│  │   │       AGENTS         │    │        TOOLS         │    │      SKILLS       │   │  │
│  │   │  (A2A - LangGraph,   │    │  (MCP Protocol       │    │    (Reusable      │   │  │
│  │   │   CrewAI, Marvin,    │    │   Servers)           │    │   capabilities)   │   │  │
│  │   │   Autogen, etc.)     │    │                      │    │                   │   │  │
│  │   └──────────────────────┘    └──────────────────────┘    └───────────────────┘   │  │
│  └───────────────────────────────────────────────────────────────────────────────────┘  │
│                                                 │                                       │
├─────────────────────────────────────────────────┼───────────────────────────────────────┤
│                                        PLATFORM PILLARS                                 │
│                                                 │                                       │
│  ┌──────────────────┐  ┌──────────────────┐  ┌──────────────────┐  ┌────────────────┐   │
│  │    LIFECYCLE     │  │    NETWORKING    │  │     SECURITY     │  │  OBSERVABILITY │   │
│  │  ORCHESTRATION   │  │                  │  │                  │  │                │   │
│  ├──────────────────┤  ├──────────────────┤  ├──────────────────┤  ├────────────────┤   │
│  │                  │  │                  │  │                  │  │                │   │
│  │   Agents/Tools   │  │   Tool Routing   │  │  Identity & Auth │  │    Tracing     │   │
│  │   Lifecycle &    │  │    & Policy      │  │   (AuthBridge*)  │  │(MLflow,Langflow│   │
│  │   Discovery      │  │  (MCP Gateway)   │  │                  │  │ Phoenix)       │   │
│  │ (k8s workloads,  │  │                  │  │                  │  │                │   │
│  │ labels,          │  ├──────────────────┤  ├──────────────────┤  ├────────────────┤   │
│  │  AgentCard CRD*) │  │                  │  │                  │  │                │   │
│  │                  │  │  Service Mesh    │  │    OAuth/OIDC    │  │   Network      │   │
│  │                  │  │ (Istio/Ambient)  │  │    (Keycloak)    │  │ Visualization  │   │
│  │                  │  │                  │  │                  │  │   (Kiali)      │   │
│  │   Container      │  ├──────────────────┤  ├──────────────────┤  │                │   │
│  │     Builds       │  │                  │  │                  │  │                │   │
│  │  (Shipwright)    │  │ Ingress/Routing  │  │ Workload Identity│  │                │   │
│  │                  │  │ (Gateway API)    │  │ (SPIFFE/SPIRE)   │  │                │   │
│  │                  │  │                  │  │                  │  │                │   │
│  └──────────────────┘  └──────────────────┘  └──────────────────┘  └────────────────┘   │
│                                                                                         │
├─────────────────────────────────────────────────────────────────────────────────────────┤
│                                 KUBERNETES / OPENSHIFT                                  │
└─────────────────────────────────────────────────────────────────────────────────────────┘
* = Built by Rossoctl
```

## Core Components

Rossoctl provides a set of components and assets that make it easier to manage AI agents and tools and integrate their fine-grained authorization into modern cloud-native environments.

| Component | Description |
|-----------|-------------|
| **[Rossoctl UI](./rossoctl/ui-v2/)** | Dashboard for deploying agents/tools as Kubernetes Deployments, interactive testing, and monitoring |
| **[Identity & Auth Bridge](./docs/identity-guide.md)** | Identity pattern assets that capture common authorization scenarios and provide reusable building blocks for implementing consistent authorization across services |
| **[Agent Lifecycle Operator](https://github.com/rossoctl/operator)** | Kubernetes admission webhook for building agents from source, managing lifecycle, and coordinating platform services |
| **[MCP Gateway](https://github.com/Kuadrant/mcp-gateway/blob/main/README.md)** | Unified gateway for Model Context Protocol (MCP) servers and tools. It acts as the entry point for policy enforcement, handling requests and routing them through the appropriate authorization patterns |
| **[Plugins adapter](https://github.com/rossoctl/plugins-adapter)** | Adapter for security and safety plugins for Envoy-based gateways |

## Quick Start

### Prerequisites

- Python ≥3.9 with [uv](https://docs.astral.sh/uv/getting-started/installation) installed
- Docker Desktop, Rancher Desktop, or Podman (16GB RAM, 4 cores recommended)
- [Kind](https://kind.sigs.k8s.io), [kubectl](https://kubernetes.io/docs/tasks/tools/), [Helm](https://helm.sh/docs/intro/install/)
- [Ollama](https://ollama.com/download) for local LLM inference

### Install

```bash
# Clone the repository
git clone https://github.com/rossoctl/rossoctl.git
cd rossoctl

# Check out the latest release
git checkout v0.6.0

# Copy and configure secrets (optional)
cp charts/rossoctl/.secrets_template.yaml charts/rossoctl/.secrets.yaml
# Edit charts/rossoctl/.secrets.yaml with your values

# Deploy to Kind cluster
scripts/kind/setup-rossoctl.sh --with-ui --with-spire --with-agent-sandbox --with-builds
```

Use `scripts/kind/setup-rossoctl.sh --help` for all available options. For detailed instructions including OpenShift, refer to the [Installation Guide](./docs/install.md).

### Access the UI

```bash
# Show service URLs and credentials
.github/scripts/local-setup/show-services.sh

open http://rossoctl-ui.localtest.me:8080
# Login with credentials from show-services.sh output
```

From the UI you can:
- Import and deploy A2A agents from any framework
- Deploy MCP tools directly from source
- Test agents interactively
- Monitor traces and network traffic

To learn how to deploy agents and MCP tools, follow the **[Weather Agent Demo](https://github.com/rossoctl/rossocortex/blob/main/authbridge/demos/weather-agent/demo-ui.md)** — the recommended getting-started tutorial that walks you through deploying an agent and tool via the UI and chatting with it end-to-end. For more demos, see the [full demo list](./docs/demos/README.md).

## Documentation

| Topic | Link |
|-------|------|
| **Installation** | [Installation Guide](./docs/install.md) (Kind & OpenShift) |
| **Components** | [Component Details](./docs/components.md) |
| **Demos & Tutorials** | [Demo Documentation](./docs/demos/README.md) |
| **Developing Rossoctl Apps** | [Application Development Guide](./docs/developing-rossoctl-app.md) · [App Demo Example](./rossoctl/examples/app-demo/README.md) |
| **Import Your Own Agent** | [New Agent Guide](./docs/new-agent.md) |
| **Import Your Own Tool** | [New Tool Guide](./docs/new-tool.md) |
| **Skills Configuration & Usage** | [Skills Guide](./docs/skills.md) |
| **Architecture Details** | [Technical Details](./docs/tech-details.md) |
| **Identity, Security, and Auth Bridge** | [Identity and Auth Bridge](./docs/identity-guide.md) |
| **Fine-Grained Zero-Trust Access Control** | [Access Control](./docs/access-control/README.md) |
| **Developer Guide** | [Contributing](./docs/dev-guide.md) |
| **Troubleshooting** | [Troubleshooting Guide](./docs/troubleshooting.md) |
| **Blog Posts** | [Rossoctl Blog](./docs/blogs.md) |

## Supported Protocols

- **[A2A (Agent-to-Agent)](https://a2a-protocol.org/latest/)** — Standard protocol for agent communication
- **[MCP (Model Context Protocol)](https://modelcontextprotocol.io)** — Protocol for tool/server integration

## Contributing

We welcome contributions! See [CONTRIBUTING.md](./CONTRIBUTING.md) for guidelines.

## Contact

To reach the maintainer team, email **rossoctl-maintainers@googlegroups.com** or join us on [Slack](https://ibm.biz/rossoctl-slack).

## License

[Apache 2.0](./LICENSE)

## QR Code for Rossoctl.io

This QR Code links to <http://rossoctl.io>

![Rossoctl.io QR Code](./docs/images/Rossoctl.QRcode.png)
