---
title: Quickstart
description: Install Rossoctl on a Kubernetes cluster
weight: 5
---

## Prerequisites

- Python ≥3.9 with [uv](https://docs.astral.sh/uv/getting-started/installation) installed
- Docker Desktop, Rancher Desktop, or Podman (16GB RAM, 6 cores recommended)
- A Kubernetes cluster such as [Kind](https://kind.sigs.k8s.io), [kubectl](https://kubernetes.io/docs/tasks/tools/), [Helm](https://helm.sh/docs/intro/install/)
- (optional) [Ollama](https://ollama.com/download) for local LLM inference

### Install

```bash
# Clone the repository
git clone https://github.com/rossoctl/rossoctl.git
cd rossoctl

# Check out the latest stable release (recommended)
# Find the current version at https://github.com/rossoctl/rossoctl/releases/latest.
git checkout v0.7.0-alpha.6

# Copy and configure secrets (optional)
cp deployments/envs/secret_values.yaml.example deployments/envs/.secret_values.yaml
# Edit deployments/envs/.secret_values.yaml with your values

# Deploy to Kubernetes cluster
scripts/kind/setup-rossoctl.sh --with-ui --with-spire --with-agent-sandbox --with-builds
```

> **Tip:** To find the latest stable version from the command line:
> ```bash
> git tag --list 'v*' --sort=-v:refname | grep -v -E '(alpha|rc)' | head -1
> ```

For all available installer options and detailed instructions (including OpenShift), refer to the [Installation Guide](../Getting%20Started/install.md).

### Access the Rossoctl Dashboard

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

To learn how to deploy agents and MCP tools, follow the **[Weather Agent Demo](https://github.com/rossoctl/cortex/blob/main/authbridge/demos/weather-agent/demo-ui.md)** — the recommended getting-started tutorial that walks you through deploying an agent and tool via the UI and chatting with it end-to-end. For more demos, see the [full demo list](/docs/demos/).
