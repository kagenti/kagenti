# Approach B: Minimal Agent Boilerplate + OTEL Collector Enrichment

**Issue:** #667
**Goal:** Minimize agent observability code to ~15 lines, let OTEL Collector handle enrichment.

## Overview

Since the OTEL Collector **cannot create new spans** (only modify existing ones), the agent must create at least one root span. However, we can reduce the agent's responsibility to the absolute minimum:

1. Agent creates a named root span (`invoke_agent {name}`) - ~5 lines
2. Agent sets `input.value` from request body (only agent has this context) - ~3 lines
3. Agent sets `output.value` from response (only agent knows the final answer) - ~3 lines
4. OTEL Collector handles ALL MLflow/OpenInference/GenAI enrichment via transform processor

## Architecture

```
┌─────────────────────────────────────────────┐
│ Agent Pod                                    │
│                                              │
│  ┌─────────────────────────────────────────┐ │
│  │ Agent Code                              │ │
│  │                                         │ │
│  │ # Minimal boilerplate (~15 lines):      │ │
│  │ - TracerProvider + OTLP exporter        │ │
│  │ - Root span middleware                  │ │
│  │ - input/output capture                  │ │
│  │                                         │ │
│  │ # Auto-instrumentation (existing):      │ │
│  │ - LangChainInstrumentor()               │ │
│  │ - OpenAIInstrumentor() (optional)       │ │
│  └────────────────┬────────────────────────┘ │
│                   │                           │
└───────────────────┼───────────────────────────┘
                    │ OTLP spans
                    ▼
         ┌──────────────────────┐
         │ OTEL Collector       │
         │                      │
         │ transform/enrich:    │
         │ - Add mlflow.* attrs │
         │ - Add OI attrs       │
         │ - Set spanType       │
         │ - Map session IDs    │
         │                      │
         │ ┌──────┐ ┌────────┐  │
         │ │Phoenix│ │ MLflow │  │
         │ └──────┘ └────────┘  │
         └──────────────────────┘
```

## What the Agent Needs (Complete Code)

```python
"""
Minimal OTEL observability setup for any Kagenti agent.
This is ALL the observability code an agent needs.
The OTEL Collector handles MLflow/Phoenix attribute enrichment.
"""
import json
import os
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.resources import Resource, SERVICE_NAME
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.propagate import set_global_textmap
from opentelemetry.propagators.composite import CompositePropagator
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator
from opentelemetry.baggage.propagation import W3CBaggagePropagator

# Setup (call once at startup)
def setup_tracing(service_name: str = None):
    service_name = service_name or os.getenv("OTEL_SERVICE_NAME", "agent")
    provider = TracerProvider(resource=Resource({SERVICE_NAME: service_name}))
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
    trace.set_tracer_provider(provider)
    set_global_textmap(CompositePropagator([
        TraceContextTextMapPropagator(),
        W3CBaggagePropagator(),
    ]))

# Auto-instrument frameworks (call once at startup)
def setup_auto_instrumentation():
    try:
        from openinference.instrumentation.langchain import LangChainInstrumentor
        LangChainInstrumentor().instrument()
    except ImportError:
        pass
    try:
        from opentelemetry.instrumentation.openai import OpenAIInstrumentor
        OpenAIInstrumentor().instrument()
    except ImportError:
        pass

# Middleware for root span (add to Starlette/FastAPI app)
def create_tracing_middleware():
    tracer = trace.get_tracer("agent")
    async def middleware(request, call_next):
        # Only trace A2A API calls
        if request.url.path in ["/health", "/ready", "/.well-known/agent-card.json"]:
            return await call_next(request)

        # Parse A2A input
        body = await request.body()
        user_input = ""
        context_id = ""
        try:
            data = json.loads(body)
            parts = data.get("params", {}).get("message", {}).get("parts", [])
            if parts:
                user_input = parts[0].get("text", "")
            context_id = data.get("params", {}).get("contextId", "")
        except Exception:
            pass

        # Create root span with standard naming
        agent_name = os.getenv("AGENT_NAME", "agent")
        with tracer.start_as_current_span(f"invoke_agent {agent_name}") as span:
            # Set minimal attributes that only the agent can provide
            if user_input:
                span.set_attribute("input.value", user_input[:1000])
            if context_id:
                span.set_attribute("gen_ai.conversation.id", context_id)

            response = await call_next(request)

            # Note: output capture requires response body access
            # which is complex with streaming - handled by collector fallback
            return response
    return middleware
```

That's approximately **50 lines** vs the 551 lines in PR 114's observability.py. The agent sets only what it uniquely knows (input text, conversation ID), and the OTEL Collector adds everything else.

## OTEL Collector Transform Configuration

The collector enriches spans with MLflow, OpenInference, and GenAI attributes:

