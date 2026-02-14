# Approach B: Minimal Agent Boilerplate + OTEL Collector Enrichment

**Issue:** #667
**Goal:** Reduce agent observability code from ~551 lines (PR 114 baseline) to ~50 lines by having the OTEL Collector handle attribute enrichment.

## Overview

The OTEL Collector **cannot create new spans** -- it can only modify existing ones. Therefore the agent must still create a root span. But we can minimize the agent's responsibility to the absolute essentials:

1. Agent creates a named root span (`invoke_agent {agent_name}`) with standard OTEL SDK
2. Agent sets attributes that only it can provide: `input.value`, `output.value`, `gen_ai.conversation.id`, `gen_ai.agent.name`, `gen_ai.operation.name`
3. Agent enables LangChain and OpenAI auto-instrumentation (one line each)
4. OTEL Collector `transform/agent_enrichment` processor derives **all** MLflow, OpenInference, and additional GenAI attributes from the above

## Architecture

```
+---------------------------------------------+
| Agent Pod                                    |
|                                              |
|  +-------------------------------------------+
|  | Agent Code                                |
|  |                                           |
|  | # Minimal boilerplate (~50 lines):        |
|  | - TracerProvider + OTLP exporter           |
|  | - Root span middleware (input/output)      |
|  | - gen_ai.agent.name, gen_ai.operation.name |
|  | - gen_ai.conversation.id                   |
|  |                                           |
|  | # Auto-instrumentation (existing):        |
|  | - LangChainInstrumentor()                 |
|  | - OpenAIInstrumentor() (optional)         |
|  +--------------------+----------------------+
|                       |
+-----------------------|-----------------------+
                        | OTLP spans
                        v
             +----------------------+
             | OTEL Collector       |
             |                      |
             | transform/           |
             |  agent_enrichment:   |
             | - mlflow.spanInputs  |
             | - mlflow.spanOutputs |
             | - mlflow.traceName   |
             | - mlflow.spanType    |
             | - mlflow.source      |
             | - mlflow.version     |
             | - mlflow.runName     |
             | - mlflow.user        |
             | - mlflow.trace.*     |
             | - openinference.*    |
             | - llm.model_name     |
             | - llm.token_count.*  |
             |                      |
             | +------+ +--------+ |
             | |Phoenix| | MLflow | |
             | +------+ +--------+ |
             +----------------------+
```

## How the Minimal Agent Module Works

The reference implementation is in `kagenti/examples/agents/observability_minimal.py`. It provides three functions:

### `setup_tracing(service_name, service_version)`

Standard OTEL boilerplate: creates a `TracerProvider` with a `Resource` (setting `service.name` and `service.version`), attaches a `BatchSpanProcessor` with an `OTLPSpanExporter`, and sets the global tracer provider. The OTLP endpoint is configured via the standard `OTEL_EXPORTER_OTLP_ENDPOINT` environment variable.

### `setup_auto_instrumentation()`

Enables LangChain and OpenAI auto-instrumentation via their respective instrumentors. These generate child spans for LLM calls, tool invocations, and chain steps automatically -- no agent code needed.

### `create_tracing_middleware(agent_name)`

Returns a Starlette/FastAPI HTTP middleware that:

1. Skips health and metadata endpoints (`/health`, `/ready`, `/.well-known/agent-card.json`)
2. Parses the A2A JSON-RPC request body to extract user input text and `contextId`
3. Creates a root span named `invoke_agent {agent_name}`
4. Sets five attributes on the span:
   - `gen_ai.agent.name` -- the agent's name (hardcoded per agent)
   - `gen_ai.operation.name` -- always `"invoke_agent"`
   - `input.value` -- user's input text (truncated to 4096 chars)
   - `gen_ai.conversation.id` -- the A2A contextId for session tracking
   - `output.value` -- agent's response text (non-streaming only, truncated to 4096 chars)
5. All LangChain/OpenAI auto-instrumented spans become children of this root span

That is it. No `mlflow.*` attributes, no `openinference.span.kind`, no `mlflow.user` -- the collector handles those.

## What the OTEL Collector Transform Does

The `transform/agent_enrichment` processor (defined in the collector ConfigMap and also shown standalone in `kagenti/examples/agents/otel-collector-agent-enrichment.yaml`) uses OTTL to enrich spans:

### Root span detection

Root spans are detected by span name pattern: `IsMatch(name, "^invoke_agent.*")`. This matches spans created by the middleware with the naming convention `invoke_agent {agent_name}`.

### MLflow attributes derived

| Derived attribute | Source | Condition |
|---|---|---|
| `mlflow.spanInputs` | `input.value` | `input.value != nil` |
| `mlflow.spanOutputs` | `output.value` | `output.value != nil` |
| `mlflow.traceName` | `gen_ai.agent.name` | `gen_ai.agent.name != nil` |
| `mlflow.source` | `resource.attributes["service.name"]` | resource attr exists |
| `mlflow.version` | `resource.attributes["service.version"]` | resource attr exists |
| `mlflow.spanType` | `"AGENT"` (literal) | span name matches `^invoke_agent.*` |
| `mlflow.runName` | `gen_ai.agent.name` + `"-invoke"` | `gen_ai.agent.name != nil` |
| `mlflow.user` | `"kagenti"` (literal) | not already set, root span |
| `mlflow.trace.session` | `gen_ai.conversation.id` | `gen_ai.conversation.id != nil` |

### OpenInference attributes derived

| Derived attribute | Source | Condition |
|---|---|---|
| `openinference.span.kind` | `"AGENT"` (literal) | span name matches `^invoke_agent.*` |

### GenAI to OpenInference conversion (for Phoenix)

