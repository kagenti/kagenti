# Agent OpenTelemetry Instrumentation Guide

This document describes how to properly instrument AI agents with OpenTelemetry following the GenAI semantic conventions, with specific guidance for MLflow and Phoenix compatibility.

## Overview

Agents emit traces following [OpenTelemetry GenAI Semantic Conventions](https://opentelemetry.io/docs/specs/semconv/gen-ai/). The OTEL Collector transforms these to target-specific formats for:
- **MLflow**: Experiment tracking and trace analysis
- **Phoenix**: LLM observability and debugging

```
Agent (gen_ai.*) → OTEL Collector → Transform → MLflow + Phoenix
```

---

## Span Naming Conventions

### Agent Invocation Span

Per [GenAI Agent Spans Spec](https://opentelemetry.io/docs/specs/semconv/gen-ai/gen-ai-agent-spans/):

| Condition | Span Name Format |
|-----------|------------------|
| Agent name available | `invoke_agent {gen_ai.agent.name}` |
| Agent name unavailable | `invoke_agent` |

**Example:**
```python
# Correct span names:
"invoke_agent weather-assistant"  # When agent name is known
"invoke_agent"                    # Fallback when name unknown
```

**Important:** The `gen_ai.operation.name` attribute MUST be `invoke_agent`.

### Other Operation Spans

| Operation | Span Name | `gen_ai.operation.name` |
|-----------|-----------|-------------------------|
| LLM chat completion | `chat {gen_ai.request.model}` | `chat` |
| Tool execution | `execute_tool {gen_ai.tool.name}` | `execute_tool` |
| Embeddings | `embeddings {gen_ai.request.model}` | `embeddings` |
| Agent creation | `create_agent {gen_ai.agent.name}` | `create_agent` |

---

## Required Attributes

### Agent Span Attributes (invoke_agent)

| Attribute | Type | Requirement | Description |
|-----------|------|-------------|-------------|
| `gen_ai.operation.name` | string | **Required** | Must be `invoke_agent` |
| `gen_ai.provider.name` | string | **Required** | Provider: `langchain`, `crewai`, `openai`, etc. |
| `gen_ai.agent.name` | string | Conditionally Required | Agent identifier |
| `gen_ai.agent.id` | string | Conditionally Required | Unique agent instance ID |
| `gen_ai.conversation.id` | string | Conditionally Required | Session/conversation ID (for multi-turn) |
| `gen_ai.request.model` | string | Conditionally Required | Model name if applicable |
| `error.type` | string | Conditionally Required | Error class (only if operation failed) |

### Recommended Attributes

| Attribute | Type | Description |
|-----------|------|-------------|
| `gen_ai.response.finish_reasons` | string[] | Why generation stopped: `["stop"]`, `["tool_calls"]` |
| `gen_ai.usage.input_tokens` | int | Tokens in prompt |
| `gen_ai.usage.output_tokens` | int | Tokens in response |
| `gen_ai.request.temperature` | double | Sampling temperature |
| `gen_ai.request.max_tokens` | int | Maximum tokens to generate |
| `gen_ai.response.model` | string | Actual model used (may differ from requested) |

### Optional (Opt-In, Sensitive)

| Attribute | Type | Description |
|-----------|------|-------------|
| `gen_ai.input.messages` | any | Full conversation history |
| `gen_ai.output.messages` | any | Model responses |
| `gen_ai.system_instructions` | any | System prompt |
| `gen_ai.tool.definitions` | any | Available tools |

---

## Span Kind

| Scenario | Span Kind |
|----------|-----------|
| Remote agent service (OpenAI Assistants, AWS Bedrock) | `CLIENT` |
| In-process agent (LangChain, CrewAI, custom) | `INTERNAL` |

---

## MLflow-Specific Requirements

MLflow reads specific attributes for its UI columns. These are **in addition to** GenAI conventions.

### MLflow UI Column Mapping

| UI Column | Attribute | Source |
|-----------|-----------|--------|
| Request | `mlflow.spanInputs` | Root span |
| Response | `mlflow.spanOutputs` | Root span |
| Trace Name | `mlflow.traceName` | Root span or trace tag |
| Session | `mlflow.trace.session` | Trace tag (from `gen_ai.conversation.id`) |
| User | `mlflow.user` | Root span |
| Tokens | `mlflow.span.chat_usage` | LLM span (JSON: `{"input_tokens": N, "output_tokens": M}`) |
| Type | `mlflow.spanType` | Span (`AGENT`, `LLM`, `TOOL`, `CHAIN`) |

### MLflow Span Type Values

| `mlflow.spanType` | Use Case |
|-------------------|----------|
| `AGENT` | Agent invocation span |
| `LLM` | Direct LLM call |
| `TOOL` | Tool/function execution |
| `CHAIN` | Chain/workflow step |
| `RETRIEVER` | RAG retrieval |
| `EMBEDDING` | Embedding generation |

### Critical: Root Span Attributes

**MLflow reads `mlflow.spanInputs` and `mlflow.spanOutputs` from the ROOT span only.**

For streaming responses, you must explicitly set these on the root span:

```python
from contextvars import ContextVar

_root_span: ContextVar = ContextVar('root_span', default=None)

def get_root_span():
    return _root_span.get()

# In middleware - store root span
async def middleware(request, call_next):
    with tracer.start_as_current_span("invoke_agent weather-assistant") as span:
        token = _root_span.set(span)
        span.set_attribute("mlflow.spanInputs", user_input)
        try:
            response = await call_next(request)
        finally:
            _root_span.reset(token)

# In agent - set output on root span (NOT current span)
def on_complete(output):
    root_span = get_root_span()
    if root_span:
        root_span.set_attribute("mlflow.spanOutputs", output)
```

---

## Phoenix (OpenInference) Requirements

Phoenix uses [OpenInference semantic conventions](https://github.com/Arize-ai/openinference/blob/main/spec/semantic_conventions.md).

### Required Attributes

| Attribute | Type | Description |
|-----------|------|-------------|
| `openinference.span.kind` | string | **Required**: `AGENT`, `LLM`, `TOOL`, etc. |
| `input.value` | string | Input to the operation |
| `output.value` | string | Output from the operation |

### OpenInference Span Kinds

| Kind | Use Case |
|------|----------|
| `AGENT` | Agent invocation |
| `LLM` | LLM calls |
| `CHAIN` | Chain/workflow |
| `TOOL` | Tool execution |
| `RETRIEVER` | RAG retrieval |
| `EMBEDDING` | Embedding generation |
| `RERANKER` | Document reranking |
| `GUARDRAIL` | Safety checks |

### LLM-Specific Attributes

| Attribute | Type | Description |
|-----------|------|-------------|
| `llm.model_name` | string | Model identifier |
| `llm.system` | string | AI vendor (`openai`, `anthropic`) |
| `llm.provider` | string | Hosting provider if different |
| `llm.token_count.prompt` | int | Input tokens |
| `llm.token_count.completion` | int | Output tokens |
| `llm.input_messages` | indexed | Chat messages (flattened) |
| `llm.output_messages` | indexed | Response messages |

---

## Complete Agent Instrumentation Example

```python
"""
Weather Agent with proper GenAI + MLflow + Phoenix instrumentation.
"""
from contextvars import ContextVar
from opentelemetry import trace
from opentelemetry.trace import SpanKind, Status, StatusCode

# Agent metadata
AGENT_NAME = "weather-assistant"
AGENT_VERSION = "1.0.0"
PROVIDER = "langchain"

# ContextVar for root span access
_root_span: ContextVar = ContextVar('root_span', default=None)

def get_root_span():
    return _root_span.get()


def create_tracing_middleware():
    """Middleware that creates properly named root span."""
    tracer = trace.get_tracer("weather-agent")

    async def middleware(request, call_next):
        # Parse user input from request
        user_input = extract_user_input(request)
        session_id = extract_session_id(request)

        # Create root span with correct naming
        span_name = f"invoke_agent {AGENT_NAME}"

        with tracer.start_as_current_span(
            span_name,
            kind=SpanKind.INTERNAL,  # In-process agent
        ) as span:
            # Store for agent code access
            token = _root_span.set(span)

            try:
                # === GenAI Semantic Conventions (Required) ===
                span.set_attribute("gen_ai.operation.name", "invoke_agent")
                span.set_attribute("gen_ai.provider.name", PROVIDER)
                span.set_attribute("gen_ai.agent.name", AGENT_NAME)

                # === GenAI (Conditionally Required) ===
                if session_id:
                    span.set_attribute("gen_ai.conversation.id", session_id)

                # === MLflow-Specific ===
                if user_input:
                    span.set_attribute("mlflow.spanInputs", user_input[:1000])
                span.set_attribute("mlflow.spanType", "AGENT")
                span.set_attribute("mlflow.traceName", AGENT_NAME)
                span.set_attribute("mlflow.version", AGENT_VERSION)

                # === OpenInference (Phoenix) ===
                span.set_attribute("openinference.span.kind", "AGENT")
                if user_input:
                    span.set_attribute("input.value", user_input[:1000])

                # Call agent handler
                response = await call_next(request)

                span.set_status(Status(StatusCode.OK))
                return response

            except Exception as e:
                span.set_status(Status(StatusCode.ERROR, str(e)))
                span.set_attribute("error.type", type(e).__name__)
                span.record_exception(e)
                raise
            finally:
                _root_span.reset(token)

    return middleware


def set_agent_output(output: str):
    """Set output on root span (call after agent completes)."""
    root_span = get_root_span()
    if root_span and root_span.is_recording():
        truncated = output[:1000]

        # GenAI convention (for general OTEL consumers)
        root_span.set_attribute("gen_ai.completion", truncated)

        # MLflow (Response column)
        root_span.set_attribute("mlflow.spanOutputs", truncated)

        # Phoenix/OpenInference
        root_span.set_attribute("output.value", truncated)
```

---

## OTEL Collector Transforms

The OTEL Collector can transform GenAI attributes to target formats:

```yaml
processors:
  transform/genai_to_mlflow:
    trace_statements:
      - context: span
        statements:
          # Copy gen_ai.conversation.id to mlflow.trace.session
          - set(attributes["mlflow.trace.session"], attributes["gen_ai.conversation.id"])
            where attributes["gen_ai.conversation.id"] != nil

          # Set mlflow.spanType based on operation
          - set(attributes["mlflow.spanType"], "AGENT")
            where attributes["gen_ai.operation.name"] == "invoke_agent"
          - set(attributes["mlflow.spanType"], "LLM")
            where attributes["gen_ai.operation.name"] == "chat"
          - set(attributes["mlflow.spanType"], "TOOL")
            where attributes["gen_ai.operation.name"] == "execute_tool"

  transform/genai_to_openinference:
    trace_statements:
      - context: span
        statements:
          # Map gen_ai.* to OpenInference llm.*
          - set(attributes["llm.model_name"], attributes["gen_ai.request.model"])
          - set(attributes["llm.system"], attributes["gen_ai.provider.name"])
          - set(attributes["llm.token_count.prompt"], attributes["gen_ai.usage.input_tokens"])
          - set(attributes["llm.token_count.completion"], attributes["gen_ai.usage.output_tokens"])
```

---

## Attribute Summary Table

| Purpose | GenAI Attribute | MLflow Attribute | OpenInference Attribute |
|---------|-----------------|------------------|-------------------------|
| Operation type | `gen_ai.operation.name` | `mlflow.spanType` | `openinference.span.kind` |
| Agent name | `gen_ai.agent.name` | `mlflow.traceName` | - |
| Model | `gen_ai.request.model` | - | `llm.model_name` |
| Provider | `gen_ai.provider.name` | - | `llm.system` |
| Session | `gen_ai.conversation.id` | `mlflow.trace.session` | - |
| Input | `gen_ai.prompt` | `mlflow.spanInputs` | `input.value` |
| Output | `gen_ai.completion` | `mlflow.spanOutputs` | `output.value` |
| Input tokens | `gen_ai.usage.input_tokens` | - | `llm.token_count.prompt` |
| Output tokens | `gen_ai.usage.output_tokens` | - | `llm.token_count.completion` |

---

## Testing Requirements

E2E tests should verify:

1. **Span naming**: Root span name matches `invoke_agent {agent_name}` format
2. **Required attributes**: `gen_ai.operation.name`, `gen_ai.provider.name` present
3. **MLflow columns**: `mlflow.spanInputs`, `mlflow.spanOutputs` on root span
4. **Phoenix attributes**: `openinference.span.kind`, `input.value`, `output.value`
5. **Session tracking**: `gen_ai.conversation.id` propagated correctly
6. **Token counts**: Present when LLM returns usage data

---

## References

- [OpenTelemetry GenAI Semantic Conventions](https://opentelemetry.io/docs/specs/semconv/gen-ai/)
- [GenAI Agent Spans Specification](https://opentelemetry.io/docs/specs/semconv/gen-ai/gen-ai-agent-spans/)
- [OpenInference Semantic Conventions](https://github.com/Arize-ai/openinference/blob/main/spec/semantic_conventions.md)
- [MLflow Tracing with OpenTelemetry](https://mlflow.org/docs/latest/genai/tracing/opentelemetry/)
