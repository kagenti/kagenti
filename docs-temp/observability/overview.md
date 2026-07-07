---
sidebar_label: Overview
sidebar_position: 1
---

# Observability Overview

You can't operate what you can't see. Agents are especially opaque — they make decisions and chains of tool calls that are hard to reconstruct after the fact. Rosso instruments the platform so you get traces, metrics, cost, and network topology out of the box.

## What you can see

| Signal | Answers | Page |
|--------|---------|------|
| **Traces** | What did this agent do, step by step? | [Tracing](tracing.md) |
| **Metrics & cost** | How much traffic and token spend, by whom? | [Metrics & cost](metrics-and-cost.md) |
| **Network topology** | How do agents, tools, and services connect? | [Network visualization](network-visualization.md) |

## Built on OpenTelemetry

Rosso emits telemetry using [OpenTelemetry](https://opentelemetry.io/) and the emerging **GenAI semantic conventions** — the standard attributes for LLM and agent spans (model, tokens, tool calls). Because it's standard OTel, you can send it to the backends you already run, not just the ones Rosso ships.

## Ships with

- **MLflow** and **Phoenix** for LLM trace collection and inspection (both optional, OTel-fed).
- **Kiali** for service-mesh topology.
- Token/cost attribution so spend is visible per team and agent.

:::tip Instrument once, view anywhere
Because telemetry is OTel with GenAI conventions, adding your own collector or backend is configuration,
not re-instrumentation.
:::

:::note For contributors
Expand from `kagenti/docs/agents/otel-instrumentation.md`, `mlflow-integration.md`, and
`kiali/README.md`. The `genai:semantic-conventions` skill documents the attribute set.
:::
