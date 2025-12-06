# Kagenti Documentation

This directory contains the official Kagenti project documentation. 

## Getting Started

If you are new to Kagenti, we recommend the following flow to get started with a local Kind cluster. 

1. [Installation Guide](./kind-install.md): Step-by-step instructions to start a Kind cluster and install all prerequisite components
2. [Quickstart Weather Agent](./demo-weather-agent.md): Deploy your first agent. 

Kagenti is built on existing open-source cloud-native technologies. 

- [Architecture Overview](./tech-details.md) gives a high-level look at the existing technologies. 

## Additional Demos

We are developing other demos:

- [Github Issue Agent Demo](./demo-github-issue.md): See this demo to run an agent that can query Github Issues using Github's remote MCP Server. 
  - [Interactive Online Demo](https://red.ht/3WL5Loc): See this demo presented at KubeCon NA 2025 to see the Github Issue example without running it locally. 
- [Slack Authentication Demo](./demo-slack-research-agent.md): See this demo to deploy an agent and a simple MCP Server tool to talk to the Slack API. 
- [Generic Agent Demo](./demo-generic-agent.md): See this demo to deploy a generic agent and a two MCP Server tools.


## Core Concepts

Through this incubation project, we have identified several core components: 

- [MCP Gateway](./gateway.md) offers a quickstart to using the MCP Gateway. You may also find more information in [our mcp-gateway repo](https://github.com/kagenti/mcp-gateway).
- [Identity and Security](./demo-identity.md) provides deeper overview on the various security tools that help implement zero-trust security from the platform level. 

## Develop with Kagenti

This repo provides a UI to interface with the operator and deployed agents and tools. 

- [Developer's Guide](./dev-guide.md) provides instructions to get started contributing to the Kagenti UI
- [Import your own agent](./new-agent.md) provides instructions to import your own agent via the UI. 

## Community

For additional queries, join [our Discord](https://discord.gg/aJ92dNDzqB). 

If you would like to contribute, feel free to submit a pull request! Please see our [CONTRIBUTING guidelines](../CONTRIBUTING.md). 
