---
draft: true       # excluded from https://www.rossoctl.dev/
---

# Rossoctl Documentation

This directory contains the official Rossoctl project documentation. 

## Getting Started

If you are new to Rossoctl, we recommend the following flow to get started with a local Kind cluster. 

1. [Installation Guide](./install.md): Step-by-step instructions to start a Kind cluster and install all prerequisite components
2. [Quickstart Weather Agent](https://github.com/rossoctl/cortex/blob/main/authbridge/demos/weather-agent/demo-ui.md): Deploy your first agent with AuthBridge security.

Rossoctl is built on existing open-source cloud-native technologies. 

- [Architecture Overview](./Concepts/tech-details.md) gives a high-level look at the existing technologies. 

## Demos and Tutorials

For a complete list of available demos and tutorials, see the [Demos Documentation](./demos/README.md).
## Vision & Use Cases

- [Use Cases](./user-stories.md) — Platform-wide scenarios organized by persona: deployment, governance, observability, identity, developer experience, and more.
- [Use Case Types](./use-case-types.md) — Taxonomy of agent operational models the platform supports (read-only insight, synchronous task, async task, monitoring, event-driven).
- [Personas and Roles](../PERSONAS_AND_ROLES.md) — The people who use and operate Rossoctl.

## Core Concepts

Through this incubation project, we have identified several core components: 

- [MCP Gateway](./gateway.md) offers a quickstart to using the MCP Gateway. You may also find more information in [our mcp-gateway repo](https://github.com/rossoctl/mcp-gateway).
- [Identity and Security](./identity-guide.md) provides deeper overview on the various security tools that help implement zero-trust security from the platform level. 

## Develop with Rossoctl

This repo provides a UI to interface with the operator and deployed agents and tools.

- [Developer Environment Guides](./developer/README.md) - Setup guides for Kind, HyperShift, and Claude Code workflows
- [Developer's Guide](./dev-guide.md) provides instructions to get started contributing to the Rossoctl UI
- [Import your own agent](./new-agent.md) provides instructions to import your own agent via the UI.
- [Import your own tool](./new-tool.md) provides instructions to import your own MCP tool via the UI.

## Community

For additional queries, join us on [Slack](https://ibm.biz/rossoctl-slack). 

If you would like to contribute, feel free to submit a pull request! Please see our [CONTRIBUTING guidelines](../CONTRIBUTING.md). 
