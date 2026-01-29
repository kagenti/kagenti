# MLflow Integration for LLM Observability

This document describes deploying MLflow alongside Phoenix for LLM trace
collection in Kagenti E2E tests.

## Overview

MLflow Tracing provides LLM observability similar to Phoenix. This integration
allows comparing both tools and validating that weather agent traces are
captured correctly.

## Architecture

```
Weather Agent
    │
    │ OTLP (port 8335)
    ▼
OTEL Collector
    │
    ├──► [filter/phoenix] ──► Phoenix (OpenInference spans only)
    │
    └──► [filter/mlflow] ──► MLflow (GenAI semantic convention spans)
```

## Current State

- Phoenix receives traces via OTEL Collector filter for `openinference.*` scopes
- Weather agent uses OpenInference instrumentation (`openinference-instrumentation-langchain`)
- OTEL Collector filters out non-OpenInference spans before sending to Phoenix

## MLflow Integration Approach

### Option 1: Dual Export (Recommended)

Add MLflow as a second exporter in OTEL Collector:
- Export the same OpenInference spans to both Phoenix and MLflow
- MLflow can ingest OTLP traces directly (since MLflow 2.14+)

### Option 2: GenAI Auto-Instrumentation + Transform

1. Add OpenTelemetry GenAI auto-instrumentation to weather agent
2. Use OTEL Collector transform processor to convert GenAI spans to OpenInference
3. Export to both Phoenix and MLflow

## Components to Add

### 1. MLflow Helm Template (`charts/kagenti-deps/templates/mlflow.yaml`)

Deploys MLflow tracking server with:
- PostgreSQL backend (shared with Phoenix or dedicated)
- OTLP receiver endpoint
- UI access via HTTPRoute/Route

### 2. OTEL Collector Pipeline Update

Add MLflow exporter pipeline:
```yaml
exporters:
  otlp/mlflow:
    endpoint: mlflow:4317
    tls:
      insecure: true

pipelines:
  traces/mlflow:
    receivers: [otlp]
    processors: [memory_limiter, batch]
    exporters: [otlp/mlflow]
```

### 3. E2E Test for MLflow Traces

Verify weather agent traces appear in MLflow after E2E tests run.

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `MLFLOW_TRACKING_URI` | MLflow server URL | Auto-detect from cluster |

## Success Criteria

1. MLflow pod running and accessible
2. Weather agent traces visible in MLflow UI
3. E2E test validates traces exist in MLflow

## References

- [MLflow Tracing](https://mlflow.org/docs/latest/llms/tracing/index.html)
- [MLflow OTLP Integration](https://mlflow.org/docs/latest/llms/tracing/tracing-schema.html)
- [OpenInference Spec](https://github.com/Arize-ai/openinference)
