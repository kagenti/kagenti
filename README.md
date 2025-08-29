
![Kagenti](banner.png)

**Kagenti** is a Cloud-native middleware providing a *framework-neutral*, *scalable* and *secure* platform for deploying and orchestrating AI agents through a standardized REST API. It includes key services such as:

- Trusted identity
- Deployment
- Configuration
- Scaling
- Fault-tolerance
- Checkpointing
- Discovery of agents and tools
- Persistence

## Value Proposition

Despite the extensive variety of frameworks available for developing agent-based applications, there is a distinct lack of standardized methods for deploying and operating agent code in production environments, as well as for exposing it through a standardized API. Agents are adept at reasoning, planning, and interacting with various tools, but their full potential can be limited by these deployment challenges. **Kagenti** addresses this gap by enhancing existing agent frameworks with the following key components:

- **Kubernetes Platform Operator**: Facilitates the deployment and configuration of agents along with infrastructure dependencies on Kubernetes. It enables scaling and updating configurations seamlessly.

- **Agent and Tool Authorization Pattern**: This pattern replaces static credentials with dynamic SPIRE-managed identities, enforcing least privilege and continuous authentication. Secure token exchanges ensure end-to-end security principles enforcement across agentic workflows.

## Multi-Framework Agents

In the open-source community, several frameworks are emerging for developing agent-based applications. These include **LangGraph**, **CrewAI**, **AG2**, **Llama Stack**, and **BeeAI**. The selection of a specific framework is often driven by the use case requirements. For scenarios requiring complex orchestration with a high degree of control over the agent workflow, frameworks like LangGraph are usually a better fit. They allow explicit graph creation where nodes perform LLM model inference and tool calls, with routing that can be either predefined or dynamically influenced by LLM decisions. On the other hand, frameworks such as CrewAI are designed to assign roles and tasks to agents, enabling them to autonomously work towards achieving predefined goals. Llama Stack agents are primarily pre-built state machines focused on ReAct-style patterns. Users configure the system’s prompts, tools, models, and then simply input data and prompts, allowing the agent to execute without the need for backend code development.

**Kagenti** provides a unified platform to deploy, scale, configure, and orchestrate agents created across these various frameworks by supporting APIs based on emerging standards such as [ACP](https://agentcommunicationprotocol.dev) and [A2A](https://google.github.io/A2A/#/documentation).

## Kubernetes Operator

Deploying agents in production involves addressing typical challenges associated with managing complex microservices-based applications, including managing infrastructure services such as key-value store databases, caches, queuing systems and deployment, configuration management and scaling of API servers, and workers. The Kubernetes operator facilitates the deployment of new framework instances, supports the registration and scaling of multi-framework agents, and assists in setting up and configuring identity management and agents' authorizations.

## Agent and Tool Authorization Pattern

The Agent and Tool Authorization Pattern for the Agentic Platform ensures that both human and machine identities are continuously authenticated and authorized, minimizing implicit trust at every stage of interaction. Traditional static credentials, such as API keys or client secrets, risk privilege escalation and credential leaks, and therefore are replaced with dynamic, short-lived identity-based tokens, managed through SPIRE and integrated with Keycloak for access control.

This approach enforces least privilege access by ensuring that identities — whether users, tools, or external services — only receive the minimum permissions necessary. The authentication and authorization flow follows a structured token exchange mechanism, where a user's identity propagates securely through the system, from initial authentication to tool interactions and external service access. By leveraging SPIFFE/SPIRE for workload identity and OAuth2 transaction tokens for controlled delegation, the platform prevents credential misuse, reduces attack surfaces, and ensures real-time policy enforcement.

In practice, the Authorization Pattern within the Agentic Platform enables:

- Machine Identity Management – replacing static credentials with SPIRE-issued JWTs.
- Secure Delegation – enforcing token exchange to propagate identity across services without excessive permissions.
- Continuous Verification – ensuring authentication and authorization at each step, preventing privilege escalation.

This end-to-end approach aligns agentic workflows with security best practice principles, making them secure, scalable, and eventually production-ready.

## Components

To achieve the objectives outlined above, we are developing this technology through a series of demos, each targeting specific aspects of our goals. Our aim is to refine these demos into an initial **Minimum Viable Product (MVP)** architecture.

These demos are built on the following core technologies:

- Cloud-native infrastructure including [Kubernetes Gateway API](https://gateway-api.sigs.k8s.io), [Istio Ambient Mesh](https://istio.io/latest/docs/ambient/), and [Kiali](https://kiali.io).
- [Kagenti Operator](https://github.com/kagenti/kagenti-operator/blob/main/platform-operator/INSTALL.md): an operator for building agents and tools from source, managing their lifecycle, and coordinating platform components.
- Tool-side communication via [Model Context Protocol (MCP)](https://modelcontextprotocol.io)
- Agent-side communication via [A2A](https://google.github.io/A2A) and [Agent Communication Protocol (ACP)](https://agentcommunicationprotocol.dev/introduction/welcome)

---

### Try our demo

We provide a quick way to deploy various relevant open source technologies to set up an agentic platform on your local cluster. This demonstrates how agents, tools, and protocols interoperate to fulfill end-to-end application flows in cloud-native environments.

See the [documentation](./docs/demos.md) here for deploying a Cloud-Native Agent Platform with A2A and ACP Multi-Framework Agents.

---

### Legacy and Reference Demos

The following demos were developed during earlier phases of the Kagenti project. While no longer actively supported, they remain available for reference or to demonstrate specific functionalities:

- [Llama Stack Demos – Installation Guide](./docs/demos-llama-stack.md#installation)
- [API Key Propagation from LS Client to MCP Tool Server](./docs/demos-llama-stack.md#api-key-propagation-from-ls-client-to-mcp-tool-server)
- [Agent-as-Tool Demo (LLM Agent as MCP Tool)](./docs/demos-llama-stack.md#agent-as-tool)
- [Identity and Token Exchange Workflows](./kagenti/examples/identity/)
- [Keycloak Client Registration](./kagenti/examples/identity/kagenti_client_registration)

## Blogs

We regularly publish articles at the intersection of cloud-native architecture, AI agents, and platform security.

Some recent posts include:

- [Toward a Cloud-Native Platform for AI Agents](https://medium.com/kagenti-the-agentic-platform/toward-a-cloud-native-platform-for-ai-agents-70081f15316d)
- [Security in and around MCP](https://medium.com/kagenti-the-agentic-platform/security-in-and-around-mcp-part-1-oauth-in-mcp-3f15fed0dd6e)
- [Identity in Agentic Platforms: Enabling Secure, Least-Privilege Access](https://medium.com/kagenti-the-agentic-platform/identity-in-agentic-platforms-enabling-secure-least-privilege-access-996527f1c983)

Explore more on our [Kagenti Medium publication](https://medium.com/kagenti-the-agentic-platform).
