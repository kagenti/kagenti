---
title: Concepts
sidebar_label: Core and experiments
description: How Rossoctl works, and which features are ready for production use.
sidebar_position: 1
---

This section explains how Rossoctl works. It has two parts.

**Core** describes the parts that every Rossoctl installation uses. These parts are ready for
production use. Read them in the order that the sidebar shows.

**Experiments** describes features that are not yet ready for production use. Each experiment page
gives the status of the feature and tells you how to enable it. You can ignore this group. A Rossoctl
installation without any experiment is complete and supported.

The split follows the [Rossoctl organization](https://github.com/rossoctl), which marks each
repository as core or experimental.

## Maturity levels

| Level | What it means |
| --- | --- |
| **Ready** | The feature is on by default. Tests cover it. You can depend on it. |
| **Beta** | The feature works and this site documents it. The configuration can change in a later release. |
| **Alpha** | You can evaluate the feature. The behaviour and the interface will change. Do not depend on it. |

## Core features

| Feature | Status | Page |
| --- | --- | --- |
| Agent identity | Ready | [Identity and trust](core/identity.md) |
| Access control and delegation | Ready | [Identity and trust](core/identity.md) |
| Agent deployment and discovery | Ready | [Control plane](core/control-plane.md) |
| Visibility of each model, tool and API call | Ready | [RossoCortex](core/cortex.md) |
| Traces and network data | Ready | [Observability](../operate/observability.md) |
| Token counts, cost and latency on a laptop | Ready | [Read the numbers](../get-started/reading-the-numbers.md) |

## Experimental features

| Feature | Status | What it does | Page |
| --- | --- | --- | --- |
| MCP Gateway | Beta | Gives every agent one address for all tools. | [MCP Gateway](experiments/mcp-gateway.md) |
| Skills | Beta | Stores reusable instructions that an agent can use. | [Skills](experiments/skills.md) |
| Agent context | Beta | Gives an agent durable storage for files and memory. | [Agent context](experiments/agent-context.md) |
| Sandboxes | Alpha | Isolates an agent more strongly than a pod does. | [Sandboxes](experiments/sandboxes.md) |
| Intent-based access | Alpha | Denies an action that does not match the request of the user. | [Intent-based access](experiments/intent-based-access.md) |
| Tool call validation | Alpha | Denies a tool call that has invented arguments. | [Tool call validation](experiments/tool-validation.md) |
| Context compaction | Alpha | Makes tool output smaller before the model reads it. | [Context compaction](experiments/context-compaction.md) |
| Cost control | Alpha | Removes unused tool definitions and limits spending. | [Cost control](experiments/cost-control.md) |
| AI-based access control | Alpha | Applies organizational access control policy to a running agentic system. | [AI-based access control](experiments/aiac.md) |

Two more experiments exist in the platform but have no page on this site yet. **Failure recovery**
returns a stopped agent to a known state. **Data-flow analysis** records the source of the data that
an agent used. For the current state of both, see the
[cortex repository](https://github.com/rossoctl/cortex).

## Report an error

If a feature does not operate as this page describes, the error is in these documents. Open an issue
on [rossoctl/rossoctl](https://github.com/rossoctl/rossoctl/issues), or write a message in
[Slack](https://ibm.biz/rossoctl-slack).
