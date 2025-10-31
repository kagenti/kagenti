# Kagenti Project Personas and Roles Documentation

This document outlines all the personas and roles that the Kagenti platform references or serves across its **all-repository ecosystem**. The Kagenti platform is designed to support a diverse ecosystem of users involved in developing, deploying, managing, and consuming AI agents in cloud-native environments.

## Overview

Kagenti is a cloud-native middleware platform that provides framework-neutral, scalable, and secure infrastructure for deploying and orchestrating AI agents. The platform serves multiple distinct personas across the AI agent lifecycle, from development to production deployment and end-user consumption.

---

## 1. Primary Development Personas

### 1.1 AI Agent Developers

**Description**: Software developers who create intelligent agents using various AI frameworks.

**Frameworks Supported**:

- **LangGraph** - For complex orchestration with high degree of workflow control
- **CrewAI** - For role-based agent task assignment and autonomous goal achievement
- **AG2** - Multi-agent conversation frameworks
- **Llama Stack** - Pre-built state machines focused on ReAct-style patterns
- **BeeAI** - Bee agent framework implementations

**Key Activities**:

- Develop agents using their preferred framework
- Integrate agents with A2A (Agent-to-Agent) protocol
- Configure agent behavior, prompts, and model parameters
- Test agent interactions with tools and other agents

**Kagenti Benefits**:

- Framework-neutral deployment platform
- Standardized REST API exposure
- Seamless scaling and configuration management
- Integrated security and identity management

### 1.2 Tool Developers

**Description**: Developers who create Model Context Protocol (MCP) tools that agents can interact with.

