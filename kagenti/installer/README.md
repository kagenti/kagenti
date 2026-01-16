# Kagenti Installer

The Kagenti installer deploys a comprehensive agentic platform across multiple Kubernetes namespaces, creating a secure, scalable environment for running AI agents and tools. The following diagram illustrates the cluster-wide architecture and how components are organized:

```shell
┌───────────────────────────────────────────────────────────────────────┐
│                           Kubernetes Cluster                          │
├───────────────────────────────────────────────────────────────────────┤
│                                                                       │
│  ┌─────────────────────────────────────────────────────────────────┐  │
│  │                      kagenti-system Namespace                   │  │
│  │  ┌────────────┐  ┌────────────┐  ┌────────────┐  ┌────────────┐ │  │
│  │  │ Kagenti UI │  │  Agent     │  │  Ingress   │  │   Kiali    │ │  │
│  │  │            │  │  Lifecycle │  │  Gateway   │  │            │ │  │
│  │  │            │  │  Operator  │  │            │  │            │ │  │
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

### Component Overview

**Platform Services (`kagenti-system`):**
- **Kagenti UI**: Web-based dashboard for managing agents, tools, and monitoring platform health
- **Agent Lifecycle Operator**: Kubernetes operator that manages the complete lifecycle of AI agents
- **Ingress Gateway**: Entry point for external traffic, providing secure routing and load balancing
- **Kiali**: Service mesh observability tool for visualizing traffic flows and service dependencies

**Workload Namespaces:**
Isolated environments where user agents and tools run. These can be organized by team, project, or environment, providing multi-tenancy and resource isolation. Supports:
- **A2A Agents**: Framework-agnostic agents built with LangGraph, CrewAI, AutoGen2, and others
- **MCP Tools**: Model Context Protocol servers providing standardized tool interfaces
- **Custom Workloads**: Any additional services or applications required by your agents

**Gateway Services:**
- **MCP Gateway** (`gateway-system`): Envoy-based gateway that routes and enforces policies for MCP protocol traffic
- **MCP Broker Controller** (`mcp-system`): Manages MCP server discovery, registration, and lifecycle coordination

**Infrastructure Layer:**
- **SPIRE**: Provides workload identity and mTLS certificate management for zero-trust security
- **IAM (Keycloak)**: Identity and access management for user authentication and authorization
- **Istio Ambient**: Service mesh providing secure communication, traffic management, and observability without sidecar proxies