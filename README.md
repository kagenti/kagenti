-- testing clear CI run


![Kagenti](banner.png)

**Kagenti** is a Cloud-native middleware providing a *framework-neutral*, *scalable* and *secure* platform for deploying and orchestrating AI agents through a standardized REST API. It includes key services such as:

- Authentication and Authorization
- Trusted identity
- Deployment
- Configuration
- Scaling
- Fault-tolerance
- Checkpointing
- Discovery of agents and tools
- Persistence

## Value Proposition

![License](https://img.shields.io/github/license/kagenti/kagenti)
![Python](https://img.shields.io/pypi/pyversions/kagenti)
![Contributors](https://img.shields.io/github/contributors/kagenti/kagenti)
![Issues](https://img.shields.io/github/issues/kagenti/kagenti)
![Pull Requests](https://img.shields.io/github/issues-pr/kagenti/kagenti)


Despite the extensive variety of frameworks available for developing agent-based applications, there is a distinct lack of standardized methods for deploying and operating agent code in production environments, as well as for exposing it through a standardized API. Agents are adept at reasoning, planning, and interacting with various tools, but their full potential can be limited by these deployment challenges. **Kagenti** addresses this gap by enhancing existing agent frameworks with the following key components:

- **Kubernetes Platform Operator**: Facilitates the deployment and configuration of agents along with infrastructure dependencies on Kubernetes. It enables scaling and updating configurations seamlessly.

- **Agent and Tool Authorization Pattern**: This pattern replaces static credentials with dynamic SPIRE-managed identities, enforcing least privilege and continuous authentication. Secure token exchanges ensure end-to-end security principles enforcement across agentic workflows.

## Multi-Framework Agents

In the open-source community, several frameworks are emerging for developing agent-based applications. These include **LangGraph**, **CrewAI**, **AG2**, **Llama Stack**, and **BeeAI**. The selection of a specific framework is often driven by the use case requirements. For scenarios requiring complex orchestration with a high degree of control over the agent workflow, frameworks like LangGraph are usually a better fit. They allow explicit graph creation where nodes perform LLM model inference and tool calls, with routing that can be either predefined or dynamically influenced by LLM decisions. On the other hand, frameworks such as CrewAI are designed to assign roles and tasks to agents, enabling them to autonomously work towards achieving predefined goals. Llama Stack agents are primarily pre-built state machines focused on ReAct-style patterns. Users configure the system’s prompts, tools, models, and then simply input data and prompts, allowing the agent to execute without the need for backend code development.

**Kagenti** provides a unified platform to deploy, scale, configure, and orchestrate agents created across these various frameworks by supporting APIs based on emerging standards such as  [A2A](https://google.github.io/A2A/#/documentation).

## Kubernetes Operator

Deploying agents in production involves addressing typical challenges associated with managing complex microservices-based applications, including managing infrastructure services such as key-value store databases, caches, queuing systems and deployment, configuration management and scaling of API servers, and workers. The Kubernetes operator facilitates the deployment of new framework instances, supports the registration and scaling of multi-framework agents, and assists in setting up and configuring identity management and agents' authorizations.

## Agent and Tool Authorization Pattern

Kagenti provides a unified framework for identity and authorization in agentic systems, replacing static credentials with dynamic, short‑lived tokens issued through SPIRE and integrated with Keycloak. This approach enforces least‑privilege access, secure delegation, and continuous verification across both human and machine agents. By propagating identity through structured token exchanges, Kagenti ensures that every tool or service invoked by an agent operates under the right permissions without exposing long‑lived secrets.

[The Identity Demo](./docs/demo-identity.md) illustrates these principles in action, showing how agent identities are provisioned, authenticated, and authorized end‑to‑end. It highlights machine identity management, secure delegation via token exchange, and continuous verification at each step of a workflow. Together with the agent and tool authorization pattern, the demo demonstrates Kagenti’s security model—making agent workflows scalable, interoperable, and resilient against evolving threats.

## Components

To achieve the objectives outlined above, we are developing this technology through a series of demos, each targeting specific aspects of our goals. Our aim is to refine these demos into an initial **Minimum Viable Product (MVP)** architecture.

These demos are built on the following core technologies:

- Cloud-native infrastructure including [Kubernetes Gateway API](https://gateway-api.sigs.k8s.io), [Istio Ambient Mesh](https://istio.io/latest/docs/ambient/), and [Kiali](https://kiali.io).
- [Kagenti Operator](https://github.com/kagenti/kagenti-operator/tree/main/platform-operator): an operator for building agents and tools from source, managing their lifecycle, and coordinating platform components.
- Tool-side communication via [Model Context Protocol (MCP)](https://modelcontextprotocol.io)
- Agent-side communication via [A2A](https://google.github.io/A2A)

## Prerequisites

For running the local demos (and the `preload-file` Makefile target) you should have the following tools installed and available in your PATH:

- `kubectl` — used to query the cluster for pods and images.
- `jq` — used to parse and filter JSON output from `kubectl`.

On macOS you can install them with Homebrew, for example:

```
brew install kubectl jq
```

If these tools are missing, the `preload-file` target will now fail with a clear message explaining which tool is absent and how to install it.

---

### Try our demo

We provide a quick way to deploy various relevant open source technologies to set up an agentic platform on your local cluster. This demonstrates how agents, tools, and protocols interoperate to fulfill end-to-end application flows in cloud-native environments.

See the **[Demo Documentation](./docs/demos.md)** for deploying a Cloud-Native Agent Platform with A2A Multi-Framework Agents.

## Blogs

We regularly publish articles at the intersection of cloud-native architecture, AI agents, and platform security.

Some recent posts include:

- [Introducing MCP-Gateway in Kagenti: A Unified Front Door for Your MCP Servers](https://medium.com/kagenti-the-agentic-platform/introducing-mcp-gateway-in-kagenti-a-unified-front-door-for-your-mcp-servers-28db5b6ef62d)
- [Hands-On Introduction to Agentic AI Concepts with Kagenti](https://medium.com/kagenti-the-agentic-platform/hands-on-introduction-to-agentic-ai-concepts-with-kagenti-d70f15aa9051)
- [Toward a Cloud-Native Platform for AI Agents](https://medium.com/kagenti-the-agentic-platform/toward-a-cloud-native-platform-for-ai-agents-70081f15316d)
- [Security in and around MCP](https://medium.com/kagenti-the-agentic-platform/security-in-and-around-mcp-part-1-oauth-in-mcp-3f15fed0dd6e)
- [Identity in Agentic Platforms: Enabling Secure, Least-Privilege Access](https://medium.com/kagenti-the-agentic-platform/identity-in-agentic-platforms-enabling-secure-least-privilege-access-996527f1c983)

Explore more on our [Kagenti Medium publication](https://medium.com/kagenti-the-agentic-platform).

## QR Code for Kagenti.io

This QR Code links to <http://kagenti.io>

![Kagenti.io QR Code](./docs/images/Kagenti.QRcode.png)