| Derived attribute | Source | Condition |
|---|---|---|
| `llm.model_name` | `gen_ai.request.model` | attr exists (LLM child spans) |
| `llm.token_count.prompt` | `gen_ai.usage.input_tokens` | attr exists (LLM child spans) |
| `llm.token_count.completion` | `gen_ai.usage.output_tokens` | attr exists (LLM child spans) |

### Pipeline placement

The processor is placed in both pipelines, before `batch`:

```yaml
traces/phoenix:
  processors: [memory_limiter, filter/phoenix, transform/agent_enrichment, transform/genai_to_openinference, batch]
traces/mlflow:
  processors: [memory_limiter, filter/mlflow, transform/agent_enrichment, batch]
```

## Attribute Responsibility Matrix

| Attribute | Agent sets? | Collector derives? | Notes |
|---|---|---|---|
| `input.value` | Yes | No | Only agent has request body access |
| `output.value` | Yes | No | Only agent has response body access |
| `gen_ai.agent.name` | Yes | No | Hardcoded per agent |
| `gen_ai.operation.name` | Yes | No | Always `"invoke_agent"` |
| `gen_ai.conversation.id` | Yes | No | From A2A contextId |
| `service.name` (resource) | Yes | No | Set in TracerProvider resource |
| `service.version` (resource) | Yes | No | Set in TracerProvider resource |
| `mlflow.spanInputs` | No | Yes | Copied from `input.value` |
| `mlflow.spanOutputs` | No | Yes | Copied from `output.value` |
| `mlflow.traceName` | No | Yes | From `gen_ai.agent.name` |
| `mlflow.source` | No | Yes | From resource `service.name` |
| `mlflow.version` | No | Yes | From resource `service.version` |
| `mlflow.spanType` | No | Yes | Literal `"AGENT"` on root spans |
| `mlflow.runName` | No | Yes | `{agent_name}-invoke` |
| `mlflow.user` | No | Yes | Default `"kagenti"` |
| `mlflow.trace.session` | No | Yes | From `gen_ai.conversation.id` |
| `openinference.span.kind` | No | Yes | Literal `"AGENT"` on root spans |
| `llm.model_name` | No | Yes | From `gen_ai.request.model` (auto-instr) |
| `llm.token_count.*` | No | Yes | From `gen_ai.usage.*` (auto-instr) |
| `gen_ai.request.model` | No (auto) | No | LangChain/OpenAI auto-instrumentation |
| `gen_ai.usage.*` | No (auto) | No | LangChain/OpenAI auto-instrumentation |

## Comparison: Baseline (PR 114) vs Minimal (This Approach)

| Aspect | PR 114 (Baseline) | Approach B (Minimal) |
|---|---|---|
| **Agent observability code** | ~551 lines | ~50 lines |
| **MLflow-specific knowledge in agent** | Yes (all `mlflow.*` attrs) | No (collector handles) |
| **OpenInference knowledge in agent** | Yes (`openinference.span.kind`) | No (collector handles) |
| **Output capture** | Yes (full middleware) | Yes (simple middleware) |
| **Session tracking** | Yes | Yes |
| **Token usage tracking** | Yes (auto-instrumentation) | Yes (auto-instrumentation) |
| **Tool call spans** | Yes (auto-instrumentation) | Yes (auto-instrumentation) |
| **Centralized attribute config** | No (each agent hardcodes) | Yes (collector config) |
| **Adding new backend attrs** | Redeploy all agents | Update collector config only |
| **Agent metadata source** | Hardcoded in agent | Resource attrs + env vars |
| **Root span detection** | N/A (agent sets all attrs) | `IsMatch(name, "^invoke_agent.*")` |

## Limitations

### What the collector cannot do

1. **Cannot create spans** -- the agent MUST create the root span. Auto-instrumentation creates LLM/tool child spans.

2. **Cannot copy attributes between spans** -- each span is processed independently. For example, copying token counts from LLM child spans to the root span is not possible in the transform processor.

3. **Cannot access HTTP request/response bodies** -- the agent middleware must parse A2A JSON-RPC and set `input.value` and `output.value`.

### What the agent must still do

1. Create a named root span (`invoke_agent {agent_name}`)
2. Parse A2A request body for user input text
3. Set `input.value`, `output.value`, `gen_ai.agent.name`, `gen_ai.operation.name`, and `gen_ai.conversation.id`
4. Initialize TracerProvider with resource attributes (`service.name`, `service.version`)
5. Enable auto-instrumentation for LangChain/OpenAI

### Streaming responses

For streaming (SSE) responses, capturing `output.value` on the root span is not straightforward because the response body is not available as a single value. Options:
- Accept missing output for streaming responses (root span still has `input.value`)
- Implement buffered output capture in the agent middleware (adds complexity)
- Post-process in the observability backend

## Files

| File | Purpose |
|---|---|
| `kagenti/examples/agents/observability_minimal.py` | Reference implementation (~50 lines) for agent developers |
| `kagenti/examples/agents/otel-collector-agent-enrichment.yaml` | Standalone collector transform config (for reference/testing) |
| `charts/kagenti-deps/templates/otel-collector.yaml` | Deployed collector config with `transform/agent_enrichment` |
| `docs/design/otel-minimal-agent-collector.md` | This design document |

## Implementation Steps

1. Create minimal agent tracing module (`observability_minimal.py`)
2. Create standalone collector enrichment config (`otel-collector-agent-enrichment.yaml`)
3. Update OTEL Collector Helm template with `transform/agent_enrichment` processor
4. Update both Phoenix and MLflow pipelines to include the new processor
5. Deploy and verify with E2E tests
6. Migrate existing agents from PR 114's `observability.py` to `observability_minimal.py`
