
# Kagenti

[![License](https://img.shields.io/github/license/kagenti/kagenti)](LICENSE)
![Contributors](https://img.shields.io/github/contributors/kagenti/kagenti)
![Issues](https://img.shields.io/github/issues/kagenti/kagenti)
![Pull Requests](https://img.shields.io/github/issues-pr/kagenti/kagenti)

**Kagenti** is a cloud-native middleware providing a *framework-neutral*, *scalable* and *secure* platform for deploying and orchestrating AI agents through a standardized REST API.

| Included Services: |  |
|--------------------|--------|
| - Authentication and Authorization<br>- Trusted identity<br>- Deployment<br>- Configuration<br>- Scaling<br>- Fault-tolerance<br>- Checkpointing<br>- Discovery of agents and tools<br>- Persistence | <img src="banner.png" width="400"/> |

## Architecture

The goal of Kagenti is to provide a pluggable agentic platform blueprint. Key functionalities are currently organized into four key pillars: 
1. Lifecycle Orchestration
2. Networking
3. Security
4. Observability

Under each of these pillars are logical components that support the workload runtime. 

![Kagenti Architecture](./docs/images/kagenti-architecture.drawio.png)

## Core Components

Kagenti provides a set of components and assets that make it easier to manage AI agents and tools and integrate their fine-grained authorization into modern cloud-native environments.

| Component | Description |
|-----------|-------------|
| **[Kagenti UI](./kagenti/ui/)** | Dashboard for deploying agents/tools, interactive testing, and monitoring |
| **[Identity & Auth Bridge](./docs/identity-guide.md)** | Identity pattern assets that capture common authorization scenarios and provide reusable building blocks for implementing consistent authorization across services |
| **[Agent Lifecycle Operator](https://github.com/kagenti/kagenti-extensions/tree/main/kagenti-webhook)** | Kubernetes admission webhook for building agents from source, managing lifecycle, and coordinating platform services |
| **[MCP Gateway](https://github.com/kagenti/mcp-gateway/blob/main/README.md)** | Unified gateway for Model Context Protocol (MCP) servers and tools. It acts as the entry point for policy enforcement, handling requests and routing them through the appropriate authorization patterns |



## Quick Start

### Prerequisites

- Python ≥3.9 with [uv](https://docs.astral.sh/uv/getting-started/installation) installed
- Docker Desktop, Rancher Desktop, or Podman (16GB RAM, 4 cores recommended)
- [Kind](https://kind.sigs.k8s.io), [kubectl](https://kubernetes.io/docs/tasks/tools/), [Helm](https://helm.sh/docs/intro/install/)
- [Ollama](https://ollama.com/download) for local LLM inference

### Install

The Ansible-based Helm installer is now the recommended and default installer for Kagenti. The legacy `kagenti-installer` (the uv-based Kind installer) is deprecated and will be removed in a future release. See [installer/DEPRECATION.md](installer/DEPRECATION.md) for migration notes and timelines.

Quick Install (recommended — Ansible-based):

```bash
# Clone the repository
git clone https://github.com/kagenti/kagenti.git
cd kagenti

# Copy and configure secrets
cp deployments/envs/secret_values.yaml.example deployments/envs/.secret_values.yaml
# Edit deployments/envs/.secret_values.yaml with your values

# Run the Ansible-based installer (default)
deployments/ansible/run-install.sh --env dev
```

For local Kind development the legacy `kagenti-installer` remains available but is deprecated:

```bash
# Configure environment for legacy installer (deprecated)
cp kagenti/installer/app/.env_template kagenti/installer/app/.env
# Edit .env with your GITHUB_USER, GITHUB_TOKEN, and optionally OPENAI_API_KEY
cd kagenti/installer
uv run kagenti-installer
```

Use `deployments/ansible/run-install.sh --help` (recommended) or `uv run kagenti-installer --help` (deprecated) for options. For more detailed installation instructions including OpenShift refer to [Installation Guide](./docs/install.md).

### Access the UI

```bash
open http://kagenti-ui.localtest.me:8080
# Login: admin / admin
```

From the UI you can:
- Import and deploy A2A agents from any framework
- Deploy MCP tools directly from source
- Test agents interactively
- Monitor traces and network traffic

## Documentation

| Topic | Link |
|-------|------|
| **Installation** | [Installation Guide](./docs/install.md) (Kind & OpenShift) |
| **Components** | [Component Details](./docs/components.md) |
| **Demos & Tutorials** | [Demo Documentation](./docs/demos/README.md) |
| **Import Your Own Agent** | [New Agent Guide](./docs/new-agent.md) |
| **Architecture Details** | [Technical Details](./docs/tech-details.md) |
| **Identity, Security, and Auth Bridge** | [Identity and Auth Bridge](./docs/identity-guide.md) |
| **Developer Guide** | [Contributing](./docs/dev-guide.md) |
| **Troubleshooting** | [Troubleshooting Guide](./docs/troubleshooting.md) |
| **Blog Posts** | [Kagenti Blog](./docs/blogs.md) |

## Supported Protocols

- **[A2A (Agent-to-Agent)](https://google.github.io/A2A)** — Standard protocol for agent communication
- **[MCP (Model Context Protocol)](https://modelcontextprotocol.io)** — Protocol for tool/server integration

## Contributing

We welcome contributions! See [CONTRIBUTING.md](./CONTRIBUTING.md) for guidelines.

## License

[Apache 2.0](./LICENSE)

## QR Code for Kagenti.io

This QR Code links to <http://kagenti.io>

![Kagenti.io QR Code](./docs/images/Kagenti.QRcode.png)