```yaml
processors:
  # Enrich root spans with MLflow attributes
  transform/agent_enrichment:
    trace_statements:
      - context: span
        statements:
          # MLflow attributes (from resource and span attributes)
          - set(attributes["mlflow.spanType"], "AGENT")
            where IsRootSpan() and attributes["mlflow.spanType"] == nil
          - set(attributes["mlflow.traceName"], resource.attributes["service.name"])
            where IsRootSpan() and attributes["mlflow.traceName"] == nil
          - set(attributes["mlflow.source"], resource.attributes["service.name"])
            where IsRootSpan() and attributes["mlflow.source"] == nil
          - set(attributes["mlflow.version"], resource.attributes["service.version"])
            where IsRootSpan() and attributes["mlflow.version"] == nil
          - set(attributes["mlflow.runName"], Concat([resource.attributes["service.name"], "-invoke"], ""))
            where IsRootSpan() and attributes["mlflow.runName"] == nil
          - set(attributes["mlflow.user"], "kagenti")
            where IsRootSpan() and attributes["mlflow.user"] == nil

          # Copy input.value to mlflow.spanInputs (agent sets input.value)
          - set(attributes["mlflow.spanInputs"], attributes["input.value"])
            where IsRootSpan() and attributes["input.value"] != nil and attributes["mlflow.spanInputs"] == nil

          # Copy gen_ai.conversation.id to mlflow.trace.session
          - set(attributes["mlflow.trace.session"], attributes["gen_ai.conversation.id"])
            where attributes["gen_ai.conversation.id"] != nil

          # OpenInference enrichment
          - set(attributes["openinference.span.kind"], "AGENT")
            where IsRootSpan() and attributes["openinference.span.kind"] == nil
          - set(attributes["gen_ai.prompt"], attributes["input.value"])
            where IsRootSpan() and attributes["input.value"] != nil and attributes["gen_ai.prompt"] == nil

          # GenAI agent attributes from resource
          - set(attributes["gen_ai.agent.name"], resource.attributes["service.name"])
            where IsRootSpan() and attributes["gen_ai.agent.name"] == nil
          - set(attributes["gen_ai.operation.name"], "invoke_agent")
            where IsRootSpan() and attributes["gen_ai.operation.name"] == nil
          - set(attributes["gen_ai.provider.name"], "langchain")
            where IsRootSpan() and attributes["gen_ai.provider.name"] == nil

  # Existing GenAI to OpenInference transform for LLM spans
  transform/genai_to_openinference:
    trace_statements:
      - context: span
        statements:
          - set(attributes["llm.model_name"], attributes["gen_ai.request.model"])
            where attributes["gen_ai.request.model"] != nil
          # ... (existing transforms)
```

### Pipeline Configuration

```yaml
service:
  pipelines:
    traces/mlflow:
      receivers: [otlp]
      processors: [memory_limiter, filter/mlflow, transform/agent_enrichment, batch]
      exporters: [debug, otlphttp/mlflow]
    traces/phoenix:
      receivers: [otlp]
      processors: [memory_limiter, filter/phoenix, transform/agent_enrichment, transform/genai_to_openinference, batch]
      exporters: [otlp/phoenix]
```

## Limitations

### What the Collector Cannot Do
1. **Cannot set `mlflow.spanOutputs`** - this requires access to the HTTP response body, which only the agent middleware has. Options:
   - Agent middleware captures output (adds ~10 more lines)
   - Accept that output column is empty in MLflow (informational only)
   - Post-processing in MLflow backend

2. **Cannot copy attributes between spans** - e.g., copying token counts from LLM child spans to root span. Each span is processed independently.

3. **Cannot create spans** - agent MUST create the root span.

### What the Agent Must Still Do
1. Create a named root span (`invoke_agent {name}`)
2. Parse A2A request body for user input
3. Set `input.value` and `gen_ai.conversation.id` on root span
4. Optionally capture output for `output.value` / `mlflow.spanOutputs`

## Trade-offs

**Pros:**
- Agent code reduced from ~551 lines to ~50 lines
- No MLflow-specific knowledge in agent code
- Centralized attribute mapping in OTEL Collector
- Easy to update attribute mappings without agent changes
- `IsRootSpan()` function (OTEL Collector v0.104.0+) enables reliable root span detection

**Cons:**
- Agent still needs ~50 lines of boilerplate (not zero)
- Output capture (`mlflow.spanOutputs`) still requires agent-side code or is missing
- A2A JSON-RPC parsing duplicated (in agent middleware + potentially collector)
- Each agent needs the middleware added to their web framework

## Comparison with Current Approach (PR 114)

| Aspect | PR 114 (Current) | This Approach |
|--------|------------------|---------------|
| Agent code lines | ~551 | ~50 |
| MLflow knowledge in agent | Yes (all attrs) | No (collector handles) |
| Output capture | Yes (middleware) | Partial (needs agent help) |
| Session tracking | Yes | Yes |
| Token usage | Yes (auto-instr) | Yes (auto-instr) |
| Tool spans | Yes (auto-instr) | Yes (auto-instr) |
| Centralized config | No | Yes (collector) |
| Agent metadata source | Hardcoded | Resource attrs + env vars |

## E2E Test Impact

| Test | Expected Result | Notes |
|------|----------------|-------|
| TestWeatherAgentTracesInMLflow | PASS | Root span has service.name from resource |
| TestGenAITracesInMLflow | PASS | Auto-instrumentation unchanged |
| TestMLflowTraceMetadata | PASS | Collector sets all metadata |
| TestSessionTracking | PASS | Agent sets gen_ai.conversation.id |
| TestRootSpanAttributes (MLflow) | PARTIAL | spanOutputs may be missing |
| TestRootSpanAttributes (OpenInference) | PARTIAL | output.value may be missing |
| TestRootSpanAttributes (GenAI) | PASS | conversation.id + agent.name set |
| TestTokenUsageVerification | PASS | Auto-instrumentation handles this |
| TestToolCallSpanAttributes | PASS | Auto-instrumentation handles this |
| TestErrorSpanValidation | PASS | OTEL SDK handles error status |

## Implementation Steps

1. Create minimal agent tracing module (~50 lines)
2. Update weather agent to use minimal module (remove observability.py)
3. Update OTEL Collector config with `transform/agent_enrichment`
4. Verify `IsRootSpan()` works with collector v0.122.1
5. Run MLflow E2E tests
6. Address output capture gap if tests require it
