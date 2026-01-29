# Kagenti Demos and Tutorials

The following proof-of-concepts apply Cloud Native technologies to manage agentic workloads. A diagram and description of the demo architecture is provided on the [technical details](../tech-details.md#cloud-native-agent-platform-demo) page.

Detailed overview of the identity concepts are covered in the [Kagenti Identity PDF document](../2025-10.Kagenti-Identity.pdf).

## Demo List

Check the details for running various demos:

- **AuthBridge demo - Identity and the new webhook** - [Simple demo showing AuthBridge functionality](https://github.com/kagenti/kagenti-extensions/blob/main/AuthBridge/demo-webhook.md) with the mutating webhook controller
- **Interactive online demo at KubeCon NA 2025**: [Tutorial: Build-a-Bot Workshop: Enabling Trusted Agents With SPIRE + MCP](https://red.ht/3WL5Loc)
- **Simplest Demo** - [Weather Service](./demo-weather-agent.md): Deploy your first agent and tool
- **Identity & Auth Demo** - [Slack Authentication](./demo-slack-research-agent.md): Deploy an agent and MCP Server tool to talk to the Slack API
- **Github Issue Demo** - [Github Issue Agent](./demo-github-issue.md): Run an agent that can query Github Issues using Github's remote MCP Server ([demo recording](https://youtu.be/5SpTwERN2jU))
- **Generic Agent Demo** - [Generic Agent](./demo-generic-agent.md): Deploy a generic agent and two MCP Server tools
- **File Organizer Agent Demo** - [File Organizer Agent](./demo-file-organizer-agent.md): Deploy an agent that can organize files in a cloud storage bucket using a custom MCP Server tool
- **Multimodal Demo** - [Image Agent](./demo-image-agent.md): Deploy an agent and MCP Server tool to return randomly generated images of user-specified sizes. 


## Choose Your Demo Based on Your Role

Different demos showcase capabilities relevant to different personas:

- **Agent Developers** → Start with [Weather Service](./demo-weather-agent.md) for framework basics
- **Tool Developers** → Try [Slack Authentication](./demo-slack-research-agent.md) for MCP integration
- **Security Specialists** → Focus on identity features in [Slack Authentication](./demo-slack-research-agent.md)
- **Platform Operators** → All demos showcase operational aspects

**👥 [Find Your Persona](../../PERSONAS_AND_ROLES.md#overview)** to understand which demo best matches your role.

