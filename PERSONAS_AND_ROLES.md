# Kagenti Project Personas and Roles Documentation

This document outlines the core personas that the Kagenti platform serves across its repository ecosystem.

## Overview

Kagenti is a cloud-native middleware platform that provides framework-neutral, scalable, and secure infrastructure for deploying and orchestrating AI agents. The platform serves three primary persona categories: **Developers**, **Operators/Administrators**, and **End Users**.

---

## 1. Developer Personas

### 1.1 Agent Developer

**Description**: Developers who create AI agents using various frameworks.

**Primary Repository**: [agent-examples](https://github.com/kagenti/agent-examples)

**Frameworks Supported**:

- **LangGraph** - Complex orchestration with high degree of workflow control
- **CrewAI** - Role-based agent task assignment and autonomous goal achievement
- **AG2** - Multi-agent conversation frameworks
- **Llama Stack** - Pre-built state machines focused on ReAct-style patterns
- **BeeAI** - Bee agent framework implementations

**Key Activities**:

- Develop agents using their preferred framework
- Integrate agents with A2A (Agent-to-Agent) protocol
- Configure agent behavior, prompts, and model parameters
- Test agent interactions with tools and other agents

**Getting Started**:

1. Review instructions in [new-agent](docs/new-agent.md) documentation
2. Clone [agent-examples](https://github.com/kagenti/agent-examples) repository
3. Explore framework-specific examples (`a2a/slack_researcher`, `a2a/weather_service`)
4. Use sample Dockerfiles and configurations as templates
5. Access Kagenti UI and navigate to "Import New Agent"
6. Deploy using your GitHub repository

---

### 1.2 Tool Developer

**Description**: Developers who create Model Context Protocol (MCP) tools that agents can interact with.

**Primary Repository**: [agent-examples](https://github.com/kagenti/agent-examples)

**Tool Categories**:

- **Slack Tool** (`mcp/slack_tool`) - Workspace interactions, channel management
- **GitHub Tool** (`mcp/github_tool`) - Repository management, issue tracking
- **Weather Tool** (`mcp/weather_tool`) - Weather data retrieval and forecasting
- **Custom MCP Tools** - Domain-specific enterprise tools

**Key Activities**:

- Implement MCP-compliant tools using examples as templates
- Define tool capabilities and permissions
- Configure tool authentication and authorization via MCP Gateway
- Integrate with external APIs and services

**Getting Started**:

1. Study MCP tool examples in [agent-examples](https://github.com/kagenti/agent-examples) (`mcp/slack_tool`, `mcp/weather_tool`)
2. Implement your tool following MCP protocol standards
3. Create appropriate Dockerfile and configuration files
4. Access "Import New Tool" in Kagenti UI
5. Register tool with MCP Gateway for discovery

---

### 1.3 MCP Gateway Developer

**Description**: Go developers who build and maintain the Envoy-based MCP Gateway that connects agents to tools via the Model Context Protocol.

**Primary Repository**: [mcp-gateway](https://github.com/kagenti/mcp-gateway)

**Key Responsibilities**:

- Develop and extend MCP Gateway core functionality
- Implement centralized routing for multiple MCP servers and virtual MCP servers
- Build Kubernetes-native control plane features with custom CRDs
- Develop automatic backend discovery via HTTPRoute integration
- Implement Kuadrant support for authorization and token exchange policies
- Create and maintain Envoy filter extensions

**Technical Skills**:

- Go programming language
- Envoy Proxy internals and filter development
- Model Context Protocol (MCP) specification
- Kubernetes CRD design and controller development
- Gateway API (HTTPRoute, Gateway resources)

**Getting Started**:

1. Clone [mcp-gateway](https://github.com/kagenti/mcp-gateway) repository
2. Set up Go development environment
3. Study Envoy proxy architecture and filter development
4. Understand MCP protocol specification and implementation
5. Explore existing CRD controllers and HTTPRoute integrations

---

### 1.4 Operator Developer

**Description**: Go developers who build and maintain Kubernetes operators for the Kagenti ecosystem.

**Primary Repository**: [kagenti-operator](https://github.com/kagenti/kagenti-operator)

**Key Responsibilities**:

- Develop and maintain the kagenti-operator
- Create custom resource definitions (CRDs) for agents and components
- Implement controller logic for agent/tool lifecycle management
- Build operator extensions and integrations
- Manage operator versioning and releases

**CRDs Managed**:

- `agents.kagenti.operator.dev/v1alpha1`
- `components.kagenti.operator.dev/v1alpha1`
- `mcpserverregistrations.mcp.kagenti.com/v1alpha1`

**Technical Skills**:

- Go programming language
- Kubernetes operator framework (controller-runtime)
- Custom Resource Definition (CRD) design
- Controller pattern and reconciliation loops
- Helm chart development and OCI registry management

**Getting Started**:

1. Clone [kagenti-operator](https://github.com/kagenti/kagenti-operator) repository
2. Set up Go development environment
3. Study existing CRDs and controller implementations
4. Develop custom operators using controller-runtime
5. Package operators as OCI Helm charts

---

### 1.5 Extensions Developer

**Description**: Developers who create extensions and plugins to extend Kagenti platform capabilities.

**Primary Repositories**:

- [kagenti-extensions](https://github.com/kagenti/kagenti-extensions) - Core extensions (Go)
- [plugins-adapter](https://github.com/kagenti/plugins-adapter) - Guardrails and policy plugins (Python)
- [agentic-control-plane](https://github.com/kagenti/agentic-control-plane) - A2A control plane agents (Python)

**Extension Types**:

- **Protocol Extensions** - New communication protocols beyond A2A and MCP
- **Framework Integrations** - Support for additional AI frameworks
- **Tool Connectors** - Integrations with enterprise systems
- **Guardrails Plugins** - Content safety and policy enforcement
- **Control Plane Agents** - Autonomous Kubernetes management agents

**Technical Skills**:

- Go programming (for kagenti-extensions)
- Python programming (for plugins-adapter, agentic-control-plane)
- Kubernetes API and controller development
- Plugin architecture design

**Getting Started**:

1. Clone the relevant extensions repository
2. Study existing extension patterns and APIs
3. Develop extensions using Go or Python
4. Test extensions with main platform
5. Submit contributions via pull requests

---

### 1.6 UI Developer

**Description**: Developers who build and maintain the Kagenti user interface and dashboard.

**Primary Repository**: [kagenti](https://github.com/kagenti/kagenti) (UI components in `kagenti/ui-v2/` and `kagenti/backend/`)

**Key Responsibilities**:

- Develop and maintain the Kagenti web dashboard
- Build agent and tool management interfaces
- Create observability and monitoring dashboards
- Implement identity management UI components
- Design user-friendly agent interaction experiences

**Technical Skills**:

- TypeScript/React (PatternFly UI framework)
- Python (FastAPI for backend)
- Frontend development and UI/UX design
- REST API integration
- OAuth2/OIDC authentication flows

**Getting Started**:

1. Clone [kagenti](https://github.com/kagenti/kagenti) repository
2. Navigate to `kagenti/ui-v2/` (frontend) and `kagenti/backend/` (API) directories
3. Study existing UI components and architecture
4. Set up local development environment
5. Test UI changes with local Kagenti deployment

---

## 2. Operator/Administrator Personas

### 2.1 Platform Operator (Admin)

**Description**: Administrators responsible for deploying, managing, and operating the Kagenti platform infrastructure.

**Primary Repository**: [kagenti](https://github.com/kagenti/kagenti) (Ansible installer and UI)

**Key Responsibilities**:

- Deploy Kagenti platform using the Ansible-based installer (`deployments/ansible/run-install.sh --env dev`).
- Manage platform component lifecycle:
  - **Core Components**: registry, tekton, cert-manager, operator, istio, spire
  - **Gateway Components**: mcp-gateway, ingress-gateway, shared-gateway-access
  - **Security Components**: keycloak, metrics-server, inspector
- Configure networking and service mesh (Istio Ambient)
- Set up monitoring and alerting (Kiali, Phoenix)
- Manage agent and tool deployments via CRDs
- Monitor platform health and performance

**Tools Used**:

- Ansible-based installer (`deployments/ansible/run-install.sh`)
- Kubernetes CLI tools (`kubectl`)
- Kagenti UI dashboard
- Observability dashboards (Kiali, Phoenix, MCP Inspector)

**Getting Started**:

1. Install Kagenti using the Ansible-based installer: `deployments/ansible/run-install.sh --env dev`
2. Configure cluster components as needed
3. Set up monitoring and observability
4. Enable agent and tool namespaces with proper labels
5. Deploy kagenti-operator for CRD management

---

### 2.2 MCP Gateway Operator (Admin)

**Description**: Administrators who manage the MCP Gateway infrastructure and protocol routing.

**Primary Repository**: [mcp-gateway](https://github.com/Kuadrant/mcp-gateway)

**Key Responsibilities**:

- Configure and maintain Envoy-based MCP Gateway
- Manage HTTPRoute configurations for tool discovery
- Set up protocol federation and load balancing
- Configure MCPServerRegistration custom resources
- Troubleshoot MCP protocol communication issues
- Monitor gateway performance and scaling
- Manage gateway security and access control

**Tools Used**:

- MCP Gateway admin interfaces
- Envoy configuration tools
- Gateway API resources (`gateway.networking.k8s.io`)
- MCP Inspector for protocol debugging
- HTTPRoute configurations

**Technical Skills**:

- Envoy Proxy configuration and management
- Kubernetes Gateway API (HTTPRoute, Gateway resources)
- Protocol debugging and network troubleshooting
- Service mesh networking (Istio integration)

**Getting Started**:

1. Understand Envoy-based gateway architecture
2. Configure HTTPRoute resources for tool registration
3. Set up MCPServerRegistration custom resources
4. Monitor gateway performance and scaling
5. Troubleshoot protocol routing issues

---

### 2.3 Security and Identity Specialist

**Description**: Administrators responsible for implementing and maintaining the zero-trust security model and identity management.
Review Identity Patterns in [identity documentation](docs/identity-guide.md) for more information.

**Key Responsibilities**:

- SPIFFE/SPIRE identity management and workload attestation
- Keycloak realm, client, and role configuration
- OAuth2 token exchange policy implementation
- User lifecycle and permission management
- Security policy definition and enforcement
- Compliance monitoring and audit

**Security Technologies**:

- **SPIRE** - Workload identity and attestation
- **Keycloak** - Identity and access management
- **OAuth2 Token Exchange** - Secure delegation
- **SPIFFE JWT** - Machine identity

**Management Tools**:

- Keycloak Admin Console (`http://keycloak.localtest.me:8080`)
- Kagenti UI Admin page
- SPIRE server management tools
- Identity management scripts

**Getting Started**:

1. Access Keycloak Admin Console
2. Configure users, roles, and client scopes for different access levels
3. Set up SPIFFE/SPIRE identity management and attestation
4. Implement token exchange policies for secure delegation
5. Monitor security events and compliance

---

## 3. End User Persona

### 3.1 End User

**Description**: Business users and developers who interact with deployed agents through the Kagenti UI or APIs.

**User Access Levels**:

- **Full Access Users** - Complete permissions for all agent capabilities
- **Partial Access Users** - Limited permissions based on business roles
- **Read-Only Users** - View-only access to agent outputs

**Key Activities**:

- Submit queries and requests to agents via Kagenti UI
- Review agent responses and outputs
- Monitor agent task execution
- Access agent-generated reports and insights
- Interact with agents through REST APIs

**Integration Types**:

- Kagenti UI dashboard
- REST API clients
- A2A protocol consumers
- Webhook receivers

**Getting Started**:

1. Login with provided credentials
2. Navigate to "Agent Catalog" to see deployed agents
3. Use "Tool Catalog" to explore available tools
4. Access "Observability" for monitoring and debugging
5. Interact with agents using natural language prompts

---

## Role-Based Access Control (RBAC) Matrix

| Persona | Keycloak Admin | Agent Deploy | Tool Deploy | UI Access | API Access | Infrastructure | Gateway Config | Operator CRDs |
|---------|---------------|--------------|-------------|-----------|------------|----------------|---------------|---------------|
| Agent Developer | ❌ | ✅ | ❌ | ✅ | ✅ | ❌ | ❌ | ❌ |
| Tool Developer | ❌ | ❌ | ✅ | ✅ | ✅ | ❌ | ✅ | ❌ |
| MCP Gateway Developer | ❌ | ❌ | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Operator Developer | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ | ✅ |
| Extensions Developer | ❌ | ❌ | ❌ | ✅ | ✅ | ❌ | ✅ | ✅ |
| UI Developer | ❌ | ❌ | ❌ | ✅ | ✅ | ❌ | ❌ | ❌ |
| Platform Operator | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| MCP Gateway Operator | ❌ | ❌ | ❌ | ✅ | ✅ | ✅ | ✅ | ❌ |
| Security Specialist | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| End User | ❌ | ❌ | ❌ | ✅ | ✅ | ❌ | ❌ | ❌ |

---

## Repository-Persona Mapping

| Repository | Primary Personas |
|------------|------------------|
| **[kagenti](https://github.com/kagenti/kagenti)** | Platform Operator, UI Developer, End User |
| **[agent-examples](https://github.com/kagenti/agent-examples)** | Agent Developer, Tool Developer |
| **[mcp-gateway](https://github.com/kagenti/mcp-gateway)** | MCP Gateway Developer, MCP Gateway Operator |
| **[kagenti-operator](https://github.com/kagenti/kagenti-operator)** | Operator Developer, Platform Operator |
| **[kagenti-extensions](https://github.com/kagenti/kagenti-extensions)** | Extensions Developer |
| **[agentic-control-plane](https://github.com/kagenti/agentic-control-plane)** | Extensions Developer, Agent Developer |
| **[plugins-adapter](https://github.com/kagenti/plugins-adapter)** | Extensions Developer, Security Specialist |
| **[.github](https://github.com/kagenti/.github)** | UI Developer |

---

## Conclusion

The Kagenti platform serves **10 core personas** across eight specialized repositories:

- **Developers** (6): Agent, Tool, MCP Gateway, Operator, Extensions, UI
- **Operators/Administrators** (3): Platform Operator, MCP Gateway Operator, Security Specialist
- **End Users** (1): End User

**Get Involved**:

- 🌐 **Website**: [kagenti.io](http://kagenti.io)
- 💬 **Discord**: [Join our community](https://discord.gg/aJ92dNDzqB)
- 📖 **Blog**: [Kagenti Medium Publication](https://medium.com/kagenti-the-agentic-platform)
- 🐙 **GitHub**: [github.com/kagenti](https://github.com/kagenti)
