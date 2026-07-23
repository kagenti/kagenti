---
sidebar_label: Tracing
sidebar_position: 2
---

:::danger Placeholder content
This content is placeholder and should be replaced, edited, or deleted by the content owners.
:::

# Tracing

A trace is the single most useful artifact for understanding an agent: it shows the full sequence of reasoning steps, model calls, and tool invocations behind one request. Rossoctl captures traces automatically using OpenTelemetry, and gives you MLflow and Phoenix to explore them.

## What a trace captures

- The **prompt and completion** for each model call (with token counts).
- Each **tool call** the agent made, its arguments, and its result.
- **Timing and nesting** — which step led to which, and how long each took.
- The **user and agent identity** behind the request.

## Explore traces

Rossoctl can run **MLflow** and **Phoenix** in-cluster; both consume the same OpenTelemetry data:

```bash
rossoctl install --local --with-observability
rossoctl ui open --view traces
```

- **Phoenix** is well suited to inspecting individual LLM/agent traces and debugging behavior.
- **MLflow** is useful for tracking runs and comparing over time.

## Send to your own backend

Because agents emit standard OTel with GenAI semantic conventions, point the collector at your existing tracing backend (Jaeger, Tempo, a vendor) instead of — or in addition to — the bundled tools.

```yaml
# OpenTelemetry Collector exporter (illustrative)
exporters:
  otlp:
    endpoint: my-otel-backend.observability.svc:4317
```

:::tip Trace-driven debugging
When an agent does something surprising, open its trace first. The step-by-step view usually shows the
exact tool call or prompt that sent it off course.
:::

:::note For contributors
Confirm the GenAI attribute set and MLflow/Phoenix wiring against `kagenti/docs/agents/otel-instrumentation.md`
and `mlflow-integration.md`. Replace the `--view traces` command with the real UI path.
:::