**Primary Repository**: [agent-examples](https://github.com/kagenti/agent-examples)

**Tool Categories** (from agent-examples):

- **Sample Communication Tools**:
  - **Slack Tool** (`mcp/slack_tool`) - Workspace interactions, channel management
  - **GitHub Tool** (`mcp/github_tool`) - Repository management, issue tracking
- **Sample Information Tools**:
  - **Weather Tool** (`mcp/weather_tool`) - Weather data retrieval and forecasting
- **Custom MCP Tools** - Domain-specific enterprise tools

**Agent Integration Examples**:

- **A2A Slack Researcher** (`a2a/slack_researcher`) - Research agent with Slack integration
- **Weather Service Agent** (`a2a/weather_service`) - Weather information agent
- **Github Issue Agent** (`a2a/github_issue_agent`) - Github issue agent
- **Multi-framework Support** - Examples for LangGraph, CrewAI, AG2, Llama Stack, BeeAI

**Key Activities**:

- Implement MCP-compliant tools using examples as templates
- Define tool capabilities and permissions
- Configure tool authentication and authorization via MCP Gateway
- Integrate with external APIs and services
- Contribute sample implementations to agent-examples repository

**Kagenti Benefits**:

- Standardized MCP protocol support via mcp-gateway
- Automatic tool discovery and registration through Kubernetes operator
- Secure tool-to-agent communication with SPIFFE/SPIRE integration
- Scalable tool deployment with sample Dockerfiles and configurations

---

### 1.3 Extension Developers

**Description**: Developers who create extensions and plugins to extend Kagenti platform capabilities.

**Primary Repository**: [kagenti-extensions](https://github.com/kagenti/kagenti-extensions)

**Extension Types**:

- **Protocol Extensions** - New communication protocols beyond A2A and MCP
- **Framework Integrations** - Support for additional AI frameworks
- **Tool Connectors** - Integrations with enterprise systems
- **UI Extensions** - Custom dashboard components and widgets
- **Operator Extensions** - Custom resource definitions and controllers

**Key Activities**:

- Develop custom Kubernetes operators and CRDs
- Create framework-specific agent adapters
- Build enterprise integration connectors
- Design UI components and dashboard extensions
- Implement security and compliance plugins

**Technical Skills**:

- Go programming (primary language for extensions)
- Kubernetes API and controller development
- Frontend development (for UI extensions)
- Protocol design and implementation
- Enterprise integration patterns

---

## 2. Platform Operation Personas

### 2.1 Platform Engineers/DevOps Engineers

**Description**: Engineers responsible for deploying, managing, and scaling the Kagenti platform infrastructure.

**Key Responsibilities**:

- Kubernetes cluster management and configuration
- Platform component deployment (Istio, SPIRE, Keycloak, etc.)
- Infrastructure as Code implementation
- Monitoring and observability setup
- Disaster recovery and backup strategies

**Primary Repository**: [kagenti](https://github.com/kagenti/kagenti) (installer and UI)

**Tools Used**:

- `kagenti-installer` CLI tool
- Kubernetes manifests and Helm charts  
- [kagenti-operator](https://github.com/kagenti/kagenti-operator) components
- [mcp-gateway](https://github.com/kagenti/mcp-gateway) for protocol routing

**Key Activities**:

- Deploy Kagenti platform using installer
- Manage component lifecycle:
  - **Core Components**: registry, tekton, cert-manager, operator, istio, spire
  - **Gateway Components**: mcp-gateway, ingress-gateway, shared-gateway-access
  - **Security Components**: keycloak, metrics-server, inspector
  - **Extensions**: toolhive-operator, kagenti-extensions
- Configure networking and service mesh (Istio Ambient)
- Set up monitoring and alerting (Kiali, Phoenix)
- Manage MCP Gateway routing and protocol federation

### 2.2 Platform Operators

**Description**: Day-to-day operators who manage running Kagenti platform instances.

**Primary Repository**: [kagenti-operator](https://github.com/kagenti/kagenti-operator)

**Key Responsibilities**:

- Monitor platform health and performance
- Manage agent and tool deployments via CRDs
- Troubleshoot operational issues using operator logs
- Perform routine maintenance tasks
- Manage MCP Gateway configurations and routing
- Handle Kubernetes operator lifecycle and updates

**Tools Used**:

- Kagenti UI dashboard
- Kubernetes CLI tools (`kubectl`, CRDs: `agents.kagenti.operator.dev`, `components.kagenti.operator.dev`)
- Operator-specific tools (`mcpservers.mcp.kagenti.com` CRDs)
- Observability dashboards (Kiali, Phoenix, MCP Inspector)
- Gateway management tools (Envoy admin, HTTPRoute configurations)

### 2.3 Gateway Administrators

**Description**: Specialists who manage the MCP Gateway infrastructure and protocol routing.

**Primary Repository**: [mcp-gateway](https://github.com/kagenti/mcp-gateway)

**Key Responsibilities**:

- Configure and maintain Envoy-based MCP Gateway
- Manage HTTPRoute configurations for tool discovery
- Set up protocol federation and load balancing
- Troubleshoot MCP protocol communication issues
- Monitor gateway performance and scaling

**Technical Skills**:

- Envoy Proxy configuration and management
- Kubernetes Gateway API (HTTPRoute, Gateway resources)
- Go programming for gateway customizations
- Protocol debugging and network troubleshooting
- Service mesh networking (Istio integration)

**Tools Used**:

- MCP Gateway admin interfaces
- Envoy configuration tools
- Gateway API resources (`gateway.networking.k8s.io`)
- MCP Inspector for protocol debugging
- Network traffic analysis tools

---

## 3. Security & Identity Management Personas

### 3.1 Security Engineers/Administrators

**Description**: Security professionals responsible for implementing and maintaining the zero-trust security model.

**Key Responsibilities**:

- SPIFFE/SPIRE identity management
- OAuth2 token exchange configuration
- Least-privilege access enforcement
- Security policy definition and enforcement

**Security Technologies**:

- **SPIRE** - For workload identity and attestation
- **Keycloak** - For identity and access management
- **OAuth2 Token Exchange** - For secure delegation
- **SPIFFE JWT** - For machine identity

**Key Activities**:

- Configure SPIRE trust domains and identities
- Set up Keycloak realms, clients, and roles
- Implement token exchange policies
- Monitor security events and compliance

### 3.2 Identity Administrators

**Description**: Administrators who manage user identities, roles, and permissions within the platform.

**Key Responsibilities**:

- User lifecycle management
- Role and permission assignment
- Client registration and management
- Authentication policy configuration

**Management Tools**:

- Keycloak Admin Console
- Kagenti UI Admin page
- Identity management scripts

---

## 4. End User Personas

### 4.1 Agent End Users

**Description**: Business users who interact with deployed agents through the Kagenti UI or APIs.

**User Access Levels**:

- **Full Access Users** - Complete permissions for all agent capabilities
- **Partial Access Users** - Limited permissions based on business roles
- **Read-Only Users** - View-only access to agent outputs

**Key Activities**:

- Submit queries and requests to agents
- Review agent responses and outputs
- Monitor agent task execution
- Access agent-generated reports and insights

### 4.2 Demonstration Users (Testing/Demo Personas)

**Description**: Specialized user accounts created for testing different access levels and capabilities.

**Slack Demo Users**:

- `slack-full-access-user` - Full Slack API access (channels:history, channels:read)
- `slack-partial-access-user` - Limited Slack access (channels:read only)

**GitHub Demo Users**:

- `github-full-access-user` - Complete GitHub repository access
- `github-partial-access-user` - Limited GitHub permissions

**Authentication**:

- Default credentials: `password` for demo users
- Admin credentials: `admin/admin`

### 4.3 API Consumers

**Description**: Developers and systems that interact with agents programmatically through standardized APIs.

**Integration Types**:

- REST API clients
- A2A protocol consumers
- Webhook receivers
- Event-driven integrations

---

## 5. Infrastructure & DevOps Personas

### 5.1 Infrastructure Engineers

**Description**: Engineers who manage the underlying cloud and Kubernetes infrastructure.

**Key Responsibilities**:

- Kubernetes cluster provisioning and management
- Network configuration and security
- Storage and persistence layer management
- Infrastructure monitoring and capacity planning

**Infrastructure Components**:

- **Kubernetes** - Container orchestration
- **Istio Ambient Mesh** - Service mesh for security and observability
- **Gateway API** - Ingress and traffic management
- **Cert Manager** - TLS certificate management

### 5.2 Site Reliability Engineers (SREs)

**Description**: Engineers focused on platform reliability, performance, and scalability.

**Key Responsibilities**:

- Service level objective (SLO) definition and monitoring
- Incident response and resolution
- Performance optimization
- Capacity planning and auto-scaling

**Monitoring Tools**:

- **Kiali** - Network traffic visualization
- **Phoenix** - Distributed tracing
- **MCP Inspector** - MCP protocol debugging
- **Metrics Server** - Resource utilization monitoring

---

## 6. Specialized Technical Personas

### 6.1 Kubernetes Operator Developers

**Description**: Go developers who build and maintain Kubernetes operators for the Kagenti ecosystem.

**Primary Repository**: [kagenti-operator](https://github.com/kagenti/kagenti-operator)

**Key Responsibilities**:

- Develop and maintain the kagenti-platform-operator
- Create custom resource definitions (CRDs) for agents and components
- Implement controller logic for agent/tool lifecycle management
- Build operator extensions and integrations
- Manage operator versioning and releases

**Technical Skills**:

- Go programming language
- Kubernetes operator framework (controller-runtime)
- Custom Resource Definition (CRD) design
- Controller pattern and reconciliation loops
- Kubernetes API and client libraries
- Helm chart development and OCI registry management

**CRDs Managed**:

- `agents.kagenti.operator.dev/v1alpha1`
- `components.kagenti.operator.dev/v1alpha1`
- `mcpservers.mcp.kagenti.com/v1alpha1`

**Tools Used**:

- Kubernetes operator SDK
- Go development environment
- OCI registry tools (`ghcr.io/kagenti/kagenti-operator`)
- Helm chart packaging and distribution

### 6.2 Protocol Specialists

**Description**: Engineers who work on communication protocols and integration standards.

**Primary Repositories**:

- [mcp-gateway](https://github.com/kagenti/mcp-gateway) - MCP protocol implementation
- [agent-examples](https://github.com/kagenti/agent-examples) - A2A protocol examples

**Protocol Expertise**:

- **Model Context Protocol (MCP)** - Tool-side communication standard
- **Agent-to-Agent (A2A)** - Agent-side communication protocol
- **SPIFFE/SPIRE** - Workload identity and attestation
- **OAuth2 Token Exchange** - Secure delegation patterns

**Key Activities**:

- Design and implement protocol bridges and gateways
- Create protocol adapters for different frameworks
- Develop authentication and authorization flows
- Build protocol debugging and inspection tools
- Ensure protocol security and compliance

---

## 7. Content Creator Personas

**Description**: Technical writers and content creators who produce educational and promotional materials.

**Content Types**:

- Blog posts on [Kagenti Medium publication](https://medium.com/kagenti-the-agentic-platform)
- Video tutorials and demos
- Webinar content and presentations
- Case studies and success stories
- Community newsletter content

**Topics Covered**:

- Cloud-native AI agent development
- Security best practices in agentic platforms
- Multi-framework agent deployment strategies
- Zero-trust architecture implementation

---

## Extended Role-Based Access Control (RBAC) Matrix

| Persona | Keycloak Admin | Agent Deploy | Tool Deploy | UI Access | API Access | Infrastructure | Gateway Config | Operator CRDs | Extensions |
|---------|---------------|--------------|-------------|-----------|------------|----------------|---------------|---------------|------------|
| Security Admin | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Platform Engineer | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Agent Developer | ❌ | ✅ | ❌ | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ |
| Tool Developer | ❌ | ❌ | ✅ | ✅ | ✅ | ❌ | ✅ | ❌ | ❌ |
| Extension Developer | ❌ | ❌ | ❌ | ✅ | ✅ | ❌ | ❌ | ✅ | ✅ |
| Gateway Administrator | ❌ | ❌ | ❌ | ✅ | ✅ | ✅ | ✅ | ❌ | ❌ |
| Operator Developer | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ | ✅ | ✅ |
| Protocol Specialist | ❌ | ❌ | ❌ | ✅ | ✅ | ❌ | ✅ | ✅ | ✅ |
| End User | ❌ | ❌ | ❌ | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ |
| Platform Operator | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ |

---

## Getting Started by Persona and Repository

### For Agent Developers ([agent-examples](https://github.com/kagenti/agent-examples))

1. Clone the agent-examples repository
2. Explore framework-specific examples (`a2a/slack_researcher`, `a2a/weather_service`)
3. Use sample Dockerfiles and configurations as templates
4. Access Kagenti UI at `http://kagenti-ui.localtest.me:8080`
5. Navigate to "Import New Agent" and deploy using your GitHub repository
6. Configure framework-specific environment variables
7. Test agent interactions with sample MCP tools

### For Tool Developers ([agent-examples](https://github.com/kagenti/agent-examples))

1. Study MCP tool examples (`mcp/slack_tool`, `mcp/weather_tool`, `mcp/github_tool`)
2. Implement your tool following MCP protocol standards
3. Create appropriate Dockerfile and configuration files
4. Access "Import New Tool" in Kagenti UI
5. Configure MCP protocol settings and authentication
6. Register tool with MCP Gateway for discovery
7. Test tool integration with sample agents

### For Platform Engineers ([kagenti](https://github.com/kagenti/kagenti))

1. Install Kagenti using: `uv run kagenti-installer`
2. Configure cluster with components: `--skip-install keycloak --skip-install spire --skip-install mcp_gateway` as needed
3. Set up monitoring and observability (Kiali, Phoenix, MCP Inspector)
4. Enable agent and tool namespaces with proper labels
5. Configure MCP Gateway routing and HTTPRoute resources
6. Deploy kagenti-operator for CRD management

### For Gateway Administrators ([mcp-gateway](https://github.com/kagenti/mcp-gateway))

1. Understand Envoy-based gateway architecture
2. Configure HTTPRoute resources for tool registration
3. Set up MCPServer custom resources
4. Monitor gateway performance and scaling
5. Troubleshoot protocol routing issues
6. Manage gateway security and access control

### For Operator Developers ([kagenti-operator](https://github.com/kagenti/kagenti-operator))

1. Clone the kagenti-operator repository
2. Set up Go development environment
3. Study existing CRDs and controller implementations
4. Develop custom operators using controller-runtime
5. Test operators with sample agents and tools
6. Package operators as OCI Helm charts
7. Publish to `ghcr.io/kagenti/kagenti-operator` registry

### For Extension Developers ([kagenti-extensions](https://github.com/kagenti/kagenti-extensions))

1. Clone the kagenti-extensions repository
2. Study existing extension patterns and APIs
3. Develop extensions using Go or appropriate languages
4. Create custom CRDs or UI components as needed
5. Test extensions with main platform
6. Submit contributions via pull requests

### For End Users

1. Login with provided credentials (admin/admin or demo users)
2. Navigate to "Agent Catalog" to see deployed agents
3. Use "Tool Catalog" to explore available tools
4. Access "Observability" for monitoring and debugging
5. Try "Admin" section for identity management
6. Interact with agents using natural language prompts

### For Security Administrators

1. Access Keycloak Admin Console at `http://keycloak.localtest.me:8080`
2. Configure users, roles, and client scopes for different access levels
3. Set up SPIFFE/SPIRE identity management and attestation
4. Implement token exchange policies for secure delegation
5. Monitor security events and compliance across all repositories
6. Manage zero-trust architecture policies and enforcement

---

## Repository-Specific Persona Mapping

| Repository | Primary Personas | Secondary Personas |
|------------|------------------|-------------------|
| **kagenti** (main) | Platform Engineers, Platform Operators, End Users | Security Administrators, Technical Support |
| **agent-examples** | Agent Developers, Tool Developers | Integration Engineers, Protocol Specialists |
| **mcp-gateway** | Gateway Administrators, Protocol Specialists | Platform Engineers, Network Engineers |
| **kagenti-operator** | Operator Developers, Platform Operators | Kubernetes Engineers, Infrastructure Engineers |
| **kagenti-extensions** | Extension Developers, Integration Engineers | Solution Architects, Platform Engineers |
| **.github** | Website Developers, Community Managers | Content Creators, Documentation Engineers |

---

## Conclusion

The Kagenti ecosystem serves a comprehensive multi-repository platform supporting **20+ distinct personas** across six specialized repositories. From technical developers working with [agent-examples](https://github.com/kagenti/agent-examples) to operators managing the [kagenti-operator](https://github.com/kagenti/kagenti-operator), from gateway administrators configuring [mcp-gateway](https://github.com/kagenti/mcp-gateway) to community managers maintaining the [.github](https://github.com/kagenti/.github) repository.

Each repository serves specific personas with dedicated tools, skills, and responsibilities:

- **Development-Focused**: agent-examples, kagenti-extensions
- **Operations-Focused**: kagenti, kagenti-operator, mcp-gateway  
- **Community-Focused**: .github

The platform's strength lies in its ability to serve both technical and non-technical users while maintaining enterprise-grade security and compliance standards through its zero-trust identity model, comprehensive role-based access controls, and modular architecture that spans multiple specialized repositories.

This multi-repository approach enables:

- **Specialized Expertise**: Each repository attracts domain experts
- **Modular Development**: Teams can work independently on different components
- **Community Growth**: Different entry points for various skill levels
- **Enterprise Adoption**: Clear separation of concerns for security and compliance
- **Framework Neutrality**: Support for diverse AI agent frameworks and tools
