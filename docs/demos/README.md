# Kagenti Demos and Tutorials

The following proof-of-concepts apply Cloud Native technologies to manage agentic workloads. A diagram and description of the demo architecture is provided on the [technical details](../tech-details.md#cloud-native-agent-platform-demo) page.

Detailed overview of the identity concepts are covered in the [Kagenti Identity PDF document](../2025-10.Kagenti-Identity.pdf).

## Demo List

Check the details for running various demos:

- **AuthBridge Demos (with zero-trust security)** - [All AuthBridge demos](https://github.com/kagenti/kagenti-extensions/blob/main/authbridge/demos/README.md) in kagenti-extensions, including:
  - [Weather Agent](https://github.com/kagenti/kagenti-extensions/blob/main/authbridge/demos/weather-agent/demo-ui.md) — Getting-started demo with inbound JWT validation
  - [GitHub Issue Agent](https://github.com/kagenti/kagenti-extensions/blob/main/authbridge/demos/github-issue/demo.md) — Full demo with token exchange and scope-based access control ([demo recording](https://youtu.be/5SpTwERN2jU))
- **Interactive online demo at KubeCon NA 2025**: [Tutorial: Build-a-Bot Workshop: Enabling Trusted Agents With SPIRE + MCP](https://red.ht/3WL5Loc)
- **Identity & Auth Demo** - [Slack Authentication](./demo-slack-research-agent.md): Deploy an agent and MCP Server tool to talk to the Slack API
- **Generic Agent Demo** - [Generic Agent](./demo-generic-agent.md): Deploy a generic agent and two MCP Server tools
- **File Organizer Agent Demo** - [File Organizer Agent](./demo-file-organizer-agent.md): Deploy an agent that can organize files in a cloud storage bucket using a custom MCP Server tool
- **Multimodal Demo** - [Image Agent](./demo-image-agent.md): Deploy an agent and MCP Server tool to return randomly generated images of user-specified sizes.


## Choose Your Demo Based on Your Role

Different demos showcase capabilities relevant to different personas:

- **Agent Developers** → Start with the [Weather Agent with AuthBridge](https://github.com/kagenti/kagenti-extensions/blob/main/authbridge/demos/weather-agent/demo-ui.md) for framework basics with zero-trust security
- **Tool Developers** → Try [Slack Authentication](./demo-slack-research-agent.md) for MCP integration
- **Security Specialists** → Focus on the [GitHub Issue Agent with AuthBridge](https://github.com/kagenti/kagenti-extensions/blob/main/authbridge/demos/github-issue/demo.md) for token exchange and scope-based access control
- **Platform Operators** → All demos showcase operational aspects

**👥 [Find Your Persona](../../PERSONAS_AND_ROLES.md#overview)** to understand which demo best matches your role.

